import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


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
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise ValueError("invalid token: not base64") from exc
        if len(raw) < 13:
            raise ValueError("invalid token: too short")
        nonce, ct = raw[:12], raw[12:]
        try:
            return self._aead.decrypt(nonce, ct, associated_data=None).decode("utf-8")
        except InvalidTag as exc:
            raise ValueError("invalid token: bad tag") from exc
