FLAG_CHARACTER_DUPLICATES_TOOL = {
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
                            "description": "IDs of character records believed to refer to the same person.",
                        },
                        "canonical_id": {
                            "type": "string",
                            "description": "Which of character_ids should survive as the merged record - generally the one with the most complete name/most events, but use judgment.",
                        },
                        "confidence": {"type": "string", "enum": ["certain", "likely", "uncertain"]},
                        "reasoning": {
                            "type": "string",
                            "description": "Short paraphrase of why these records are believed to refer to the same character. Not a verbatim quote from the text.",
                        },
                    },
                    "required": ["character_ids", "canonical_id", "confidence", "reasoning"],
                },
            }
        },
        "required": ["duplicate_groups"],
    },
}
