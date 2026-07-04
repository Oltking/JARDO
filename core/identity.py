"""Owner identity + device keypair (spec §4.1).

Device-bound Ed25519 keypair generated at first run: public half on the owner
row, private half in the Keychain. It will sign the desktop↔cloud channel
enrollment at Phase 5 (§6.9 mTLS lifecycle).
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession

from core import secrets
from core.schema import Owner


def generate_device_keypair() -> tuple[str, str]:
    """Returns (private_pem, public_pem)."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),  # at rest inside Keychain
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


async def create_owner(
    session: AsyncSession, name: str, pronoun_style: str, email: str
) -> Owner:
    private_pem, public_pem = generate_device_keypair()
    secrets.write_secret(secrets.DEVICE_PRIVATE_KEY, private_pem)
    owner = Owner(
        name=name,
        pronoun_style=pronoun_style,
        email=email,
        device_public_key=public_pem,
    )
    session.add(owner)
    await session.flush()
    return owner
