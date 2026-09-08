# 06 — Policy change accepted

**What this proves:** the real policy rulebook (Cedar) passes a real validation check before it's trusted.

## Steps

**macOS/Linux:**
```sh
docker run --rm \
  -v "$(pwd)/policies:/policies:ro" \
  -v "$(pwd)/infra/scripts:/scripts:ro" \
  custodian-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```

**Windows (Git Bash):** identical, but prefix with `MSYS_NO_PATHCONV=1` —

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd)/policies:/policies:ro" \
  -v "$(pwd)/infra/scripts:/scripts:ro" \
  custodian-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```

This checks the real `policies/*.cedar` files: do they parse correctly, are any of them dangerously wide-open, and do they produce the right allow/deny answers for a small set of real test cases.

