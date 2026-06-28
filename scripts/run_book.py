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
from literature_meetup import model_config, usage_tracker

# No per-book chapter cap in production - process every chapter Gutendex
# returns. MAX_CHAPTERS is a separate guard: refuse to run a novel longer
# than this many chapters without an explicit override, since extraction
# cost scales linearly with chapter count and a single very long novel
# (e.g. Les Miserables: 365 chapters) could rack up unexpected cost on a
# single manual invocation. Override with MAX_CHAPTERS=<n> in the
# environment, or pass --force as a third CLI arg, to process it anyway.
MAX_CHAPTERS = int(os.environ.get("MAX_CHAPTERS", "120"))


def main():
    title, author = sys.argv[1], sys.argv[2]
    force = len(sys.argv) > 3 and sys.argv[3] == "--force"

    usage_tracker.reset()

    novel = fetch_novel(title, author)
    chapters = novel["chapters"]
    print(f"Fetched: {novel['metadata']['title']!r} by {novel['metadata']['author']} "
          f"(gutenberg_id={novel['metadata']['gutenberg_id']}, {len(chapters)} chapters)")

    if len(chapters) > MAX_CHAPTERS and not force:
        print(
            f"Refusing to process: {len(chapters)} chapters exceeds MAX_CHAPTERS={MAX_CHAPTERS}. "
            "Re-run with a third argument --force, or set MAX_CHAPTERS in the environment, to proceed anyway."
        )
        return

    client = anthropic.Anthropic() if model_config.LLM_BACKEND == "api" else None
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
    if model_config.LLM_BACKEND == "cli":
        print(
            f"Subscription usage (no per-token billing); "
            f"equivalent API cost would have been ~${cost_summary['equivalent_api_cost']:.4f}"
        )
    else:
        print(f"API cost for this book: ${cost_summary['total_cost']:.4f}")
    for model, bucket in cost_summary["by_model"].items():
        print(
            f"  {model}: {bucket['calls']} call(s), "
            f"{bucket['input_tokens']} input tok, "
            f"{bucket['cache_creation_input_tokens']} cache-write tok, "
            f"{bucket['cache_read_input_tokens']} cache-read tok, "
            f"{bucket['output_tokens']} output tok, "
            f"${bucket['cost']:.4f}"
        )


if __name__ == "__main__":
    main()
