from __future__ import annotations

import time
from datetime import date, timedelta
from urllib.parse import quote

import requests

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_DATA_URL = "https://www.wikidata.org/wiki/Special:EntityData"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
PAGEVIEWS_API_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents"

# Wikimedia's API/SPARQL endpoints 403 the default requests user-agent
# outright (confirmed live) - a descriptive UA is required, not just polite.
_HEADERS = {"User-Agent": "LiteratureMeetUp/1.0 (literature-meet-up cost-experiment research script)"}

# P674 = "characters" - notable characters appearing in a work. Populated
# deliberately by editors (unlike Gutendex's LoC subject headings, which only
# ever surface at most one title-level character) but inconsistently across
# the corpus - confirmed live to be rich for some classics (Around the World
# in Eighty Days, Great Expectations) and entirely empty for others (The
# Mayor of Casterbridge, Five Weeks in a Balloon). Treat as best-effort.
CHARACTERS_PROPERTY = "P674"

# Q7725634 = "literary work" - what novels on Wikidata are actually tagged
# with (not the narrower Q8261 "novel", which returns nothing for P674-having
# works when queried directly).
LITERARY_WORK_QID = "Q7725634"

_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = (10, 20, 40, 60)


def _get(url: str, **kwargs) -> requests.Response:
    """Wikidata's API rate-limits aggressively under repeated calls (confirmed
    live: a 429 mid-batch on the wbgetentities calls a discovery run makes one
    per candidate work) - retries with backoff on 429 specifically, mirroring
    this repo's existing transient-error pattern in cli_backend.py.
    """
    headers = {**_HEADERS, **kwargs.pop("headers", {})}
    timeout = kwargs.pop("timeout", 10)
    for attempt in range(_MAX_ATTEMPTS):
        response = requests.get(url, headers=headers, timeout=timeout, **kwargs)
        if response.status_code != 429:
            return response
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_SECONDS[attempt])
    return response


def find_novel_entity(title: str, author: str | None = None) -> str | None:
    """Searches Wikidata for the literary-work entity matching title/author,
    returning its QID, or None if no confident match is found.

    Disambiguates by description rather than label alone, since Wikidata
    routinely has multiple items sharing a title (film/TV adaptations,
    unrelated works, translated editions) - confirmed live for "Around the
    World in Eighty Days" (novel/1873 edition/1919 film all share the exact
    label). Requires at least one name token from `author` to also appear in
    the description when given, to avoid matching a same-titled work by
    someone else - checks every token rather than assuming name order, since
    metadata["author"] (novel_pipeline.py, from Gutendex) is "Lastname,
    Firstname" while a SPARQL-sourced author (wikidata_characters.py's own
    find_literary_works_with_characters) is "Firstname Lastname".
    """
    response = _get(
        WIKIDATA_API_URL,
        params={"action": "wbsearchentities", "search": title, "language": "en", "format": "json", "limit": 10},
    )
    response.raise_for_status()
    results = response.json().get("search", [])

    author_tokens = [token.strip(",").lower() for token in author.split()] if author else []
    author_tokens = [token for token in author_tokens if len(token) > 2]  # skip initials/particles
    for result in results:
        description = (result.get("description") or "").lower()
        if ("novel" in description or "literary work" in description) and (
            not author_tokens or any(token in description for token in author_tokens)
        ):
            return result["id"]
    return None


def _fetch_character_qids(qid: str) -> list[str]:
    """Reads the raw P674 claims off a Wikidata literary-work entity, in
    claim order - confirmed live to NOT track narrative importance (on The
    Count of Monte Cristo, Gerard de Villefort, one of the four central
    antagonists, sits at position 17 of 33, behind clearly minor figures
    like Ali Pasha and Louis Dantès) - see fetch_main_characters_ranked for
    a better-than-claim-order ordering.
    """
    response = _get(f"{WIKIDATA_ENTITY_DATA_URL}/{qid}.json")
    response.raise_for_status()
    entity = response.json()["entities"][qid]
    claims = entity.get("claims", {}).get(CHARACTERS_PROPERTY, [])
    return [claim["mainsnak"]["datavalue"]["value"]["id"] for claim in claims if claim["mainsnak"].get("datavalue")]


def _fetch_entities_batched(qids: list[str], props: str) -> dict:
    """wbgetentities caps at 50 ids per request - some literary works (The
    Divine Comedy: 173 characters) blow well past that, so batch.
    """
    entities: dict = {}
    batch_size = 50
    for i in range(0, len(qids), batch_size):
        batch = qids[i : i + batch_size]
        response = _get(
            WIKIDATA_API_URL,
            params={"action": "wbgetentities", "ids": "|".join(batch), "props": props, "languages": "en", "format": "json"},
        )
        response.raise_for_status()
        entities.update(response.json()["entities"])
        time.sleep(0.5)
    return entities


def _annual_range() -> tuple[str, str]:
    """Rolling last-12-months window ending a couple of days ago, since
    Wikimedia's pageview pipeline lags real-time by a day or two.
    """
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=365)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _fetch_annual_pageviews(article_title: str) -> int:
    """Sums the last ~12 months of English Wikipedia pageviews for one
    article - the finer-grained secondary signal underneath sitelink count,
    which has poor resolution below the handful of genuinely
    multi-language-famous characters (confirmed live: on The Count of Monte
    Cristo, every character past the top 5 ties at exactly 1 sitelink).
    Returns 0 if the article has no pageview data (including a freshly-
    created or very obscure article).
    """
    start, end = _annual_range()
    encoded_title = quote(article_title.replace(" ", "_"), safe="")
    response = _get(f"{PAGEVIEWS_API_URL}/{encoded_title}/monthly/{start}/{end}")
    if response.status_code == 404:
        return 0
    response.raise_for_status()
    return sum(item["views"] for item in response.json().get("items", []))


def fetch_main_characters(qid: str) -> list[str]:
    """Reads the P674 claims off a Wikidata literary-work entity and resolves
    them to English labels, in raw claim order. Returns [] if the property
    isn't populated - callers must treat this as best-effort, not guaranteed
    (see CHARACTERS_PROPERTY docstring above). Prefer
    fetch_main_characters_ranked when you want only the most important N,
    not the full raw list.

    A wrong or oddly-labeled entry here (observed live: one character legitimately
    tagged as a "fictional human" but with an unexpected label) is low-risk by
    construction - extraction's entity resolution only ever matches by name, so
    a name that doesn't appear in the text just produces zero events for it.
    """
    character_qids = _fetch_character_qids(qid)
    if not character_qids:
        return []

    entities = _fetch_entities_batched(character_qids, props="labels")
    names = []
    for character_qid in character_qids:
        label = entities.get(character_qid, {}).get("labels", {}).get("en", {}).get("value")
        if label:
            names.append(label)
    return names


def fetch_main_characters_ranked(qid: str, top_n: int | None = None) -> list[str]:
    """Ranks a literary work's P674 characters by importance using two free
    signals, combined per the recommended strategy: Wikidata sitelink count
    (across all language editions) as a coarse first-pass importance proxy,
    then English Wikipedia annual pageviews as a finer-grained secondary
    signal to break the many ties sitelink count alone leaves (most named-
    but-non-iconic characters only ever have a single Wikipedia article, so
    they're indistinguishable by sitelink count alone). Sorts by
    (sitelink_count, pageviews) descending and returns the top_n names (or
    every name if top_n is None).

    Two known, unfixed limitations - documented rather than special-cased,
    since this is a cost-saving heuristic (see analyze_pipeline.py's
    target_characters), not something that needs to be exact:
    - Sitelink count can be wildly inflated when a character's Wikidata item
      is shared with an unrelated real-world namesake. Confirmed live: "Ali
      Pasha" topped Monte Cristo's sitelink count at 41 because that QID is
      actually the real historical Ali Pasha of Yanina (briefly referenced
      as backstory), not a Monte-Cristo-specific item.
    - Pageviews are only fetched when an enwiki sitelink exists. A character
      whose primary Wikipedia coverage is in another language gets
      pageviews=0 and is ranked on sitelink count alone, which can underrate
      a genuinely important character. Confirmed live: Gerard de Villefort's
      only sitelink is to Dutch Wikipedia, not English.
    """
    character_qids = _fetch_character_qids(qid)
    if not character_qids:
        return []

    entities = _fetch_entities_batched(character_qids, props="labels|sitelinks")

    candidates = []
    for character_qid in character_qids:
        entity = entities.get(character_qid, {})
        label = entity.get("labels", {}).get("en", {}).get("value")
        if not label:
            continue  # no English name to match against the (English) extracted text
        sitelinks = entity.get("sitelinks", {})
        enwiki_title = sitelinks.get("enwiki", {}).get("title")
        pageviews = _fetch_annual_pageviews(enwiki_title) if enwiki_title else 0
        if enwiki_title:
            time.sleep(1.0)
        candidates.append((len(sitelinks), pageviews, label))

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    names = [label for _, _, label in candidates]
    return names[:top_n] if top_n else names


def discover_target_characters(title: str, author: str | None, top_n: int) -> list[str] | None:
    """Per-book auto-discovery: looks up one specific book on Wikidata and
    returns its ranked main-character list, for pipeline.process_book's
    TARGET_CHARACTERS_AUTO_DISCOVER (see model_config.py) - distinct from
    find_literary_works_with_characters's bulk SPARQL search for *new*
    candidate books (scripts/discover_wikidata_corpus.py).

    Returns None - not [] - when no confident Wikidata match is found or no
    characters resolve, so callers can log "couldn't auto-discover" instead
    of silently treating a real lookup failure the same as a deliberate
    empty-cast lookup. Either way the caller falls back to unrestricted
    extraction; this never raises for a missing/uncovered book.
    """
    qid = find_novel_entity(title, author)
    if qid is None:
        return None
    characters = fetch_main_characters_ranked(qid, top_n=top_n)
    return characters or None


def find_literary_works_with_characters(min_characters: int = 3, limit: int = 100) -> list[dict]:
    """Queries Wikidata directly for literary works that already have a rich
    P674 character list, instead of starting from an arbitrary book and
    hoping it's covered - the inverted approach this module exists for.
    Confirmed live to surface real classics immediately (Pride and
    Prejudice: 38 characters, The Count of Monte Cristo: 33).

    Returns [{"qid", "title", "author", "character_count"}], sorted by
    character_count descending. author may be None (not every work has a
    P50 claim, or the author's label isn't in English) - callers must handle
    that when cross-referencing against Gutendex.
    """
    query = f"""
    SELECT ?novel ?novelLabel ?authorLabel (COUNT(?character) AS ?charCount) WHERE {{
      ?novel wdt:P31 wd:{LITERARY_WORK_QID} .
      ?novel wdt:P674 ?character .
      ?novel rdfs:label ?novelLabel . FILTER(LANG(?novelLabel) = "en")
      OPTIONAL {{
        ?novel wdt:P50 ?author .
        ?author rdfs:label ?authorLabel . FILTER(LANG(?authorLabel) = "en")
      }}
    }}
    GROUP BY ?novel ?novelLabel ?authorLabel
    HAVING (COUNT(?character) >= {min_characters})
    ORDER BY DESC(?charCount)
    LIMIT {limit}
    """
    response = _get(
        WIKIDATA_SPARQL_URL,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=60,
    )
    response.raise_for_status()
    bindings = response.json()["results"]["bindings"]

    results = []
    for binding in bindings:
        qid = binding["novel"]["value"].rsplit("/", 1)[-1]
        results.append(
            {
                "qid": qid,
                "title": binding["novelLabel"]["value"],
                "author": binding.get("authorLabel", {}).get("value"),
                "character_count": int(binding["charCount"]["value"]),
            }
        )
    return results
