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
_cli_equivalent_api_cost: float = 0.0


def reset() -> None:
    _records.clear()
    global _cli_equivalent_api_cost
    _cli_equivalent_api_cost = 0.0


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


def record_cli(model: str, result_message) -> None:
    """Records a call made via LLM_BACKEND=cli (literature_meetup/cli_backend.py).
    Subscription usage isn't billed per-token, so this never contributes to
    the real `cost` total in summary() - instead it tracks call/token counts
    for visibility, and separately accumulates the SDK's own
    equivalent-API-cost estimate (`total_cost_usd`) into a running total so
    callers can report "what this would have cost under the API".
    """
    usage = getattr(result_message, "usage", None) or {}
    _records.append(
        {
            "model": model,
            "input_tokens": usage.get("input_tokens", 0) or 0,
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
            "output_tokens": usage.get("output_tokens", 0) or 0,
            "cli": True,
        }
    )
    global _cli_equivalent_api_cost
    total_cost_usd = getattr(result_message, "total_cost_usd", None) or 0.0
    _cli_equivalent_api_cost += total_cost_usd


def summary() -> dict:
    """Returns {"total_cost": float, "equivalent_api_cost": float,
    "by_model": {model: {"calls", "input_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens", "cost"}}}.
    `cost` is always 0 for calls recorded via record_cli (subscription
    usage, not billed per-token); `equivalent_api_cost` is the SDK's own
    estimate of what those calls would have cost under the API, separate
    from the real per-token total_cost.
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
                # Billable subset only - excludes record_cli entries, which
                # are subscription usage and never contribute real cost.
                "_billable_input_tokens": 0,
                "_billable_cache_creation_input_tokens": 0,
                "_billable_cache_read_input_tokens": 0,
                "_billable_output_tokens": 0,
            },
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += entry["input_tokens"]
        bucket["cache_creation_input_tokens"] += entry["cache_creation_input_tokens"]
        bucket["cache_read_input_tokens"] += entry["cache_read_input_tokens"]
        bucket["output_tokens"] += entry["output_tokens"]
        if not entry.get("cli"):
            bucket["_billable_input_tokens"] += entry["input_tokens"]
            bucket["_billable_cache_creation_input_tokens"] += entry["cache_creation_input_tokens"]
            bucket["_billable_cache_read_input_tokens"] += entry["cache_read_input_tokens"]
            bucket["_billable_output_tokens"] += entry["output_tokens"]

    for model, bucket in by_model.items():
        input_rate, output_rate = PRICING_PER_MILLION_TOKENS.get(model, (0.0, 0.0))
        bucket["cost"] = (
            bucket.pop("_billable_input_tokens") * input_rate
            + bucket.pop("_billable_cache_creation_input_tokens") * input_rate * CACHE_WRITE_MULTIPLIER
            + bucket.pop("_billable_cache_read_input_tokens") * input_rate * CACHE_READ_MULTIPLIER
            + bucket.pop("_billable_output_tokens") * output_rate
        ) / 1_000_000

    return {
        "total_cost": sum(bucket["cost"] for bucket in by_model.values()),
        "equivalent_api_cost": _cli_equivalent_api_cost,
        "by_model": by_model,
    }
