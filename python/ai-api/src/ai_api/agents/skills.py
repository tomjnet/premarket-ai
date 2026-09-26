"""Agent Skills: ``python/skills/<name>/SKILL.md``, loaded on demand.

A skill is a folder with a ``SKILL.md``: YAML front matter with ``name``
and ``description``, then a Markdown body with the instructions. The same
folders work in Claude Code and Claude Desktop.

Progressive disclosure: only the front matter is read up front. An agent's
system prompt lists the skills it may use (name and description, one line
each), and the agent calls the ``load_skill`` tool to read a body when it
needs it. The brief writer always needs its format, so it gets the body
directly.

Skills are trusted instructions (they are in the repository, reviewed like
code); they are never built from vendor text.
"""

from __future__ import annotations

from collections.abc import Iterable
import dataclasses
import logging
import pathlib
import re

from langchain_core import tools as lc_tools
import yaml

_log = logging.getLogger(__name__)
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
TOOL_NAME = "load_skill"


class SkillError(ValueError):
    """A SKILL.md is malformed."""


@dataclasses.dataclass(frozen=True)
class Skill:
    """One skill's front matter and where its body is.

    Attributes:
        name: The folder name (lower-case words joined by hyphens).
        description: What it is for and when to use it.
        path: Its SKILL.md.
    """

    name: str
    description: str
    path: pathlib.Path

    def body(self) -> str:
        """The instructions (the file without its front matter)."""
        text = self.path.read_text(encoding="utf-8")
        return _FRONT_MATTER.sub("", text, count=1).strip()


def parse(path: pathlib.Path) -> Skill:
    """Reads a SKILL.md's front matter.

    Args:
        path: ``<skills>/<name>/SKILL.md``.

    Returns:
        The skill.

    Raises:
        SkillError: No front matter, or a bad name or description.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise SkillError(f"{path}: no YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    name = str(meta.get("name", "")).strip()
    description = " ".join(str(meta.get("description", "")).split())
    if (
        not _NAME.match(name)
        or len(name) > _MAX_NAME
        or name != path.parent.name
    ):
        raise SkillError(f"{path}: name {name!r} must be the folder's name")
    if not description or len(description) > _MAX_DESCRIPTION:
        raise SkillError(f"{path}: the description must be 1-1024 chars")
    return Skill(name, description, path)


class Library:
    """The skills of one folder."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        """Keeps the skills by name."""
        self._skills = {s.name: s for s in skills}

    @classmethod
    def load(cls, root: pathlib.Path) -> Library:
        """Every valid ``<root>/*/SKILL.md`` (a bad one is logged, skipped).

        Args:
            root: The skills folder (SKILLS_DIR); missing means none.

        Returns:
            The library.
        """
        skills = []
        if root.is_dir():
            for path in sorted(root.glob("*/SKILL.md")):
                try:
                    skills.append(parse(path))
                except (SkillError, yaml.YAMLError, OSError) as e:
                    _log.warning("skill skipped: %s", e)
        _log.info("skills: %s", ", ".join(s.name for s in skills) or "none")
        return cls(skills)

    @property
    def names(self) -> tuple[str, ...]:
        """The skill names, sorted."""
        return tuple(sorted(self._skills))

    def get(self, name: str) -> Skill | None:
        """A skill by name, or None."""
        return self._skills.get(name)

    def body(self, name: str) -> str | None:
        """A skill's instructions, or None when there is no such skill."""
        skill = self._skills.get(name)
        return None if skill is None else skill.body()

    def catalog(self, names: Iterable[str] | None = None) -> str:
        """The system-prompt lines: ``- name: description`` per skill.

        Args:
            names: Only these skills (the agent's own); None means all.

        Returns:
            The lines, or an empty string when none of them exists.
        """
        wanted = self.names if names is None else tuple(names)
        lines = [
            f"- {s.name}: {s.description}"
            for n in wanted
            if (s := self._skills.get(n)) is not None
        ]
        if not lines:
            return ""
        return (
            f"Skills you can load with the {TOOL_NAME} tool when a task "
            "needs them:\n" + "\n".join(lines)
        )

    def tool(self, names: Iterable[str]) -> lc_tools.BaseTool:
        """The ``load_skill`` tool, limited to ``names``.

        Args:
            names: The skills this agent may load.

        Returns:
            A LangChain tool returning a skill's instructions.
        """
        allowed = tuple(n for n in names if n in self._skills)

        async def load_skill(name: str) -> str:
            if name not in allowed:
                return (
                    f"No skill named {name[:64]!r}. "
                    f"Available: {', '.join(allowed)}."
                )
            return self.body(name) or ""

        return lc_tools.StructuredTool.from_function(
            coroutine=load_skill,
            name=TOOL_NAME,
            description=(
                "Load the full instructions of a skill by name ("
                + ", ".join(allowed)
                + ")."
            ),
        )
