# Literature Meet Up — Project Brief & Addenda

Consolidated design document: the original project brief plus all seven addenda, in order. Each addendum extends the ones before it.

## Contents

1. [Novel Character Location/Time Extraction Tool — Project Brief](#novel-character-locationtime-extraction-tool-project-brief)
2. [Project Brief Addendum 1 — Chronological Reconstruction & Cleanup](#project-brief-addendum-1-chronological-reconstruction-cleanup)
3. [Project Brief Addendum 2 — Pipeline State Management](#project-brief-addendum-2-pipeline-state-management)
4. [Project Brief Addendum 3 — Location Deduplication](#project-brief-addendum-3-location-deduplication)
5. [Project Brief Addendum 4 — Geocoding Backfill](#project-brief-addendum-4-geocoding-backfill)
6. [Project Brief Addendum 5 — Book-Level Setting Estimation](#project-brief-addendum-5-book-level-setting-estimation)
7. [Project Brief Addendum 6 — Database Schema](#project-brief-addendum-6-database-schema)
8. [Project Brief Addendum 7 — Character Duplication Detection](#project-brief-addendum-7-character-duplication-detection)

---

# Novel Character Location/Time Extraction Tool — Project Brief

## Purpose

Build a tool that ingests public-domain novels and extracts a structured database of
**where each character was, and when**, throughout the story. Source texts come from
Project Gutenberg. The output is a queryable database of character/location/time events.

This document is the spec resulting from a planning conversation. Schema and prompt
decisions below are final; a few items are explicitly flagged as open and need your
(Claude Code's) input or experimentation once we start testing against real text.

---

## Architecture overview

Two main modules:

### Module 1 — Fetch
Pulls book text and metadata from Project Gutenberg via the **Gutendex API**
(`https://gutendex.com`), an unofficial but stable, no-auth-required JSON wrapper around
Gutenberg's catalog.

- `GET /books/{id}` returns metadata including a `formats` object mapping MIME types to
  direct download URLs (plain text, HTML, EPUB) hosted on Gutenberg's own servers.
- Module 1 should fetch metadata via Gutendex, then download the actual text from the
  URL in `formats` (Gutendex itself does not host book text).
- Needs to strip Project Gutenberg boilerplate (license header/footer) and split the
  raw text into chapters. Chapter-marker conventions vary across Gutenberg texts
  (not perfectly consistent) — this will likely need some heuristics/testing across a
  few sample books, not just the one we discuss below.

### Module 2 — Analyze
For each chapter, in order:
1. Send the chapter text + the current **story state** (see below) to Claude via the API.
2. Use a defined tool (`record_chapter_events`, schema below) to force structured output.
3. Merge the result into the running story state (new characters/locations get IDs;
   resolved aliases reuse existing IDs).
4. Write events to the database.
5. Pass the updated story state forward to the next chapter's call.

This is a **sequential, stateful pipeline** — chapters must be processed in order because
each call depends on the accumulated story state from prior chapters. Parallelizing
across chapters is not safe without a different entity-resolution strategy.

---

## Why this design (key decisions from planning)

- **Chunking by chapter**, not sliding window or whole-book-in-context. Chapters are
  natural narrative units and keep state small per call.
- **Tool use / structured output**, not prose-then-parse. Far more reliable for getting
  consistent, schema-valid extraction across many sequential calls.
- **A persistent story-state object passed into every call**, so the model can resolve
  "Fogg" / "Mr. Fogg" / "he" back to an existing character ID instead of creating
  duplicates. This is the central mechanism that makes long-document consistency work.
- **No inference of computed values during extraction.** The model records what the text
  states or directly implies (with a `source`/`confidence` flag distinguishing the two).
  It must NOT calculate dates from elapsed-time references, interpolate transit
  position, or reconstruct chronological order. All of that is explicitly deferred to a
  **separate, later, auditable derivation step** — not bundled into extraction. Rationale:
  arithmetic/reconstruction errors compound silently across a long book if done inline;
  better to keep extraction purely observational and validate derivation separately.
- **Evidence fields must be paraphrased, never verbatim quotes** — both for copyright
  hygiene and to keep extraction outputs lightweight.
- **One event per character per distinct location/time state** (not one event with a
  character array). Chosen for query simplicity given the stated goal ("where was
  character X, and when").

---

## Final schema

### Story state (carried between chapter calls, not part of the tool schema itself —
this is pipeline-managed state, merged from each call's `new_characters`/`new_locations`)

```json
{
  "characters": [
    {"id": "char_001", "canonical_name": "Phileas Fogg", "aliases": ["Mr. Fogg", "Fogg"]}
  ],
  "locations": [
    {"id": "loc_001", "canonical_name": "London", "hierarchy": {"country": "United Kingdom", "region": null, "city": "London", "neighborhood": null, "street": null}}
  ]
}
```

### Tool schema: `record_chapter_events`

```json
{
  "name": "record_chapter_events",
  "description": "Record characters, locations, and character location/time events found in this chapter.",
  "input_schema": {
    "type": "object",
    "properties": {
      "new_characters": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string"},
            "canonical_name": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["id", "canonical_name"]
        }
      },
      "new_locations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string"},
            "canonical_name": {"type": "string"},
            "hierarchy": {
              "type": "object",
              "properties": {
                "country": {"type": ["string", "null"]},
                "region": {"type": ["string", "null"]},
                "city": {"type": ["string", "null"]},
                "neighborhood": {"type": ["string", "null"]},
                "street": {"type": ["string", "null"]}
              }
            }
          },
          "required": ["id", "canonical_name"]
        }
      },
      "events": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "character_id": {"type": "string"},

            "location": {
              "type": "object",
              "properties": {
                "location_type": {"type": "string", "enum": ["real", "fictional", "ambiguous", "transit"]},
                "hierarchy": {
                  "type": "object",
                  "properties": {
                    "country": {"type": ["string", "null"]},
                    "region": {"type": ["string", "null"]},
                    "city": {"type": ["string", "null"]},
                    "neighborhood": {"type": ["string", "null"]},
                    "street": {"type": ["string", "null"]}
                  }
                },
                "proximity": {"type": ["string", "null"], "enum": ["at", "area", null]},
                "transit": {
                  "type": ["object", "null"],
                  "properties": {
                    "from": {
                      "type": "object",
                      "properties": {
                        "country": {"type": ["string", "null"]},
                        "city": {"type": ["string", "null"]}
                      }
                    },
                    "to": {
                      "type": "object",
                      "properties": {
                        "country": {"type": ["string", "null"]},
                        "city": {"type": ["string", "null"]}
                      }
                    },
                    "transport_mode": {
                      "type": ["string", "null"],
                      "enum": ["on_foot", "animal", "carriage", "train", "ship", "automobile", "aircraft", "spacecraft", "magical", "other", null]
                    },
                    "transport_detail": {"type": ["string", "null"]}
                  }
                },
                "source": {"type": "string", "enum": ["stated", "inferred"]}
              },
              "required": ["location_type", "source"]
            },

            "time": {
              "type": "object",
              "properties": {
                "hierarchy": {
                  "type": "object",
                  "properties": {
                    "year_range_start": {"type": ["integer", "null"]},
                    "year_range_end": {"type": ["integer", "null"]},
                    "year": {"type": ["integer", "null"]},
                    "month": {"type": ["integer", "null"]},
                    "day": {"type": ["integer", "null"]}
                  }
                },
                "precision": {"type": ["string", "null"], "enum": ["year_range", "year", "month", "day", null]},
                "source": {"type": "string", "enum": ["stated", "inferred"]}
              },
              "required": ["source"]
            },

            "sequence": {
              "type": "object",
              "properties": {
                "narration_order": {"type": "integer"},
                "story_chronological_order": {"type": ["integer", "null"]}
              },
              "required": ["narration_order"]
            },

            "temporal_relation": {"type": "string", "enum": ["current", "flashback", "flash_forward", "unclear"]},
            "chapter": {"type": "integer"},
            "evidence_quote": {"type": "string", "description": "Short paraphrase, never a verbatim quote from the source text."},
            "confidence": {"type": "string", "enum": ["explicit", "inferred"]}
          },
          "required": ["character_id", "location", "time", "sequence", "temporal_relation", "chapter", "evidence_quote", "confidence"]
        }
      }
    },
    "required": ["new_characters", "new_locations", "events"]
  }
}
```

**Field semantics, for reference (do not confuse these three similarly-named flags):**
- `location.source` (`stated`/`inferred`) — precision of *where*: was this hierarchy
  level explicitly named in the text, or filled from context?
- `time.source` (`stated`/`inferred`) — precision of *when*, same logic applied to dates.
- `confidence` (`explicit`/`inferred`) — is the character's *presence* at this
  location actually confirmed by the text at all, independent of how precisely the
  location/time itself is known.

`transport_mode` is a fixed enum (max 10 values) by design — keeps the field stable and
groupable; specifics go in free-text `transport_detail` (e.g. "the Mongolia," "elephant").

`narration_order` = position as the reader/pipeline encounters it (mechanical, stamped
by Module 1/pipeline code from chapter position — not something the LLM should compute).
`story_chronological_order` = where the event falls in actual story-time; intentionally
left null at extraction time. Reconstructing this is future work, deliberately out of
scope for the extraction module (see "No inference" decision above).

---

## System prompt

Use the following as the system prompt for every chapter-extraction API call. Full text
also provided separately as `extraction_system_prompt.md` — reproduced here for completeness.

```markdown
# Character Location & Time Extraction — System Prompt

## Task

You extract factual, textually-grounded information about **where each character was, and when**, from a single chapter of a novel. You are not summarizing the chapter, interpreting its meaning, or evaluating its quality. You are producing structured data for a database, one event per character per location/time state.

You will receive:
1. The text of one chapter.
2. A **story state** object listing characters and locations already identified in earlier chapters of this book.

You must call the `record_chapter_events` tool with your findings. Do not respond in prose.

## Core principle: report only what the text supports

Record what the narration states or directly, unambiguously implies. Never compute, estimate, or reconstruct information the text does not provide. Specifically, you must NOT:

- Calculate or infer a date from elapsed time references ("three days later") unless the resulting date is also stated directly.
- Estimate a character's geographic position while in transit (e.g. interpolating a midpoint between two ports).
- Reorder events into story-chronological order. Only record narration order (the order events appear in the text) — chronological reconstruction happens in a later, separate process.
- Fill in a location hierarchy level (country, region, etc.) that the text never names or makes unambiguous, even if you know the real-world geography. If the chapter says "Bombay" and never mentions India, leave `country` null and mark `source: "stated"` for city, with country simply absent — do not add India yourself.

If you are inferring rather than reading something directly stated, you may still record it — but you must mark the relevant `source` or `confidence` field as `"inferred"` rather than `"stated"` / `"explicit"`. Inference is allowed; silent inference is not.

## Entity resolution (characters and locations)

You will be given a `story_state` object with previously-identified characters and locations, each with a canonical name and known aliases/variant names.

- Before creating a new character or location, check whether the text's reference matches an existing entry (by name, alias, title, nickname, or unambiguous pronoun reference within the passage).
- If it matches, reuse that entity's existing `id`. Do not create a duplicate.
- If it's a genuinely new character or location not seen before, add it to `new_characters` or `new_locations` in your output, and assign it a new working id following the same id pattern already in use.
- Minor narrators, unnamed characters ("a porter," "the driver") generally should NOT be tracked as characters unless they are clearly a recurring or named figure. Use judgment: if the chapter never gives a name or stable identifying title, skip them.
- Titles and roles (e.g. "the detective," "the Consul") count as an alias for a named character once the text has linked the role to a name. Before that link is made in the text, do not assume the role refers to a character you already know.

## When to create a new event for a character

Create one event per character per distinct location/time state. A new event is warranted when, for a given character, EITHER:
- Their location changes (any level of the hierarchy, or a shift into/out of transit), OR
- Their time context changes (a new date is stated, or the narration explicitly marks a shift such as a flashback or time skip).

Do not create a new event for every sentence a character appears in if neither their location nor time context has changed — multiple consecutive paragraphs describing the same character in the same place and time belong to a single event. Conversely, do not merge two genuinely distinct location or time states into one event for the sake of brevity.

## Transit vs. stationary

- If a character is explicitly described as traveling between two named places (e.g. "two days out of Bombay," "aboard the Mongolia bound for Hong Kong"), record this as `location_type: "transit"` with `from` and `to` filled from what the text states, and leave the hierarchy fields empty. Do not guess a current position along the route.
- If a character is vaguely but stationarily placed (e.g. "somewhere in the English countryside," with no specific city given), use the normal hierarchy with the deepest known level filled, and set `proximity: "area"`.
- `transport_mode` must be chosen from the fixed list provided in the tool schema. Use `transport_detail` for the specific vehicle name or descriptor (e.g. "the Mongolia," "elephant") — do not invent values outside the fixed enum for `transport_mode` itself.

## Time precision

- Fill `time.hierarchy` only as deep as the text supports: a chapter that only mentions "October" without a day should have `month` filled, `day` null, and `precision: "month"`.
- If the chapter gives no date information at all for an event, leave all `time.hierarchy` fields null and `precision` null. Do not leave the event out of your results because of this — location-only events are still valid and useful.
- Mark `time.source` as `"stated"` only if the date or date-level is written explicitly in this chapter. If you are carrying forward an earlier-established date because nothing in this chapter contradicts it, that is `"inferred"`, not `"stated"`.

## Flashbacks and non-linear narration

- Set `temporal_relation` based only on textual signals — explicit framing like "years before," "she remembered," "in his youth," or similar — not on your own judgment of where an event belongs chronologically.
- `"current"` is the default when no such signal is present.
- Use `"unclear"` rather than guessing if the chapter's temporal framing is genuinely ambiguous.
- Do not attempt to place flashback events on the main timeline. That is intentionally out of scope here.

## Confidence

`confidence` reflects whether the character's presence at the recorded location is actually confirmed by the text, separate from how precisely that location or time is known:
- `"explicit"` — the text directly states or unambiguously shows the character present (action, dialogue, direct narration).
- `"inferred"` — presence is implied but not directly stated (e.g. a character is assumed present in a scene because they were last seen entering the room and the narration doesn't explicitly mention them leaving).

## Evidence

For each event, include a brief `evidence_quote` field. This must be a short paraphrase in your own words of the textual basis for the event — never a verbatim quotation from the source text, regardless of length.

## Output

Call `record_chapter_events` exactly once per chapter with:
- `new_characters` — any characters introduced this chapter, not present in `story_state`.
- `new_locations` — any locations introduced this chapter, not present in `story_state`.
- `events` — one entry per character per distinct location/time state this chapter, per the rules above.

Do not output anything outside the tool call.
```

---

## Suggested test subject

**Around the World in Eighty Days**, Towle translation — Project Gutenberg ebook #103.
Good first test because:
- Clear chapter structure
- Frequent, explicit location changes (good stress test for hierarchy + transit)
- A working in-story calendar (good for testing `time` fields and `source: stated`)
- Small, stable cast (good for testing entity resolution / alias handling)
- Largely linear narration (low flashback complexity — saves that edge case for a second
  test book once the core pipeline is validated)

Fetch via:
```
GET https://gutendex.com/books/103
```
Then download the plain text / HTML format from the returned `formats` URLs (Gutendex
does not host the text itself, only metadata + links to Gutenberg's own file servers).

---

## Open items — not yet resolved, need decisions or experimentation during build

1. **Chapter-splitting heuristics.** Gutenberg texts don't follow one consistent
   chapter-marking convention. Module 1 will likely need testing against a few different
   books (not just #103) to build robust splitting logic, plus boilerplate
   header/footer stripping (the standard PG license text at start/end of file).

2. **Geocoding / hierarchy backfill.** Planning conversation concluded that filling
   gaps in the location hierarchy (e.g. inferring country from a stated city) should be
   a **separate post-processing step**, likely via a gazetteer or geocoding API — not
   something asked of the LLM during extraction. This step still needs to be designed.

3. **`story_chronological_order` reconstruction.** Deliberately deferred. Will need its
   own design pass — possibly a second LLM pass over accumulated events, or rule-based
   logic using `temporal_relation` + stated dates + `narration_order`. Treat as a
   separate module/phase, not part of initial pipeline.

4. **Validation pass for entity duplication.** Flagged in planning as the most likely
   silent failure mode (e.g. model fails to resolve an alias and creates a duplicate
   character mid-book). Consider a periodic or end-of-book consistency check — possibly
   a non-LLM heuristic (fuzzy name matching against existing `story_state`) or a cheap
   second LLM pass — before treating extracted data as final.

5. **`new_locations` granularity / dedup across hierarchy.** Schema allows partial
   hierarchy fills with nulls. Need a rule (in code, not just prompt) for when two
   `new_locations` entries should actually be treated as the same place at different
   specificity (e.g. "London" added in chapter 1, "Saville Row, London" added in chapter
   3 — should the second reuse/extend the first rather than create a sibling?).

6. **Database schema for storage.** Not yet designed — this brief defines the
   extraction/event schema, not the persistence layer (SQL tables vs. document store,
   indexing strategy, etc.). Needs its own pass once extraction is validated against
   real chapters.

7. **End consumer / query interface.** Not yet decided (structured export vs. queryable
   app vs. visualization) — deprioritized until the extraction pipeline itself is proven
   to work. Worth revisiting once Module 2 produces validated output for at least one
   full book.

---

## Suggested first build milestone

Get Module 1 fetching and chapter-splitting a single book (#103), and Module 2 running
the extraction call chapter-by-chapter against it with story-state passed forward,
writing raw event JSON to disk (no database yet). Manually review the output for:
- Alias resolution correctness (no duplicate characters for Fogg/Passepartout/Fix)
- Sensible event boundaries (not over- or under-segmented)
- Correct use of `transit` vs. `area` proximity
- `source`/`confidence` flags being used as intended, not defaulted to `"stated"`/`"explicit"`

This will surface schema or prompt gaps cheaply before any database or multi-book work
begins.

---

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

---

# Project Brief Addendum 2 — Pipeline State Management

Extends `PROJECT_BRIEF.md` and `ADDENDUM_1_chronological_reconstruction.md`. Read after
both — assumes that context.

---

## Decision: in-memory until cleanup completes, single batch write to DB

The pipeline holds all data **in memory** from the start of extraction through the end
of cleanup. The database is only written to **once, after cleanup completes**, with the
final surviving event set for the whole book.

Concretely, the in-memory lifecycle for a single book run is:

1. Module 1 fetches and chapter-splits the book (in memory).
2. Module 2 runs extraction chapter-by-chapter, accumulating: the running story_state
   (characters/locations) and the full events list, all in memory. Nothing is written
   to the database during this phase.
3. Once all chapters are extracted, reconstruction runs once over the full in-memory
   events list (the dated subset), producing `story_chronological_order` and
   `ordering_confidence` for those events. Merged back into the in-memory events list.
4. Cleanup runs once over the full in-memory events list, dropping events that fail the
   location/date checks.
5. ONLY NOW does the pipeline write to the database — a single batch write of
   characters, locations, and the surviving events for this book.

(Subsequent addenda add further in-memory stages — location dedup, geocoding backfill —
that also run before this single DB write. See `ADDENDUM_3_location_dedup.md` and
`ADDENDUM_4_geocoding_backfill.md`. This document describes the governing principle;
later documents extend the in-memory pipeline further without changing it.)

---

## Consequence: no partial persistence, no resume

This is a deliberate simplification, not an oversight. If the pipeline fails at any
point before the final DB write (e.g. extraction crashes on chapter 40 of 50,
reconstruction fails, or any later in-memory stage fails), all in-memory work for that
book run is lost — there is no partial save, and the book must be re-run from the
beginning.

This is considered an acceptable tradeoff for the current build phase (single-book,
on-demand runs), in exchange for a much simpler storage layer that only ever has to
model complete, finished data.

This should be revisited if/when the tool moves toward unattended batch processing of
many or very long books, where re-running a whole book from scratch after a late
failure becomes costly. A future option would be a lightweight checkpoint (e.g. caching
extraction output to disk after each chapter, separate from the real database) without
changing the final database schema at all — but this is explicitly out of scope now.

---

## Consequence for database schema

Because of this, the database schema only needs to model the **final, clean state**:

- No need for a "raw staging" table separate from the final table.
- `story_chronological_order` and `ordering_confidence` (from reconstruction) can be
  modeled as normal (nullable) columns on the events table from the start — they are
  never retrofitted onto already-persisted rows, since nothing is persisted until
  they're already computed.
- The database never contains an event that was later deleted by cleanup — deleted
  events simply never reach the database at all.
- The same applies to fields introduced by later in-memory stages (deduped
  `location_id` references, `geocode_status`, etc.) — by the time anything is written,
  it is already in its final form. The database schema should be designed assuming it
  only ever receives complete, fully-processed rows, never partial ones requiring
  later updates.

---

## Still open

- Geocoding / hierarchy backfill — see `ADDENDUM_4_geocoding_backfill.md`.
- Validation pass for entity duplication (characters) — not yet designed.
- `new_locations` granularity / dedup — see `ADDENDUM_3_location_dedup.md`.
- Database schema for storage — now well-scoped per the consequences above; a
  reasonable next design pass once dedup and geocoding are finalized.
- End consumer / query interface — still deferred.

---

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

---

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

---

# Project Brief Addendum 5 — Book-Level Setting Estimation

Extends `PROJECT_BRIEF.md` and Addenda 1–4. Read after all of them — assumes that
context.

---

## Why this exists

Many novels never state an absolute date anywhere in the text — setting is implied
only through accumulated context (technology, social references, publication era),
never asserted as a fact the way `record_chapter_events` requires for `source: "stated"`
or even `"inferred"` (which still means inferred from THIS text's own statements about
elapsed time, not inferred from genre/period cues).

This is a deliberate, bounded exception to the pipeline's governing principle of "report
only what the text supports, never compute or estimate." Every other stage in this
pipeline avoids inference of this kind. This stage exists specifically to provide ONE
narrow, clearly-labeled exception — a book-wide estimate, used only to keep otherwise
date-less events from being silently dropped, never presented as equivalent to a
text-stated or text-inferred date.

**This must remain visibly distinguishable from real event-level dates everywhere it
appears downstream.** See the `source: "book_estimated"` value below — this is the
mechanism that prevents this exception from quietly contaminating the rest of the
dataset.

---

## Updated pipeline order

```
1. Extraction (chapter-by-chapter, in memory)
2. Reconstruction (whole book, dated-events subset only, unchanged — does NOT see
   book-estimated dates, see below)
3. Book-level setting estimation (whole book, in memory)   <-- this document
4. Cleanup, modified to use the estimate (see below)
5. Location deduplication
6. Geocoding backfill
7. DB write
```

Setting estimation can run independently of extraction (it doesn't depend on extracted
events — it works from raw text sample + Gutendex metadata) and could in principle run
in parallel with Module 2. It is sequenced here before cleanup because cleanup is the
stage that consumes its output.

---

## Inputs (combined, with fallback)

Per your decision: **both metadata and text are used together; if the text-based pass
yields nothing useful, fall back to metadata alone.**

1. **Gutendex metadata** — publication date, author birth/death years if available.
   Cheap, always available, used as a baseline/fallback signal.
2. **A sample of the book's text** — opening chapters are generally sufficient;
   historical/technological/social cues that reveal setting tend to surface early.
   Fed to a model call to refine or override the metadata-only baseline.

If the text sample gives the model nothing useful to anchor an estimate (e.g. a very
abstract or non-period-specific opening), fall back to a metadata-only estimate rather
than forcing a guess from text alone. This fallback must be visible in the output (see
`method` field below), not silent.

---

## Output: book-level metadata, NOT an event field

```json
"book_metadata": {
  "estimated_setting": {
    "year_range_start": 1870,
    "year_range_end": 1875,
    "confidence": "high | medium | low",
    "basis": "short paraphrase of reasoning — e.g. publication date 1873, telegraph and steamship technology referenced, no automobiles present",
    "method": "text_and_metadata | metadata_only"
  }
}
```

- This is a **single estimate per book**, stored as book-level metadata — not written
  into any individual event during this step.
- Output is always a **range**, never a false-precision single year, reflecting the
  inherent uncertainty of this kind of estimate. Confidence should correspond to range
  width in practice (a high-confidence estimate may still reasonably be a narrow range;
  a low-confidence one should be wide) but this is a judgment call for the estimation
  prompt to make, not a hard rule enforced elsewhere.
- `method: "metadata_only"` records when the fallback was used, per the instruction
  above — this must remain visible, not collapsed into the same value as a
  text-informed estimate.

---

## Storage: estimate is always recorded, regardless of confidence

**The `estimated_setting` object itself is stored as book metadata for every book,
including `confidence: "low"`.** A low-confidence estimate is still informative data
about the book (it tells you the setting genuinely could not be pinned down), and is
not, by itself, harmful to store — it does not get used to alter any event's data
unless it clears the bar described in the next section.

---

## Use in cleanup: gated by confidence

This is the part of the design that required an explicit decision, since it changes
what survives into the database. **Per your decision: low-confidence estimates must
NOT be used to fill events into the database.**

Updated cleanup logic (extends the rule from Addendum 1):

An event is evaluated for survival as follows:
1. **Has usable location AND usable date already (per original Addendum 1 rule)** →
   passes through unchanged. (Most common case, unaffected by this addendum.)
2. **Has usable location, but NO usable date** →
   - If the book's `estimated_setting.confidence` is `"medium"` or `"high"`: fill the
     event's `time.hierarchy` with the estimated `year_range_start`/`year_range_end`,
     set `time.precision: "year_range"`, and set `time.source: "book_estimated"`. The
     event survives cleanup.
   - If the book's `estimated_setting.confidence` is `"low"`, OR no estimate could be
     produced at all: the event is dropped, exactly as in the original Addendum 1 rule.
     A low-confidence book-wide guess must not be used to rescue individual events —
     doing so risks a single uncertain estimate silently dominating large portions of
     the dataset with the least reliable date information available.
3. **Missing usable location (regardless of date status)** → dropped, unchanged from
   Addendum 1. This addendum only affects the date-completeness check, never the
   location-completeness check.

### New `source` value: `"book_estimated"`

The `time.source` field (previously `"stated" | "inferred"`, both describing
event-level provenance) gains a third value: `"book_estimated"`. This must remain a
distinct value, never collapsed into `"inferred"` — `"inferred"` means the model
inferred the date from something else stated in the same text (e.g. elapsed-time
counting within the narrative); `"book_estimated"` means there was no event-level
information at all, and the date is purely a book-wide backfill. Anything downstream
that branches on `time.source` must handle this third case explicitly, not assume a
binary.

---

## Consequence for reconstruction (Addendum 1) — unchanged, explicitly confirmed

**Reconstruction's input is unaffected by this addendum and must remain so.**
Reconstruction continues to operate ONLY on events with real, event-level date data —
it must NOT receive or use `book_estimated` dates as input. Reasoning: reconstruction's
entire value is sorting by genuine date evidence; feeding it a book-wide estimate
applied identically across many events would create large tie clusters with no real
ordering signal, degrading reconstruction's output rather than improving it.

This means: book-level setting estimation runs AFTER reconstruction in the pipeline
order above, and cleanup's date-filling behavior only ever applies to events that
reconstruction has already finished with (or that were never part of reconstruction's
input in the first place, having no date at all). Events whose date comes only from
`book_estimated` keep `story_chronological_order: null` permanently — we may know
roughly when in history the event occurred, but not where it falls relative to other
scenes in the story's internal sequence. This is consistent with the existing principle
that `story_chronological_order` is reserved for genuinely textually-grounded ordering.

---

## Still open

- Entity-duplication validation pass for characters — not yet designed.
- Database schema — now needs to additionally account for: a `book_metadata` table/
  object distinct from the events table, and the `time.source` enum expanding to three
  values.
- End consumer / query interface — still deferred.

---

# Project Brief Addendum 6 — Database Schema

Extends `PROJECT_BRIEF.md` and Addenda 1–5. Read after all of them — assumes that
context. Companion file: `schema.sql` (plain Postgres DDL, designed for Supabase).

---

## Why Supabase / Postgres

- The data is genuinely relational (characters → events → locations, with foreign
  keys throughout) — not document-shaped — so a relational DB fits naturally rather
  than working against the grain.
- Free tier is sufficient for single-book, on-demand processing during development.
- Built-in REST/client API gives a query layer for free if/when the end-consumer /
  query interface (still an open item) gets designed.
- `schema.sql` is plain Postgres DDL — runs directly in the Supabase SQL editor or via
  Supabase migration tooling. No Supabase-specific syntax used beyond relying on
  `gen_random_uuid()`, which is available by default in Supabase Postgres instances.

---

## Design principles carried into the schema

- **No staging tables.** Per Addendum 2, nothing is written to the database until the
  full in-memory pipeline (extraction → reconstruction → book-setting estimation →
  cleanup → location dedup → geocoding backfill) has finished. Every row inserted is
  already in its final form — there is no "partial" row shape to support anywhere.
- **Each pipeline run produces a new `books` row** (and cascading characters/locations/
  events), rather than updating an existing book's data in place. Re-running the same
  Gutenberg book is treated as an independent new run. No uniqueness constraint on
  `gutenberg_id` — deliberately, to keep iteration/re-testing friction-free during
  development. See note at the bottom of `schema.sql`.
- **Fixed-vocabulary fields are Postgres ENUM types**, not free text — gives DB-level
  validation for the controlled vocabularies defined across the brief and addenda
  (`location_type`, `transport_mode`, `precision`, `source`, `confidence`,
  `temporal_relation`, `ordering_confidence`, geocoding status, etc.).
- **Hierarchy fields are real columns**, not JSON — `city`, `country`, etc. are
  expected query/filter targets, so they're indexed columns rather than buried in a
  `jsonb` blob.

---

## Table-by-table mapping to prior addenda

### `books`
One row per processed novel.
- `gutendex_metadata` (jsonb) — raw Gutendex API response, kept for reference/debugging,
  not queried directly in normal use.
- `estimated_year_range_start/end`, `estimated_setting_confidence`,
  `estimated_setting_basis`, `estimated_setting_method` — directly from Addendum 5's
  `book_metadata.estimated_setting` object. **Always populated for every book,
  regardless of confidence** — per Addendum 5, only the USE of this estimate to fill
  individual events is confidence-gated (medium/high only), not its storage.

### `characters`
One row per distinct character per book, post entity-resolution (project brief,
"Entity resolution" section). `aliases` is a Postgres `text[]` — no separate alias
table needed at this scale.

### `locations`
One row per distinct location per book, **after** both location dedup (Addendum 3) and
geocoding backfill (Addendum 4) have run — this table only ever holds final, deduped,
backfilled location data.
- `country` / `region` / `city` / `neighborhood` / `street` — the hierarchy, per the
  original location schema. Null fields reflect genuine absence in the source text
  (or geocoding's inability to confidently resolve them — see `geocode_status`).
- `hierarchy_source` — maps to the original `location.source` field
  (`stated`/`inferred`; `book_estimated` is not expected here, that value is reserved
  for `events.time_source` per Addendum 5 — see note in schema comments).
- `transit_from_*` / `transit_to_*` / `transport_mode` / `transport_detail` —
  populated only when `location_type = 'transit'`, per Addendum 2's transit design.
  Enforced via the `chk_transit_shape` CHECK constraint: transit and hierarchy fields
  are mutually exclusive on a single row.
- `geocode_status` — directly from Addendum 4 (`resolved` / `unresolved` / `skipped`).
  Defaults to `'skipped'` since most rows (fictional/ambiguous/transit) never attempt
  backfill at all.

### `events`
The core table — one row per character per distinct location/time state, per the
project brief's one-event-per-character decision. Only events that survived cleanup
(Addendum 1, as modified by Addendum 5's book-estimated fallback) ever reach this
table.
- `id` — this column IS the `event_id` referenced throughout Addenda 1 and 5 (used by
  the reconstruction step to reference events). Generated once, at insert time, since
  nothing is written until the pipeline's final batch write (Addendum 2) — no need to
  generate IDs earlier in the pipeline unless your in-memory implementation finds it
  convenient to do so before insert.
- `time_year_range_start/end`, `time_year`, `time_month`, `time_day`, `time_precision`
  — the `time.hierarchy` object, flattened to columns.
- `time_source` — three-value enum per Addendum 5 (`stated` / `inferred` /
  `book_estimated`). This is the field that distinguishes a real textual date from a
  book-wide era backfill — must never be dropped or collapsed in any downstream query
  that cares about date reliability.
- `narration_order` — pipeline-stamped (not LLM-generated), per the project brief's
  original note and Addendum 1's clarification distinguishing it from
  `story_chronological_order`.
- `story_chronological_order` — nullable. Null for events that never had enough date
  information to enter reconstruction (Addendum 1), AND for events whose only date
  came from `book_estimated` (Addendum 5 — these deliberately never get a
  chronological position, only a rough era).
- `ordering_confidence` — nullable; only populated for events that actually went
  through reconstruction (Addendum 1's `assign_chronological_order` output).
- `confidence` — the presence-confidence field (`explicit`/`inferred`), distinct from
  `time_source` and the location's `hierarchy_source`. Answers "is the character
  actually here," not "how precisely do we know where/when." See inline column
  comment in `schema.sql` for the full distinction — this is a recurring point of
  possible confusion given three similarly-purposed fields exist in this schema, and
  is worth keeping straight when writing queries later.
- `evidence_quote` — paraphrase only, never a verbatim excerpt, per copyright handling
  established in the original system prompt.

---

## What's intentionally NOT in this schema

- No table for raw/incomplete extraction output — doesn't exist per Addendum 2's
  in-memory-until-final design.
- No alias join table — `text[]` column is sufficient at this scale.
- No historical/period-accurate geography table — explicitly out of scope per
  Addendum 4 (modern-day political geography only, by deliberate choice).
- No user/auth tables — out of scope for the current single-user, local-pipeline
  build phase.

---

## Still open

- Entity-duplication validation pass for characters — not yet designed; would likely
  operate on the `characters` table post-insert, or as an in-memory pre-insert check
  consistent with everything else in this pipeline.
- End consumer / query interface — now meaningfully unblocked, since the schema this
  would query against is defined. Reasonable next planning topic.

---

# Project Brief Addendum 7 — Character Duplication Detection

Extends `PROJECT_BRIEF.md` and Addenda 1–6. Read after all of them — assumes that
context.

---

## Why this exists

The project brief's extraction system prompt already includes a real-time defense
against character duplication: the `story_state` object passed into every chapter
call tells the model about existing characters and instructs it to reuse IDs rather
than creating new ones. This addendum addresses what happens when that real-time
defense fails — which it will, on long enough books, because alias resolution from
prose alone is genuinely hard (nicknames, titles introduced mid-book, a character
referred to only by epithet for several chapters before being named outright).

This is the character-side counterpart to Addendum 3 (location deduplication), but
the two problems are NOT solved the same way, and that difference is deliberate —
see "Why this differs from location dedup" below.

---

## Updated pipeline order

```
1. Extraction (chapter-by-chapter, in memory)
2. Reconstruction (whole book, dated-events subset only)
3. Book-level setting estimation (whole book, in memory)
4. Character duplication detection (whole book, in memory)   <-- this document
5. Cleanup (modified per Addendum 5)
6. Location deduplication
7. Geocoding backfill
8. DB write
```

This step does not depend on reconstruction, book-setting estimation, cleanup,
location dedup, or geocoding — it only needs the full character list and event data
from extraction. It is placed here (after extraction, before cleanup/dedup/geocoding)
because merging characters means repointing event `character_id` references, and it's
simplest to do that repointing before any of the later stages that also touch events
(cleanup drops events; dedup/geocoding modify location references) — keeping the
character-identity question settled first avoids any later stage having to reconcile
events under two different IDs that turn out to be the same person.

---

## Why this differs from location dedup (Addendum 3)

Location identity is structural — hierarchy fields either nest inside one another or
they don't, which is checkable with deterministic string/field comparison. Character
identity has no equivalent structural signal: "Phileas Fogg" and "the gentleman of
Saville Row" might be the same person with zero string overlap between their name
fields. A purely algorithmic pass (fuzzy string matching on `canonical_name`/
`aliases`) would catch only the easy cases — near-identical spellings, obvious
nickname patterns — and would systematically miss the hard cases, which are exactly
the cases that already slipped past extraction-time resolution (if they were easy to
catch by string matching, the extraction-time `story_state` mechanism likely would
have caught them too).

For this reason, character duplication detection is an **LLM pass, not a
deterministic algorithm** — similar reasoning to why reconstruction (Addendum 1) used
a model rather than pure sort logic: this requires judgment about what's been
described in the narrative, not just structural comparison of fields.

---

## Input

The full `characters` list as it stands after extraction (`id`, `canonical_name`,
`aliases`), PLUS enough event context for the model to judge by behavior, not just
name string similarity. Recommend including, per character: their associated events'
`evidence_quote` paraphrases and chapter numbers — this gives the model material to
judge "do these two character records describe the same person's actions across the
book," which is the actual signal needed, not just name comparison.

Whole book in one call, consistent with reconstruction (Addendum 1) — the character
list for a single novel is small, and the entire value of this step is seeing the
global picture across all chapters at once.

---

## Tool schema: `flag_character_duplicates`

```json
{
  "name": "flag_character_duplicates",
  "description": "Identify groups of character records that likely refer to the same person, given their names, aliases, and associated event context across the book.",
  "input_schema": {
    "type": "object",
    "properties": {
      "duplicate_groups": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "character_ids": {
              "type": "array",
              "items": {"type": "string"},
              "minItems": 2,
              "description": "IDs of character records believed to refer to the same person."
            },
            "canonical_id": {
              "type": "string",
              "description": "Which of character_ids should survive as the merged record — generally the one with the most complete name/most events, but use judgment."
            },
            "confidence": {
              "type": "string",
              "enum": ["certain", "likely", "uncertain"]
            },
            "reasoning": {
              "type": "string",
              "description": "Short paraphrase of why these records are believed to refer to the same character. Not a verbatim quote from the text."
            }
          },
          "required": ["character_ids", "canonical_id", "confidence", "reasoning"]
        }
      }
    },
    "required": ["duplicate_groups"]
  }
}
```

### Confidence tiers — three, not two, and deliberately so

This step uses a three-value confidence scale (`certain` / `likely` / `uncertain`),
diverging from the binary patterns used elsewhere in this pipeline (`stated`/
`inferred`, `explicit`/`inferred`). This is deliberate: "are these the same person" is
a genuinely fuzzier judgment than anything else asked of the model in this pipeline,
and the cost of being wrong is asymmetric — collapsing two records that are actually
different people is a worse outcome than leaving two records for the same character
unmerged. A finer-grained scale is needed to act differently on different confidence
levels, per the next section.

---

## What happens at each confidence tier

**Per your decision: only `certain` triggers an automatic merge. `likely` and
`uncertain` are left as separate, unmerged records for now.**

### `certain` → auto-merge
- Repoint every event currently referencing any non-canonical `character_id` in the
  group to instead reference `canonical_id`.
- Delete the non-canonical character records.
- Merge `aliases` arrays from all merged records into the surviving canonical
  record's `aliases` (union, deduplicated), so the merged record retains the full
  set of names it was known by across the book.

### `likely` / `uncertain` → leave as-is
- No automatic action taken. Both/all character records remain separate in the
  dataset, exactly as extraction produced them.
- This is the conservative choice: a missed merge leaves two visible records in the
  character list (e.g. "Fogg" and "the gentleman of Saville Row" both present) — a
  problem a person reviewing the data would likely notice and could manually
  reconcile. A wrong merge, by contrast, silently blends two different people's
  entire movement histories into one record, which is far harder to detect after the
  fact and actively corrupts the core purpose of this database.
- This output is still worth retaining somewhere visible (see "Suggested handling of
  non-merged groups" below) rather than discarded, since it's useful information even
  without automatic action.

---

## Suggested handling of non-merged groups

Since `likely`/`uncertain` groups are real signal (the model found a plausible reason
to suspect duplication) but are deliberately not auto-merged, consider surfacing them
somewhere for manual review rather than letting the information disappear — e.g.
logging them to console/file at pipeline-run time, or storing them in a lightweight
review table. This is NOT specified as a requirement here (manual review tooling is
out of scope for this addendum) — just worth not silently dropping output that took a
model call to produce. Treat as an implementation nicety, not a blocking requirement.

---

## Consequence for the rest of the pipeline

Because this step runs before cleanup, location dedup, and geocoding, all of those
later stages operate on an already-settled character identity set (for the `certain`
cases) — they never need to know this step occurred, since by the time they run,
event `character_id` references are already final for any character merges that did
happen.

No schema changes required to `schema.sql` from Addendum 6 — this step's effects
(fewer character rows, repointed event foreign keys) are absorbed naturally by the
existing `characters` and `events` table structure, since the database is only ever
written to once, after the full in-memory pipeline (including this step) has
finished, per Addendum 2.

---

## Still open

- Transit `from`/`to` enrichment — still deferred (Addendum 4).
- Chapter-splitting heuristics and Project Gutenberg boilerplate stripping — flagged
  in the original project brief's open items, not yet designed. This is Module 1's
  core remaining hard problem.
- Cross-character location deduplication — Addendum 3's dedup algorithm operates
  within a single character's events; it does not address whether two different
  characters' independently-extracted mentions of the same real place (e.g. both
  separately extracted as "London") get merged into a single location row or remain
  as duplicate rows describing the same place. Worth a follow-up check once real
  extraction output exists to see how much this actually matters in practice.
- End consumer / query interface — still deferred, now meaningfully unblocked.
- Manual review tooling for `likely`/`uncertain` character duplicate groups —
  explicitly out of scope for this addendum; flagged as a nicety, not a requirement.
