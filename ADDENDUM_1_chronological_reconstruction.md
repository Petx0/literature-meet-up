# Project Brief Addendum 1 — Chronological Reconstruction & Cleanup

This document extends `PROJECT_BRIEF.md` with the next pipeline stage, decided in a
follow-up planning session. Read after the original brief — this assumes that schema
and system prompt as context and does not repeat it in full.

---

## Schema change to extraction output: add `event_id`

The extraction tool schema (`record_chapter_events`, in the original brief) needs one
addition: every event must have a stable, unique `event_id`. This did not exist in the
original schema and is required by the reconstruction step below, which references
events by ID.

Recommend assigning this **in pipeline code at write-time** (e.g. on database insert,
or immediately after each chapter's tool-call response is received), rather than asking
the LLM to generate it during extraction — it's a mechanical concern, not an extraction
judgment, consistent with how `narration_order` is handled (pipeline-stamped, not
model-invented). A simple scheme like `{book_id}_{chapter}_{character_id}_{index}` or a
UUID is sufficient.

Update the `events` array item schema in `record_chapter_events` to include:
```json
"event_id": {"type": "string"}
```
(Required field, pipeline-assigned post-hoc — does not need to be requested from the
model in the tool call itself if you'd rather stamp it in code after receiving the
response. Either approach works; stamping in code is simpler since it guarantees
uniqueness without relying on the model.)

---

## New pipeline stage: Story-Chronological Order Reconstruction

Runs once per book, after all chapters have been extracted (Module 2 complete).

### Scope and input

- Input: all events for the book where `time.hierarchy` has at least one non-null
  field (year, month, day, year_range_start, or year_range_end).
- Events with zero date information anywhere are excluded from this step's input
  entirely — their `story_chronological_order` simply stays `null`. This is a
  deliberate, final decision: reconstruction is **opt-in per event** based on having
  any date data at all, and books that are largely undated may end up with this step
  doing very little. That's expected and fine.
- Whole book in one call — do NOT chunk this step by chapter. The entire point is
  seeing the global picture to resolve cross-chapter ordering (especially flashbacks),
  and by this stage the input is already-structured event data (small, not raw prose),
  so it comfortably fits in a single context window even for a full novel.

### Model choice

This step is structured-in/structured-out reasoning over a small bounded dataset, not
prose interpretation — the hard interpretive work already happened during extraction.
**Recommend testing with a cheaper/smaller model first** (e.g. Haiku-class) and only
escalating to a larger model if testing shows it struggling with a particular book's
ordering complexity. This is explicitly cheaper than extraction calls and should be
budgeted/implemented as such.

### Tool schema: `assign_chronological_order`

```json
{
  "name": "assign_chronological_order",
  "description": "Assign story-chronological order to a set of dated events from a novel, given their narration order, chapter, temporal relation, and extracted date information.",
  "input_schema": {
    "type": "object",
    "properties": {
      "ordered_events": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "event_id": {"type": "string"},
            "story_chronological_order": {"type": "integer"},
            "ordering_confidence": {"type": "string", "enum": ["certain", "uncertain"]}
          },
          "required": ["event_id", "story_chronological_order", "ordering_confidence"]
        }
      }
    },
    "required": ["ordered_events"]
  }
}
```

Output must be a **strict total order** — every input event gets a distinct integer, no
ties. Ties are resolved silently using narration order (see system prompt). This was a
deliberate choice to keep `story_chronological_order` simple for downstream consumers
(no tie-handling logic needed anywhere that queries this field later).

`ordering_confidence` is new relative to the original event schema's `confidence`/
`source` flags — it describes a different kind of uncertainty (relative-ordering
uncertainty between two events) rather than extraction certainty (is this in the text
at all). It should fire only for genuine ambiguity, not routine tiebreaking — see system
prompt for the precise distinction.

### System prompt

Full text below; also provided as a separate file `reconstruction_system_prompt.md`.

```markdown
# Story-Chronological Order Reconstruction — System Prompt

## Task

You receive a list of events extracted from a novel — each with a narration position
(the order they appear in the text), a chapter number, a temporal relation
(current / flashback / flash_forward / unclear), and date information of varying
precision. Every event in this list has at least partial date information; events with
no date information at all have already been excluded and are not your concern.

Your job is to assign each event a `story_chronological_order`: an integer reflecting
the order these events actually happened in the story's internal timeline, NOT the
order they were narrated in. You must produce a strict total order — every event gets
a distinct integer, with no ties.

Call the `assign_chronological_order` tool with your results. Do not respond in prose.

## Primary rule: sort by stated date

Where two or more events have date information, order them according to that date,
using the deepest level of precision available for each (year, month, day, or year
range). An event precise to the day should be ordered relative to an event only known
to the month using the information you have — place the day-precise event consistently
with the month it falls in.

## Tiebreakers

When two events cannot be distinguished by date alone (identical stated dates, or
overlapping/equal precision with no finer information available), break the tie using:
1. `temporal_relation` — events marked `current` should generally follow the
   established narration sequence relative to other `current` events; flashback/
   flash-forward events are handled per the rules below.
2. `narration_order` — if still tied, use narration order as the deciding factor.
   This is a silent tiebreak: do not flag these as uncertain merely because narration
   order was used to break an exact date tie. That is expected, normal behavior, not a
   sign of ambiguity.

### Year-range vs. precise-date conflicts

A common case: one event has only a `year_range_start`/`year_range_end` (e.g. "the
1920s"), and another nearby event has a precise year, month, or day. Handle this as
follows:

- If the precise date falls OUTSIDE the range entirely, order by the range's start/end
  boundary as if it were the date — no ambiguity, no tiebreaker needed.
- If the precise date falls WITHIN the range, do not attempt to guess where inside the
  range the range-only event sits relative to the precise one. Instead, apply the
  standard tiebreakers (`temporal_relation`, then `narration_order`) to decide the
  order, and mark `ordering_confidence` as `"uncertain"` for the range-only event. This
  is a genuine ambiguity, unlike a same-date tiebreak, and should be flagged as such.
- If two events both have only overlapping ranges (no precise date on either), apply
  the standard tiebreakers and mark BOTH events `"uncertain"`.

## Handling flashback and flash-forward events

- A `flashback` event must be ordered chronologically BEFORE the `current`-timeline
  events that surround it in narration order, even though it appears later in the text.
  Use its own date information (if present) to place it as precisely as possible within
  the broader timeline — not just generically "before everything in this chapter."
- A `flash_forward` event must be ordered chronologically AFTER the `current`-timeline
  events that surround it in narration order, with the same principle applying.
- `unclear` events should be placed using only their explicit date information. If date
  information does not resolve their position relative to nearby events, fall back to
  treating them as `current` for tiebreak purposes, but mark `ordering_confidence` as
  `"uncertain"`.
- When multiple flashback (or multiple flash-forward) events relate to each other and
  their relative order to one another is not determinable from date or narration
  information, you must still assign a strict order between them (no ties allowed), but
  mark `ordering_confidence` as `"uncertain"` for the affected events.

## What NOT to do

- Do not invent or assume a date that is not present in the event's data, even to
  resolve a tie. Use narration order instead, silently, as described above.
- Do not assign an order that contradicts a stated date. Narration order and
  temporal_relation are only for breaking ties or positioning genuinely undated-relative
  events — they never override an explicit date conflict.
- Do not exclude any event from your output. Every event you are given must receive a
  `story_chronological_order` value.
- Do not mark `ordering_confidence` as `"uncertain"` simply because you used a
  tiebreaker. Reserve `"uncertain"` for cases where you are genuinely unsure of relative
  placement even after applying all the rules above — for example, two undated-relative
  flashback events with no information distinguishing their order from one another.

## Output

Call `assign_chronological_order` exactly once with one entry per input event, each
containing `event_id`, `story_chronological_order`, and `ordering_confidence`.
```

---

## New pipeline stage: Cleanup (post-reconstruction)

Runs once per book, immediately after reconstruction completes. **Pure algorithmic
filter — no LLM involved.** Operates on the full event set (not just the dated subset
used by reconstruction).

### Rule

An event is **dropped (hard delete)** if it fails EITHER of these two checks:

**Has a usable location** — true if ANY of:
- At least one `location.hierarchy` field (country/region/city/neighborhood/street) is
  non-null, OR
- `location.location_type == "transit"` AND at least one of `transit.from` /
  `transit.to` is populated

**Has a usable date** — true if ANY of:
- `time.hierarchy.year`, `.month`, or `.day` is non-null, OR
- `time.hierarchy.year_range_start` or `.year_range_end` is non-null

If an event fails the location check, OR fails the date check, it is deleted. An event
must pass both to survive — the entire point of the database is "where was X, when," so
an event missing either axis can't serve that purpose.

### Explicitly NOT part of this filter

- `confidence` (`explicit`/`inferred`) — presence-certainty is a separate concern from
  completeness and is intentionally NOT a deletion criterion here. Low-confidence
  events are kept as long as they pass the location/date checks above.
- `ordering_confidence` from the reconstruction step — also not a deletion criterion.
  An event with `"uncertain"` ordering still has a real (if imprecise) position and
  should be kept.

### Retention policy

**Hard delete, no retention log, for now.** This was a deliberate simplification for
the current build phase — dropped events are not written anywhere else, just removed
from the dataset that proceeds to storage/querying. This can be revisited later (e.g.
adding a diagnostic log of dropped events to help debug systematic extraction gaps for
a particular character or chapter) but is explicitly out of scope for now.

### Suggested implementation order

1. Run reconstruction (assigns `story_chronological_order` to the dated subset).
2. Merge reconstruction output back into the full event set.
3. Run the cleanup filter across the full (now-reconstructed) event set.
4. Persist the surviving events.

Running cleanup after reconstruction (rather than before) is intentional — reconstruction
needs to see the full picture of dated events to resolve ordering, and cleanup's
location-check doesn't depend on reconstruction's output anyway, so the order is mostly
about keeping reconstruction's input well-defined (the dated-events filter for step 1
is a subset of, not dependent on, the cleanup criteria in step 3).

---

## Still open

Carried forward and resolved/updated across later addenda — see
`ADDENDUM_2_pipeline_state_management.md` onward for what followed this document.
