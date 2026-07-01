"""Batch runner for test_corpus.md, in the doc's recommended processing
order. Skips any book already present in the DB (by gutenberg_id). On any
per-book failure, prints the error and moves on to the next book rather than
stopping the whole batch. Prints a time/cost summary at the end.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key:
            os.environ[key] = value

import anthropic

from literature_meetup import fetch_novel_by_id, get_connection, process_book, save_book
from literature_meetup import model_config, usage_tracker
from literature_meetup.cli_backend import CliStopBatchError

# No per-book chapter cap in production - process every chapter Gutendex returns.
# MAX_CHAPTERS is a separate, unrelated guard: skip a novel outright (no Claude
# API calls at all) if it's longer than this many chapters, since extraction
# cost scales linearly with chapter count and a few outliers in this corpus
# (Les Miserables: 365 chapters, ~6x the next-longest book) would dominate a
# batch run's cost. Override via the MAX_CHAPTERS env var if you want to
# process a skipped book anyway.
MAX_CHAPTERS = int(os.environ.get("MAX_CHAPTERS", "120"))

# (gutenberg_id, title) in test_corpus.md's recommended processing order.
CORPUS = [
    (103, "Around the World in Eighty Days"),
    (1184, "The Count of Monte Cristo"),
    (1257, "The Three Musketeers"),
    (2759, "The Man in the Iron Mask"),
    (60, "The Scarlet Pimpernel"),
    (521, "Robinson Crusoe"),
    (76, "Adventures of Huckleberry Finn"),
    (86, "A Connecticut Yankee in King Arthur's Court"),
    (3526, "Five Weeks in a Balloon"),
    (2166, "King Solomon's Mines"),
    (2641, "A Room with a View"),
    (829, "Gulliver's Travels"),
    (2554, "Crime and Punishment"),
    (2610, "Notre-Dame de Paris (The Hunchback of Notre Dame)"),
    (145, "Middlemarch"),
    (143, "The Mayor of Casterbridge"),
    (541, "The Age of Innocence"),
    #(2600, "War and Peace"),
    #(1399, "Anna Karenina"),
    (74, "The Adventures of Tom Sawyer"),
    (120, "Treasure Island"),
    (244, "A Study in Scarlet"),
    (4217, "A Portrait of the Artist as a Young Man"),
    (2465, "Carmen"),
    (66677, "Gil Blas Vol. 1 (Le Sage)"),
    (2527, "Sorrows of Young Werther"),
    (1237, "Père Goriot"),
    (2413, "Madame Bovary"),
    (2638, "The Idiot"),
    (1081, "Dead Souls"),
    (766, "David Copperfield"),
    (2833, "Portrait of a Lady Vol. 1")
]


def already_processed(conn, gutenberg_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from books where gutenberg_id = %s limit 1", (gutenberg_id,))
        return cur.fetchone() is not None


def process_one(novel: dict, gutenberg_id: int) -> dict:
    usage_tracker.reset()
    start = time.monotonic()

    chapters = novel["chapters"]
    print(
        f"  Fetched: {novel['metadata']['title']!r} by {novel['metadata']['author']} "
        f"({len(chapters)} chapters)"
    )

    client = anthropic.Anthropic() if model_config.LLM_BACKEND == "api" else None
    result = process_book(client, chapters, metadata=novel["metadata"], book_id=str(gutenberg_id))

    conn = get_connection()
    try:
        book_id = save_book(conn, novel, result)
        cur = conn.cursor()
        cur.execute("select count(*) from characters where book_id = %s", (book_id,))
        characters = cur.fetchone()[0]
        cur.execute("select count(*) from locations where book_id = %s", (book_id,))
        locations = cur.fetchone()[0]
        cur.execute("select count(*) from events where book_id = %s", (book_id,))
        events = cur.fetchone()[0]
    finally:
        conn.close()

    elapsed = time.monotonic() - start
    cost_summary = usage_tracker.summary()
    print(f"  Saved book_id: {book_id} | characters: {characters} | locations: {locations} | events: {events}")
    if model_config.LLM_BACKEND == "cli":
        print(
            f"  Time: {elapsed:.0f}s | Subscription usage (no per-token billing); "
            f"equivalent API cost ~${cost_summary['equivalent_api_cost']:.4f}"
        )
    else:
        print(f"  Time: {elapsed:.0f}s | Cost: ${cost_summary['total_cost']:.4f}")

    return {
        "title": novel["metadata"]["title"],
        "status": "processed",
        "elapsed_seconds": elapsed,
        "cost": cost_summary["total_cost"],
    }


def main():
    summary = []

    for gutenberg_id, title in CORPUS:
        print(f"\n=== Book {gutenberg_id}: {title} ===")

        conn = get_connection()
        try:
            skip = already_processed(conn, gutenberg_id)
        finally:
            conn.close()

        if skip:
            print("  Already in DB - skipping.")
            summary.append({"title": title, "status": "skipped", "elapsed_seconds": None, "cost": None})
            continue

        novel = fetch_novel_by_id(gutenberg_id)
        chapter_count = len(novel["chapters"])
        if chapter_count > MAX_CHAPTERS:
            print(f"  Skipping - {chapter_count} chapters exceeds MAX_CHAPTERS={MAX_CHAPTERS}.")
            summary.append(
                {"title": title, "status": f"skipped: too long ({chapter_count} chapters)", "elapsed_seconds": None, "cost": None}
            )
            continue

        try:
            summary.append(process_one(novel, gutenberg_id))
        except CliStopBatchError as exc:
            print(f"  STOPPING BATCH: {exc} Re-run later to resume.")
            summary.append({"title": title, "status": f"failed: {exc}", "elapsed_seconds": None, "cost": None})
            break
        except Exception as exc:
            print(f"  ERROR: {exc!r} - skipping to next book.")
            summary.append({"title": title, "status": f"failed: {exc!r}", "elapsed_seconds": None, "cost": None})

    print("\n\n=== Summary ===")
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
