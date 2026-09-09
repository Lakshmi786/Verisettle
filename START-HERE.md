# VeriSettle — ready to run

Staged 8 Sep 2026. This is a clean clone of `Lakshmi786/Verisettle` @ `0c684b9`
with five first-run defects already fixed and `.env` already written, including
your real OpenAI and Groq keys.

`git status` shows exactly six modified files — those are the fixes. Nothing
else has been touched, and no secret is tracked (`.env` and the rendered
Keycloak realm are both gitignored).

## Already done for you

- [x] Repo cloned
- [x] All 5 fixes applied (see `FIXES` below)
- [x] `make env` run — `.env` written, 0600, both API keys filled in
- [x] **Verified**: `.env` now sources cleanly (this was defect 1 — it used to
      abort every bootstrap script with `./.env: of: not found`)
- [x] **Verified**: `make step0`'s second half — the Keycloak realm renders

## What's left, and it needs Docker

Docker Desktop is not installed on this Mac. Install it, then give it as much
memory as you can spare (Settings > Resources). The README asks for 20 GB;
see "If you're short on RAM" below if you can't.

```sh
brew install --cask docker          # then launch it once
# infisical CLI: already provided at ./bin/infisical (no brew needed)

cd ~/Documents/VeriSettle-ready
make step0                          # docker network + realm (realm already done)
make bootstrap                      # steps 0-2, then stops
#   -> paste INFISICAL_PROJECT_ID, PAYMENT_EXECUTION_CLIENT_ID,
#      PAYMENT_EXECUTION_CLIENT_SECRET (printed) into .env
make bootstrap-data                 # steps 3-4a, then stops
#   -> paste the LITELLM_KEY_AGENT_* values into .env
make bootstrap-finish               # eval gate, Cedar, full stack, sandbox image
```

Then: `make ps`, `make health`, `make validate-policies`, `make verify-audit`,
`make urls`.

Note `bootstrap-finish` runs the DeepEval gate first, which makes **real paid
OpenAI calls**. Small bill, but not zero.

## If you're short on RAM

The six compose files declare 25.2 GiB of memory caps across ~35 containers.
On a MacBook Air, drop the catalog and tracing layers — the governance path
(identity -> policy -> agent runtime -> six payment gates -> ledger -> audit
chain) does not need them:

- skip `om-postgres om-elasticsearch om-migrate om-server om-ingestion` (~10 GB)
- skip `langfuse-clickhouse langfuse-redis langfuse-worker langfuse-web` (~5 GB)
- **still run** `sh infra/scripts/compose.sh up data-loader` — that loads the
  real CORD/SROIE invoices and USAspending vendors, and the pipeline has
  nothing to work on without it.

Leaves roughly 8-9 GB of caps. Prometheus and Grafana stay, so the governance
metrics are still there.

## Check these two images before step 3 (Apple Silicon)

```sh
docker manifest inspect docker.getcollate.io/openmetadata/server:1.13.3 | grep -i arm64
docker manifest inspect ghcr.io/data-privacy-stack/presidio-analyzer:latest | grep -i arm64
```

OpenMetadata's ingestion image has historically been amd64-only, and the
Presidio images are not on Microsoft's publishing path
(`mcr.microsoft.com/presidio-analyzer`) and are the only `:latest` tags in an
otherwise patch-pinned repo. If either is amd64-only, add
`platform: linux/amd64` to that service and it runs under Rosetta.

## FIXES

1. `generate-env.sh` emitted `USASPENDING_AGENCY` unquoted -> every script that
   does `. ./.env` died on it. Killed `make step0` on all platforms.
2. `setup-spire.sh` and `bootstrap-infisical.sh` used GNU `sed -i`; BSD sed on
   macOS rejects it. Rewritten portably.
3. `register-spire-entries.sh` ran `docker exec` before spire-server was
   listening, and every `entry create` is `|| true` — so on a cold start they
   failed *silently*, leaving no SPIFFE entries and no error. Now waits.
4. `bootstrap-infisical.sh` raced Infisical's first-boot migrations. Now waits.
5. The `infisical` CLI was required by step 2 but undocumented. README updated.

Fixes 3-5 are unverified — they need a real run. Paste any error back into the
Claude session and I'll work it.

## No Homebrew on this Mac

The `infisical` CLI that step 2 needs is already here as `./bin/infisical`
(v0.41.90, darwin/arm64, fetched from Infisical's GitHub release). Put it on
PATH for the shell you run `make` in:

```sh
cd ~/Documents/VeriSettle-ready
export PATH="$PWD/bin:$PATH"
infisical --version
```

It was written straight to disk rather than downloaded by a browser, so it
should carry no quarantine flag. If macOS refuses to run it anyway:

```sh
xattr -dr com.apple.quarantine bin/infisical
```
