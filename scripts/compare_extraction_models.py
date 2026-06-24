"""Side-by-side extraction quality comparison: runs the same chapters through
the stateful chapter-analyzer loop once per model and prints both results for
manual review. Not part of the library - a throwaway tool to decide whether
EXTRACTION_MODEL can be safely downgraded from Sonnet to Haiku (see the cost
optimization plan). This does NOT write to the database.

Usage:
    python scripts/compare_extraction_models.py "Around the World in Eighty Days" "Jules Verne" [num_chapters]
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key and not line.startswith("#"):
            os.environ[key] = value

import anthropic

from literature_meetup import chapter_analyzer, fetch_novel, usage_tracker
from literature_meetup.analyze_pipeline import _normalize_new_characters, _reconcile_orphaned_character_references
from literature_meetup.story_state import merge_chapter_result, new_story_state

MODELS_TO_COMPARE = ["claude-sonnet-4-6", "claude-haiku-4-5"]


def run_with_model(client, model: str, chapters: list[dict]) -> tuple[list[dict], dict]:
    """Runs the same sequential, stateful extraction loop analyze_book() uses,
    but pinned to one model (via monkeypatching the chapter_analyzer module's
    MODEL global, since analyze_chapter() reads it as a module-level name at
    call time - the cleanest way to override the model without changing the
    production function's signature for a throwaway comparison script) and
    capturing each chapter's result instead of just the merged final state.
    """
    chapter_analyzer.MODEL = model
    usage_tracker.reset()

    story_state = new_story_state()
    chapter_results = []

    for chapter_number, chapter in enumerate(chapters, start=1):
        chapter_text = "\n\n".join(chapter["paragraphs"])
        result = chapter_analyzer.analyze_chapter(client, chapter_text, story_state, chapter_number)
        _normalize_new_characters(result, chapter_number)
        _reconcile_orphaned_character_references(story_state, result, chapter_number)
        chapter_results.append(result)
        story_state = merge_chapter_result(story_state, result)

    return chapter_results, usage_tracker.summary()


def summarize(model: str, chapter_results: list[dict], cost: dict) -> None:
    print(f"\n{'=' * 70}\n{model}\n{'=' * 70}")
    for chapter_number, result in enumerate(chapter_results, start=1):
        new_chars = [c["canonical_name"] for c in result.get("new_characters", [])]
        new_locs = [l["canonical_name"] for l in result.get("new_locations", [])]
        print(f"\n--- Chapter {chapter_number} ---")
        print(f"new_characters: {new_chars}")
        print(f"new_locations: {new_locs}")
        print(f"events: {len(result.get('events', []))}")
        print(json.dumps(result, indent=2))
    print(f"\nCost for this model: ${cost['total_cost']:.4f}")
    for m, bucket in cost["by_model"].items():
        print(
            f"  {m}: {bucket['calls']} call(s), {bucket['input_tokens']} input tok, "
            f"{bucket['cache_creation_input_tokens']} cache-write tok, "
            f"{bucket['cache_read_input_tokens']} cache-read tok, "
            f"{bucket['output_tokens']} output tok, ${bucket['cost']:.4f}"
        )


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "Around the World in Eighty Days"
    author = sys.argv[2] if len(sys.argv) > 2 else "Jules Verne"
    num_chapters = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    novel = fetch_novel(title, author)
    chapters = novel["chapters"][:num_chapters]
    print(
        f"Fetched: {novel['metadata']['title']!r} by {novel['metadata']['author']} "
        f"- comparing {len(chapters)} chapter(s) across {MODELS_TO_COMPARE}"
    )

    client = anthropic.Anthropic()

    results_by_model = {}
    for model in MODELS_TO_COMPARE:
        results_by_model[model] = run_with_model(client, model, chapters)

    for model, (chapter_results, cost) in results_by_model.items():
        summarize(model, chapter_results, cost)

    print(
        "\nManual review checklist: same characters/locations identified per chapter? "
        "Same event count and location/time precision? Any entity duplication "
        "(same person/place split into two ids) on either model? Only promote Haiku "
        "to DEFAULT_EXTRACTION_MODEL in model_config.py if this looks acceptable."
    )


if __name__ == "__main__":
    main()
