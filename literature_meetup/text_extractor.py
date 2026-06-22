import re

import requests

PLAIN_TEXT_MIME_PREFERENCE = [
    "text/plain; charset=utf-8",
    "text/plain; charset=us-ascii",
    "text/plain",
]

START_BOILERPLATE_PATTERN = re.compile(
    r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)
END_BOILERPLATE_PATTERN = re.compile(
    r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)
CHAPTER_HEADING_PATTERN = re.compile(
    r"^[ \t]*(chapter|part|book)\s+([ivxlcdm]+|\d+)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)

# Some Gutenberg editions number chapters with a bare roman numeral or digit
# plus an ALL-CAPS title and no "Chapter"/"Part"/"Book" keyword at all (e.g.
# "I. PLAYING PILGRIMS", "II. A MERRY CHRISTMAS" - observed in Little Women).
# Requiring an all-caps title (no IGNORECASE) is what keeps this from
# matching ordinary numbered-list prose, which is mixed-case.
STANDALONE_HEADING_PATTERN = re.compile(
    r"^[ \t]*([IVXLCDM]+|\d+)\.\s+[A-Z][A-Z0-9 ,.'-]*\r?$",
    re.MULTILINE,
)

# Some Gutenberg editions use bare, unnumbered ALL-CAPS chapter titles with no
# numeral at all (e.g. "STORY OF THE DOOR", "THE LAST NIGHT" - observed in
# Dr. Jekyll and Mr. Hyde). Requiring at least two words is what keeps this
# from matching short ALL-CAPS interjections in dialogue. Since there's no
# numeral here, the title text itself (lowercased) stands in for the
# "number" field everywhere else a heading's identity is needed (e.g. TOC
# detection), since it's exactly what repeats between TOC and real heading.
TITLE_ONLY_HEADING_PATTERN = re.compile(
    r"^[ \t]*([A-Z][A-Z'’.,-]*(?: [A-Z'’.,-]+)+)[ \t]*\r?$",
    re.MULTILINE,
)


def download_text(book: dict) -> tuple[str, str]:
    """Returns (source_url, raw_text) for the best available plain-text format."""
    formats = book.get("formats", {})

    url = next((formats[mime] for mime in PLAIN_TEXT_MIME_PREFERENCE if mime in formats), None)
    if url is None:
        url = next((link for mime, link in formats.items() if mime.startswith("text/plain")), None)
    if url is None:
        raise ValueError(f"No plain-text format available for book id={book.get('id')}.")

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return url, response.text


def strip_boilerplate(raw_text: str) -> str:
    """Removes the standard Project Gutenberg header/footer boilerplate."""
    start_match = START_BOILERPLATE_PATTERN.search(raw_text)
    end_match = END_BOILERPLATE_PATTERN.search(raw_text)

    start_idx = start_match.end() if start_match else 0
    end_idx = end_match.start() if end_match else len(raw_text)

    return raw_text[start_idx:end_idx].strip()


def _find_headings(text: str) -> list[dict]:
    """Tries the keyword-based pattern (Chapter/Part/Book + number) first;
    falls back to the bare-numeral pattern, then to the bare-title pattern,
    only if the previous tier found fewer than 2 matches - not enough to
    actually split a book into chapters, a sign this edition doesn't use
    that convention at all.
    """
    keyword_matches = [
        {"start": m.start(), "end": m.end(), "title": m.group(0).strip(), "number": m.group(2).lower()}
        for m in CHAPTER_HEADING_PATTERN.finditer(text)
    ]
    if len(keyword_matches) >= 2:
        return keyword_matches

    standalone_matches = [
        {"start": m.start(), "end": m.end(), "title": m.group(0).strip(), "number": m.group(1).lower()}
        for m in STANDALONE_HEADING_PATTERN.finditer(text)
    ]
    if len(standalone_matches) >= 2:
        return standalone_matches

    title_only_matches = [
        {"start": m.start(), "end": m.end(), "title": m.group(0).strip(), "number": m.group(1).strip().lower()}
        for m in TITLE_ONLY_HEADING_PATTERN.finditer(text)
    ]
    return title_only_matches if len(title_only_matches) >= 2 else keyword_matches


def split_into_chapters(clean_text: str) -> list[dict]:
    """Splits text into chapters by heading.

    Falls back to a single untitled chapter if no headings are found.
    """
    headings = _find_headings(clean_text)
    headings = _drop_table_of_contents(headings, clean_text)

    if not headings:
        paragraphs = _split_paragraphs(clean_text)
        return [{"title": None, "paragraphs": paragraphs}] if paragraphs else []

    chapters = []
    for i, heading in enumerate(headings):
        start = heading["end"]
        end = headings[i + 1]["start"] if i + 1 < len(headings) else len(clean_text)
        paragraphs = _split_paragraphs(clean_text[start:end])
        if paragraphs:
            chapters.append({"title": heading["title"], "paragraphs": paragraphs})

    return chapters


def _drop_table_of_contents(headings: list, text: str, max_toc_entry_chars: int = 500) -> list:
    """A table of contents lists every chapter heading once, immediately
    followed (later in the text) by the same headings again marking the real
    chapter bodies. A heading-sequence mirror alone isn't enough to tell that
    apart from two real volumes/parts that happen to share the same chapter
    numbering (e.g. two volumes each numbered I-XX) with no TOC at all, so
    also require that every entry in the candidate TOC prefix is followed by
    only a short stretch of text, the way TOC entries (not real chapter
    bodies) are.

    The repeat isn't assumed to span the *entire* list (numbers[:n/2] vs.
    numbers[n/2:]) - some Gutenberg files bundle unrelated extra content
    (other works by the same author, promotional excerpts) after the real
    chapters, which would throw off an exact whole-list split. Instead this
    searches for the longest prefix length k such that the first k headings
    repeat immediately afterward (numbers[:k] == numbers[k:2k]), trying
    larger k first.
    """
    numbers = [heading["number"] for heading in headings]
    n = len(numbers)

    for k in range(n // 2, 0, -1):
        if numbers[:k] != numbers[k : 2 * k]:
            continue
        # Only check gaps strictly within the candidate TOC prefix. The gap
        # after the *last* TOC entry runs into the real content (which may
        # include front matter like a preface or letters before chapter 1)
        # and isn't a useful signal either way.
        if all(headings[i + 1]["start"] - headings[i]["end"] <= max_toc_entry_chars for i in range(k - 1)):
            return headings[k:]

    return headings


def _split_paragraphs(text: str) -> list[str]:
    raw_paragraphs = re.split(r"\n\s*\n", text)
    return [" ".join(p.split()) for p in raw_paragraphs if p.strip()]
