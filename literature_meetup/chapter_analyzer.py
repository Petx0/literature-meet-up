import json

from literature_meetup.extraction_prompt import SYSTEM_PROMPT
from literature_meetup.extraction_schema import RECORD_CHAPTER_EVENTS_TOOL
from literature_meetup.model_config import EXTRACTION_MODEL as MODEL
from literature_meetup.usage_tracker import record as record_usage


def _story_state_for_prompt(story_state: dict) -> dict:
    """Entity resolution only ever matches by name/alias (see extraction_prompt.py),
    never by location hierarchy - so hierarchy is dropped here to keep the
    resent-every-chapter story state as small as possible. The full story_state
    (hierarchy included) still flows through merge_chapter_result/the pipeline's
    return value unchanged; only the prompt-facing copy is trimmed.
    """
    return {
        "characters": story_state["characters"],
        "locations": [
            {"id": location["id"], "canonical_name": location["canonical_name"]}
            for location in story_state["locations"]
        ],
    }


def analyze_chapter(client, chapter_text: str, story_state: dict, chapter_number: int) -> dict:
    """Sends one chapter plus the running story state to Claude and returns the
    record_chapter_events tool input: {new_characters, new_locations, events}.
    """
    user_content = (
        f"## Story state so far\n{json.dumps(_story_state_for_prompt(story_state), separators=(',', ':'))}\n\n"
        f"## Chapter {chapter_number}\n{chapter_text}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[RECORD_CHAPTER_EVENTS_TOOL],
        tool_choice={"type": "tool", "name": "record_chapter_events"},
        messages=[{"role": "user", "content": user_content}],
    )

    record_usage(MODEL, response.usage)
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return tool_use.input
