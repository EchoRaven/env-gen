from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, hash_password, verify_password
from database import get_db
from models import ContinueWatching, Episode, Genre, MyList, Profile, Rating, Title, User

app = FastAPI(title="Netflix Catalog API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    username: Optional[str] = None
    tenant_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str
    tenant_id: Optional[str] = None


class ProfileCreate(BaseModel):
    name: str
    avatar: str = "crimson"
    is_kids: bool = False


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    is_kids: Optional[bool] = None


class MyListCreate(BaseModel):
    title_id: int
    profile_id: Optional[int] = None


class RatingCreate(BaseModel):
    value: int
    profile_id: Optional[int] = None


class ContinueCreate(BaseModel):
    title_id: int
    progress_seconds: int = Field(ge=0)
    profile_id: Optional[int] = None


def envelope_item(obj):
    return {"item": obj, "id": obj.get("id") if isinstance(obj, dict) else None}


def profile_dict(p: Profile):
    return {
        "id": p.id,
        "user_id": p.user_id,
        "name": p.name,
        "avatar": p.avatar,
        "is_kids": bool(p.is_kids),
    }


def user_dict(u: User):
    return {"id": u.id, "email": u.email, "name": u.name}


def active_profile(db: Session, user: User, x_profile_id: Optional[str] = None,
                   requested_profile_id: Optional[int] = None) -> Profile:
    requested = None
    if x_profile_id not in (None, ""):
        try:
            requested = int(x_profile_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="X-Profile-Id must be an integer")
    elif requested_profile_id is not None:
        try:
            requested = int(requested_profile_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="profile_id must be an integer")
    if requested is not None:
        profile = db.query(Profile).filter(Profile.id == requested, Profile.user_id == user.id).first()
        if not profile:
            raise HTTPException(status_code=403, detail="Profile does not belong to this account")
        return profile
    profile = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).first()
    if not profile:
        profile = Profile(user_id=user.id, name="Viewer", avatar="crimson", is_kids=False)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def title_dict(t: Title) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "year": int(t.year),
        "genre": t.genre,
        "genres": [g.name for g in t.genres] if t.genres else ([t.genre] if t.genre else []),
        "maturity_rating": t.maturity_rating,
        "rating": float(t.rating or 0),
        "synopsis": t.synopsis,
        "poster": t.poster,
        "backdrop": t.backdrop,
        "video_url": t.video_url,
        "duration": int(t.duration),
        "top10_rank": t.top10_rank,
        "language": t.language,
        "cast": [],
    }


def episode_dict(e: Episode) -> dict:
    return {
        "id": e.id,
        "title_id": e.title_id,
        "season": e.season,
        "number": e.number,
        "name": e.name,
        "synopsis": e.synopsis,
        "duration": e.duration,
        "thumbnail": e.thumbnail,
    }


def decorate_titles(db: Session, titles: list[Title], profile: Profile) -> list[dict]:
    ids = [t.id for t in titles]
    listed = {}
    ratings = {}
    progress = {}
    if ids:
        listed = {r[1]: r[0] for r in db.query(MyList.id, MyList.title_id).filter(
            MyList.profile_id == profile.id, MyList.title_id.in_(ids)).all()}
        ratings = {r[0]: r[1] for r in db.query(Rating.title_id, Rating.value).filter(
            Rating.profile_id == profile.id, Rating.title_id.in_(ids)).all()}
        progress = {r[0]: r[1] for r in db.query(ContinueWatching.title_id, ContinueWatching.progress_seconds).filter(
            ContinueWatching.profile_id == profile.id, ContinueWatching.title_id.in_(ids)).all()}
    out = []
    for title in titles:
        item = title_dict(title)
        item["in_my_list"] = title.id in listed
        item["my_list_id"] = listed.get(title.id)
        item["profile_rating"] = ratings.get(title.id)
        item["progress_seconds"] = progress.get(title.id, 0)
        out.append(item)
    return out


def title_by_id(db: Session, title_id: int) -> Title:
    title = db.get(Title, title_id)
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    return title


@app.get("/")
def root():
    return {"name": "Netflix Catalog API", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required")
    if len(payload.password or "") < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    name = (payload.name or "").strip() or (payload.username or "").strip() or email.split("@", 1)[0]
    user = User(email=email, password_hash=hash_password(payload.password), name=name)
    db.add(user)
    db.flush()
    profile = Profile(user_id=user.id, name=(name.split()[0] if name else "Viewer"), avatar="crimson", is_kids=False)
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user_dict(user), "profiles": [profile_dict(profile)]}


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = (payload.email or payload.username or "").strip().lower()
    if not email or not payload.password:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user)
    profiles = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).all()
    return {"access_token": token, "token_type": "bearer", "user": user_dict(user), "profiles": [profile_dict(p) for p in profiles]}


@app.get("/api/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).all()
    return {"item": {**user_dict(user), "profiles": [profile_dict(p) for p in profiles]}}


@app.get("/api/profiles")
def list_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).all()
    return {"items": [profile_dict(p) for p in rows], "total": len(rows)}


@app.post("/api/profiles", status_code=201)
def create_profile(payload: ProfileCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Profile name is required")
    rows = db.query(Profile).filter(Profile.user_id == user.id).count()
    if rows >= 5:
        raise HTTPException(status_code=400, detail="An account can have up to 5 profiles")
    profile = Profile(user_id=user.id, name=name[:40], avatar=(payload.avatar or "crimson")[:30], is_kids=bool(payload.is_kids))
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return envelope_item(profile_dict(profile))


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"item": profile_dict(profile)}


@app.patch("/api/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=422, detail="Profile name is required")
        profile.name = payload.name.strip()[:40]
    if payload.avatar is not None:
        profile.avatar = payload.avatar[:30]
    if payload.is_kids is not None:
        profile.is_kids = bool(payload.is_kids)
    db.commit()
    db.refresh(profile)
    return envelope_item(profile_dict(profile))


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = db.query(Profile).filter(Profile.user_id == user.id).all()
    profile = next((p for p in profiles if p.id == profile_id), None)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if len(profiles) <= 1:
        raise HTTPException(status_code=400, detail="An account needs at least one profile")
    db.delete(profile)
    db.commit()
    return envelope_item({"id": profile_id, "deleted": True})


@app.get("/api/titles")
def list_titles(
    kind: Optional[str] = None,
    genre: Optional[str] = None,
    language: Optional[str] = None,
    q: Optional[str] = None,
    sort: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    query = db.query(Title)
    if kind:
        query = query.filter(Title.kind == kind)
    if language:
        query = query.filter(Title.language == language)
    if genre:
        query = query.filter(or_(Title.genre == genre, Title.genres.any(Genre.name == genre)))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Title.name.ilike(like), Title.synopsis.ilike(like), Title.genre.ilike(like), Title.genres.any(Genre.name.ilike(like))))
    if sort == "rating":
        query = query.order_by(Title.rating.desc(), Title.id.asc())
    elif sort == "newest":
        query = query.order_by(Title.year.desc(), Title.id.asc())
    elif sort == "top10":
        query = query.order_by(Title.top10_rank.is_(None), Title.top10_rank.asc(), Title.rating.desc())
    else:
        query = query.order_by(Title.id.asc())
    rows = query.limit(limit).all()
    items = decorate_titles(db, rows, profile)
    return {"items": items, "total": len(items)}


@app.get("/api/titles/trending")
def trending(
    limit: int = Query(default=20, ge=1, le=60),
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    rows = db.query(Title).order_by(Title.top10_rank.is_(None), Title.top10_rank.asc(), Title.rating.desc(), Title.id.asc()).limit(limit).all()
    items = decorate_titles(db, rows, profile)
    return {"items": items, "total": len(items)}


@app.get("/api/titles/top10")
def top10(
    kind: Optional[str] = None,
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    if kind:
        rows = (db.query(Title).filter(Title.kind == kind)
                .order_by(Title.top10_rank.is_(None), Title.top10_rank.asc(), Title.rating.desc())
                .limit(10).all())
    else:
        rows = (db.query(Title).filter(Title.top10_rank.isnot(None))
                .order_by(Title.top10_rank.asc()).limit(10).all())
    items = decorate_titles(db, rows, profile)
    if kind:
        for index, item in enumerate(items, start=1):
            item["top10_rank"] = index
    return {"items": items, "total": len(items)}


@app.get("/api/titles/{title_id}")
def get_title(
    title_id: int,
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    title = title_by_id(db, title_id)
    item = decorate_titles(db, [title], profile)[0]
    item["episode_count"] = len(title.episodes)
    item["season_count"] = len({e.season for e in title.episodes})
    return {"item": item}


@app.get("/api/titles/{title_id}/episodes")
def get_episodes(
    title_id: int,
    season: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title_by_id(db, title_id)
    query = db.query(Episode).filter(Episode.title_id == title_id)
    if season is not None:
        query = query.filter(Episode.season == season)
    rows = query.order_by(Episode.season.asc(), Episode.number.asc()).all()
    return {"items": [episode_dict(e) for e in rows], "total": len(rows)}


@app.get("/api/genres")
def list_genres(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Genre).order_by(Genre.name.asc()).all()
    items = []
    for genre in rows:
        count = db.query(func.count(Title.id)).join(Title.genres).filter(Genre.id == genre.id).scalar() or 0
        items.append({"id": genre.id, "name": genre.name, "title_count": count})
    return {"items": items, "total": len(items)}


@app.get("/api/genres/{genre_id}/titles")
def titles_for_genre(
    genre_id: int,
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    genre = db.get(Genre, genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    rows = db.query(Title).filter(Title.genres.any(Genre.id == genre_id)).order_by(Title.rating.desc(), Title.id.asc()).all()
    items = decorate_titles(db, rows, profile)
    return {"items": items, "total": len(items), "genre": {"id": genre.id, "name": genre.name}}


@app.get("/api/search")
def search(
    q: str = Query(default=""),
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    term = q.strip()
    if not term:
        return {"items": [], "total": 0}
    like = f"%{term}%"
    rows = db.query(Title).filter(or_(
        Title.name.ilike(like),
        Title.synopsis.ilike(like),
        Title.genre.ilike(like),
        Title.genres.any(Genre.name.ilike(like)),
    )).order_by(Title.rating.desc(), Title.id.asc()).limit(60).all()
    items = decorate_titles(db, rows, profile)
    return {"items": items, "total": len(items), "query": term}


@app.get("/api/my-list")
def get_my_list(
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    rows = db.query(MyList).filter(MyList.profile_id == profile.id).order_by(MyList.id.desc()).all()
    titles = [db.get(Title, row.title_id) for row in rows]
    titles = [t for t in titles if t]
    decorated = decorate_titles(db, titles, profile)
    by_id = {item["id"]: item for item in decorated}
    items = []
    for row in rows:
        if row.title_id in by_id:
            items.append({**by_id[row.title_id], "my_list_id": row.id})
    return {"items": items, "total": len(items)}


@app.post("/api/my-list", status_code=201)
def add_my_list(
    payload: MyListCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, payload.profile_id)
    title = title_by_id(db, payload.title_id)
    existing = db.query(MyList).filter(MyList.profile_id == profile.id, MyList.title_id == title.id).first()
    if existing:
        item = decorate_titles(db, [title], profile)[0]
        item["my_list_id"] = existing.id
        return {**envelope_item(item), "id": existing.id, "created": False}
    row = MyList(profile_id=profile.id, title_id=title.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    item = decorate_titles(db, [title], profile)[0]
    item["in_my_list"] = True
    item["my_list_id"] = row.id
    return {**envelope_item(item), "id": row.id, "created": True}


@app.put("/api/my-list/{entry_id}")
def update_my_list(
    entry_id: int,
    payload: Optional[dict] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id)
    row = db.query(MyList).filter(MyList.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="My List entry not found")
    if row.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="This My List entry belongs to another profile")
    title = title_by_id(db, row.title_id)
    item = decorate_titles(db, [title], profile)[0]
    item["my_list_id"] = row.id
    return envelope_item(item)


@app.delete("/api/my-list/{entry_id}")
def remove_my_list(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id)
    row = db.query(MyList).filter(MyList.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="My List entry not found")
    if row.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="This My List entry belongs to another profile")
    title_id = row.title_id
    db.delete(row)
    db.commit()
    return envelope_item({"id": entry_id, "title_id": title_id, "deleted": True})


@app.post("/api/titles/{title_id}/rating")
def rate_title(
    title_id: int,
    payload: RatingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, payload.profile_id)
    title_by_id(db, title_id)
    if payload.value not in (-1, 1, 2):
        raise HTTPException(status_code=422, detail="Rating value must be -1, 1, or 2")
    row = db.query(Rating).filter(Rating.profile_id == profile.id, Rating.title_id == title_id).first()
    if row:
        row.value = payload.value
    else:
        row = Rating(profile_id=profile.id, title_id=title_id, value=payload.value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return envelope_item({"id": row.id, "profile_id": profile.id, "title_id": title_id, "value": row.value})


@app.get("/api/continue-watching")
def continue_watching(
    profile_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, profile_id)
    rows = db.query(ContinueWatching).filter(ContinueWatching.profile_id == profile.id).order_by(ContinueWatching.updated_at.desc()).all()
    titles = [db.get(Title, row.title_id) for row in rows]
    titles = [t for t in titles if t]
    decorated = decorate_titles(db, titles, profile)
    by_id = {item["id"]: item for item in decorated}
    items = []
    for row in rows:
        title = by_id.get(row.title_id)
        if not title:
            continue
        total_seconds = max(title["duration"] * 60, 1)
        items.append({
            **title,
            "continue_id": row.id,
            "progress_seconds": row.progress_seconds,
            "progress_percent": min(100, round(row.progress_seconds / total_seconds * 100, 1)),
        })
    return {"items": items, "total": len(items)}


@app.post("/api/continue-watching")
def update_continue_watching(
    payload: ContinueCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id, payload.profile_id)
    title = title_by_id(db, payload.title_id)
    progress = max(0, min(int(payload.progress_seconds), max(title.duration * 60, 1)))
    row = db.query(ContinueWatching).filter(ContinueWatching.profile_id == profile.id, ContinueWatching.title_id == title.id).first()
    if row:
        row.progress_seconds = progress
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = ContinueWatching(profile_id=profile.id, title_id=title.id, progress_seconds=progress)
        db.add(row)
    db.commit()
    db.refresh(row)
    return envelope_item({"id": row.id, "profile_id": profile.id, "title_id": title.id, "progress_seconds": row.progress_seconds})


@app.delete("/api/continue-watching/{entry_id}")
def delete_continue_watching(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    profile = active_profile(db, user, x_profile_id)
    row = db.query(ContinueWatching).filter(ContinueWatching.id == entry_id, ContinueWatching.profile_id == profile.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Continue Watching entry not found")
    db.delete(row)
    db.commit()
    return envelope_item({"id": entry_id, "deleted": True})


@app.get("/api/notifications")
def notifications(user: User = Depends(get_current_user)):
    return {"items": [], "total": 0}
