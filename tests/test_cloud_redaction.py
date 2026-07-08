"""Audit HIGH: credential-shaped content read from the terminal must be redacted
before it crosses to the cloud model (alignment + observation paths)."""

from core.sentinel.checks import redact


async def test_alignment_redacts_secrets_before_cloud():
    captured = {}

    async def fake_chat(prompt: str) -> str:
        captured["prompt"] = prompt
        return "ALIGNED"

    from core.supervision import judge_alignment
    secret = "sk-abc1234567890abcdefghij"
    await judge_alignment("build the API",
                          f"curl -H 'Authorization: Bearer {secret}' https://x",
                          chat_fn=fake_chat)
    assert secret not in captured["prompt"], "secret leaked to the cloud prompt"
    assert "[REDACTED]" in captured["prompt"]


def test_redact_catches_common_credential_shapes():
    for s in ("sk-abc1234567890abcdefgh", "api_key_ABCDEF1234567890",
              "token-0123456789abcdef01"):
        assert "[REDACTED]" in redact(f"export KEY={s}"), s
    # A private key block is redacted too.
    assert "[REDACTED]" in redact("-----BEGIN OPENSSH PRIVATE KEY-----\nxxxx")
    # Ordinary output is untouched.
    assert redact("pytest -q\n12 passed") == "pytest -q\n12 passed"
