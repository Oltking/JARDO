"""Claude Code PreToolUse hook → Jardo Agent Supervisor (packaged as a module so
it works from any install location; exposed as the `jardo-hook` console script).

Contract: docs/vendor/claude-code/hooks-reference.md
  - stdin: JSON with tool_name, tool_input, tool_use_id
  - stdout: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
             "permissionDecision": allow|deny|ask, "permissionDecisionReason": ...}}
  - exit 0 with no output = no decision (normal permission flow continues)

Fail-open BY DESIGN: if the Jardo core is down/unreachable this hook stays silent,
so Claude Code's own prompts still guard everything (silence never approves).
Stdlib only — Claude Code runs it in a bare environment. Core URL overridable via
JARDO_CORE_URL.
"""

import json
import os
import sys
import urllib.request


def _supervise_url() -> str:
    base = os.environ.get("JARDO_CORE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/supervise"


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    payload = json.dumps({
        "actor": "claude-code",
        "tool_name": event.get("tool_name", ""),
        "tool_input": event.get("tool_input", {}) or {},
    }).encode()
    request = urllib.request.Request(
        _supervise_url(), data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            decision = json.load(response)
    except Exception:  # noqa: BLE001 — any failure → silent → normal permission flow
        return 0

    if isinstance(decision, dict) and "hookSpecificOutput" in decision:
        json.dump(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
