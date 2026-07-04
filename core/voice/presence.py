"""Presence-confirmation ritual (spec §8, verbatim behavior).

When Jardo is about to engage a task autonomously and voice is enabled, it
speaks the plan and asks the owner to say their own name to confirm presence.
On ~10s silence it says the silence line and proceeds ONLY within pre-approved
policy bounds; anything needing live consent is queued for the owner.

CRITICAL (SECURITY.md rule 6, §4.1): saying the name establishes **presence, not
identity**. A spoken name is trivially spoofable, so this ritual never authorizes
a destructive action — those still require TOTP. The outcome only decides whether
Jardo may proceed autonomously-within-policy vs. wait for live consent.

Pure logic: `speak_fn` and `listen_for_name_fn` are injected, so the ritual is
fully testable without audio hardware. The voice loop wires in the real TTS/STT.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

SILENCE_TIMEOUT_SECONDS = 10.0


class Presence(StrEnum):
    PRESENT = "present"    # owner confirmed → live consent available
    ABSENT = "absent"      # silence → proceed within policy only, queue the rest


def silence_line(pronoun_style: str) -> str:
    honorific = "ma" if pronoun_style == "ma" else "sir"
    return (f"I'll assume you are not there and carry out my diligent duties "
            f"for you, {honorific}.")


def _name_matches(heard: str, owner_name: str) -> bool:
    heard_tokens = {t for t in heard.lower().replace(".", " ").split() if t}
    name_tokens = {t for t in owner_name.lower().split() if t}
    # Match on any name token (first name is enough to confirm presence).
    return bool(heard_tokens & name_tokens)


@dataclass
class PresenceResult:
    presence: Presence
    heard: str | None
    live_consent_available: bool
    spoken_lines: list[str]


def run_presence_ritual(
    owner_name: str,
    pronoun_style: str,
    plan: str,
    speak_fn: Callable[[str], None],
    listen_for_name_fn: Callable[[float], str | None],
    timeout_seconds: float = SILENCE_TIMEOUT_SECONDS,
) -> PresenceResult:
    """Run the ritual. listen_for_name_fn(timeout) returns the transcribed
    utterance or None on silence/timeout."""
    honorific = "ma" if pronoun_style == "ma" else "sir"
    spoken: list[str] = []

    def say(line: str) -> None:
        spoken.append(line)
        speak_fn(line)

    say(f"Here is my plan, {honorific}: {plan}")
    say(f"Please say your name to confirm you are present.")

    heard = listen_for_name_fn(timeout_seconds)

    if heard and _name_matches(heard, owner_name):
        say(f"Thank you, {owner_name}. Proceeding with you present.")
        return PresenceResult(Presence.PRESENT, heard, True, spoken)

    # Silence, timeout, or a non-matching utterance → assume absent.
    line = silence_line(pronoun_style)
    say(line)
    return PresenceResult(Presence.ABSENT, heard, False, spoken)
