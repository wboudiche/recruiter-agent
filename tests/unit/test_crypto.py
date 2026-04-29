import pytest

from recruiter.crypto import SecretCipher


def test_roundtrip_encrypts_and_decrypts() -> None:
    cipher = SecretCipher(b"0123456789abcdef0123456789abcdef")
    token = cipher.encrypt("my-api-key")
    assert token != "my-api-key"
    assert cipher.decrypt(token) == "my-api-key"


def test_decrypt_rejects_tampered_token() -> None:
    cipher = SecretCipher(b"0123456789abcdef0123456789abcdef")
    token = cipher.encrypt("my-api-key")
    tampered = token[:-2] + "00"
    with pytest.raises(ValueError, match="invalid token"):
        cipher.decrypt(tampered)


def test_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretCipher(b"too-short")
