from __future__ import annotations

LOCATION_HIERARCHY_FIELDS = ("country", "region", "city", "neighborhood", "street")
YEAR_FIELDS = ("year", "year_range_start", "year_range_end")
ESTIMATE_USABLE_CONFIDENCES = ("medium", "high")


def _is_populated(endpoint: dict | None) -> bool:
    return bool(endpoint) and any(value is not None for value in endpoint.values())


def _has_usable_location(location: dict) -> bool:
    hierarchy = location.get("hierarchy") or {}
    if any(hierarchy.get(field) is not None for field in LOCATION_HIERARCHY_FIELDS):
        return True

    if location.get("location_type") == "transit":
        transit = location.get("transit") or {}
        return _is_populated(transit.get("from")) or _is_populated(transit.get("to"))

    return False


def _has_usable_date(time: dict) -> bool:
    """A date is only usable for this database if it has a year - month or
    day alone, with no year, is too ambiguous to be useful (it could belong
    to any year in the story) and is treated as not having a usable date at
    all.
    """
    hierarchy = time.get("hierarchy") or {}
    return any(hierarchy.get(field) is not None for field in YEAR_FIELDS)


def _apply_book_estimate(event: dict, estimated_setting: dict) -> None:
    # Replace the hierarchy wholesale, not just set the range fields - an
    # event reaching this point had no usable year, but may still have had a
    # dangling month/day (the exact reason it failed _has_usable_date). Once
    # we're substituting a book-wide era guess, that leftover month/day must
    # not survive alongside it - it would misrepresent a rough era estimate
    # as a precise date.
    event["time"]["hierarchy"] = {
        "year": None,
        "month": None,
        "day": None,
        "year_range_start": estimated_setting.get("year_range_start"),
        "year_range_end": estimated_setting.get("year_range_end"),
    }
    event["time"]["precision"] = "year_range"
    event["time"]["source"] = "book_estimated"


def filter_complete_events(events: list[dict], estimated_setting: dict | None = None) -> list[dict]:
    """Pure algorithmic filter, no LLM involved: drops (hard delete, no log)
    any event missing a usable location, per Addendum 1. Per Addendum 5, an
    event with a usable location but NO usable date is no longer dropped
    outright - it survives, backfilled with the book-wide `estimated_setting`
    range and `time.source: "book_estimated"`, but only when
    `estimated_setting["confidence"]` is `"medium"` or `"high"`. A low- (or
    no-)confidence estimate must never rescue an event; that event is still
    dropped, exactly as in Addendum 1.

    `confidence` (event-level) and `ordering_confidence` are deliberately not
    part of this filter - those are separate certainty concerns, not
    completeness. `estimated_setting` is the book-level dict produced by
    literature_meetup.setting_estimation.estimate_book_setting, or None if
    that step was skipped or produced nothing.
    """
    estimate_is_usable = (
        estimated_setting is not None and estimated_setting.get("confidence") in ESTIMATE_USABLE_CONFIDENCES
    )

    surviving = []
    for event in events:
        if not _has_usable_location(event["location"]):
            continue

        if _has_usable_date(event["time"]):
            surviving.append(event)
            continue

        if estimate_is_usable:
            _apply_book_estimate(event, estimated_setting)
            surviving.append(event)

    return surviving
