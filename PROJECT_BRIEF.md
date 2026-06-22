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
