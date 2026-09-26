"""The multi-agent chat: a supervisor and three specialists (LangGraph).

::

    START -> supervisor -> fact_checker   -+
                 ^     -> market_analyst  -+-> supervisor -> ... -> END
                 |     -> brief_writer    -+
                 +-------------------------+

- ``supervisor`` plans once: a structured-output call picks up to 2
  specialists for the question (a keyword router takes over when the model
  gives no valid plan). Then it hands the question to each one in turn and
  ends when none is left.
- Each specialist is a ReAct agent (``langchain.agents.create_agent``) with
  an allowlist of the MCP server's read-only tools, its skills (loaded on
  demand with ``load_skill``) and a budget of tool calls.
- What the specialists found (tool results, never their own words) becomes
  numbered sources; the "Ask the News" writer (``rag.ask``) answers from
  them plus the trusted corpus, and its checks (citations, no advice,
  Llama Guard) apply as before.

The graph streams its progress (``plan``, ``tool``, ``done`` steps) as
custom events, which the chat forwards to the browser as ``step`` events.
One MCP session per question; without the MCP server the specialists are
skipped and the answer comes from the corpus alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import contextlib
import dataclasses
import datetime
import logging
import operator
import re
from typing import Annotated, Any, Literal, TypedDict

from langchain import agents as lc_agents
from langchain_core import language_models
from langchain_core import messages as lc_messages
from langchain_core import tools as lc_tools
from langgraph import config as lg_config
from langgraph import errors as lg_errors
from langgraph import graph as lg
from langgraph import runtime as lg_runtime
import pydantic

from ai_api.agents import prompts
from ai_api.agents import skills as skills_lib
from ai_api.agents import tools as tools_lib
from ai_api.guard import spotlight
from ai_api.llm import tracing

_log = logging.getLogger(__name__)
SERVER = "premarket"
MAX_SPECIALISTS = 2
_MAX_FINDINGS = 5

AgentName = Literal["fact_checker", "market_analyst", "brief_writer"]


@dataclasses.dataclass(frozen=True)
class Specialist:
    """One specialist of the team.

    Attributes:
        name: Its node name.
        title: How the UI names it.
        tools: Its MCP tools (the allowlist).
        skills: The skills it may load.
        prompt: Its system prompt.
    """

    name: str
    title: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    prompt: str


SPECIALISTS: dict[str, Specialist] = {
    s.name: s
    for s in (
        Specialist(
            "fact_checker",
            "Fact-Checker",
            (
                "list_news",
                "get_verification",
                "lookup_company",
                "get_source_reputation",
                "search_news",
                "web_search",
                "fetch_url",
            ),
            ("fact-check-methodology", "source-credibility-rules"),
            prompts.FACT_CHECKER,
        ),
        Specialist(
            "market_analyst",
            "Market Analyst",
            ("get_price_history", "search_news", "lookup_company"),
            (),
            prompts.MARKET_ANALYST,
        ),
        Specialist(
            "brief_writer",
            "Brief Writer",
            ("get_brief",),
            ("premarket-brief-format",),
            prompts.BRIEF_WRITER,
        ),
    )
}

_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "fact_checker",
        re.compile(
            r"\b(fake|flag\w*|verif\w*|verdict|real|true|false|mislead\w*|"
            r"spoof\w*|rumou?r|source|reliab\w*|check\w*|evidence|why)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "market_analyst",
        re.compile(
            r"\b(price|prices|share|shares|stock|stocks|jump\w*|fell|fall\w*|"
            r"drop\w*|rose|rall\w*|move\w*|trad\w*|close\w*|%)",
            re.IGNORECASE,
        ),
    ),
    ("brief_writer", re.compile(r"\bbrief\w*\b", re.IGNORECASE)),
)


class Plan(pydantic.BaseModel):
    """The supervisor's choice of specialists."""

    agents: list[AgentName] = pydantic.Field(
        default_factory=list,
        description="The specialists to ask, most useful first (0 to 2).",
    )
    reason: str = pydantic.Field(
        default="", description="Why, in one short sentence."
    )


def route_by_keywords(question: str) -> list[str]:
    """The fallback plan: specialists whose topic the question mentions."""
    found = [name for name, pattern in _KEYWORDS if pattern.search(question)]
    return found[:MAX_SPECIALISTS]


def clean_plan(names: list[str]) -> list[str]:
    """Known specialists, no repeats, at most ``MAX_SPECIALISTS``."""
    found: list[str] = []
    for name in names:
        if name in SPECIALISTS and name not in found:
            found.append(name)
    return found[:MAX_SPECIALISTS]


@dataclasses.dataclass(frozen=True)
class Step:
    """One progress event of the team (sent to the browser as ``step``).

    Attributes:
        agent: ``supervisor`` or a specialist's name.
        action: ``plan``, ``tool``, ``done`` or ``failed``.
        detail: Plain text for the progress line.
    """

    agent: str
    action: str
    detail: str

    def to_json(self) -> dict[str, str]:
        """The event's data."""
        title = (
            "Supervisor"
            if self.agent == "supervisor"
            else SPECIALISTS[self.agent].title
        )
        return {
            "agent": self.agent,
            "title": title,
            "action": self.action,
            "detail": self.detail[:200],
        }


class State(TypedDict, total=False):
    """The team's state for one question."""

    question: str
    day: str
    tickers: list[str]
    watchlist: list[str]
    plan: list[str] | None
    remaining: list[str]
    findings: Annotated[list[dict[str, Any]], operator.add]


@dataclasses.dataclass
class Context:
    """Per-question objects (not part of the state).

    Attributes:
        tools: The MCP tools by name (empty when the server is down).
        config: The run config (Langfuse callbacks).
    """

    tools: dict[str, lc_tools.BaseTool]
    config: dict[str, Any]


AgentFactory = Callable[..., Any]


def _emit(step: Step) -> None:
    lg_config.get_stream_writer()(step.to_json())


class Supervisor:
    """Runs the team for one question (see the module docstring)."""

    def __init__(
        self,
        model: language_models.BaseChatModel,
        library: skills_lib.Library,
        tracer: tracing.Tracer,
        mcp: Any = None,
        max_tool_calls: int = 3,
        agent_factory: AgentFactory = lc_agents.create_agent,
    ) -> None:
        """Wires the team.

        Args:
            model: The chat model of the supervisor and the specialists
                (tool calling, through the gateway).
            library: The skills.
            tracer: Langfuse configs.
            mcp: A ``MultiServerMCPClient`` with the server ``premarket``;
                None runs without specialists.
            max_tool_calls: Tool calls per specialist at most.
            agent_factory: Builds a specialist (``create_agent``; tests pass
                a fake).
        """
        self._model = model
        self._skills = library
        self._tracer = tracer
        self._mcp = mcp
        self._max_calls = max_tool_calls
        self._factory = agent_factory
        self._graph = self._build()

    def _build(self) -> Any:
        builder = lg.StateGraph(State, context_schema=Context)
        builder.add_node("supervisor", self._supervise)
        for name in SPECIALISTS:
            builder.add_node(name, self._node(name))
            builder.add_edge(name, "supervisor")
        builder.add_edge(lg.START, "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            _next,
            {**{n: n for n in SPECIALISTS}, lg.END: lg.END},
        )
        return builder.compile(name="chat_team")

    async def _plan(self, state: State, config: dict[str, Any]) -> list[str]:
        user = (
            f"Feed date: {state['day']}. Companies named: "
            f"{', '.join(state['tickers']) or 'none'}. The trader's "
            f"watchlist: {', '.join(state['watchlist']) or 'empty'}.\n\n"
            f"{spotlight.question_block(state['question'])}"
        )
        try:
            runnable = self._model.with_structured_output(
                Plan, method="json_schema"
            )
            plan = await runnable.ainvoke(
                [("system", prompts.SUPERVISOR_SYSTEM), ("human", user)],
                config=config,
            )
        except Exception as e:  # noqa: BLE001 - the keywords take over.
            _log.warning("supervisor plan failed: %r", e)
            plan = None
        if not isinstance(plan, Plan):
            chosen = route_by_keywords(state["question"])
            titles = ", ".join(SPECIALISTS[n].title for n in chosen)
            _emit(
                Step(
                    "supervisor",
                    "plan",
                    f"Keyword routing: asking {titles or 'no specialist'}",
                )
            )
            return chosen
        chosen = clean_plan(list(plan.agents))
        reason = " ".join(plan.reason.split())[:120]
        titles = ", ".join(SPECIALISTS[n].title for n in chosen)
        _emit(
            Step(
                "supervisor",
                "plan",
                f"Asking {titles or 'no specialist'}"
                + (f": {reason}" if reason else ""),
            )
        )
        return chosen

    async def _supervise(
        self, state: State, runtime: lg_runtime.Runtime[Context]
    ) -> dict[str, Any]:
        if state.get("plan") is not None:
            return {}
        if not runtime.context.tools:
            _emit(Step("supervisor", "plan", "Tools unavailable: corpus only"))
            return {"plan": [], "remaining": []}
        chosen = await self._plan(state, runtime.context.config)
        return {"plan": chosen, "remaining": chosen}

    def _node(
        self, name: str
    ) -> Callable[[State, lg_runtime.Runtime[Context]], Any]:
        async def node(
            state: State, runtime: lg_runtime.Runtime[Context]
        ) -> dict[str, Any]:
            found = await self._specialist(SPECIALISTS[name], state, runtime)
            return {
                "remaining": list(state.get("remaining", []))[1:],
                "findings": [f.to_json() for f in found],
            }

        return node

    async def _specialist(
        self,
        spec: Specialist,
        state: State,
        runtime: lg_runtime.Runtime[Context],
    ) -> list[tools_lib.Finding]:
        available = runtime.context.tools
        tools = [available[t] for t in spec.tools if t in available]
        if not tools:
            _emit(Step(spec.name, "failed", "Its tools are unavailable"))
            return []
        if spec.skills:
            tools.append(self._skills.tool(spec.skills))
        system = spec.prompt.replace("{max_calls}", str(self._max_calls))
        catalog = self._skills.catalog(spec.skills)
        if catalog:
            system = f"{system}\n\n{catalog}"
        agent = self._factory(
            self._model, tools, system_prompt=system, name=spec.name
        )
        message = prompts.task(
            state["question"],
            state["day"],
            state["tickers"],
            state["watchlist"],
        )
        calls: dict[str, dict[str, Any]] = {}
        found: list[tools_lib.Finding] = []
        config = {
            **runtime.context.config,
            # model, tools, model... : max_tool_calls rounds, then an answer.
            "recursion_limit": 2 * self._max_calls + 2,
        }
        try:
            async for update in agent.astream(
                {"messages": [("human", message)]},
                config=config,
                stream_mode="updates",
            ):
                for part in update.values():
                    messages = (part or {}).get("messages", [])
                    for msg in messages:
                        self._record(spec, msg, calls, found)
        except lg_errors.GraphRecursionError:
            _emit(Step(spec.name, "done", "Tool budget used"))
        except Exception as e:  # noqa: BLE001 - one specialist can fail.
            _log.warning("%s failed: %r", spec.name, e)
            _emit(Step(spec.name, "failed", "It stopped with an error"))
            return found[:_MAX_FINDINGS]
        _emit(Step(spec.name, "done", f"{len(found)} tool results"))
        return found[:_MAX_FINDINGS]

    def _record(
        self,
        spec: Specialist,
        msg: Any,
        calls: dict[str, dict[str, Any]],
        found: list[tools_lib.Finding],
    ) -> None:
        if isinstance(msg, lc_messages.AIMessage):
            for call in msg.tool_calls:
                calls[call.get("id") or ""] = call
                args = tools_lib.describe_args(call.get("args") or {})
                _emit(Step(spec.name, "tool", f"{call['name']}({args})"))
        elif isinstance(msg, lc_messages.ToolMessage):
            if msg.name == skills_lib.TOOL_NAME or msg.status == "error":
                return
            call = calls.get(msg.tool_call_id, {})
            found.append(
                tools_lib.finding(
                    spec.name,
                    msg.name or call.get("name", "tool"),
                    call.get("args") or {},
                    msg.content,
                )
            )

    @contextlib.asynccontextmanager
    async def _tools(self) -> AsyncIterator[dict[str, lc_tools.BaseTool]]:
        """The MCP tools of one session (empty when unavailable)."""
        if self._mcp is None:
            yield {}
            return
        from langchain_mcp_adapters import tools as mcp_tools  # noqa: PLC0415

        async with contextlib.AsyncExitStack() as stack:
            try:
                session = await stack.enter_async_context(
                    self._mcp.session(SERVER)
                )
                loaded = await mcp_tools.load_mcp_tools(session)
            except Exception as e:  # noqa: BLE001 - corpus-only answer.
                _log.warning("MCP server unavailable for chat: %r", e)
                loaded = []
            yield {t.name: t for t in loaded}

    async def run(
        self,
        question: str,
        day: datetime.date,
        user: str,
        tickers: list[str],
        watchlist: list[str],
    ) -> AsyncIterator[Step | tools_lib.Finding]:
        """Runs the team on one question.

        Args:
            question: The sanitized question.
            day: The feed date.
            user: Who asks (trace metadata).
            tickers: The companies the question names.
            watchlist: The asker's watchlist (long-term memory).

        Yields:
            ``Step`` progress events as they happen, then the findings.
        """
        config = self._tracer.config(
            "chat_team",
            tags=[prompts.CHAT_PROMPT_VERSION],
            metadata={"user": user, "feed_date": day.isoformat()},
        )
        state: State = {
            "question": question,
            "day": day.isoformat(),
            "tickers": list(tickers),
            "watchlist": list(watchlist),
            "plan": None,
            "remaining": [],
            "findings": [],
        }
        final: dict[str, Any] = {}
        async with self._tools() as tools:
            async for mode, chunk in self._graph.astream(
                state,
                config=config,
                context=Context(tools, config),
                stream_mode=["custom", "values"],
            ):
                if mode == "custom":
                    yield Step(chunk["agent"], chunk["action"], chunk["detail"])
                else:
                    final = chunk
        for data in final.get("findings", []):
            yield tools_lib.Finding.from_json(data)


def _next(state: State) -> str:
    remaining = state.get("remaining") or []
    return remaining[0] if remaining else lg.END
