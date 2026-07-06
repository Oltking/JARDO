"""TOTP destructive-action gate (spec §4.1).

The primary gate for destructive / high-privilege actions: a fresh 6-digit code
from the owner's authenticator app. RFC 6238 implemented with the standard
library (no dependency); the shared secret lives in the OS Keychain, never in a
file (SECURITY.md rule 3).

Flow: `enroll()` generates a secret, stores it, and returns an otpauth:// URI the
owner adds to Google Authenticator / 1Password. `verify(code)` checks a code
(±1 time-step for clock skew). Destructive actions Jardo would otherwise refuse
can be authorized by a valid code (owner explicitly present and consenting).
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote

from core import secrets

_STEP = 30
_DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** _DIGITS)
    return str(code).zfill(_DIGITS)


def totp_now(secret: str) -> str:
    return _hotp(secret, int(time.time()) // _STEP)


def verify_code(secret: str, code: str, window: int = 1) -> bool:
    if not code or not code.strip().isdigit():
        return False
    code = code.strip().zfill(_DIGITS)
    counter = int(time.time()) // _STEP
    return any(hmac.compare_digest(_hotp(secret, counter + i), code)
               for i in range(-window, window + 1))


def provisioning_uri(secret: str, account: str, issuer: str = "Jardo") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret}&issuer={quote(issuer)}&digits={_DIGITS}&period={_STEP}")


# ---- enrollment + gate (Keychain-backed) --------------------------------

def is_enrolled() -> bool:
    return secrets.read_secret(secrets.TOTP_SECRET) is not None


def enroll(account: str) -> str:
    """Generate + store a TOTP secret; return the otpauth URI to add to an app."""
    secret = generate_secret()
    secrets.write_secret(secrets.TOTP_SECRET, secret)
    return provisioning_uri(secret, account)


def verify(code: str) -> bool:
    """Verify a code against the enrolled secret. False if not enrolled."""
    secret = secrets.read_secret(secrets.TOTP_SECRET)
    if not secret:
        return False
    return verify_code(secret, code)
