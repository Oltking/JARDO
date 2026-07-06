"""TOTP gate: RFC-6238 codes and owner-authorized destructive actions."""

import sys

import pytest

from core import totp
from core.autonomy.decider import autonomous_decision
from core.schema import Owner

pytestmark_darwin = pytest.mark.skipif(sys.platform != "darwin",
                                       reason="Keychain-backed enroll is macOS-only")


# ---- RFC 6238 primitives (no Keychain) -----------------------------------

def test_generated_code_verifies():
    secret = totp.generate_secret()
    code = totp.totp_now(secret)
    assert totp.verify_code(secret, code) is True


def test_wrong_code_rejected():
    secret = totp.generate_secret()
    assert totp.verify_code(secret, "000000") is False
    assert totp.verify_code(secret, "") is False
    assert totp.verify_code(secret, "abc") is False


def test_provisioning_uri_shape():
    uri = totp.provisioning_uri("ABC234", "me@example.com")
    assert uri.startswith("otpauth://totp/Jardo:")
    assert "secret=ABC234" in uri


def test_known_vector():
    # RFC 6238 test secret "12345678901234567890" (base32) at t=59 → 94287082
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp._hotp(secret, 59 // 30) == "287082"


# ---- decider integration (TOTP authorizes a risky action) ----------------

async def _owner(session) -> Owner:
    owner = Owner(name="O", pronoun_style="sir", email="o@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


async def test_totp_authorizes_blocked_action(session, monkeypatch):
    await _owner(session)
    # sudo is normally refused unattended; a valid TOTP authorizes it.
    monkeypatch.setattr("core.totp.verify", lambda code: code == "123456")
    denied = await autonomous_decision(session, "sudo apt update", "update packages")
    assert denied.approve is False
    allowed = await autonomous_decision(session, "sudo apt update", "update packages",
                                        totp_code="123456")
    assert allowed.approve is True
    assert "TOTP" in allowed.reason


async def test_forbidden_action_never_authorized_even_with_totp(session, monkeypatch):
    await _owner(session)
    monkeypatch.setattr("core.totp.verify", lambda code: True)
    d = await autonomous_decision(session, "nmap -sS 10.0.0.1", "scan the network",
                                  totp_code="123456")
    assert d.approve is False
    assert "forbidden" in d.reason
