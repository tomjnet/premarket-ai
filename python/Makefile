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
VENDOR_BUILD = $(ENGINE) build -f podman/vendor-sim/Containerfile python/vendor-sim
PSQL = $(COMPOSE) exec -T postgres psql -U premarket -d premarket

.DEFAULT_GOAL := help
.PHONY: help env build up down logs ps test lint cpp-test cpp-lint \
        cpp-asan cpp-tsan cpp-bench sanitizers check demo ingest report \
        runs pdf feed-summary psql reset

help: ## List the tasks
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@cd $(ROOT) && [ -f .env ] || { cp .env.example .env && echo "created .env"; }

# --- build and run ----------------------------------------------------------
build: env ## Build the service images (vendor-sim, legacy)
	cd $(ROOT) && $(VENDOR_BUILD) --target runtime -t $(PREFIX)/vendor-sim:dev
	cd $(ROOT) && $(LEGACY_BUILD) --target runtime -t $(PREFIX)/legacy:dev

up: build ## Build (cached) and start postgres, vendor-sim, legacy (cron)
	cd $(ROOT) && $(COMPOSE) --profile legacy up -d --wait

down: ## Stop the stack (volumes are kept)
	cd $(ROOT) && $(COMPOSE) --profile full down

logs: ## Follow the logs of all services
	cd $(ROOT) && $(COMPOSE) --profile legacy logs -f --tail=100

ps: ## Show service status
	cd $(ROOT) && $(COMPOSE) --profile legacy ps

reset: ## Stop the stack and DELETE its volumes (database, PDFs, labels)
	cd $(ROOT) && $(COMPOSE) --profile full down -v

# --- tests ------------------------------------------------------------------
test: ## Unit tests: pytest (vendor-sim) + GoogleTest (legacy)
	cd $(ROOT) && $(VENDOR_BUILD) --target test -t $(PREFIX)/vendor-sim:test
	$(MAKE) --no-print-directory cpp-test

lint: ## Style: ruff (vendor-sim) + clang-format/cpplint/clang-tidy (legacy)
	cd $(ROOT) && $(VENDOR_BUILD) --target lint -t $(PREFIX)/vendor-sim:lint
	$(MAKE) --no-print-directory cpp-lint

cpp-test: ## C++ debug build + ctest
	cd $(ROOT) && $(LEGACY_BUILD) --target test -t $(PREFIX)/legacy:test

cpp-lint: ## C++ clang-format, cpplint, clang-tidy
	cd $(ROOT) && $(LEGACY_BUILD) --target lint -t $(PREFIX)/legacy:lint

cpp-asan: ## C++ tests under AddressSanitizer + UBSan
	cd $(ROOT) && $(LEGACY_BUILD) --target asan -t $(PREFIX)/legacy:asan

cpp-tsan: ## C++ tests under ThreadSanitizer
	cd $(ROOT) && $(LEGACY_BUILD) --target tsan -t $(PREFIX)/legacy:tsan

sanitizers: cpp-asan cpp-tsan ## Both sanitizer builds

cpp-bench: ## Build and run the legacy micro-benchmarks
	cd $(ROOT) && $(LEGACY_BUILD) --target bench -t $(PREFIX)/legacy:bench
	$(ENGINE) run --rm $(PREFIX)/legacy:bench

check: test lint sanitizers ## Everything CI runs

# --- the legacy day ---------------------------------------------------------
demo: up ## Whole legacy day now: ingest history + DATE, PDF, run table
	@cd $(ROOT) && for i in $$(seq $(HISTORY_DAYS) -1 1); do \
	  d=$$(date -d "$(DATE) -$$i day" +%F); \
	  echo "== history ingest $$d"; \
	  $(COMPOSE) run --rm legacy ingest --date $$d || exit 1; \
	done
	$(MAKE) --no-print-directory ingest report runs pdf DATE=$(DATE)

ingest: ## Run the C++11 ingest for DATE
	cd $(ROOT) && $(COMPOSE) run --rm legacy ingest --date $(DATE)

report: ## Render /nfs/reports/DATE.pdf
	cd $(ROOT) && $(COMPOSE) run --rm legacy report --date $(DATE)

runs: ## Last 10 rows of legacy.ingest_run
	@cd $(ROOT) && $(PSQL) -c "SELECT run_id, feed_date, status, \
	  rows_received AS received, dups, workers, p50_us, p99_us, p999_us, \
	  total_ms, to_char(finished_at AT TIME ZONE 'America/New_York', \
	  'HH24:MI:SS') AS finished_et FROM legacy.ingest_run \
	  ORDER BY run_id DESC LIMIT 10"

pdf: ## Copy DATE's PDF from the NFS volume to out/DATE.pdf
	@mkdir -p $(ROOT)/out
	cd $(ROOT) && $(COMPOSE) exec -T legacy cat /nfs/reports/$(DATE).pdf \
	  > out/$(DATE).pdf
	@echo "PDF: $(ROOT)/out/$(DATE).pdf"

feed-summary: ## What vendor-sim sends for DATE (by label kind)
	cd $(ROOT) && $(COMPOSE) exec -T vendor-sim vendor-sim summary --date $(DATE)

psql: ## Open psql on the premarket database
	cd $(ROOT) && $(COMPOSE) exec postgres psql -U premarket -d premarket
