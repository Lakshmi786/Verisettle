# syntax=docker/dockerfile:1
# Build context is the REPO ROOT, not this folder - the single uv workspace
# lock file lives there. Build via infra/compose or:
#   docker build -f services/sandbox-runner/Dockerfile .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Only the manifests land in this layer, so editing source never
# invalidates the dependency install. --frozen means the build fails rather
# than silently resolving something the lock file does not describe.
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY services/sandbox-runner/pyproject.toml services/sandbox-runner/
RUN uv sync --frozen --no-dev --package verisettle-sandbox-runner

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
COPY services/sandbox-runner/app ./app

# No USER directive on purpose: this service mounts the Docker socket to
# launch a fresh, locked-down sandbox container per OCR call.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
