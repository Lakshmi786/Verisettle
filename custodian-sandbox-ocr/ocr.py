"""Entrypoint for the OCR sandbox container. Applies a real, kernel-enforced
Landlock ruleset (via Microsoft's open-source agt-sandbox NonoSandboxProvider
- https://github.com/microsoft/agent-governance-toolkit) around the actual
OCR work in ocr_worker.py, one layer deeper than the Docker-level isolation
sandbox-runner already applies (--network none, --read-only, non-root,
--cap-drop=ALL). Landlock needs no host-level setup (no custom Docker
runtime, no Docker Desktop config) - it's a plain Linux kernel feature
(mainline since 5.13) a process applies to itself before it execs the real
work, so this runs the same way on every machine with no manual step.

Fails loudly if Landlock isn't available on the host kernel, rather than
silently running ocr_worker.py unsandboxed - same "no silent fallback"
principle used everywhere else in this project (see e.g. the settlement
hold / kill-switch fail-open-but-loud comments in custodian-backend).
"""
import os
import sys
import warnings

# agent_sandbox's own __init__.py unconditionally raises this on import,
# regardless of which package provides it - it's warning about the old
# "agt-sandbox" PyPI distribution name, not the `agent_sandbox` module
# itself. We install the real, current package (agent-governance-toolkit-cli,
# not the deprecated agt-sandbox shim - see the Dockerfile), so this is
# stale noise in the library, not something to actually migrate away from.
warnings.filterwarnings("ignore", message="agt-sandbox is deprecated", category=DeprecationWarning)
from agent_sandbox import NonoSandboxProvider, SandboxConfig  # noqa: E402

SCRATCH = "/scratch"
INPUT_DIR = "/input"


def main():
    input_path = os.environ.get("INPUT_PATH")
    if not input_path:
        print("INPUT_PATH not set", file=sys.stderr)
        sys.exit(1)

    provider = NonoSandboxProvider()
    if not provider.is_available():
        print(
            "Landlock is not available on this kernel (needs Linux 5.13+) - "
            "refusing to run OCR unsandboxed rather than silently degrading.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = SandboxConfig(
        timeout_seconds=25,
        memory_mb=200,
        cpu_limit=0.5,
        network_enabled=False,
        read_only_fs=True,
        input_dir=INPUT_DIR,
        output_dir=SCRATCH,
        env_vars={"INPUT_PATH": input_path},
    )
    # Explicit session + execute_code(), not the bare provider.run() with a
    # file path to /app/ocr_worker.py, for two real reasons found by
    # reading nono_sandbox_provider/provider.py directly:
    #  1. provider.run()'s ephemeral one-shot path never creates its own
    #     scratch "output/" working directory before using it as cwd (only
    #     create_session() does) - a real bug in this library version.
    #  2. Landlock's ruleset only grants read access to input_dir,
    #     output_dir, and a fixed system-paths list - /app isn't in it, so
    #     a spawned `python3 /app/ocr_worker.py` gets a real Permission
    #     denied reading its own script (proving the ruleset is genuinely
    #     enforced). execute_code() sidesteps this by writing the script
    #     into the session's own auto-granted scripts/ directory instead.
    agent_id = "sandbox-ocr"
    handle = provider.create_session(agent_id, config=config)
    try:
        with open("/app/ocr_worker.py") as f:
            worker_source = f.read()
        execution = provider.execute_code(agent_id, handle.session_id, worker_source)
        result = execution.result
    finally:
        provider.destroy_session(agent_id, handle.session_id)

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    if result.killed:
        print(f"OCR worker killed by sandbox: {result.kill_reason}", file=sys.stderr)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
