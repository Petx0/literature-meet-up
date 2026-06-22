# Project Brief Addendum 6 — Database Schema

Extends `PROJECT_BRIEF.md` and Addenda 1–5. Read after all of them — assumes that
context. Companion file: `schema.sql` (plain Postgres DDL, designed for Supabase).

---

## Why Supabase / Postgres

- The data is genuinely relational (characters → events → locations, with foreign
  keys throughout) — not document-shaped — so a relational DB fits naturally rather
  than working against the grain.
- Free tier is sufficient for single-book, on-demand processing during development.
- Built-in REST/client API gives a query layer for free if/when the end-consumer /
  query interface (still an open item) gets designed.
- `schema.sql` is plain Postgres DDL — runs directly in the Supabase SQL editor or via
  Supabase migration tooling. No Supabase-specific syntax used beyond relying on
  `gen_random_uuid()`, which is available by default in Supabase Postgres instances.

---

## Design principles carried into the schema

- **No staging tables.** Per Addendum 2, nothing is written to the database until the
  full in-memory pipeline (extraction → reconstruction → book-setting estimation →
  cleanup → location dedup → geocoding backfill) has finished. Every row inserted is
  already in its final form — there is no "partial" row shape to support anywhere.
- **Each pipeline run produces a new `books` row** (and cascading characters/locations/
  events), rather than updating an existing book's data in place. Re-running the same
  Gutenberg book is treated as an independent new run. No uniqueness constraint on
  `gutenberg_id` — deliberately, to keep iteration/re-testing friction-free during
  development. See note at the bottom of `schema.sql`.
- **Fixed-vocabulary fields are Postgres ENUM types**, not free text — gives DB-level
  validation for the controlled vocabularies defined across the brief and addenda
  (`location_type`, `transport_mode`, `precision`, `source`, `confidence`,
  `temporal_relation`, `ordering_confidence`, geocoding status, etc.).
- **Hierarchy fields are real columns**, not JSON — `city`, `country`, etc. are
  expected query/filter targets, so they're indexed columns rather than buried in a
  `jsonb` blob.

---

## Table-by-table mapping to prior addenda

### `books`
One row per processed novel.
- `gutendex_metadata` (jsonb) — raw Gutendex API response, kept for reference/debugging,
  not queried directly in normal use.
- `estimated_year_range_start/end`, `estimated_setting_confidence`,
  `estimated_setting_basis`, `estimated_setting_method` — directly from Addendum 5's
  `book_metadata.estimated_setting` object. **Always populated for every book,
  regardless of confidence** — per Addendum 5, only the USE of this estimate to fill
  individual events is confidence-gated (medium/high only), not its storage.

### `characters`
One row per distinct character per book, post entity-resolution (project brief,
"Entity resolution" section). `aliases` is a Postgres `text[]` — no separate alias
table needed at this scale.

### `locations`
One row per distinct location per book, **after** both location dedup (Addendum 3) and
geocoding backfill (Addendum 4) have run — this table only ever holds final, deduped,
backfilled location data.
- `country` / `region` / `city` / `neighborhood` / `street` — the hierarchy, per the
  original location schema. Null fields reflect genuine absence in the source text
  (or geocoding's inability to confidently resolve them — see `geocode_status`).
- `hierarchy_source` — maps to the original `location.source` field
  (`stated`/`inferred`; `book_estimated` is not expected here, that value is reserved
  for `events.time_source` per Addendum 5 — see note in schema comments).
- `transit_from_*` / `transit_to_*` / `transport_mode` / `transport_detail` —
  populated only when `location_type = 'transit'`, per Addendum 2's transit design.
  Enforced via the `chk_transit_shape` CHECK constraint: transit and hierarchy fields
  are mutually exclusive on a single row.
- `geocode_status` — directly from Addendum 4 (`resolved` / `unresolved` / `skipped`).
  Defaults to `'skipped'` since most rows (fictional/ambiguous/transit) never attempt
  backfill at all.

### `events`
The core table — one row per character per distinct location/time state, per the
project brief's one-event-per-character decision. Only events that survived cleanup
(Addendum 1, as modified by Addendum 5's book-estimated fallback) ever reach this
table.
- `id` — this column IS the `event_id` referenced throughout Addenda 1 and 5 (used by
  the reconstruction step to reference events). Generated once, at insert time, since
  nothing is written until the pipeline's final batch write (Addendum 2) — no need to
  generate IDs earlier in the pipeline unless your in-memory implementation finds it
  convenient to do so before insert.
- `time_year_range_start/end`, `time_year`, `time_month`, `time_day`, `time_precision`
  — the `time.hierarchy` object, flattened to columns.
- `time_source` — three-value enum per Addendum 5 (`stated` / `inferred` /
  `book_estimated`). This is the field that distinguishes a real textual date from a
  book-wide era backfill — must never be dropped or collapsed in any downstream query
  that cares about date reliability.
- `narration_order` — pipeline-stamped (not LLM-generated), per the project brief's
  original note and Addendum 1's clarification distinguishing it from
  `story_chronological_order`.
- `story_chronological_order` — nullable. Null for events that never had enough date
  information to enter reconstruction (Addendum 1), AND for events whose only date
  came from `book_estimated` (Addendum 5 — these deliberately never get a
  chronological position, only a rough era).
- `ordering_confidence` — nullable; only populated for events that actually went
  through reconstruction (Addendum 1's `assign_chronological_order` output).
- `confidence` — the presence-confidence field (`explicit`/`inferred`), distinct from
  `time_source` and the location's `hierarchy_source`. Answers "is the character
  actually here," not "how precisely do we know where/when." See inline column
  comment in `schema.sql` for the full distinction — this is a recurring point of
  possible confusion given three similarly-purposed fields exist in this schema, and
  is worth keeping straight when writing queries later.
- `evidence_quote` — paraphrase only, never a verbatim excerpt, per copyright handling
  established in the original system prompt.

---

## What's intentionally NOT in this schema

- No table for raw/incomplete extraction output — doesn't exist per Addendum 2's
  in-memory-until-final design.
- No alias join table — `text[]` column is sufficient at this scale.
- No historical/period-accurate geography table — explicitly out of scope per
  Addendum 4 (modern-day political geography only, by deliberate choice).
- No user/auth tables — out of scope for the current single-user, local-pipeline
  build phase.

---

## Still open

- Entity-duplication validation pass for characters — not yet designed; would likely
  operate on the `characters` table post-insert, or as an in-memory pre-insert check
  consistent with everything else in this pipeline.
- End consumer / query interface — now meaningfully unblocked, since the schema this
  would query against is defined. Reasonable next planning topic.
