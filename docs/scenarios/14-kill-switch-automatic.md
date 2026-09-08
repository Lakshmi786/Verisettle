# 14 — Kill switch: automatic triggers

**What this proves:** the kill switch also trips itself, with no human involved, when something looks wrong.

## Trigger A — a vendor that should never be touched

```sh
curl -X POST http://localhost:8091/authorize -H "Content-Type: application/json" -d '{
  "principal": {"type":"Agent","id":"payment-execution","attrs":{"trustTier":"write-ledger"}},
  "action": "CreateLedgerEntry",
  "resource": {"type":"Payment","id":"canary-test-1","attrs":{"amount":10,"vendorFirstSeen":true,"vendor":"CANARY-DO-NOT-USE","approvalCount":0}},
  "context": {}
}'
sleep 15
curl http://localhost:8095/status
```
`CANARY-DO-NOT-USE` is a trap vendor name no real invoice should ever contain. Touching it trips the switch fleet-wide, automatically, within about 10-15 seconds.

## Trigger B — one agent getting denied over and over

```sh
for i in 1 2 3 4 5; do
curl -X POST http://localhost:8091/authorize -H "Content-Type: application/json" -d '{
  "principal": {"type":"Agent","id":"denial-test-agent","attrs":{"trustTier":"read-and-flag"}},
  "action": "CreateLedgerEntry",
  "resource": {"type":"Payment","id":"denial-'"$i"'","attrs":{"amount":999999,"vendorFirstSeen":true,"vendor":"unknown-shell-co","approvalCount":0}},
  "context": {}
}'
done
curl http://localhost:8095/status
```
5 denials in a row for the same agent → that one agent gets automatically paused.

## What you'll see

Trigger A: `"global_stop": true` after the wait.
Trigger B: `"paused_agents": ["denial-test-agent"]`.

Reset afterward — **each trigger needs its own reset call, matching its
own `scope`/`target`; resetting `global` does not clear a paused agent, and
vice versa**:
```sh
curl -X POST http://localhost:8095/kill-switch/reset -H "Content-Type: application/json" -d '{"scope":"global","target":"*","reset_by":"cleanup"}'
curl -X POST http://localhost:8095/kill-switch/reset -H "Content-Type: application/json" -d '{"scope":"agent","target":"denial-test-agent","reset_by":"cleanup"}'
```
Confirm both are clear:
```sh
curl http://localhost:8095/status
```
Should show `"global_stop":false` and `"paused_agents":[]`.

**If `paused_agents` keeps showing `denial-test-agent` again right after you
reset it (Trigger B specifically):** this isn't the reset command failing —
`_check_repeated_denials()` re-scans every `WATCHDOG_INTERVAL_SECONDS`
(10s by default) and looks back over a **rolling 5-minute window**
(`DENIAL_WINDOW_MINUTES`). If the real denial rows from your test are still
inside that trailing 5 minutes, the very next watchdog tick will just see
"3+ denials in the last 5 minutes" again and re-pause it immediately,
undoing your reset within seconds. The fix isn't to keep re-running reset —
it's to wait until **5 minutes have passed since the *last denial call*
you made** (not 5 minutes since you reset). Once that window is genuinely
quiet, one reset will hold permanently. Resetting early isn't wrong, it's
just pointless until the underlying trigger condition itself has gone
quiet.

>A third real trigger exists (missed heartbeat — an agent going silent mid-task) but is harder to demo with a single command since it needs an agent to actually stop responding.
