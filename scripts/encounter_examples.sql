-- ============================================================================
-- Character-Encounter Queries — paste-able examples for the Supabase SQL editor
-- ============================================================================
-- Run the SETUP block once (creates two reusable views). Then run any of the
-- EXAMPLE blocks below, independently, as many times as you like. Each
-- example is self-contained - just change the granularity comments.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- SETUP (run once)
-- ----------------------------------------------------------------------------

-- event_match_points: one row per event per comparable "point". Non-transit
-- locations get one point; transit locations get up to two (their `from` and
-- `to` endpoints), since a journey touches two places. This is the shape used
-- to actually perform the time/location overlap matching.
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


-- event_readable: one row per event with human-readable name/location/time
-- labels, for display only (not used for matching - see event_match_points).
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


-- ----------------------------------------------------------------------------
-- EXAMPLE 1: same city + same year (a practical, moderately strict combo)
-- ----------------------------------------------------------------------------
select distinct
    r1.character_name as character_a, r1.book_title as book_a, r1.readable_location as location_a, r1.readable_time as time_a, r1.evidence_quote as evidence_a,
    r2.character_name as character_b, r2.book_title as book_b, r2.readable_location as location_b, r2.readable_time as time_b, r2.evidence_quote as evidence_b
from event_match_points p1
join event_match_points p2 on p1.book_id < p2.book_id
join event_readable r1 on r1.event_id = p1.event_id
join event_readable r2 on r2.event_id = p2.event_id
where
    -- same year (range-overlap, generous toward book-estimated ranges)
    p1.y_start <= p2.y_end and p2.y_start <= p1.y_end
    -- same city (and country must agree too, if both happen to specify it)
    and p1.city is not null and p2.city is not null and p1.city = p2.city
    and (p1.country is null or p2.country is null or p1.country = p2.country)
order by r1.book_title, r2.book_title
limit 25;


-- ----------------------------------------------------------------------------
-- EXAMPLE 2: same country + same decade (broader - more results expected)
-- ----------------------------------------------------------------------------
select distinct
    r1.character_name as character_a, r1.book_title as book_a, r1.readable_location as location_a, r1.readable_time as time_a, r1.evidence_quote as evidence_a,
    r2.character_name as character_b, r2.book_title as book_b, r2.readable_location as location_b, r2.readable_time as time_b, r2.evidence_quote as evidence_b
from event_match_points p1
join event_match_points p2 on p1.book_id < p2.book_id
join event_readable r1 on r1.event_id = p1.event_id
join event_readable r2 on r2.event_id = p2.event_id
where
    -- same decade (10-year buckets, range-overlap)
    floor(p1.y_start / 10.0) <= floor(p2.y_end / 10.0) and floor(p2.y_start / 10.0) <= floor(p1.y_end / 10.0)
    -- same country
    and p1.country is not null and p2.country is not null and p1.country = p2.country
order by r1.book_title, r2.book_title
limit 25;


-- ----------------------------------------------------------------------------
-- EXAMPLE 3: same neighborhood + same month (strict - few or zero results
-- expected, since very few events have stated month/day precision at all;
-- this demonstrates the "generous" wildcard behavior: events with no month
-- data don't get excluded, they just don't add evidence either way)
-- ----------------------------------------------------------------------------
select distinct
    r1.character_name as character_a, r1.book_title as book_a, r1.readable_location as location_a, r1.readable_time as time_a, r1.evidence_quote as evidence_a,
    r2.character_name as character_b, r2.book_title as book_b, r2.readable_location as location_b, r2.readable_time as time_b, r2.evidence_quote as evidence_b
from event_match_points p1
join event_match_points p2 on p1.book_id < p2.book_id
join event_readable r1 on r1.event_id = p1.event_id
join event_readable r2 on r2.event_id = p2.event_id
where
    -- same year and same month-or-unknown
    p1.y_start <= p2.y_end and p2.y_start <= p1.y_end
    and (p1.time_month is null or p2.time_month is null or p1.time_month = p2.time_month)
    -- same neighborhood (forces city/region/country to agree too, where known)
    and p1.neighborhood is not null and p2.neighborhood is not null and p1.neighborhood = p2.neighborhood
    and (p1.city is null or p2.city is null or p1.city = p2.city)
    and (p1.region is null or p2.region is null or p1.region = p2.region)
    and (p1.country is null or p2.country is null or p1.country = p2.country)
order by r1.book_title, r2.book_title
limit 25;
