# Project Brief Addendum 4 — Geocoding Backfill

Extends `PROJECT_BRIEF.md`, `ADDENDUM_1_chronological_reconstruction.md`,
`ADDENDUM_2_pipeline_state_management.md`, and `ADDENDUM_3_location_dedup.md`. Read
after all four — assumes that context.

---

## Updated pipeline order

```
1. Extraction (chapter-by-chapter, in memory)
2. Reconstruction (whole book, in memory)
3. Cleanup — drop events missing date or location (in memory)
4. Location deduplication (in memory)
5. Geocoding backfill (in memory)   <-- this document
6. DB write — single batch
```

---

## Scope and governing principle

This step fills missing hierarchy levels (country/region/city/neighborhood/street) on
finalized, deduped `real`-type locations, using the OpenStreetMap Nominatim API.

**Explicit, deliberate scope decision: modern-day political geography only.** This tool
does NOT attempt period-accurate historical geography. A character placed in 1980s
Belgrade will be backfilled with whatever Nominatim returns today (e.g. modern Serbia),
not the historically accurate country at the time (Yugoslavia). This is an accepted,
known limitation, not a bug — the goal of this database is "where was this character,"
not a historically precise political atlas. Do not attempt to add year-aware or
historical-gazetteer logic; that was explicitly considered and rejected for this build.

**Governing principle for everything else: never fill anything we are not confident
about.** This step must be conservative by design — partial, uncertain, or best-guess
fills are worse than leaving a field null, because they would silently misrepresent
data as text-derived when it is actually a geocoder's guess. Every rule below exists to
enforce this.

---

## Source: OpenStreetMap Nominatim

- API: `https://nominatim.openstreetmap.org`
- No API key required; free to use.
- **Must send a descriptive `User-Agent` header** identifying this application —
  required by Nominatim's usage policy, requests without one may be blocked.
- **Rate limit: ~1 request/second** on the public instance. Backfilling must run as
  sequential, throttled calls — NOT parallelized — for a book's worth of locations.
  For heavier future use (many books, batch processing), self-hosting Nominatim or
  switching to a paid geocoding provider is the documented escalation path — not needed
  for current single-book, on-demand runs.
- **Use structured query parameters** (e.g. `city=`, `country=`) rather than free-text
  search wherever possible — structured queries reduce ambiguous or incorrect matches
  compared to free-text search against a bare string.

---

## What gets processed

Operates on the **deduped `locations` list** (output of Addendum 2), once per distinct
location record — not once per event. The same place should get the same backfilled
hierarchy regardless of which character or event references it.

| `location_type` | Action |
|---|---|
| `real` | Attempt backfill (see rules below) |
| `fictional` | Skip — geocoding a made-up place is meaningless |
| `ambiguous` | Skip — not enough information to look up with confidence |
| `transit` | Skip — transit records reference `from`/`to` place names directly; these are NOT run through geocoding backfill in this version. (Treated as plain extracted strings for now. Revisit later if transit `from`/`to` ever need their own hierarchy — explicitly out of scope for this pass.) |

For `real` locations: by this stage (post-cleanup), every such location has at least
one filled hierarchy level. Use the **deepest available filled field** as the lookup
key — e.g. if `city: "Bombay"` is the deepest filled field with everything above and
below null, geocode using `city=Bombay`.

---

## Acceptance criteria — when a result may be used to fill data

A geocode result may only be used to backfill hierarchy levels if ALL of the following
hold:

1. **Unambiguous match.** Either exactly one result is returned, or — if multiple
   results are returned — the top result has a clear margin over the next one using
   Nominatim's `importance` score. Do not simply take the first result from a list of
   similarly-scored candidates. If ambiguous, treat as unresolved (see below).

2. **Type consistency.** The matched result's `type`/`class` must be consistent with
   the hierarchy level we queried at. If we queried using the `city` field, the result
   must actually be classified as a city/town/place — not a street, neighborhood, or
   country that happens to share the name string. This guards against name collisions
   across unrelated places.

3. **Only fill levels ABOVE what the text already gave us.** Never overwrite a
   hierarchy field that the extraction step already populated, even if Nominatim's
   canonical name differs (e.g. text says "Bombay," Nominatim's canonical name is
   "Mumbai" — keep "Bombay" as extracted, do not replace it). Only use the geocode
   result to fill the NULL fields above the deepest already-filled level (e.g. fill
   `country`/`region` if `city` was given). Never invent `neighborhood` or `street`
   from a city-level (or higher) geocode result — geocoding a city cannot legitimately
   produce street-level detail, and a city-level match should never cause neighborhood/
   street fields to be filled.

If ANY of these checks fail, the location's hierarchy is left exactly as extracted —
no partial fill, no best-guess, no fallback to a lower-confidence result.

---

## Recording the outcome

Every location that goes through this step (i.e. every `real`-type location) gets a
`geocode_status` field recording what happened, so it's visible in the data which
locations were enriched vs. left as-extracted:

```json
"geocode_status": "resolved" | "unresolved" | "skipped"
```

- `"resolved"` — backfill was applied; a confident, type-consistent match was found and
  used to fill one or more null hierarchy levels.
- `"unresolved"` — backfill was attempted but no result cleared the acceptance criteria
  above; hierarchy left exactly as extracted.
- `"skipped"` — backfill was never attempted, because `location_type` was `fictional`,
  `ambiguous`, or `transit`.

This field should NOT be treated as a deletion or filtering criterion anywhere
downstream — `unresolved` and `skipped` locations are still valid, usable data (the
text-derived hierarchy is unaffected either way); this field is purely diagnostic/
informational about whether enrichment happened.

---

## Suggested implementation notes

- Cache geocode lookups within a single book-processing run (and ideally across runs,
  keyed by the exact query parameters used) to avoid re-querying Nominatim for the same
  place string repeatedly — likely to recur often within a single book (e.g. "London"
  may be the deepest-filled field on several distinct location records if dedup left
  them separate due to time non-overlap, per Addendum 2).
- Because of the 1 req/sec throttle, processing time for this step scales with the
  number of distinct `real` locations needing backfill, not the number of events —
  expect this step to be fast for most novels (location count is typically much smaller
  than event count).
- Log/print failures (network errors, timeouts) distinctly from `"unresolved"” —
  a failed API call is not the same thing as a confidently-determined non-match, and
  the two probably warrant different handling (e.g. retry-worthy vs. not).

---

## Still open

- Database schema (now unblocked — geocoding output shape is defined above; this can
  reasonably be the next design pass).
- Entity-duplication validation pass for characters (separate from location dedup;
  not yet designed).
- Transit `from`/`to` enrichment (explicitly deferred in this pass — see table above).
- End consumer / query interface.
