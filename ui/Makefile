# premarket-ai UI task runner. Run from the repo root:
#   make -C ui <task>
# Everything runs inside Podman containers. There is no Node on the host:
# every npm/npx/vite/vitest command goes through a task.
#
# Style: Google TypeScript Style Guide, enforced by gts (ESLint + Prettier with
# Google's settings) plus the React Hooks and jsx-a11y rules.

ENGINE ?= podman
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
WEB := $(ROOT)/ui/web
NODE_IMAGE ?= docker.io/library/node:22-bookworm-slim
PORT ?= 5173

# Dev server settings (see web/.env.example). `make dev` is mock mode;
# `make dev VITE_API_MODE=live` talks to the real backend through the /api
# proxy, which forwards to API_PROXY_TARGET.
VITE_API_MODE ?= mock
VITE_API_BASE_URL ?= /api
VITE_MOCK_TOKEN_TTL_S ?= 900
API_PROXY_TARGET ?= http://host.containers.internal:8000

# node_modules lives in a named volume, so the checkout stays clean and
# installs are cached between runs. --init lets Ctrl+C stop the dev server.
NODE_VOLUME := premarket-ai-web-node-modules
NODE_RUN = $(ENGINE) run --rm --init \
  -v $(WEB):/app \
  -v $(NODE_VOLUME):/app/node_modules \
  -w /app $(NODE_IMAGE)
NPM_CI = npm ci --no-audit --no-fund --loglevel=error
# Run `npm ci` only when package-lock.json changed since the last install;
# a full reinstall on every task would add a minute to each command.
DEPS = h="$$(sha256sum package-lock.json)" && \
  [ "$$(cat node_modules/.lock-hash 2>/dev/null)" = "$$h" ] || \
  { $(NPM_CI) && echo "$$h" > node_modules/.lock-hash; }
# Fails when the production bundle contains mock code (MSW or its worker).
NO_MSW = if grep -rlE "mockServiceWorker|setupWorker|\[MSW\]" dist; then \
  echo "MSW code found in dist/" >&2; exit 1; fi

.DEFAULT_GOAL := help
.PHONY: help web-check install dev test test-watch typecheck build check \
  lint fix npm clean

help: ## List the tasks
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

web-check:
	@[ -f $(WEB)/package.json ] || \
	  { echo "ui/web/package.json not found: scaffold ui/web first" >&2; exit 1; }

# --- dependencies -----------------------------------------------------------
install: web-check ## npm ci into the node_modules volume
	$(NODE_RUN) sh -c '$(NPM_CI) && sha256sum package-lock.json > node_modules/.lock-hash'

npm: web-check ## Any npm command: make npm ARGS="install -E zod"
	$(NODE_RUN) npm $(ARGS)

# --- run --------------------------------------------------------------------
dev: web-check ## Vite dev server on http://localhost:$PORT (mock API)
	$(ENGINE) run --rm --init -p $(PORT):5173 \
	  -e VITE_API_MODE=$(VITE_API_MODE) \
	  -e VITE_API_BASE_URL=$(VITE_API_BASE_URL) \
	  -e VITE_MOCK_TOKEN_TTL_S=$(VITE_MOCK_TOKEN_TTL_S) \
	  -e API_PROXY_TARGET=$(API_PROXY_TARGET) \
	  -v $(WEB):/app -v $(NODE_VOLUME):/app/node_modules \
	  -w /app $(NODE_IMAGE) \
	  sh -c '$(DEPS) && npx vite --host 0.0.0.0 --port 5173 --strictPort'

# --- checks -----------------------------------------------------------------
test: web-check ## Unit, component and contract tests with coverage
	$(NODE_RUN) sh -c '$(DEPS) && npm run test'

# -it: Vitest only watches when stdin is a terminal.
test-watch: web-check ## Re-run tests on every file change (Ctrl+C stops)
	$(ENGINE) run --rm --init -it \
	  -v $(WEB):/app -v $(NODE_VOLUME):/app/node_modules \
	  -w /app $(NODE_IMAGE) sh -c '$(DEPS) && npx vitest --watch'

typecheck: web-check ## TypeScript: tsc --noEmit
	$(NODE_RUN) sh -c '$(DEPS) && npm run typecheck'

build: web-check ## Production build (live mode, no MSW) into web/dist
	$(NODE_RUN) sh -c '$(DEPS) && VITE_API_MODE=live npm run build && $(NO_MSW)'

check: lint typecheck test build ## Everything CI would run

# The tasks share one node_modules volume, so `make -j` must not run two
# `npm ci` at once.
.NOTPARALLEL:

# --- style ------------------------------------------------------------------
lint: web-check ## Style: ESLint with the gts config, zero warnings
	$(NODE_RUN) sh -c '$(DEPS) && npm run lint'

fix: web-check ## Rewrite files to match the style: gts fix
	$(NODE_RUN) sh -c '$(DEPS) && npm run fix'

# --- housekeeping -----------------------------------------------------------
clean: ## Remove dist/, coverage/ and the node_modules volume
	rm -rf $(WEB)/dist $(WEB)/coverage
	-$(ENGINE) volume rm $(NODE_VOLUME)
