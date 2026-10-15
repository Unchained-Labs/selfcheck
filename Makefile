# selfcheck — a local, read-only PR/MR review workbench.
#
# Thin wrappers over scripts/, so `make help` is the one thing you need to
# remember. Every target here runs the same script you could run by hand.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT    := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PORT    ?= $(shell grep -sE '^SELFCHECK_PORT=' .env | cut -d= -f2 || echo 7777)
PORT    := $(or $(strip $(PORT)),7777)
URL     := http://127.0.0.1:$(PORT)
# Run the container as the invoking user so mounted files keep host ownership.
COMPOSE := SELFCHECK_UID=$(shell id -u) SELFCHECK_GID=$(shell id -g) docker compose

# Passed through to the underlying script, e.g. `make skill ARGS=--project`.
ARGS ?=

.PHONY: help
help: ## Show this help
	@echo "selfcheck — $(URL)"
	@echo
	@awk 'BEGIN {FS = ":.*?## "} \
		/^## / { section = substr($$0, 4); printf "\n\033[1m%s\033[0m\n", section; next } \
		/^[a-zA-Z0-9_-]+:.*?## / { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)
	@echo

## Running it locally
.PHONY: setup
setup: ## Install the Python and web dependencies
	@cd api && { [ -d .venv ] || uv venv --python 3.12 .venv; } && \
		uv pip install -q -e . pytest --python .venv/bin/python
	@source scripts/_node.sh && cd web && pnpm install
	@echo "ready — now run 'make dev' or 'make build serve'"

.PHONY: dev
dev: ## API with reload + the Vite dev server (Ctrl-C stops both)
	@scripts/dev.sh

.PHONY: build
build: ## Build the web UI into web/dist
	@scripts/build.sh

.PHONY: serve
serve: ## Serve the API and the built UI as one process
	@scripts/serve.sh

.PHONY: stop
stop: ## Stop servers started by `make dev`
	@scripts/stop.sh

.PHONY: status
status: ## Ask a running instance what it can currently do
	@curl -sf $(URL)/api/status | python3 -m json.tool || \
		{ echo "selfcheck is not answering on $(URL)"; exit 1; }

## Checks
.PHONY: test
test: ## Run the API test suite
	@scripts/test.sh $(ARGS)

.PHONY: smoke
smoke: ## Browser smoke test against a running instance
	@scripts/smoke-ui.sh $(ARGS)

.PHONY: typecheck
typecheck: ## Typecheck the web app
	@source scripts/_node.sh && cd web && pnpm typecheck

.PHONY: check
check: test typecheck ## Everything that does not need a running server

## Claude integration
.PHONY: skill
skill: ## Install the selfcheck skill (ARGS=--project to scope it here)
	@scripts/install-skill.sh $(ARGS)

## Docker
.PHONY: up
up: ## Build if needed and start the stack in the background
	@$(COMPOSE) up -d --build
	@echo "selfcheck is on $(URL)"

.PHONY: down
down: ## Stop the stack
	@$(COMPOSE) down

.PHONY: logs
logs: ## Follow the container logs
	@$(COMPOSE) logs -f

.PHONY: shell
shell: ## Open a shell inside the running container
	@$(COMPOSE) exec selfcheck bash

.PHONY: docker-build
docker-build: ## Rebuild the image without starting anything
	@$(COMPOSE) build

## Housekeeping
.PHONY: prune
prune: ## Evict least-recently-used repo mirrors from the cache
	@curl -sf -X POST $(URL)/api/cache/prune | python3 -m json.tool || \
		{ echo "selfcheck is not answering on $(URL)"; exit 1; }

.PHONY: clean
clean: ## Remove build output and installed dependencies
	@rm -rf web/dist web/node_modules api/.venv api/.pytest_cache
	@find api -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "cleaned (data/ left alone — that is your reviews and repo cache)"

.PHONY: clean-data
clean-data: ## Delete the database, repo mirrors and worktrees. Destructive.
	@read -r -p "Delete every tracked review, note and cached clone? [y/N] " a; \
	 case "$$a" in [yY]*) chmod -R u+w data 2>/dev/null; rm -rf data; echo "data/ removed";; \
	 *) echo "left alone";; esac
