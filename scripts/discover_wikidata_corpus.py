"""One-off discovery tool, not part of the regular pipeline: finds novels that
already have a rich main-character list on Wikidata (P674), then cross-
references each one against Gutendex to see if it's actually available on
Project Gutenberg - inverting the usual direction (start from a book, hope
Wikidata covers it) since Wikidata's P674 coverage is rich but inconsistent
per-arbitrary-book (see literature_meetup/wikidata_characters.py).

Makes no Claude API calls and writes nothing to the database - purely prints
a candidate (gutenberg_id, title, author, target_characters) list, ready to
be reviewed and manually copied into scripts/run_test_corpus.py's CORPUS
(passing target_characters= through to process_book) once you're happy with it.

target_characters here is the top TOP_N by fetch_main_characters_ranked's
combined sitelink-count + English-pageviews signal, not the full raw P674
list - confirmed live that raw claim order doesn't track importance (a
central Count of Monte Cristo antagonist landed at position 17 of 33), and
that feeding a large untrimmed list into a short/early chapter sample dilutes
the target_characters cost-saving (measured ~25-32% on a tight 3-name list
vs only ~9% on the full 33-name list, on the same book). The ranking isn't
perfect either - see fetch_main_characters_ranked's docstring for its two
known, accepted gaps (QID collisions with real-world namesakes; characters
whose Wikipedia coverage skews to a non-English language losing the
pageviews signal entirely) - it's just better than the alternatives.

Usage:
    python scripts/discover_wikidata_corpus.py [min_characters] [limit] [top_n]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from literature_meetup.gutendex_client import NovelNotFoundError, pick_best_edition, search_books
from literature_meetup.wikidata_characters import fetch_main_characters_ranked, find_literary_works_with_characters

MIN_CHARACTERS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 40
TOP_N = int(sys.argv[3]) if len(sys.argv) > 3 else 8


def main():
    candidates = find_literary_works_with_characters(min_characters=MIN_CHARACTERS, limit=LIMIT)
    print(f"Found {len(candidates)} Wikidata literary works with >= {MIN_CHARACTERS} characters.\n")

    matches = []
    for candidate in candidates:
        title, author, qid = candidate["title"], candidate["author"], candidate["qid"]
        if not author:
            print(f"  SKIP {title!r} - no English author label on Wikidata, can't search Gutendex confidently.")
            continue

        try:
            books = search_books(title, author)
            edition = pick_best_edition(books)
        except NovelNotFoundError:
            print(f"  SKIP {title!r} by {author} - not found on Gutendex (likely not public domain).")
            continue

        characters = fetch_main_characters_ranked(qid, top_n=TOP_N)
        if not characters:
            print(f"  SKIP {title!r} - P674 count was {candidate['character_count']} but no labels resolved.")
            continue

        print(
            f"  MATCH gutenberg_id={edition['id']} {title!r} by {author} "
            f"({candidate['character_count']} characters): {characters}"
        )
        matches.append(
            {
                "gutenberg_id": edition["id"],
                "title": title,
                "author": author,
                "target_characters": characters,
            }
        )
        time.sleep(0.5)  # Wikidata rate-limits aggressively under back-to-back requests (confirmed live).

    print(f"\n=== {len(matches)} matched against Gutendex ===")
    for match in matches:
        print(
            f"    ({match['gutenberg_id']}, {match['title']!r}, "
            f"target_characters={match['target_characters']!r}),"
        )


if __name__ == "__main__":
    main()
