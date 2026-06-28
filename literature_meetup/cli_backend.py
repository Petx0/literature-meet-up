"""Runs a single structured prompt through the locally-installed `claude`
CLI (via claude-agent-sdk) instead of the Anthropic API, so a stage's call
can be billed against a Claude Pro/Max subscription instead of per-token.
See LLM_BACKEND in model_config.py for how a stage opts into this path.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time

_SETUP_HINT = (
    "`npm install -g @anthropic-ai/claude-code`, `claude login`, "
    "`pip install claude-agent-sdk`."
)

# HTTP statuses worth retrying - transient overload/rate-limit, not a
# malformed request or auth failure.
_TRANSIENT_API_ERROR_STATUSES = {429, 500, 529}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (15, 60, 180)

# Process-lifetime running total of result_message.total_cost_usd across
# every successful run_cli_query call, regardless of which book it
# belongs to - deliberately NOT the same counter as usage_tracker, which
# resets per book and so can't see usage accumulating across a whole
# multi-book run. See CLI_SESSION_BUDGET_USD below.
_session_equivalent_cost_usd = 0.0

# Optional proactive ceiling on _session_equivalent_cost_usd, read once at
# import time. None (the default - unset) disables this check entirely,
# since there's no reliable a-priori number for the real subscription
# quota; set it empirically from a prior run's reported equivalent_api_cost.
CLI_SESSION_BUDGET_USD = (
    float(os.environ["CLI_SESSION_BUDGET_USD"]) if os.environ.get("CLI_SESSION_BUDGET_USD") else None
)


class CliStopBatchError(RuntimeError):
    """Base class for failures that mean every subsequent CLI call this
    session will also fail (or shouldn't be attempted) - callers should
    catch this to stop a whole batch run rather than skip to the next book.
    """


class CliRateLimitedError(CliStopBatchError):
    """Raised when the underlying API call behind the CLI keeps failing
    with a transient (rate-limit/overload) status after every retry -
    distinct from a generic CLI failure so callers can stop a whole batch
    run instead of uselessly burning through the remaining books against
    the same rate limit.
    """

    def __init__(self, api_error_status: int | None, attempts: int):
        self.api_error_status = api_error_status
        super().__init__(
            f"Claude CLI API call still failing after {attempts} attempts "
            f"(HTTP {api_error_status}) - likely a sustained rate limit/overload."
        )


class CliBudgetExceededError(CliStopBatchError):
    """Raised proactively, before attempting a call, when
    _session_equivalent_cost_usd has reached CLI_SESSION_BUDGET_USD - stops
    the batch before the call that would likely get rate-limited anyway.
    """

    def __init__(self, used: float, budget: float):
        self.used = used
        self.budget = budget
        super().__init__(
            f"CLI_SESSION_BUDGET_USD (${budget:.2f}) reached - ${used:.2f} of "
            f"equivalent API cost used this run. Stopping before the call that "
            f"would likely hit the real rate limit anyway; re-run later in a "
            f"new usage window."
        )


def _check_cli_available(cli_path: str | None) -> None:
    """Fails fast with a clear error instead of letting claude_agent_sdk
    hang indefinitely when the CLI is missing or not on PATH.
    """
    cmd = cli_path or shutil.which("claude")
    if cmd is None:
        raise RuntimeError(f"claude CLI not found on PATH. Setup: {_SETUP_HINT}")
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=5, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"claude CLI at {cmd!r} did not respond to --version. Setup: {_SETUP_HINT}") from exc


def _run_cli_query_once(system_prompt: str, user_content: str, model: str):
    """Single attempt, no retry. Returns (response_text, result_message) on
    success. On failure, raises with a message built from the SDK's own
    ResultMessage fields instead of letting the SDK's generic
    "Claude Code returned an error result: {subtype}" propagate - that
    text is misleading on its own: per claude_agent_sdk's ResultMessage
    docstring, when the underlying API call fails (e.g. 429/500/529),
    is_error=True but subtype is still "success", with the real HTTP
    status in api_error_status. Re-raises unchanged if the failure wasn't
    an API error result (e.g. CLI crashed before emitting one).

    allowed_tools=[] keeps this non-agentic - no file edits or shell
    commands, regardless of max_turns. max_turns=3 (rather than 1) gives
    the model room to continue when a single chapter's extraction output
    is large enough to need a follow-up turn (seen on dense chapters of
    long novels, e.g. Crime and Punishment) - allowed_tools=[] still means
    those extra turns can only be more plain-text continuation, never
    tool use. permission_mode="bypassPermissions" avoids the default mode's
    interactive-confirmation hang risk in unattended batch runs.
    env blanks ANTHROPIC_API_KEY for the subprocess specifically - the CLI
    prefers an API key over subscription/OAuth login when one is present,
    and ClaudeAgentOptions.env merges on top of (not replacing) the
    inherited environment, so omitting the key here would NOT be enough;
    it must be explicitly overridden to force subscription billing.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )
    except ImportError as exc:
        raise ImportError(f"LLM_BACKEND=cli requires claude-agent-sdk and the claude CLI. Setup: {_SETUP_HINT}") from exc

    _check_cli_available(None)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        allowed_tools=[],
        max_turns=3,
        permission_mode="bypassPermissions",
        env={"ANTHROPIC_API_KEY": ""},
    )

    async def _run():
        text_parts = []
        result_message = None
        try:
            async for message in query(prompt=user_content, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    result_message = message
        except Exception as exc:
            if result_message is not None and result_message.is_error:
                raise RuntimeError(
                    f"Claude CLI API call failed (HTTP {result_message.api_error_status}, "
                    f"subtype={result_message.subtype!r}): {result_message.errors}"
                ) from exc
            raise
        return "".join(text_parts), result_message

    return asyncio.run(_run())


def run_cli_query(system_prompt: str, user_content: str, model: str):
    """Returns (response_text, result_message) - see _run_cli_query_once.

    Checks CLI_SESSION_BUDGET_USD first (if set) and raises
    CliBudgetExceededError immediately, without attempting a call, once the
    process-lifetime _session_equivalent_cost_usd reaches it - cheaper than
    finding out the same thing via a 429.

    Otherwise retries up to _MAX_ATTEMPTS times with backoff
    (_BACKOFF_SECONDS) when the failure is a transient API error
    (429/500/529 - see _TRANSIENT_API_ERROR_STATUSES), since those clear on
    their own given enough time. Any other failure raises immediately,
    unretried. If every attempt still fails with a transient status, raises
    CliRateLimitedError instead of the last RuntimeError, so callers can
    distinguish "still rate-limited after backoff" from a one-off failure
    and stop a whole batch run rather than burning through the rest of it
    against the same wall.
    """
    global _session_equivalent_cost_usd

    if CLI_SESSION_BUDGET_USD is not None and _session_equivalent_cost_usd >= CLI_SESSION_BUDGET_USD:
        raise CliBudgetExceededError(_session_equivalent_cost_usd, CLI_SESSION_BUDGET_USD)

    last_status = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response_text, result_message = _run_cli_query_once(system_prompt, user_content, model)
            _session_equivalent_cost_usd += getattr(result_message, "total_cost_usd", None) or 0.0
            return response_text, result_message
        except RuntimeError as exc:
            api_error_status = _extract_api_error_status(exc)
            if api_error_status not in _TRANSIENT_API_ERROR_STATUSES:
                raise
            last_status = api_error_status
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
    raise CliRateLimitedError(last_status, _MAX_ATTEMPTS)


def _extract_api_error_status(exc: RuntimeError) -> int | None:
    """Pulls the HTTP status back out of the message _run_cli_query_once
    raises - simpler than threading the ResultMessage itself through the
    exception chain, and the message format is fully controlled above.
    """
    match = re.search(r"HTTP (\d+|None)", str(exc))
    if match is None or match.group(1) == "None":
        return None
    return int(match.group(1))
