import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def settings_cipher() -> "SecretCipher":
    """Return a SecretCipher built from `RECRUITER_SETTINGS_KEY`.

    Accepts either a 32-byte raw string or a 64-char hex-encoded string —
    no silent padding. Single source of truth for callers that need to
    encrypt/decrypt fields stored on the singleton Settings row.
    """
    from recruiter.config import get_config

    raw = get_config().settings_key
    if len(raw) == 64:
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise RuntimeError(
                "RECRUITER_SETTINGS_KEY: 64-char value must be valid hex"
            ) from exc
    else:
        key = raw.encode("utf-8")
    if len(key) != 32:
        raise RuntimeError(
            "RECRUITER_SETTINGS_KEY must be 32 bytes (or 64 hex chars). "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return SecretCipher(key)


class SecretCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
        return base64.urlsafe_b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii") + b"===")
        except Exception as exc:
            raise ValueError("invalid token: not base64") from exc
        if len(raw) < 28:  # 12-byte nonce + 16-byte AES-GCM tag minimum
            raise ValueError("invalid token: too short")
        nonce, ct = raw[:12], raw[12:]
        try:
            return self._aead.decrypt(nonce, ct, associated_data=None).decode("utf-8")
        except InvalidTag as exc:
            raise ValueError("invalid token: bad tag") from exc
