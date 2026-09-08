#!/bin/sh
# Generates a fresh SPIRE agent join token and writes it into .env.
#
# Join-token node attestation is single-use by design: once spire-agent
# successfully attests, the token is consumed. If the agent ever loses its
# persisted SVID (a fresh spire-agent-data volume, or an SVID that expired
# past its renewal window) it needs a new token to re-attest - run this,
# then recreate the agent: sh infra/scripts/compose.sh up -d --force-recreate spire-agent
set -eu
cd "$(dirname "$0")/../.."

TOKEN=$(MSYS_NO_PATHCONV=1 docker exec custodian-spire-server \
  /opt/spire/bin/spire-server token generate \
  -socketPath /run/spire/data/api.sock \
  -spiffeID spiffe://custodian.local/agent/docker-agent \
  | sed -n 's/^Token: //p')

if [ -z "$TOKEN" ]; then
  echo "failed to generate a join token - is custodian-spire-server up?" >&2
  exit 1
fi

sed -i "s/^SPIRE_AGENT_JOIN_TOKEN=.*/SPIRE_AGENT_JOIN_TOKEN=${TOKEN}/" .env
echo "new join token written to .env: ${TOKEN}"
echo "now run: sh infra/scripts/compose.sh up -d --force-recreate spire-agent"
