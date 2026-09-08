# VeriSettle

**In one sentence:** a team of AI agents reads invoices, decides whether
they look safe to pay, and pays the safe ones automatically — while a
separate set of guardrails watches everything the agents do and can prove,
after the fact, exactly what happened and why.

More precisely: a governed multi-agent finance operations platform —
autonomous invoice extraction, fraud/risk scoring, approval routing, and
vendor payment execution, wrapped in six real governance layers (Identity,
Data, Model, Policy, Agent Runtime, Operations).

The point of the project is not the agents. It is that giving an agent
authority to move money is where a mistake stops being a bug and becomes a
financial loss — so every control around it has to do real, load-bearing
work. **Nothing here is mocked.** Invoices come from real public datasets
(CORD, SROIE) with real ground-truth annotations; vendors and payment
history come from the real USAspending.gov award API; the promotion gate is
a real computed evaluation that a genuinely worse prompt genuinely fails.
The one thing that cannot be real — a bank wire — is a full double-entry
ledger service instead, the same sandboxed settlement pattern fintechs
build before going live.

Everything runs locally on Docker Desktop. The only calls leaving your
machine go to the OpenAI and Groq APIs.

See [`INSTRUCTIONS.md`](INSTRUCTIONS.md) for the full specification this
build satisfies, including the design trade-offs that were made
deliberately and the gaps that are documented rather than hidden.

---

## What happens to an invoice

A LangGraph state machine with Postgres checkpointing, so a run can pause
for a human and resume hours later:

```
Extraction -> Risk-Scoring -> Approval -> [human interrupt] -> Payment-Execution
```

1. **Extraction** reads OCR text, or an uploaded image routed through a
   locked-down per-invocation sandbox container, and returns a typed,
   schema-validated invoice. Its prompt is loaded from the MLflow registry
   at the `production` alias, not hardcoded.
2. **Risk-Scoring** asks the ledger what it actually knows about this
   vendor — first-seen date, award count, historical average. It never
   accepts a self-reported "this vendor is known" flag, because that would
   let anyone bypass the first-seen rule by asserting it.
3. **Approval** returns a decision *and* a numeric confidence. Below the
   threshold, a human is required regardless of the decision. A second
   model from the **other provider** then reviews the decision
   adversarially and can force escalation.
4. **Human review** is a real graph interrupt, resumed from the console
   after a Keycloak login. What you may approve depends on your role tier.
5. **Payment-Execution** runs the gate chain: capability manifest, Cedar
   authorization, a dry-run against the real ledger that always rolls back,
   a settlement hold, a **fresh** kill-switch re-check after that hold, the
   double-entry commit with duplicate detection, and only then the vendor
   history update that makes the next invoice from this vendor score
   against real accumulated history.

---

## The six governance layers

| Layer | Tools | What it actually enforces |
|---|---|---|
| **Identity** | Keycloak, SPIFFE/SPIRE, Infisical | Human roles tied to approval-authority tiers. The backend fetches a real X.509 SVID *at import time* — no identity, the container dies before it can serve traffic. Ledger credentials are fetched fresh from the vault before each use, never cached, never written to disk. |
| **Data** | OpenMetadata, Presidio, Great Expectations | Tables tagged `RestrictedFinancial`. PII stripped before anything durable is written. A real data-quality checkpoint with its own runnable self-test. |
| **Model** | LiteLLM, MLflow, DeepEval | One gateway for every LLM call, one virtual key per agent with a model allowlist and a budget cap enforced *before* the call goes out. Prompts are versioned artifacts; the promotion gate grades candidates against held-out ground truth. |
| **Policy** | Cedar, Dogwood | `policies/` is the source of truth: no agent auto-approves above the threshold; a first-seen vendor needs a human regardless of amount; only Payment-Execution may write the ledger. `policies/temporal/` covers the rate limits Cedar's stateless model cannot express. |
| **Agent Runtime** | LangGraph, policy-service PDP, guardrail model, Landlock sandbox | Default-deny authorization before every consequential action, re-checked at every node rather than trusting the previous one. A guardrail classifier on all untrusted content, catching prompt injection *and* business-fraud phrasing. OCR runs in a throwaway container with no network, read-only root, all capabilities dropped, plus a kernel-enforced Landlock ruleset inside it. |
| **Operations** | OpenTelemetry, Langfuse, Prometheus, Grafana | A hash-chained audit log in WORM storage that even root cannot rewrite, verified in two stages (recompute the chain, then byte-compare actual object content). A background watchdog runs that check continuously, so a tamper reverted before anyone looks is still permanently provable. A kill switch with graduated scopes, living outside the agent runtime so a broken agent can never veto its own stop. |

---

## Repository layout

```
services/           every deployable service, one folder each
  backend/            FastAPI + LangGraph agent runtime (the 4 agents are graph nodes)
  ledger/             double-entry ledger, vendors and payment history
  policy-service/     Cedar + temporal rules as a Policy Decision Point
  control-plane/      kill switch and heartbeat watchdog
  audit-log/          hash-chained WORM audit log and tamper watchdog
  data-loader/        one-shot, re-runnable real-data seeding
  sandbox-runner/     launches a fresh OCR sandbox per call
  sandbox-ocr/        the sandbox image itself (built separately)
apps/console/       Next.js dashboard
policies/           Cedar policies, temporal/ rules, schema
infra/
  compose/            six compose files, one per governance layer
  scripts/            bootstrap and provisioning scripts
  deepeval/           the one-shot prompt promotion gate
  keycloak/ spire/ litellm/ mlflow/ prometheus/ grafana/ minio-init/ postgres-init/
docs/scenarios/     one runnable proof per governance control
pyproject.toml      uv workspace root, shared dev tooling
uv.lock             one resolved lock for every workspace service
Makefile            developer entry point - `make help`
```

Each compose file runs standalone, so any single governance layer can be
brought up on its own.

---

## Prerequisites

- **Docker Desktop**, recent stable release, WSL2 backend on Windows.
- **20GB RAM allocated to Docker Desktop, minimum.** Measured steady-state
  usage is ~9-10GB, but Keycloak, SPIRE, Infisical, OpenMetadata, Presidio,
  LiteLLM, MLflow, Langfuse, Prometheus, Grafana and the agent runtime all
  run together, and headroom matters during builds and OpenMetadata's JVM
  startup. On Windows, raise the ceiling in `%UserProfile%\.wslconfig`:
  ```ini
  [wsl2]
  memory=20GB
  processors=8
  ```
  then `wsl --shutdown` and restart Docker Desktop.
- **Disk:** ~25GB free for images.
- **CPU:** 6+ cores recommended.
- **`make`** — ships with macOS and Linux; on Windows it comes with Git
  Bash's toolchain. Every target is a thin wrapper over the commands
  documented below, so it is a convenience, never a requirement.
- **A POSIX shell** (`sh`) for the bootstrap scripts — Git Bash on Windows
  works; every script under `infra/scripts/` is plain `#!/bin/sh`.
- **`uv`** — only for working on the Python code locally. Running the stack
  does not need it; the images install it themselves.

### The two API keys

VeriSettle calls two real providers through LiteLLM. There is no offline or
mocked model path.

- **OpenAI** — the reasoning route, used for risk judgment and any payment
  decision above the routine threshold. Create a key at
  https://platform.openai.com/api-keys.
- **Groq** — the routine-extraction and guardrail routes. Create a key at
  https://console.groq.com/keys.

```sh
make env
```

This writes `.env` with a freshly generated value for every local-only
secret, using the `openssl` calls documented in
[`SECRETS GEN GUIDE.md`](SECRETS%20GEN%20GUIDE.md). There is no
`.env.example` to copy: the layout lives in the generator, so no env file is
ever committed and every clone gets its own distinct secrets. It refuses to
overwrite an existing `.env`, because once the stack has run those values
are baked into your data volumes.

Then open `.env` and set just these two lines:

```
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

---

## First run

```sh
make bootstrap          # steps 0-2, then stops
make bootstrap-data     # steps 3-4a, then stops
make bootstrap-finish   # eval gate, policy validation, full stack, sandbox image
```

It stops twice because two provisioning scripts print values that a human
has to paste into `.env` — `make` does not pretend that part is automatic.
Each stop tells you exactly which variables to paste and what to run next.

Every step is also individually re-runnable, which matters when one fails
halfway:

| Command | What it does | Wait for |
|---|---|---|
| `make step0` | Creates the Docker network, renders the Keycloak realm from `.env` | instant |
| `make step1` | Postgres + MinIO | both `healthy` |
| `make step2` | Keycloak, SPIRE, Infisical; registers the 6 SPIRE entries, mints the agent join token, creates the vault admin and per-service identities | **prints `INFISICAL_PROJECT_ID`, `PAYMENT_EXECUTION_CLIENT_ID`, `PAYMENT_EXECUTION_CLIENT_SECRET` — paste into `.env`** |
| `make step3` | OpenMetadata + Presidio, loads the real CORD/SROIE invoices and USAspending vendors, tags the tables as sensitive | data-loader exits 0; takes a few minutes |
| `make step4-keys` | LiteLLM + MLflow, then one budget-capped key per agent | **prints `LITELLM_KEY_AGENT_*` — paste into `.env`** |
| `make eval-gate` | Grades two real prompt versions; the good one is promoted, the bad one is blocked | makes real paid LLM calls; takes a few minutes |
| `make step5` | Validates the Cedar rulebook | prints `ACCEPTED` |
| `make step6` | Brings up the agent runtime, ledger, PDP, audit log, kill switch, console, dashboards | all `healthy` |
| `make sandbox-image` | Builds the locked-down OCR sandbox | required before any image upload works |

### Confirm it is up

```sh
make ps        # every container and its status
make health    # backend health, including the SPIFFE ID it actually fetched
make urls      # every browser-facing URL
```

A couple of one-shot jobs show `Exited (0)` rather than `healthy` — that is
correct, not a failure. Then check: the Keycloak realm is seeded, the Cedar
policies validate, LiteLLM reaches both providers, and the data loader
reported the record counts it loaded.

---

## Using it

Open the console at http://localhost:3000 and sign in through Keycloak as
one of the seeded demo users — `ap.clerk.demo`, `controller.demo` or
`cfo.demo`, whose passwords are the `DEMO_*_PASSWORD` values in your `.env`.
Their approval authority differs on purpose; the CFO account is the only one
that can approve above the high-value threshold.

The console gives you the live pipeline view (each agent step and the policy
decision at that point), the approval queue for paused runs, the audit log
viewer with a real "verify chain integrity" button, ledger balances and
per-agent spend against budget, the kill switch, and a policy explorer.

**Submit page** takes either pasted OCR text, which skips OCR and is fast,
or a real image upload, which goes through the sandboxed OCR path. Five
ready-made test invoices live in `docs/sample-invoices/` — a clean one, a
first-time vendor with a large amount, a prompt-injection attempt, a
PII-heavy one, and a suspicious round number.
[`docs/testing-your-own-invoice.md`](docs/testing-your-own-invoice.md)
covers using your own.

### Logins

`make urls` prints every URL. The credentials are whatever `make env`
generated on your machine, so there is nothing to look up and nothing to
leak — each one is a variable in your own `.env`:

| Page | URL | Login comes from |
|---|---|---|
| VeriSettle Console | http://localhost:3000 | Keycloak; demo users above, passwords in `DEMO_*_PASSWORD` |
| Keycloak admin | http://localhost:8180/admin | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` |
| Infisical | http://localhost:8443 | `INFISICAL_ADMIN_EMAIL` / `INFISICAL_ADMIN_PASSWORD` |
| MinIO console | http://localhost:9001 | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| LiteLLM UI | http://localhost:4000/ui | `LITELLM_MASTER_KEY` |
| MLflow | http://localhost:5500 | none — deliberately unauthenticated, local only |
| OpenMetadata | http://localhost:8585 | `admin@open-metadata.org` / `admin` — OpenMetadata's own default, not from `.env` |
| Langfuse | http://localhost:3010 | `INFISICAL_ADMIN_EMAIL` address / `LANGFUSE_INIT_USER_PASSWORD` |
| Prometheus | http://localhost:9095 | none |
| Grafana | http://localhost:3020 | `admin` / `GRAFANA_ADMIN_PASSWORD` |

---

## Prove the guardrails work

[`docs/scenarios/`](docs/scenarios/) holds one short, self-contained script
per governance control: run a few real commands against the running stack
and watch a control catch something, or correctly let it through. Every one
was actually run against a live system before being written down — the
outputs shown are real.

Start with `01-end-to-end-happy-path.md` to watch a normal invoice get paid,
then work through the layers that would have stopped it if something were
wrong: credential brokering, PII redaction, the eval gate passing and
failing, a policy change accepted and rejected, prompt injection through a
poisoned document, sandbox isolation, cost caps, the kill switch, and audit
log tamper resistance.
[`docs/scenarios/README.md`](docs/scenarios/README.md) indexes them all and
suggests a teaching order grouped by layer.

Shortcuts for the checks those docs run by hand:

```sh
make verify-audit         # two-stage hash-chain and WORM content verification
make kill-switch-status   # paused agents, halted threads, frozen tools, global stop
make validate-policies    # the real Cedar validator
```

---

## Development

The Python services are a **uv workspace**: one lock file, one resolution,
each service declaring its own dependencies in its own `pyproject.toml`.
There are no `requirements.txt` files.

```sh
make sync        # create the local dev environment from the lock
make lint        # ruff
make format      # ruff format
make typecheck   # mypy
make test        # pytest
make check       # all of the above
make lock        # re-resolve every lock file after changing a dependency
```

Two jobs sit deliberately outside that workspace, each with its own lock:

- **`services/sandbox-ocr`** — the image that parses untrusted documents.
  Keeping it out of the shared resolution means nothing another service
  pulls in can widen the dependency surface of the one process that touches
  attacker-controlled input.
- **`infra/deepeval`** — a genuine conflict, not tidiness: deepeval pins
  `click<8.4.0` while `huggingface-hub` requires `click>=8.4.0`. They cannot
  share one resolution, so they do not pretend to.

Service images build from a repo-root context so they can see the workspace
lock, and install with `uv sync --frozen`, which fails the build rather than
silently resolving something the lock does not describe.

`make help` lists every target.

---

## Troubleshooting

These are real, previously-encountered failure modes, not generic advice.

**A container reports `healthy` but is unreachable from the host** (common
after a WSL2 restart). Its healthcheck runs inside its own network
namespace and stays green even when Docker Desktop's host-side port
forwarding did not come back. Rebind it:

```sh
make restart SERVICE=<name>
```

**Every bind mount breaks at once on Windows.** A stopped or idle Docker
Desktop VM can wedge WSL2's synthetic mount tree at the drive-root level,
which survives a plain restart or even `--force-recreate`. Fix: `wsl
--shutdown`, reopen Docker Desktop, then `make up`.

**Langfuse fails after Postgres was recreated.** Its Node/Prisma services
hold a persistent connection pool that does not survive the database being
replaced, unlike the Python services which open a fresh connection per
request. `make restart SERVICE=langfuse-web` and the same for
`langfuse-worker`.

**`spire-agent` crash-loops on "join token does not exist or has already
been used".** Join-token attestation is single-use by design. If the agent
lost its persisted identity, it genuinely cannot self-heal — this is
correct fail-closed behaviour, not a bug:

```sh
sh infra/scripts/setup-spire.sh
make restart SERVICE=spire-agent
```

**LiteLLM returns an empty response on `/health/liveliness`.** It is still
migrating. Re-run until you get a real reply.

**`make env` refuses to run.** That is deliberate: a `.env` already exists
and its secrets are baked into your data volumes. To start genuinely fresh,
`make clean` and then `FORCE=1 make env`.

---

## Honest limitations

The project documents what it does not do rather than hiding it. In short:
SPIRE attests one identity per OS process and the four agents are function
calls inside one process, so per-agent separation is enforced by Cedar and
the capability manifests instead — documented, not papered over. A
self-hosted Langfuse may not price internal model-route names even though
token counts are captured correctly. Policy validation is run manually per
this README; there is no CI in this project, and it does not imply one.
[`INSTRUCTIONS.md`](INSTRUCTIONS.md) sections 5 and 10 carry the full list,
including the controls whose real failure cases were tested and what those
tests actually revealed.
