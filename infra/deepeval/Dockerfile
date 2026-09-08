FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prompts/ ./prompts/
COPY eval_gate.py .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "eval_gate.py"]
