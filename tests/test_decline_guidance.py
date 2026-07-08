"""When Jardo declines a command, it must guide the agent to adapt and continue —
so supervision keeps the work moving instead of stalling it."""

from core.supervision import decline_guidance


def test_guidance_names_the_reason_and_the_goal():
    g = decline_guidance("pkill -9 -f server", "not a recognizably-safe command",
                         "build the todo API")
    assert "not a recognizably-safe command" in g
    assert "build the todo API" in g
    assert "keep working toward" in g.lower() or "continue" in g.lower()


def test_guidance_has_a_fallback_goal_when_none_set():
    g = decline_guidance("rm -rf build", "unsafe to run unattended", "")
    assert "what you were working on" in g
    # It tells the agent NOT to run it and to move on — never leaves it hanging.
    assert "don't run it" in g.lower()
