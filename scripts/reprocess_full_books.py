"""One-off batch script: every book currently in the DB was processed under
the old CHAPTER_CAP=10 test constraint (see CLAUDE.md/git history). Now that
the pipeline is validated and the cap is removed from run_book.py /
run_test_corpus.py, this reprocesses each existing book from chapter 1 with
no cap, replacing its truncated row with a full one.

Per MAX_CHAPTERS (see run_book.py/run_test_corpus.py), any book longer than
the cap is left untouched - 10 chapters of a very long novel is better than
nothing, and reprocessing it would need an explicit override decided
separately (see Les Miserables, currently 365 chapters > MAX_CHAPTERS=120).

Safety: the old row is only deleted AFTER a new pipeline run succeeds, and
the delete + the new insert happen in the same DB transaction (save_book's
own commit covers both) - so a failed API call never destroys existing data.

Idempotent across re-runs: a book whose existing row's chapters_processed
already matches (or exceeds) the freshly-fetched full chapter count is
skipped before any API call - otherwise a re-run (e.g. after hitting a
billing limit partway through the corpus) would burn API cost re-doing books
that were already fully reprocessed in an earlier run. chapters_processed is
read straight off the books row (see schema.sql) rather than inferred from
how many chapters' events survived cleanup, which is unreliable - cleanup
legitimately drops chapters with no usable date, and by how much varies a
lot book to book.

Usage:
    python scripts/reprocess_full_books.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key and not line.startswith("#"):
            os.environ[key] = value

import anthropic

from literature_meetup import fetch_novel_by_id, get_connection, process_book, save_book
from literature_meetup import model_config, usage_tracker

MAX_CHAPTERS = int(os.environ.get("MAX_CHAPTERS", "120"))


def existing_books(conn) -> list[tuple[str, int, str, int | None]]:
    with conn.cursor() as cur:
        cur.execute("select id, gutenberg_id, title, chapters_processed from books order by processed_at")
        return cur.fetchall()


def reprocess_one(old_book_id: str, gutenberg_id: int, old_title: str, chapters_processed: int | None) -> dict:
    usage_tracker.reset()
    start = time.monotonic()

    novel = fetch_novel_by_id(gutenberg_id)
    chapters = novel["chapters"]
    chapter_count = len(chapters)
    print(f"  Fetched: {novel['metadata']['title']!r} ({chapter_count} chapters)")

    if chapter_count > MAX_CHAPTERS:
        print(f"  Keeping existing truncated row - {chapter_count} chapters exceeds MAX_CHAPTERS={MAX_CHAPTERS}.")
        return {"title": old_title, "status": f"kept existing ({chapter_count} chapters)", "elapsed_seconds": None, "cost": None}

    if chapters_processed is not None and chapters_processed >= chapter_count:
        print(f"  Already fully reprocessed ({chapters_processed} of {chapter_count} chapters) - skipping.")
        return {"title": old_title, "status": "already fully reprocessed", "elapsed_seconds": None, "cost": None}

    client = anthropic.Anthropic() if model_config.LLM_BACKEND == "api" else None
    result = process_book(client, chapters, metadata=novel["metadata"], book_id=str(gutenberg_id))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("delete from books where id = %s", (old_book_id,))
        new_book_id = save_book(conn, novel, result)  # commits the delete + the new rows together

        cur = conn.cursor()
        cur.execute("select count(*) from characters where book_id = %s", (new_book_id,))
        characters = cur.fetchone()[0]
        cur.execute("select count(*) from locations where book_id = %s", (new_book_id,))
        locations = cur.fetchone()[0]
        cur.execute("select count(*) from events where book_id = %s", (new_book_id,))
        events = cur.fetchone()[0]
    finally:
        conn.close()

    elapsed = time.monotonic() - start
    cost_summary = usage_tracker.summary()
    print(f"  Replaced book_id {old_book_id} -> {new_book_id} | characters: {characters} | locations: {locations} | events: {events}")
    if model_config.LLM_BACKEND == "cli":
        print(
            f"  Time: {elapsed:.0f}s | Subscription usage (no per-token billing); "
            f"equivalent API cost ~${cost_summary['equivalent_api_cost']:.4f}"
        )
    else:
        print(f"  Time: {elapsed:.0f}s | Cost: ${cost_summary['total_cost']:.4f}")

    return {
        "title": novel["metadata"]["title"],
        "status": "reprocessed",
        "elapsed_seconds": elapsed,
        "cost": cost_summary["total_cost"],
    }


def main():
    conn = get_connection()
    try:
        books = existing_books(conn)
    finally:
        conn.close()

    print(f"Found {len(books)} existing book(s) to reprocess.\n")

    summary = []
    for old_book_id, gutenberg_id, old_title, chapters_processed in books:
        print(f"=== {old_title} (gutenberg_id={gutenberg_id}) ===")
        try:
            summary.append(reprocess_one(old_book_id, gutenberg_id, old_title, chapters_processed))
        except Exception as exc:
            print(f"  ERROR: {exc!r} - existing row left untouched, skipping to next book.")
            summary.append({"title": old_title, "status": f"failed: {exc!r}", "elapsed_seconds": None, "cost": None})
        print()

    print("\n=== Summary ===")
    total_time = 0.0
    total_cost = 0.0
    for entry in summary:
        if entry["elapsed_seconds"] is not None:
            total_time += entry["elapsed_seconds"]
            total_cost += entry["cost"]
            print(f"  {entry['title']}: {entry['status']} | {entry['elapsed_seconds']:.0f}s | ${entry['cost']:.4f}")
        else:
            print(f"  {entry['title']}: {entry['status']}")
    print(f"\n  TOTAL processed time: {total_time:.0f}s | TOTAL cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
