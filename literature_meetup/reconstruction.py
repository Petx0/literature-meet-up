import json

from literature_meetup.model_config import RECONSTRUCTION_MODEL as MODEL
from literature_meetup.reconstruction_prompt import RECONSTRUCTION_SYSTEM_PROMPT
from literature_meetup.reconstruction_schema import ASSIGN_CHRONOLOGICAL_ORDER_TOOL
from literature_meetup.usage_tracker import record as record_usage

DATE_FIELDS = ("year", "month", "day", "year_range_start", "year_range_end")


def _has_date_info(time: dict) -> bool:
    hierarchy = time.get("hierarchy") or {}
    return any(hierarchy.get(field) is not None for field in DATE_FIELDS)


def reconstruct_chronology(client, events: list[dict]) -> list[dict]:
    """Runs the story-chronological-order reconstruction step once over the
    whole book, per Addendum 1: events with at least partial date information
    are sent in a single call so the model can resolve cross-chapter and
    flashback ordering with the full picture. Events with no date information
    anywhere are left out of the call and keep story_chronological_order=null.

    Mutates and returns `events` in place: merges story_chronological_order
    and a new `ordering_confidence` field into the dated subset.
    """
    dated_events = [event for event in events if _has_date_info(event["time"])]
    if not dated_events:
        return events

    payload = [
        {
            "event_id": event["event_id"],
            "chapter": event["chapter"],
            "narration_order": event["sequence"]["narration_order"],
            "temporal_relation": event["temporal_relation"],
            "time": event["time"],
        }
        for event in dated_events
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=RECONSTRUCTION_SYSTEM_PROMPT,
        tools=[ASSIGN_CHRONOLOGICAL_ORDER_TOOL],
        tool_choice={"type": "tool", "name": "assign_chronological_order"},
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
    )

    record_usage(MODEL, response.usage)
    tool_use = next(block for block in response.content if block.type == "tool_use")
    assignments_by_id = {entry["event_id"]: entry for entry in tool_use.input["ordered_events"]}

    for event in dated_events:
        assignment = assignments_by_id.get(event["event_id"])
        if assignment is None:
            continue
        event["sequence"]["story_chronological_order"] = assignment["story_chronological_order"]
        event["ordering_confidence"] = assignment["ordering_confidence"]

    return events
