#!/bin/sh
# Asserts that every per-service database and login role actually exists.
#
# Why this exists: infra/postgres-init/01-create-service-databases.sh runs
# only on Postgres's FIRST init, from a bind mount. If the container cannot
# read it - a restrictive umask on the host checkout, a file-sharing layer
# that presents it as executable-but-unreadable (observed on Docker Desktop
# for Mac: "/bin/sh: bad interpreter: Permission denied") - the entrypoint
# skips it and Postgres comes up perfectly healthy with no service databases
# at all. Keycloak and Infisical then crash-loop on "role does not exist",
# three steps downstream of the actual cause.
#
# Fail loudly here instead. Run from the repo root.
set -eu
cd "$(dirname "$0")/../.."
[ -f .env ] || { echo ".env not found - run: make env" >&2; exit 1; }
set -a
. ./.env
set +a

CONTAINER=verisettle-postgres
EXPECTED="keycloak infisical litellm mlflow langfuse verisettle_ledger verisettle_backend"

echo "waiting for $CONTAINER to accept connections..."
i=0
until docker exec "$CONTAINER" pg_isready -U "$POSTGRES_SUPERUSER" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 45 ]; then
    echo "postgres did not become ready within 90s (docker logs $CONTAINER)" >&2
    exit 1
  fi
  sleep 2
done

missing=""
for db in $EXPECTED; do
  if ! docker exec "$CONTAINER" psql -U "$POSTGRES_SUPERUSER" -d postgres -tAc \
       "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    missing="$missing $db"
  fi
done

if [ -n "$missing" ]; then
  echo >&2
  echo "MISSING service databases:$missing" >&2
  echo >&2
  echo "The Postgres init script never ran. Almost always a permissions problem" >&2
  echo "on the bind mount - the container must be able to READ" >&2
  echo "infra/postgres-init/01-create-service-databases.sh. Check with:" >&2
  echo "  docker logs $CONTAINER 2>&1 | grep -i initdb.d" >&2
  echo >&2
  echo "Fix and re-initialise (this deletes Postgres data, which is empty anyway" >&2
  echo "if the databases were never created):" >&2
  echo "  chmod -R a+rX ." >&2
  echo "  sh infra/scripts/compose.sh down -v" >&2
  echo "  make bootstrap" >&2
  exit 1
fi

echo "all 7 service databases present."
