"""Small, dependency-free bearer-token and password implementation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

JWT_SECRET = os.getenv("JWT_SECRET", "netflix-local-development-secret")
JWT_TTL = int(os.getenv("JWT_TTL_SECONDS", str(60 * 60 * 24 * 30)))
PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(user_id: int, email: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL,
    }
    head = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{head}.{body}.{_b64encode(signature)}"


def decode_token(token: str) -> dict:
    try:
        head, body, signature = token.split(".")
        signing_input = f"{head}.{body}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise ValueError("bad signature")
        payload = json.loads(_b64decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        if not payload.get("sub"):
            raise ValueError("missing subject")
        return payload
    except Exception as exc:
        raise ValueError("Invalid or expired token") from exc
