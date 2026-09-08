"""PII redaction for whatever lands in the durable audit trail. The
extraction LLM still sees the real OCR text (it needs the vendor
name/address), but nothing with an account number, SSN, or contact detail
should reach the audit log's WORM storage in the clear.
"""
import os

import requests

PRESIDIO_ANALYZER_URL = os.environ.get("PRESIDIO_ANALYZER_URL", "http://presidio-analyzer:3000")
PRESIDIO_ANONYMIZER_URL = os.environ.get("PRESIDIO_ANONYMIZER_URL", "http://presidio-anonymizer:3000")


def redact_for_audit(text: str) -> tuple[str, list[str]]:
    """Returns (redacted_text, entity_types_found). Fails open to the
    original text if Presidio is unreachable - a redaction outage must not
    silently drop every invoice."""
    try:
        analysis = requests.post(
            f"{PRESIDIO_ANALYZER_URL}/analyze",
            json={"text": text, "language": "en"},
            timeout=10,
        )
        analysis.raise_for_status()
        results = analysis.json()
        if not results:
            return text, []

        anonymized = requests.post(
            f"{PRESIDIO_ANONYMIZER_URL}/anonymize",
            json={"text": text, "analyzer_results": results},
            timeout=10,
        )
        anonymized.raise_for_status()
        entity_types = sorted({r["entity_type"] for r in results})
        return anonymized.json()["text"], entity_types
    except requests.RequestException:
        return text, []
