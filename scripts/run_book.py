"""Ad-hoc runner for the popularity-test batch: fetch -> process (capped at
N chapters) -> save to Supabase. Not part of the library; a throwaway
script for this manual test run.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key:
            os.environ[key] = value

import anthropic

from literature_meetup import fetch_novel, get_connection, process_book, save_book
from literature_meetup import usage_tracker

CHAPTER_CAP = 10


def main():
    title, author = sys.argv[1], sys.argv[2]

    usage_tracker.reset()

    novel = fetch_novel(title, author)
    chapters = novel["chapters"][:CHAPTER_CAP]
    print(f"Fetched: {novel['metadata']['title']!r} by {novel['metadata']['author']} "
          f"(gutenberg_id={novel['metadata']['gutenberg_id']}, {len(novel['chapters'])} chapters total, "
          f"using first {len(chapters)})")

    client = anthropic.Anthropic()
    result = process_book(client, chapters, metadata=novel["metadata"], book_id=str(novel["metadata"]["gutenberg_id"]))

    conn = get_connection()
    book_id = save_book(conn, novel, result)
    print(f"Saved book_id: {book_id}")

    cur = conn.cursor()
    cur.execute("select count(*) from characters where book_id = %s", (book_id,))
    print("characters:", cur.fetchone()[0])
    cur.execute("select count(*) from locations where book_id = %s", (book_id,))
    print("locations:", cur.fetchone()[0])
    cur.execute("select count(*) from events where book_id = %s", (book_id,))
    print("events:", cur.fetchone()[0])
    conn.close()

    cost_summary = usage_tracker.summary()
    print(f"API cost for this book: ${cost_summary['total_cost']:.4f}")
    for model, bucket in cost_summary["by_model"].items():
        print(
            f"  {model}: {bucket['calls']} call(s), "
            f"{bucket['input_tokens']} input tok, {bucket['output_tokens']} output tok, "
            f"${bucket['cost']:.4f}"
        )


if __name__ == "__main__":
    main()
