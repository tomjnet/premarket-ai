# AI engineer vs ML engineer

> Last reviewed: 2026-09-26. Job titles aren't standardized: companies use them loosely, and many job posts mix both. This page describes the **typical** split in 2026, and shows which parts of premarket-ai belong to which role.

## In one sentence
- An **ML engineer** builds, trains and serves **models**: data in, a trained model out, and the pipeline that keeps it accurate in production.
- An **AI engineer** builds **applications on top of existing models** (mostly foundation models and LLMs): prompts, RAG, agents, tools, guardrails and evals, shipped as a product.

A simple way to remember it: the ML engineer's main output is a **model**; the AI engineer's main output is a **product that uses models**.

## Side by side

| Topic | ML engineer | AI engineer |
|---|---|---|
| **Starting point** | A dataset and a prediction problem | An existing model (API or open-weight) and a user problem |
| **Main question** | "Can we train a model that predicts this well enough?" | "Can we make a reliable product with the models we have?" |
| **Main output** | A trained, versioned model plus its training and serving pipeline | An application: APIs, RAG, agents, tools, UI integration |
| **Data work** | Heavy: collection, labeling, feature engineering, train/validation/test splits, data quality | Lighter but different: document ingestion and chunking, golden sets for evals, feedback data |
| **Model work** | Chooses architectures, trains, tunes hyperparameters, fine-tunes, distills, quantizes | Chooses and compares models, writes prompts, routes between small and large models; fine-tunes only when justified |
| **Typical techniques** | Supervised learning, gradient boosting, deep learning, embeddings training, distributed training | Prompt and context engineering, structured output, RAG, hybrid search, reranking, tool calling, multi-agent graphs, MCP, semantic caching |
| **Quality** | Offline metrics (accuracy, F1, AUC, RMSE), cross-validation, drift monitoring | Evals of whole behaviours: faithfulness, citation accuracy, LLM-as-judge, red-team suites, regression gates in CI |
| **Failure modes they fight** | Overfitting, data leakage, training/serving skew, drift | Hallucination, prompt injection, excessive agency, runaway cost, latency |
| **Production concerns** | Feature stores, training pipelines, model registry, GPU clusters, batch and online serving, retraining schedules | LLM gateway, token budgets, tracing, guardrails, human review, prompt and model version pinning |
| **Math depth** | High: statistics, linear algebra, optimization | Moderate: enough to understand embeddings, sampling, metrics and evals |
| **Software engineering depth** | Solid (Python, pipelines, data systems) | High: APIs, async code, distributed systems, security, front-end integration |
| **Typical tools** | PyTorch, scikit-learn, XGBoost, Hugging Face Transformers, Spark, MLflow, Kubeflow, SageMaker AI / Gemini Enterprise Agent Platform (formerly Vertex AI) / Azure Machine Learning training | LangChain, LangGraph, LiteLLM, MCP SDKs, vector databases (pgvector, OpenSearch, AI Search), Langfuse, RAGAS, promptfoo, Bedrock / Agent Platform / Microsoft Foundry model APIs |
| **Closest neighbours** | Data scientist, data engineer, research engineer | Backend / full-stack engineer, platform engineer, product engineer |
| **Cost driver** | GPU hours for training | Tokens per request at inference time |

## How they overlap
Both roles share a lot, and the line keeps moving:
- **Evaluation discipline:** both need golden sets, honest metrics and regression gates.
- **Serving and MLOps:** both deploy models behind APIs and monitor them (latency, cost, drift).
- **Embeddings:** the ML engineer may train or fine-tune them; the AI engineer indexes and searches with them.
- **Fine-tuning:** when prompting and RAG aren't enough, an AI engineer fine-tunes (often with an ML engineer's help or a managed service).
- **Small models next to LLMs:** strong AI systems combine an LLM with cheap classic models (classifiers, rerankers) for speed and cost; building those is ML engineering.

In small teams one person does both. In large enterprises they are usually separate teams: an **ML platform team** (training infrastructure, feature store, model registry) and **AI application teams** (products on top of the model platform), with a governance function (model risk management) reviewing both.

## Who built what in premarket-ai

| Part of the lab | Role | Why |
|---|---|---|
| DistilBERT verdict classifier (`ml/`, `make -C python ml-train`) | **ML engineer** | Labeled data, a train split that never touches the golden set's seed, fine-tuning, evaluated against a baseline |
| FinBERT sentiment and the reranker (`bge-reranker-base`) | **ML engineer** (selection and serving) | Choosing, packaging and serving pretrained task models on CPU |
| Quantized local models on a 4 GB GPU, the model benchmark (`bench-models`) | **Both** | Model selection and memory trade-offs (ML); latency and quality per task alias (AI) |
| Embedding model choice and the pgvector migration with overlap@k | **Both** | Embedding quality and index tuning (ML); retrieval inside the product (AI) |
| LLM gateway aliases, cloud budget and switches (`llm/`) | **AI engineer** | Routing, fallbacks and cost of foundation models |
| Enrichment prompts and structured output (`enrich/`) | **AI engineer** | Prompt engineering with strict schemas |
| RAG: chunking, hybrid search, reranking, citations, semantic cache (`rag/`) | **AI engineer** | Grounded answers from a curated corpus |
| `verify_news` LangGraph workflow, the LLM judge and the verdict policy (`verify/`) | **AI engineer** | A deterministic workflow with a model deciding only the uncertain middle |
| Multi-agent chat, Agent Skills, long-term memory (`agents/`, `python/skills/`) | **AI engineer** | Supervisor and specialists with tool allowlists |
| MCP server and its read-only tools (`python/mcp-server/`) | **AI engineer** | Standard tool interface for agents |
| Guardrails: sanitize, spotlighting, Llama Guard, output checks (`guard/`) | **AI engineer** | Defending an LLM application against injection and unsafe output |
| Human review queue and labeled examples from overrides | **Both** | The HITL product flow (AI) feeds new training and eval labels (ML) |
| Eval harness: confusion matrix, RAGAS, red-team checks, CI gates (`evals/`) | **Both** | Classic classification metrics (ML) plus LLM behaviour evals (AI) |
| OpenTelemetry GenAI metrics, Langfuse traces, drift signal (override rate) | **Both** (LLMOps / MLOps) | Monitoring models in production |
| C++ ingesters, the scheduler, the website | Neither: **software / platform engineering** | The rest of the system both roles depend on |

## Skills to learn, in order

**Toward ML engineer**
1. Python, NumPy, pandas; statistics and linear algebra basics.
2. scikit-learn: classification, regression, cross-validation, metrics.
3. Deep learning with PyTorch; Hugging Face Transformers; fine-tuning a small model (like the lab's DistilBERT).
4. Data pipelines, experiment tracking and a model registry (for example MLflow).
5. Serving and monitoring: batch vs online inference, drift, retraining.
6. A managed ML platform: SageMaker AI, Gemini Enterprise Agent Platform (formerly Vertex AI) or Azure Machine Learning.

**Toward AI engineer**
1. Solid backend engineering: Python, async APIs (FastAPI), SQL, containers, security basics.
2. LLM APIs, prompting and structured output; an LLM gateway.
3. RAG: chunking, embeddings, vector and hybrid search, reranking, citations.
4. Evals: golden sets, RAG metrics, LLM-as-judge, red-team tests, CI gates.
5. Agents: tool calling, LangGraph, MCP, human in the loop, memory.
6. LLMOps: tracing, cost control, guardrails, and a managed model platform (Amazon Bedrock, Gemini Enterprise Agent Platform or Microsoft Foundry).

## Job-title variations you will see
- **Applied AI engineer, GenAI engineer, LLM engineer:** usually the AI engineer role.
- **Applied scientist, research engineer:** closer to ML, often with research and publications.
- **MLOps engineer, ML platform engineer:** the infrastructure side of ML engineering.
- **Data scientist:** analysis and modeling, usually with less production engineering than an ML engineer.
- **AI architect / AI platform engineer:** designs the enterprise platform both roles build on (see `reference-architecture.md`).
