# Enterprise reference architecture (cloud-neutral)

> Last reviewed: 2026-09-26. Theory only: nothing here is deployed and nothing costs money. Provider-specific versions: `azure.md`, `aws.md`, `gcp.md`.

## Purpose
This page describes how a **large regulated firm** (a bank, broker-dealer or asset manager) would build premarket-ai in production, without naming any cloud. The same building blocks appear on every hyperscaler; the provider pages only swap in the product names.

The business problem is unchanged: every trading day, a vendor sends about 100 news items, some duplicated, stale, misleading or fake. By 07:30 ET traders need a brief built only from verified stories, with evidence, and analysts must be able to review the uncertain ones.

## Design principles
1. **Private by default.** No model, database or cache has a public endpoint. Users reach the web tier through a WAF; everything else talks over private networking.
2. **Identity everywhere, keys nowhere.** People sign in with corporate SSO and MFA. Services use **workload identities** (managed identities, IAM roles, service accounts), never API keys in code or `.env` files.
3. **One door to the models.** Every model call goes through an **AI gateway** that enforces quotas, routing, content safety, logging and chargeback.
4. **Code decides what matters; models decide the uncertain middle.** The lab's rule (hard rules for FAKE, the judge only between VERIFIED, UNVERIFIED and MISLEADING, humans for low confidence) is exactly what model risk teams want to see.
5. **Least agency.** Agents get read-only tools from an allowlist, through a governed tool gateway. Any write action needs a human.
6. **Everything is recorded.** Prompts, retrieved context, tool calls, answers, verdicts and overrides go to an immutable audit store for years.
7. **Open standards at the seams.** OpenAI-compatible model APIs, MCP for tools, A2A between agents, OpenTelemetry for telemetry, SQL + pgvector for data. The lab's code maps onto the cloud version without a rewrite of its logic.
8. **Everything as code.** Landing zone, networks, services, policies, prompts, eval sets and dashboards are versioned and deployed by pipelines with approvals.

## Logical architecture

```mermaid
flowchart LR
  classDef edge fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
  classDef app fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef ai fill:#ede9fe,stroke:#7c3aed,color:#3b0764
  classDef data fill:#fef3c7,stroke:#d97706,color:#78350f
  classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111827

  U(["Traders · Analysts · Admins<br/>corporate SSO + MFA"]):::ext
  V(["News vendor<br/>(SFTP / API)"]):::ext
  X(["SEC EDGAR · market data ·<br/>approved web search"]):::ext

  subgraph EDGE["Edge"]
    WAF["WAF + CDN<br/>DDoS protection"]:::edge
    WEB["Static web app<br/>(React)"]:::edge
  end

  subgraph APP["Application tier (private)"]
    API["API (containers)<br/>auth · news · review · brief · chat"]:::app
    Q["Message queue"]:::app
    W["Workers<br/>verify graph · briefing agent"]:::app
    SCH["Scheduler + workflow engine<br/>NYSE calendar · SLA checks"]:::app
    ING["Ingest batch<br/>(C++20 container job)"]:::app
  end

  subgraph AI["AI platform (private)"]
    GW["AI gateway<br/>quotas · routing · safety · logs"]:::ai
    LLM["Managed LLMs<br/>(enterprise contract)"]:::ai
    SELF["Self-hosted open models<br/>(GPU endpoints)"]:::ai
    SAFE["Content safety +<br/>prompt-injection shields"]:::ai
    AGT["Agent runtime<br/>(LangGraph or managed agents)"]:::ai
    TG["Tool gateway (MCP)<br/>authN/Z per tool"]:::ai
  end

  subgraph DATA["Data tier (private endpoints, CMK)"]
    PG[("PostgreSQL<br/>+ pgvector")]:::data
    VS[("Search / vector index<br/>(optional managed)")]:::data
    RC[("Redis-compatible cache")]:::data
    OBJ[("Object storage<br/>raw feed · corpus")]:::data
    AUD[("Immutable audit store<br/>WORM, years")]:::data
  end

  U --> WAF --> WEB --> API
  V --> OBJ --> ING --> PG
  SCH --> ING
  SCH --> Q --> W
  API --> Q
  API --> AGT
  W --> AGT
  AGT --> GW
  API --> GW
  GW --> SAFE
  GW --> LLM
  GW --> SELF
  AGT --> TG --> X
  TG --> PG
  API --> PG
  W --> PG
  API --> RC
  W --> RC
  AGT --> VS
  GW -. "prompt + answer log" .-> AUD
  API -. "decisions + overrides" .-> AUD
```

### Cross-cutting services

```mermaid
flowchart TB
  classDef x fill:#f1f5f9,stroke:#475569,color:#0f172a
  ID["Identity<br/>SSO · MFA · RBAC/ABAC ·<br/>workload identity · agent identity"]:::x
  SEC["Secrets + keys<br/>vault · HSM-backed CMK"]:::x
  NET["Networking<br/>hub-and-spoke · private endpoints ·<br/>egress allowlist · private DNS"]:::x
  OBS["Observability<br/>OpenTelemetry traces + metrics ·<br/>GenAI dashboards · SIEM"]:::x
  GOV["Data governance<br/>catalog · lineage · classification · DLP"]:::x
  MLO["MLOps / LLMOps<br/>eval pipelines · registry · approvals"]:::x
  FIN["FinOps<br/>token budgets · chargeback"]:::x
  LZ["Landing zone<br/>accounts/subscriptions/projects ·<br/>policy guardrails · IaC"]:::x
  LZ --- ID & SEC & NET
  LZ --- OBS & GOV
  LZ --- MLO & FIN
```

## Building blocks

| Block | What it does in the enterprise | Lab equivalent |
|---|---|---|
| **WAF + CDN** | TLS termination, bot and DDoS protection, OWASP rules, geo and rate limits in front of the web tier | nginx edge proxy with security headers and rate limits |
| **Static web app** | The React UI from object storage behind the CDN | `web-1` / `web-2` behind the edge |
| **API (containers)** | Stateless FastAPI on a managed container platform or Kubernetes, autoscaled, private | `ai-api` in Podman |
| **Message queue + workers** | Durable queue, dead-letter queue, autoscaled workers per queue depth | taskiq on a Redis Stream, `ai-worker` |
| **Scheduler + workflow engine** | Cron on the exchange calendar, retries, timeouts, SLA alarms, a visual run history | APScheduler + `exchange_calendars`, SLA checks to a Redis Stream |
| **Ingest batch** | The C++20 ingester as a container job reading the vendor drop from object storage | `ingest` container with supercronic |
| **AI gateway** | One endpoint for every model: auth by workload identity, token quotas per team, load balancing and failover across regions, semantic cache, content safety, logging, chargeback | LiteLLM with task aliases and a monthly budget |
| **Managed LLMs** | Frontier models under an enterprise contract: no training on customer data, regional processing, provisioned throughput | `cloud-openai` alias through an API key |
| **Self-hosted open models** | Open-weight models on private GPU endpoints for cost, latency or data-sensitivity reasons | Ollama on the GPU host |
| **Content safety** | Managed classifiers for harmful content, prompt injection (direct and indirect) and data leakage, on input and output | Llama Guard 3 plus the lab's sanitize, spotlighting and output checks |
| **Agent runtime** | Hosts agent graphs with session isolation, memory, identity and tracing; either managed agents or LangGraph in containers | LangGraph in `ai-api` / `ai-worker`, Postgres checkpoints and store |
| **Tool gateway (MCP)** | Publishes internal APIs as MCP tools with authentication, per-agent authorization, rate limits and audit | `mcp-server` with a service token and read-only tools |
| **PostgreSQL + pgvector** | Managed, zone-redundant PostgreSQL with private endpoint, CMK, PITR backups, read replicas; pgvector for hybrid search | PostgreSQL 17 + pgvector in a container |
| **Managed search index** | Optional: a managed search service for large corpora, semantic ranking and document-level security | Not needed at 5,000 chunks |
| **Redis-compatible cache** | Sessions, dedup index, rate limits, semantic cache, locks | Redis 8 + RedisVL |
| **Object storage** | The raw vendor feed, the trusted corpus, eval datasets, with lifecycle rules | Container volumes |
| **Immutable audit store** | WORM retention of prompts, answers, verdicts, overrides and brief views for the regulatory period | Audit tables, 90 days (a documented simplification) |
| **Observability + SIEM** | OpenTelemetry traces and GenAI metrics into the cloud monitor and a Langfuse-like LLM tracer; security events into the SIEM | Langfuse, OpenTelemetry Collector, Prometheus, Grafana |

## How a trading day flows

```mermaid
sequenceDiagram
  autonumber
  participant V as Vendor
  participant S as Scheduler
  participant I as Ingest job
  participant Q as Queue
  participant W as Workers + agents
  participant G as AI gateway
  participant H as Analyst
  participant T as Trader
  V->>I: 05:30 ET feed (~100 items)
  S->>I: wait until ingest DONE (SLA 06:15)
  S->>Q: 06:00 rules → enrich → verify jobs
  Q->>W: one verify graph per unique item
  W->>G: judge only the uncertain middle
  G-->>W: verdict + cited evidence (logged)
  W->>H: low confidence → review queue
  H-->>W: approve / change (audited)
  S->>W: 07:15 briefing agent
  W->>T: brief before 07:30 ET (SLA)
  S->>W: 09:00 refresh with reviewed items
```

## Environments and delivery
- **Accounts / subscriptions / projects:** separate `dev`, `test` and `prod`, plus shared `network`, `security` (logs, SIEM) and `ai-platform` (gateway, model deployments) units under a landing zone with policy guardrails (allowed regions, no public IPs, encryption required, approved model list).
- **Pipelines:** infrastructure as code (Terraform, Bicep or CDK), container images signed and scanned, the eval suite as a required gate, and a change approval for production.
- **Release:** canary or blue-green for the API and workers; **shadow mode** for a new model or prompt (it runs on real items without affecting verdicts, and its results are compared before the switch).
- **Resilience:** zone-redundant data services, a second region for the AI gateway's failover, documented RTO/RPO, and a "rules-only" degraded mode when every model is unavailable (the lab already falls back to local models and deterministic overviews).

## What changes from the lab, and what doesn't
**Changes:** managed services instead of containers for state (database, cache, queue), corporate identity instead of seeded users, private networking, WORM audit, model risk approval, multi-environment delivery.

**Stays the same:** the verify workflow and its verdict policy, the rules engine, the prompts and schemas, RAG with hybrid search, the MCP tools, the skills, the eval sets and gates, and the OpenTelemetry instrumentation. That is the benefit of building the lab on open standards.

## Related pages
- `service-mapping.md`: every lab component and its Azure, AWS and GCP service
- `security.md`: enterprise controls vs the lab
- `mlops-llmops.md`: lifecycle, evaluation, approval and monitoring
- `build-vs-buy.md`: when a managed service beats the open-source stack
