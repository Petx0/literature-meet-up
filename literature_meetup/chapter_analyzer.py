import json

from literature_meetup import llm_client
from literature_meetup.extraction_prompt import SYSTEM_PROMPT
from literature_meetup.extraction_schema import RECORD_CHAPTER_EVENTS_TOOL
from literature_meetup.model_config import EXTRACTION_MODEL as MODEL


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

    story_state only ever grows by appending (see story_state.merge_chapter_result),
    so the JSON serialized here is always an exact byte-for-byte prefix of what gets
    sent on the next chapter call. Putting a separate cache_control breakpoint right
    after it (instead of bundling it into one block with the chapter text, which
    changes every call) lets the API match that growing prefix against the cache
    written by the previous chapter's call - turning a full-price resend into a
    cheap cache read for everything except the newly-appended entries.
    """
    story_state_json = json.dumps(_story_state_for_prompt(story_state), separators=(",", ":"))
    user_content = [
        {
            "type": "text",
            "text": f"## Story state so far\n{story_state_json}",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"\n\n## Chapter {chapter_number}\n{chapter_text}",
        },
    ]

    return llm_client.call_tool(
        client, MODEL, SYSTEM_PROMPT, RECORD_CHAPTER_EVENTS_TOOL, user_content, max_tokens=8000
    )
