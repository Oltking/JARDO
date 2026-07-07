"""Secret storage backed by the macOS Keychain.

Uses the `security(1)` CLI — no third-party dependency, no secrets in files.
Source: docs/vendor/computer-use/macos-security-keychain-cli.md
  - `add-generic-password [-a account] [-s service] [-w password] [-U]`
    (-U updates the item if it already exists)
  - `find-generic-password [-a account] [-s service] [-w]`
    (-w prints only the password to stdout)
  - `delete-generic-password [-a account] [-s service]`

Every secret read is an auditable event (SECURITY.md rule 5); callers go through
read_secret() so Phase 3 can hook the audit log in one place.
"""

import subprocess
import sys

_ACCOUNT = "jardo"

FIREWORKS_API_KEY = "jardo.fireworks_api_key"
AMD_API_KEY = "jardo.amd_api_key"
DEVICE_PRIVATE_KEY = "jardo.device_private_key"
TOTP_SECRET = "jardo.totp_secret"


class SecretsUnavailableError(RuntimeError):
    """Raised when the platform keychain is not usable."""


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise SecretsUnavailableError(
            "core.secrets currently supports macOS Keychain only (macOS-first, spec §3)."
        )


def write_secret(service: str, value: str) -> None:
    _require_macos()
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", _ACCOUNT, "-s", service, "-w", value],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SecretsUnavailableError(f"keychain write failed for {service}: {result.stderr.strip()}")


def read_secret(service: str) -> str | None:
    _require_macos()
    result = subprocess.run(
        ["security", "find-generic-password", "-a", _ACCOUNT, "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def delete_secret(service: str) -> bool:
    _require_macos()
    result = subprocess.run(
        ["security", "delete-generic-password", "-a", _ACCOUNT, "-s", service],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
