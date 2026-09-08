# python:3.14 breaks great_expectations' pydantic-v1 compat shim - pin 3.12.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY loader/ ./loader/
COPY main.py .

RUN useradd --create-home --uid 10001 loader && \
    mkdir -p /data/invoices && chown -R loader:loader /data /app
USER loader

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "main.py"]
