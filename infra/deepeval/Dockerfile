# syntax=docker/dockerfile:1
# One-shot prompt promotion gate (README step 4), not a long-running
# service. Build context is THIS folder: deepeval pins click<8.4.0 while
# huggingface-hub (used by the data loader) requires click>=8.4.0, so this
# job genuinely cannot share the workspace resolution and locks its own.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY prompts/ ./prompts/
COPY eval_gate.py .

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "eval_gate.py"]
