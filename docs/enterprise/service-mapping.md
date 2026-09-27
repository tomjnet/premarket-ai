# Service mapping: every lab component → Azure / AWS / GCP

> Last reviewed: 2026-09-26. Theory only. Cloud AI names change often; the renames of the last year are listed [below](#renames-to-know-2025-2026). Check each name against the provider's documentation before using this page in a design.

**Reading the table:** the first choice is the service a regulated enterprise would most likely pick; alternatives follow after a semicolon. "Keep" means the lab's code or open-source component carries over unchanged, running on the cloud's container platform.

## 1. Models and AI platform

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Platform umbrella** | **Microsoft Foundry** (formerly Azure AI Foundry) | **Amazon Bedrock** (+ Bedrock AgentCore for agents) | **Gemini Enterprise Agent Platform** (formerly Vertex AI) |
| **Hosted LLMs** (OpenAI, Claude, Gemini through the `cloud-*` aliases) | Foundry Models: Azure OpenAI models, Claude, Llama and others | Bedrock models: Claude, Llama, Amazon Nova, Mistral and others | Agent Platform Model Garden: Gemini, plus Claude and Llama "available on Gemini Enterprise Agent Platform" |
| **Self-hosted open models** (Ollama on the GPU host) | Foundry managed compute; AKS GPU node pools; Container Apps serverless GPUs | SageMaker AI real-time endpoints; EKS GPU nodes | Model Garden self-deployed endpoints; GKE GPU nodes; Cloud Run GPUs |
| **LLM gateway** (LiteLLM: aliases, keys, budgets, fallbacks) | API Management **AI gateway** (`llm-token-limit`, `llm-semantic-cache-*`, load balancing and circuit breaker across deployments; a dedicated AI Gateway tier is in preview) | No single first-party AI gateway: Bedrock cross-region inference profiles and application inference profiles (cost tags) behind API Gateway; or keep LiteLLM on EKS / ECS | Apigee AI gateway policies (`LLMTokenQuota`, prompt-token rate limits, semantic cache, Model Armor sanitize policies) |
| **Embeddings** (`nomic-embed-text`, 768 dimensions) | Azure OpenAI embedding models in Foundry Models | Titan Text Embeddings, Cohere Embed on Bedrock | Gemini embedding models on Agent Platform |
| **Reranker** (`bge-reranker-base`) | Azure AI Search semantic ranker | Bedrock rerank models (Amazon Rerank, Cohere Rerank) | Ranking API of Agent Search (formerly Vertex AI Search) |
| **Classic ML** (FinBERT, DistilBERT training and serving) | Azure Machine Learning training jobs + managed online endpoints | SageMaker AI training jobs + endpoints | Agent Platform custom training + endpoints |

## 2. RAG and data

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Vector store** (pgvector, hybrid search in one SQL query) | Azure Database for PostgreSQL Flexible Server + `pgvector` / `pg_diskann`; Azure AI Search (hybrid + semantic ranker) for large corpora | Aurora PostgreSQL / RDS + `pgvector`; OpenSearch Service vector engine; Amazon S3 Vectors (low-cost, very large indexes) | AlloyDB AI (ScaNN index) / Cloud SQL + `pgvector`; Vector Search on Agent Platform (Vector Search 2.0 is now **Agent Retrieval**) |
| **Managed RAG** (the lab builds its own) | Azure AI Search **agentic retrieval** ("knowledge bases") used by Foundry Agent Service | Bedrock Knowledge Bases (can store in S3 Vectors, OpenSearch, Aurora) | RAG Engine on Agent Platform; Agent Search |
| **Trusted corpus download** (SEC EDGAR, Fed) | Keep the `corpus` job, as a Container Apps job | Keep, as an ECS scheduled task | Keep, as a Cloud Run job |
| **PostgreSQL** (`ai.*`, `ingest.*`, LangGraph checkpoints and store) | Azure Database for PostgreSQL Flexible Server (Azure HorizonDB is a newer PostgreSQL service in preview) | Aurora PostgreSQL; RDS for PostgreSQL | AlloyDB for PostgreSQL; Cloud SQL for PostgreSQL |
| **Redis** (sessions, dedup L0–L3, locks, rate limits, streams) | Azure Managed Redis (replaces Azure Cache for Redis, which is being retired) | ElastiCache for Valkey | Memorystore for Valkey |
| **Semantic answer cache** (RedisVL) | APIM `llm-semantic-cache-*` policies backed by Azure Managed Redis; or keep RedisVL | Keep RedisVL on ElastiCache for Valkey (vector search) | Apigee semantic cache policies; or keep RedisVL on Memorystore |
| **Object storage** (raw feed, corpus files, eval datasets; the old NFS share) | Blob Storage; Azure Files (NFS) | S3; EFS | Cloud Storage; Filestore |
| **Data governance and DLP** | Microsoft Purview (Data Map, Data Security Posture Management) | SageMaker Catalog (built on DataZone), Lake Formation, Macie (PII discovery) | **Knowledge Catalog** (formerly Dataplex Universal Catalog), Sensitive Data Protection |

## 3. Agents and tools

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Agent runtime** (LangGraph: `verify_news`, supervisor, briefing agent) | Foundry Agent Service (hosted agents); or keep LangGraph on Container Apps / AKS | **Bedrock AgentCore Runtime** (hosts LangGraph, Strands, CrewAI or any framework). Bedrock Agents is now **Bedrock Agents Classic**, closed to new customers since 2026-07-30 | **Agent Runtime** on Agent Platform (formerly Agent Engine; hosts LangGraph and ADK agents) |
| **Agent framework** (LangGraph) | Keep LangGraph; Microsoft Agent Framework 1.0 (successor of Semantic Kernel and AutoGen) | Keep LangGraph; Strands Agents | Keep LangGraph; Agent Development Kit (ADK 2.0, with graph workflows) |
| **Long-term memory** (LangGraph store: watchlists) | Keep the LangGraph store in PostgreSQL; Azure Cosmos DB | AgentCore Memory; or keep the store | Agent Platform Memory Bank / Sessions; or keep the store |
| **MCP server and tools** (`mcp-server`, read-only tools) | Keep the MCP server on Container Apps behind APIM (MCP passthrough, or APIM exposing REST APIs as MCP servers); Foundry Agent Service MCP tool with authentication | Keep the MCP server; **AgentCore Gateway** (turns APIs and Lambda functions into MCP tools, with authentication) | Keep the MCP server; Agent Platform Gateway; Apigee in front of it |
| **Per-tool authorization** (tool allowlists) | APIM policies per product and subscription | **AgentCore Policy** (Cedar policies on tool calls) | Agent Platform Gateway with IAM |
| **Agent identity** (the lab's shared MCP service token) | **Microsoft Entra Agent ID** | AgentCore Identity | Agent Platform Identity |
| **Agent-to-agent** (A2A; not used in the lab) | A2A support in Foundry Agent Service / Microsoft Agent Framework | A2A in AgentCore Runtime; Strands Agents | A2A in ADK and Agent Runtime |
| **Agent Skills** (`python/skills/*/SKILL.md`) | Keep: files packaged with the agent image | Keep | Keep |
| **Web search** (SearXNG) and `fetch_url` | Grounding with Bing Search in Foundry | No first-party search API: a licensed search API behind AgentCore Gateway; AgentCore Browser for pages | Grounding with Google Search |
| **Market data and company registry** (yfinance, SEC registry; lab only) | Licensed market data (for example Bloomberg or LSEG) through internal APIs exposed as MCP tools | Same | Same |
| **Human in the loop** (LangGraph `interrupt()`, review queue) | Keep LangGraph interrupts; Durable Functions / Logic Apps approvals for workflow-level approval | Keep; Step Functions task tokens (`waitForTaskToken`) | Keep; Workflows callbacks |

## 4. Safety

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Content safety** (Llama Guard 3) | **Guardrails in Microsoft Foundry** (built on Azure AI Content Safety: harmful content, prompt attacks, document attacks, PII, task adherence) | **Bedrock Guardrails** (content filters, denied topics, PII, contextual grounding, Automated Reasoning checks) | **Model Armor** (part of Security Command Center AI Protection) |
| **Prompt-injection defence** (sanitize, spotlighting, data tags) | Prompt Shields for user prompts and documents (in Guardrails) + keep the lab's code | Bedrock Guardrails prompt-attack filter + keep the lab's code | Model Armor prompt-injection and jailbreak detection + keep the lab's code |
| **Domain rules** (no advice, verdict policy, citation checks) | Keep | Keep | Keep |

## 5. Application platform

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Containers** (Podman) | Azure Container Apps; AKS | ECS on Fargate; EKS | Cloud Run; GKE |
| **ai-api** (FastAPI) | Container Apps (internal ingress) | ECS Fargate service behind an internal ALB | Cloud Run (internal ingress) |
| **Queue + ai-worker** (taskiq on Redis Streams) | Service Bus + Container Apps (KEDA scaling on queue depth) | SQS (with a dead-letter queue) + ECS Fargate service; Lambda for short tasks | Pub/Sub + Cloud Run worker pools |
| **Scheduler** (APScheduler, NYSE calendar, SLA checks) | Container Apps scheduled jobs; Logic Apps / Durable Functions for the day's workflow | EventBridge Scheduler + Step Functions | Cloud Scheduler + Workflows |
| **C++20 ingester** (supercronic) and legacy C++11 batch | Container Apps jobs; Azure Batch | ECS scheduled tasks; AWS Batch | Cloud Run jobs; Batch |
| **C++ fastpath module** (nanobind, inside ai-api) | Keep: built into the API image | Keep | Keep |
| **Web front end** (two nginx replicas) | Static Web Apps; or Blob Storage static website | S3 + CloudFront | Cloud Storage + Cloud CDN; Firebase Hosting |
| **Edge proxy** (nginx: TLS, headers, rate limits) | Azure Front Door with WAF; Application Gateway WAF | CloudFront + AWS WAF; ALB | External Application Load Balancer + Cloud Armor |
| **Container images** | Azure Container Registry | Amazon ECR | Artifact Registry |

## 6. Identity, secrets and network

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **User login** (JWT, argon2id, three roles) | Microsoft Entra ID with app roles, MFA and Conditional Access | IAM Identity Center for the workforce; Cognito federated to the corporate IdP (or ALB OIDC) for the app | Cloud Identity / Workforce Identity Federation; Identity-Aware Proxy (IAP); Identity Platform |
| **Service credentials** (`.env` passwords, gateway key) | Managed identities | IAM roles (ECS task roles, EKS Pod Identity) | Service accounts; Workload Identity Federation |
| **Secrets** | Key Vault (Managed HSM for CMK) | Secrets Manager + KMS (CloudHSM) | Secret Manager + Cloud KMS (Cloud HSM) |
| **Private networking** (the Podman network) | Virtual networks, Private Link / private endpoints, Azure Firewall | VPC, PrivateLink / VPC endpoints, Network Firewall | VPC, Private Service Connect, VPC Service Controls, Cloud NGFW |
| **GPU host firewall rule** | Network security groups | Security groups | VPC firewall rules |

## 7. Observability, security operations and audit

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **LLM tracing** (Langfuse) | Foundry Observability (tracing, evaluations, monitoring); or hosted Langfuse | AgentCore Observability, CloudWatch; or hosted Langfuse | Agent Platform tracing in Cloud Trace; or hosted Langfuse |
| **OpenTelemetry Collector** (GenAI semantic conventions, still "Development" status upstream) | Azure Monitor OpenTelemetry Distro | AWS Distro for OpenTelemetry (ADOT) | Google-built OpenTelemetry Collector |
| **Prometheus + Grafana** | Azure Monitor managed service for Prometheus + Azure Managed Grafana | Amazon Managed Service for Prometheus + Amazon Managed Grafana | Google Cloud Managed Service for Prometheus + Cloud Monitoring dashboards (or Grafana) |
| **Alerts** (Redis Stream `alerts`, UI banner) | Azure Monitor alerts → action groups (Teams, email, ITSM) | CloudWatch alarms → SNS | Cloud Monitoring alerting → notification channels |
| **Audit tables** (90 days) | Blob Storage **immutable storage** (locked time-based retention) + Log Analytics | S3 **Object Lock** (compliance mode) + CloudTrail Lake | Cloud Storage **Bucket Lock** + Cloud Logging buckets with locked retention |
| **SIEM** (none in the lab) | Microsoft Sentinel | Security Lake + a SIEM; OpenSearch Service | Google Security Operations |
| **Security posture and threat detection** (none in the lab) | Defender for Cloud, incl. the **Defender for AI Services** plan | **AWS Security Hub** (new, GA December 2025) with GuardDuty, Inspector, Macie and **Security Hub CSPM** (the former Security Hub) | Security Command Center with **AI Protection** (Premium tier) |

## 8. Delivery, MLOps and cost

| Lab component | Azure | AWS | GCP |
|---|---|---|---|
| **Evals** (promptfoo, RAGAS, custom gates) | Keep the gates; Foundry evaluations in addition | Keep; Bedrock Evaluations (models, RAG) and **AgentCore Evaluations** (agents) | Keep; **Gemini Enterprise Agent Platform Evals** (formerly the Gen AI evaluation service) |
| **Pipelines and registry** (`ml-train`, pinned aliases) | Azure Machine Learning pipelines + registries | SageMaker AI Pipelines + Model Registry | Agent Platform Pipelines + Model Registry on Agent Platform |
| **CI/CD** (GitHub Actions, self-hosted GPU runner) | GitHub Actions or Azure DevOps (managed DevOps pools with GPU) | GitHub Actions; CodePipeline + CodeBuild | GitHub Actions; Cloud Build + Cloud Deploy |
| **Infrastructure as code** (`compose.yaml`) | Bicep; Terraform (Azure Verified Modules) | CloudFormation; CDK; Terraform | Terraform (Infrastructure Manager) |
| **Landing zone** | Azure landing zones (Cloud Adoption Framework) | AWS Control Tower + Landing Zone Accelerator | Enterprise foundations blueprint (Terraform) |
| **Cloud budget** (`LLM_MONTHLY_BUDGET_USD`, cloud switches) | Cost Management budgets + APIM token metrics per consumer | AWS Budgets + cost allocation tags on application inference profiles | Cloud Billing budgets + Apigee token quotas |

## Renames to know (2025–2026)

| Before | Now | When |
|---|---|---|
| Azure AI Foundry | **Microsoft Foundry** (old portal: "Foundry (classic)") | November 2025 |
| Azure AI Agent Service | **Foundry Agent Service** (next generation GA) | GA 2026-03-16 |
| Semantic Kernel + AutoGen | **Microsoft Agent Framework** 1.0 | 2026-04-02 |
| Azure AI Content Safety + Prompt Shields as separate settings | **Guardrails** in Microsoft Foundry (Content Safety APIs still exist) | 2025–2026 |
| Azure Cache for Redis | **Azure Managed Redis** (old tiers retire 2027–2028) | — |
| Purview DSPM for AI | Unified **Data Security Posture Management** | 2026 |
| Amazon SageMaker (ML service) | **SageMaker AI** | December 2024 |
| Amazon Bedrock Agents | **Bedrock Agents Classic** (maintenance mode; use AgentCore) | 2026-07-30 |
| AWS Security Hub (original) | **Security Hub CSPM**; the new **AWS Security Hub** correlates findings | December 2025 |
| Vertex AI | **Gemini Enterprise Agent Platform** | 2026-04-22 |
| Vertex AI Agent Engine | **Agent Runtime** | 2026-04-22 |
| Vertex AI Search | **Agent Search** | 2026-04-22 |
| Vertex AI Vector Search / Vector Search 2.0 | **Vector Search on Agent Platform** / **Agent Retrieval** | 2026-04-22 |
| Vertex AI Studio | **Agent Studio** | 2026-04-22 |
| Gen AI evaluation service | **Gemini Enterprise Agent Platform Evals** | 2026-04-22 |
| Google Agentspace | **Gemini Enterprise** (the workplace app, not the developer platform) | late 2025 |
| Dataplex Universal Catalog | **Knowledge Catalog** | 2026-04-10 |

## Verification notes
- Checked against the providers' official documentation and blogs on 2026-09-26: the platform umbrellas, agent runtimes and frameworks, guardrail services, AI gateways, Azure Managed Redis, Azure Database for PostgreSQL (`pg_diskann`, HorizonDB), Container Apps serverless GPUs, Purview DSPM, Defender for AI Services, Entra Agent ID, Bedrock Knowledge Bases, Guardrails, Evaluations, S3 Vectors, SageMaker AI, SageMaker Catalog, AWS Security Hub, AgentCore (Runtime, Gateway, Memory, Identity, Observability, Policy, Evaluations, A2A), Strands Agents, every Agent Platform rename, ADK 2.0, Model Armor, SCC AI Protection, Apigee AI policies, Memorystore for Valkey, AlloyDB AI, Cloud Run GPUs and Knowledge Catalog.
- Carried over without an individual check (no rename found): OpenSearch Service, Aurora / RDS pgvector, Lake Formation, Macie, GuardDuty, Inspector, ElastiCache for Valkey, EventBridge Scheduler, Step Functions, IAM Identity Center, Cloud SQL, Cloud Run jobs, Cloud Scheduler, Workflows, Sensitive Data Protection, Identity Platform, IAP, Grounding with Bing Search, Grounding with Google Search, the rerank models and ranking API, Cloud Run worker pools, and the general-purpose infrastructure services (networking, storage, registries, IaC, monitoring).
- Not confirmed: the per-component GA or preview status inside Gemini Enterprise Agent Platform, and the current model versions each cloud offers.
