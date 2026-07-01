from __future__ import annotations

import time

import requests

HIERARCHY_FIELDS = ("country", "region", "city", "neighborhood", "street")

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LiteratureMeetUp/0.1 (novel character location/time extraction tool)"
RATE_LIMIT_SECONDS = 1.0

# Only country/region/city have a reliable Nominatim structured-query
# parameter; neighborhood/street fall back to free-text search.
STRUCTURED_PARAM_BY_LEVEL = {"country": "country", "region": "state", "city": "city"}

# Nominatim's `addresstype` field per result, used for the type-consistency
# acceptance check (Addendum 4, criterion 2).
ACCEPTABLE_ADDRESSTYPES_BY_LEVEL = {
    "country": {"country"},
    "region": {"state", "region"},
    "city": {"city", "town", "village", "municipality", "county"},
}

# Address-block keys (from Nominatim's addressdetails=1 response) that can
# legitimately fill each of our hierarchy fields.
ADDRESS_FIELD_CANDIDATES = {
    "country": ("country",),
    "region": ("state", "region"),
    "city": ("city", "town", "village", "municipality"),
}

# How much clearer the top result's `importance` must be than the runner-up
# before we trust it as unambiguous (criterion 1). Conservative by design.
IMPORTANCE_MARGIN = 0.05


def _deepest_filled_level(hierarchy: dict) -> str | None:
    deepest = None
    for field in HIERARCHY_FIELDS:
        if hierarchy.get(field) is not None:
            deepest = field
    return deepest


def _query_nominatim(level: str, value: str) -> list[dict]:
    params = {"format": "json", "addressdetails": 1, "limit": 5}
    structured_param = STRUCTURED_PARAM_BY_LEVEL.get(level)
    if structured_param:
        params[structured_param] = value
    else:
        params["q"] = value

    response = requests.get(
        NOMINATIM_SEARCH_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _dedupe_same_place(results: list[dict]) -> list[dict]:
    """Nominatim can return one real place as several separate OSM boundary
    records with identical importance - these aren't genuinely ambiguous
    candidates, just multiple representations of the same place.

    Two passes:
    1. Exact display_name dedup (handles Paris as 'city' and 'suburb').
    2. address.city + address.country dedup (handles a city appearing as both
       its administrative boundary and a postal-code district, e.g. Valladolid
       returning with and without '47003' in the display_name)."""
    seen_name: set = set()
    deduped = []
    for result in results:
        name = result.get("display_name")
        if name in seen_name:
            continue
        seen_name.add(name)
        deduped.append(result)

    seen_place: set = set()
    collapsed = []
    for result in deduped:
        addr = result.get("address") or {}
        city = addr.get("city") or addr.get("town") or addr.get("village")
        country = addr.get("country")
        if city and country:
            key = (city, country)
            if key in seen_place:
                continue
            seen_place.add(key)
        collapsed.append(result)
    return collapsed


def _accept_result(results: list[dict], level: str) -> dict | None:
    """Addendum 4 acceptance criteria 1 & 2. Returns the usable top result,
    or None if the match is ambiguous or type-inconsistent.
    """
    if not results:
        return None

    results = _dedupe_same_place(results)

    if len(results) > 1:
        top_importance = results[0].get("importance", 0.0)
        next_importance = results[1].get("importance", 0.0)
        if top_importance - next_importance < IMPORTANCE_MARGIN:
            return None

    top = results[0]
    acceptable_types = ACCEPTABLE_ADDRESSTYPES_BY_LEVEL.get(level)
    if acceptable_types is not None and top.get("addresstype") not in acceptable_types:
        return None

    return top


def _backfill_fields(result: dict, deepest_index: int) -> dict:
    """Addendum 4 acceptance criterion 3: only fill levels broader than
    (smaller index than) the deepest level the text already gave us.
    """
    address = result.get("address") or {}
    fills = {}
    for i, field in enumerate(HIERARCHY_FIELDS):
        if i >= deepest_index:
            continue
        for candidate_key in ADDRESS_FIELD_CANDIDATES.get(field, ()):
            value = address.get(candidate_key)
            if value:
                fills[field] = value
                break
    return fills


def geocode_backfill(locations: list[dict], cache: dict | None = None) -> list[dict]:
    """Per Addendum 4: backfills missing hierarchy levels on real-type,
    finalized (deduped) locations via OpenStreetMap Nominatim. Sequential and
    throttled to Nominatim's ~1 req/sec usage policy - never parallelized.
    Conservative by design: any ambiguity or type mismatch leaves the
    location exactly as extracted.

    Mutates and returns `locations` in place, adding a `geocode_status`
    field ("resolved" | "unresolved" | "skipped") to every entry.

    `cache` (a dict, created fresh per call by default) avoids re-querying
    Nominatim for the same (level, value) lookup more than once in a run.
    """
    if cache is None:
        cache = {}

    for location in locations:
        if location.get("location_type") != "real":
            location["geocode_status"] = "skipped"
            continue

        hierarchy = location.get("hierarchy") or {}
        deepest_field = _deepest_filled_level(hierarchy)
        if deepest_field is None:
            location["geocode_status"] = "skipped"
            continue

        value = hierarchy[deepest_field]
        cache_key = (deepest_field, value)

        if cache_key in cache:
            results = cache[cache_key]
        else:
            try:
                results = _query_nominatim(deepest_field, value)
            except requests.RequestException as exc:
                print(f"geocode lookup failed for {deepest_field}={value!r}: {exc}")
                location["geocode_status"] = "unresolved"
                continue
            finally:
                time.sleep(RATE_LIMIT_SECONDS)
            cache[cache_key] = results

        accepted = _accept_result(results, deepest_field)
        if accepted is None:
            location["geocode_status"] = "unresolved"
            continue

        fills = _backfill_fields(accepted, HIERARCHY_FIELDS.index(deepest_field))
        if not fills:
            location["geocode_status"] = "unresolved"
            continue

        hierarchy.update(fills)
        location["hierarchy"] = hierarchy
        location["geocode_status"] = "resolved"

    return locations
