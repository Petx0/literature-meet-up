import requests

GUTENDEX_BASE_URL = "https://gutendex.com/books"


class NovelNotFoundError(Exception):
    pass


MAX_SEARCH_PAGES = 3


def search_books(title: str, author: str) -> list[dict]:
    """Query Gutendex for books matching title and author.

    Gutendex orders results by relevance to the search terms, so the best
    matches are always on the early pages; a specific title+author rarely
    needs more than one. Capping pagination avoids many sequential requests
    for broad/ambiguous queries (common words, popular surnames).
    """
    books = []
    params = {"search": f"{title} {author}"}
    url = GUTENDEX_BASE_URL

    for _ in range(MAX_SEARCH_PAGES):
        if not url:
            break
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        books.extend(data["results"])
        url = data.get("next")
        params = None  # 'next' already contains the query string

    return books


def get_book_by_id(gutenberg_id: int) -> dict:
    """Fetches a single book directly by its Gutenberg id, bypassing title/
    author search entirely. Preferred over search_books when the exact id is
    already known (e.g. a curated test corpus) - search has been observed to
    miss matches on accented author names and similar title-matching quirks.
    """
    response = requests.get(f"{GUTENDEX_BASE_URL}/{gutenberg_id}", timeout=10)
    response.raise_for_status()
    return response.json()


def pick_best_edition(books: list[dict]) -> dict:
    """English-first, then most downloaded; falls back to most downloaded overall."""
    if not books:
        raise NovelNotFoundError("No matching books found on Gutendex.")

    english_books = [b for b in books if "en" in b.get("languages", [])]
    candidates = english_books if english_books else books

    return max(candidates, key=lambda b: b.get("download_count", 0))
