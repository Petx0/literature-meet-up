---
name: process-book
description: Process one novel through the full literature_meetup pipeline (fetch from Project Gutenberg, extract, reconstruct, dedupe, geocode, save to DB) and report character/location/event counts plus API cost. Use whenever asked to process, run, or add a specific book.
argument-hint: "<title> <author>  |  --id <gutenberg_id>"
allowed-tools: Bash(python *)
---

Run one book through the pipeline and report the result. `$ARGUMENTS` is
either a `"<title>" "<author>"` pair, or `--id <gutenberg_id>`.

## If given a title and author

Just run the existing runner script as-is - it already does everything
needed (loads `.env`, fetches via Gutendex title/author search, runs
`process_book`, saves, prints counts and cost):

```bash
python scripts/run_book.py "<title>" "<author>"
```

## If given `--id <gutenberg_id>` instead

Title/author search has missed matches before (accented author names,
ambiguous titles - see `fetch_novel_by_id` in `literature_meetup/novel_pipeline.py`).
Prefer fetching directly by id, mirroring the `process_one()` pattern in
`scripts/run_test_corpus.py`:

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from run_test_corpus import process_one
result = process_one(<gutenberg_id>, '<title-for-display>')
print(result)
"
```

(This still loads `.env`, caps chapters at `CHAPTER_CAP = 10` - the active
test-phase constraint, not a bug - and prints the same counts/cost summary.)

## Either way

- Report back: book title/author, Gutenberg id, chapters processed vs.
  total, character/location/event counts, and the per-model cost breakdown
  that's already printed by `usage_tracker.summary()`.
- If it fails partway (API credit exhaustion is the most common real
  cause so far), report the exact error and stop - don't retry silently or
  paper over it. If it's a new kind of model-compliance edge case (a
  malformed field shape, an undeclared reference), that's a pipeline bug
  to fix in code (see the defensive-normalization pattern in
  `literature_meetup/analyze_pipeline.py`), not something to work around
  ad hoc.
- Check first whether the book is already in the DB (`select 1 from books
  where gutenberg_id = <id>`) before re-running it, same as
  `run_test_corpus.py` does for its batch.
