"""Standalone re-geocoding script: re-runs Nominatim hierarchy backfill on
all real-location rows in the DB whose geocode_status is not 'resolved'.

Run this:
- After a batch of new books (pipeline geocode_backfill only ran for those
  books' locations during processing)
- After the _dedupe_same_place ambiguity fix (locations processed before that
  fix may have been wrongly marked 'unresolved' for well-known cities like
  London or Paris)
- With --force to retry every real-location row regardless of current status

Throttled to ~1 req/sec (Nominatim usage policy). A cross-book cache avoids
duplicate lookups for the same (level, value) pair (e.g. many books with
city=London share one Nominatim call).

Usage:
    python scripts/regeocde_locations.py           # only unresolved rows
    python scripts/regeocde_locations.py --force   # all real-location rows
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

from literature_meetup.geocode_backfill import geocode_backfill

HIERARCHY_FIELDS = ("country", "region", "city", "neighborhood", "street")


def run(force: bool = False) -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            if force:
                cur.execute(
                    """
                    SELECT id, location_type, country, region, city, neighborhood, street
                    FROM locations
                    WHERE location_type = 'real'
                    ORDER BY id
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, location_type, country, region, city, neighborhood, street
                    FROM locations
                    WHERE location_type = 'real'
                      AND geocode_status != 'resolved'
                    ORDER BY id
                    """
                )
            rows = cur.fetchall()

        print(f"Found {len(rows)} location(s) to process.")

        locations = []
        id_map = {}
        for row in rows:
            loc_id, loc_type, country, region, city, neighborhood, street = row
            loc = {
                "location_type": loc_type,
                "hierarchy": {
                    "country": country,
                    "region": region,
                    "city": city,
                    "neighborhood": neighborhood,
                    "street": street,
                },
            }
            locations.append(loc)
            id_map[id(loc)] = loc_id

        cache: dict = {}
        geocode_backfill(locations, cache=cache)

        resolved = 0
        still_unresolved = 0
        skipped = 0

        with conn.cursor() as cur:
            for loc in locations:
                loc_id = id_map[id(loc)]
                status = loc.get("geocode_status", "unresolved")
                h = loc.get("hierarchy", {})

                if status == "resolved":
                    cur.execute(
                        """
                        UPDATE locations
                        SET country      = %s,
                            region       = %s,
                            city         = %s,
                            neighborhood = %s,
                            street       = %s,
                            geocode_status = 'resolved'
                        WHERE id = %s
                        """,
                        (
                            h.get("country"),
                            h.get("region"),
                            h.get("city"),
                            h.get("neighborhood"),
                            h.get("street"),
                            loc_id,
                        ),
                    )
                    resolved += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    cur.execute(
                        "UPDATE locations SET geocode_status = 'unresolved' WHERE id = %s",
                        (loc_id,),
                    )
                    still_unresolved += 1

        conn.commit()
        print(
            f"Done. resolved: {resolved} | still unresolved: {still_unresolved} | skipped: {skipped}"
        )
        print(f"Nominatim cache hits saved {len(cache)} unique lookup(s).")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="retry all real-location rows, not just unresolved ones",
    )
    args = parser.parse_args()
    run(force=args.force)
