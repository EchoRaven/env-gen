"""Password hashing (PBKDF2-SHA256, stdlib) + HS256 JWT (stdlib). No crypto deps."""
import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.getenv("NETFLIX_JWT_SECRET", "netflix-local-dev-secret").encode()
TOKEN_TTL = 60 * 60 * 24 * 30          # 30 days
PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_password(password, salt_hex), stored)


def _b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def create_token(user_id: int, email: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({
        "sub": str(user_id), "email": email, "iat": now, "exp": now + TOKEN_TTL,
    }, separators=(",", ":")).encode())
    signing_input = header + b"." + payload
    sig = _b64url(hmac.new(SECRET, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + sig).decode()


def decode_token(token: str) -> dict | None:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = (header_b64 + "." + payload_b64).encode()
        expected = _b64url(hmac.new(SECRET, signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig_b64.encode()):
            return None
        pad = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
