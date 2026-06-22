from __future__ import annotations

import json

from literature_meetup.character_dedup_prompt import CHARACTER_DEDUP_SYSTEM_PROMPT
from literature_meetup.character_dedup_schema import FLAG_CHARACTER_DUPLICATES_TOOL
from literature_meetup.model_config import CHARACTER_DEDUP_MODEL as MODEL
from literature_meetup.usage_tracker import record as record_usage


def _build_character_context(characters: list[dict], events: list[dict]) -> list[dict]:
    events_by_character: dict[str, list[dict]] = {}
    for event in events:
        events_by_character.setdefault(event["character_id"], []).append(event)

    context = []
    for character in characters:
        character_events = events_by_character.get(character["id"], [])
        context.append(
            {
                "id": character["id"],
                "canonical_name": character["canonical_name"],
                "aliases": character.get("aliases", []),
                "events": [
                    {"chapter": event["chapter"], "evidence_quote": event["evidence_quote"]}
                    for event in character_events
                ],
            }
        )
    return context


def detect_character_duplicates(client, characters: list[dict], events: list[dict]) -> list[dict]:
    """Per Addendum 7: one whole-book LLM call judging which character
    records likely refer to the same person, using name/alias data plus
    each character's associated event evidence as context - not just
    string similarity on names, which would systematically miss exactly the
    hard cases that already slipped past extraction-time resolution.

    Returns the raw `duplicate_groups` list from the model, unmerged - see
    apply_certain_merges for what happens to each confidence tier.
    """
    if not characters:
        return []

    context = _build_character_context(characters, events)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=CHARACTER_DEDUP_SYSTEM_PROMPT,
        tools=[FLAG_CHARACTER_DUPLICATES_TOOL],
        tool_choice={"type": "tool", "name": "flag_character_duplicates"},
        messages=[{"role": "user", "content": json.dumps(context, indent=2)}],
    )

    record_usage(MODEL, response.usage)
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return tool_use.input["duplicate_groups"]


def _build_redirect_map(certain_groups: list[dict]) -> dict[str, str]:
    """Maps every non-canonical character_id to its group's canonical_id,
    resolving chains so a character_id that is itself merged away in one
    group but also named as a non-canonical member of another group still
    resolves to the final surviving id - never to an intermediate id that
    is about to be dropped.
    """
    direct = {}
    for group in certain_groups:
        canonical_id = group["canonical_id"]
        for character_id in group["character_ids"]:
            if character_id != canonical_id:
                direct[character_id] = canonical_id

    resolved = {}
    for character_id in direct:
        target = character_id
        seen = set()
        while target in direct and target not in seen:
            seen.add(target)
            target = direct[target]
        resolved[character_id] = target

    return resolved


def apply_certain_merges(
    characters: list[dict], events: list[dict], duplicate_groups: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Per Addendum 7: only `certain`-confidence groups are auto-merged.
    `likely`/`uncertain` groups take no automatic action and are returned
    as-is for visibility.

    For each certain group, every event referencing a non-canonical
    character_id is repointed to canonical_id, the non-canonical character
    records are dropped, and their canonical_name + aliases are unioned
    into the surviving record's `aliases` (so the merged record keeps every
    name it was known by across the book).

    Mutates and returns (characters, events, unmerged_groups).
    """
    certain_groups = [group for group in duplicate_groups if group["confidence"] == "certain"]
    unmerged_groups = [group for group in duplicate_groups if group["confidence"] != "certain"]

    redirect = _build_redirect_map(certain_groups)
    if not redirect:
        return characters, events, unmerged_groups

    characters_by_id = {character["id"]: character for character in characters}
    merged_aliases: dict[str, set] = {}

    for old_id, canonical_id in redirect.items():
        old_character = characters_by_id.get(old_id)
        canonical_character = characters_by_id.get(canonical_id)
        if old_character is None or canonical_character is None:
            continue
        bucket = merged_aliases.setdefault(canonical_id, set(canonical_character.get("aliases") or []))
        bucket.add(old_character["canonical_name"])
        bucket.update(old_character.get("aliases") or [])

    for canonical_id, aliases in merged_aliases.items():
        characters_by_id[canonical_id]["aliases"] = sorted(aliases)

    merged_characters = [character for character in characters if character["id"] not in redirect]

    for event in events:
        if event["character_id"] in redirect:
            event["character_id"] = redirect[event["character_id"]]

    return merged_characters, events, unmerged_groups


def dedupe_characters(client, characters: list[dict], events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Runs the full Addendum 7 stage: detect duplicate groups, then apply
    only the certain-confidence merges. Prints any likely/uncertain groups
    to console for manual review - a nicety the addendum suggests rather
    than requires, so this signal isn't silently discarded.
    """
    duplicate_groups = detect_character_duplicates(client, characters, events)
    characters, events, unmerged_groups = apply_certain_merges(characters, events, duplicate_groups)

    if unmerged_groups:
        print(f"Character dedup: {len(unmerged_groups)} unmerged duplicate group(s) flagged for manual review:")
        for group in unmerged_groups:
            print(f"  [{group['confidence']}] {group['character_ids']} -> {group['canonical_id']}: {group['reasoning']}")

    return characters, events
