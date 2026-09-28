# premarket-ai on Minikube. Run from the repo root:
#   make -C minikube-kubernetes <task> [DATE=YYYY-MM-DD]
# The same images and config files as `make -C python` / compose.yaml; only
# the orchestrator changes. Build the images with `make -C python build`.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
HERE := $(ROOT)/minikube-kubernetes
NS ?= premarket
MINIKUBE ?= minikube
KUBECTL ?= $(shell command -v kubectl >/dev/null 2>&1 && echo kubectl \
  || echo "$(MINIKUBE) kubectl --")
K = $(KUBECTL) -n $(NS)
ENV_FILE ?= $(ROOT)/.env
DATE ?= $(shell TZ=America/New_York date +%F)
HISTORY_DAYS ?= 5
EDITION ?= morning
# Minikube VM size: fits the 16 GB WSL limit of scripts/windows/wslconfig.example.
CPUS ?= 6
MEMORY ?= 12g
DISK ?= 60g
WEB_PORT ?= $(or $(shell grep -s '^WEB_PORT=' $(ENV_FILE) | cut -d= -f2),8080)
VECTOR_STORE ?= $(or $(shell grep -s '^VECTOR_STORE=' $(ENV_FILE) \
  | cut -d= -f2),chroma)

# The kustomizations read podman/config and sql in place, outside this
# folder. Server-side apply: the Grafana dashboard is too big for the
# last-applied annotation of a client-side apply.
RENDER = $(KUBECTL) kustomize --load-restrictor LoadRestrictionsNone
APPLY = $(KUBECTL) apply --server-side --force-conflicts -f -
# The database owner's batch commands (`podman compose run ai-api-init
# ai-api ...` in python/Makefile) run in the scheduler pod: same image
# base, same env.
AI_API = $(K) exec deploy/scheduler -- ai-api
PSQL = $(K) exec -i deploy/postgres -- psql -U premarket -d premarket

.DEFAULT_GOAL := help
.PHONY: help start stop delete-cluster load-images config up obs-up \
        obs-down down reset ps logs web grafana langfuse mcp psql demo \
        ingest rules registry enrich corpus reindex llm-status verify \
        brief scorecard smoke demo-open retention schedule-plan sla \
        mcp-tools feed-summary render restart

help: ## List the tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

# --- cluster ----------------------------------------------------------------
start: ## Start Minikube (Podman driver, containerd), CPUS/MEMORY/DISK
	$(MINIKUBE) start --driver=podman --container-runtime=containerd \
	  --cpus=$(CPUS) --memory=$(MEMORY) --disk-size=$(DISK)

stop: ## Stop Minikube (everything is kept)
	$(MINIKUBE) stop

delete-cluster: ## DELETE the Minikube cluster (all volumes and images in it)
	$(MINIKUBE) delete

load-images: ## Copy the Podman-built images into Minikube (after make -C python build)
	bash $(HERE)/scripts/load-images.sh

# --- the stack ----------------------------------------------------------------
config: ## .env -> ConfigMap premarket-settings + Secret premarket-env, edge config
	NS=$(NS) KUBECTL="$(KUBECTL)" bash $(HERE)/scripts/config.sh $(ENV_FILE)

render: ## Print the manifests (base; + chroma while VECTOR_STORE=chroma)
	@$(RENDER) $(HERE)/base
	@$(if $(filter chroma,$(VECTOR_STORE)),echo ---; $(RENDER) $(HERE)/chroma)

up: config ## Start everything (profile ai): re-runs ai-api-init, waits until ready
	$(K) delete job ai-api-init --ignore-not-found
	$(RENDER) $(HERE)/base | $(APPLY)
	$(if $(filter chroma,$(VECTOR_STORE)),$(RENDER) $(HERE)/chroma | $(APPLY))
	# The edge reads its template at start (config may have changed it).
	$(K) rollout restart deploy/edge
	$(K) wait --for=condition=complete job/ai-api-init --timeout=15m
	$(K) wait --for=condition=available deploy --all --timeout=20m
	@$(MAKE) --no-print-directory ps

restart: ## Roll SVC=<name> (after load-images), or every Deployment (.env changed)
	$(K) rollout restart deploy$(if $(SVC),/$(SVC))
	$(if $(SVC),$(K) rollout status deploy/$(SVC) --timeout=10m,$(K) wait \
	  --for=condition=available deploy --all --timeout=20m)

obs-up: config ## Start Langfuse, OTel Collector, Prometheus, Grafana
	$(RENDER) $(HERE)/observability | $(APPLY)
	$(K) wait --for=condition=available deploy --all --timeout=20m
	@echo "Grafana:  make -C minikube-kubernetes grafana   (admin / GRAFANA_ADMIN_PASSWORD)"
	@echo "Langfuse: make -C minikube-kubernetes langfuse  (LANGFUSE_INIT_USER_EMAIL)"

OBS_APPS = langfuse-db langfuse-clickhouse langfuse-minio langfuse-redis   langfuse-worker langfuse-web otel-collector prometheus grafana
obs-down: ## Remove the observability overlay (its volumes are kept)
	$(K) delete $(foreach a,$(OBS_APPS),deploy/$(a)) --ignore-not-found
	$(K) delete svc $(filter-out langfuse-worker,$(OBS_APPS)) --ignore-not-found

down: ## Stop the stack (volumes, config and secrets are kept)
	$(K) delete deploy,svc,job --all --ignore-not-found

reset: ## Stop the stack and DELETE its volumes (the whole namespace)
	$(KUBECTL) delete namespace $(NS) --ignore-not-found

ps: ## Pods, Jobs and volumes
	$(K) get pods,jobs,pvc -o wide

logs: ## Follow the logs of one service: SVC=ai-api (default: all pods)
	$(if $(SVC),$(K) logs -f --tail=100 deploy/$(SVC),\
	  $(K) logs -f --tail=20 --prefix --max-log-requests=30 \
	  -l app.kubernetes.io/part-of=premarket-ai)

# --- open in the browser (kubectl port-forward, Ctrl+C to stop) -------------
web: ## The website on http://localhost:WEB_PORT and the demo logins
	@echo "Website: http://localhost:$(WEB_PORT)  (trader1, analyst1, admin1 / DEMO_USER_PASSWORD in .env)"
	$(K) port-forward svc/edge $(WEB_PORT):8080

grafana: ## Grafana on http://localhost:3001
	$(K) port-forward svc/grafana 3001:3000

langfuse: ## Langfuse on http://localhost:3000
	$(K) port-forward svc/langfuse-web 3000:3000

mcp: ## The MCP server on http://localhost:8765/mcp (Claude Desktop, Inspector)
	$(K) port-forward svc/mcp-server 8765:8000

psql: ## Open psql on the premarket database
	$(K) exec -it deploy/postgres -- psql -U premarket -d premarket

# --- the demo day (the same commands as make -C python) ---------------------
demo: ## Whole day: history + DATE (ingest, rules, AI, verify, brief), check
	@for i in $$(seq $(HISTORY_DAYS) -1 1); do \
	  d=$$(date -d "$(DATE) -$$i day" +%F); \
	  echo "== history $$d"; \
	  $(MAKE) --no-print-directory ingest rules DATE=$$d || exit 1; \
	done
	$(MAKE) --no-print-directory corpus
	$(MAKE) --no-print-directory ingest rules enrich verify brief scorecard \
	  smoke DATE=$(DATE)
	@echo "Open the site: make -C minikube-kubernetes web"

ingest: ## Run the C++20 ingest for DATE (schema ingest.*)
	$(K) exec deploy/ingest -- premarket-ingest ingest --date $(DATE)

rules: ## Rule checks for DATE: dedup L0-L2, SEC registry, sources, stale
	$(AI_API) rules --date $(DATE)

registry: ## Refresh the SEC ticker registry now (needs SEC_USER_AGENT)
	$(AI_API) registry

enrich: ## First AI for DATE: dedup L3, summaries, sentiment (GPU host)
	$(AI_API) enrich --date $(DATE)

corpus: ## Download new EDGAR/Fed/SEC documents and index them (SEC_USER_AGENT)
	$(AI_API) corpus

reindex: ## Rebuild the vector store (VECTOR_STORE) from ai.chunk
	$(AI_API) reindex

llm-status: ## The gateway's aliases, one embedding and one chat call
	$(AI_API) llm-status

verify: ## AI verification of DATE: queue the run, follow it (GPU host)
	$(AI_API) verify --date $(DATE)

brief: ## Pre-market brief of DATE (EDITION=morning|refresh), after verify
	$(AI_API) brief --date $(DATE) --edition $(EDITION)

scorecard: ## DATE's vendor scorecard (billable vs contracted items)
	$(AI_API) scorecard --date $(DATE)

smoke: ## Website check for DATE through the edge (the "done when" check)
	$(AI_API) smoke --base-url http://edge:8080 --date $(DATE)

demo-open: ## Market open for DATE: pending reviews expire (verdicts stand)
	$(AI_API) expire --date $(DATE)

retention: ## Delete AI results older than RETENTION_DAYS (nightly job)
	$(AI_API) retention

schedule-plan: ## The scheduler's timeline for DATE (NYSE calendar, RUN_MODE)
	$(K) exec deploy/scheduler -- scheduler plan --date $(DATE)

sla: ## DATE's scheduled jobs and SLA checks (exit 1 if one was breached)
	$(K) exec deploy/scheduler -- scheduler status --date $(DATE)

mcp-tools: ## List the MCP server's tools (through MCP, with the token)
	$(K) exec deploy/mcp-server -- mcp-server tools

feed-summary: ## What vendor-sim sends for DATE (by label kind)
	$(K) exec deploy/vendor-sim -- vendor-sim summary --date $(DATE)
