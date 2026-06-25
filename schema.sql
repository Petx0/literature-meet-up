-- ============================================================================
-- Novel Character Location/Time Database — Schema
-- Target: Supabase (Postgres)
-- ============================================================================
-- Design principles (per project brief + addenda):
-- - No staging tables. Per Addendum 2, nothing is written until the in-memory
--   pipeline (extraction -> reconstruction -> book-setting estimation ->
--   cleanup -> dedup -> geocoding) has fully finished. Every row inserted
--   here is already final.
-- - Fixed-vocabulary fields are Postgres ENUMs for DB-level validation.
-- - Hierarchy fields are real columns (not buried in JSON) since filtering/
--   grouping by city, country, etc. is an expected query pattern.
-- - One row per book per processing run. Re-processing a book is a new book
--   row, not an update-in-place, keeping history simple (see note at bottom).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ENUM TYPES
-- ----------------------------------------------------------------------------

create type location_type_enum as enum ('real', 'fictional', 'ambiguous', 'transit');
create type proximity_enum as enum ('at', 'area');
create type transport_mode_enum as enum (
  'on_foot', 'animal', 'carriage', 'train', 'ship',
  'automobile', 'aircraft', 'spacecraft', 'magical', 'other'
);
create type geocode_status_enum as enum ('resolved', 'unresolved', 'skipped');

create type time_precision_enum as enum ('year_range', 'year', 'month', 'day');

-- time.source and location.source: three values per Addendum 5
-- ("book_estimated" only ever appears on time.source, never location.source,
-- but a single shared type keeps things simple — unused values are harmless).
create type provenance_source_enum as enum ('stated', 'inferred', 'book_estimated');

create type temporal_relation_enum as enum ('current', 'flashback', 'flash_forward', 'unclear');
create type presence_confidence_enum as enum ('explicit', 'inferred');
create type ordering_confidence_enum as enum ('certain', 'uncertain');
create type setting_confidence_enum as enum ('high', 'medium', 'low');
create type setting_method_enum as enum ('text_and_metadata', 'metadata_only');

-- ----------------------------------------------------------------------------
-- BOOKS
-- One row per processed book. Holds Gutendex metadata and the Addendum 5
-- book-level setting estimate (always stored, regardless of confidence —
-- see Addendum 5; only its USE to fill events is confidence-gated, not its
-- storage).
-- ----------------------------------------------------------------------------

create table books (
  id uuid primary key default gen_random_uuid(),

  gutenberg_id integer not null,                 -- Gutendex/Gutenberg ebook id, e.g. 103
  title text not null,
  author text,
  gutendex_metadata jsonb,                       -- raw Gutendex response, for reference/debugging
  chapters_processed integer,                    -- how many chapters were fed into process_book() for
                                                  -- this run; null for rows inserted before this column
                                                  -- existed. Lets a reprocessing script tell "already
                                                  -- ran on the full text" apart from "still truncated"
                                                  -- without guessing from how many chapters' events
                                                  -- survived cleanup (unreliable - cleanup legitimately
                                                  -- drops chapters with no usable date, and how many
                                                  -- varies a lot book to book).

  -- Addendum 5: book-level estimated setting
  estimated_year_range_start integer,
  estimated_year_range_end integer,
  estimated_setting_confidence setting_confidence_enum,
  estimated_setting_basis text,                  -- short paraphrase of reasoning
  estimated_setting_method setting_method_enum,

  processed_at timestamptz not null default now()
);

comment on column books.gutendex_metadata is
  'Raw metadata blob from Gutendex, kept for reference. Not used in queries directly.';
comment on column books.estimated_setting_confidence is
  'Per Addendum 5: this is stored for every book regardless of value. Only medium/high
   confidence estimates are ever used to fill event dates during cleanup — see events.';

-- ----------------------------------------------------------------------------
-- CHARACTERS
-- One row per distinct character per book (post entity-resolution during
-- extraction — see project brief). Aliases stored as a text array; no
-- separate join table needed at this scale.
-- ----------------------------------------------------------------------------

create table characters (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references books(id) on delete cascade,

  canonical_name text not null,
  aliases text[] not null default '{}',

  created_at timestamptz not null default now()
);

create index idx_characters_book on characters(book_id);

-- ----------------------------------------------------------------------------
-- LOCATIONS
-- One row per distinct location per book, AFTER dedup (Addendum 3) and
-- geocoding backfill (Addendum 4). Hierarchy fields are real columns.
-- Transit locations leave hierarchy null and populate the transit_* fields
-- instead (location_type = 'transit').
-- ----------------------------------------------------------------------------

create table locations (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references books(id) on delete cascade,

  location_type location_type_enum not null,

  -- hierarchy (null for transit-type locations; partially null otherwise,
  -- per the text — never fabricated beyond what extraction/geocoding support)
  country text,
  region text,
  city text,
  neighborhood text,
  street text,

  proximity proximity_enum,                      -- 'at' | 'area'; null for transit

  -- transit-only fields (populated only when location_type = 'transit')
  transit_from_country text,
  transit_from_city text,
  transit_to_country text,
  transit_to_city text,
  transport_mode transport_mode_enum,
  transport_detail text,

  -- provenance of the hierarchy fields as extracted (NOT geocoding provenance —
  -- this is the "source" field from the original event/location schema:
  -- was the deepest hierarchy level stated or inferred in the text)
  hierarchy_source provenance_source_enum,

  -- Addendum 4: geocoding backfill outcome
  geocode_status geocode_status_enum not null default 'skipped',

  created_at timestamptz not null default now(),

  -- a transit location must have at least one of from/to populated, and must
  -- NOT populate hierarchy fields; a non-transit location must populate
  -- hierarchy (per cleanup, at least one level) and must NOT populate transit
  -- fields. These two shapes are mutually exclusive per Addendum 2/3 design.
  constraint chk_transit_shape check (
    (location_type = 'transit' and (
      transit_from_country is not null or transit_from_city is not null or
      transit_to_country is not null or transit_to_city is not null
    ) and
      country is null and region is null and city is null and
      neighborhood is null and street is null
    )
    or
    (location_type != 'transit' and
      transit_from_country is null and transit_from_city is null and
      transit_to_country is null and transit_to_city is null and
      transport_mode is null and transport_detail is null
    )
  )
);

create index idx_locations_book on locations(book_id);
create index idx_locations_city on locations(city);
create index idx_locations_country on locations(country);

-- ----------------------------------------------------------------------------
-- EVENTS
-- The core table. One row per character per distinct location/time state,
-- per the project brief's "one event per character" decision. Only events
-- that survived cleanup (Addendum 1, modified by Addendum 5) ever reach this
-- table — there is no "incomplete" or staging row shape to support.
-- ----------------------------------------------------------------------------

create table events (
  id uuid primary key default gen_random_uuid(),     -- this IS the event_id referenced
                                                        -- throughout the addenda
  book_id uuid not null references books(id) on delete cascade,
  character_id uuid not null references characters(id) on delete cascade,
  location_id uuid not null references locations(id) on delete restrict,

  chapter integer not null,

  -- time
  time_year_range_start integer,
  time_year_range_end integer,
  time_year integer,
  time_month integer,
  time_day integer,
  time_precision time_precision_enum,
  time_source provenance_source_enum not null,        -- 'stated' | 'inferred' | 'book_estimated'

  -- sequence
  narration_order integer not null,
  story_chronological_order integer,                   -- null unless reconstruction (Addendum 1)
                                                          -- produced a value; permanently null for
                                                          -- events whose only date came from
                                                          -- book_estimated (Addendum 5)
  ordering_confidence ordering_confidence_enum,         -- null unless reconstruction ran on this event

  temporal_relation temporal_relation_enum not null,

  evidence_quote text not null,                         -- paraphrase, never verbatim (copyright)
  confidence presence_confidence_enum not null,         -- presence-confidence, distinct from time_source

  created_at timestamptz not null default now()
);

create index idx_events_book on events(book_id);
create index idx_events_character on events(character_id);
create index idx_events_location on events(location_id);
create index idx_events_narration_order on events(book_id, narration_order);
create index idx_events_chrono_order on events(book_id, story_chronological_order);

comment on column events.confidence is
  'Presence-confidence: is the character''s presence at this location actually
   confirmed by the text. Distinct from time_source/location hierarchy_source,
   which describe precision of WHEN/WHERE, not certainty of presence itself.';
comment on column events.story_chronological_order is
  'Null for: (a) events never run through reconstruction (no real date data), and
   (b) events whose only date is book_estimated (Addendum 5 — these intentionally
   never receive a chronological order, only a rough era).';

-- ----------------------------------------------------------------------------
-- CHARACTER DUPLICATE FLAGS
-- Per Addendum 7: only `certain`-confidence duplicate groups are auto-merged
-- at pipeline time. `likely`/`uncertain` groups are persisted here instead of
-- being printed and discarded, so they can actually be reviewed and acted on
-- (see scripts/review_duplicates.py) rather than vanishing with the terminal
-- output the moment a run finishes.
-- ----------------------------------------------------------------------------

create type duplicate_confidence_enum as enum ('likely', 'uncertain');
create type duplicate_flag_status_enum as enum ('pending', 'approved', 'rejected');

create table character_duplicate_flags (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references books(id) on delete cascade,

  character_ids uuid[] not null,        -- every character in the flagged group
  canonical_id uuid not null,           -- which one the model suggested as the survivor

  confidence duplicate_confidence_enum not null,
  reasoning text not null,

  status duplicate_flag_status_enum not null default 'pending',

  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index idx_duplicate_flags_book on character_duplicate_flags(book_id);
create index idx_duplicate_flags_status on character_duplicate_flags(status);

-- ============================================================================
-- NOTE ON RE-PROCESSING A BOOK
-- ============================================================================
-- This schema treats each pipeline run as producing a new `books` row (and
-- cascading characters/locations/events). Re-running the same Gutenberg book
-- creates a second, independent set of rows rather than updating the first.
-- This keeps the "write once, fully finished" principle (Addendum 2) simple —
-- no update/upsert logic needed anywhere. If comparing pipeline runs over
-- time becomes useful later, query by gutenberg_id + processed_at rather than
-- assuming one row per book. A uniqueness constraint on gutenberg_id was
-- deliberately NOT added, to keep re-processing/iteration friction-free during
-- development.
-- ============================================================================
