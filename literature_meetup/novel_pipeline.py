from literature_meetup.gutendex_client import get_book_by_id, pick_best_edition, search_books
from literature_meetup.text_extractor import download_text, split_into_chapters, strip_boilerplate


def _build_novel(book: dict, fallback_title: str | None = None, fallback_author: str | None = None) -> dict:
    source_url, raw_text = download_text(book)
    clean_text = strip_boilerplate(raw_text)
    chapters = split_into_chapters(clean_text)

    book_authors = book.get("authors", [])
    authors = ", ".join(a["name"] for a in book_authors) or fallback_author
    first_author = book_authors[0] if book_authors else {}

    return {
        "metadata": {
            "title": book.get("title", fallback_title),
            "author": authors,
            "gutenberg_id": book["id"],
            "language": "en" if "en" in book.get("languages", []) else next(iter(book.get("languages", [])), None),
            "download_count": book.get("download_count"),
            "source_url": source_url,
            "author_birth_year": first_author.get("birth_year"),
            "author_death_year": first_author.get("death_year"),
        },
        "chapters": chapters,
        "raw_gutendex_metadata": book,
    }


def fetch_novel(title: str, author: str) -> dict:
    """Finds the most relevant Gutendex edition of a novel and returns it as
    structured metadata + chapters/paragraphs, ready for downstream parsing.
    """
    books = search_books(title, author)
    book = pick_best_edition(books)
    return _build_novel(book, title, author)


def fetch_novel_by_id(gutenberg_id: int) -> dict:
    """Same as fetch_novel, but fetches the exact Gutenberg id directly
    instead of going through title/author search - use this whenever the id
    is already known (e.g. a curated corpus), since search can miss matches
    on accented names or ambiguous titles.
    """
    book = get_book_by_id(gutenberg_id)
    return _build_novel(book)
