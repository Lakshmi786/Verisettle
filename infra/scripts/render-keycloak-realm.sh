#!/bin/sh
# Renders infra/keycloak/realm-verisettle.template.json (tracked, no secrets)
# into infra/keycloak/realm-verisettle.json (gitignored, real secrets baked
# in) so Keycloak can --import-realm it on startup without manual UI setup.
# Run from repo root: sh infra/scripts/render-keycloak-realm.sh
set -eu

cd "$(dirname "$0")/../.."
[ -f .env ] || { echo ".env not found - run: make env" >&2; exit 1; }
set -a
. ./.env
set +a

sed \
  -e "s/__VERISETTLE_BACKEND_CLIENT_SECRET__/${KEYCLOAK_BACKEND_CLIENT_SECRET}/g" \
  -e "s/__VERISETTLE_CONSOLE_CLIENT_SECRET__/${KEYCLOAK_CONSOLE_CLIENT_SECRET}/g" \
  -e "s/__AP_CLERK_PASSWORD__/${DEMO_AP_CLERK_PASSWORD}/g" \
  -e "s/__CONTROLLER_PASSWORD__/${DEMO_CONTROLLER_PASSWORD}/g" \
  -e "s/__CFO_PASSWORD__/${DEMO_CFO_PASSWORD}/g" \
  infra/keycloak/realm-verisettle.template.json > infra/keycloak/realm-verisettle.json

echo "rendered infra/keycloak/realm-verisettle.json"
