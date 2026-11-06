from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Episode, Genre, Title, TitleGenre
from ..serializers import episode_to_dict, title_to_dict

router = APIRouter(prefix="/api/titles", tags=["titles"])


@router.get("/trending")
def trending(db: Session = Depends(get_db), user=Depends(get_current_user)):
    titles = (
        db.query(Title)
        .order_by(Title.rating.desc().nullslast(), Title.id.asc())
        .limit(20)
        .all()
    )
    return {"items": [title_to_dict(t, db) for t in titles]}


@router.get("/top10")
def top10(kind: str | None = Query(None), db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Title).filter(Title.top10_rank.isnot(None))
    if kind:
        q = q.filter(Title.kind == kind)
    titles = q.order_by(Title.top10_rank.asc(), Title.id.asc()).all()
    return {"items": [title_to_dict(t, db) for t in titles]}


@router.get("")
def list_titles(
    kind: str | None = Query(None),
    genre: str | None = Query(None),
    year: str | None = Query(None),
    language: str | None = Query(None),
    q: str | None = Query(None),
    limit: int | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Title)
    if kind:
        query = query.filter(Title.kind == kind)
    if genre:
        query = query.filter(or_(Title.genre.ilike(genre), Title.name.ilike(f"%{genre}%")))
    if year:
        query = query.filter(Title.year == year)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Title.name.ilike(like), Title.genre.ilike(like)))
    query = query.order_by(Title.id.asc())
    if limit:
        query = query.limit(limit)
    return {"items": [title_to_dict(t, db) for t in query.all()]}


@router.get("/{title_id}")
def get_title(title_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(Title).filter(Title.id == title_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Title not found")
    return title_to_dict(t, db)


@router.get("/{title_id}/episodes")
def get_episodes(
    title_id: int,
    season: int | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    t = db.query(Title).filter(Title.id == title_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Title not found")
    q = db.query(Episode).filter(Episode.title_id == title_id)
    if season is not None:
        q = q.filter(Episode.season == season)
    episodes = q.order_by(Episode.season.asc(), Episode.number.asc()).all()
    return {"items": [episode_to_dict(e) for e in episodes]}


@router.post("/{title_id}/rating")
def set_rating(
    title_id: int,
    body: dict = {},
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    from ..deps import get_current_profile
    from ..models import Rating

    if isinstance(body, dict):
        value = body.get("value", body.get("rating"))
    else:
        value = getattr(body, "value", None)
    if value not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="value must be 1, 2 or 3")
    profile = get_current_profile(db, user, None, body_profile_id=body.get("profile_id") if isinstance(body, dict) else None)
    existing = (
        db.query(Rating)
        .filter(Rating.profile_id == profile.id, Rating.title_id == title_id)
        .first()
    )
    if existing:
        existing.value = value
        db.commit()
        db.refresh(existing)
        return {"id": existing.id, "profile_id": profile.id, "title_id": title_id, "value": value}
    rating = Rating(profile_id=profile.id, title_id=title_id, value=value)
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return {"id": rating.id, "profile_id": profile.id, "title_id": title_id, "value": value}
