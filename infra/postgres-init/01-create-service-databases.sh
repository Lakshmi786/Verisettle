#!/bin/sh
# Runs once, on first init of the shared Postgres data volume.
# Creates one database + one login role per service, with the password
# supplied by the environment (see .env PGPASS_* / docker-compose.base.yml)
# rather than generated inside the container, so nothing has to write to a
# shared volume and there is no cross-container permission dance.
set -eu

# service_name:password_env_var
MAPPINGS="
keycloak:PGPASS_KEYCLOAK
infisical:PGPASS_INFISICAL
litellm:PGPASS_LITELLM
mlflow:PGPASS_MLFLOW
langfuse:PGPASS_LANGFUSE
verisettle_ledger:PGPASS_VERISETTLE_LEDGER
verisettle_backend:PGPASS_VERISETTLE_BACKEND
"

for pair in $MAPPINGS; do
  svc="${pair%%:*}"
  var="${pair##*:}"
  eval "pw=\${$var:?missing $var in environment}"

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${svc}') THEN
        CREATE ROLE ${svc} LOGIN PASSWORD '${pw}';
      ELSE
        ALTER ROLE ${svc} WITH PASSWORD '${pw}';
      END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE ${svc} OWNER ${svc}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${svc}')\gexec

    GRANT ALL PRIVILEGES ON DATABASE ${svc} TO ${svc};
EOSQL
done
