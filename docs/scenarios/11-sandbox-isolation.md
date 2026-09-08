# 11 — Sandbox isolation

**What this proves:** the container that reads scanned invoice images has no internet access, no admin rights, and can't write outside its scratch space.

## Steps

```sh
# no network
docker run --rm --network none --read-only --tmpfs /tmp:size=16m \
  --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
  --entrypoint python3 verisettle-sandbox-ocr:latest -c "
import socket
try:
    socket.create_connection(('1.1.1.1', 80), timeout=3)
    print('NETWORK REACHABLE (unexpected)')
except OSError as e:
    print('NETWORK BLOCKED (expected):', e)
"

# not root
docker run --rm --network none --read-only --tmpfs /tmp:size=16m \
  --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
  --entrypoint id verisettle-sandbox-ocr:latest

# read-only filesystem
docker run --rm --network none --read-only --tmpfs /tmp:size=16m \
  --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
  --entrypoint sh verisettle-sandbox-ocr:latest -c "touch /app/test"
```

## What you'll see

- Network: `NETWORK BLOCKED (expected): [Errno 101] Network is unreachable`
- User: `uid=10001(sandbox) gid=10001(sandbox)` — never root (uid 0)
- Filesystem: `touch: cannot touch '/app/test': Read-only file system`

## A second, real layer: Landlock

Those three checks are Docker's own isolation. `verisettle-sandbox-ocr`'s real
entrypoint (`ocr.py`) adds one more, independent layer on top: a real,
kernel-enforced [Landlock](https://landlock.io) ruleset (via Microsoft's
open-source `agent-governance-toolkit` `NonoSandboxProvider`), applied
inside the container, restricting the actual OCR subprocess to only the
paths it's explicitly given - even paths Docker itself would otherwise
allow.

This launches the real OCR sandbox with everything locked down (no network, no root, no extra privileges) and tries to make it write a file to /tmp — a folder it's not supposed to be allowed to touch. It's testing whether the sandbox's Landlock protection actually blocks that write for real, or just claims to.

```sh
docker run --rm --network none --tmpfs /tmp:size=16m --tmpfs /input:size=16m --tmpfs /scratch:size=16m \
  --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
  --entrypoint python3 verisettle-sandbox-ocr:latest -c "
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
from agent_sandbox import NonoSandboxProvider, SandboxConfig
p = NonoSandboxProvider()
config = SandboxConfig(network_enabled=False, input_dir='/input', output_dir='/scratch')
handle = p.create_session('demo', config=config)
try:
    execution = p.execute_code('demo', handle.session_id, \"open('/tmp/pwned.txt', 'w').write('pwned')\")
    r = execution.result
    print('BLOCKED (expected)' if not r.success else 'NOT BLOCKED (unexpected)')
    print(r.stderr[:300])
finally:
    p.destroy_session('demo', handle.session_id)
"
```
`BLOCKED (expected)`, with a real `PermissionError: [Errno 13] Permission
denied: '/tmp/pwned.txt'` - Landlock refuses the write even though Docker's
own container settings would have allowed it, proving this is a real,
additional restriction, not just a restatement of what Docker already does.


>The reason: --tmpfs /tmp:size=16m mounts /tmp with the same permissions a normal Linux /tmp has — world-writable (mode 1777, meaning literally any user, root or not, can write files there)

> --read-only only locks down the container's own root filesystem (the OS files that came baked into the image).