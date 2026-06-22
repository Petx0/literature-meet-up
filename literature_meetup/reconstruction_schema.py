ASSIGN_CHRONOLOGICAL_ORDER_TOOL = {
    "name": "assign_chronological_order",
    "description": "Assign story-chronological order to a set of dated events from a novel, given their narration order, chapter, temporal relation, and extracted date information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ordered_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "story_chronological_order": {"type": "integer"},
                        "ordering_confidence": {"type": "string", "enum": ["certain", "uncertain"]},
                    },
                    "required": ["event_id", "story_chronological_order", "ordering_confidence"],
                },
            }
        },
        "required": ["ordered_events"],
    },
}
