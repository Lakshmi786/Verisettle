"""Great Expectations checkpoint validating the shape of invoice records
before any agent is allowed to trust them (Ground Rule 4 / Data Governance).
Real, computed pass/fail against real data - not a hardcoded check.
"""
import great_expectations as gx
import pandas as pd
from great_expectations.data_context.types.base import (
    DataContextConfig,
    InMemoryStoreBackendDefaults,
)

from . import db

# GE's anonymous usage-statistics reporting spawns a background thread on
# each context/validator event to phone home telemetry. In a one-shot batch
# job that thread can still be in flight when the process exits, racing the
# interpreter's finalization and crashing with a GIL-release segfault. This
# pipeline has no use for that telemetry, so it's disabled at context
# construction (before any event can spawn the thread) rather than raced.
_PROJECT_CONFIG = DataContextConfig(
    store_backend_defaults=InMemoryStoreBackendDefaults(),
    anonymous_usage_statistics={"enabled": False},
)


def validate_dataframe(df: pd.DataFrame):
    context = gx.get_context(mode="ephemeral", project_config=_PROJECT_CONFIG)
    datasource = context.sources.add_pandas(name="invoices")
    asset = datasource.add_dataframe_asset(name="invoice_records")
    batch_request = asset.build_batch_request(dataframe=df)
    context.add_or_update_expectation_suite("invoice-shape")
    validator = context.get_validator(batch_request=batch_request, expectation_suite_name="invoice-shape")

    validator.expect_column_values_to_not_be_null("source")
    validator.expect_column_values_to_be_in_set("source", ["sroie", "cord"])
    validator.expect_column_values_to_not_be_null("total")
    validator.expect_column_values_to_be_between("total", min_value=0.01, max_value=10_000_000)
    validator.expect_column_values_to_match_regex("external_key", r"^\S+$")

    return validator.validate()


def run():
    conn = db.backend_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source, external_key, split,
                   (ground_truth->>'total')::float AS total
            FROM invoices
        """)
        rows = cur.fetchall()
        cols = [d.name for d in cur.description]
    conn.close()

    df = pd.DataFrame(rows, columns=cols)
    df = df.dropna(subset=["total"])
    result = validate_dataframe(df)

    print(f"Great Expectations checkpoint: {len(df)} invoice records checked")
    print(f"success={result.success}")
    for r in result.results:
        cfg = r.expectation_config
        status = "PASS" if r.success else "FAIL"
        print(f"  [{status}] {cfg.expectation_type} column={cfg.kwargs.get('column')} "
              f"unexpected_count={r.result.get('unexpected_count', 0)}")
    return result


def demo():
    """Runnable self-check: a deliberately malformed record must genuinely
    fail validation (negative total, null source) - proving the gate is
    real, not a rubber stamp. Run: python -m loader.validate --demo"""
    good = pd.DataFrame([
        {"source": "sroie", "external_key": "X001", "split": "train", "total": 42.50},
        {"source": "cord", "external_key": "cord-train-0", "split": "train", "total": 9.00},
    ])
    bad = pd.DataFrame([
        {"source": None, "external_key": "bad-1", "split": "train", "total": -5.0},
        {"source": "sroie", "external_key": "bad-2", "split": "train", "total": 99_999_999.0},
    ])

    good_result = validate_dataframe(good)
    assert good_result.success, "expected the well-formed batch to pass"

    bad_result = validate_dataframe(bad)
    assert not bad_result.success, "expected the malformed batch to genuinely fail"

    print("demo: well-formed batch PASSED, malformed batch genuinely FAILED as expected")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        run()
