from __future__ import annotations

TIME_GRANULARITIES = ("none", "century", "decade", "year", "month", "day")
LOCATION_LEVELS = ("country", "region", "city", "neighborhood")
LOCATION_GRANULARITIES = ("none",) + LOCATION_LEVELS

# Same two views as scripts/encounter_examples.sql - kept in sync by hand since
# this is the canonical source the web app runs against; the .sql file is the
# paste-into-Supabase copy for manual exploration.
ENSURE_VIEWS_SQL = """
create or replace view event_match_points as
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
)
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
where e.time_precision is not null;

create or replace view event_readable as
select
    e.id as event_id,
    e.book_id,
    b.title as book_title,
    c.canonical_name as character_name,
    case
        when l.location_type = 'transit' then
            'travelling from ' || coalesce(l.transit_from_city, l.transit_from_country, 'an unknown place')
            || ' to ' || coalesce(l.transit_to_city, l.transit_to_country, 'an unknown place')
            || coalesce(' by ' || replace(l.transport_mode::text, '_', ' '), '')
        else
            coalesce(
                nullif(
                    concat_ws(', ', l.neighborhood, l.city, l.region, l.country),
                    ''
                ),
                'an unspecified location'
            )
    end as readable_location,
    case e.time_precision
        when 'day' then trim(to_char(make_date(e.time_year, e.time_month, e.time_day), 'DD Month YYYY'))
        when 'month' then trim(to_char(make_date(e.time_year, e.time_month, 1), 'Month YYYY'))
        when 'year' then e.time_year::text
        when 'year_range' then
            (case when e.time_source = 'book_estimated' then 'estimated ' else '' end)
            || e.time_year_range_start || '-' || e.time_year_range_end
        else 'an unknown time'
    end as readable_time,
    e.evidence_quote
from events e
join books b on b.id = e.book_id
join characters c on c.id = e.character_id
join locations l on l.id = e.location_id;
"""

ENCOUNTER_QUERY_TEMPLATE = """
select
    r1.character_name as character_a, r1.book_title as book_a,
    r1.readable_location as location_a, r1.readable_time as time_a, r1.evidence_quote as evidence_a,
    r2.character_name as character_b, r2.book_title as book_b,
    r2.readable_location as location_b, r2.readable_time as time_b, r2.evidence_quote as evidence_b
from event_match_points p1
join event_match_points p2 on p1.book_id < p2.book_id
join event_readable r1 on r1.event_id = p1.event_id
join event_readable r2 on r2.event_id = p2.event_id
where {time_condition}
  and {location_condition}
order by random()
limit 1
"""


def ensure_views(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(ENSURE_VIEWS_SQL)
    conn.commit()


def _time_condition(granularity: str) -> str:
    if granularity == "none":
        return "true"

    year_overlap = "p1.y_start <= p2.y_end and p2.y_start <= p1.y_end"
    if granularity == "year":
        return year_overlap
    if granularity == "decade":
        return (
            "floor(p1.y_start / 10.0) <= floor(p2.y_end / 10.0) "
            "and floor(p2.y_start / 10.0) <= floor(p1.y_end / 10.0)"
        )
    if granularity == "century":
        return (
            "floor(p1.y_start / 100.0) <= floor(p2.y_end / 100.0) "
            "and floor(p2.y_start / 100.0) <= floor(p1.y_end / 100.0)"
        )
    if granularity == "month":
        return f"{year_overlap} and (p1.time_month is null or p2.time_month is null or p1.time_month = p2.time_month)"
    if granularity == "day":
        month_cond = "(p1.time_month is null or p2.time_month is null or p1.time_month = p2.time_month)"
        return f"{year_overlap} and {month_cond} and (p1.time_day is null or p2.time_day is null or p1.time_day = p2.time_day)"

    raise ValueError(f"Unknown time granularity: {granularity!r}")


def _location_condition(granularity: str) -> str:
    if granularity == "none":
        return "true"
    if granularity not in LOCATION_LEVELS:
        raise ValueError(f"Unknown location granularity: {granularity!r}")

    idx = LOCATION_LEVELS.index(granularity)
    parts = [f"p1.{granularity} is not null and p2.{granularity} is not null and p1.{granularity} = p2.{granularity}"]
    for coarser in LOCATION_LEVELS[:idx]:
        parts.append(f"(p1.{coarser} is null or p2.{coarser} is null or p1.{coarser} = p2.{coarser})")
    return " and ".join(parts)


def random_encounter(conn, time_granularity: str, location_granularity: str) -> dict | None:
    """Picks one random matching character-encounter for the given
    granularities, or None if no pair satisfies them. Raises ValueError for
    an unrecognized granularity (callers should validate against
    TIME_GRANULARITIES/LOCATION_GRANULARITIES before calling, e.g. to turn
    that into a clean 400 at an API boundary).
    """
    sql = ENCOUNTER_QUERY_TEMPLATE.format(
        time_condition=_time_condition(time_granularity),
        location_condition=_location_condition(location_granularity),
    )
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))
