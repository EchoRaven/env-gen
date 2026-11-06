from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db

from .models import Profile, User
from .security import decode_access_token


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_current_profile(db, user, request: Request, body_profile_id=None):
    """Resolve the acting profile: X-Profile-Id header > query/body profile_id > user's first profile."""
    header_id = request.headers.get("x-profile-id") if request is not None else None
    query_id = request.query_params.get("profile_id") if request is not None else None
    candidate = header_id or query_id or body_profile_id
    if candidate:
        try:
            profile = (
                db.query(Profile)
                .filter(Profile.id == int(candidate), Profile.user_id == user.id)
                .first()
            )
        except (ValueError, TypeError):
            profile = None
        if profile:
            return profile
    profiles = (
        db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id).all()
    )
    if not profiles:
        raise HTTPException(status_code=409, detail="No profile available")
    return profiles[0]
