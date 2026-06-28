"""Single call site every Claude-calling stage goes through, so the
api/cli backend switch (LLM_BACKEND in model_config.py) and the one piece
of complexity it adds - turning a tool schema into a CLI prompt
instruction, then defensively parsing the response back into that shape -
lives in one place instead of being duplicated across stages.
"""
from __future__ import annotations

import json
import re

from literature_meetup import cli_backend
from literature_meetup.model_config import LLM_BACKEND
from literature_meetup.usage_tracker import record as record_usage
from literature_meetup.usage_tracker import record_cli

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Mirrors this repo's existing pattern of defending against model
    non-compliance in code rather than prompt wording alone (see
    analyze_pipeline.py): strips a markdown code fence if present, then
    falls back to locating the outermost {...} span, before parsing.
    """
    fence_match = _JSON_FENCE_RE.search(text)
    candidate = fence_match.group(1) if fence_match else text.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in CLI response: {text!r}")
    return json.loads(candidate[start : end + 1])


def _cli_instructions(tool: dict) -> str:
    return (
        f"\n\nRespond with ONLY a single raw JSON object matching this schema "
        f"(no markdown code fences, no commentary, no other text):\n"
        f"Schema for `{tool['name']}` ({tool['description']}):\n"
        f"{json.dumps(tool['input_schema'], separators=(',', ':'))}"
    )


def call_tool(
    client, model: str, system_prompt: str, tool: dict, user_content: str | list[dict], max_tokens: int = 8000
) -> dict:
    """Sends one structured-extraction call and returns the parsed input
    dict - equivalent to today's `tool_use.input` from the Messages API,
    regardless of which backend actually served the call.

    user_content is usually a plain string, but callers that want a second
    cache_control breakpoint within the user turn (extraction's growing,
    append-only story_state - see chapter_analyzer.py) can instead pass a
    list of Messages API content blocks. The CLI backend has no concept of
    cache breakpoints, so blocks are flattened back into plain text there.
    """
    if LLM_BACKEND == "cli":
        text_content = (
            user_content if isinstance(user_content, str) else "".join(block["text"] for block in user_content)
        )
        full_user_content = text_content + _cli_instructions(tool)
        response_text, result_message = cli_backend.run_cli_query(system_prompt, full_user_content, model)
        record_cli(model, result_message)
        return _extract_json(response_text)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_content}],
    )

    record_usage(model, response.usage)
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return tool_use.input
