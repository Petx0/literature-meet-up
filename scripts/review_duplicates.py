"""Review and resolve character_duplicate_flags rows - the likely/uncertain
duplicate-character groups the pipeline flagged but didn't auto-merge
(only `certain`-confidence groups are merged automatically, per Addendum 7).

Usage:
    python scripts/review_duplicates.py list
    python scripts/review_duplicates.py approve <flag_id>
    python scripts/review_duplicates.py reject <flag_id>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key and not line.startswith("#"):
            os.environ[key] = value

from literature_meetup import get_connection


def _parse_uuid_array(raw: str) -> list[str]:
    """psycopg2 returns a uuid[] column as a raw Postgres array-literal
    string ("{a,b,c}"), not a parsed Python list, since this project never
    registers a uuid typecaster (db.py treats every uuid column as a plain
    str elsewhere, by convention). UUIDs never contain ',' or braces, so a
    plain strip+split is safe here without needing a real array parser.
    """
    return raw.strip("{}").split(",") if raw else []


def list_pending(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select f.id, b.title, f.character_ids, f.canonical_id, f.confidence, f.reasoning
            from character_duplicate_flags f
            join books b on b.id = f.book_id
            where f.status = 'pending'
            order by f.created_at
            """
        )
        flags = cur.fetchall()

    if not flags:
        print("No pending duplicate flags.")
        return

    for flag_id, book_title, character_ids, canonical_id, confidence, reasoning in flags:
        character_ids = _parse_uuid_array(character_ids)
        with conn.cursor() as cur:
            cur.execute(
                "select id, canonical_name, aliases from characters where id = any(%s::uuid[])",
                (character_ids,),
            )
            characters = {row[0]: {"name": row[1], "aliases": row[2]} for row in cur.fetchall()}

        print(f"\n=== Flag {flag_id} ({book_title}) [{confidence}] ===")
        for character_id in character_ids:
            character = characters.get(character_id, {"name": "?", "aliases": []})
            marker = " (suggested canonical)" if character_id == canonical_id else ""
            print(f"  {character_id}: {character['name']} {character['aliases']}{marker}")
        print(f"  Reasoning: {reasoning}")


def approve(conn, flag_id: str) -> None:
    """Merges the flagged group: unions aliases into the canonical character,
    repoints every event from the non-canonical characters to it, then deletes
    the now-unreferenced non-canonical character rows. Repointing events MUST
    happen before deleting characters - events.character_id cascades on
    delete, so deleting first would silently destroy those events.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select character_ids, canonical_id from character_duplicate_flags where id = %s and status = 'pending'",
            (flag_id,),
        )
        row = cur.fetchone()
        if row is None:
            print(f"No pending flag with id {flag_id}.")
            return
        character_ids, canonical_id = row
        character_ids = _parse_uuid_array(character_ids)
        non_canonical_ids = [cid for cid in character_ids if cid != canonical_id]

        cur.execute("select canonical_name, aliases from characters where id = any(%s::uuid[])", (character_ids,))
        names_and_aliases = cur.fetchall()
        merged_aliases = set()
        for name, aliases in names_and_aliases:
            merged_aliases.add(name)
            merged_aliases.update(aliases or [])
        cur.execute("select canonical_name from characters where id = %s", (canonical_id,))
        merged_aliases.discard(cur.fetchone()[0])

        cur.execute(
            "update characters set aliases = %s where id = %s",
            (sorted(merged_aliases), canonical_id),
        )
        cur.execute(
            "update events set character_id = %s where character_id = any(%s::uuid[])",
            (canonical_id, non_canonical_ids),
        )
        cur.execute("delete from characters where id = any(%s::uuid[])", (non_canonical_ids,))
        cur.execute(
            "update character_duplicate_flags set status = 'approved', resolved_at = now() where id = %s",
            (flag_id,),
        )
    conn.commit()
    print(f"Approved flag {flag_id}: merged {non_canonical_ids} into {canonical_id}.")


def reject(conn, flag_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update character_duplicate_flags set status = 'rejected', resolved_at = now() "
            "where id = %s and status = 'pending'",
            (flag_id,),
        )
        if cur.rowcount == 0:
            print(f"No pending flag with id {flag_id}.")
            conn.rollback()
            return
    conn.commit()
    print(f"Rejected flag {flag_id}.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    conn = get_connection()
    try:
        command = sys.argv[1]
        if command == "list":
            list_pending(conn)
        elif command == "approve" and len(sys.argv) == 3:
            approve(conn, sys.argv[2])
        elif command == "reject" and len(sys.argv) == 3:
            reject(conn, sys.argv[2])
        else:
            print(__doc__)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
