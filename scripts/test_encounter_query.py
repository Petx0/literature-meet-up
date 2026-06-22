"""Scratch script to build and validate the character-encounter SQL query
against the live Supabase data, per the encounter-query plan. Not part of
the core library - for iterating on the query shape before any app exists.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        key, _, value = line.strip().partition("=")
        if key:
            os.environ[key] = value

import psycopg2

LOCATION_LEVELS = ["country", "region", "city", "neighborhood"]

BASE_CTE = """
with location_points as (
    select
        id as location_id,
        'place' as point_role,
        country, region, city, neighborhood
    from locations
    where location_type != 'transit'

    union all

    select id, 'from', transit_from_country, null, transit_from_city, null
    from locations
    where location_type = 'transit'
      and (transit_from_country is not null or transit_from_city is not null)

    union all

    select id, 'to', transit_to_country, null, transit_to_city, null
    from locations
    where location_type = 'transit'
      and (transit_to_country is not null or transit_to_city is not null)
),
event_points as (
    select
        e.id as event_id,
        e.book_id,
        e.character_id,
        coalesce(e.time_year_range_start, e.time_year) as y_start,
        coalesce(e.time_year_range_end, e.time_year) as y_end,
        e.time_month,
        e.time_day,
        lp.location_id,
        lp.point_role,
        lower(trim(lp.country)) as country,
        lower(trim(lp.region)) as region,
        lower(trim(lp.city)) as city,
        lower(trim(lp.neighborhood)) as neighborhood
    from events e
    join location_points lp on lp.location_id = e.location_id
    where e.time_precision is not null
)
"""

SELECT_AND_JOIN = """
select distinct
    c1.canonical_name as character_a, b1.title as book_a_title,
    c2.canonical_name as character_b, b2.title as book_b_title,
    ep1.point_role as role_a, ep1.country as country_a, ep1.region as region_a,
    ep1.city as city_a, ep1.neighborhood as neighborhood_a,
    ep2.point_role as role_b, ep2.country as country_b, ep2.region as region_b,
    ep2.city as city_b, ep2.neighborhood as neighborhood_b,
    case when greatest(ep1.y_start, ep2.y_start) <= least(ep1.y_end, ep2.y_end)
         then greatest(ep1.y_start, ep2.y_start) end as overlap_year_start,
    case when greatest(ep1.y_start, ep2.y_start) <= least(ep1.y_end, ep2.y_end)
         then least(ep1.y_end, ep2.y_end) end as overlap_year_end
from event_points ep1
join event_points ep2 on ep1.book_id < ep2.book_id
join characters c1 on c1.id = ep1.character_id
join characters c2 on c2.id = ep2.character_id
join books b1 on b1.id = ep1.book_id
join books b2 on b2.id = ep2.book_id
where {time_condition}
  and {location_condition}
order by overlap_year_start
limit {limit}
"""


def time_condition(granularity: str) -> str:
    if granularity == "none":
        return "true"

    year_overlap = "ep1.y_start <= ep2.y_end and ep2.y_start <= ep1.y_end"
    if granularity == "year":
        return year_overlap
    if granularity == "decade":
        return (
            "floor(ep1.y_start / 10.0) <= floor(ep2.y_end / 10.0) "
            "and floor(ep2.y_start / 10.0) <= floor(ep1.y_end / 10.0)"
        )
    if granularity == "century":
        return (
            "floor(ep1.y_start / 100.0) <= floor(ep2.y_end / 100.0) "
            "and floor(ep2.y_start / 100.0) <= floor(ep1.y_end / 100.0)"
        )
    if granularity == "month":
        return f"{year_overlap} and (ep1.time_month is null or ep2.time_month is null or ep1.time_month = ep2.time_month)"
    if granularity == "day":
        month_cond = f"(ep1.time_month is null or ep2.time_month is null or ep1.time_month = ep2.time_month)"
        return f"{year_overlap} and {month_cond} and (ep1.time_day is null or ep2.time_day is null or ep1.time_day = ep2.time_day)"

    raise ValueError(f"Unknown time granularity: {granularity!r}")


def location_condition(granularity: str) -> str:
    if granularity == "none":
        return "true"
    if granularity not in LOCATION_LEVELS:
        raise ValueError(f"Unknown location granularity: {granularity!r}")

    idx = LOCATION_LEVELS.index(granularity)
    parts = [f"ep1.{granularity} is not null and ep2.{granularity} is not null and ep1.{granularity} = ep2.{granularity}"]
    for coarser in LOCATION_LEVELS[:idx]:
        parts.append(f"(ep1.{coarser} is null or ep2.{coarser} is null or ep1.{coarser} = ep2.{coarser})")
    return " and ".join(parts)


def build_query(time_granularity: str, location_granularity: str, limit: int = 20) -> str:
    return BASE_CTE + SELECT_AND_JOIN.format(
        time_condition=time_condition(time_granularity),
        location_condition=location_condition(location_granularity),
        limit=limit,
    )


def run(conn, time_granularity: str, location_granularity: str, limit: int = 20):
    sql = build_query(time_granularity, location_granularity, limit)
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    return columns, rows


def _place_label(record, side):
    for field in ("neighborhood", "city", "region", "country"):
        value = record[f"{field}_{side}"]
        if value is not None:
            return f"{field}={value}"
    return "(no location data)"


def print_results(label, columns, rows):
    print(f"\n=== {label}: {len(rows)} row(s) ===")
    for row in rows[:5]:
        record = dict(zip(columns, row))
        years = (
            f"{record['overlap_year_start']}-{record['overlap_year_end']}"
            if record["overlap_year_start"] is not None
            else "(no actual overlap - time filter off)"
        )
        print(
            f"  {record['character_a']} ({record['book_a_title']}) <-> "
            f"{record['character_b']} ({record['book_b_title']}) | "
            f"A: {record['role_a']} {_place_label(record, 'a')} | "
            f"B: {record['role_b']} {_place_label(record, 'b')} | "
            f"years {years}"
        )


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])

    combos = [
        ("year", "city"),
        ("decade", "country"),
        ("none", "city"),
        ("century", "none"),
        ("day", "neighborhood"),
    ]

    for time_g, loc_g in combos:
        columns, rows = run(conn, time_g, loc_g)
        print_results(f"time={time_g}, location={loc_g}", columns, rows)

    # Sanity check: count totals/same-book pairs without fetching the full row set.
    count_sql = BASE_CTE + """
        select
            count(*) as total,
            count(*) filter (where b1.title = b2.title) as same_book
        from event_points ep1
        join event_points ep2 on ep1.book_id < ep2.book_id
        join books b1 on b1.id = ep1.book_id
        join books b2 on b2.id = ep2.book_id
    """
    with conn.cursor() as cur:
        cur.execute(count_sql)
        total, same_book = cur.fetchone()
    print(f"\n=== Sanity check: total cross-book point-pairs (no filters): {total} ===")
    print(f"=== Sanity check: same-book pairs found: {same_book} (expect 0) ===")

    conn.close()


if __name__ == "__main__":
    main()
