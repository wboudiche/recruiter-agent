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
    key = _decode_key(raw)
    if len(key) != 32:
        raise RuntimeError(
            "RECRUITER_SETTINGS_KEY must decode to 32 bytes. Provide one "
            "of: a 32-character raw string, 64 hex characters, or a "
            "urlsafe-base64-encoded 32-byte value (44 chars incl. '='). "
            "Generate via:\n"
            "  python -c 'import secrets,base64; "
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'"
        )
    return SecretCipher(key)


def _decode_key(raw: str) -> bytes:
    """Decode the env var into 32 raw bytes. Tries (in order):

      1. 44-char urlsafe-base64 (the Fernet-shaped format the README
         tells users to generate — ends with '=' padding).
      2. 64 hex chars.
      3. 32-char raw ASCII (legacy / dev placeholder).

    Returns whatever the first matching format decodes to, or the raw
    UTF-8 bytes as a last resort so the caller's length check still
    fires with a useful error.
    """
    s = (raw or "").strip()
    # 1. urlsafe-base64 (Fernet-style). Tolerate missing/extra padding.
    if len(s) in (43, 44) and all(
        c.isalnum() or c in "-_=" for c in s
    ):
        try:
            return base64.urlsafe_b64decode(s + "==="[: (-len(s)) % 4])
        except Exception:
            pass
    # 2. hex.
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except ValueError:
            pass
    # 3. raw 32-char ASCII.
    return s.encode("utf-8")


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
