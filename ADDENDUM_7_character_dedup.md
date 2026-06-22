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
