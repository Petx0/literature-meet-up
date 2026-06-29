def _event_item_schema(include_evidence_quote: bool) -> dict:
    """include_evidence_quote is an experimental, opt-in cost lever (not a
    shipped feature): evidence_quote is a full natural-language paraphrase
    per event, used by character_dedup.py as identity evidence but otherwise
    just for human review - measured to be ~20% of one event's output tokens.
    Dropping it is a separate, additional lever from the target_characters
    one in analyze_pipeline.py.
    """
    properties = {
        "character_id": {"type": "string"},
        "location": {
            "type": "object",
            "properties": {
                "location_type": {
                    "type": "string",
                    "enum": ["real", "fictional", "ambiguous", "transit"],
                },
                "hierarchy": {
                    "type": "object",
                    "properties": {
                        "country": {"type": ["string", "null"]},
                        "region": {"type": ["string", "null"]},
                        "city": {"type": ["string", "null"]},
                        "neighborhood": {"type": ["string", "null"]},
                        "street": {"type": ["string", "null"]},
                    },
                },
                "proximity": {"type": ["string", "null"], "enum": ["at", "area", None]},
                "transit": {
                    "type": ["object", "null"],
                    "properties": {
                        "from": {
                            "type": "object",
                            "properties": {
                                "country": {"type": ["string", "null"]},
                                "city": {"type": ["string", "null"]},
                            },
                        },
                        "to": {
                            "type": "object",
                            "properties": {
                                "country": {"type": ["string", "null"]},
                                "city": {"type": ["string", "null"]},
                            },
                        },
                        "transport_mode": {
                            "type": ["string", "null"],
                            "enum": [
                                "on_foot",
                                "animal",
                                "carriage",
                                "train",
                                "ship",
                                "automobile",
                                "aircraft",
                                "spacecraft",
                                "magical",
                                "other",
                                None,
                            ],
                        },
                        "transport_detail": {"type": ["string", "null"]},
                    },
                },
                "source": {"type": "string", "enum": ["stated", "inferred"]},
            },
            "required": ["location_type", "source"],
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
                        "day": {"type": ["integer", "null"]},
                    },
                },
                "precision": {
                    "type": ["string", "null"],
                    "enum": ["year_range", "year", "month", "day", None],
                },
                "source": {"type": "string", "enum": ["stated", "inferred"]},
            },
            "required": ["source"],
        },
        "temporal_relation": {
            "type": "string",
            "enum": ["current", "flashback", "flash_forward", "unclear"],
        },
        "chapter": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["explicit", "inferred"]},
    }
    required = ["character_id", "location", "time", "temporal_relation", "chapter", "confidence"]

    if include_evidence_quote:
        properties["evidence_quote"] = {
            "type": "string",
            "description": "Short paraphrase, never a verbatim quote from the source text.",
        }
        required.append("evidence_quote")

    return {"type": "object", "properties": properties, "required": required}


def build_record_chapter_events_tool(include_evidence_quote: bool = False) -> dict:
    return {
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
                            "aliases": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["id", "canonical_name"],
                    },
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
                                    "street": {"type": ["string", "null"]},
                                },
                            },
                        },
                        "required": ["id", "canonical_name"],
                    },
                },
                "events": {
                    "type": "array",
                    "items": _event_item_schema(include_evidence_quote),
                },
            },
            "required": ["new_characters", "new_locations", "events"],
        },
    }


RECORD_CHAPTER_EVENTS_TOOL = build_record_chapter_events_tool()
