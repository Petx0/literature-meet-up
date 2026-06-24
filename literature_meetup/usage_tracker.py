from __future__ import annotations

# $ per million tokens, (input, output). Cache reads/writes are priced
# separately in summary() below (0.1x / 1.25x of the base input rate) since
# that's how Anthropic actually bills them - lumping them into the base input
# rate (as this used to do) overstates real cost and hides the value of
# prompt caching.
PRICING_PER_MILLION_TOKENS = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

_records: list[dict] = []


def reset() -> None:
    _records.clear()


def record(model: str, usage) -> None:
    _records.append(
        {
            "model": model,
            "input_tokens": usage.input_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "output_tokens": usage.output_tokens,
        }
    )


def summary() -> dict:
    """Returns {"total_cost": float, "by_model": {model: {"calls", "input_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens", "cost"}}}.
    """
    by_model: dict[str, dict] = {}
    for entry in _records:
        model = entry["model"]
        bucket = by_model.setdefault(
            model,
            {
                "calls": 0,
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += entry["input_tokens"]
        bucket["cache_creation_input_tokens"] += entry["cache_creation_input_tokens"]
        bucket["cache_read_input_tokens"] += entry["cache_read_input_tokens"]
        bucket["output_tokens"] += entry["output_tokens"]

    for model, bucket in by_model.items():
        input_rate, output_rate = PRICING_PER_MILLION_TOKENS.get(model, (0.0, 0.0))
        bucket["cost"] = (
            bucket["input_tokens"] * input_rate
            + bucket["cache_creation_input_tokens"] * input_rate * CACHE_WRITE_MULTIPLIER
            + bucket["cache_read_input_tokens"] * input_rate * CACHE_READ_MULTIPLIER
            + bucket["output_tokens"] * output_rate
        ) / 1_000_000

    return {"total_cost": sum(bucket["cost"] for bucket in by_model.values()), "by_model": by_model}
