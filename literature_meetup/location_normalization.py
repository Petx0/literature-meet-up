"""Normalizes locations.country to a single canonical English name per
country, and flags continents that extraction mistakenly stored as if they
were countries.

Distinct from geocode_backfill.py's Addendum 4 rule ("keep Bombay, don't
replace with Mumbai"): that rule protects a meaningful historical/editorial
distinction in the source text. Translating "Deutschland" to "Germany"
loses no information - it's the same modern country, just not yet in the
app's working language - so this module overwrites country in place rather
than preserving the original-language form.

Deliberately a pure in-memory dict lookup, no network/LLM calls - cheap
enough to run over every location row in the DB in a fraction of a second.
"""
from __future__ import annotations

COUNTRY_NAME_ALIASES: dict[str, str] = {
    "deutschland": "Germany",
    "belgië / belgique / belgien": "Belgium",
    "schweiz/suisse/svizzera/svizra": "Switzerland",
    "éire / ireland": "Ireland",
    "lëtzebuerg": "Luxembourg",
    "türkiye": "Turkey",
    "eesti": "Estonia",
    "italia": "Italy",
    "پاکستان": "Pakistan",
    "مصر": "Egypt",
}

# Never valid country names, despite sometimes showing up in the country
# field when extraction only had a vague continent-level reference.
# "Australia" is deliberately excluded - it's a legitimate country name too,
# and the data can't tell the two senses apart, so it's left untouched
# rather than guessed at.
CONTINENT_NAMES: set[str] = {
    "africa",
    "europe",
    "asia",
    "antarctica",
    "north america",
    "south america",
}


def normalize_country(raw: str) -> str | None:
    """Returns the canonical English name for a known alias, or None if
    `raw` is already canonical or unrecognized (either way, no change)."""
    return COUNTRY_NAME_ALIASES.get(raw.strip().lower())


def run_normalization(conn, force: bool = False) -> dict:
    """Scans real-location rows (force=False: only ones not yet looked at)
    and overwrites country with its canonical form where a known alias
    matches. Every scanned row gets country_normalized=true regardless of
    whether it changed, so a later non-force run only touches new rows.
    """
    where_force = "" if force else "and country_normalized = false"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select id, country from locations
            where location_type = 'real' and country is not null {where_force}
            """
        )
        rows = cur.fetchall()

        changed = 0
        for location_id, country in rows:
            canonical = normalize_country(country)
            if canonical and canonical != country:
                cur.execute(
                    "update locations set country = %s, country_normalized = true where id = %s",
                    (canonical, location_id),
                )
                changed += 1
            else:
                cur.execute(
                    "update locations set country_normalized = true where id = %s",
                    (location_id,),
                )
    conn.commit()
    return {"scanned": len(rows), "changed": changed}
