from __future__ import annotations

from literature_meetup.analyze_pipeline import analyze_book
from literature_meetup.character_dedup import dedupe_characters
from literature_meetup.cleanup import filter_complete_events
from literature_meetup.dedup_locations import dedupe_locations
from literature_meetup.geocode_backfill import geocode_backfill
from literature_meetup.reconstruction import reconstruct_chronology
from literature_meetup.setting_estimation import estimate_book_setting


def process_book(
    client,
    chapters: list[dict],
    metadata: dict | None = None,
    book_id: str | None = None,
) -> dict:
    """Runs the full in-memory pipeline for one book, per Addenda 1-7:
    chapter-by-chapter extraction, one whole-book chronological
    reconstruction pass (real, event-level dates only - never sees the
    book-wide estimate below), book-level setting estimation, character
    duplication detection (certain-confidence merges only - repoints event
    character_id references before any later stage touches events), the
    cleanup filter (using the setting estimate as a confidence-gated
    fallback for otherwise dateless events), per-character location
    deduplication, then geocoding backfill on the finalized location table.

    Nothing is persisted to a database here - per Addendum 2's decided
    state management, the only DB write happens once, after this function
    returns, with whatever final event/location/character set survives
    every stage. If this function raises partway through, the whole book
    run must be re-run from scratch; that's a deliberate simplification,
    not an oversight.

    `metadata` is the novel's metadata dict from
    literature_meetup.fetch_novel (author/author_birth_year/
    author_death_year etc.) - used only by setting estimation, which runs
    independently of extraction. Defaults to {} if not supplied.

    Returns {"story_state": ..., "events": ..., "locations": ...,
    "book_metadata": {"estimated_setting": ...}, "unmerged_duplicate_groups":
    [...], "chapters_processed": int}. `story_state` is the extraction-time
    character/location registry, with `characters` updated in place to
    reflect any certain-confidence merges from character dedup; `events` is
    the final event set, each pointing at `locations` via `location_id`
    rather than holding inline location data; `locations` is the finalized,
    deduped, geocoded location table for this book; `book_metadata` carries
    the book-wide setting estimate (recorded regardless of confidence, per
    Addendum 5, even though only medium/high confidence ever affects which
    events survive cleanup); `unmerged_duplicate_groups` is the likely/
    uncertain character-duplicate groups dedupe_characters() didn't
    auto-merge, persisted by db.save_book() for later review rather than
    discarded (see scripts/review_duplicates.py); `chapters_processed` is
    simply `len(chapters)` - the number of chapters actually fed into this
    run, stored verbatim so later code can tell "already ran on the full
    text" apart from "still truncated" without guessing from how many
    chapters' events survived cleanup (unreliable - see schema.sql).
    """
    metadata = metadata or {}

    extracted = analyze_book(client, chapters, book_id=book_id)
    events = reconstruct_chronology(client, extracted["events"])

    estimated_setting = estimate_book_setting(client, metadata, chapters)

    characters, events, unmerged_duplicate_groups = dedupe_characters(
        client, extracted["story_state"]["characters"], events
    )
    extracted["story_state"]["characters"] = characters

    events = filter_complete_events(events, estimated_setting=estimated_setting)
    events, locations = dedupe_locations(events)
    locations = geocode_backfill(locations)

    return {
        "story_state": extracted["story_state"],
        "events": events,
        "locations": locations,
        "book_metadata": {"estimated_setting": estimated_setting},
        "unmerged_duplicate_groups": unmerged_duplicate_groups,
        "chapters_processed": len(chapters),
    }
