ESTIMATE_BOOK_SETTING_TOOL = {
    "name": "estimate_book_setting",
    "description": "Estimate the approximate historical period this novel is set in, from text cues and publication metadata, for use as a book-wide fallback when no event-level date exists.",
    "input_schema": {
        "type": "object",
        "properties": {
            "year_range_start": {"type": ["integer", "null"]},
            "year_range_end": {"type": ["integer", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "basis": {
                "type": "string",
                "description": "Short paraphrase of the reasoning, never a verbatim quote from the source text.",
            },
            "method": {"type": "string", "enum": ["text_and_metadata", "metadata_only"]},
        },
        "required": ["year_range_start", "year_range_end", "confidence", "basis", "method"],
    },
}
