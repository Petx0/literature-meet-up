#!/bin/bash
# PostToolUse hook: after an Edit/Write to a pipeline .py file, run a quick
# syntax check so a typo surfaces immediately instead of at the next manual
# run. Non-blocking by design (PostToolUse can't block - the edit already
# happened) - this only prints a warning.
set -uo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null || true)

if [ -z "$FILE" ] || [[ "$FILE" != *.py ]]; then
    exit 0
fi

case "$FILE" in
    literature_meetup/*|*/literature_meetup/*|webapp/*|*/webapp/*) ;;
    *) exit 0 ;;
esac

if ! python3 -m py_compile "$FILE" 2>/tmp/py_syntax_check_err; then
    echo "Warning: $FILE failed a syntax check after this edit:" >&2
    cat /tmp/py_syntax_check_err >&2
fi

exit 0
