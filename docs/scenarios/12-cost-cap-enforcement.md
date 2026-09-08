# 12 — Cost-cap enforcement

**What this proves:** each AI agent can only use the models it's allowed to, and can only spend up to its daily budget.

## Steps

1. Try using a model the Extraction agent isn't scoped for:
   ```sh
   curl -X POST http://localhost:4000/chat/completions \
     -H "Authorization: Bearer $LITELLM_KEY_AGENT_EXTRACTION" -H "Content-Type: application/json" \
     -d '{"model":"custodian-reasoning","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
   ```

2. Lower its budget below what it's already spent, then try a call it's normally allowed to make:
   ```sh
   curl -X POST http://localhost:4000/key/update -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
     -d "{\"key\": \"$LITELLM_KEY_AGENT_EXTRACTION\", \"max_budget\": 0.001}"

   curl -X POST http://localhost:4000/chat/completions \
     -H "Authorization: Bearer $LITELLM_KEY_AGENT_EXTRACTION" -H "Content-Type: application/json" \
     -d '{"model":"custodian-routine","messages":[{"role":"user","content":"hi"}],"max_tokens":5}'

   # put the budget back
   curl -X POST http://localhost:4000/key/update -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
     -d "{\"key\": \"$LITELLM_KEY_AGENT_EXTRACTION\", \"max_budget\": 2.0}"
   ```

## What you'll see

1. `HTTP 403`, `"key_model_access_denied" ... this key can only access models=[...]`.
2. `HTTP 429`, `"budget_exceeded" ... Current cost: 0.26..., Max budget: 0.001`. After restoring the budget, a normal call works again.
