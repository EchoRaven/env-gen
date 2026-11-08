import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Profile, User

SECRET_KEY = os.getenv("JWT_SECRET", "netflix-clone-local-secret-change-me")
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 7)))


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(computed, digest)
    except Exception:
        return False


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: User) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": secrets.token_hex(8),
    }
    signing_input = (
        _b64encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64encode(signature)


def decode_access_token(token: str) -> dict:
    try:
        header_raw, payload_raw, signature_raw = token.split(".")
        signing_input = header_raw + "." + payload_raw
        expected = hmac.new(SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature_raw)):
            raise ValueError("bad signature")
        payload = json.loads(_b64decode(payload_raw))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    try:
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_current_profile(
    x_profile_id: Optional[str] = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Profile:
    if x_profile_id:
        try:
            profile_id = int(x_profile_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid profile")
        profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
        if not profile:
            raise HTTPException(status_code=403, detail="Profile does not belong to the caller")
        return profile
    profile = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).first()
    if profile:
        return profile
    profile = Profile(user_id=user.id, name="You", avatar="/assets/avatars/avatar_1.svg", is_kids=False)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile
