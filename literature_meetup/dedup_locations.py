from __future__ import annotations

import json
from collections import defaultdict

HIERARCHY_FIELDS = ("country", "region", "city", "neighborhood", "street")


def _deepest_index(hierarchy: dict) -> int:
    deepest = -1
    for i, field in enumerate(HIERARCHY_FIELDS):
        if hierarchy.get(field) is not None:
            deepest = i
    return deepest


def _nests_inside(location_a: dict, location_b: dict) -> bool:
    """True if location_a nests inside location_b (b is the more specific one).

    Per Addendum 3 Step 2. Transit locations are never comparable for nesting,
    against hierarchy locations or against each other.
    """
    if location_a.get("location_type") == "transit" or location_b.get("location_type") == "transit":
        return False

    hierarchy_a = location_a.get("hierarchy") or {}
    hierarchy_b = location_b.get("hierarchy") or {}

    for field in HIERARCHY_FIELDS:
        value_a = hierarchy_a.get(field)
        if value_a is not None and hierarchy_b.get(field) != value_a:
            return False

    return _deepest_index(hierarchy_b) > _deepest_index(hierarchy_a)


def _time_compatible(time_a: dict, time_b: dict) -> bool:
    """Per Addendum 3 Step 3. Nulls never conflict; equal stated fields don't
    conflict; a precise date is compatible with an overlapping year range.
    """
    hierarchy_a = time_a.get("hierarchy") or {}
    hierarchy_b = time_b.get("hierarchy") or {}

    for field in ("year", "month", "day"):
        value_a, value_b = hierarchy_a.get(field), hierarchy_b.get(field)
        if value_a is not None and value_b is not None and value_a != value_b:
            return False

    def _range_conflicts_with_year(range_hierarchy: dict, year: int) -> bool:
        start, end = range_hierarchy.get("year_range_start"), range_hierarchy.get("year_range_end")
        if start is not None and year < start:
            return True
        if end is not None and year > end:
            return True
        return False

    a_has_range = hierarchy_a.get("year_range_start") is not None or hierarchy_a.get("year_range_end") is not None
    b_has_range = hierarchy_b.get("year_range_start") is not None or hierarchy_b.get("year_range_end") is not None

    if a_has_range and not b_has_range and hierarchy_b.get("year") is not None:
        if _range_conflicts_with_year(hierarchy_a, hierarchy_b["year"]):
            return False
    if b_has_range and not a_has_range and hierarchy_a.get("year") is not None:
        if _range_conflicts_with_year(hierarchy_b, hierarchy_a["year"]):
            return False

    return True


def _find_best_match(event: dict, character_events: list[dict]) -> dict | None:
    """Per Addendum 3 Step 4: across ALL of the character's other events (one
    pass, not chained pairwise merges), find the single most specific location
    that nests this event's location inside it with non-conflicting time.
    """
    candidates = [
        other["location"]
        for other in character_events
        if other is not event
        and _nests_inside(event["location"], other["location"])
        and _time_compatible(event["time"], other["time"])
    ]
    if not candidates:
        return None

    def _specificity(location: dict) -> tuple:
        hierarchy = location.get("hierarchy") or {}
        filled_count = sum(1 for field in HIERARCHY_FIELDS if hierarchy.get(field) is not None)
        # Deepest filled level alone can tie between two candidates that fill
        # the same maximum index but a different number of fields overall
        # (e.g. one has only `street`, another has `neighborhood` and
        # `street`) - field count breaks that tie in favor of the more
        # complete candidate.
        return (_deepest_index(hierarchy), filled_count)

    return max(candidates, key=_specificity)


def refine_event_locations(events: list[dict]) -> list[dict]:
    """Per Addendum 3 Steps 1-5: for each character, upgrade each event's
    location to the most specific time-compatible match among that same
    character's other events. Only the `location` sub-object is replaced;
    everything else about the event (event_id, time, confidence, etc.) is
    untouched. Mutates and returns `events` in place.
    """
    by_character = defaultdict(list)
    for event in events:
        by_character[event["character_id"]].append(event)

    for character_events in by_character.values():
        for event in character_events:
            match = _find_best_match(event, character_events)
            if match is not None:
                event["location"] = json.loads(json.dumps(match))

    return events


def _location_identity_key(location: dict) -> tuple:
    """Canonical identity for Step 6 dedup. Deliberately excludes `source`
    and `proximity` - those are per-event evidentiary metadata about how a
    place was mentioned, not part of the place's own identity, so two events
    referencing the same physical place with different source/proximity
    values must still collapse into one location record.
    """
    is_transit = location.get("location_type") == "transit"
    # The extraction prompt instructs the model to leave hierarchy empty for
    # transit locations, but this has been observed not holding in practice
    # (e.g. a transit event with hierarchy.city leaked in alongside the
    # transit details). Ignore hierarchy entirely for transit identity so two
    # otherwise-identical routes don't spuriously become separate records
    # over that noise - the DB schema doesn't allow transit rows to carry
    # hierarchy data anyway (see the fix in finalize_location_table below).
    hierarchy = {} if is_transit else (location.get("hierarchy") or {})
    hierarchy_key = tuple(hierarchy.get(field) for field in HIERARCHY_FIELDS)

    transit = location.get("transit") or {}
    transit_from = transit.get("from") or {}
    transit_to = transit.get("to") or {}
    transit_key = (
        transit_from.get("country"),
        transit_from.get("city"),
        transit_to.get("country"),
        transit_to.get("city"),
        transit.get("transport_mode"),
        transit.get("transport_detail"),
    )

    return (location.get("location_type"), hierarchy_key, transit_key)


def finalize_location_table(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Per Addendum 3 Step 6 (and Addendum 6's schema, which is authoritative
    on this point): collect the distinct remaining hierarchy/transit
    combinations across the whole book (all characters) and assign each a
    stable location_id. `proximity` and `source` live on the location record
    itself (matching the `locations` table's `proximity`/`hierarchy_source`
    columns), not per-event - whichever event first establishes a given
    location record's identity also sets its proximity/source. Each event's
    inline `location` object is replaced with a bare `location_id` reference.

    Returns (events, locations) where `locations` is the finalized table,
    ready for geocoding backfill and the eventual DB write.
    """
    locations_by_key: dict[tuple, dict] = {}

    for event in events:
        location = event["location"]
        key = _location_identity_key(location)

        if key not in locations_by_key:
            location_id = f"loc_{len(locations_by_key) + 1}"
            transit = location.get("transit") or {}
            transit_from = transit.get("from") or {}
            transit_to = transit.get("to") or {}
            has_transit_endpoint = any(
                (transit_from.get("country"), transit_from.get("city"), transit_to.get("country"), transit_to.get("city"))
            )
            # The DB's chk_transit_shape constraint requires a transit row to
            # name at least one from/to endpoint. The model has been observed
            # tagging an event as transit (e.g. "marching toward the
            # marshes") while naming no place at all on either end - demote
            # those to a non-transit, hierarchy-less location rather than
            # violate the constraint or fabricate a place that isn't in the
            # text.
            is_transit = location.get("location_type") == "transit" and has_transit_endpoint
            record = {
                "location_id": location_id,
                "location_type": "transit" if is_transit else (
                    "ambiguous" if location.get("location_type") == "transit" else location.get("location_type")
                ),
                # Force hierarchy empty for transit regardless of what the
                # model put there - the DB's chk_transit_shape constraint
                # requires transit rows to carry zero hierarchy data, and the
                # model has been observed leaking a hierarchy field (e.g.
                # city) onto a transit event despite the prompt instructing
                # otherwise.
                "hierarchy": {} if is_transit else dict(location.get("hierarchy") or {}),
                "proximity": location.get("proximity"),
                "source": location.get("source"),
            }
            if is_transit:
                record["transit"] = transit
            locations_by_key[key] = record

        record = locations_by_key[key]
        event["location_id"] = record["location_id"]
        del event["location"]

    return events, list(locations_by_key.values())


def dedupe_locations(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Runs the full Addendum 3 pipeline stage: per-character location
    refinement (Steps 1-5), then the whole-book finalized location table
    (Step 6). Pure deterministic code, no LLM involved.
    """
    events = refine_event_locations(events)
    return finalize_location_table(events)
