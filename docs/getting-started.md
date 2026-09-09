# Getting started

The [README](../README.md) has the short version. This is the same first run
with everything spelled out: what each command actually prints, what you have
to paste where, how to tell a step finished properly, and what to do when one
doesn't.

If you have run it before and just want the commands, go back to the README.

---

## Before you begin

Work through the [prerequisites](../README.md#1-prerequisites) first. Two of
them cause almost all first-run failures:

**The `infisical` CLI must be 0.43 or newer.** Step 2 calls it directly. At
0.41 and earlier it fails with `unknown flag: --email`, because the CLI moved
to its own repository at 0.43 and the login flags changed.

```sh
infisical --version     # must be >= 0.43
```

**Docker needs enough memory, and the failure is silent.** See
[Choosing a memory allocation](#choosing-a-memory-allocation) below. If you
under-allocate, containers are killed during startup and log nothing — you
will not get an error message telling you memory was the problem.

---

## Step 0 — your environment file

```sh
make env
```

Writes `.env`, mode 0600, with a freshly generated value for every local
secret. There is no committed template: the layout lives inside
`infra/scripts/generate-env.sh`, so no env file is ever committed and every
clone gets different secrets. If `.env` already exists the command refuses
rather than overwriting, because once the stack has run those values are
baked into your Postgres, Keycloak and MinIO volumes.

Then open `.env` and set the only two values it cannot generate:

```
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

Everything else is already filled in.
[`secrets-reference.md`](secrets-reference.md) explains what each generated
secret is for and why it is the length it is.

**Check it before going further.** A single unquoted value with a space in it
will break every script that sources this file:

```sh
sh -c '. ./.env && echo ok'
```

If this prints anything other than `ok` — `./.env: of: not found` is the
classic — fix the quoting first. Nothing downstream will work until it
sources cleanly.

---

## Steps 1 and 2 — foundations and identity

```sh
make bootstrap
```

This runs `step0`, `step1` and `step2` and then **stops on purpose**.

- **step0** creates the Docker network and renders the Keycloak realm from
  `.env`. Returns immediately.
- **step1** brings up Postgres and MinIO and creates the seven service
  databases. It finishes by running `infra/scripts/verify-service-databases.sh`,
  which exists because this genuinely failed before: Postgres reported
  `healthy` with no service databases in it, and Keycloak and Infisical then
  crash-looped on `role ... does not exist` two steps later.
- **step2** brings up Keycloak, SPIRE and Infisical, registers six SPIRE
  entries, mints the agent join token, creates the vault admin and the seven
  service identities.

**What you must do now.** Step 2 prints three values. Paste them into `.env`:

```
INFISICAL_PROJECT_ID=...
PAYMENT_EXECUTION_CLIENT_ID=...
PAYMENT_EXECUTION_CLIENT_SECRET=...
```

**Confirm before moving on:**

```sh
make ps                                       # keycloak, infisical, spire-server healthy
sh infra/scripts/verify-service-databases.sh  # all seven
```

`spire-agent` shows `Up` with no health status. It has no healthcheck
defined; that is expected, not a failure.

---

## Steps 3 and 4a — data and model gateway

```sh
make bootstrap-data
```

Runs `step3` and `step4-keys`, then stops again.

**step3** brings up OpenMetadata and Presidio, loads the real datasets, and
tags the catalog. The load takes a few minutes and pulls from Hugging Face and
USAspending.gov, so it needs working outbound network from inside the
containers. Expect exactly:

```
CORD:  150 train, 40 test
SROIE: 250 train, 60 test
       300 historical payments across 159 vendors
```

**step4-keys** brings up LiteLLM and MLflow and mints one virtual key per
agent, each scoped to only the model routes that agent's capability manifest
allows, each with a real 24-hour budget cap.

**What you must do now.** Paste the four printed keys into `.env`:

```
LITELLM_KEY_AGENT_EXTRACTION=sk-...
LITELLM_KEY_AGENT_RISK_SCORING=sk-...
LITELLM_KEY_AGENT_APPROVAL=sk-...
LITELLM_KEY_AGENT_PAYMENT_EXECUTION=sk-...
```

And set one more that the script does not print:

```
LITELLM_EXTRACTION_KEY=<same value as LITELLM_KEY_AGENT_EXTRACTION>
```

`generate-env.sh` labels this one auto-filled, but
`provision-litellm-keys.py` never writes it. Left empty, the eval gate falls
back to `LITELLM_MASTER_KEY` and runs unscoped and unbudgeted — it works, but
it defeats the point of per-agent keys.

### If step4-keys stalls

`make step4-keys` waits for LiteLLM to answer `/health/liveliness`, giving up
after six minutes with instructions. If it gives up, LiteLLM is
restart-looping. The most likely cause is memory: the `litellm-database`
image runs a Prisma migration alongside the Python proxy at startup, and that
is its peak. Its limit lives in
`infra/compose/docker-compose.model.yml` — note that raising Docker Desktop's
overall allocation does nothing if the *container's* cap is below what it
needs. See [when a container will not stay up](../README.md#a-container-will-not-stay-up).

---

## Step 4b onwards — gate, policies, application

```sh
make bootstrap-finish
```

Runs the eval gate, the Cedar validation, the application layer and the
sandbox image.

**The eval gate makes real paid LLM calls.** It grades two prompt versions
against 60 held-out SROIE records. A correct run promotes one and blocks the
other:

```
v1-production: accuracy=0.654 -> PROMOTED (mlflow v1)
v2-candidate:  accuracy=0.000 -> BLOCKED  (mlflow v2)
```

If both pass, or both fail, the gate is not discriminating and something is
wrong with it — that outcome is the whole reason two prompts exist.

**Cedar validation** should print `ACCEPTED` with the policy count, the
schema result, and the authorization test matrix. `make validate-policies`
uses your host `python3` if it can import `cedarpy`, and otherwise runs the
validator in a throwaway container, so it works on a machine with nothing
installed but Docker.

**The application layer** is `make step6`. It names the services it starts —
the agent runtime, ledger, PDP, audit log, kill switch, console and the two
dashboards — rather than starting everything, so it fits a normal machine.
`make step6-full` adds Langfuse and needs the full allocation.

Then confirm with the [first-run checklist](../README.md#first-run-checklist).

---

## Choosing a memory allocation

Declared container limits sum to **25.2 GiB across ~35 containers** for the
full stack. Limits are ceilings rather than reservations, so the stack does
not need 25 GB of real memory — but the failure mode when you are short is a
container being SIGKILLed during startup with no log output at all, which is
easy to misdiagnose as almost anything else.

| You have allocated | Run |
|---|---|
| 20 GB or more | Everything. `make step6-full`. |
| 10-20 GB | The governance path. `make step6`. |
| Under 10 GB | The governance path with the trim below. Expect to stop services around the heavy steps. |

### Trimming for a small machine

The governance path — identity, policy, agent runtime, the six payment gates,
ledger, audit chain — does not need the catalog or tracing layers. Skip:

- `om-postgres om-elasticsearch om-migrate om-server om-ingestion` (~10 GB)
- `presidio-analyzer presidio-anonymizer` (~1 GB)
- `langfuse-clickhouse langfuse-redis langfuse-worker langfuse-web` (~5 GB)

**Still run the data loader.** The pipeline has nothing to work on without it:

```sh
sh infra/scripts/compose.sh up data-loader
```

Prometheus and Grafana stay, so the governance metrics are still there.

On a very tight machine you can also stop services temporarily around a heavy
step — `docker stop verisettle-keycloak verisettle-infisical` frees about 1.8
GB while LiteLLM starts, for example. Two cautions: the backend needs
Infisical at *runtime* (it brokers the ledger credential fresh per call), so
Infisical has to be back up before `make step6`; and do not stop
`spire-agent`, because its join token is single-use and restarting it means
re-running `infra/scripts/setup-spire.sh`.

---

## Apple Silicon

Two images are worth checking before step 3, because neither is on a
publisher's usual arm64 path:

```sh
docker manifest inspect docker.getcollate.io/openmetadata/server:1.13.3 | grep -i arm64
docker manifest inspect ghcr.io/data-privacy-stack/presidio-analyzer:latest | grep -i arm64
```

OpenMetadata's ingestion image has historically been amd64-only, and the
Presidio images are not on Microsoft's publishing path
(`mcr.microsoft.com/presidio-analyzer`) and are the only `:latest` tags in an
otherwise patch-pinned repo. If either is amd64-only, add
`platform: linux/amd64` to that service and it runs under Rosetta.

Everything else in the stack has been built and run natively on arm64.

---

## No Homebrew?

The `infisical` CLI is the only host binary the bootstrap needs. Without
Homebrew, download the release for your platform from
[github.com/Infisical/cli/releases](https://github.com/Infisical/cli/releases)
(0.43 or newer), put it somewhere on your `PATH`, and confirm:

```sh
infisical --version
```

On macOS, a binary downloaded by a browser carries a quarantine flag and will
be refused. Clear it with:

```sh
xattr -dr com.apple.quarantine /path/to/infisical
```

---

## When something fails

Work in this order:

1. **`make ps`** — find the service that isn't `healthy`. A service showing
   `Up 10 seconds` when its neighbours show hours is restart-looping, which is
   a different problem from one that never started.
2. **Run it in the foreground.** This is the single most useful command in the
   repo when a container misbehaves, because it gives you a real exit code and
   unbuffered output instead of a restart loop that hides both:

   ```sh
   sh infra/scripts/compose.sh run --rm <service>; echo "exit=$?"
   ```

3. **`exit=137` means SIGKILL**, which almost always means memory. Raise that
   service's limit in its compose file, or free memory by stopping something
   else.
4. Check the [troubleshooting table](../README.md#everything-else) for the
   specific symptom.

Do **not** diagnose from `docker inspect ... .State.ExitCode` or
`.State.OOMKilled` while the container is running or restarting. Both fields
describe the current state and read `0` and `false` regardless of how the last
run ended. They will point you away from the real cause.
