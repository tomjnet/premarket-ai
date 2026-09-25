# premarket-ai UI task runner. Run from the repo root:
#   make -C ui <task>
# Everything runs inside containers (ENGINE=docker works too).
#
# Style: Google TypeScript Style Guide, enforced by gts (ESLint + Prettier with
# Google's settings). ui/web needs gts as a devDependency plus the config files
# `npx gts init` writes (eslint.config.js, .prettierrc.js, tsconfig.json).

ENGINE ?= podman
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
WEB := $(ROOT)/ui/web
NODE_IMAGE ?= docker.io/library/node:22-bookworm-slim
# node_modules lives in a named volume, so the checkout stays clean and
# installs are cached between runs.
NODE_RUN = $(ENGINE) run --rm \
  -v $(WEB):/app \
  -v premarket-ai-web-node-modules:/app/node_modules \
  -w /app $(NODE_IMAGE)
NPM_CI = npm ci --no-audit --no-fund --loglevel=error

.DEFAULT_GOAL := help
.PHONY: help web-check lint fix

help: ## List the tasks
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

web-check:
	@[ -f $(WEB)/package.json ] || \
	  { echo "ui/web/package.json not found: scaffold ui/web first" >&2; exit 1; }

# --- style ------------------------------------------------------------------
lint: web-check ## Style: gts lint (Google TypeScript style)
	$(NODE_RUN) sh -c '$(NPM_CI) && npx gts lint'

fix: web-check ## Rewrite files to match the style: gts fix
	$(NODE_RUN) sh -c '$(NPM_CI) && npx gts fix'
