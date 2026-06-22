def new_story_state() -> dict:
    return {"characters": [], "locations": []}


def merge_chapter_result(story_state: dict, chapter_result: dict) -> dict:
    """Appends new_characters/new_locations from a chapter's extraction result
    into the running story state, skipping ids already known (defends against
    the model re-declaring an entity it should have reused instead).
    """
    known_character_ids = {c["id"] for c in story_state["characters"]}
    known_location_ids = {loc["id"] for loc in story_state["locations"]}

    for character in chapter_result.get("new_characters", []):
        if character["id"] not in known_character_ids:
            story_state["characters"].append(character)
            known_character_ids.add(character["id"])

    for location in chapter_result.get("new_locations", []):
        if location["id"] not in known_location_ids:
            story_state["locations"].append(location)
            known_location_ids.add(location["id"])

    return story_state
