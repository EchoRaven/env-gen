import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt

from .models import User

JWT_SECRET = hmac.new(b"key", b"netflix-clone-secret", hashlib.sha256).digest()  # stable dev secret
try:
    import os
    _env_secret = os.environ.get("JWT_SECRET")
    if _env_secret:
        JWT_SECRET = _env_secret.encode()
except Exception:
    pass

_ALGORITHM = "HS256"
_TOKEN_TTL_HOURS = 24


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200000).hex()
    return f"pbkdf2_sha256$200000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(calc, digest)
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "iat": int(time.time()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGORITHM)


def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[_ALGORITHM])
        return int(payload["sub"])
    except Exception:
        return None
