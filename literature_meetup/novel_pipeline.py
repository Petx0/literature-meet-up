from literature_meetup.gutendex_client import pick_best_edition, search_books
from literature_meetup.text_extractor import download_text, split_into_chapters, strip_boilerplate


def fetch_novel(title: str, author: str) -> dict:
    """Finds the most relevant Gutendex edition of a novel and returns it as
    structured metadata + chapters/paragraphs, ready for downstream parsing.
    """
    books = search_books(title, author)
    book = pick_best_edition(books)

    source_url, raw_text = download_text(book)
    clean_text = strip_boilerplate(raw_text)
    chapters = split_into_chapters(clean_text)

    book_authors = book.get("authors", [])
    authors = ", ".join(a["name"] for a in book_authors) or author
    first_author = book_authors[0] if book_authors else {}

    return {
        "metadata": {
            "title": book.get("title", title),
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
