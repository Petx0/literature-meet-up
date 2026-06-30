"""Live, request-time geocoding for the web app's map feature.

Separate from geocode_backfill.py on purpose: that module is pipeline batch
code (Addendum 4) that mutates location dicts in place and runs once per
book during processing. This module instead serves webapp/main.py's
/api/encounter endpoint - a different caller, different cache lifetime
(process-lifetime, not per-book), and different concurrency concern (many
overlapping HTTP requests sharing one Nominatim rate-limit budget, not a
single sequential offline script).
"""
from __future__ import annotations

import threading
import time

import requests

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LiteratureMeetUp/0.1 (novel character location/time extraction tool)"
RATE_LIMIT_SECONDS = 1.0

STRUCTURED_PARAM_BY_LEVEL = {"country": "country", "region": "state", "city": "city"}
ACCEPTABLE_ADDRESSTYPES_BY_LEVEL = {
    "country": {"country"},
    "region": {"state", "region"},
    "city": {"city", "town", "village", "municipality", "county"},
}
IMPORTANCE_MARGIN = 0.05

_cache: dict[tuple[str, str], tuple[float, float] | None] = {}
_rate_limit_lock = threading.Lock()
_last_call_time = 0.0


def _throttled_get(params: dict) -> list[dict]:
    global _last_call_time
    with _rate_limit_lock:
        wait = RATE_LIMIT_SECONDS - (time.monotonic() - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        _last_call_time = time.monotonic()
    response.raise_for_status()
    return response.json()


def _accept_result(results: list[dict], level: str) -> dict | None:
    if not results:
        return None
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


def geocode_one(country: str | None, region: str | None, city: str | None) -> tuple[float, float] | None:
    """Returns (lat, lon) for the deepest non-null of city > region > country,
    or None if all three are null or the lookup fails/is ambiguous. Never
    raises - geocoding is best-effort decoration for the map, not something
    that should ever break /api/encounter.
    """
    if city:
        level, value = "city", city
    elif region:
        level, value = "region", region
    elif country:
        level, value = "country", country
    else:
        return None

    cache_key = (level, value)
    if cache_key in _cache:
        return _cache[cache_key]

    params = {"format": "json", "addressdetails": 1, "limit": 5}
    structured_param = STRUCTURED_PARAM_BY_LEVEL.get(level)
    if structured_param:
        params[structured_param] = value
    else:
        params["q"] = value

    try:
        results = _throttled_get(params)
    except requests.RequestException as exc:
        print(f"live geocode lookup failed for {level}={value!r}: {exc}")
        return None

    accepted = _accept_result(results, level)
    if accepted is None:
        _cache[cache_key] = None
        return None

    try:
        coords = (float(accepted["lat"]), float(accepted["lon"]))
    except (KeyError, ValueError, TypeError):
        coords = None

    _cache[cache_key] = coords
    return coords
