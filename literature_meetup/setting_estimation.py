from __future__ import annotations

import json

from literature_meetup.model_config import SETTING_ESTIMATION_MODEL as MODEL
from literature_meetup.setting_estimation_prompt import SETTING_ESTIMATION_SYSTEM_PROMPT
from literature_meetup.setting_estimation_schema import ESTIMATE_BOOK_SETTING_TOOL
from literature_meetup.usage_tracker import record as record_usage

SAMPLE_CHAPTER_COUNT = 2


def _build_text_sample(chapters: list[dict]) -> str:
    sample_chapters = chapters[:SAMPLE_CHAPTER_COUNT]
    return "\n\n".join("\n\n".join(chapter["paragraphs"]) for chapter in sample_chapters)


def estimate_book_setting(client, metadata: dict, chapters: list[dict]) -> dict:
    """Per Addendum 5: produces a single, book-wide `estimated_setting`
    estimate from a sample of the opening chapters plus whatever author
    metadata Gutendex provides (publication year is not reliably available
    from Gutendex, only author birth/death years).

    This runs independently of extraction/reconstruction - it only needs
    `chapters` (as produced by Module 1) and the novel's `metadata`, not any
    extracted events. Returns the `estimated_setting` dict described in the
    addendum: {year_range_start, year_range_end, confidence, basis, method}.
    """
    text_sample = _build_text_sample(chapters)

    user_content = (
        f"## Publication metadata\n"
        f"Author: {metadata.get('author')}\n"
        f"Author birth year: {metadata.get('author_birth_year')}\n"
        f"Author death year: {metadata.get('author_death_year')}\n\n"
        f"## Text sample (opening chapters)\n{text_sample}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SETTING_ESTIMATION_SYSTEM_PROMPT,
        tools=[ESTIMATE_BOOK_SETTING_TOOL],
        tool_choice={"type": "tool", "name": "estimate_book_setting"},
        messages=[{"role": "user", "content": user_content}],
    )

    record_usage(MODEL, response.usage)
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return json.loads(json.dumps(tool_use.input))
