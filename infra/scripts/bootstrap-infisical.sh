#!/bin/sh
# One-time, re-runnable bootstrap for the self-hosted Infisical instance:
#   1. Creates the instance admin (org + user + instance-admin machine
#      identity) via `infisical bootstrap` - no manual signup UI needed.
#   2. Exchanges that for a real admin session token.
#   3. Later scripts (provision-infisical-identities.py) use that token.
#
# Requires the `infisical` CLI >= 0.43 on PATH. Older builds (0.41.x) do not
# accept --email/--password on `login` and fail with "unknown flag: --email".
set -eu

cd "$(dirname "$0")/../.."
[ -f .env ] || { echo ".env not found - run: make env" >&2; exit 1; }
set -a
. ./.env
set +a

if [ "${OPENAI_API_KEY}" = "sk-replace-me" ] || [ "${GROQ_API_KEY}" = "gsk-replace-me" ]; then
  echo "OPENAI_API_KEY / GROQ_API_KEY still have placeholder values in .env - fill in the real keys before running this." >&2
  exit 1
fi

DOMAIN="http://localhost:8443"
PROJECT_NAME="verisettle"
STATE_FILE=".infisical-bootstrap.json"

# Infisical runs its database migrations on first boot and only then starts
# answering. `up -d` has long since returned by that point, so wait for the
# real readiness signal rather than letting the first API call fail.
echo "waiting for Infisical at ${DOMAIN} ..."
i=0
until curl -fsS "${DOMAIN}/api/status" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 90 ]; then
    echo "Infisical did not come up within 180s (docker logs verisettle-infisical)" >&2
    exit 1
  fi
  sleep 2
done

if [ -f "$STATE_FILE" ]; then
  # This file is local, not a Docker volume - it survives a `docker compose
  # down -v` that wipes Infisical's own Postgres data, leaving a token that
  # looks present but no longer resolves. Verify before trusting it.
  CACHED_TOKEN=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['identity']['credentials']['token'])" 2>/dev/null) || CACHED_TOKEN=""
  CHECK_CODE="000"
  [ -n "$CACHED_TOKEN" ] && CHECK_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CACHED_TOKEN" "$DOMAIN/api/v1/projects")
  if [ "$CHECK_CODE" != "200" ]; then
    echo "$STATE_FILE exists but is not a working token (check: $CHECK_CODE) - re-bootstrapping."
    rm -f "$STATE_FILE"
  fi
fi

if [ ! -f "$STATE_FILE" ]; then
  TMP_STATE_FILE="${STATE_FILE}.tmp"
  echo "Bootstrapping Infisical instance admin..."
  infisical bootstrap \
    --domain="$DOMAIN" \
    --email="$INFISICAL_ADMIN_EMAIL" \
    --password="$INFISICAL_ADMIN_PASSWORD" \
    --organization="$INFISICAL_ADMIN_ORGANIZATION" \
    --ignore-if-bootstrapped \
    > "$TMP_STATE_FILE" || true

  if [ -s "$TMP_STATE_FILE" ]; then
    # Genuinely fresh instance. Persist the org id - it is the one thing
    # nothing can rediscover later; `infisical login` can always mint a fresh
    # token, but only if it already knows which org to ask for.
    ORG_ID=$(python3 -c "import json;print(json.load(open('$TMP_STATE_FILE'))['organization']['id'])")
    if grep -q '^INFISICAL_ORG_ID=' .env; then
      TMP_ENV=$(mktemp)
      sed "s/^INFISICAL_ORG_ID=.*/INFISICAL_ORG_ID=${ORG_ID}/" .env > "$TMP_ENV"
      cat "$TMP_ENV" > .env
      rm -f "$TMP_ENV"
    else
      echo "INFISICAL_ORG_ID=${ORG_ID}" >> .env
    fi
    rm -f "$TMP_STATE_FILE"
  else
    # `bootstrap --ignore-if-bootstrapped` prints nothing once the org exists
    # and hands out no token, so fall back to the org id recorded in .env.
    rm -f "$TMP_STATE_FILE"
    ORG_ID="${INFISICAL_ORG_ID:-}"
    if [ -z "$ORG_ID" ]; then
      echo "Org already exists but INFISICAL_ORG_ID is not set in .env - cannot" >&2
      echo "log in without it. Reset Infisical's database and re-run, or set" >&2
      echo "INFISICAL_ORG_ID (and optionally INFISICAL_ADMIN_TOKEN) by hand." >&2
      exit 1
    fi
    echo "Org already bootstrapped - reusing INFISICAL_ORG_ID from .env."
  fi

  # One login path for both cases. The bootstrap-issued identity token is NOT
  # a usable session (verified against this instance: /api/v1/projects answers
  # 401 with it), so a real user login is always required.
  if [ -n "${INFISICAL_ADMIN_TOKEN:-}" ]; then
    LOGIN_TOKEN="$INFISICAL_ADMIN_TOKEN"
    echo "Using INFISICAL_ADMIN_TOKEN from the environment."
  else
    echo "Logging in as $INFISICAL_ADMIN_EMAIL for a working session token..."
    LOGIN_TOKEN=$(infisical login --domain="$DOMAIN" --method=user \
      --email="$INFISICAL_ADMIN_EMAIL" --password="$INFISICAL_ADMIN_PASSWORD" \
      --organization-id="$ORG_ID" --plain --silent)
  fi

  if [ -z "$LOGIN_TOKEN" ]; then
    echo "infisical login returned no token." >&2
    echo "Check the CLI is >= 0.43 (infisical --version); 0.41.x has no --email flag." >&2
    exit 1
  fi

  python3 -c "
import json
json.dump({'identity': {'credentials': {'token': '$LOGIN_TOKEN'}}, 'organization': {'id': '$ORG_ID'}}, open('$STATE_FILE', 'w'))
"
  echo "Wrote a working admin session to $STATE_FILE (gitignored)."
else
  echo "$STATE_FILE already exists and its token is still valid, skipping instance bootstrap."
fi

ADMIN_TOKEN=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['identity']['credentials']['token'])")
ORG_ID=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['organization']['id'])")

export INFISICAL_API_URL="$DOMAIN"
export INFISICAL_TOKEN="$ADMIN_TOKEN"

echo "Instance admin ready. Org: $ORG_ID"
echo "Next: create the '${PROJECT_NAME}' project and per-service machine"
echo "identities via infra/scripts/provision-infisical-identities.py."
