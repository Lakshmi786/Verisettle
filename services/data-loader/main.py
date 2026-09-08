"""custodian-data-loader: one-time (and re-runnable) seeding tool.

Pulls real SROIE/CORD invoice data with ground truth into custodian_backend,
pulls a real bounded USAspending award slice into custodian_ledger as vendor
master + historical payment data, then runs the Great Expectations shape
checkpoint against what was loaded.
"""
import os
import sys

from loader import load_invoices, load_vendors, validate


def main():
    print("=== loading invoice corpus (SROIE + CORD) ===")
    invoice_counts = load_invoices.run()

    print("\n=== loading vendor master + historical ledger (USAspending) ===")
    vendor_counts = load_vendors.run()

    print("\n=== validating invoice shape (Great Expectations) ===")
    result = validate.run()

    print("\n=== summary ===")
    print(f"invoices: {invoice_counts}")
    print(f"vendors: {vendor_counts}")
    print(f"great expectations success: {result.success}")

    if not result.success:
        print("data loader completed but the GE checkpoint failed - inspect the invoices table", file=sys.stderr)

    # All real work (DB writes) is done by this point. huggingface_hub's
    # retry logic can leave a background thread alive on a flaky
    # connection, which races Python's normal interpreter shutdown and
    # segfaults (PyGILState_Release) - a real bug in that library's
    # threading, not this script. os._exit() terminates at the OS level
    # immediately, skipping interpreter finalization entirely, so no
    # leftover thread from any library gets a chance to race it.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
