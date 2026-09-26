# premarket-ai task runner. Run from the repo root:
#   make -C python <task> [DATE=YYYY-MM-DD]
# Everything builds, runs and tests inside containers (ENGINE=docker works too).

ENGINE ?= podman
COMPOSE ?= $(ENGINE) compose
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PREFIX ?= localhost/premarket-ai
DATE ?= $(shell TZ=America/New_York date +%F)
# Earlier days ingested by `demo`, so stale duplicates can be caught.
HISTORY_DAYS ?= 5

LEGACY_BUILD = $(ENGINE) build -f podman/legacy/Containerfile cpp/legacy
INGEST_BUILD = $(ENGINE) build -f podman/ingest/Containerfile cpp/ingest
# Named build contexts: the lab universe (config), the C++20 fastpath module
# built into ai-api, and vendor-sim's generator for the eval stage.
VENDOR_BUILD = $(ENGINE) build -f podman/vendor-sim/Containerfile \
  --build-context config=python/config python/vendor-sim
API_BUILD = $(ENGINE) build -f podman/ai-api/Containerfile \
  --build-context fastpath=cpp/fastpath --build-context config=python/config \
  --build-context vendorsim=python/vendor-sim python/ai-api
WEB_BUILD = $(ENGINE) build -f podman/web/Containerfile ui/web
MCP_BUILD = $(ENGINE) build -f podman/mcp-server/Containerfile \
  --build-context config=python/config python/mcp-server
# The GPU evals run on the compose network (gateway, chroma, reranker).
EVAL_RUN = $(COMPOSE) --profile eval run --rm --no-deps ai-eval
PSQL = $(COMPOSE) exec -T postgres psql -U premarket -d premarket
# Increment 1 runs the legacy pipeline and the website side by side;
# increment 2 adds the C++20 ingester (profile legacy) and the rule checks;
# increment 3 adds the LLM gateway, chroma and the reranker (profile ai);
# increment 4 adds ai-worker, mcp-server and searxng (profile ai).
# `run` always uses --no-deps: with Podman, compose recreates the running
# postgres for every `run` with dependencies, and ai-api would lose its
# connections for a few seconds. `up` (or `demo`) starts everything first.
PROFILES = --profile legacy --profile ai
# Secrets `env` fills with random values when .env has them empty or missing.
SECRETS = JWT_SECRET REDIS_PASSWORD AI_DB_PASSWORD LLM_GATEWAY_KEY \
  LANGFUSE_KEY_ID LANGFUSE_SECRET LANGFUSE_DB_PASSWORD \
  LANGFUSE_CLICKHOUSE_PASSWORD LANGFUSE_MINIO_PASSWORD \
  LANGFUSE_REDIS_PASSWORD LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY \
  LANGFUSE_NEXTAUTH_SECRET LANGFUSE_INIT_USER_PASSWORD \
  WORKER_DB_PASSWORD MCP_DB_PASSWORD MCP_SERVICE_TOKEN SEARXNG_SECRET
# Settings added to an older .env (from increments 0 and 1).
NEW_SETTINGS = WEB_PORT WEB_BIND DEMO_USER_PASSWORD ACCESS_TOKEN_TTL_S \
  REFRESH_TOKEN_TTL_S LOGIN_MAX_FAILURES LOGIN_LOCKOUT_S \
  LAB_UNIVERSE_SIZE INGEST_WORKERS INGEST_QUEUE_CAPACITY \
  INGEST_DEDUP_WINDOW_DAYS INGEST_CPU_AFFINITY SEC_USER_AGENT \
  REGISTRY_MAX_AGE_DAYS STALE_MAX_AGE_DAYS DEDUP_WINDOW_DAYS \
  DEDUP_SIMHASH_NGRAM DEDUP_SIMHASH_MAX_HAMMING DEDUP_NEAR_MAX_WORD_EDITS \
  LLM_CONCURRENCY OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY \
  DEDUP_COSINE_MIN DEDUP_PARAPHRASE_MIN_WORD_EDITS RAG_TOP_K RAG_TOP_N \
  RERANKER_MODEL RERANKER_MEM RERANKER_THREADS CORPUS_MONTHS CORPUS_MAX_FILINGS CORPUS_MAX_RELEASES \
  LANGFUSE_TRACING LANGFUSE_PORT LANGFUSE_INIT_USER_EMAIL \
  HITL_CONFIDENCE_MIN JUDGE_CLOUD_MODEL LLM_MONTHLY_BUDGET_USD LLAMA_GUARD   GUARD_NEWS_REVIEW \
  ML_BASELINE WORKER_CONCURRENCY WORKER_MEM MCP_BIND MCP_PORT \
  WEB_SEARCH_PER_MIN PRICES_PER_MIN
WEB_PORT ?= $(shell grep -s '^WEB_PORT=' $(ROOT)/.env | cut -d= -f2)

.DEFAULT_GOAL := help
.PHONY: help env build up down logs ps test lint cpp-test cpp-lint \
        cpp-asan cpp-tsan cpp-bench sanitizers check demo ingest report \
        runs pdf feed-summary psql reset api-test api-lint web-image smoke \
        enrich corpus reindex llm-status ai-runs eval-image eval-ai \
        bench-models eval-rag obs-up obs-down verify demo-open \
        verify-runs review-queue mcp-test mcp-lint mcp-tools mcp-call \
        ml-train worker-logs \
        web openapi audit ingest-legacy ingest-modern parity rules registry \
        dedup-rebuild rule-runs eval bench ingest-test ingest-lint \
        ingest-asan ingest-tsan fastpath-test fastpath-lint fastpath-asan

help: ## List the tasks
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

env: ## Create .env from .env.example and fill empty secrets with random values
	@cd $(ROOT) && [ -f .env ] || { cp .env.example .env && echo "created .env"; }
	@cd $(ROOT) && for key in $(NEW_SETTINGS); do \
	  grep -q "^$$key=" .env || grep "^$$key=" .env.example >> .env; \
	done
	@cd $(ROOT) && for key in $(SECRETS); do \
	  value=$$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'); \
	  if grep -q "^$$key=$$" .env; then \
	    sed -i "s/^$$key=$$/$$key=$$value/" .env && echo "generated $$key"; \
	  elif ! grep -q "^$$key=" .env; then \
	    echo "$$key=$$value" >> .env && echo "generated $$key"; \
	  fi; \
	done
	@chmod 600 $(ROOT)/.env

# --- build and run ----------------------------------------------------------
build: env ## Build the images (vendor-sim, legacy, ingest, ai-api, worker, mcp, web)
	cd $(ROOT) && $(VENDOR_BUILD) --target runtime -t $(PREFIX)/vendor-sim:dev
	cd $(ROOT) && $(LEGACY_BUILD) --target runtime -t $(PREFIX)/legacy:dev
	cd $(ROOT) && $(INGEST_BUILD) --target runtime -t $(PREFIX)/ingest:dev
	cd $(ROOT) && $(API_BUILD) --target runtime -t $(PREFIX)/ai-api:dev
	cd $(ROOT) && $(API_BUILD) --target worker -t $(PREFIX)/ai-api:worker
	cd $(ROOT) && $(MCP_BUILD) --target runtime -t $(PREFIX)/mcp-server:dev
	cd $(ROOT) && $(WEB_BUILD) --target runtime -t $(PREFIX)/web:dev

up: build ## Build (cached) and start everything: both ingesters + website
	cd $(ROOT) && $(COMPOSE) $(PROFILES) up -d --wait
	@$(MAKE) --no-print-directory web

down: ## Stop the stack (volumes are kept)
	cd $(ROOT) && $(COMPOSE) --profile full down

logs: ## Follow the logs of all services
	cd $(ROOT) && $(COMPOSE) $(PROFILES) logs -f --tail=100

ps: ## Show service status
	cd $(ROOT) && $(COMPOSE) $(PROFILES) ps

reset: ## Stop the stack and DELETE its volumes (database, PDFs, labels)
	cd $(ROOT) && $(COMPOSE) --profile full down -v

web: ## Print the website URL and the demo logins
	@echo "Website: http://localhost:$(or $(WEB_PORT),8080)"
	@echo "Logins:  trader1, analyst1, admin1 (password: DEMO_USER_PASSWORD in .env)"
	@echo "Review:  analyst1 or admin1 -> Review queue; MCP: make -C python mcp-tools"

obs-up: ## Start Langfuse (profile observability); set LANGFUSE_TRACING=true
	cd $(ROOT) && $(COMPOSE) --profile observability up -d --wait
	@echo "Langfuse: http://localhost:$(or $(LANGFUSE_PORT),3000)"
	@echo "Login:    LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD in .env"

obs-down: ## Stop Langfuse (its volumes are kept)
	cd $(ROOT) && $(COMPOSE) --profile observability stop

# --- tests ------------------------------------------------------------------
test: ## Unit tests: pytest (vendor-sim, ai-api + parity, mcp) + GoogleTest (C++)
	cd $(ROOT) && $(VENDOR_BUILD) --target test -t $(PREFIX)/vendor-sim:test
	$(MAKE) --no-print-directory api-test
	$(MAKE) --no-print-directory mcp-test
	$(MAKE) --no-print-directory cpp-test
	$(MAKE) --no-print-directory ingest-test
	$(MAKE) --no-print-directory fastpath-test

lint: ## Style: ruff + clang-format/cpplint/clang-tidy (all C++ projects)
	cd $(ROOT) && $(VENDOR_BUILD) --target lint -t $(PREFIX)/vendor-sim:lint
	$(MAKE) --no-print-directory api-lint
	$(MAKE) --no-print-directory mcp-lint
	$(MAKE) --no-print-directory cpp-lint
	$(MAKE) --no-print-directory ingest-lint
	$(MAKE) --no-print-directory fastpath-lint

api-test: ## ai-api pytest (auth, news, rules, dedup, C++ vs Python parity)
	cd $(ROOT) && $(API_BUILD) --target test -t $(PREFIX)/ai-api:test

api-lint: ## ai-api ruff
	cd $(ROOT) && $(API_BUILD) --target lint -t $(PREFIX)/ai-api:lint

mcp-test: ## mcp-server pytest (tools, SSRF guard, token, host check)
	cd $(ROOT) && $(MCP_BUILD) --target test -t $(PREFIX)/mcp-server:test

mcp-lint: ## mcp-server ruff
	cd $(ROOT) && $(MCP_BUILD) --target lint -t $(PREFIX)/mcp-server:lint

web-image: ## Build only the web image (production UI bundle + nginx)
	cd $(ROOT) && $(WEB_BUILD) --target runtime -t $(PREFIX)/web:dev

eval: ## Rule/dedup + rules-only verdict eval on the golden set (gates)
	cd $(ROOT) && $(API_BUILD) --target eval -t $(PREFIX)/ai-api:eval

eval-image: ## Build the GPU eval image (L3, verdicts, benchmark, RAGAS, ml-train)
	cd $(ROOT) && $(API_BUILD) --target ai-eval -t $(PREFIX)/ai-api:ai-eval

eval-ai: eval-image ## L3 + guard eval, verdicts with the LLM judge (GPU host)
	cd $(ROOT) && $(EVAL_RUN) python -m evals.ai_eval --check
	cd $(ROOT) && $(EVAL_RUN) python -m evals.verify_eval --judge --ml \
	  --check --out /out

ml-train: eval-image ## Fine-tune the DistilBERT baseline (CPU, ~10 min)
	cd $(ROOT) && $(EVAL_RUN) ai-api ml-train

bench-models: eval-image ## Local model benchmark -> docs/benchmarks (GPU host)
	cd $(ROOT) && $(EVAL_RUN) python -m evals.bench_models --out /out

eval-rag: eval-image ## RAGAS baseline of "Ask the News" -> docs/benchmarks
	cd $(ROOT) && $(EVAL_RUN) python -m evals.rag_eval --out /out

cpp-test: ## C++11 legacy: debug build + ctest
	cd $(ROOT) && $(LEGACY_BUILD) --target test -t $(PREFIX)/legacy:test

cpp-lint: ## C++ clang-format, cpplint, clang-tidy
	cd $(ROOT) && $(LEGACY_BUILD) --target lint -t $(PREFIX)/legacy:lint

cpp-asan: ## C++ tests under AddressSanitizer + UBSan
	cd $(ROOT) && $(LEGACY_BUILD) --target asan -t $(PREFIX)/legacy:asan

cpp-tsan: ## C++ tests under ThreadSanitizer
	cd $(ROOT) && $(LEGACY_BUILD) --target tsan -t $(PREFIX)/legacy:tsan

ingest-test: ## C++20 ingester: debug build + ctest
	cd $(ROOT) && $(INGEST_BUILD) --target test -t $(PREFIX)/ingest:test

ingest-lint: ## C++20 ingester: clang-format, cpplint, clang-tidy
	cd $(ROOT) && $(INGEST_BUILD) --target lint -t $(PREFIX)/ingest:lint

ingest-asan: ## C++20 ingester under ASan + UBSan
	cd $(ROOT) && $(INGEST_BUILD) --target asan -t $(PREFIX)/ingest:asan

# seccomp=unconfined lets the stage run ctest with ASLR off (setarch -R):
# GCC 14's TSan aborts with the high ASLR entropy of the WSL kernel.
ingest-tsan: ## C++20 ingester under TSan (lock-free queue, worker pool)
	cd $(ROOT) && $(INGEST_BUILD) --security-opt seccomp=unconfined \
	  --target tsan -t $(PREFIX)/ingest:tsan

fastpath-test: ## C++20 fastpath core: debug build + ctest
	cd $(ROOT) && $(API_BUILD) --target fastpath-test -t $(PREFIX)/fastpath:test

fastpath-lint: ## C++20 fastpath: clang-format, cpplint, clang-tidy
	cd $(ROOT) && $(API_BUILD) --target fastpath-lint -t $(PREFIX)/fastpath:lint

fastpath-asan: ## C++20 fastpath core under ASan + UBSan
	cd $(ROOT) && $(API_BUILD) --target fastpath-asan -t $(PREFIX)/fastpath:asan

sanitizers: cpp-asan cpp-tsan ingest-asan ingest-tsan fastpath-asan ## All sanitizer builds

cpp-bench: ## Build and run the legacy micro-benchmarks
	cd $(ROOT) && $(LEGACY_BUILD) --target bench -t $(PREFIX)/legacy:bench
	$(ENGINE) run --rm $(PREFIX)/legacy:bench

bench: cpp-bench ## Legacy (C++11) vs modern (C++20) micro-benchmarks
	cd $(ROOT) && $(INGEST_BUILD) --target bench -t $(PREFIX)/ingest:bench
	$(ENGINE) run --rm $(PREFIX)/ingest:bench

check: test lint sanitizers eval ## Everything CI runs

# The increment's "done when", through the edge: C++20 parity PASS, the rule
# run DONE, the feed hides exactly the rule duplicates and shows FAKE badges,
# every unique item has a verdict with evidence, low-confidence items wait in
# the review queue (an analyst approves one and the worker resumes it), plus
# the security checks of increment 1.
smoke: ## Website check for DATE: verdicts, review, rules, login, headers
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api smoke --base-url http://edge:8080 --date $(DATE)

openapi: ## Write the ai-api OpenAPI document to out/openapi.json
	@mkdir -p $(ROOT)/out
	$(ENGINE) run --rm $(PREFIX)/ai-api:dev ai-api openapi > $(ROOT)/out/openapi.json
	@echo "OpenAPI: $(ROOT)/out/openapi.json"

audit: ## Last 20 auth events (logins, failures, lockouts, logouts)
	@cd $(ROOT) && $(PSQL) -c "SELECT to_char(at AT TIME ZONE \
	  'America/New_York', 'MM-DD HH24:MI:SS') AS at_et, action, actor, \
	  client_ip FROM ai.audit_log ORDER BY id DESC LIMIT 20"

# --- the demo day -----------------------------------------------------------
demo: up ## Whole day: history + DATE (ingest, rules, AI, verify), corpus, PDF, check
	@for i in $$(seq $(HISTORY_DAYS) -1 1); do \
	  d=$$(date -d "$(DATE) -$$i day" +%F); \
	  echo "== history $$d"; \
	  $(MAKE) --no-print-directory ingest parity rules DATE=$$d || exit 1; \
	done
	$(MAKE) --no-print-directory corpus
	$(MAKE) --no-print-directory ingest parity rules enrich verify report \
	  runs pdf smoke web DATE=$(DATE)

ingest: ingest-legacy ingest-modern ## Ingest DATE with both ingesters

ingest-legacy: ## Run the C++11 legacy ingest for DATE
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps legacy ingest --date $(DATE)

ingest-modern: ## Run the C++20 ingest for DATE (shadow schema ingest.*)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ingest ingest --date $(DATE)

parity: ## Compare DATE's legacy and C++20 rows (must be 0 differences)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ingest parity --date $(DATE)

rules: ## Rule checks for DATE: dedup L0-L2, SEC registry, sources, stale
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api rules --date $(DATE)

registry: ## Refresh the SEC ticker registry now (needs SEC_USER_AGENT)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api registry

enrich: ## First AI for DATE: dedup L3, summaries, sentiment (GPU host)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api enrich --date $(DATE)

corpus: ## Download new EDGAR/Fed/SEC documents and index them (SEC_USER_AGENT)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api corpus

reindex: ## Rebuild the vector store (chroma) from ai.chunk
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api reindex

llm-status: ## The gateway's aliases, one embedding and one chat call
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api llm-status

ai-runs: ## Last 10 AI runs (paraphrases, summaries, fallbacks, time)
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, items, \
	  paraphrases AS para, conflicts AS conf, injections AS inj, summarized, \
	  fallbacks AS fb, skipped, failed, model, llm_ms, total_ms \
	  FROM ai.ai_run ORDER BY run_id DESC LIMIT 10"

verify: ## AI verification of DATE: queue the run, follow it (GPU host)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api verify --date $(DATE)

demo-open: ## Market open for DATE: pending reviews expire (verdicts stand)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api expire --date $(DATE)

verify-runs: ## Last 10 verify runs (verdicts, reviews, escalations, time)
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, total, \
	  done, verified AS ver, unverified AS unv, misleading AS mis, fake, \
	  pending_review AS review, escalated AS esc, failed, requested_by, \
	  total_ms FROM ai.verify_run ORDER BY run_id DESC LIMIT 10"

review-queue: ## The pending reviews, highest market impact first
	@cd $(ROOT) && $(PSQL) -c "SELECT t.id, n.vendor_item_id, t.ai_verdict \
	  AS ai, round(t.ai_confidence::numeric, 2) AS conf, t.reasons, \
	  round(t.impact_score::numeric, 2) AS impact FROM ai.review_task t \
	  JOIN ai.news_item n ON n.id = t.news_id WHERE t.status = 'PENDING' \
	  ORDER BY t.impact_score DESC LIMIT 30"

worker-logs: ## Follow the verification worker's log
	cd $(ROOT) && $(COMPOSE) $(PROFILES) logs -f --tail=100 ai-worker

mcp-tools: ## List the MCP server's tools (through MCP, with the token)
	cd $(ROOT) && $(COMPOSE) $(PROFILES) exec -T mcp-server mcp-server tools

TOOL ?= lookup_company
ARGS ?= {"query": "AAPL"}
mcp-call: ## Call one MCP tool: TOOL=lookup_company ARGS='{"query": "AAPL"}'
	cd $(ROOT) && $(COMPOSE) $(PROFILES) exec -T mcp-server \
	  mcp-server call $(TOOL) '$(ARGS)'

dedup-rebuild: ## Re-index the 7-day dedup window ending at DATE into Redis
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps ai-api-init \
	  ai-api dedup-rebuild --date $(DATE)

report: ## Render /nfs/reports/DATE.pdf
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps legacy report --date $(DATE)

rule-runs: ## Last 10 rule runs (duplicates by type, reason codes)
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, items, \
	  duplicates AS dups, stale, flagged, by_type, reason_counts, backend, \
	  total_ms FROM ai.rule_run ORDER BY run_id DESC LIMIT 10"

runs: ## Last 10 runs of each ingester, and the parity checks
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, \
	  rows_received AS received, dups, workers, p50_us, p99_us, p999_us, \
	  total_ms, to_char(finished_at AT TIME ZONE 'America/New_York', \
	  'HH24:MI:SS') AS finished_et FROM legacy.ingest_run \
	  ORDER BY run_id DESC LIMIT 10"
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, \
	  rows_received AS received, dups, workers, p50_us, p99_us, p999_us, \
	  wait_p99_us, parse_us, copy_ms, total_ms FROM ingest.ingest_run \
	  ORDER BY run_id DESC LIMIT 10"
	@cd $(ROOT) && $(PSQL) -c "SELECT feed_date, status, differences, \
	  legacy_rows, modern_rows, to_char(checked_at AT TIME ZONE \
	  'America/New_York', 'MM-DD HH24:MI') AS checked_et \
	  FROM ingest.parity_run ORDER BY id DESC LIMIT 10"

pdf: ## Copy DATE's PDF from the NFS volume to out/DATE.pdf
	@mkdir -p $(ROOT)/out
	cd $(ROOT) && $(COMPOSE) exec -T legacy cat /nfs/reports/$(DATE).pdf \
	  > out/$(DATE).pdf
	@echo "PDF: $(ROOT)/out/$(DATE).pdf"

feed-summary: ## What vendor-sim sends for DATE (by label kind)
	cd $(ROOT) && $(COMPOSE) exec -T vendor-sim vendor-sim summary --date $(DATE)

psql: ## Open psql on the premarket database
	cd $(ROOT) && $(COMPOSE) exec postgres psql -U premarket -d premarket
