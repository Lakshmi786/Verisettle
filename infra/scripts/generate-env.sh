#!/bin/sh
# Writes .env from .env.example, replacing every __RAND_HEX_n__ placeholder
# with a fresh `openssl rand -hex n` value. Each placeholder names the exact
# call documented in "SECRETS GEN GUIDE.md", so the guide, the template and
# this script cannot drift apart.
#
# Refuses to overwrite an existing .env - regenerating secrets against
# already-initialised Postgres/MinIO/Keycloak volumes would lock you out of
# your own stack. To start over deliberately: make clean, then FORCE=1.
#
# Run from the repo root: sh infra/scripts/generate-env.sh
set -eu

cd "$(dirname "$0")/../.."

[ -f .env.example ] || { echo ".env.example not found - run this from the repo root" >&2; exit 1; }

if [ -f .env ] && [ "${FORCE:-0}" != "1" ]; then
  echo ".env already exists - refusing to overwrite it." >&2
  echo "Existing secrets are baked into your Docker volumes; replacing them" >&2
  echo "would break the running stack. To regenerate anyway: FORCE=1 sh $0" >&2
  exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

while IFS= read -r line || [ -n "$line" ]; do
  # Each placeholder is replaced one at a time so that two placeholders of
  # the same width never collapse to the same value.
  while printf '%s' "$line" | grep -q '__RAND_HEX_[0-9]\{1,\}__'; do
    n=$(printf '%s' "$line" | sed -n 's/.*__RAND_HEX_\([0-9]\{1,\}\)__.*/\1/p')
    v=$(openssl rand -hex "$n")
    line=$(printf '%s' "$line" | sed "s/__RAND_HEX_${n}__/${v}/")
  done
  printf '%s\n' "$line"
done < .env.example > "$TMP"

mv "$TMP" .env
trap - EXIT
chmod 600 .env

echo "wrote .env with freshly generated local secrets."
echo "Now open .env and set the two real provider keys:"
echo "  OPENAI_API_KEY=sk-..."
echo "  GROQ_API_KEY=gsk_..."
