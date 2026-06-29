"""Central place to configure which Claude model each pipeline stage uses.

Each constant reads its matching environment variable first (same name),
falling back to the default shown below if unset - so models can be
swapped per-environment via .env without touching any code. The defaults
are also the recommended setting for each stage.

| Stage                          | Env var / constant         | Default            | Why this tier                                          |
|---------------------------------|-----------------------------|---------------------|----------------------------------------------------------|
| Chapter extraction               | EXTRACTION_MODEL            | claude-sonnet-4-6   | Runs once PER CHAPTER - the only stage that scales with  |
|                                  |                              |                     | book length, so it's the most cost-sensitive one.        |
|                                  |                              |                     | Sonnet-tier quality has been empirically validated on    |
|                                  |                              |                     | this task; reserve Opus spend for the low-volume,        |
|                                  |                              |                     | judgment-heavy single calls below instead. Also large    |
|                                  |                              |                     | enough (combined with the tool schema) to clear Sonnet's |
|                                  |                              |                     | prompt-caching minimum (2048 tokens) - Opus's minimum is  |
|                                  |                              |                     | 4096, which this prompt would NOT reach, silently         |
|                                  |                              |                     | disabling the cache_control breakpoint in                |
|                                  |                              |                     | chapter_analyzer.py.                                      |
| Chronological reconstruction     | RECONSTRUCTION_MODEL        | claude-haiku-4-5    | Structured-in/structured-out sorting over already-       |
|                                  |                              |                     | extracted data, not prose - cheaper model suffices       |
|                                  |                              |                     | (Addendum 1).                                            |
| Book-setting estimation          | SETTING_ESTIMATION_MODEL    | claude-opus-4-8     | Reads text cues and cross-references metadata - needs    |
|                                  |                              |                     | real judgment. Runs once per book, so the tier cost is    |
|                                  |                              |                     | bounded regardless of book length.                        |
| Character duplication detection  | CHARACTER_DEDUP_MODEL       | claude-opus-4-8     | Narrative judgment about behavior/continuity, not string |
|                                  |                              |                     | matching (Addendum 7). Also once per book.                |

LLM_BACKEND selects how every stage above actually places its call, not
which model it asks for:
  - "api" (default): the Anthropic Python SDK, billed per-token against
    ANTHROPIC_API_KEY. Supports forced tool-use and cache_control.
  - "cli": literature_meetup/cli_backend.py via claude-agent-sdk, which
    spawns the locally-installed, subscription-authenticated `claude` CLI
    (run `claude login` once) - no per-token billing, but requires the CLI
    installed and logged in, and loses forced tool-use (the schema is
    turned into a "respond with only this JSON" instruction instead - see
    llm_client.py). One switch controls all four stages above.

CLI_SESSION_BUDGET_USD (cli_backend.py): optional proactive ceiling on
cumulative equivalent-API-cost for the "cli" backend across an entire
process run (not reset per book, unlike usage_tracker). Subscription usage
windows (Claude Pro/Max) can't be reliably outrun by pacing calls slightly
slower, so once a run gets rate-limited, the fix is to stop proactively
*before* the call that would hit it, not retry harder. Unset by default
(no cap enforced) - there's no reliable a-priori number for the real quota,
so set this empirically from a prior rate-limited run's reported
`equivalent_api_cost`, a bit lower, for the next run.

The remaining env vars below are process_book's (pipeline.py) cost levers -
centralized here rather than left as Python-only kwargs, so every script
(run_book.py, run_test_corpus.py, reprocess_full_books.py) picks up the same
.env-configured behavior without each one threading its own CLI flags:

INCLUDE_EVIDENCE_QUOTE (default "false"): whether extraction asks the model
for a per-event evidence_quote. Off by default - measured ~20% output-token
reduction with no accuracy cost (see chapter_analyzer.py).

TARGET_CHARACTERS_AUTO_DISCOVER (default "false"): when "true",
process_book looks up `metadata`'s title/author on Wikidata (see
literature_meetup/wikidata_characters.py) and uses the result as
target_characters whenever a caller doesn't pass one explicitly - cutting
output tokens on minor characters (measured ~25-32% on a tight, well-suited
list, less on a large untrimmed one - see TARGET_CHARACTERS_TOP_N). Off by
default since it adds a network dependency (Wikidata) to every book run and
its ranking has known, accepted imperfections (real-world-fame proxy, not a
true narrative-importance measure - see
wikidata_characters.fetch_main_characters_ranked's docstring). Silently
falls back to unrestricted extraction (not an error) when Wikidata has no
match or no characters for a book.

TARGET_CHARACTERS_TOP_N (default "8"): how many ranked characters
TARGET_CHARACTERS_AUTO_DISCOVER keeps per book. Confirmed live that a large,
untrimmed P674 list dilutes the cost saving on a long book sampled only
partially (8.6% reduction with 33 names vs 24.8% with 3, on the same
chapters) - keep this small relative to the book's real main cast size.

CHAPTER_SAMPLE_PCT (default "100", i.e. no sampling): process only the
first N% of a book's chapters - see pipeline._sample_chapters. A real
quality tradeoff (events from the unprocessed remainder are never
discovered at all), not a free lever like the two above, so it defaults to
full-book processing; only lower this deliberately.
"""

import os

DEFAULT_EXTRACTION_MODEL = "claude-sonnet-4-6"
DEFAULT_RECONSTRUCTION_MODEL = "claude-haiku-4-5"
DEFAULT_SETTING_ESTIMATION_MODEL = "claude-opus-4-8"
DEFAULT_CHARACTER_DEDUP_MODEL = "claude-opus-4-8"


def _env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL)
RECONSTRUCTION_MODEL = os.environ.get("RECONSTRUCTION_MODEL", DEFAULT_RECONSTRUCTION_MODEL)
SETTING_ESTIMATION_MODEL = os.environ.get("SETTING_ESTIMATION_MODEL", DEFAULT_SETTING_ESTIMATION_MODEL)
CHARACTER_DEDUP_MODEL = os.environ.get("CHARACTER_DEDUP_MODEL", DEFAULT_CHARACTER_DEDUP_MODEL)

LLM_BACKEND = os.environ.get("LLM_BACKEND", "api")

INCLUDE_EVIDENCE_QUOTE = _env_bool("INCLUDE_EVIDENCE_QUOTE", "false")
TARGET_CHARACTERS_AUTO_DISCOVER = _env_bool("TARGET_CHARACTERS_AUTO_DISCOVER", "false")
TARGET_CHARACTERS_TOP_N = int(os.environ.get("TARGET_CHARACTERS_TOP_N", "8"))
CHAPTER_SAMPLE_PCT = float(os.environ.get("CHAPTER_SAMPLE_PCT", "100"))
