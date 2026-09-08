# 15 — Audit log tamper resistance

**What this proves:** the audit log detects it if someone tries to secretly edit or delete a past entry.

## Steps

1. Check the chain is currently valid:
   ```sh
   curl http://localhost:8094/verify
   ```

2. Try to tamper with a real locked entry directly in storage. This uses
   `mc`, the MinIO client CLI — if you don't have it installed locally,
   every command below can run the same way through a throwaway container
   instead (note the endpoint changes from `localhost:9000` to
   `minio:9000`, since the container reaches MinIO over the real Docker
   network rather than your host's published port):

   **If you have `mc` installed:**
   ```sh
   mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
   KEY=$(mc ls local/verisettle-audit-log | head -1 | awk '{print $NF}')
   mc retention info "local/verisettle-audit-log/$KEY"
   echo "TAMPERED" | mc pipe "local/verisettle-audit-log/$KEY"
   mc rm "local/verisettle-audit-log/$KEY"
   ```

   **If you don't have `mc` installed** (no separate install needed):
   ```sh
   set -a; source .env; set +a
   KEY=$(docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc ls local/verisettle-audit-log" | head -1 | awk '{print $NF}')
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc retention info 'local/verisettle-audit-log/$KEY'"
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; echo TAMPERED | mc pipe 'local/verisettle-audit-log/$KEY'"
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc rm 'local/verisettle-audit-log/$KEY'"
   ```
   Either way, this grabs the oldest real audit-log entry from MinIO,
   confirms it's really locked, then tries to overwrite it and delete it.

3. Check the chain again:
   ```sh
   curl http://localhost:8094/verify
   ```

## What you'll see

Step 1: `{"valid": true, ...}`.

Step 2: the retention check shows it's really locked (`Mode: COMPLIANCE`) — but the overwrite and delete *commands themselves* still complete. That's expected: the storage system prevents the original file from ever being erased, but it doesn't stop someone from stacking a new version on top of it.

Step 3: `{"valid": false, "breaks": [{"id": 1, "reason": "MinIO object is gone (delete marker or removed) ..."}]}` — the audit log's own check catches exactly this, because it double-checks the real file content matches what was originally written, not just that a file with that name still exists.

## Can you actually recover it?

Yes — but only by restoring the *exact original bytes*, not by just undoing
your last action. This was tested live, in order:

1. **List every version of the tampered key:**
   ```sh
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc ls --versions 'local/verisettle-audit-log/$KEY'"
   ```
   You'll see three real versions stacked on the same key: `v1` (the
   original, locked, still fully intact), `v2` (the `TAMPERED` content from
   step 2's overwrite), and `v3` (the delete marker from step 2's `mc rm`).

2. The first command found and saved the delete marker's ID number; the second command deleted that specific marker, revealing the tampered version underneath it (not the real original).

   ```sh
   V3=$(docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc ls --versions 'local/verisettle-audit-log/$KEY'" | grep " v3 " | awk '{print $6}')
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc rm --version-id=$V3 'local/verisettle-audit-log/$KEY'"
   curl http://localhost:8094/verify
   ```
   Real result: still `"valid": false` — just with a *different* reason
   now (`"MinIO object content no longer matches this entry"`). Removing
   the delete marker only un-hid `v2`, the tampered content — not the real
   original underneath it.

3. **Full recovery — fetch `v1`'s real bytes and write them back as a
   brand-new top version:**
   ```sh
   V1=$(docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1; mc ls --versions 'local/verisettle-audit-log/$KEY'" | grep " v1 " | awk '{print $6}')
   docker run --rm --network verisettle-net --entrypoint sh minio/mc:latest -c "
     mc alias set local http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1
     mc cat --version-id=$V1 'local/verisettle-audit-log/$KEY' | mc pipe 'local/verisettle-audit-log/$KEY'
   "
   curl http://localhost:8094/verify
   ```
   Real result this time: `{"valid": true, "breaks": []}` — genuinely
   recovered, because you can't edit `v1` in place (it's locked), but you
   *can* always add a new version on top with the correct content.

4. **But check `/entries` — the recovery doesn't erase that it happened:**
   ```sh
   curl "http://localhost:8094/entries?limit=5"
   ```
   If the continuous watchdog (see scenario 24) had a chance to run while
   the entry was broken (its check runs automatically every
   `VERIFY_INTERVAL_SECONDS`, ~30s by default), you'll find a permanent
   `audit_log_tamper_detected` entry from while it was broken, and an
   `audit_log_tamper_resolved` entry from the moment you fixed it — both
   still sitting in the chain forever, even though `/verify` now says
   everything is fine. Recovering the *data* is possible. Recovering the
   *fact that it was ever caught* is not, by design.
