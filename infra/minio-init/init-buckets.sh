#!/bin/sh
# One-shot bucket setup, run by the minio-init service after minio is healthy.
# mc is now the only supported way to do bucket/Object Lock admin since
# MinIO stripped bucket/policy management out of the community web console
# (RELEASE.2025-05-24) - this script is the real, reproducible replacement
# for what used to be a console click-through.
set -eu

RETENTION_DAYS="${MINIO_AUDIT_RETENTION_DAYS:-1}"

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

# Audit log bucket: Object Lock can only be enabled at creation time.
if ! mc ls local/verisettle-audit-log >/dev/null 2>&1; then
  mc mb --with-lock local/verisettle-audit-log
fi
mc retention set --default COMPLIANCE "${RETENTION_DAYS}d" local/verisettle-audit-log

# Langfuse blob storage: regular bucket, no Object Lock.
if ! mc ls local/langfuse-blobs >/dev/null 2>&1; then
  mc mb local/langfuse-blobs
fi

# MLflow artifact store: regular bucket, no Object Lock.
if ! mc ls local/mlflow-artifacts >/dev/null 2>&1; then
  mc mb local/mlflow-artifacts
fi

echo "minio buckets ready: verisettle-audit-log (Object Lock, COMPLIANCE ${RETENTION_DAYS}d), langfuse-blobs, mlflow-artifacts"
