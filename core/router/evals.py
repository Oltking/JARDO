"""Eval harness (spec §5.3): per-task-type accuracy sets, nightly runner.

Case format (JSONL in evals/<task_type>.jsonl):
  {"id": "...", "prompt": "...", "expect_contains": ["substr", ...]}
Scoring: fraction of cases where the reply contains ALL expected substrings
(case-insensitive). Deliberately dumb for the MVP — model-judge scoring can
replace `_score_case` later without touching the runner.

Results land in evals/scores.json:
  {"<task_type>": {"<model>": {"score": 0.9, "threshold": 0.7, "n": 20, "ts": ...}}}
The router consults this file as the accuracy floor (§5.3).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

EVALS_DIR = Path("evals")
SCORES_PATH = EVALS_DIR / "scores.json"
DEFAULT_THRESHOLD = 0.7


@dataclass
class EvalCase:
    id: str
    prompt: str
    expect_contains: list[str]


def load_cases(task_type: str) -> list[EvalCase]:
    path = EVALS_DIR / f"{task_type}.jsonl"
    if not path.exists():
        return []
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            raw = json.loads(line)
            cases.append(EvalCase(raw["id"], raw["prompt"], raw["expect_contains"]))
    return cases


def _score_case(reply: str, case: EvalCase) -> bool:
    lowered = reply.lower()
    return all(expected.lower() in lowered for expected in case.expect_contains)


async def run_eval(task_type: str, model: str, chat_fn, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """chat_fn: async (prompt: str) -> str, bound to a specific backend+model."""
    cases = load_cases(task_type)
    if not cases:
        raise ValueError(f"no eval cases for task type '{task_type}' in {EVALS_DIR}/")
    passed = 0
    for case in cases:
        reply = await chat_fn(case.prompt)
        if _score_case(reply, case):
            passed += 1
    score = passed / len(cases)
    result = {"score": round(score, 4), "threshold": threshold, "n": len(cases),
              "ts": int(time.time())}

    scores = json.loads(SCORES_PATH.read_text()) if SCORES_PATH.exists() else {}
    scores.setdefault(task_type, {})[model] = result
    SCORES_PATH.parent.mkdir(exist_ok=True)
    SCORES_PATH.write_text(json.dumps(scores, indent=2))
    return result
