import json
import os
import re

from datasets import load_dataset

from . import db

IMAGE_DIR = os.environ.get("INVOICE_IMAGE_DIR", "/data/invoices")

CORD_TRAIN_LIMIT = int(os.environ.get("CORD_TRAIN_LIMIT", "150"))
CORD_TEST_LIMIT = int(os.environ.get("CORD_TEST_LIMIT", "40"))
SROIE_TRAIN_LIMIT = int(os.environ.get("SROIE_TRAIN_LIMIT", "250"))
SROIE_TEST_LIMIT = int(os.environ.get("SROIE_TEST_LIMIT", "60"))

_MONEY_RE = re.compile(r"[^0-9.]")


def _to_amount(value):
    if value is None:
        return None
    cleaned = _MONEY_RE.sub("", str(value))
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _load_cord(split, limit, conn):
    ds = load_dataset("naver-clova-ix/cord-v2", split=split, streaming=True)
    count = 0
    for i, rec in enumerate(ds):
        if count >= limit:
            break
        try:
            gt = json.loads(rec["ground_truth"])
        except (KeyError, json.JSONDecodeError):
            continue
        parse = gt.get("gt_parse", {})
        total_block = parse.get("total", {})
        raw_total = total_block.get("total_price") or total_block.get("cashprice")
        normalized = {
            "vendor": None,
            "date": None,
            "address": None,
            "total": _to_amount(raw_total),
        }
        external_key = f"cord-{split}-{i}"
        image_path = os.path.join(IMAGE_DIR, "cord", split, f"{external_key}.png")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        rec["image"].save(image_path)
        db.upsert_invoice(conn, "cord", external_key, split, image_path, normalized, gt)
        count += 1
    return count


def _load_sroie(split, limit, conn):
    ds = load_dataset("jsdnrs/ICDAR2019-SROIE", split=split, streaming=True)
    count = 0
    for i, rec in enumerate(ds):
        if count >= limit:
            break
        entities = rec.get("entities") or {}
        normalized = {
            "vendor": entities.get("company"),
            "date": entities.get("date"),
            "address": entities.get("address"),
            "total": _to_amount(entities.get("total")),
        }
        # Keep the real OCR word tokens - the eval gate uses them as
        # extraction input without re-running OCR here.
        raw = {"entities": entities, "words": rec.get("words") or []}
        external_key = rec.get("key") or f"sroie-{split}-{i}"
        image_path = os.path.join(IMAGE_DIR, "sroie", split, f"{external_key}.png")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        rec["image"].save(image_path)
        db.upsert_invoice(conn, "sroie", external_key, split, image_path, normalized, raw)
        count += 1
    return count


def run():
    conn = db.backend_conn()
    db.ensure_backend_schema(conn)

    cord_train = _load_cord("train", CORD_TRAIN_LIMIT, conn)
    cord_test = _load_cord("test", CORD_TEST_LIMIT, conn)
    sroie_train = _load_sroie("train", SROIE_TRAIN_LIMIT, conn)
    sroie_test = _load_sroie("test", SROIE_TEST_LIMIT, conn)

    conn.close()
    print(f"CORD: {cord_train} train, {cord_test} test")
    print(f"SROIE: {sroie_train} train, {sroie_test} test")
    return {
        "cord_train": cord_train, "cord_test": cord_test,
        "sroie_train": sroie_train, "sroie_test": sroie_test,
    }


if __name__ == "__main__":
    run()
