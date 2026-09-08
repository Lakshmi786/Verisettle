"""The only component with a bind-mounted docker.sock. Spins up a fresh
container per untrusted document parse: --rm, --network none, read-only
root, non-root, all capabilities dropped, hard resource/time limits.
verisettle-sandbox-ocr itself adds one more real layer inside that container
(a kernel-enforced Landlock ruleset via agt-sandbox's NonoSandboxProvider)
before it touches the actual image. Spawning a sandbox is itself authorized
via policy-service.

Uses named volumes rather than bind mounts for input/scratch: a bind mount
sourced from this container's own filesystem resolves against the real
host, not this container, in Docker-outside-of-Docker.
"""
import os
import time
import uuid

import docker
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="verisettle-sandbox-runner", version="1.0.0")
client = docker.from_env()

POLICY_SERVICE_URL = os.environ.get("POLICY_SERVICE_URL", "http://policy-service:8000")
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "verisettle-sandbox-ocr:latest")
INVOICE_IMAGES_VOLUME = os.environ.get("INVOICE_IMAGES_VOLUME", "verisettle_invoice-images")
HARD_TIMEOUT_SECONDS = 30


class OcrRequest(BaseModel):
    invoice_id: str
    image_path: str  # path as seen under this service's own /data/invoices mount
    requesting_agent: str = "extraction"


@app.get("/health")
def health():
    return {"status": "ok"}


def _authorize(requesting_agent: str, invoice_id: str):
    try:
        resp = requests.post(f"{POLICY_SERVICE_URL}/authorize", json={
            "principal": {"type": "Agent", "id": requesting_agent, "attrs": {"trustTier": "read-only"}},
            "action": "InvokeTool",
            "resource": {"type": "Tool", "id": invoice_id, "attrs": {"name": "sandbox-ocr"}},
            "context": {},
        }, timeout=10)
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        result = {"decision": "Deny", "error": str(e)}
    if result["decision"] != "Allow":
        raise HTTPException(status_code=403, detail=f"policy-service denied sandbox spawn: {result}")


@app.post("/ocr")
def run_ocr(req: OcrRequest):
    _authorize(req.requesting_agent, req.invoice_id)

    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=404, detail=f"no such image: {req.image_path}")
    relative_path = os.path.relpath(req.image_path, "/data/invoices")

    execution_id = str(uuid.uuid4())
    scratch_volume_name = f"verisettle-sandbox-scratch-{execution_id[:12]}"
    scratch_volume = client.volumes.create(name=scratch_volume_name)
    started_at = time.time()

    try:
        # A fresh volume is root-owned; the sandbox runs as uid 10001 with
        # no capabilities, so it can't chown its own scratch dir.
        client.containers.run(
            "alpine:3.22",
            command=["chown", "10001:10001", "/scratch"],
            volumes={scratch_volume_name: {"bind": "/scratch", "mode": "rw"}},
            remove=True,
            network_disabled=True,
        )

        container = client.containers.run(
            SANDBOX_IMAGE,
            name=f"verisettle-sandbox-{execution_id[:8]}",
            environment={"INPUT_PATH": f"/input/{relative_path}"},
            remove=True,
            detach=True,
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": "size=16m"},
            volumes={
                INVOICE_IMAGES_VOLUME: {"bind": "/input", "mode": "ro"},
                scratch_volume_name: {"bind": "/scratch", "mode": "rw"},
            },
            user="10001:10001",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            pids_limit=64,
            mem_limit="256m",
            nano_cpus=500_000_000,  # 0.5 CPU
        )
        try:
            exit_status = container.wait(timeout=HARD_TIMEOUT_SECONDS)
        except Exception:
            container.kill()
            raise HTTPException(status_code=504, detail="sandbox execution exceeded hard timeout, killed")

        success = exit_status.get("StatusCode", 1) == 0
        ocr_text = _read_from_volume(scratch_volume_name, "output.txt") if success else ""

        return {
            "execution_id": execution_id,
            "success": success,
            "ocr_text": ocr_text,
            "duration_seconds": round(time.time() - started_at, 3),
        }
    finally:
        try:
            scratch_volume.remove(force=True)
        except docker.errors.APIError:
            pass


def _read_from_volume(volume_name: str, filename: str) -> str:
    """Named volumes aren't directly readable from this container's
    filesystem either (same DooD constraint as above) - read the output
    back via a tiny throwaway reader container."""
    output = client.containers.run(
        "alpine:3.22",
        command=["cat", f"/scratch/{filename}"],
        volumes={volume_name: {"bind": "/scratch", "mode": "ro"}},
        remove=True,
        network_disabled=True,
    )
    return output.decode() if isinstance(output, bytes) else str(output)
