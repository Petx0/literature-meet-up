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
"""

import os

DEFAULT_EXTRACTION_MODEL = "claude-sonnet-4-6"
DEFAULT_RECONSTRUCTION_MODEL = "claude-haiku-4-5"
DEFAULT_SETTING_ESTIMATION_MODEL = "claude-opus-4-8"
DEFAULT_CHARACTER_DEDUP_MODEL = "claude-opus-4-8"

EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL)
RECONSTRUCTION_MODEL = os.environ.get("RECONSTRUCTION_MODEL", DEFAULT_RECONSTRUCTION_MODEL)
SETTING_ESTIMATION_MODEL = os.environ.get("SETTING_ESTIMATION_MODEL", DEFAULT_SETTING_ESTIMATION_MODEL)
CHARACTER_DEDUP_MODEL = os.environ.get("CHARACTER_DEDUP_MODEL", DEFAULT_CHARACTER_DEDUP_MODEL)
