import json

import pytest

import core.router.evals as evals_module
from core.router.evals import load_cases, run_eval


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    monkeypatch.setattr(evals_module, "EVALS_DIR", tmp_path)
    monkeypatch.setattr(evals_module, "SCORES_PATH", tmp_path / "scores.json")
    (tmp_path / "demo.jsonl").write_text(
        '{"id": "a", "prompt": "2+2?", "expect_contains": ["4"]}\n'
        '{"id": "b", "prompt": "capital of France?", "expect_contains": ["Paris"]}\n'
    )
    return tmp_path


async def test_run_eval_scores_and_persists(eval_env):
    async def perfect(prompt: str) -> str:
        return "The answer is 4, or Paris, whichever you asked."

    result = await run_eval("demo", "test-model", perfect)
    assert result["score"] == 1.0

    scores = json.loads((eval_env / "scores.json").read_text())
    assert scores["demo"]["test-model"]["score"] == 1.0
    assert scores["demo"]["test-model"]["n"] == 2


async def test_run_eval_partial_score_case_insensitive(eval_env):
    async def half(prompt: str) -> str:
        return "paris"  # lowercase still matches; misses the math case

    result = await run_eval("demo", "test-model", half)
    assert result["score"] == 0.5


async def test_missing_eval_set_raises(eval_env):
    async def noop(prompt: str) -> str:
        return ""
    with pytest.raises(ValueError, match="no eval cases"):
        await run_eval("nonexistent", "m", noop)


def test_load_real_eval_sets():
    # the repo ships trivial + routine sets (spec §5.3: 20–50 cases across types)
    assert len(load_cases("trivial")) == 10
    assert len(load_cases("routine")) == 10
