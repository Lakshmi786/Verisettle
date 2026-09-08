# 02 — Identity: credential brokering

**What this proves:** `custodian-backend` never actually holds the ledger
password. Instead it holds a separate, narrow login to a vault (Infisical),
and fetches the real ledger password fresh, right before each use, then
throws it away.

## Before you start — load the real values into your shell

The commands below use real values from your `.env` (`PAYMENT_EXECUTION_CLIENT_ID`,
`PAYMENT_EXECUTION_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`). Load them all
into your current shell first, or every command below will silently run
with empty values and fail in a confusing way:

```sh
set -a; source .env; set +a
echo "clientId is set: ${PAYMENT_EXECUTION_CLIENT_ID:+yes}"
```

## Step 1 — prove the password genuinely isn't in the agent's environment

```sh
docker inspect custodian-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i ledger
```

This looks inside the *running* container's real environment, the same
place an attacker who broke in would look first.

**What you'll see:** at most `LEDGER_URL=http://custodian-ledger:8000` — an
address, not a password. `LEDGER_API_KEY` never appears here. That's the
core claim of this whole scenario, proven directly rather than just
asserted.

## Step 2 — fetch the password the same way the agent does

This is a two-part handshake, done by hand here so you can watch each part
separately instead of it happening invisibly inside the backend.

**2a — log in as the backend's own Payment-Execution identity:**
```sh
curl -s -X POST http://localhost:8443/api/v1/auth/universal-auth/login \
  -H "Content-Type: application/json" \
  -d "{\"clientId\":\"$PAYMENT_EXECUTION_CLIENT_ID\",\"clientSecret\":\"$PAYMENT_EXECUTION_CLIENT_SECRET\"}"
```
**What you'll see:** a real JSON response with an `accessToken` (a signed
login token, not the secret itself yet) and `"expiresIn":7200` — this login
token is only good for 2 hours, not forever. If you want to show 
what's actually inside it, paste the token into https://jwt.io (it's not
sensitive — no secret values are encoded in it, just metadata) and point
out `"identityName":"custodian-payment-execution"` — this token is tied to
*that one agent's identity specifically*, not a generic admin login.

**2b — use that token to actually ask the vault for the ledger password:**
```sh
TOKEN=$(curl -s -X POST http://localhost:8443/api/v1/auth/universal-auth/login \
  -H "Content-Type: application/json" \
  -d "{\"clientId\":\"$PAYMENT_EXECUTION_CLIENT_ID\",\"clientSecret\":\"$PAYMENT_EXECUTION_CLIENT_SECRET\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['accessToken'])")

curl -s "http://localhost:8443/api/v3/secrets/raw/LEDGER_API_KEY?workspaceId=$INFISICAL_PROJECT_ID&environment=dev&secretPath=/" \
  -H "Authorization: Bearer $TOKEN"
```
**What you'll see:** a real JSON response with `"secretKey":"LEDGER_API_KEY"`
and a real `"secretValue"` — the exact same password
`services/backend/app/ledger_client.py` fetches internally every time
Payment-Execution actually pays a vendor. You just retrieved it the same
way the agent does: prove identity first, then ask, every time, nothing
cached long-term.