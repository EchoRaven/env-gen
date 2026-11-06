from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_profile, get_current_user
from ..models import ContinueWatching, Title
from ..serializers import title_to_dict

router = APIRouter(prefix="/api/continue-watching", tags=["continue-watching"])


@router.get("")
def list_continue_watching(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    profile = get_current_profile(db, user, request)
    rows = (
        db.query(ContinueWatching)
        .filter(ContinueWatching.profile_id == profile.id)
        .order_by(ContinueWatching.id.desc())
        .all()
    )
    out = []
    for row in rows:
        t = db.query(Title).filter(Title.id == row.title_id).first()
        if not t:
            continue
        d = title_to_dict(t, db)
        d["progress_seconds"] = row.progress_seconds
        d["title_id"] = t.id
        d["profile_id"] = profile.id
        if t.duration:
            d["progress_percent"] = min(100, round(100 * row.progress_seconds / t.duration))
        out.append(d)
    return out


@router.post("")
def save_continue_watching(
    request: Request,
    body: dict = {},
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    title_id = body.get("title_id") or body.get("id")
    progress = body.get("progress_seconds", 0)
    if title_id is None:
        raise HTTPException(status_code=422, detail="title_id is required")
    t = db.query(Title).filter(Title.id == int(title_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Title not found")
    profile = get_current_profile(db, user, request, body_profile_id=body.get("profile_id"))
    row = (
        db.query(ContinueWatching)
        .filter(ContinueWatching.profile_id == profile.id, ContinueWatching.title_id == t.id)
        .first()
    )
    if row:
        row.progress_seconds = int(progress)
    else:
        row = ContinueWatching(profile_id=profile.id, title_id=t.id, progress_seconds=int(progress))
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "profile_id": profile.id, "title_id": t.id, "progress_seconds": row.progress_seconds}
