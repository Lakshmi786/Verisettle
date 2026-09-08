#!/bin/sh
# Run from the HOST (not inside a container - the spire-server image ships
# no shell, so this drives it via `docker exec`). Registers SPIFFE ID
# entries for the four agent workloads plus one verification workload.
# Real-agent selectors match a docker label each container will carry in
# Phase 5, so any container run with that label attests to exactly that
# identity - no valid label match, no SVID, no action.
set -eu

CONTAINER=custodian-spire-server
BIN=/opt/spire/bin/spire-server
SOCK=/run/spire/data/api.sock
TD=custodian.local
PARENT="spiffe://${TD}/agent/docker-agent"

register() {
  spiffe_id="$1"
  selector="$2"
  MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" "$BIN" entry create \
    -socketPath "$SOCK" \
    -spiffeID "spiffe://${TD}/${spiffe_id}" \
    -parentID "$PARENT" \
    -selector "$selector" \
    -x509SVIDTTL 3600 \
    || true
}

register "agent/extraction"        "docker:label:custodian.agent:extraction"
register "agent/risk-scoring"      "docker:label:custodian.agent:risk-scoring"
register "agent/approval"          "docker:label:custodian.agent:approval"
register "agent/payment-execution" "docker:label:custodian.agent:payment-execution"

# custodian-backend runs all 4 agents above as in-process function calls, not
# as 4 separate workloads - SPIRE attests one identity per process, so those
# 4 entries can never actually be issued to it. This 5th entry is the one
# that's real and actually used: the backend process's own identity, fetched
# at startup via the Workload API (app/identity.py) and required before it
# will serve any request.
register "service/custodian-backend" "docker:label:custodian.service:backend"

# Verification-only entry: matched by unix uid instead of a docker label, so
# Phase 1 can prove real SVID issuance without also having to solve
# docker.sock group permissions for the docker workload attestor (addressed
# in Phase 5 when the real agent containers are built).
register "test/verification" "unix:uid:0"

echo "SPIRE registration entries created for trust domain ${TD}:"
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" "$BIN" entry show -socketPath "$SOCK"
