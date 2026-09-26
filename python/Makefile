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
PSQL = $(COMPOSE) exec -T postgres psql -U premarket -d premarket
# Increment 1 runs the legacy pipeline and the website side by side;
# increment 2 adds the C++20 ingester (profile legacy) and the rule checks.
# `run` always uses --no-deps: with Podman, compose recreates the running
# postgres for every `run` with dependencies, and ai-api would lose its
# connections for a few seconds. `up` (or `demo`) starts everything first.
PROFILES = --profile legacy --profile ai
# Secrets `env` fills with random values when .env has them empty or missing.
SECRETS = JWT_SECRET REDIS_PASSWORD AI_DB_PASSWORD
# Settings added to an older .env (from increments 0 and 1).
NEW_SETTINGS = WEB_PORT WEB_BIND DEMO_USER_PASSWORD ACCESS_TOKEN_TTL_S \
  REFRESH_TOKEN_TTL_S LOGIN_MAX_FAILURES LOGIN_LOCKOUT_S \
  LAB_UNIVERSE_SIZE INGEST_WORKERS INGEST_QUEUE_CAPACITY \
  INGEST_DEDUP_WINDOW_DAYS INGEST_CPU_AFFINITY SEC_USER_AGENT \
  REGISTRY_MAX_AGE_DAYS STALE_MAX_AGE_DAYS DEDUP_WINDOW_DAYS \
  DEDUP_SIMHASH_NGRAM DEDUP_SIMHASH_MAX_HAMMING DEDUP_NEAR_MAX_WORD_EDITS
WEB_PORT ?= $(shell grep -s '^WEB_PORT=' $(ROOT)/.env | cut -d= -f2)

.DEFAULT_GOAL := help
.PHONY: help env build up down logs ps test lint cpp-test cpp-lint \
        cpp-asan cpp-tsan cpp-bench sanitizers check demo ingest report \
        runs pdf feed-summary psql reset api-test api-lint web-image smoke \
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
build: env ## Build the images (vendor-sim, legacy, ingest, ai-api, web)
	cd $(ROOT) && $(VENDOR_BUILD) --target runtime -t $(PREFIX)/vendor-sim:dev
	cd $(ROOT) && $(LEGACY_BUILD) --target runtime -t $(PREFIX)/legacy:dev
	cd $(ROOT) && $(INGEST_BUILD) --target runtime -t $(PREFIX)/ingest:dev
	cd $(ROOT) && $(API_BUILD) --target runtime -t $(PREFIX)/ai-api:dev
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

# --- tests ------------------------------------------------------------------
test: ## Unit tests: pytest (vendor-sim, ai-api + parity) + GoogleTest (C++)
	cd $(ROOT) && $(VENDOR_BUILD) --target test -t $(PREFIX)/vendor-sim:test
	$(MAKE) --no-print-directory api-test
	$(MAKE) --no-print-directory cpp-test
	$(MAKE) --no-print-directory ingest-test
	$(MAKE) --no-print-directory fastpath-test

lint: ## Style: ruff + clang-format/cpplint/clang-tidy (all C++ projects)
	cd $(ROOT) && $(VENDOR_BUILD) --target lint -t $(PREFIX)/vendor-sim:lint
	$(MAKE) --no-print-directory api-lint
	$(MAKE) --no-print-directory cpp-lint
	$(MAKE) --no-print-directory ingest-lint
	$(MAKE) --no-print-directory fastpath-lint

api-test: ## ai-api pytest (auth, news, rules, dedup, C++ vs Python parity)
	cd $(ROOT) && $(API_BUILD) --target test -t $(PREFIX)/ai-api:test

api-lint: ## ai-api ruff
	cd $(ROOT) && $(API_BUILD) --target lint -t $(PREFIX)/ai-api:lint

web-image: ## Build only the web image (production UI bundle + nginx)
	cd $(ROOT) && $(WEB_BUILD) --target runtime -t $(PREFIX)/web:dev

eval: ## Rule/dedup eval on the seed-42 golden set (fails on regression)
	cd $(ROOT) && $(API_BUILD) --target eval -t $(PREFIX)/ai-api:eval

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
# plus the increment 1 security checks.
smoke: ## Website check for DATE: parity, rules, badges, login, headers
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
demo: up ## Whole day now: history + DATE (both ingesters, rules), PDF, check
	@for i in $$(seq $(HISTORY_DAYS) -1 1); do \
	  d=$$(date -d "$(DATE) -$$i day" +%F); \
	  echo "== history $$d"; \
	  $(MAKE) --no-print-directory ingest parity rules DATE=$$d || exit 1; \
	done
	$(MAKE) --no-print-directory ingest parity rules report runs pdf smoke \
	  web DATE=$(DATE)

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
