# Build vs buy: managed cloud services or the open-source lab stack

> Last reviewed: 2026-09-26. Theory only. This page helps decide, component by component, when a managed cloud service beats running the open-source piece yourself.

## Short answer
- **Managed services win for regulated production:** SSO, private networking, compliance attestations, SLAs, support and audit tooling come built in, and the firm's auditors already know them.
- **Open source / self-hosted wins** for learning, portability, cost control at small scale, special requirements, and avoiding lock-in.
- **The enterprise pattern is both:** managed platforms for the undifferentiated parts (databases, queues, identity, model hosting) plus **open standards** at the seams (OpenAI-compatible APIs, MCP, A2A, OpenTelemetry, SQL with pgvector, LangGraph), so the firm can change a provider without rewriting its logic.

## Decision criteria

| Criterion | Favors managed | Favors self-hosted / open source |
|---|---|---|
| **Compliance** | Needs SOC 2 / ISO 27001 attestations, data residency, private endpoints, CMK out of the box | Data never leaves your own environment (on-premises or air-gapped) |
| **Team size** | Small platform team; no one to patch and page at night | A strong platform team that already runs Kubernetes and databases |
| **Scale** | Spiky or growing load; autoscaling and multi-region matter | Small, steady load (like 100 items a day) |
| **Cost** | Low volume of managed calls, or high value of saved engineering time | Very high steady volume, where GPU capacity you own is cheaper per token |
| **Speed to market** | Need it working next month | Time to learn and build is acceptable |
| **Control** | Default behaviour is good enough | Need custom routing, prompts, rankers, or a model the provider doesn't offer |
| **Portability** | Committed to one cloud | Multi-cloud or exit strategy required |
| **Innovation pace** | Want new models and features the day they ship | Want to pin versions and change only on your schedule |

## Component by component

| Lab component | Buy (managed) when… | Build / self-host when… | Typical enterprise choice |
|---|---|---|---|
| **Frontier LLMs** (OpenAI, Claude, Gemini) | Always, unless data can't leave the premises: nobody self-hosts frontier models | Air-gapped environments using open-weight models | **Buy** through the cloud's model platform under an enterprise contract |
| **Open-weight models** (Ollama) | Serverless or managed endpoints exist for the model and volume is modest | Steady high volume, fine-tuned models, strict latency, or data sensitivity | **Mixed:** managed endpoints first, own GPU clusters at scale |
| **LLM gateway** (LiteLLM) | The cloud's API management AI gateway covers quotas, routing, logging and chargeback | Multi-cloud routing across providers, custom logic | **Mixed:** the cloud gateway, or LiteLLM on Kubernetes behind it |
| **Embeddings** | Managed embedding models are cheap and good | You need a specific open model or no data egress | **Buy** |
| **Vector store** (pgvector) | A managed search service gives hybrid search, semantic ranking and document-level security for large corpora | Data is already in PostgreSQL and the corpus is moderate (pgvector on managed PostgreSQL) | **pgvector on managed PostgreSQL** for this size; managed search for millions of documents |
| **Managed RAG** (knowledge bases) | Standard document Q&A with little custom logic | Custom ranking (hybrid + RRF + reranker), citation rules, domain filters like ticker and date | **Build** the RAG logic, buy the storage |
| **Reranker** (bge-reranker) | The search service's semantic ranker is enough | Domain-tuned reranking | **Buy** if available in the search service |
| **Agent framework** (LangGraph) | The managed agent service meets the need and you accept its model of agents | Deterministic workflows with interrupts, custom verdict policies, portability | **Build with LangGraph, run it on the managed agent runtime** (all three clouds can host it) |
| **Tools** (MCP server) | The cloud's tool gateway can expose existing APIs as MCP tools with authentication | Domain tools with custom safety (SSRF-safe fetch, rate limits) | **Build the tools, buy the gateway** in front of them |
| **Guardrails** (Llama Guard, rules) | Managed content safety and prompt-injection shields | Domain rules (no advice, verdict policy, citation checks) | **Both:** managed safety plus the firm's own rules |
| **Relational DB** (PostgreSQL) | Always in production: backups, HA, patching, PITR | Only in a lab | **Buy** |
| **Cache** (Redis) | Always in production | Only in a lab | **Buy** |
| **Queue + workers** (taskiq on Redis Streams) | Managed queue with dead-letter queues and autoscaled consumers | Very low latency or in-memory pipelines | **Buy** the queue; keep the worker code |
| **Scheduler** (APScheduler) | Managed scheduler + workflow engine with run history and retries | Exchange-calendar logic is custom anyway | **Buy** the trigger and workflow engine; keep the calendar logic in code |
| **Legacy C++ batch** | Managed batch or container jobs | Nothing to gain from rewriting | **Buy** the runtime, keep the C++ |
| **Observability** (Langfuse, OTel, Prometheus, Grafana) | The cloud monitor plus the provider's AI tracing covers it | Multi-cloud view, LLM-specific tracing, data kept in-house | **Mixed:** OpenTelemetry everywhere, the cloud monitor plus an LLM tracer (hosted Langfuse or similar) |
| **Evals** (RAGAS, promptfoo, custom) | The cloud's evaluation service is enough for standard metrics | Domain metrics (verdict confusion matrix, injection red team) | **Build** the domain evals; use managed ones in addition |
| **Identity** (JWT + seeded users) | Always: corporate SSO | Never in production | **Buy** |
| **Secrets** (`.env`) | Always: a vault with CMK | Never in production | **Buy** |

## Lock-in and how to limit it
1. **Call models through an OpenAI-compatible gateway**, not a provider SDK, so switching providers is a config change (the lab already does this with LiteLLM aliases).
2. **Keep agent logic in LangGraph (or another portable framework)** and host it on the managed runtime, instead of defining agents only in a provider's console.
3. **Expose tools through MCP**, so any agent runtime can use them.
4. **Instrument with OpenTelemetry** (GenAI semantic conventions), so traces can go to any backend.
5. **Keep data in PostgreSQL + pgvector** where possible; every cloud offers it as a managed service.
6. **Own the eval sets and gates.** They are the firm's real asset: they decide whether any new model or provider is good enough.

## Rough cost picture for this workload
The lab's workload is small: about 100 items a day, one brief, a handful of analysts. At that size:
- Managed model calls cost **cents to a few dollars a day** (the lab's whole monthly cloud cap is $20).
- The fixed costs dominate: managed PostgreSQL, cache, private networking, WAF, logging and the SIEM cost more per month than the tokens.
- Self-hosted GPUs for open models only pay off at far higher, steady volumes, or when data can't leave the firm.

So for this use case the enterprise would **buy almost everything**, and **build** only what makes the product: the verdict policy, the rules, the RAG logic, the tools, the prompts and the evals.
