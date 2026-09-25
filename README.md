# premarket-ai

AI pre-market news platform that separates real market news from fake. It migrates a legacy **C++11 / PostgreSQL / PDF** pipeline, step by step, to **modern C++20, RAG, LangGraph agents, MCP, Skills and local LLMs** (with an OpenAI / Claude / Gemini switch), all running on **Podman**.

> ⚠️ **Simulation, not investment advice.** All vendor news in this project is **synthetic**: it's generated, labeled `[SYNTHETIC]`, and fake sources use reserved `.example` / `.test` domains. The system is decision support only. It never recommends buying or selling and has no trading tools.

## The story
Before the market opens, traders read a news report. For years it came from a **batch pipeline**: an external vendor sends ~100 news items per day, a C++ program loads them into PostgreSQL, and another C++ program prints a **PDF** onto an NFS share.

The vendor is paid for 100 items per day, so it **pads the feed with duplicates, stale stories, fake news and even fake companies**. After a conference, the CEO asked for a modern website and for AI that can tell traders **which news is real**.

This repo rebuilds the system **one increment at a time** (the strangler-fig pattern). Every increment ships something traders can use and replaces one piece of the legacy system, until the PDF is retired.

## Delivery increments
Each increment is developed on its own branch, merged to `main` through a PR once its "done when" check passes, and tagged (`inc-0`, `inc-1`, …) so every stage can be checked out exactly as it was.

| # | branch_name | Traders get |
|---|---|---|
| 0 | `inc-0-legacy-baseline` | The PDF report, as today (the "before") |
| 1 | `inc-1-web-instead-of-pdf` | A news feed **website** instead of the PDF, no AI yet |
| 2 | `inc-2-rule-based-checks` | **FAKE COMPANY / DUPLICATE / STALE / SPOOFED SOURCE** badges from rules, no LLM |
| 3 | `inc-3-first-ai` | AI **summaries, sentiment** and **"Ask the News"** chat with cited sources |
| 4 | `inc-4-ai-verification` | **4 verdicts** (VERIFIED / UNVERIFIED / MISLEADING / FAKE) with evidence, plus an analyst **review queue** |
| 5 | `inc-5-agents-and-skills` | The **pre-market brief** and multi-agent chat. **The PDF is retired.** |
| 6 | `inc-6-production` | A reliable brief **before 07:30 ET** every trading day, alerts, and the vendor scorecard |
| 7 | `inc-7-enterprise-cloud-theory` | *(Theory only)* How a large enterprise would build the same platform on **Azure, AWS and GCP** |
## Architecture by increment
**Legend:** 🟩 green = new in this increment · ⬜ grey = already there · 🟥 red dashed = retired

### Increment 0: Legacy baseline
The "before": a synthetic vendor feed, a multithreaded **C++11** ingester, PostgreSQL, and a PDF on an NFS share.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151

  VS["vendor-sim<br/>100 synthetic items/day<br/>(real + fake + duplicates)"]:::new
  CRON["supercronic<br/>05:30 ET"]:::new
  ING["legacy ingest (C++11)<br/>std::thread pool · libcurl · RapidJSON"]:::new
  PG[("PostgreSQL 17<br/>legacy.vendor_news_raw")]:::new
  REP["legacy report (C++11)<br/>libharu"]:::new
  PDF[/"PDF on NFS volume"/]:::new
  T(["Trader"])

  CRON --> ING
  VS -- "JSON feed" --> ING
  ING -- "COPY (libpq)" --> PG
  PG --> REP --> PDF --> T
```

### Increment 1: Web instead of PDF (no AI)
A website over the same legacy tables. The PDF keeps running in parallel.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151

  VS["vendor-sim"]:::old
  ING["legacy ingest (C++11)"]:::old
  PG[("PostgreSQL<br/>legacy tables")]:::old
  REP["legacy report → PDF<br/>(parallel run)"]:::old
  API["ai-api (FastAPI)<br/>/news · /auth"]:::new
  R[("Redis<br/>sessions")]:::new
  WEB["web (React + Vite + TS)<br/>login · news feed"]:::new
  T(["Trader"])

  VS --> ING --> PG
  PG --> REP
  PG --> API
  API <--> R
  API --> WEB --> T
  REP -. "PDF still delivered" .-> T
```

### Increment 2: Rule-based checks (no LLM)
Duplicates and obvious fakes are caught with cheap, deterministic checks before any AI. The modern **C++20** ingester starts running in parallel with the C++11 one, and a **C++20 native module** speeds up the Python checks.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151

  VS["vendor-sim"]:::old
  LING["legacy ingest (C++11)"]:::old
  NING["ingest (C++20)<br/>lock-free · simdjson · Abseil"]:::new
  PAR["parity check<br/>legacy = modern"]:::new
  PG[("PostgreSQL<br/>legacy + ingest + ai schemas")]:::old
  subgraph RULES["rule engine (ai-api)"]
    DD["dedup L0–L2<br/>URL · exact hash · SimHash"]:::new
    EC["entity check<br/>FAKE_COMPANY / FAKE_TICKER"]:::new
    SC["source check<br/>reputation · lookalike · stale"]:::new
  end
  FP["fastpath (C++20)<br/>nanobind module"]:::new
  R[("Redis<br/>dedup keys · caches")]:::new
  SEC["SEC EDGAR<br/>ticker registry"]:::new
  EVAL["eval harness v1<br/>golden set + CI"]:::new
  API["ai-api"]:::old
  WEB["web: badges<br/>FAKE · DUPLICATE · STALE"]:::new
  T(["Trader"])

  VS --> LING --> PG
  VS --> NING --> PG
  PG --> PAR
  PG --> DD --> EC --> SC --> PG
  DD <--> R
  FP -. "SimHash · hashing ·<br/>normalize" .-> DD
  EC <--> SEC
  PG --> API --> WEB --> T
  EVAL -. "measures" .-> RULES
```

### Increment 3: First AI
Local LLMs on a GPU host (switchable to OpenAI), LangChain, and a first RAG on ChromaDB.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151

  subgraph GPU["GPU host"]
    OL["Ollama<br/>3–4B LLM · embeddings"]:::new
  end
  OAI["OpenAI API<br/>(cloud switch)"]:::new
  GW["llm-gateway (LiteLLM)<br/>routing · budget"]:::new
  API["ai-api<br/>LangChain: extract · summary · sentiment"]:::new
  RAG["RAG v1<br/>retrieve → rerank → cite"]:::new
  CH[("ChromaDB<br/>trusted corpus")]:::new
  CORP["EDGAR 8-K + EX-99.1<br/>Fed / SEC releases"]:::new
  PG[("PostgreSQL<br/>ai.chunk text")]:::old
  LF["Langfuse traces"]:::new
  WEB["web: summaries<br/>+ Ask the News"]:::new
  T(["Trader"])

  CORP --> PG --> CH
  API --> GW
  GW --> OL
  GW --> OAI
  API --> RAG --> CH
  API -. traces .-> LF
  API --> WEB --> T
```

### Increment 4: AI verification
A LangGraph pipeline gives every item one of 4 verdicts, with evidence gathered through MCP tools, and asks a human when it's unsure.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151

  API["ai-api /runs"]:::old
  Q[("Redis<br/>arq queue · streams")]:::new
  W["ai-worker"]:::new
  subgraph G["LangGraph verify_news"]
    direction TB
    S1["sanitize + Llama Guard"]:::new
    S2["extract claims"]:::new
    S3["checks: entity · source ·<br/>corroboration · numbers"]:::new
    S4["aggregate: hard rules +<br/>LLM judge → verdict"]:::new
    S5{"confident?"}:::new
    S1 --> S2 --> S3 --> S4 --> S5
  end
  MCP["mcp-server<br/>web_search · fetch_url ·<br/>prices · lookup_company"]:::new
  HITL["Review Queue<br/>(Analyst)"]:::new
  PG[("PostgreSQL<br/>verdicts · evidence")]:::old
  WEB["web: verdict badges<br/>evidence · live progress"]:::new
  T(["Trader"])

  API --> Q --> W --> G
  S3 <--> MCP
  S5 -- "yes" --> PG
  S5 -- "no" --> HITL --> PG
  PG --> WEB --> T
```

### Increment 5: Agents and Skills (PDF retired)
Agents write the pre-market brief from verified news. After a 2-week parallel run, the PDF is switched off.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151
  classDef retired fill:#fee2e2,stroke:#dc2626,color:#7f1d1d,stroke-dasharray: 5 5

  PG[("PostgreSQL<br/>verified news")]:::old
  SUP["Supervisor agent"]:::new
  FC["Fact-Checker"]:::new
  MA["Market-Analyst"]:::new
  BW["Brief-Writer"]:::new
  SK["Agent Skills"]:::new
  MEM[("Memory<br/>watchlists · preferences")]:::new
  SEMC[("Redis<br/>semantic cache")]:::new
  MCP["mcp-server"]:::old
  WEB["web: Today's Brief (SSE)<br/>+ multi-agent chat"]:::new
  REP["legacy report → PDF"]:::retired
  T(["Trader"])

  PG --> SUP
  SUP --> FC
  SUP --> MA
  SUP --> BW
  FC <--> MCP
  MA <--> MCP
  SK -. guides .-> SUP
  SUP <--> MEM
  SUP <--> SEMC
  BW --> WEB --> T
  PG -.-x REP
```

### Increment 6: Production
Scheduled, monitored and measured: the C++20 ingester replaces the C++11 legacy one, pgvector replaces ChromaDB, the NYSE-calendar scheduler meets the 07:30 deadline, and the vendor scorecard shows what the vendor really delivered.

```mermaid
flowchart LR
  classDef new fill:#d1fae5,stroke:#059669,color:#064e3b
  classDef old fill:#f3f4f6,stroke:#9ca3af,color:#374151
  classDef retired fill:#fee2e2,stroke:#dc2626,color:#7f1d1d,stroke-dasharray: 5 5

  SCH["scheduler<br/>NYSE calendar · Redis lock<br/>06:00 verify → 07:15 brief"]:::new
  ING["ingest (C++20)<br/>the only ingester"]:::old
  LEG["legacy ingest (C++11)"]:::retired
  AI["ai-api + ai-worker<br/>+ agents"]:::old
  PGV[("PostgreSQL + pgvector<br/>hybrid search")]:::new
  CH[("ChromaDB")]:::retired
  subgraph OBS["observability profile"]
    OT["OpenTelemetry"]:::new
    PR["Prometheus"]:::new
    GR["Grafana<br/>SLA · cost · alerts"]:::new
    OT --> PR --> GR
  end
  SCORE["Vendor scorecard<br/>billable vs contracted"]:::new
  CI["CI eval gate<br/>self-hosted GPU runner"]:::new
  WEB["web: brief by 07:30 ET<br/>alert + budget banners"]:::old
  T(["Trader"])

  SCH --> ING
  LEG -. "replaced" .-> ING
  SCH --> AI
  AI <--> PGV
  CH -. "migrated" .-> PGV
  AI -. metrics .-> OT
  GR -. alerts .-> WEB
  PGV --> SCORE --> WEB
  CI -. "blocks regressions" .-> AI
  WEB --> T
```

### Increment 7: Enterprise AI on Azure / AWS / GCP (theory)
No code or deployment. It maps every component above to managed cloud services, and covers enterprise tools, services, security and MLOps.

## Tech stack
| Area | Technologies |
|---|---|
| Legacy C++ | **C++11** (Google style), CMake, libpq, libcurl, RapidJSON, libharu, GoogleTest |
| Modern C++ | **C++20** (Google style + low-latency rules), CMake, Abseil, simdjson, libpq, nanobind (Python module), GoogleTest, Google Benchmark |
| AI backend | Python 3.13, FastAPI, LangChain, LangGraph, LiteLLM, MCP (FastMCP), Agent Skills, arq |
| Models | Ollama on a GPU host (local 3–4B models, Llama Guard 3), OpenAI (default cloud), Claude / Gemini switchable |
| Data | PostgreSQL 17 (+ pgvector), ChromaDB (increments 3–5), Redis 8 |
| Web | React, Vite, TypeScript, TanStack Query, Tailwind, shadcn/ui |
| Quality | RAGAS, promptfoo, pytest, Vitest, clang-format / cpplint / clang-tidy |
| Observability | Langfuse, OpenTelemetry, Prometheus, Grafana |
| Runtime | Podman (rootless) in Ubuntu 24.04 on WSL2 · Ollama on a host with an NVIDIA GPU |

## Getting started
The setup is one-time and scripted:
1. **GPU host:** Ollama settings, firewall rule, and model pull.
2. **Ubuntu Linux or WSL:** `.wslconfig` and `/etc/wsl.conf`, then move the repo to `~/src/premarket-ai`, then Podman.
3. `scripts/wsl/check-ollama.sh` confirms that containers can reach Ollama.

Tested hardware: NVIDIA GTX 1650 (4 GB VRAM), 32 GB RAM. Run `scripts/hw-check.sh` / `scripts/hw-check.ps1` to see yours.

## C++ style guide
All C++ code follows the Google C++ Style Guide:
- [docs/Google_Cpp_Style_Guide_20260925.md](docs/Google_Cpp_Style_Guide_20260925.md): searchable Markdown copy with a table of contents
- [docs/Google_Cpp_Style_Guide_20260925.pdf](docs/Google_Cpp_Style_Guide_20260925.pdf): original print (2026-09-25)

## License
MIT © 2026 premarket-ai contributors. The Google C++ Style Guide copy in `docs/` is © Google; see its header for source and license.
