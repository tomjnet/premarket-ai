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
API_BUILD = $(ENGINE) build -f podman/ai-api/Containerfile python/ai-api
WEB_BUILD = $(ENGINE) build -f podman/web/Containerfile ui/web
PSQL = $(COMPOSE) exec -T postgres psql -U premarket -d premarket
# Increment 1 runs the legacy pipeline and the website side by side.
# `run` always uses --no-deps: with Podman, compose recreates the running
# postgres for every `run` with dependencies, and ai-api would lose its
# connections for a few seconds. `up` (or `demo`) starts everything first.
PROFILES = --profile legacy --profile ai
# Secrets `env` fills with random values when .env has them empty or missing.
SECRETS = JWT_SECRET REDIS_PASSWORD AI_DB_PASSWORD
# Increment 1 settings added to an older .env (from increment 0).
NEW_SETTINGS = WEB_PORT WEB_BIND DEMO_USER_PASSWORD ACCESS_TOKEN_TTL_S \
  REFRESH_TOKEN_TTL_S LOGIN_MAX_FAILURES LOGIN_LOCKOUT_S
WEB_PORT ?= $(shell grep -s '^WEB_PORT=' $(ROOT)/.env | cut -d= -f2)

.DEFAULT_GOAL := help
.PHONY: help env build up down logs ps test lint cpp-test cpp-lint \
        cpp-asan cpp-tsan cpp-bench sanitizers check demo ingest report \
        runs pdf feed-summary psql reset api-test api-lint web-image smoke \
        web openapi audit

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
build: env ## Build the service images (vendor-sim, legacy, ai-api, web)
	cd $(ROOT) && $(VENDOR_BUILD) --target runtime -t $(PREFIX)/vendor-sim:dev
	cd $(ROOT) && $(LEGACY_BUILD) --target runtime -t $(PREFIX)/legacy:dev
	cd $(ROOT) && $(API_BUILD) --target runtime -t $(PREFIX)/ai-api:dev
	cd $(ROOT) && $(WEB_BUILD) --target runtime -t $(PREFIX)/web:dev

up: build ## Build (cached) and start everything: legacy + the website
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
test: ## Unit tests: pytest (vendor-sim, ai-api) + GoogleTest (legacy)
	cd $(ROOT) && $(VENDOR_BUILD) --target test -t $(PREFIX)/vendor-sim:test
	$(MAKE) --no-print-directory api-test
	$(MAKE) --no-print-directory cpp-test

lint: ## Style: ruff (vendor-sim, ai-api) + clang-format/cpplint/clang-tidy
	cd $(ROOT) && $(VENDOR_BUILD) --target lint -t $(PREFIX)/vendor-sim:lint
	$(MAKE) --no-print-directory api-lint
	$(MAKE) --no-print-directory cpp-lint

api-test: ## ai-api pytest (auth, sessions, news contract)
	cd $(ROOT) && $(API_BUILD) --target test -t $(PREFIX)/ai-api:test

api-lint: ## ai-api ruff
	cd $(ROOT) && $(API_BUILD) --target lint -t $(PREFIX)/ai-api:lint

web-image: ## Build only the web image (production UI bundle + nginx)
	cd $(ROOT) && $(WEB_BUILD) --target runtime -t $(PREFIX)/web:dev

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

# The increment's "done when": the website shows DATE's news (the same items
# as the PDF), through the edge, with the security settings in place.
smoke: ## Website check for DATE: login, feed = PDF rows, headers, logout
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
demo: up ## Whole day now: ingest history + DATE, PDF, website check
	@cd $(ROOT) && for i in $$(seq $(HISTORY_DAYS) -1 1); do \
	  d=$$(date -d "$(DATE) -$$i day" +%F); \
	  echo "== history ingest $$d"; \
	  $(COMPOSE) $(PROFILES) run --rm --no-deps legacy ingest --date $$d || exit 1; \
	done
	$(MAKE) --no-print-directory ingest report runs pdf smoke web DATE=$(DATE)

ingest: ## Run the C++11 ingest for DATE
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps legacy ingest --date $(DATE)

report: ## Render /nfs/reports/DATE.pdf
	cd $(ROOT) && $(COMPOSE) $(PROFILES) run --rm --no-deps legacy report --date $(DATE)

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
