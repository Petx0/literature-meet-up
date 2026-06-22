# Project Brief Addendum 3 — Location Deduplication

Extends `PROJECT_BRIEF.md`, `ADDENDUM_1_chronological_reconstruction.md`, and
`ADDENDUM_2_pipeline_state_management.md`. Read after all three — assumes that context.

---

## Updated pipeline order

```
1. Extraction (chapter-by-chapter, in memory)
2. Reconstruction (whole book, in memory)
3. Cleanup — drop events missing date or location (in memory)
4. Location deduplication (in memory)   <-- this document
5. Geocoding backfill (in memory)        <-- next addendum, not yet designed
6. DB write — single batch
```

Dedup runs BEFORE geocoding: cheaper to collapse refinements using only what the text
gave you (string/hierarchy matching) before spending API calls/lookups backfilling a
larger, non-deduplicated set.

---

## Problem being solved

The same real-world place can be extracted at different specificity across different
events for the same character — e.g. "London" (city only) in one event and "Saville
Row, London" (city + street) in another. These should not always become two separate
location entries. But — critically — they should ONLY collapse into one when both of
these hold:

1. **Location nests** — one event's hierarchy is a strict refinement of the other's.
2. **Time does not conflict** — same character, and the time fields are compatible
   (not contradictory) between the two events.

A structural nesting relationship is NOT sufficient on its own. "London" in chapter 1
(day 2) and "Saville Row, London" in chapter 9 (day 40) are two genuinely different
moments and must NOT be collapsed, even though one hierarchy nests inside the other.
This is why dedup must operate on events (location + time + character together), not on
a standalone list of location strings.

This step is **pure deterministic code, no LLM** — a well-defined structural comparison,
not a judgment call requiring text understanding. This matters for trustworthiness as
much as cost: this step makes merge decisions that directly affect data integrity
(repointing event references), so a deterministic, auditable algorithm is preferred
over a model's judgment call.

---

## Algorithm

### Scope

Runs **per character**. Only compares events belonging to the same character —
never merges location specificity across different characters, even if they're in the
same place at the same time. (Two characters both being "in London" at the same time
does not imply anything about refining one's location based on the other's.)

Runs **after cleanup** (operating only on events that survived the location/date
completeness check) and **before geocoding**.

### Step 1 — Group

Group the character's events. All comparison happens within a single character's event
list; no cross-character comparison.

### Step 2 — Define "nests"

Event A's location **nests inside** event B's location (B is more specific) if:
- Every non-null field in A's `location.hierarchy` matches the corresponding field in
  B's `location.hierarchy` exactly, AND
- B has at least one additional non-null field at a deeper hierarchy level than A's
  deepest filled level.

**Transit events are never comparable for nesting against hierarchy events, or against
other transit events with different from/to.** `location_type: "transit"` and a
stationary hierarchy are structurally different and must not be merged via this
mechanism — leave both as-is regardless of any apparent overlap.

### Step 3 — Define "time does not conflict"

Between two events' `time.hierarchy`:
- If both specify `year`, they must be equal.
- If both specify `month`, they must be equal (assuming year already matches or either
  side has no year stated).
- If both specify `day`, they must be equal.
- A null field on either side does not block a match (absence is not a conflict).
- If one event has a precise date and the other only a `year_range_start`/`_end`, they
  are non-conflicting if the precise date falls within the stated range.

### Step 4 — Find the best match per event (single pass, not iterative)

For each event E belonging to a character, find — across ALL of that character's other
events, not just adjacent ones — the single MOST SPECIFIC event whose location nests E
inside it (per Step 2) AND whose time does not conflict with E (per Step 3).

- "Most specific" = the candidate with the deepest filled hierarchy level among all
  valid candidates, not merely the first one found.
- This must be computed by comparing E against the full candidate set in one pass per
  event, not by chaining pairwise merges — this avoids partial-chain inconsistency
  (e.g. A merges into B, but B fails to then merge into C, leaving A effectively
  "one step behind" the most specific available location). By checking each event
  against the full set directly, every event that has a most-specific compatible match
  finds it directly, regardless of how many intermediate specificity levels exist.
- If no event nests E (E is already the most specific, or has no time-compatible
  match), E's location is left unchanged.

### Step 5 — Apply the refinement

For every event E with a found most-specific match M:
- Replace E's `location` data with M's `location` data (the more specific hierarchy).
- E keeps its own `event_id`, `time`, `confidence`, `temporal_relation`,
  `story_chronological_order`, etc. — only the `location` portion is upgraded. This is
  refining one event's location, not merging two events into one. Both events continue
  to exist independently in the events list.

### Step 6 — Build the final location list

After all events have had their locations refined where applicable, collect the
distinct remaining hierarchy/transit combinations across the whole book (all
characters) and assign each a stable `location_id`. Point every event's `location` at
the appropriate `location_id`. This is the point at which the `locations` table for
this book is finalized, ready for geocoding backfill (next stage) and then DB write.

---

## Still open

- Geocoding backfill (see `ADDENDUM_4_geocoding_backfill.md` — addresses historical
  accuracy considerations, e.g. resolving a 1980s-set location to "Yugoslavia" rather
  than the modern "Serbia," flagged in planning as a real consideration).
- Entity-duplication validation pass for characters (separate from this — this document
  covers location refinement only).
- Database schema (still blocked on geocoding being designed, per current pipeline
  order — schema needs to know the final shape of a backfilled location record).
- End consumer / query interface.
