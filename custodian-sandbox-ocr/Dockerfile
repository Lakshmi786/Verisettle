# The image that reads an untrusted invoice image. sandbox-runner already
# runs this container with --network none, --read-only, non-root,
# --cap-drop=ALL; ocr.py adds a real, kernel-enforced Landlock ruleset
# (via agt-sandbox's NonoSandboxProvider) one layer deeper before running
# the actual OCR work in ocr_worker.py as a restricted subprocess.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# agent-governance-toolkit-cli is the current package (the older
# "agt-sandbox" name is a deprecated compatibility shim that just depends
# on this one) - still provides the same `agent_sandbox` module/import
# path. nono-py is the real Landlock/Seatbelt binding it uses underneath.
RUN pip install --no-cache-dir pytesseract==0.3.13 pillow==12.3.0 \
    agent-governance-toolkit-cli==5.0.0 nono-py==0.10.1

COPY ocr.py ocr_worker.py /app/

RUN useradd --create-home --uid 10001 sandbox
USER sandbox

ENTRYPOINT ["python3", "/app/ocr.py"]
