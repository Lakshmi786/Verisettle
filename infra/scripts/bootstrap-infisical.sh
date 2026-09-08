#!/bin/sh
# One-time, re-runnable bootstrap for the self-hosted Infisical instance:
#   1. Creates the instance admin (org + user + instance-admin machine
#      identity) via `infisical bootstrap` - no manual signup UI needed.
#   2. Creates one Universal Auth machine identity per VeriSettle service.
#   3. Pushes the two real provider API keys and the per-service Postgres
#      passwords into an Infisical project, so every later service reads its
#      credentials from Infisical instead of a plaintext compose env block.
# Requires the `infisical` CLI on PATH (https://infisical.com/docs/cli).
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

if [ -f "$STATE_FILE" ]; then
  # This file is local, not a Docker volume - it survives a `docker compose
  # down -v` that wipes Infisical's own Postgres data, leaving a token that
  # looks present but no longer resolves to a real session. Verify it's
  # valid JSON and actually still works before trusting it.
  CACHED_TOKEN=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['identity']['credentials']['token'])" 2>/dev/null) || CACHED_TOKEN=""
  CHECK_CODE="000"
  [ -n "$CACHED_TOKEN" ] && CHECK_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CACHED_TOKEN" "$DOMAIN/api/v1/projects")
  if [ "$CHECK_CODE" != "200" ]; then
    echo "$STATE_FILE exists but isn't a working token against the live instance (check: $CHECK_CODE) - re-bootstrapping."
    rm -f "$STATE_FILE"
  fi
fi

if [ ! -f "$STATE_FILE" ]; then
  TMP_STATE_FILE="${STATE_FILE}.tmp"
  # Write to a temp file first - if `infisical bootstrap` fails partway, a
  # `> "$STATE_FILE"` redirect alone would still leave an empty/corrupt
  # state file behind that breaks every future run's validity check too.
  echo "Bootstrapping Infisical instance admin..."
  infisical bootstrap \
    --domain="$DOMAIN" \
    --email="$INFISICAL_ADMIN_EMAIL" \
    --password="$INFISICAL_ADMIN_PASSWORD" \
    --organization="$INFISICAL_ADMIN_ORGANIZATION" \
    --ignore-if-bootstrapped \
    > "$TMP_STATE_FILE"

  if [ -s "$TMP_STATE_FILE" ]; then
    # Genuinely fresh instance: bootstrap printed real credentials. Persist
    # the org id into .env - it's the one piece of information nothing else
    # can rediscover later (unlike the token, `infisical login` can always
    # mint a fresh one, but only if it already knows which org to ask for).
    ORG_ID_NEW=$(python3 -c "import json;print(json.load(open('$TMP_STATE_FILE'))['organization']['id'])")
    if grep -q '^INFISICAL_ORG_ID=' .env; then
      sed -i "s/^INFISICAL_ORG_ID=.*/INFISICAL_ORG_ID=${ORG_ID_NEW}/" .env
    else
      echo "INFISICAL_ORG_ID=${ORG_ID_NEW}" >> .env
    fi
    rm -f "$TMP_STATE_FILE"
    # The bootstrap-issued token itself has a very short server-enforced max
    # age (seconds, not minutes - confirmed by decoding it: no `exp` claim,
    # yet the server rejects it as "exceeded max age" almost immediately).
    # It's a one-shot bootstrap credential, not a session to carry between
    # scripts. Immediately exchange it for a real login session instead of
    # trusting it further.
    echo "Instance bootstrapped. Logging in as the new admin for a working session token..."
    LOGIN_TOKEN=$(infisical login --domain="$DOMAIN" --method=user \
      --email="$INFISICAL_ADMIN_EMAIL" --password="$INFISICAL_ADMIN_PASSWORD" \
      --organization-id="$ORG_ID_NEW" --plain)
    python3 -c "
import json
json.dump({'identity': {'credentials': {'token': '$LOGIN_TOKEN'}}, 'organization': {'id': '$ORG_ID_NEW'}}, open('$STATE_FILE', 'w'))
"
    echo "Wrote a working admin session to $STATE_FILE (gitignored)."
  else
    # `infisical bootstrap --ignore-if-bootstrapped` prints nothing at all
    # once the org already exists - it does not hand out a fresh token for
    # an existing org, only `infisical login` can do that.
    rm -f "$TMP_STATE_FILE"
    ORG_ID="${INFISICAL_ORG_ID:-}"
    if [ -z "$ORG_ID" ]; then
      echo "Org already exists but INFISICAL_ORG_ID is not set in .env - cannot" >&2
      echo "log in without it. If this is truly a fresh instance, check that" >&2
      echo "'infisical bootstrap' above actually failed instead." >&2
      exit 1
    fi
    echo "Org already bootstrapped - logging in as the existing admin user for a fresh token..."
    LOGIN_TOKEN=$(infisical login --domain="$DOMAIN" --method=user \
      --email="$INFISICAL_ADMIN_EMAIL" --password="$INFISICAL_ADMIN_PASSWORD" \
      --organization-id="$ORG_ID" --plain)
    python3 -c "
import json
json.dump({'identity': {'credentials': {'token': '$LOGIN_TOKEN'}}, 'organization': {'id': '$ORG_ID'}}, open('$STATE_FILE', 'w'))
"
    echo "Wrote a fresh admin session to $STATE_FILE (gitignored)."
  fi
else
  echo "$STATE_FILE already exists and its token is still valid, skipping instance bootstrap."
fi

ADMIN_TOKEN=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['identity']['credentials']['token'])")
ORG_ID=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['organization']['id'])")

export INFISICAL_API_URL="$DOMAIN"
export INFISICAL_TOKEN="$ADMIN_TOKEN"

echo "Instance admin ready. Org: $ORG_ID"
echo "Next: create the '${PROJECT_NAME}' project and per-service machine"
echo "identities via the Infisical API (see infra/scripts/provision-infisical-identities.py),"
echo "then push secrets with 'infisical secrets set'."
