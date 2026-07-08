"""Supervision comprehension parser: extract a rich, structured read (state +
activity + command + issue + progress), flag notable states, fail safe to idle."""

from core.observer import NOTABLE, build_messages, parse_observation


def test_extracts_the_full_structured_read():
    p = parse_observation(
        '{"state":"error","activity":"running tests","last_command":"pytest -q",'
        '"issue":"ModuleNotFoundError: no module named foo","progress":"",'
        '"note":"A test import is failing."}')
    assert p["state"] == "error" and p["notable"] is True
    assert p["activity"] == "running tests"
    assert p["last_command"] == "pytest -q"
    assert "ModuleNotFoundError" in p["issue"]
    assert "import is failing" in p["note"]


def test_progress_and_quiet_states():
    p = parse_observation(
        '{"state":"progressing","activity":"editing app.py","last_command":"",'
        '"issue":"","progress":"3 files changed","note":""}')
    assert p["state"] == "progressing" and p["notable"] is False
    assert p["progress"] == "3 files changed"


def test_done_is_notable():
    p = parse_observation('{"state":"done","progress":"12 tests passed"}')
    assert p["state"] == "done" and p["notable"] is True
    assert p["progress"] == "12 tests passed"
    assert p["activity"] == ""  # missing fields default to empty, never absent


def test_fails_safe_and_fills_every_field():
    for bad in ("", "no json", '{"state":"launch"}', "{broken"):
        p = parse_observation(bad)
        assert p["state"] == "idle"
        # every field is always present (the UI can rely on it)
        for f in ("activity", "last_command", "issue", "progress", "note", "notable"):
            assert f in p


def test_notable_set_and_messages():
    assert NOTABLE == {"stuck", "off_task", "done", "error"}
    msgs = build_messages("build a todo API", "pytest -q\n2 failed")
    assert "build a todo API" in msgs[1]["content"] and "2 failed" in msgs[1]["content"]
