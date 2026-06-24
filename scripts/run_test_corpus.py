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
from literature_meetup import usage_tracker

CHAPTER_CAP = 10

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
    (2226, "Kim"),
    (2641, "A Room with a View"),
    (829, "Gulliver's Travels"),
]


def already_processed(conn, gutenberg_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from books where gutenberg_id = %s limit 1", (gutenberg_id,))
        return cur.fetchone() is not None


def process_one(gutenberg_id: int, title: str) -> dict:
    usage_tracker.reset()
    start = time.monotonic()

    novel = fetch_novel_by_id(gutenberg_id)
    chapters = novel["chapters"][:CHAPTER_CAP]
    print(
        f"  Fetched: {novel['metadata']['title']!r} by {novel['metadata']['author']} "
        f"({len(novel['chapters'])} chapters total, using first {len(chapters)})"
    )

    client = anthropic.Anthropic()
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

        try:
            summary.append(process_one(gutenberg_id, title))
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
