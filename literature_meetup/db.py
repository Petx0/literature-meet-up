import os

import psycopg2
import psycopg2.extras


def get_connection():
    """Opens a new connection using DATABASE_URL from the environment."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


def save_book(conn, novel: dict, pipeline_result: dict) -> str:
    """Writes one fully-processed book to the database in a single
    transaction, per Addendum 2's "single batch write" principle: every row
    inserted here is already in its final form (post extraction,
    reconstruction, setting estimation, cleanup, dedup, and geocoding). On
    any error the whole transaction is rolled back - there is no partial
    persistence, matching the rest of this pipeline's design.

    `novel` is the dict from literature_meetup.fetch_novel (metadata +
    raw_gutendex_metadata). `pipeline_result` is the dict from
    literature_meetup.process_book (story_state, events, locations,
    book_metadata). Returns the new book's UUID (as a string).
    """
    metadata = novel["metadata"]
    estimated_setting = pipeline_result["book_metadata"]["estimated_setting"]

    try:
        with conn.cursor() as cur:
            book_id = _insert_book(
                cur,
                metadata,
                novel.get("raw_gutendex_metadata"),
                estimated_setting,
                pipeline_result.get("chapters_processed"),
            )
            character_id_map = _insert_characters(cur, book_id, pipeline_result["story_state"]["characters"])
            location_id_map = _insert_locations(cur, book_id, pipeline_result["locations"])
            _insert_events(cur, book_id, pipeline_result["events"], character_id_map, location_id_map)
            _insert_duplicate_flags(
                cur, book_id, character_id_map, pipeline_result.get("unmerged_duplicate_groups", [])
            )
        conn.commit()
        return book_id
    except Exception:
        conn.rollback()
        raise


def _insert_book(
    cur, metadata: dict, raw_gutendex_metadata, estimated_setting: dict, chapters_processed: int | None
) -> str:
    cur.execute(
        """
        insert into books (
            gutenberg_id, title, author, gutendex_metadata, chapters_processed,
            estimated_year_range_start, estimated_year_range_end,
            estimated_setting_confidence, estimated_setting_basis, estimated_setting_method
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            metadata.get("gutenberg_id"),
            metadata.get("title"),
            metadata.get("author"),
            psycopg2.extras.Json(raw_gutendex_metadata) if raw_gutendex_metadata is not None else None,
            chapters_processed,
            estimated_setting.get("year_range_start"),
            estimated_setting.get("year_range_end"),
            estimated_setting.get("confidence"),
            estimated_setting.get("basis"),
            estimated_setting.get("method"),
        ),
    )
    return cur.fetchone()[0]


def _insert_characters(cur, book_id: str, characters: list) -> dict:
    """Returns a map from the pipeline's own working character id (e.g.
    "char_fogg") to the database-generated UUID, needed to point events at
    the right row.
    """
    id_map = {}
    for character in characters:
        cur.execute(
            "insert into characters (book_id, canonical_name, aliases) values (%s, %s, %s) returning id",
            (book_id, character["canonical_name"], character.get("aliases") or []),
        )
        id_map[character["id"]] = cur.fetchone()[0]
    return id_map


def _insert_locations(cur, book_id: str, locations: list) -> dict:
    """Returns a map from the pipeline's own working location id (e.g.
    "loc_3") to the database-generated UUID, needed to point events at the
    right row.
    """
    id_map = {}
    for location in locations:
        hierarchy = location.get("hierarchy") or {}
        transit = location.get("transit") or {}
        transit_from = transit.get("from") or {}
        transit_to = transit.get("to") or {}

        cur.execute(
            """
            insert into locations (
                book_id, location_type, country, region, city, neighborhood, street,
                proximity, transit_from_country, transit_from_city, transit_to_country,
                transit_to_city, transport_mode, transport_detail, hierarchy_source, geocode_status
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                book_id,
                location.get("location_type"),
                hierarchy.get("country"),
                hierarchy.get("region"),
                hierarchy.get("city"),
                hierarchy.get("neighborhood"),
                hierarchy.get("street"),
                location.get("proximity"),
                transit_from.get("country"),
                transit_from.get("city"),
                transit_to.get("country"),
                transit_to.get("city"),
                transit.get("transport_mode"),
                transit.get("transport_detail"),
                location.get("source"),
                location.get("geocode_status", "skipped"),
            ),
        )
        id_map[location["location_id"]] = cur.fetchone()[0]
    return id_map


def _insert_events(cur, book_id: str, events: list, character_id_map: dict, location_id_map: dict) -> None:
    for event in events:
        time = event["time"]
        hierarchy = time.get("hierarchy") or {}
        sequence = event["sequence"]

        cur.execute(
            """
            insert into events (
                book_id, character_id, location_id, chapter,
                time_year_range_start, time_year_range_end, time_year, time_month, time_day,
                time_precision, time_source, narration_order, story_chronological_order,
                ordering_confidence, temporal_relation, evidence_quote, confidence
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                book_id,
                character_id_map[event["character_id"]],
                location_id_map[event["location_id"]],
                event["chapter"],
                hierarchy.get("year_range_start"),
                hierarchy.get("year_range_end"),
                hierarchy.get("year"),
                hierarchy.get("month"),
                hierarchy.get("day"),
                time.get("precision"),
                time.get("source"),
                sequence.get("narration_order"),
                sequence.get("story_chronological_order"),
                event.get("ordering_confidence"),
                event.get("temporal_relation"),
                event.get("evidence_quote"),
                event.get("confidence"),
            ),
        )


def _insert_duplicate_flags(cur, book_id: str, character_id_map: dict, unmerged_groups: list) -> None:
    """Persists the likely/uncertain character-duplicate groups dedupe_characters()
    didn't auto-merge, so they can be reviewed later (scripts/review_duplicates.py)
    instead of only ever being printed to console and lost.
    """
    for group in unmerged_groups:
        character_ids = [character_id_map[character_id] for character_id in group["character_ids"]]
        canonical_id = character_id_map[group["canonical_id"]]
        cur.execute(
            """
            insert into character_duplicate_flags (
                book_id, character_ids, canonical_id, confidence, reasoning
            ) values (%s, %s::uuid[], %s, %s, %s)
            """,
            (book_id, character_ids, canonical_id, group["confidence"], group["reasoning"]),
        )
