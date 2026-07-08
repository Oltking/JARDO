"""The safety eval is the guardrail's regression test: it must score a perfect
100% at all times. If a future change to the danger scan or allowlist lets a
destructive command through (or wrongly declines safe dev work), this fails."""

from core.behavior_evals import run_safety_eval


def test_safety_eval_is_perfect():
    result = run_safety_eval()
    assert result["n"] >= 30, "safety eval set should be substantial"
    assert result["score"] == 1.0, f"safety regressions: {result['misses']}"


def test_safety_eval_covers_both_outcomes():
    # Make sure the set actually exercises approve AND decline (not all one way).
    from core.behavior_evals import _load
    expects = {c["expect"] for c in _load("safety")}
    assert expects == {"approve", "decline"}


def test_intent_and_alignment_sets_are_present_and_balanced():
    from core.behavior_evals import _load
    intents = _load("intents")
    assert {c["expect"] for c in intents} >= {"resume", "supervise", "new_project",
                                              "stop", "chat"}
    align = _load("alignment")
    assert {c["expect"] for c in align} == {"aligned", "off-task"}
