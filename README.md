# Custodian

**In one sentence:** a team of AI agents reads invoices, decides whether
they look safe to pay, and pays the safe ones automatically — while a
separate set of guardrails watches everything the agents do and can prove,
after the fact, exactly what happened and why.

More precisely: a governed multi-agent finance operations platform —
autonomous invoice extraction, fraud/risk scoring, approval routing, and
vendor payment execution, wrapped in six real governance layers (Identity,
Data, Model, Policy, Agent Runtime, Operations). See
[`INSTRUCTIONS.md`](INSTRUCTIONS.md) for the full specification this build
satisfies.

## 1. Prerequisites

- **Docker Desktop**, recent stable release, WSL2 backend on Windows.
- **RAM: 20GB allocated to Docker Desktop's VM, minimum.** This stack runs
  Keycloak, SPIRE, Infisical, OpenMetadata (Postgres + Elasticsearch +
  Airflow-based ingestion), Presidio, LiteLLM, MLflow, Langfuse (its own
  ClickHouse + Redis), Prometheus, Grafana, and the full agent runtime
  simultaneously — measured steady-state usage across this build is
  ~9-10GB, but headroom matters during builds and OpenMetadata's JVM startup.
  On Windows, raise the ceiling in `%UserProfile%\.wslconfig`:
  ```ini
  [wsl2]
  memory=20GB
  processors=8
  ```
  then `wsl --shutdown` and restart Docker Desktop.
- **Disk:** ~25GB free for images alone.
- **CPU:** 6+ cores recommended (8 used throughout this build).
- **`make`** — the developer entry point (`make help`). Present by default on
  macOS and Linux; on Windows it ships with Git Bash's toolchain or via
  `choco install make`. Every target is a thin wrapper over the same
  commands documented below, so `make` is a convenience, never a
  requirement.
- **`uv`** — only needed to work on the Python code locally (`make sync`,
  `make check`, `make lock`). Running the stack does not need it: the
  service images install `uv` themselves. Install from https://docs.astral.sh/uv/.
- A POSIX shell for the bootstrap scripts (`sh`) — Git Bash on Windows
  works; every script under `infra/scripts/` is plain `#!/bin/sh`.

## 2. Getting the two API keys

Custodian calls two real LLM providers through LiteLLM — there is no offline
or mocked model path.

- **OpenAI** (`custodian-reasoning` route, `gpt-5.6-sol`): create a key at
  https://platform.openai.com/api-keys. Needs standard chat-completions
  access; no special tier required for this workload's volume.
- **Groq** (`custodian-routine` and `custodian-guardrail` routes,
  `openai/gpt-oss-120b` and `openai/gpt-oss-safeguard-20b`): create a key at
  https://console.groq.com/keys.

```sh
cp .env.example .env
```
`.env.example` already has a real random value filled in for every
local-only secret — open `.env` and change just these two lines:

```
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

`.env` is gitignored — never commit it. Everything else in it either
already has a working value, or gets filled in automatically by a setup
script later in §3.


## 3. First run

Every step below is also a `make` target. `make help` lists all of them.
The short version, if you just want the sequence:

```sh
make bootstrap          # steps 0-2, stops so you can paste Infisical values into .env
make bootstrap-data     # steps 3-4a, stops so you can paste the LiteLLM keys into .env
make bootstrap-finish   # eval gate, policy validation, full stack, sandbox image
```

`make` stops at exactly the two points where a provisioning script prints
values a human has to paste into `.env` — it does not pretend that part is
automatic. The long form below explains what each step actually does, and
every step remains individually re-runnable (`make step3`, `make step5`, …).

### Step 0 — one-time setup
```sh
docker network create custodian-net
```
`make step0` does this step and the next one together.
Creates a private virtual network inside Docker so all the Custodian containers can find and talk to each other by name 

---


```sh
sh infra/scripts/render-keycloak-realm.sh
```
Fills in the Keycloak login system's config file with real passwords from your .env, so Keycloak starts up already set up instead of empty.

---

### Step 1 — Foundations (shared database + file storage)

```sh
sh infra/scripts/compose.sh up -d postgres minio     # or: make step1
```

Starts the shared database (Postgres) and file storage (MinIO) in the background

---

### Step 2 — Identity (logins, secrets, service identities)

```sh
sh infra/scripts/compose.sh up -d keycloak spire-server infisical-redis infisical
```

All of Step 2 is `make step2`.

Starts the login system (Keycloak), the identity-issuing service (SPIRE), and the secrets vault (Infisical) in the background.

---

```sh
sh infra/scripts/register-spire-entries.sh
```
Registers the 4 AI agents (plus the backend itself) with SPIRE, so it knows how to recognize each one and issue it a real ID.

---

```sh
sh infra/scripts/setup-spire.sh
sh infra/scripts/compose.sh up -d --force-recreate spire-agent
```
First command generates a one-time "invite code" (join token) SPIRE needs and saves it to .env; second command restarts the SPIRE agent so it picks up that token and gets its identity.

---


```sh
sh infra/scripts/bootstrap-infisical.sh
python3 infra/scripts/provision-infisical-identities.py
```
First command creates the vault's admin account. Second command creates a login for each service and stores your real passwords/keys inside the vault — it'll print some values you need to copy into .env.

**The second command prints values you need to copy into `.env`** —
`INFISICAL_PROJECT_ID`, `PAYMENT_EXECUTION_CLIENT_ID`,
`PAYMENT_EXECUTION_CLIENT_SECRET`. Paste them in now.

---

### Step 3 — Data (real invoice + vendor datasets)

```sh
sh infra/scripts/compose.sh up -d om-postgres om-elasticsearch om-migrate om-server om-ingestion presidio-analyzer presidio-anonymizer
```

All of Step 3 is `make step3`.
Starts the data catalog system (OpenMetadata, which tags sensitive data) and Presidio (which detects personal info like emails or account numbers) in the background.

---

```sh
sh infra/scripts/compose.sh up data-loader
```

Downloads real invoice data and real vendor/payment data from public sources(SROIE, CORD) and real U.S. government and loads them into the database — takes a couple minutes

---


```sh
python3 infra/scripts/register-openmetadata-catalog.py
```
Marks the newly-loaded tables in the data catalog as "contains sensitive data," so the system knows to treat them carefully.

---

### Step 4 — Model (the AI gateway + prompt quality gate)

```sh
sh infra/scripts/compose.sh up -d litellm-redis litellm mlflow
```

Step 4 up to the key provisioning is `make step4-keys`; the gate below is
`make eval-gate`.

Starts LiteLLM (the single gateway all AI calls go through) and MLflow (which tracks which prompt versions are good enough to use) in the background.

```sh
curl http://localhost:4000/health/liveliness
```
Empty response means it's still migrating - just re-run the same command
again until you see a real reply.

```sh
python3 infra/scripts/provision-litellm-keys.py
```

Creates a separate AI-access key for each agent, each with its own spending limit — it'll print values you need to copy into .env

---


```sh
sh infra/scripts/compose.sh up deepeval-gate
```

Runs a real grading test on two versions of the invoice-reading prompt — the good one gets approved for use, the bad one gets blocked. Takes a few minutes.

---

### Step 5 — Policy (check the rulebook is valid)

```sh
python3 infra/scripts/validate-cedar-policies.py     # or: make validate-policies
```

Checks that the real approval rulebook (Cedar policies) is written correctly and makes the right decisions — should print ACCEPTED with no errors.

---

### Step 6 — Agent runtime + everything else

```sh
sh infra/scripts/compose.sh up -d                    # or: make step6
```

Starts everything else at once — the AI agents, the ledger, the policy checker, the audit log, the kill switch, the web console, and the dashboards.

---



```sh
docker build -t custodian-sandbox-ocr:latest services/sandbox-ocr/   # or: make sandbox-image
```

Builds the locked-down sandbox image used to safely read scanned invoice images — without this, uploading an invoice photo won't work..

---

### Confirm everything is up

```sh
sh infra/scripts/compose.sh ps --format "table {{.Name}}\t{{.Status}}"   # or: make ps
```

Lists every running container and its status, so you can check that everything shows healthy before moving on.

---

### Opening all the UI Components

**Refer to the CRDENTIALS.md for this**