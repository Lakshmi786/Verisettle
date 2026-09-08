#!/bin/sh
# Thin wrapper so day-to-day commands don't need six repeated -f flags.
# Usage: sh infra/scripts/compose.sh [any real `docker compose` subcommand/args]
#   sh infra/scripts/compose.sh up -d
#   sh infra/scripts/compose.sh ps
#   sh infra/scripts/compose.sh logs -f custodian-backend
#
# Each layer's compose file still works completely on its own (Ground Rule:
# every governance layer independently demonstrable) - this script is only
# a convenience for bringing up the full stack at once.
set -eu
cd "$(dirname "$0")/../.."

exec docker compose --env-file .env -p custodian \
  -f infra/compose/docker-compose.base.yml \
  -f infra/compose/docker-compose.identity.yml \
  -f infra/compose/docker-compose.data.yml \
  -f infra/compose/docker-compose.model.yml \
  -f infra/compose/docker-compose.app.yml \
  -f infra/compose/docker-compose.observability.yml \
  "$@"
