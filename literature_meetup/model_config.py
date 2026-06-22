"""Central place to configure which Claude model each pipeline stage uses.

Each constant reads its matching environment variable first (same name),
falling back to the default shown below if unset - so models can be
swapped per-environment via .env without touching any code. The defaults
are also the recommended setting for each stage.

| Stage                          | Env var / constant         | Default            | Why this tier                                          |
|---------------------------------|-----------------------------|---------------------|----------------------------------------------------------|
| Chapter extraction               | EXTRACTION_MODEL            | claude-opus-4-8     | Real narrative judgment - entity resolution, transit vs. |
|                                  |                              |                     | stationary, source/confidence flags.                     |
| Chronological reconstruction     | RECONSTRUCTION_MODEL        | claude-haiku-4-5    | Structured-in/structured-out sorting over already-       |
|                                  |                              |                     | extracted data, not prose - cheaper model suffices       |
|                                  |                              |                     | (Addendum 1).                                            |
| Book-setting estimation          | SETTING_ESTIMATION_MODEL    | claude-opus-4-8     | Reads text cues and cross-references metadata - needs    |
|                                  |                              |                     | real judgment.                                           |
| Character duplication detection  | CHARACTER_DEDUP_MODEL       | claude-opus-4-8     | Narrative judgment about behavior/continuity, not string |
|                                  |                              |                     | matching (Addendum 7).                                   |
"""

import os

DEFAULT_EXTRACTION_MODEL = "claude-opus-4-8"
DEFAULT_RECONSTRUCTION_MODEL = "claude-haiku-4-5"
DEFAULT_SETTING_ESTIMATION_MODEL = "claude-opus-4-8"
DEFAULT_CHARACTER_DEDUP_MODEL = "claude-opus-4-8"

EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL)
RECONSTRUCTION_MODEL = os.environ.get("RECONSTRUCTION_MODEL", DEFAULT_RECONSTRUCTION_MODEL)
SETTING_ESTIMATION_MODEL = os.environ.get("SETTING_ESTIMATION_MODEL", DEFAULT_SETTING_ESTIMATION_MODEL)
CHARACTER_DEDUP_MODEL = os.environ.get("CHARACTER_DEDUP_MODEL", DEFAULT_CHARACTER_DEDUP_MODEL)
