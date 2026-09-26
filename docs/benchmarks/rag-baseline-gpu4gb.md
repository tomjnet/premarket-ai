# RAG baseline: `gpu4gb`

Run 2026-09-26: 30 questions (`python/ai-api/evals/datasets/rag_questions.jsonl`) through the "Ask the News" chain, main model `main-gpu4gb`, corpus of 4978 chunks. Command: `make -C python eval-rag`.

| Metric | Value |
|---|---|
| cites_trusted | 1.00 |
| advice_refused | 1.00 |
| ragas.faithfulness | 0.97 |
| ragas.context_precision | 0.98 |
| judge_failures | 11.00 |

- **cites_trusted**: answers citing at least one trusted source (SEC, Fed).
- **advice_refused**: advice questions answered with a refusal.
- **ragas.***: judged by the same local model, so they compare runs of this lab, not models from other labs.
