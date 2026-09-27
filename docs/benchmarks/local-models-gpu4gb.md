# Local model benchmark: `gpu4gb`

Run 2026-09-26 on the GPU host through the LLM gateway. 50 labeled vendor-sim items (seed 42, 2026-09-24/25: 22 real, 16 FAKE, 12 MISLEADING). Command: `make -C python bench-models`.

| Model | Verdict acc. | Verdict macro-F1 | Ticker recall | Structured output | Tool calls | Tokens/s | VRAM (MiB) | Min / 100 items |
|---|---|---|---|---|---|---|---|---|
| Qwen3 4B Instruct 2507 (`qwen3:4b-instruct`) **(winner)** | 0.78 | 0.79 | 1.00 | 1.00 | 1.00 | 11.5 | 2200 | 19.8 |
| Llama 3.2 3B (`llama3.2:3b`) | 0.44 | 0.16 | 1.00 | 1.00 | 1.00 | 20.0 | 2200 | 11.8 |
| Phi-4-mini 3.8B (`phi4-mini`) | 0.40 | 0.21 | 0.96 | 1.00 | 0.00 | 13.1 | 2212 | 16.9 |
| Gemma 3 4B (`gemma3:4b`) | 0.48 | 0.25 | 0.96 | 1.00 | 0.00 | 8.9 | 1495 | 25.5 |

- **Verdict** is from the text alone (no tools or evidence yet); increment 4 adds the checks, so it only compares the models.
- **Min / 100 items**: extract + summary, one call at a time (the AI run keeps two in flight).
- **Winner**: structured output >= 0.95, then the best average of verdict macro-F1 and ticker recall, then the fastest. It is pinned as `main-gpu4gb` in `podman/config/litellm/config.yaml`.
