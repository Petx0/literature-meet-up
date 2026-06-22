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
