# syntax=docker/dockerfile:1
# Build context is the REPO ROOT, not this folder - the single uv workspace
# lock file lives there. Build via infra/compose or:
#   docker build -f services/data-loader/Dockerfile .
# python:3.14 breaks great_expectations' pydantic-v1 compat shim - pin 3.12.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Only the manifests land in this layer, so editing source never
# invalidates the dependency install. --frozen means the build fails rather
# than silently resolving something the lock file does not describe.
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY services/data-loader/pyproject.toml services/data-loader/
RUN uv sync --frozen --no-dev --package verisettle-data-loader

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
COPY services/data-loader/loader ./loader
COPY services/data-loader/main.py ./main.py

RUN useradd --create-home --uid 10001 loader && \
    mkdir -p /data/invoices && chown -R loader:loader /data /app
USER loader

ENTRYPOINT ["python", "main.py"]
