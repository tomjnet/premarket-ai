# Enterprise AI on Azure, AWS and GCP (increment 7)

> Last reviewed: 2026-09-26. **Theory only:** documentation and diagrams, no cloud resources and no cost.

How a **large regulated enterprise** (a bank, broker-dealer or asset manager) would build premarket-ai on a hyperscaler, and how that compares with the lab built in increments 0–6.

## Documents

| Document | What it covers |
|---|---|
| [reference-architecture.md](reference-architecture.md) | The cloud-neutral enterprise architecture: principles, building blocks, a trading day, environments |
| [service-mapping.md](service-mapping.md) | Every lab component and its Azure, AWS and GCP service, plus the 2025–2026 renames |
| [azure.md](azure.md) | The architecture on Azure (Microsoft Foundry, API Management AI gateway, Container Apps) |
| [aws.md](aws.md) | The architecture on AWS (Amazon Bedrock, Bedrock AgentCore, ECS on Fargate) |
| [gcp.md](gcp.md) | The architecture on GCP (Gemini Enterprise Agent Platform, Apigee, Cloud Run) |
| [security.md](security.md) | Enterprise AI security controls, OWASP LLM and agentic risks, frameworks, and a checklist, each mapped to the lab |
| [mlops-llmops.md](mlops-llmops.md) | The lifecycle: data, build, evaluate, approve, release, monitor, improve, FinOps, each mapped to the lab |
| [build-vs-buy.md](build-vs-buy.md) | When a managed service beats the open-source lab stack, component by component |
| [ai-glossary.md](ai-glossary.md) | AI terms, each with where it appears in premarket-ai |
| [ai-engineer-vs-ml-engineer.md](ai-engineer-vs-ml-engineer.md) | The two roles compared, and which parts of the lab belong to each |

## Suggested reading order
1. `ai-glossary.md` if any term is new.
2. `reference-architecture.md`, then `service-mapping.md`.
3. The provider page you care about.
4. `security.md` and `mlops-llmops.md`: what separates a lab from production.
5. `build-vs-buy.md` and `ai-engineer-vs-ml-engineer.md`.

## Done when (increment 7)
- [x] Every lab component has its cloud equivalent explained (`service-mapping.md`, sections 1–8, and the three provider pages).
- [x] The security chapter maps each enterprise control to what the lab does, or doesn't do (`security.md`, with ✅ / 🟡 / ❌ per control).
- [x] The MLOps chapter maps each lifecycle practice to what the lab does, or doesn't do (`mlops-llmops.md`).
- [x] Every page is date-stamped and cloud names were checked against the providers' current documentation (see "Verification notes" in `service-mapping.md`).

## Keeping these pages current
Cloud AI products are renamed often (Vertex AI became Gemini Enterprise Agent Platform in April 2026; Azure AI Foundry became Microsoft Foundry in November 2025). When you update a page, re-check the names against the provider's documentation and change its "Last reviewed" date.
