# syntax=docker/dockerfile:1
# The image that reads an untrusted invoice image. sandbox-runner already
# runs this container with --network none, --read-only, non-root,
# --cap-drop=ALL; ocr.py adds a real, kernel-enforced Landlock ruleset
# (via agt-sandbox's NonoSandboxProvider) one layer deeper before running
# the actual OCR work in ocr_worker.py as a restricted subprocess.
#
# Build context is THIS folder, not the repo root: this image is
# deliberately outside the uv workspace and locks its own dependencies, so
# nothing another service pulls in can widen the dependency surface of the
# one process that touches untrusted input.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# agent-governance-toolkit-cli is the current package (the older
# "agt-sandbox" name is a deprecated compatibility shim that just depends
# on this one) - still provides the same `agent_sandbox` module/import
# path. nono-py is the real Landlock/Seatbelt binding it uses underneath.
# Both are pinned in this image's own pyproject.toml / uv.lock.
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY ocr.py ocr_worker.py /app/

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 sandbox
USER sandbox

ENTRYPOINT ["python3", "/app/ocr.py"]
