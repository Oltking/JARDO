"""Multilingual voice (feature: speak Jardo in your own language).

Design: the AI core stays in ENGLISH — all of Jardo's intent parsing, supervisor
prompts, and command logic are English-tuned, so we translate only at the edges.
Your speech is transcribed in your language, translated to English for the core,
and Jardo's English replies are translated back and spoken in your language.

Translation runs on the chat model (Gemma on AMD is multilingual and free), so it
costs nothing extra when the droplet is up.
"""

from core import appsettings

# Curated launch set — each has strong Whisper coverage AND a native macOS voice.
#   code: (English name, native name, whisper language code, macOS `say` voice)
LANGUAGES: dict[str, tuple[str, str, str, str]] = {
    "en": ("English", "English", "en", "Samantha"),
    "fr": ("French", "Français", "fr", "Amelie"),
    "es": ("Spanish", "Español", "es", "Monica"),
    "de": ("German", "Deutsch", "de", "Anna"),
    "pt": ("Portuguese", "Português", "pt", "Luciana"),
    "it": ("Italian", "Italiano", "it", "Alice"),
    "ar": ("Arabic", "العربية", "ar", "Majed"),
    "hi": ("Hindi", "हिन्दी", "hi", "Lekha"),
    "zh": ("Chinese", "中文", "zh", "Tingting"),
}

DEFAULT = "en"


def normalize(code: str | None) -> str:
    code = (code or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT


def current() -> str:
    return normalize(appsettings.get("language", DEFAULT))


def set_language(code: str) -> str:
    code = normalize(code)
    appsettings.set("language", code)
    return code


def english_name(code: str) -> str:
    return LANGUAGES.get(normalize(code), LANGUAGES[DEFAULT])[0]


def whisper_lang(code: str) -> str:
    return LANGUAGES.get(normalize(code), LANGUAGES[DEFAULT])[2]


def macos_voice(code: str) -> str:
    return LANGUAGES.get(normalize(code), LANGUAGES[DEFAULT])[3]


def catalog() -> list[dict]:
    """For the onboarding picker."""
    return [{"code": c, "name": v[0], "native": v[1]} for c, v in LANGUAGES.items()]


async def translate(text: str, target: str, chat_fn) -> str:
    """Translate `text` into `target` language using the chat model. No-op for
    empty text or English↔English. `chat_fn`: async (prompt:str) -> str.
    Best-effort — on any error, returns the original text (never breaks the turn)."""
    text = (text or "").strip()
    target = normalize(target)
    if not text or target == "en":
        return text
    lang = english_name(target)
    prompt = (
        f"Translate the following text into {lang}. Preserve meaning, tone, and any "
        f"code, commands, file paths, or names EXACTLY. Output ONLY the translation, "
        f"with no quotes, notes, or explanation.\n\n{text}"
    )
    try:
        out = (await chat_fn(prompt)).strip()
        return out or text
    except Exception:  # noqa: BLE001 — translation must never break the turn
        return text


async def to_english(text: str, source: str, chat_fn) -> str:
    """Translate the user's speech (in `source` language) into English for the core.
    No-op when the source is English."""
    text = (text or "").strip()
    source = normalize(source)
    if not text or source == "en":
        return text
    prompt = (
        f"Translate the following {english_name(source)} text into English. Preserve "
        f"meaning and any code, commands, file paths, or names EXACTLY. Output ONLY "
        f"the English translation, no quotes or notes.\n\n{text}"
    )
    try:
        out = (await chat_fn(prompt)).strip()
        return out or text
    except Exception:  # noqa: BLE001
        return text
