import json

from literature_meetup import llm_client
from literature_meetup.extraction_prompt import build_system_prompt
from literature_meetup.extraction_schema import build_record_chapter_events_tool
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


def analyze_chapter(
    client,
    chapter_text: str,
    story_state: dict,
    chapter_number: int,
    target_character_ids: list[str] | None = None,
    include_evidence_quote: bool = False,
) -> dict:
    """Sends one chapter plus the running story state to Claude and returns the
    record_chapter_events tool input: {new_characters, new_locations, events}.

    story_state only ever grows by appending (see story_state.merge_chapter_result),
    so the JSON serialized here is always an exact byte-for-byte prefix of what gets
    sent on the next chapter call. Putting a separate cache_control breakpoint right
    after it (instead of bundling it into one block with the chapter text, which
    changes every call) lets the API match that growing prefix against the cache
    written by the previous chapter's call - turning a full-price resend into a
    cheap cache read for everything except the newly-appended entries.

    target_character_ids is an experimental, opt-in cost lever (cost experiment, not
    a shipped feature): when given, the model is told to only emit `events` for those
    ids, cutting output tokens on the long tail of minor characters - it does not
    reduce the chapter-text input cost, since the model still has to read the whole
    chapter to find target-character mentions. analyze_pipeline.py defends against
    the model ignoring this instruction by dropping any non-compliant event anyway.

    include_evidence_quote defaults to False: dropping the evidence_quote field from
    both the schema (extraction_schema.py) and this prompt's Evidence section
    (extraction_prompt.py) measured at ~20% of one event's output tokens (it's a full
    natural-language paraphrase, not structured data) for a real, no-accuracy-cost
    saving, confirmed cheap enough to make the default. Pass True to get it back -
    character_dedup.py uses it as identity evidence when present.

    The target-character instruction is fixed for the whole book, so it's placed
    BEFORE the growing story_state JSON, not after - story_state must stay at the
    end of the cached block so each chapter's block text is still an exact prefix
    of the next chapter's (append-only), preserving the incremental-cache property
    from the cache_control breakpoint below. Putting a constant suffix after the
    growing JSON would break that prefix match on every single call.
    """
    story_state_json = json.dumps(_story_state_for_prompt(story_state), separators=(",", ":"))
    story_state_text = ""
    if target_character_ids is not None:
        story_state_text += (
            f"## Target characters\nOnly include `events` entries for these character ids: "
            f"{json.dumps(target_character_ids, separators=(',', ':'))}. You may still add other "
            f"characters to `new_characters` for entity-resolution continuity, but do not generate "
            f"`events` entries for anyone not in this list.\n\n"
        )
    story_state_text += f"## Story state so far\n{story_state_json}"
    user_content = [
        {
            "type": "text",
            "text": story_state_text,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"\n\n## Chapter {chapter_number}\n{chapter_text}",
        },
    ]

    system_prompt = build_system_prompt(include_evidence_quote)
    tool = build_record_chapter_events_tool(include_evidence_quote)
    return llm_client.call_tool(client, MODEL, system_prompt, tool, user_content, max_tokens=8000)
