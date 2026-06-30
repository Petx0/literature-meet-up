"""One-off/repeatable script: normalizes locations.country to a canonical
English name (see literature_meetup/location_normalization.py for the why).

Cheap - pure in-memory dict lookups, no network/LLM calls - safe to run
after every batch of new books, or any time COUNTRY_NAME_ALIASES gains new
entries.

Usage:
    python scripts/normalize_locations.py            # only rows not yet normalized
    python scripts/normalize_locations.py --force    # every real-location row
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key and not line.startswith("#"):
            os.environ[key] = value

import psycopg2

from literature_meetup.location_normalization import run_normalization

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="reprocess every real-location row, not just unnormalized ones")
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        result = run_normalization(conn, force=args.force)
    finally:
        conn.close()

    print(f"Scanned {result['scanned']} location(s), changed {result['changed']}.")
