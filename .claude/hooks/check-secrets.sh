#!/bin/bash
# PreToolUse hook: blocks `git commit` if the staged diff contains anything
# that looks like a credential. Automates the manual `grep -l "sk-ant\|
# postgresql://"` check that was previously run by hand before every push.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Not a git repo, or nothing staged - nothing to check.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

PATTERN='sk-ant-[A-Za-z0-9_-]{20,}|postgresql://[^[:space:]@]+:[^[:space:]@]+@'

MATCHES=$(git diff --cached | grep -nE "$PATTERN" || true)

if [ -n "$MATCHES" ]; then
    echo "BLOCKED: staged changes appear to contain a credential (API key or DB connection string with embedded password):" >&2
    echo "$MATCHES" >&2
    echo "" >&2
    echo "Remove the secret from the diff (it likely belongs in the gitignored .env) before committing." >&2
    exit 2
fi

exit 0
