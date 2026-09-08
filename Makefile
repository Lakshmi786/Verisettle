# Custodian - developer entry point.
#
# Every target here is a thin wrapper over the real scripts and compose
# files; nothing is hidden behind make-only logic. `make help` lists them.
#
# The first-run sequence has two points where a script prints values you
# must paste into .env by hand (Infisical identities, LiteLLM keys). make
# cannot paste them for you, so bootstrap is split into three commands that
# stop exactly there rather than pretending to be fully automatic.

COMPOSE := sh infra/scripts/compose.sh
UV      := uv
SERVICE ?=

# Host ports as published in infra/compose/docker-compose.app.yml
BACKEND_URL       := http://localhost:8000
LEDGER_URL        := http://localhost:8090
POLICY_URL        := http://localhost:8091
SANDBOX_URL       := http://localhost:8093
AUDIT_URL         := http://localhost:8094
CONTROL_PLANE_URL := http://localhost:8095
CONSOLE_URL       := http://localhost:3000
LITELLM_URL       := http://localhost:4000

.DEFAULT_GOAL := help
.PHONY: help up down ps logs restart clean bootstrap bootstrap-data bootstrap-finish \
        step0 step1 step2 step3 step4-keys step5 step6 sandbox-image eval-gate \
        lock sync lint format typecheck test check validate-policies \
        health verify-audit kill-switch-status urls

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------------
# Stack lifecycle
# ----------------------------------------------------------------------
up: ## Start the whole stack in the background
	$(COMPOSE) up -d

down: ## Stop the stack, keeping all data volumes
	$(COMPOSE) down

ps: ## Show every container and its health status
	$(COMPOSE) ps --format "table {{.Name}}\t{{.Status}}"

logs: ## Tail logs; SERVICE=custodian-backend to narrow to one
	$(COMPOSE) logs -f $(SERVICE)

restart: ## Recreate a service (fixes WSL2 port-forwarding); SERVICE=name
	@test -n "$(SERVICE)" || { echo "usage: make restart SERVICE=<name>"; exit 1; }
	$(COMPOSE) up -d --force-recreate $(SERVICE)

clean: ## DESTRUCTIVE - stop the stack and delete every data volume
	@printf "This deletes all Postgres, MinIO, Keycloak and Langfuse data. Type yes: "; \
	read ans; [ "$$ans" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) down -v

# ----------------------------------------------------------------------
# First run (README steps 0-6). Each step is independently re-runnable.
# ----------------------------------------------------------------------
step0: ## Step 0 - create the Docker network and render the Keycloak realm
	docker network create custodian-net 2>/dev/null || true
	sh infra/scripts/render-keycloak-realm.sh

step1: ## Step 1 - foundations: Postgres + MinIO
	$(COMPOSE) up -d postgres minio

step2: ## Step 2 - identity: Keycloak, SPIRE, Infisical (prints values for .env)
	$(COMPOSE) up -d keycloak spire-server infisical-redis infisical
	sh infra/scripts/register-spire-entries.sh
	sh infra/scripts/setup-spire.sh
	$(COMPOSE) up -d --force-recreate spire-agent
	sh infra/scripts/bootstrap-infisical.sh
	python3 infra/scripts/provision-infisical-identities.py

step3: ## Step 3 - data: OpenMetadata, Presidio, real dataset load, catalog tags
	$(COMPOSE) up -d om-postgres om-elasticsearch om-migrate om-server om-ingestion \
		presidio-analyzer presidio-anonymizer
	$(COMPOSE) up data-loader
	python3 infra/scripts/register-openmetadata-catalog.py

step4-keys: ## Step 4a - LiteLLM + MLflow, then mint per-agent keys (prints values for .env)
	$(COMPOSE) up -d litellm-redis litellm mlflow
	@echo "waiting for the LiteLLM gateway to finish migrating..."
	@until curl -sf $(LITELLM_URL)/health/liveliness >/dev/null 2>&1; do sleep 3; done
	python3 infra/scripts/provision-litellm-keys.py

eval-gate: ## Step 4b - run the real DeepEval promotion gate (makes paid LLM calls)
	$(COMPOSE) up deepeval-gate

step5: validate-policies ## Step 5 - validate the Cedar rulebook

step6: ## Step 6 - bring up the agent runtime and everything else
	$(COMPOSE) up -d

sandbox-image: ## Build the locked-down per-invocation OCR sandbox image
	docker build -t custodian-sandbox-ocr:latest services/sandbox-ocr/

bootstrap: step0 step1 step2 ## First run, part 1 - stops so you can paste Infisical values into .env
	@echo
	@echo "=============================================================="
	@echo "Paste INFISICAL_PROJECT_ID, PAYMENT_EXECUTION_CLIENT_ID and"
	@echo "PAYMENT_EXECUTION_CLIENT_SECRET (printed above) into .env."
	@echo "Then run:  make bootstrap-data"
	@echo "=============================================================="

bootstrap-data: step3 step4-keys ## First run, part 2 - stops so you can paste LiteLLM keys into .env
	@echo
	@echo "=============================================================="
	@echo "Paste the LITELLM_KEY_AGENT_* values (printed above) into .env."
	@echo "Then run:  make bootstrap-finish"
	@echo "=============================================================="

bootstrap-finish: eval-gate step5 step6 sandbox-image ## First run, part 3 - eval gate, policies, full stack
	@$(MAKE) ps
	@echo
	@echo "Stack is up. Credentials and URLs: CREDENTIALS.md, or make urls"

# ----------------------------------------------------------------------
# Development tooling (uv workspace)
# ----------------------------------------------------------------------
lock: ## Re-resolve every lock file (workspace + the two standalone jobs)
	$(UV) lock
	cd services/sandbox-ocr && $(UV) lock
	cd infra/deepeval && $(UV) lock

sync: ## Create the local dev environment from the workspace lock
	$(UV) sync --all-packages

lint: ## Ruff lint across every Python service
	$(UV) run ruff check .

format: ## Ruff format across every Python service
	$(UV) run ruff format .

typecheck: ## mypy across every Python service
	$(UV) run mypy services infra

test: ## pytest across every Python service
	$(UV) run pytest

check: lint typecheck test ## Lint, typecheck and test in one go

validate-policies: ## Run the real Cedar policy validator (expects ACCEPTED)
	python3 infra/scripts/validate-cedar-policies.py

# ----------------------------------------------------------------------
# Verification helpers - the checks the scenario docs run by hand
# ----------------------------------------------------------------------
health: ## Backend health, including the SPIFFE ID it actually fetched
	@curl -sf $(BACKEND_URL)/health && echo || echo "backend not reachable on $(BACKEND_URL)"

verify-audit: ## Two-stage hash-chain + MinIO content verification (scenario 15)
	@curl -sf $(AUDIT_URL)/verify && echo || echo "audit-log not reachable on $(AUDIT_URL)"

kill-switch-status: ## Current kill-switch scopes: paused agents, halted threads, global stop
	@curl -sf $(CONTROL_PLANE_URL)/status && echo || echo "control-plane not reachable on $(CONTROL_PLANE_URL)"

urls: ## Print every browser-facing URL
	@echo "Console          $(CONSOLE_URL)"
	@echo "Keycloak         http://localhost:8180/admin"
	@echo "Infisical        http://localhost:8443"
	@echo "MinIO console    http://localhost:9001"
	@echo "LiteLLM UI       $(LITELLM_URL)/ui"
	@echo "MLflow           http://localhost:5500"
	@echo "OpenMetadata     http://localhost:8585"
	@echo "Langfuse         http://localhost:3010"
	@echo "Prometheus       http://localhost:9095"
	@echo "Grafana          http://localhost:3020"
	@echo
	@echo "Logins are listed in CREDENTIALS.md (local development only)."
