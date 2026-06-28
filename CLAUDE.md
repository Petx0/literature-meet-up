# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Extracts *where and when* every character in a Project Gutenberg novel was,
using Claude, into a Postgres/Supabase database, then serves a small FastAPI
app that finds plausible "encounters" — characters from *different* novels
whose events overlap in time and place. Live app:
https://literature-meet-up.onrender.com. Full design rationale lives in
`PROJECT_BRIEF.md` (the original brief plus 7 addenda, written in order —
each assumes the ones before it; read it before changing pipeline behavior).

## Commands

There is no build step, lint config, or automated test suite in this repo —
all verification is done by running real pipeline/query code against the
live Supabase DB. Set up `.env` first (gitignored, never commit it):

```
ANTHROPIC_API_KEY=...
DATABASE_URL=postgresql://...
```

```bash
pip install -r requirements.txt

# Process one book through the full pipeline and write it to the DB.
# Prints character/location/event counts and the API cost for that book.
python scripts/run_book.py "Pride and Prejudice" "Jane Austen"

# Batch-process the curated corpus in test_corpus.md, in its recommended
# order. Skips any book already in the DB (by gutenberg_id) and continues
# past a per-book failure instead of aborting the whole run.
python scripts/run_test_corpus.py

# Run the web app locally (only needs DATABASE_URL - never calls the Claude API).
uvicorn webapp.main:app --reload   # http://127.0.0.1:8000

# Iterate on the encounter-finding SQL directly against the live DB.
python scripts/test_encounter_query.py
```

`scripts/encounter_examples.sql` is meant to be pasted directly into the
Supabase SQL editor for manual exploration, not run as a script.

Both `run_book.py` and `run_test_corpus.py` cap processing at the first 10
chapters per book (`CHAPTER_CAP`) — this is a deliberate, still-active test
constraint, not a bug, while the pipeline is being validated against more
books.

When running with `LLM_BACKEND=cli` (subscription billing via the local
`claude` CLI instead of per-token API billing — see `model_config.py`),
subscription usage windows can't be reliably outrun by retrying or pacing
calls slightly slower; once a run gets rate-limited mid-batch, the fix is to
stop proactively before the call that would hit it. After any run that gets
rate-limited, note the `equivalent_api_cost` figure printed in that run's
summary, then set `CLI_SESSION_BUDGET_USD` in `.env` to a bit below that
figure before the next `run_test_corpus.py` run — it stops the batch
cleanly once the process-lifetime equivalent cost reaches the cap, instead
of burning through the rest of the corpus against the same wall.

## Architecture

### The pipeline is a single in-memory function, with one DB write at the end

`literature_meetup/pipeline.py`'s `process_book()` wires every stage
together in memory and returns one final dict. **Nothing touches the
database until `db.py`'s `save_book()` runs, in one all-or-nothing
transaction, after every stage has finished.** If a run fails partway
through, the whole book must be re-run from scratch — there is no partial
persistence or staging table, by design (see `PROJECT_BRIEF.md` Addendum 2).
Don't add intermediate writes without revisiting that decision.

Stage order, and why each one is where it is:

1. **Extraction** (`analyze_pipeline.py` + `chapter_analyzer.py`) — one
   Claude call *per chapter*, sequential and stateful: each call is given
   the running `story_state` (characters/locations seen so far, via
   `story_state.py`) so the model can reuse existing entity ids instead of
   creating duplicates. This is the only stage that scales with book
   length, which is why it's also the focus of the model-tier/cost
   decisions below.
2. **Chronological reconstruction** (`reconstruction.py`) — one whole-book
   call, only over events that already have *real* (stated/inferred) date
   data. It never sees the book-level estimate from step 3.
3. **Book-setting estimation** (`setting_estimation.py`) — one call,
   independent of extraction, sampling only the opening chapters + Gutendex
   author metadata. Produces a year-range estimate used only as a
   *last-resort fallback* in cleanup, not a primary date source.
4. **Character duplication detection** (`character_dedup.py`) — one
   whole-book call. Only `certain`-confidence merges are auto-applied;
   `likely`/`uncertain` groups are printed for manual review, not acted on.
   This must run before cleanup/dedup touch events, since it repoints
   `character_id` references.
5. **Cleanup** (`cleanup.py`) — drops events with no usable date, using the
   book-level estimate from step 3 as a confidence-gated fallback for
   otherwise-dateless events.
6. **Location dedup** (`dedup_locations.py`) — per-character location
   refinement first, then a whole-book canonical location table. Pure
   deterministic code, no LLM call.
7. **Geocoding backfill** (`geocode_backfill.py`) — Nominatim, fills in
   missing hierarchy levels for named real places only.

### Defend against model non-compliance in code, not in the prompt

A recurring, deliberate pattern in `analyze_pipeline.py`: the extraction
prompt instructs the model toward a strict schema, but real responses have
been observed violating it in several ways (an event referencing a
character id never declared via `new_characters`; `new_characters` items
or even the whole field coming back as a bare string instead of an
object/array). Each observed failure mode gets a small, targeted
normalization function that runs immediately after `analyze_chapter()` and
turns the malformed shape into something valid (a placeholder character
record, etc.) — rather than trusting the model or tightening the prompt
further. When a new malformed-response shape shows up, follow this pattern:
fix it defensively in the pipeline code, not just in the prompt wording.

### Per-stage model selection is centralized and cost-aware

`literature_meetup/model_config.py` is the single place every stage's model
comes from; each constant reads its own env var first, falling back to a
documented default. **Read the docstring table in that file before changing
a default** — the current allocation (Sonnet for the per-chapter extraction
call, Opus for the three once-per-book judgment calls) is deliberately
inverted from "use the strongest model everywhere": extraction is the only
stage whose call count scales with book length, so it's the most
cost-sensitive one, while the once-per-book calls can afford the stronger
tier regardless of book length. This also interacts with prompt caching
(see next) — Opus's minimum cacheable prefix is 4096 tokens vs. Sonnet's
2048, so moving extraction to a stronger model can silently disable caching
on it.

All four Claude-calling stages set a `cache_control: {"type": "ephemeral"}`
breakpoint on their system prompt, since the system prompt + tool schema is
fixed and unchanged across all of a stage's calls within a book — most
impactful for extraction, called once per chapter with the same fixed
prefix every time. When building a new prompt that sends JSON to the model
(`json.dumps(...)`), use compact `separators=(",", ":")`, not
`indent=2` — pretty-printing only costs input tokens, and the cost compounds
in extraction since `story_state` grows every chapter and is fully
re-serialized on each call.

`usage_tracker.py` accumulates token usage across a book's calls (reset per
book by the calling script) and converts it to an estimated dollar cost
using a hardcoded per-model pricing table — update that table if pricing
changes or a new model is added to `model_config.py`.

### The encounter query: generous matching over strict matching

`literature_meetup/encounter_queries.py` is the SQL behind the web app.
Given a time-overlap granularity (day/month/year/decade/century/none) and a
location-overlap granularity (neighbourhood/city/region/country/none), it
finds cross-book character pairs whose events satisfy both — treating
missing data as a wildcard, never a blocker. This is load-bearing, not a
stylistic choice: most events only ever get a date via the book-level
estimate fallback (a wide year range, not a real date), so a strict-equality
join would return almost nothing. The same null-safe "compatible" pattern is
used for both time fields and location hierarchy levels — when extending
the granularity options, keep that symmetry.

Two other invariants in that file worth knowing before changing it:
- Matches are cross-book only (`p1.book_id < p2.book_id`), never within the
  same novel.
- Transit locations (journeys between named places) are expanded into up to
  two separate comparison "points" (`from` and `to`), each compared
  independently against other locations — a transit segment can satisfy a
  `country`/`city` match on either endpoint but never `region`/`neighborhood`
  (transit only ever stores country/city for each endpoint).

`webapp/main.py` validates the two granularity query params against
`TIME_GRANULARITIES`/`LOCATION_GRANULARITIES` before calling
`random_encounter()` (which orders by `random()` and takes one row) — any
new granularity value must be added to both the tuple in
`encounter_queries.py` and the SQL branch that handles it, or it'll 400.

### Data model

Four tables in `schema.sql`: `books` (includes the book-level setting
estimate), `characters` (canonical name + aliases, post-dedup),
`locations` (a place *or* a transit segment, never both — enforced by a
check constraint), `events` (one row per character per distinct
location/time state, with a precision-tagged time and a
stated/inferred/book-estimated source flag). `events.location_id` and
`events.character_id` point at the already-deduped final tables — there is
no junction/staging shape to support.
