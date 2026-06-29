_EVIDENCE_SECTION = """## Evidence

For each event, include a brief `evidence_quote` field. This must be a short paraphrase in your own words of the textual basis for the event — never a verbatim quotation from the source text, regardless of length.

"""


def build_system_prompt(include_evidence_quote: bool = False) -> str:
    """include_evidence_quote is the prompt-side half of the experimental,
    opt-in evidence_quote cost lever - see extraction_schema.py's
    _event_item_schema for the schema-side half. Both must be passed the
    same flag (chapter_analyzer.py does this) since the schema is what
    forced tool-use actually enforces; this just keeps the prompt from
    instructing the model to fill in a field the schema no longer has.
    """
    evidence_section = _EVIDENCE_SECTION if include_evidence_quote else ""
    return f"""# Character Location & Time Extraction — System Prompt

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

{evidence_section}## Output

Call `record_chapter_events` exactly once per chapter with:
- `new_characters` — any characters introduced this chapter, not present in `story_state`.
- `new_locations` — any locations introduced this chapter, not present in `story_state`.
- `events` — one entry per character per distinct location/time state this chapter, per the rules above.

Do not output anything outside the tool call.
"""


SYSTEM_PROMPT = build_system_prompt()
