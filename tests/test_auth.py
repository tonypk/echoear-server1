"""Tests for app/auth.py — password hashing, JWT, encryption."""
from app.auth import (
    hash_password,
    verify_password,
    hash_token,
    verify_token,
    create_access_token,
    decode_access_token,
    encrypt_secret,
    decrypt_secret,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        # bcrypt produces different salts
        assert h1 != h2

    def test_hash_not_plaintext(self):
        hashed = hash_password("secret")
        assert "secret" not in hashed


class TestTokenHashing:
    def test_hash_and_verify(self):
        hashed = hash_token("device-token-123")
        assert verify_token("device-token-123", hashed) is True

    def test_wrong_token(self):
        hashed = hash_token("device-token-123")
        assert verify_token("wrong-token", hashed) is False


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token(user_id=42, email="test@example.com")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["email"] == "test@example.com"
        assert "exp" in payload

    def test_different_users(self):
        t1 = create_access_token(1, "a@b.com")
        t2 = create_access_token(2, "c@d.com")
        assert t1 != t2

    def test_decode_invalid_token(self):
        from jose import JWTError
        import pytest

        with pytest.raises(JWTError):
            decode_access_token("invalid.token.here")


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        secret = "sk-my-api-key-12345"
        encrypted = encrypt_secret(secret)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == secret

    def test_encrypted_not_plaintext(self):
        secret = "sk-my-api-key-12345"
        encrypted = encrypt_secret(secret)
        assert secret not in encrypted

    def test_empty_string(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""

    def test_unicode_roundtrip(self):
        secret = "api-key-with-中文"
        encrypted = encrypt_secret(secret)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == secret
