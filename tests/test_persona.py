from types import SimpleNamespace

from core.persona import build_system_prompt


def _owner(pronoun="ma", name="Ada"):
    return SimpleNamespace(name=name, pronoun_style=pronoun)


def test_honorific_follows_owner_record():
    assert "'ma'" in build_system_prompt(_owner("ma"), [])
    assert "'sir'" in build_system_prompt(_owner("sir"), [])


def test_unknown_pronoun_defaults_to_sir():
    assert "'sir'" in build_system_prompt(_owner("other"), [])


def test_facts_injected():
    facts = [SimpleNamespace(content="Owner builds Jardo"),
             SimpleNamespace(content="Prefers macOS")]
    prompt = build_system_prompt(_owner(), facts)
    assert "- Owner builds Jardo" in prompt
    assert "- Prefers macOS" in prompt


def test_no_facts_section_when_empty():
    assert "Durable facts" not in build_system_prompt(_owner(), [])
