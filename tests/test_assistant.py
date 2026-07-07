"""The tool-use intent parser must extract clean intents and fail safe to chat."""

from core.assistant import build_messages, parse_intent


def test_parses_each_intent():
    assert parse_intent('{"intent":"resume"}')["intent"] == "resume"
    assert parse_intent('{"intent":"stop"}')["intent"] == "stop"
    s = parse_intent('{"intent":"supervise","agent":"Gemini"}')
    assert s["intent"] == "supervise" and s["agent"] == "gemini"  # normalised
    n = parse_intent('{"intent":"new_project","agent":"claude","goal":"a todo app"}')
    assert n["intent"] == "new_project" and n["goal"] == "a todo app"


def test_extracts_json_from_surrounding_prose():
    raw = 'Sure! Here is the intent: {"intent":"resume"}  hope that helps'
    assert parse_intent(raw)["intent"] == "resume"


def test_unknown_or_garbage_defaults_to_chat():
    assert parse_intent("")["intent"] == "chat"
    assert parse_intent("no json here")["intent"] == "chat"
    assert parse_intent('{"intent":"launch_missiles"}')["intent"] == "chat"
    assert parse_intent("{bad json")["intent"] == "chat"


def test_agent_and_goal_are_optional():
    out = parse_intent('{"intent":"supervise"}')
    assert "agent" not in out and "goal" not in out


def test_build_messages_shape():
    msgs = build_messages("where was I?")
    assert msgs[0]["role"] == "system" and msgs[1]["content"] == "where was I?"
