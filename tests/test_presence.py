"""Presence-confirmation ritual (spec §8) — pure logic, no audio hardware."""

from core.voice.presence import (
    Presence,
    run_presence_ritual,
    silence_line,
)


def _fake_speak(collected):
    def speak(line):
        collected.append(line)
    return speak


def test_silence_line_uses_honorific():
    assert silence_line("sir").endswith("sir.")
    assert silence_line("ma").endswith("ma.")
    assert "diligent duties" in silence_line("sir")  # verbatim spec phrase


def test_owner_present_when_name_spoken():
    spoken = []
    result = run_presence_ritual(
        owner_name="Ada Lovelace", pronoun_style="ma", plan="deploy the build",
        speak_fn=_fake_speak(spoken),
        listen_for_name_fn=lambda timeout: "Ada",
    )
    assert result.presence == Presence.PRESENT
    assert result.live_consent_available is True
    assert any("deploy the build" in line for line in spoken)


def test_first_name_alone_confirms():
    result = run_presence_ritual(
        "Grace Hopper", "ma", "run backups",
        speak_fn=lambda l: None,
        listen_for_name_fn=lambda t: "grace",
    )
    assert result.presence == Presence.PRESENT


def test_silence_yields_absent_and_speaks_silence_line():
    spoken = []
    result = run_presence_ritual(
        owner_name="Tony", pronoun_style="sir", plan="tidy the inbox",
        speak_fn=_fake_speak(spoken),
        listen_for_name_fn=lambda timeout: None,  # silence/timeout
    )
    assert result.presence == Presence.ABSENT
    assert result.live_consent_available is False  # proceed within policy only
    assert silence_line("sir") in spoken


def test_wrong_utterance_treated_as_absent():
    result = run_presence_ritual(
        "Tony Stark", "sir", "do the thing",
        speak_fn=lambda l: None,
        listen_for_name_fn=lambda t: "what is going on",  # not the name
    )
    assert result.presence == Presence.ABSENT


def test_ritual_always_speaks_plan_and_prompt():
    spoken = []
    run_presence_ritual(
        "Pat", "sir", "reconcile the ledger",
        speak_fn=_fake_speak(spoken),
        listen_for_name_fn=lambda t: None,
    )
    assert any("plan" in line.lower() for line in spoken)
    assert any("say your name" in line.lower() for line in spoken)
