# Literature Meet Up

Extracts character location/time data from Project Gutenberg novels (via the
[Gutendex API](https://gutendex.com) and the Claude API), stores it in
Postgres/Supabase, and serves a small web app that finds characters from
different novels who could plausibly have crossed paths in time and place.

## Project layout

- `literature_meetup/` — the extraction pipeline (Gutendex fetch, chapter
  splitting, chapter-by-chapter Claude extraction, chronological
  reconstruction, location dedup, geocoding backfill, character dedup,
  Postgres write layer) plus `encounter_queries.py`, the query logic behind
  the web app.
- `schema.sql` — the Postgres/Supabase schema.
- `scripts/` — one-off runner scripts used to process books through the
  pipeline (`run_book.py`) and to explore the encounter queries
  (`test_encounter_query.py`, `encounter_examples.sql` — paste the latter
  directly into the Supabase SQL editor).
- `webapp/` — the FastAPI app + static frontend for the public "character
  encounter finder".

## Running the pipeline locally

Requires a `.env` file (not committed) with:

```
ANTHROPIC_API_KEY=...
DATABASE_URL=postgresql://...
```

```
pip install -r requirements.txt
python scripts/run_book.py "Pride and Prejudice" "Jane Austen"
```

## Running the web app locally

Only needs `DATABASE_URL` in the environment (it never calls the Claude API):

```
uvicorn webapp.main:app --reload
```

Then open http://127.0.0.1:8000 — pick a time-overlap and location-overlap
granularity and click "Find an encounter".
