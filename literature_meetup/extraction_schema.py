RECORD_CHAPTER_EVENTS_TOOL = {
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
                "items": {
                    "type": "object",
                    "properties": {
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
                        "sequence": {
                            "type": "object",
                            "properties": {
                                "narration_order": {"type": "integer"},
                                "story_chronological_order": {"type": ["integer", "null"]},
                            },
                            "required": ["narration_order"],
                        },
                        "temporal_relation": {
                            "type": "string",
                            "enum": ["current", "flashback", "flash_forward", "unclear"],
                        },
                        "chapter": {"type": "integer"},
                        "evidence_quote": {
                            "type": "string",
                            "description": "Short paraphrase, never a verbatim quote from the source text.",
                        },
                        "confidence": {"type": "string", "enum": ["explicit", "inferred"]},
                    },
                    "required": [
                        "character_id",
                        "location",
                        "time",
                        "sequence",
                        "temporal_relation",
                        "chapter",
                        "evidence_quote",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["new_characters", "new_locations", "events"],
    },
}
