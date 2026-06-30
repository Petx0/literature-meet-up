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
    e.evidence_quote,
    l.location_type,
    l.country,
    l.region,
    l.city,
    l.transit_to_country,
    l.transit_to_city
from events e
join books b on b.id = e.book_id
join characters c on c.id = e.character_id
join locations l on l.id = e.location_id;
"""

COUNT_QUERY_TEMPLATE = """
select count(*)
from event_match_points p1
join event_match_points p2 on p1.book_id < p2.book_id
where {time_condition}
  and {location_condition}
"""

# Caps the candidate pool feeding the grouping/sort step in
# ENCOUNTER_QUERY_TEMPLATE below. Loose filters (e.g. no time or location
# filter at all) can produce millions of raw event-pairs; DISTINCT ON's
# required sort over that many rows exhausted the DB's temp disk space in
# practice. See random_encounter() for how this is applied as a cheap,
# sort-free Bernoulli filter rather than ORDER BY random() LIMIT N (the
# latter still requires fully sorting the unbounded set before taking the
# top N, which is exactly what caused the disk-full).
MAX_CANDIDATE_POOL = 20000

ENCOUNTER_QUERY_TEMPLATE = """
with raw_pairs as (
    select
        p1.character_id as character_a_id, r1.character_name as character_a, r1.book_title as book_a,
        r1.readable_location as location_a, r1.readable_time as time_a, r1.evidence_quote as evidence_a,
        r1.location_type as location_type_a, r1.country as country_a, r1.region as region_a, r1.city as city_a,
        r1.transit_to_country as transit_to_country_a, r1.transit_to_city as transit_to_city_a,
        p2.character_id as character_b_id, r2.character_name as character_b, r2.book_title as book_b,
        r2.readable_location as location_b, r2.readable_time as time_b, r2.evidence_quote as evidence_b,
        r2.location_type as location_type_b, r2.country as country_b, r2.region as region_b, r2.city as city_b,
        r2.transit_to_country as transit_to_country_b, r2.transit_to_city as transit_to_city_b
    from event_match_points p1
    join event_match_points p2 on p1.book_id < p2.book_id
    join event_readable r1 on r1.event_id = p1.event_id
    join event_readable r2 on r2.event_id = p2.event_id
    where {time_condition}
      and {location_condition}
      and {sample_condition}
),
grouped as (
    select distinct on (character_a_id, character_b_id, location_a, time_a, location_b, time_b)
        character_a, book_a, location_a, time_a, evidence_a,
        location_type_a, country_a, region_a, city_a, transit_to_country_a, transit_to_city_a,
        character_b, book_b, location_b, time_b, evidence_b,
        location_type_b, country_b, region_b, city_b, transit_to_country_b, transit_to_city_b,
        count(*) over (
            partition by character_a_id, character_b_id, location_a, time_a, location_b, time_b
        ) as support_count
    from raw_pairs
    order by character_a_id, character_b_id, location_a, time_a, location_b, time_b, random()
)
select * from grouped
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


def list_countries(conn) -> list[str]:
    """Distinct countries that have at least one *encounter* - a cross-book
    pair of events both in that country - not just countries that merely
    appear on some event. Ignores the time/location granularity controls
    (always checked at "same country" / no time filter) since this populates
    a dropdown shown before either is chosen; a country listed here may still
    return zero results under stricter granularities, but never under the
    most permissive ones - it's a floor, not a guarantee.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct p1.country
            from event_match_points p1
            join event_match_points p2
              on p1.book_id < p2.book_id and p1.country = p2.country
            where p1.country is not null
            order by p1.country
            """
        )
        return [row[0] for row in cur.fetchall()]


def random_encounter(conn, time_granularity: str, location_granularity: str, country: str | None = None) -> dict | None:
    """Picks one random matching character-encounter for the given
    granularities, or None if no pair satisfies them. Raises ValueError for
    an unrecognized granularity (callers should validate against
    TIME_GRANULARITIES/LOCATION_GRANULARITIES before calling, e.g. to turn
    that into a clean 400 at an API boundary).

    `country` (already lowercased/trimmed by the caller) restricts both sides
    of the encounter to that one country, independent of - and combinable
    with - location_granularity, which only controls how strictly the two
    sides' locations must match *each other*.

    Event-pairs are grouped by (character pair, displayed location, displayed
    time) before sampling - a character with many qualifying events would
    otherwise both dominate the random draw and show up as many near-duplicate
    "encounters". The returned dict's `support_count` is how many raw
    event-pairs collapsed into the one returned, as a rough confidence signal.

    The returned dict also carries raw, un-rendered location fields per side
    (`location_type_a/b`, `country_a/b`, `region_a/b`, `city_a/b`,
    `transit_to_country_a/b`, `transit_to_city_a/b`) alongside the existing
    human-readable `location_a/b` strings - these exist purely so callers
    (webapp/main.py) can feed a structured query into a geocoder without
    re-parsing `readable_location` text.
    """
    time_condition = _time_condition(time_granularity)
    location_condition = _location_condition(location_granularity)
    params: dict = {}
    if country is not None:
        location_condition += " and p1.country = %(country)s and p2.country = %(country)s"
        params["country"] = country

    with conn.cursor() as cur:
        cur.execute(
            COUNT_QUERY_TEMPLATE.format(time_condition=time_condition, location_condition=location_condition),
            params,
        )
        candidate_count = cur.fetchone()[0]

    if candidate_count > MAX_CANDIDATE_POOL:
        sample_condition = f"random() < {MAX_CANDIDATE_POOL / candidate_count}"
    else:
        sample_condition = "true"

    sql = ENCOUNTER_QUERY_TEMPLATE.format(
        time_condition=time_condition,
        location_condition=location_condition,
        sample_condition=sample_condition,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))
