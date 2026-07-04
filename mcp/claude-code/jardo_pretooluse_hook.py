#!/usr/bin/env python3
"""Claude Code PreToolUse hook → Jardo Agent Supervisor.

Contract source: docs/vendor/claude-code/hooks-reference.md
  - stdin: JSON with tool_name, tool_input, tool_use_id
  - stdout: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
             "permissionDecision": allow|deny|ask, "permissionDecisionReason": ...}}
  - exit 0 with no output = no decision (normal permission flow continues)

Fail-open BY DESIGN: if the Jardo core is down or errors, this hook stays
silent — Claude Code's own permission prompts still guard everything (staying
silent never approves anything, per the hooks doc). Stdlib only; no deps.

Install (merge into ~/.claude/settings.json):  see settings-snippet.json
"""

import json
import sys
import urllib.request

JARDO_SUPERVISE_URL = "http://127.0.0.1:8000/supervise"
TIMEOUT_SECONDS = 10


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # silent: no decision

    payload = json.dumps({
        "actor": "claude-code",
        "tool_name": event.get("tool_name", ""),
        "tool_input": event.get("tool_input", {}) or {},
    }).encode()

    request = urllib.request.Request(
        JARDO_SUPERVISE_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            decision = json.load(response)
    except Exception:
        return 0  # Jardo unreachable → silent → normal permission flow

    if "hookSpecificOutput" in decision:
        json.dump(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
