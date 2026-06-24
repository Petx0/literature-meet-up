# Literature Meet Up

**What if characters from different novels could have crossed paths?**

Literature Meet Up extracts *where and when* every character in a novel was,
from the raw text of Project Gutenberg books, using Claude. It stores that as
structured data in Postgres, then serves a small public web app that finds
plausible "encounters" — pairs of characters from *different* novels whose
events overlap in time and place (e.g. *Sherlock Holmes* and *Dr. Jekyll*,
both in London in the 1880s).

**Live app:** https://literature-meet-up.onrender.com

## How it works, end to end

```
Gutendex API ──▶ raw book text ──▶ chapter splitting
                                         │
                                         ▼
                  chapter-by-chapter Claude extraction (one call per chapter,
                  stateful: each call sees the running character/location
                  registry from all earlier chapters)
                                         │
                                         ▼
            ┌────────────────┬──────────┴───────────┬─────────────────┐
            ▼                ▼                       ▼                 ▼
  chronological        book-setting           character duplicate   (events,
  reconstruction       estimation             detection             characters,
  (one call,           (one call, samples                           locations
  whole-book)          opening chapters)                            so far)
            │                │                       │                 │
            └────────────────┴──────────┬────────────┘                 │
                                         ▼                              │
                          cleanup (drop events with no usable    ◀──────┘
                          date, using the book-setting estimate
                          as a confidence-gated fallback)
                                         │
                                         ▼
                    location deduplication (per-character location
                    refinement, then whole-book canonical location table)
                                         │
                                         ▼
                         geocoding backfill (Nominatim, fills in
                         missing hierarchy levels for named real places)
                                         │
                                         ▼
                    single all-or-nothing transaction → Postgres/Supabase
                                         │
                                         ▼
              web app: pick a time-overlap + location-overlap granularity,
              get a random cross-book character encounter with evidence
```

The full design rationale for every stage lives in `PROJECT_BRIEF.md` (the
original brief plus 7 addenda written as the design evolved — read in order,
each one assumes the ones before it).

## Project layout

- `literature_meetup/` — the pipeline, one module per stage:
  - `gutendex_client.py`, `text_extractor.py`, `novel_pipeline.py` — fetch a
    book from Project Gutenberg (by title+author search, or directly by
    Gutenberg id) and split it into chapters/paragraphs.
  - `chapter_analyzer.py` + `extraction_prompt.py` / `extraction_schema.py` —
    the per-chapter Claude extraction call.
  - `analyze_pipeline.py` — runs the chapter loop, and defensively patches
    over model-compliance edge cases observed in practice (e.g. an event
    referencing a character the model forgot to declare, or a malformed
    field shape) rather than trusting every response to be perfectly
    schema-conformant.
  - `reconstruction.py`, `setting_estimation.py`, `character_dedup.py`,
    `cleanup.py`, `dedup_locations.py`, `geocode_backfill.py` — the
    remaining pipeline stages, each its own module + prompt.
  - `pipeline.py` — `process_book()`, which wires every stage together
    in-memory; nothing touches the DB until the very end.
  - `db.py` — the single all-or-nothing write transaction.
  - `model_config.py` — which Claude model each stage uses, overridable via
    environment variables (see below).
  - `usage_tracker.py` — accumulates token usage across a book's API calls
    and converts it to an estimated dollar cost.
  - `encounter_queries.py` — the time/location-overlap SQL behind the web
    app (see "The encounter query" below).
- `schema.sql` — the Postgres/Supabase schema (`books`, `characters`,
  `locations`, `events`).
- `webapp/` — the FastAPI app + static frontend for the public encounter
  finder.
- `scripts/` — runner scripts: `run_book.py` (process one book by
  title/author), `run_test_corpus.py` (batch-process `test_corpus.md`,
  skipping books already in the DB), `test_encounter_query.py` and
  `encounter_examples.sql` (exploring the encounter query directly).
- `test_corpus.md` — a curated list of 13 Gutenberg novels chosen for being
  rich in named real-world locations, used to stress-test the pipeline.
- `PROJECT_BRIEF.md` — the full design document.
- `CLAUDE.md` — working instructions for Claude Code instances operating in
  this repo (commands, architecture notes); not meant for human onboarding.

## The data model

Four tables (see `schema.sql` for the full DDL with constraints):

- **`books`** — one row per processed book, plus a book-wide *estimated
  setting* (a year range + confidence, used as a last-resort fallback for
  events with no other date information).
- **`characters`** — canonical name + aliases, one row per distinct
  character (post-deduplication).
- **`locations`** — either a place (hierarchy: country → region → city →
  neighborhood → street, however deep the text supports) or a transit
  segment (from/to + transport mode), never both.
- **`events`** — the core table: one row per character per distinct
  location/time state, with precision-tagged time fields (day / month /
  year / year-range) and a `source` flag (stated / inferred / book-estimated)
  so confidence is always visible downstream.

## The encounter query

Given a **time-overlap granularity** (day / month / year / decade / century
/ none) and a **location-overlap granularity** (neighbourhood / city /
region / country / none), the query finds cross-book character pairs whose
events satisfy both, treating missing data as a wildcard rather than a
blocker — e.g. an event with no stated month doesn't get excluded from a
"same month" match, it just doesn't help confirm or deny it either way. This
matters a lot in practice: most events only ever get a date via the
book-level estimate fallback (a wide year range), so being permissive about
partial/range data is what makes the feature produce results at all. Full
design rationale and the SQL itself: see `literature_meetup/encounter_queries.py`
and the "Character-Encounter Queries" section of `PROJECT_BRIEF.md`.

## Running the pipeline locally

Requires a `.env` file (not committed) with at least:

```
ANTHROPIC_API_KEY=...
DATABASE_URL=postgresql://...
```

```
pip install -r requirements.txt
python scripts/run_book.py "Pride and Prejudice" "Jane Austen"
```

Each run prints character/location/event counts and the API cost for that
book. To batch-process the curated test corpus (skipping anything already
in the DB):

```
python scripts/run_test_corpus.py
```

### Model configuration

Each pipeline stage's Claude model is set in `literature_meetup/model_config.py`
and overridable per-environment via env vars without touching code:

| Env var | Default | Called |
|---|---|---|
| `EXTRACTION_MODEL` | `claude-sonnet-4-6` | once per chapter |
| `RECONSTRUCTION_MODEL` | `claude-haiku-4-5` | once per book |
| `SETTING_ESTIMATION_MODEL` | `claude-opus-4-8` | once per book |
| `CHARACTER_DEDUP_MODEL` | `claude-opus-4-8` | once per book |

Extraction defaults to Sonnet rather than Opus because it's the only stage
that scales with chapter count, making it the most cost-sensitive one — see
`model_config.py`'s docstring for the full rationale (including its
interaction with prompt caching).

## Running the web app locally

The web app only needs `DATABASE_URL` (it never calls the Claude API — it
just queries already-processed data):

```
uvicorn webapp.main:app --reload
```

Then open http://127.0.0.1:8000 — pick a time-overlap and location-overlap
granularity and click "Find an encounter".

## Deployment

The live app is hosted on Render's free tier, auto-deploying from
[github.com/Petx0/literature-meet-up](https://github.com/Petx0/literature-meet-up)
on every push to `main`. Render only needs `DATABASE_URL` configured as an
environment variable — no other secret is required for the deployed app.
Note: the free tier spins down after inactivity, so the first request after
a while can take 30-60 seconds while it wakes back up.
