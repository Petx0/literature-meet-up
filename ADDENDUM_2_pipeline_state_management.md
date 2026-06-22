# Project Brief Addendum 2 — Pipeline State Management

Extends `PROJECT_BRIEF.md` and `ADDENDUM_1_chronological_reconstruction.md`. Read after
both — assumes that context.

---

## Decision: in-memory until cleanup completes, single batch write to DB

The pipeline holds all data **in memory** from the start of extraction through the end
of cleanup. The database is only written to **once, after cleanup completes**, with the
final surviving event set for the whole book.

Concretely, the in-memory lifecycle for a single book run is:

1. Module 1 fetches and chapter-splits the book (in memory).
2. Module 2 runs extraction chapter-by-chapter, accumulating: the running story_state
   (characters/locations) and the full events list, all in memory. Nothing is written
   to the database during this phase.
3. Once all chapters are extracted, reconstruction runs once over the full in-memory
   events list (the dated subset), producing `story_chronological_order` and
   `ordering_confidence` for those events. Merged back into the in-memory events list.
4. Cleanup runs once over the full in-memory events list, dropping events that fail the
   location/date checks.
5. ONLY NOW does the pipeline write to the database — a single batch write of
   characters, locations, and the surviving events for this book.

(Subsequent addenda add further in-memory stages — location dedup, geocoding backfill —
that also run before this single DB write. See `ADDENDUM_3_location_dedup.md` and
`ADDENDUM_4_geocoding_backfill.md`. This document describes the governing principle;
later documents extend the in-memory pipeline further without changing it.)

---

## Consequence: no partial persistence, no resume

This is a deliberate simplification, not an oversight. If the pipeline fails at any
point before the final DB write (e.g. extraction crashes on chapter 40 of 50,
reconstruction fails, or any later in-memory stage fails), all in-memory work for that
book run is lost — there is no partial save, and the book must be re-run from the
beginning.

This is considered an acceptable tradeoff for the current build phase (single-book,
on-demand runs), in exchange for a much simpler storage layer that only ever has to
model complete, finished data.

This should be revisited if/when the tool moves toward unattended batch processing of
many or very long books, where re-running a whole book from scratch after a late
failure becomes costly. A future option would be a lightweight checkpoint (e.g. caching
extraction output to disk after each chapter, separate from the real database) without
changing the final database schema at all — but this is explicitly out of scope now.

---

## Consequence for database schema

Because of this, the database schema only needs to model the **final, clean state**:

- No need for a "raw staging" table separate from the final table.
- `story_chronological_order` and `ordering_confidence` (from reconstruction) can be
  modeled as normal (nullable) columns on the events table from the start — they are
  never retrofitted onto already-persisted rows, since nothing is persisted until
  they're already computed.
- The database never contains an event that was later deleted by cleanup — deleted
  events simply never reach the database at all.
- The same applies to fields introduced by later in-memory stages (deduped
  `location_id` references, `geocode_status`, etc.) — by the time anything is written,
  it is already in its final form. The database schema should be designed assuming it
  only ever receives complete, fully-processed rows, never partial ones requiring
  later updates.

---

## Still open

- Geocoding / hierarchy backfill — see `ADDENDUM_4_geocoding_backfill.md`.
- Validation pass for entity duplication (characters) — not yet designed.
- `new_locations` granularity / dedup — see `ADDENDUM_3_location_dedup.md`.
- Database schema for storage — now well-scoped per the consequences above; a
  reasonable next design pass once dedup and geocoding are finalized.
- End consumer / query interface — still deferred.
