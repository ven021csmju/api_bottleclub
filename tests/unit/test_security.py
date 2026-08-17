from jose import JWTError

from app.shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        plain = "SuperSecret123!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes_for_same_input(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts differ each time
        assert verify_password("same", h1)
        assert verify_password("same", h2)


class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(
            user_id=42,
            org_id=1,
            permissions=["orders.read"],
            branches=[10, 20],
        )
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["org_id"] == 1
        assert payload["permissions"] == ["orders.read"]
        assert payload["branches"] == [10, 20]
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(user_id=7, device_info="Chrome", ip="127.0.0.1")
        payload = decode_token(token)
        assert payload["sub"] == "7"
        assert payload["type"] == "refresh"
        assert payload["device"] == "Chrome"
        assert payload["ip"] == "127.0.0.1"

    def test_invalid_token_raises(self):
        try:
            decode_token("not-a-real-token")
            assert False, "Expected JWTError"
        except JWTError:
            pass


class TestTokenHashing:
    def test_hash_is_deterministic(self):
        token = "raw-refresh-token-value"
        assert hash_token(token) == hash_token(token)

    def test_hash_is_sha256_hex(self):
        h = hash_token("abc")
        assert len(h) == 64  # SHA-256 hex digest length
        assert all(c in "0123456789abcdef" for c in h)
