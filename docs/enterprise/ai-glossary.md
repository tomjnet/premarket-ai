# AI glossary

> Last reviewed: 2026-09-26. Definitions are written for this project: each one says, where it applies, **where the term shows up in premarket-ai**.

Terms are grouped by topic and sorted alphabetically inside each group. The [index](#index) at the end lists every term.

- [Foundations](#foundations)
- [Models and inference](#models-and-inference)
- [Prompting and outputs](#prompting-and-outputs)
- [Retrieval and RAG](#retrieval-and-rag)
- [Agents and tools](#agents-and-tools)
- [Safety, security and guardrails](#safety-security-and-guardrails)
- [Evaluation and quality](#evaluation-and-quality)
- [Classic machine learning](#classic-machine-learning)
- [Operations (MLOps / LLMOps)](#operations-mlops--llmops)
- [Governance, risk and regulation](#governance-risk-and-regulation)

---

## Foundations

| Term | Definition | In premarket-ai |
|---|---|---|
| **Artificial intelligence (AI)** | The broad field of building systems that perform tasks that normally need human judgment: understanding language, recognizing patterns, making decisions. | The whole platform: deciding which pre-market news is real. |
| **Deep learning** | Machine learning with neural networks of many layers. Almost all modern language, vision and speech models are deep learning models. | FinBERT, DistilBERT, the embedding model and every LLM. |
| **Foundation model** | A large model trained on broad data that can be adapted to many tasks (by prompting, RAG or fine-tuning) instead of being trained for one. | The local Ollama models and the cloud models (OpenAI, Claude, Gemini). |
| **Generative AI (GenAI)** | AI that produces new content (text, code, images, audio) instead of only classifying or predicting a number. | Summaries, the judge's rationale, "Ask the News" answers, the brief's overview. |
| **Large language model (LLM)** | A foundation model trained on text to predict the next token. At scale it can follow instructions, summarize, reason and call tools. | `qwen3:4b-instruct`, `llama3.2:3b`, `phi4-mini`, `gemma3:4b` locally; `cloud-openai` in the gateway. |
| **Machine learning (ML)** | The part of AI where a system learns patterns from data instead of following hand-written rules. | The classic ML baseline (FinBERT, DistilBERT). The rules engine is deliberately *not* ML. |
| **Multimodal model** | A model that takes or produces more than one kind of data, for example text and images. | Not used: the vendor feed is text only. |
| **Neural network** | A function made of layers of weighted connections, trained by adjusting the weights to reduce an error. | Inside every model the lab runs. |
| **Small language model (SLM)** | An LLM small enough (roughly 1–10 B parameters) to run on a laptop or a single consumer GPU. Cheaper and more private, weaker at hard reasoning. | Every local model: the lab's GPU has 4 GB of VRAM. |
| **Transformer** | The neural-network architecture behind today's LLMs. Its **attention** mechanism lets each token weigh every other token in the context. | All the lab's language models are transformers. |

## Models and inference

| Term | Definition | In premarket-ai |
|---|---|---|
| **Batch inference** | Running a model over many inputs at once, off the user's critical path, for throughput and cost. | `enrich` and `verify` over a whole day's feed. |
| **Context window** | The maximum number of tokens (prompt plus answer) a model can handle in one call. | Chunk sizes and prompt budgets are set to fit the small local models' windows. |
| **Distillation** | Training a smaller "student" model to imitate a larger "teacher" model. | DistilBERT is a distilled BERT. |
| **Embedding** | A vector of numbers that represents the meaning of a text, so that similar texts have nearby vectors. | `nomic-embed-text` (768 dimensions) for the RAG corpus and the paraphrase check (L3). |
| **Fine-tuning** | Continuing to train a pretrained model on your own labeled data so it gets better at one task. | `make -C python ml-train` fine-tunes DistilBERT on labeled vendor feeds. The LLMs are *not* fine-tuned. |
| **Hallucination** | A fluent answer that is not supported by the input or by facts. Also called confabulation. | Kept in check by RAG, required citations, evidence ids and the "cite only what you were given" checks. |
| **Inference** | Using a trained model to produce an output. Training changes the weights; inference only reads them. | Every call to the LLM gateway. |
| **Latency (TTFT, tokens/s)** | How long a model takes. **Time to first token** matters for chat; **tokens per second** for long outputs. | Measured by `make -C python bench-models` and the OpenTelemetry GenAI metrics. |
| **LLM gateway** | A proxy in front of many model providers that gives one API, keys, routing, fallbacks, budgets and logging. | LiteLLM (`llm-gateway`), with task aliases per hardware profile. |
| **Model alias** | A stable name (for example `judge` or `cloud-openai`) that the gateway maps to a concrete model, so code never hardcodes a model. | The aliases in `podman/config/litellm/config.yaml`. |
| **Open-weight model** | A model whose weights can be downloaded and run yourself (licenses vary). Not always "open source" in the strict sense. | Llama, Qwen, Phi, Gemma, Llama Guard via Ollama. |
| **Parameters (weights)** | The learned numbers inside a model. More parameters usually means more capability and more memory. | 1–4 B parameters locally. |
| **Provisioned throughput** | Capacity reserved (and paid for) in advance from a cloud model provider, for predictable latency. | Enterprise only; the lab uses pay-per-token cloud calls under a budget. |
| **Quantization** | Storing weights with fewer bits (for example 4-bit instead of 16-bit) so a model uses less memory and runs faster, with a small quality loss. | The Ollama models are 4-bit quantized to fit in 4 GB of VRAM. |
| **Reasoning model** | An LLM trained to "think" (produce intermediate reasoning) before answering. Better on hard problems, slower and more expensive. | Not needed for the lab's short, structured tasks. |
| **Temperature** | A sampling setting: 0 gives the most likely tokens (repeatable), higher values give more variety. | Low temperature for the judge and extraction. |
| **Token** | The unit a model reads and writes: a word, part of a word or a symbol. Cost and limits are counted in tokens. | `gen_ai.client.token.usage`, the monthly cloud budget. |
| **VRAM** | The GPU's memory. The model's weights and its context must fit in it for fast inference. | The GTX 1650's 4 GB decides which models the lab can run (`HW_PROFILE=gpu4gb`). |

## Prompting and outputs

| Term | Definition | In premarket-ai |
|---|---|---|
| **Chain-of-thought (CoT)** | Asking or letting a model write out intermediate steps before the answer. | Not shown to users; the judge returns a short rationale instead. |
| **Context engineering** | Deciding *everything* that goes into the model's context (instructions, retrieved data, tool results, memory, history), not just the wording of the prompt. | Spotlighting, data tags, the sources list, skills loaded on demand. |
| **Few-shot prompting** | Putting a few worked examples in the prompt. **Zero-shot** means none. | Some extraction prompts include short examples. |
| **Grounding** | Tying an answer to specific source material the model was given, so it can be checked. | Every answer and verdict cites its sources or evidence ids. |
| **Prompt** | The input text sent to a model: instructions, context and the question. | Versioned with the code under `python/ai-api/src/ai_api/`. |
| **Prompt template** | A prompt with placeholders filled at run time. | LangChain prompt templates in `enrich/`, `verify/`, `agents/`. |
| **Structured output** | Forcing the model's answer into a schema (usually JSON) that code can validate. | The judge's schema, which doesn't even contain FAKE. |
| **System prompt** | Instructions that set the model's role and rules, sent before the user's input. | "Decision support only, no investment advice" and the citation rules. |

## Retrieval and RAG

| Term | Definition | In premarket-ai |
|---|---|---|
| **Approximate nearest neighbour (ANN)** | Fast search for the closest vectors that trades a little accuracy for speed. HNSW is the most common index. | The pgvector HNSW index on `ai.chunk.embedding`. |
| **BM25 / full-text search** | Classic keyword ranking. Strong on exact names, tickers and numbers where embeddings are weak. | Postgres full-text (`tsv`) in the hybrid query. |
| **Chunking** | Splitting documents into passages small enough to embed and retrieve. | The trusted corpus (8-Ks, Fed and SEC releases) cut into about 5,000 chunks. |
| **Cosine similarity** | A measure of how close two vectors point in the same direction; the usual similarity for embeddings. | The HNSW index and the semantic cache (distance ≤ 0.05). |
| **Graph RAG** | RAG over a knowledge graph of entities and relations instead of (or next to) plain text chunks. | Not used. |
| **Hybrid search** | Combining vector search and keyword search, then fusing the two rankings. | One SQL statement: vector top-k and full-text top-k fused by **reciprocal rank fusion (RRF)**, k = 60. |
| **Knowledge base** | The curated document collection a RAG system retrieves from. | The trusted corpus, never the vendor feed. |
| **Retrieval-augmented generation (RAG)** | Retrieving relevant passages and putting them in the prompt so the model answers from them and can cite them. | "Ask the News" and the corroboration check. |
| **Reranker** | A second model that re-scores the retrieved candidates for relevance to the question, more precisely than the first search. | `bge-reranker-base` (the `reranker` service). |
| **Semantic cache** | Reusing a stored answer when a new question means the same thing as an earlier one (embedding distance below a threshold). | RedisVL `SemanticCache` for "Ask the News" (15 minutes). |
| **Vector database / vector store** | A store that indexes embeddings for similarity search. | ChromaDB (increments 3–5), then **pgvector** in PostgreSQL. |

## Agents and tools

| Term | Definition | In premarket-ai |
|---|---|---|
| **A2A (Agent2Agent protocol)** | An open protocol for agents built by different teams or vendors to discover each other and delegate tasks. Started at Google; now under the Agentic AI Foundation. | Not used; all agents run in one LangGraph process. |
| **Agentic AI Foundation (AAIF)** | The Linux Foundation body that governs MCP (since December 2025) and A2A (since August 2026), so neither protocol belongs to a single vendor. | Why the lab bets on MCP: it is vendor-neutral. |
| **Agent** | An LLM in a loop that decides which tools to call, reads the results and continues until it can answer. | The Fact-Checker, Market Analyst and Brief Writer specialists. |
| **Agent Skills** | Folders with a `SKILL.md` (a name, a one-line description and instructions) that an agent loads only when it needs them. | `python/skills/`: fact-check methodology, source credibility, brief format, vendor scorecard. |
| **Agentic workflow** | A process where an LLM decides some of the steps. A **workflow** in the strict sense has fixed steps written in code; an **agent** chooses them. | `verify_news` is a workflow (code decides); the chat is agentic (the supervisor decides). |
| **Checkpoint** | A saved copy of an agent graph's state, so it can pause, survive a restart and resume. | LangGraph checkpoints in Postgres (schema `graph`). |
| **Function calling / tool calling** | The model returns a structured request to call a named function with arguments; code runs it and returns the result. | The specialists' calls to the MCP tools. |
| **Human in the loop (HITL)** | A person approves or corrects the AI's decision before it takes effect. | The analysts' review queue (`interrupt()` in the graph). |
| **LangGraph** | A library for building agents and workflows as graphs of steps with shared state, checkpoints and interrupts. | `verify_news`, the chat supervisor, the briefing agent. |
| **MCP (Model Context Protocol)** | An open protocol that lets AI applications connect to tools and data through a standard server interface. | `mcp-server` (FastMCP): read-only tools such as `lookup_company` and `search_news`. |
| **Memory (short-term / long-term)** | Short-term: the current conversation or run state. Long-term: facts kept across sessions. | Checkpoints (short-term) and each user's watchlist in the LangGraph store (long-term). |
| **Multi-agent system** | Several specialized agents cooperating, often coordinated by a **supervisor** agent. | The chat's Supervisor picks up to two specialists per question. |
| **Progressive disclosure** | Showing a model only short descriptions first and loading the full text on demand, to save context. | Skills: agents see the description and call `load_skill`. |
| **ReAct** | "Reason + act": the agent alternates between thinking, calling a tool and observing the result. | Each chat specialist is a ReAct agent. |
| **Tool allowlist** | The explicit list of tools one agent may call. | Per-specialist allowlists, at most 3 tool calls per question. |

## Safety, security and guardrails

| Term | Definition | In premarket-ai |
|---|---|---|
| **Content safety classifier** | A model that labels text as safe or unsafe by category. | **Llama Guard 3** (1B) on questions, answers and stories. |
| **Data exfiltration** | Tricking an AI system into leaking data to an attacker, for example through a URL it fetches. | `fetch_url` refuses private addresses; tools are read-only. |
| **Excessive agency** | Giving an AI more tools, permissions or autonomy than its task needs. | No write tools anywhere; the verify graph's code, not a model, calls its tools. |
| **Guardrails** | Checks around a model's input and output: filters, classifiers, schemas and rules. | Sanitize, injection heuristics, Llama Guard, no-advice and citation checks. |
| **Indirect prompt injection** | Instructions hidden in data the model reads (a web page, an email, a news item), not typed by the user. | The vendor feed contains injection items; they are flagged and never reach a tool. |
| **Jailbreak** | A prompt designed to make a model ignore its safety rules. | Llama Guard and the refusal checks in chat. |
| **PII (personally identifiable information)** | Data that identifies a person: names with contact details, emails, phone numbers, ids. | Emails and phones are masked before any model call. |
| **Prompt injection** | Input that tries to override the application's instructions ("ignore previous instructions…"). | The security check in the plan; the red-team eval set. |
| **Red teaming** | Deliberately attacking a system to find ways it can be misused before attackers do. | The injection items and red-team checks in the verdict eval. |
| **Spotlighting** | Marking untrusted text clearly (data tags, encoding) so the model treats it as data, not instructions. | Vendor text and tool results only reach models inside data tags they can't close. |

## Evaluation and quality

| Term | Definition | In premarket-ai |
|---|---|---|
| **Confusion matrix** | A table of predicted vs actual classes, showing exactly which mistakes a classifier makes. | The 4×4 verdict matrix (VERIFIED / UNVERIFIED / MISLEADING / FAKE). |
| **Context precision** | A RAG metric: how much of the retrieved context was actually relevant. | Part of `make -C python eval-rag` (RAGAS). |
| **Eval (evaluation)** | A repeatable test of an AI system's quality on a fixed dataset, with metrics and thresholds. | `make -C python eval`, `eval-ai`, `eval-rag`. |
| **Eval gate** | CI fails when an eval metric drops below a threshold or regresses from a baseline. | "No metric more than 2 points below the baseline". |
| **F1 / macro-F1** | The harmonic mean of precision and recall; macro-F1 averages it over classes, so small classes count equally. | Verdict gate: macro-F1 ≥ 0.75. |
| **Faithfulness** | A RAG metric: whether every claim in the answer is supported by the retrieved context. | RAGAS faithfulness in `eval-rag`. |
| **Golden set** | A fixed, labeled dataset used as the reference for evals. Never used for training. | The seed-42 vendor feeds with `labels.jsonl`. |
| **LLM-as-judge** | Using an LLM to grade or decide, following a rubric. Needs its own evaluation because judges have biases. | The verdict judge (weight 0.4 against the rules' 0.6). RAGAS also uses one. |
| **Precision / recall** | Precision: of the items flagged, how many were right. Recall: of the real cases, how many were flagged. | FAKE recall ≥ 0.85 and precision ≥ 0.90. |
| **Regression** | A change that makes a metric worse than before. | Blocked by the baselines in `python/ai-api/evals/`. |

## Classic machine learning

| Term | Definition | In premarket-ai |
|---|---|---|
| **Baseline** | A simple model used to judge whether a complex one is worth it. | The DistilBERT verdict classifier vs rules and the LLM judge. |
| **Classification** | Predicting a category. **Regression** (in ML) predicts a number. | Verdicts and sentiment are classification. |
| **Feature** | An input variable a model uses. **Feature engineering** is designing them by hand. | Market impact = news kind × company size. |
| **Overfitting** | A model memorizes its training data and does worse on new data. | Why DistilBERT is never trained on the golden set's seed. |
| **Supervised learning** | Learning from examples with the correct answer (labels). **Unsupervised** finds structure without labels. | DistilBERT on labeled feeds; analysts' overrides become new labels. |
| **Train / validation / test split** | Separate data for learning, tuning and final scoring, so the score is honest. | Training seeds vs the seed-42 golden set. |

## Operations (MLOps / LLMOps)

| Term | Definition | In premarket-ai |
|---|---|---|
| **Canary / blue-green release** | Sending a small share of traffic to a new version (canary), or switching all traffic between two full environments (blue-green). | Not in the lab; see `mlops-llmops.md`. |
| **Drift** | The live data or the model's behaviour moves away from what it was evaluated on. | The analysts' override rate is the lab's early signal. |
| **FinOps** | Managing cloud cost: budgets, visibility, chargeback and optimization. | The $20 monthly cloud budget and its alerts. |
| **LLMOps** | MLOps for LLM applications: prompt and model versioning, evals, tracing, guardrails, cost. | Langfuse traces, eval gates, pinned aliases. |
| **MLOps** | Practices to build, deploy, monitor and retrain ML models reliably, like DevOps for models. | `ml-train`, the eval images, the self-hosted GPU runner. |
| **Model registry** | A catalog of model versions with their metadata, metrics and approval state. | Not in the lab (versions are pinned in config). |
| **Observability / tracing** | Recording each request's steps (prompts, tool calls, tokens, latency) to debug and audit. | Langfuse traces and OpenTelemetry GenAI metrics. |
| **Shadow mode** | Running a new model next to the current one on real traffic without showing its output to users. | The brief ran next to the PDF before the PDF was retired. |

## Governance, risk and regulation

| Term | Definition | In premarket-ai |
|---|---|---|
| **AI governance** | The policies, roles and controls that decide which AI systems an organization builds and how they are approved and monitored. | See `security.md` and `mlops-llmops.md`. |
| **EU AI Act** | The European Union's AI regulation, which sorts AI systems by risk and puts duties on providers and deployers. General-purpose AI duties apply from August 2025; the high-risk dates were postponed in 2026 (see `security.md`). | Out of scope for the lab; listed for enterprises. |
| **ISO/IEC 42001** | The international standard for an AI management system. | Enterprise control only. |
| **Model card** | A short document describing a model's purpose, data, metrics, limits and risks. | Enterprise control only. |
| **Model risk management (MRM)** | A bank's process to inventory, validate, approve and periodically review models (US guidance: SR 11-7 until April 2026, now SR 26-2). | Enterprise control only; the lab has the PR gate. |
| **NIST AI RMF** | The US National Institute of Standards and Technology's AI Risk Management Framework (Govern, Map, Measure, Manage), with a Generative AI profile. | Enterprise control only. |
| **Responsible AI** | Building AI that is fair, transparent, safe, private and accountable. | Disclaimers, citations, human review, synthetic data only. |
| **WORM storage** | "Write once, read many": records that can't be changed or deleted before their retention ends, as required for regulated recordkeeping. | The lab keeps 90 days in ordinary tables, a documented simplification. |

---

## Index

A2A · Agent · Agent Skills · Agentic AI Foundation · Agentic workflow · AI governance · Approximate nearest neighbour · Artificial intelligence · Baseline · Batch inference · BM25 · Canary release · Chain-of-thought · Checkpoint · Chunking · Classification · Confusion matrix · Content safety classifier · Context engineering · Context precision · Context window · Cosine similarity · Data exfiltration · Deep learning · Distillation · Drift · Embedding · EU AI Act · Eval · Eval gate · Excessive agency · F1 · Faithfulness · Feature · Few-shot prompting · Fine-tuning · FinOps · Foundation model · Function calling · Generative AI · Golden set · Graph RAG · Grounding · Guardrails · Hallucination · Human in the loop · Hybrid search · Indirect prompt injection · Inference · ISO/IEC 42001 · Jailbreak · Knowledge base · LangGraph · Large language model · Latency · LLM gateway · LLM-as-judge · LLMOps · Machine learning · MCP · Memory · Model alias · Model card · Model registry · Model risk management · MLOps · Multi-agent system · Multimodal model · Neural network · NIST AI RMF · Observability · Open-weight model · Overfitting · Parameters · PII · Precision / recall · Progressive disclosure · Prompt · Prompt injection · Prompt template · Provisioned throughput · Quantization · RAG · ReAct · Reasoning model · Red teaming · Regression · Reranker · Responsible AI · Semantic cache · Shadow mode · Small language model · Spotlighting · Structured output · Supervised learning · System prompt · Temperature · Token · Tool allowlist · Train / test split · Transformer · Vector database · VRAM · WORM storage
