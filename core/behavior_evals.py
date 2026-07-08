"""Behavioural evals — the 'measure it' training.

Scores Jardo's two most important learned behaviours so improvements are provable
and regressions are caught:

  - safety:  command -> auto-approvable? (rule-based scan + allowlist). Fully
             deterministic — no model, no network — so it runs in CI and a single
             regression in the guardrails fails the build.
  - intents: utterance -> intent (via the model router). Needs a capable model,
             so it runs only when one is configured.

Case files live in evals/<name>.jsonl.
"""

import json
from pathlib import Path

from core.sentinel.checks import is_recognizably_safe, scan_dangerous_patterns
from core.sentinel.models import ActionRequest, Severity

EVALS_DIR = Path("evals")
_BLOCKING = (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)


def _load(name: str) -> list[dict]:
    path = EVALS_DIR / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def auto_approvable(command: str) -> bool:
    """The exact rule the unattended supervisor uses: not dangerous AND on the
    recognized-safe allowlist."""
    findings = scan_dangerous_patterns(ActionRequest("agent", "shell.run", command, ""))
    dangerous = any(f.severity in _BLOCKING for f in findings)
    return (not dangerous) and is_recognizably_safe(command)


def run_safety_eval() -> dict:
    cases = _load("safety")
    passed, misses = 0, []
    for c in cases:
        got = "approve" if auto_approvable(c["command"]) else "decline"
        if got == c["expect"]:
            passed += 1
        else:
            misses.append({"command": c["command"], "expected": c["expect"], "got": got})
    n = len(cases)
    return {"name": "safety", "n": n, "passed": passed,
            "score": round(passed / n, 4) if n else 0.0, "misses": misses}


async def run_intent_eval(route_fn) -> dict:
    """route_fn: async (utterance) -> {"intent": ...}. Skipped (n=0) if no cases."""
    cases = _load("intents")
    passed, misses = 0, []
    for c in cases:
        result = await route_fn(c["utterance"])
        got = (result or {}).get("intent", "chat")
        if got == c["expect"]:
            passed += 1
        else:
            misses.append({"utterance": c["utterance"], "expected": c["expect"], "got": got})
    n = len(cases)
    return {"name": "intents", "n": n, "passed": passed,
            "score": round(passed / n, 4) if n else 0.0, "misses": misses}
