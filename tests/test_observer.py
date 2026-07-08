"""Supervision comprehension parser: extract a clean state + flag notable ones,
fail safe to idle on garbage."""

from core.observer import NOTABLE, build_messages, parse_observation


def test_parses_states_and_flags_notable():
    p = parse_observation('{"state":"stuck","note":"Same import error 5 times."}')
    assert p["state"] == "stuck" and p["notable"] is True
    assert "import error" in p["note"]

    d = parse_observation('{"state":"done","note":"Tests pass."}')
    assert d["state"] == "done" and d["notable"] is True

    g = parse_observation('{"state":"progressing","note":"Writing the router."}')
    assert g["state"] == "progressing" and g["notable"] is False


def test_extracts_from_prose_and_fails_safe():
    assert parse_observation('here: {"state":"off_task"} ok')["state"] == "off_task"
    assert parse_observation("no json")["state"] == "idle"
    assert parse_observation("")["state"] == "idle"
    assert parse_observation('{"state":"launch"}')["state"] == "idle"  # unknown → idle


def test_notable_set_is_the_interrupt_worthy_ones():
    assert NOTABLE == {"stuck", "off_task", "done"}


def test_build_messages_includes_goal_and_output():
    msgs = build_messages("build a todo API", "npm run build\nDone in 2s")
    assert msgs[0]["role"] == "system"
    assert "build a todo API" in msgs[1]["content"]
    assert "Done in 2s" in msgs[1]["content"]
