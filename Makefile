# =============================================================================
# CAIMP v2 — Makefile
# =============================================================================

.DEFAULT_GOAL := help
COMPOSE        := docker compose
SERVICES       := postgres redis nats ollama otelcol nginx

.PHONY: help up down logs reset ps build migrate pull \
        shell-postgres shell-redis shell-nats shell-ollama \
        shell-otelcol shell-nginx shell-api-query shell-api-admin \
        shell-ai-worker shell-alert-engine shell-ws-gateway \
        pull-models lint test \
        up-monitoring monitoring-ps grafana-open prometheus-open \
        test-integration security-scan govulncheck

# ---------------------------------------------------------------------------
# Core lifecycle
# ---------------------------------------------------------------------------

up: ## Start all infrastructure services (detached)
	$(COMPOSE) up -d

up-infra: ## Start infra only (no app services)
	$(COMPOSE) up -d postgres redis nats ollama otelcol nginx

down: ## Stop and remove containers (keeps volumes)
	$(COMPOSE) down

down-v: ## Stop and remove containers AND volumes (full reset)
	$(COMPOSE) down -v

reset: down-v up ## Full teardown + fresh start (destroys all data)

restart: ## Restart all services
	$(COMPOSE) restart

ps: ## Show status of all containers
	$(COMPOSE) ps

build: ## Build all custom images
	$(COMPOSE) build

pull: ## Pull all upstream images
	$(COMPOSE) pull

# ---------------------------------------------------------------------------
# Migrations & setup
# ---------------------------------------------------------------------------

migrate: ## Run database migrations manually
	$(COMPOSE) run --rm migrate

migrate-status: ## Show migration status
	$(COMPOSE) run --rm migrate version

nats-setup: ## Re-run NATS stream bootstrap
	$(COMPOSE) run --rm nats-setup

pull-models: ## Pull required Ollama models (run once after `make up`)
	$(COMPOSE) exec ollama ollama pull llama3.1:8b-instruct-q4_K_M
	$(COMPOSE) exec ollama ollama pull nomic-embed-text

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

logs-%: ## Follow logs for a specific service: make logs-postgres
	$(COMPOSE) logs -f $*

# ---------------------------------------------------------------------------
# Shell access
# ---------------------------------------------------------------------------

shell-%: ## Open a shell in a running container: make shell-postgres
	$(COMPOSE) exec $* sh

psql: ## Open a psql prompt in the postgres container
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-caimp} -d $${POSTGRES_DB:-caimp}

redis-cli: ## Open redis-cli in the redis container
	$(COMPOSE) exec redis redis-cli -a $${REDIS_PASSWORD}

nats-cli: ## Open nats CLI in the nats container
	$(COMPOSE) exec nats nats server check

# ---------------------------------------------------------------------------
# Development helpers
# ---------------------------------------------------------------------------

lint: ## Run linters (ruff for Python, golangci-lint for Go)
	@echo "→ Python lint (ruff)"
	ruff check services/ libs/ 2>/dev/null || echo "  ruff not installed locally; pip install ruff"
	@echo "→ Go lint"
	cd services/telemetry-writer && golangci-lint run 2>/dev/null || echo "  golangci-lint not installed locally"
	@echo "→ TypeScript type-check"
	cd frontend && npx tsc --noEmit 2>/dev/null || echo "  node/npm not installed locally"

test: ## Run unit tests
	$(COMPOSE) --profile test run --rm test-runner

# ---------------------------------------------------------------------------
# Phase 5 — Monitoring
# ---------------------------------------------------------------------------

up-monitoring: ## Start Prometheus + Grafana (alongside the rest of the stack)
	$(COMPOSE) up -d prometheus grafana

monitoring-ps: ## Show status of monitoring services
	$(COMPOSE) ps prometheus grafana

prometheus-open: ## Open Prometheus UI in the browser
	@echo "Prometheus → http://localhost:9090"
	@command -v xdg-open >/dev/null && xdg-open http://localhost:9090 || \
	 command -v open     >/dev/null && open     http://localhost:9090 || true

grafana-open: ## Open Grafana UI in the browser (admin / $GRAFANA_ADMIN_PASSWORD)
	@echo "Grafana → http://localhost:3001  (or http://localhost/grafana via nginx)"
	@command -v xdg-open >/dev/null && xdg-open http://localhost:3001 || \
	 command -v open     >/dev/null && open     http://localhost:3001 || true

# ---------------------------------------------------------------------------
# Phase 5 — Security & Integration Tests
# ---------------------------------------------------------------------------

test-integration: ## Run integration smoke tests against a running stack
	pip install httpx pytest --quiet
	pytest tests/integration/ -v

security-scan: ## Run Trivy filesystem scan for secrets + misconfigurations
	@command -v trivy >/dev/null || (echo "Install trivy: https://aquasecurity.github.io/trivy/"; exit 1)
	trivy fs . --scanners secret,misconfig --severity HIGH,CRITICAL

govulncheck: ## Run Go vulnerability check on telemetry-writer
	cd services/telemetry-writer && govulncheck ./...

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_%-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | sort \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
