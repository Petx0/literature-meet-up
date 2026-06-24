from __future__ import annotations

from literature_meetup.chapter_analyzer import analyze_chapter
from literature_meetup.story_state import merge_chapter_result, new_story_state


def _normalize_new_characters(result: dict, chapter_number: int) -> None:
    """Defends against observed model failure modes around new_characters:
    (a) the whole field coming back as a bare string instead of an array at
    all (worse than (b) below - iterating it character-by-character and then
    trying list-item-assignment on an immutable string crashes outright), and
    (b) an individual item being a bare string (just the id/name) instead of
    the required {id, canonical_name, aliases} object. Both are normalized
    away rather than crashing downstream on dict-only access.
    """
    new_characters = result.get("new_characters", [])
    if not isinstance(new_characters, list):
        print(
            f"Chapter {chapter_number}: new_characters was a {type(new_characters).__name__}, "
            "not an array at all - discarding it (any character_id an event still needs will be "
            "auto-placeholdered by the orphan-reference check)."
        )
        result["new_characters"] = []
        return

    for i, character in enumerate(new_characters):
        if isinstance(character, str):
            print(
                f"Chapter {chapter_number}: new_characters entry {character!r} was a bare "
                "string, not an object - normalizing into a placeholder record."
            )
            new_characters[i] = {"id": character, "canonical_name": character, "aliases": []}


def _reconcile_orphaned_character_references(story_state: dict, result: dict, chapter_number: int) -> None:
    """Defends against a real, observed model failure mode: an event using a
    character_id that the same tool call never declared via new_characters
    (and that no earlier chapter declared either) - an internal
    inconsistency within a single extraction response, not a story_state
    resolution failure. Left unhandled, this surfaces only as a foreign-key
    KeyError at DB-insert time, the last possible moment to catch it.

    Mutates `result["new_characters"]` to add a clearly-flagged placeholder
    for any such orphaned id, so every event's character_id is always
    backed by a real character record by the time chapters are merged.
    """
    known_ids = {character["id"] for character in story_state["characters"]}
    known_ids.update(character["id"] for character in result.get("new_characters", []))

    for event in result.get("events", []):
        character_id = event["character_id"]
        if character_id in known_ids:
            continue
        print(
            f"Chapter {chapter_number}: event referenced undeclared character_id "
            f"{character_id!r} - adding a placeholder character record."
        )
        result.setdefault("new_characters", []).append(
            {"id": character_id, "canonical_name": f"Unknown ({character_id})", "aliases": []}
        )
        known_ids.add(character_id)


def analyze_book(client, chapters: list[dict], book_id: str | None = None) -> dict:
    """Runs the sequential, stateful chapter-by-chapter extraction pipeline
    described in the project brief: each chapter is sent with the story state
    accumulated so far, and the result is merged before moving to the next.

    chapters: list of {"title": str | None, "paragraphs": list[str]}, as
    produced by literature_meetup.text_extractor.split_into_chapters.

    Returns {"story_state": ..., "events": [...]}. `narration_order`,
    `chapter`, and `event_id` on each event are stamped here from chapter
    position rather than trusted from the model — per Addendum 1, these are
    pipeline-owned, mechanical fields, not something the LLM should compute
    or generate. `story_chronological_order` is forced to null here
    regardless of what the model returns — that field is reconstructed in a
    separate, later, whole-book pass (see literature_meetup.reconstruction),
    and the model has been observed filling it in anyway despite that being
    out of scope for extraction.
    """
    story_state = new_story_state()
    all_events = []

    for chapter_number, chapter in enumerate(chapters, start=1):
        chapter_text = "\n\n".join(chapter["paragraphs"])
        result = analyze_chapter(client, chapter_text, story_state, chapter_number)
        _normalize_new_characters(result, chapter_number)
        _reconcile_orphaned_character_references(story_state, result, chapter_number)

        for narration_order, event in enumerate(result.get("events", []), start=1):
            event["chapter"] = chapter_number
            event["sequence"] = {"narration_order": narration_order, "story_chronological_order": None}
            id_prefix = book_id or "book"
            event["event_id"] = f"{id_prefix}_{chapter_number}_{event['character_id']}_{narration_order}"

        story_state = merge_chapter_result(story_state, result)
        all_events.extend(result.get("events", []))

    return {"story_state": story_state, "events": all_events}
