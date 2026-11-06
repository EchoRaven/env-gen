"""Netflix clone — FastAPI backend. All business routes require a Bearer JWT."""
import os
from typing import Optional

import starlette.concurrency
import fastapi.routing
import fastapi.dependencies.utils
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import create_token, decode_token, hash_password, verify_password
from database import get_db
from models import (ContinueWatching, Episode, Genre, MyList, Profile, Rating,
                    Title, TitleGenre, User)

# The sandbox host blocks new pthread creation; run sync handlers in-process.
async def _run_without_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)

starlette.concurrency.run_in_threadpool = _run_without_threadpool
fastapi.routing.run_in_threadpool = _run_without_threadpool
fastapi.dependencies.utils.run_in_threadpool = _run_without_threadpool

app = FastAPI(title="Netflix API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=True)


@app.get("/")
def banner():
    return {"name": "Netflix clone API", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── auth ─────────────────────────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: str
    password: str = ""
    name: Optional[str] = None
    username: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str = ""
    username: Optional[str] = None


def _auth_response(user: User, profile: Profile) -> dict:
    return {
        "access_token": create_token(user.id, user.email),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "profile": {"id": profile.id, "name": profile.name, "avatar": profile.avatar,
                    "is_kids": profile.is_kids},
    }


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if not body.password:
        raise HTTPException(status_code=400, detail="A password is required")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    name = (body.name or body.username or email.split("@")[0]).strip()
    user = User(email=email, password_hash=hash_password(body.password), name=name)
    db.add(user)
    db.flush()
    profile = Profile(user_id=user.id, name="Profile", avatar="0", is_kids=False)
    db.add(profile)
    db.commit()
    db.refresh(user)
    db.refresh(profile)
    return _auth_response(user, profile)


@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    profile = (db.query(Profile).filter(Profile.user_id == user.id)
               .order_by(Profile.id).first())
    if profile is None:
        profile = Profile(user_id=user.id, name="Profile", avatar="0")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return _auth_response(user, profile)


# ── auth guard + profile resolution ─────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = decode_token(authorization[7:].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        user = db.get(User, int(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


def get_current_profile(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db),
                        x_profile_id: Optional[int] = Header(default=None, alias="X-Profile-Id")) -> Profile:
    if x_profile_id is not None:
        profile = db.get(Profile, x_profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=403, detail="Profile not found for this account")
        return profile
    profile = (db.query(Profile).filter(Profile.user_id == user.id)
               .order_by(Profile.id).first())
    if profile is None:
        profile = Profile(user_id=user.id, name="Profile", avatar="0")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


# ── serializers ─────────────────────────────────────────────────────────────

def title_dict(t: Title) -> dict:
    return {
        "id": t.id, "name": t.name, "kind": t.kind, "year": t.year,
        "genre": t.genre, "maturity_rating": t.maturity_rating, "rating": t.rating,
        "synopsis": t.synopsis, "poster": t.poster, "backdrop": t.backdrop,
        "video_url": t.video_url, "duration": t.duration, "top10_rank": t.top10_rank,
        "language": t.language,
    }


def title_with_genres(t: Title, db: Session) -> dict:
    d = title_dict(t)
    d["genres"] = [g.name for g in db.query(Genre)
                   .join(TitleGenre, TitleGenre.genre_id == Genre.id)
                   .filter(TitleGenre.title_id == t.id).all()]
    return d


def episode_dict(e: Episode) -> dict:
    return {"id": e.id, "title_id": e.title_id, "season": e.season, "number": e.number,
            "name": e.name, "synopsis": e.synopsis, "duration": e.duration,
            "thumbnail": e.thumbnail}


def profile_dict(p: Profile) -> dict:
    return {"id": p.id, "user_id": p.user_id, "name": p.name, "avatar": p.avatar,
            "is_kids": p.is_kids}


# ── profiles ────────────────────────────────────────────────────────────────

@app.get("/api/profiles")
def list_profiles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(Profile).filter(Profile.user_id == user.id)
            .order_by(Profile.id).all())
    return {"items": [profile_dict(p) for p in rows], "total": len(rows)}


class ProfileIn(BaseModel):
    name: str = Field(default="Profile", min_length=0, max_length=64)
    avatar: str = "0"
    is_kids: bool = False


@app.post("/api/profiles", status_code=201)
def create_profile(body: ProfileIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    profile = Profile(user_id=user.id, name=body.name.strip(),
                      avatar=str(body.avatar), is_kids=bool(body.is_kids))
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"item": profile_dict(profile)}


# ── titles ──────────────────────────────────────────────────────────────────

@app.get("/api/titles")
def list_titles(kind: Optional[str] = Query(default=None),
                genre_id: Optional[int] = Query(default=None),
                year: Optional[str] = Query(default=None),
                limit: int = Query(default=60, ge=1, le=200),
                offset: int = Query(default=0, ge=0),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Title)
    if kind in ("series", "movie"):
        q = q.filter(Title.kind == kind)
    if year:
        q = q.filter(Title.year == str(year))
    if genre_id is not None:
        q = q.join(TitleGenre, TitleGenre.title_id == Title.id) \
             .filter(TitleGenre.genre_id == genre_id)
    total = q.count()
    rows = q.order_by(Title.id).offset(offset).limit(limit).all()
    return {"items": [title_with_genres(t, db) for t in rows], "total": total}


@app.get("/api/titles/trending")
def trending(limit: int = Query(default=20, ge=1, le=60),
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    watched = dict(db.query(ContinueWatching.title_id,
                            func.count(ContinueWatching.id))
                   .group_by(ContinueWatching.title_id).all())
    rows = (db.query(Title).order_by(Title.rating.desc().nullslast(), Title.year.desc().nullslast(),
                                     Title.id).limit(limit).all())
    rows.sort(key=lambda t: -watched.get(t.id, 0))
    return {"items": [title_with_genres(t, db) for t in rows], "total": len(rows)}


@app.get("/api/titles/top10")
def top10(kind: Optional[str] = Query(default=None),
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Title).filter(Title.top10_rank.isnot(None))
    if kind in ("series", "movie"):
        q = q.filter(Title.kind == kind)
    rows = q.order_by(Title.kind, Title.top10_rank).all()
    return {"items": [title_with_genres(t, db) for t in rows], "total": len(rows)}


@app.get("/api/titles/{id}")
def get_title(id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(Title, id)
    if t is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return {"item": title_with_genres(t, db)}


@app.get("/api/titles/{id}/episodes")
def get_episodes(id: int, season: Optional[int] = Query(default=None),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(Title, id)
    if t is None:
        raise HTTPException(status_code=404, detail="Title not found")
    q = db.query(Episode).filter(Episode.title_id == id)
    if season is not None:
        q = q.filter(Episode.season == season)
    rows = q.order_by(Episode.season, Episode.number).all()
    return {"items": [episode_dict(e) for e in rows], "total": len(rows)}


# ── genres ──────────────────────────────────────────────────────────────────

@app.get("/api/genres")
def list_genres(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Genre).order_by(Genre.name).all()
    return {"items": [{"id": g.id, "name": g.name} for g in rows], "total": len(rows)}


@app.get("/api/genres/{id}/titles")
def titles_by_genre(id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = db.get(Genre, id)
    if g is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    rows = (db.query(Title).join(TitleGenre, TitleGenre.title_id == Title.id)
            .filter(TitleGenre.genre_id == id).order_by(Title.rating.desc().nullslast(),
                                                        Title.id).all())
    return {"items": [title_with_genres(t, db) for t in rows], "total": len(rows)}


# ── search ──────────────────────────────────────────────────────────────────

@app.get("/api/search")
def search(q: str = Query(default=""), kind: Optional[str] = Query(default=None),
           limit: int = Query(default=40, ge=1, le=100),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = q.strip()
    base = db.query(Title)
    if kind in ("series", "movie"):
        base = base.filter(Title.kind == kind)
    if query:
        like = f"%{query}%"
        base = base.filter(or_(Title.name.ilike(like), Title.genre.ilike(like)))
    rows = base.order_by(Title.rating.desc().nullslast(), Title.id).limit(limit).all()
    return {"items": [title_with_genres(t, db) for t in rows], "total": len(rows)}


# ── my list (per profile) ───────────────────────────────────────────────────

@app.get("/api/my-list")
def get_my_list(profile: Profile = Depends(get_current_profile),
                db: Session = Depends(get_db)):
    rows = (db.query(MyList, Title).join(Title, Title.id == MyList.title_id)
            .filter(MyList.profile_id == profile.id).order_by(MyList.id).all())
    items = []
    for row, t in rows:
        d = title_with_genres(t, db)
        d["id"] = row.id
        d["title_id"] = t.id
        items.append(d)
    return {"items": items, "total": len(items)}


class MyListIn(BaseModel):
    title_id: int


@app.post("/api/my-list", status_code=201)
def add_to_my_list(body: MyListIn, profile: Profile = Depends(get_current_profile),
                   db: Session = Depends(get_db)):
    if db.get(Title, body.title_id) is None:
        raise HTTPException(status_code=404, detail="Title not found")
    existing = (db.query(MyList).filter(MyList.profile_id == profile.id,
                                        MyList.title_id == body.title_id).first())
    if existing:
        raise HTTPException(status_code=409, detail="Title is already in your list")
    row = MyList(profile_id=profile.id, title_id=body.title_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"item": {"id": row.id, "profile_id": row.profile_id, "title_id": row.title_id}}


@app.put("/api/my-list/{id}")
def update_my_list(id: int, body: Optional[dict] = None,
                   profile: Profile = Depends(get_current_profile),
                   db: Session = Depends(get_db)):
    """Ownership-guarded update. Cross-profile access is indistinguishable from missing."""
    row = db.get(MyList, id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="List entry not found")
    db.commit()
    db.refresh(row)
    return {"item": {"id": row.id, "profile_id": row.profile_id, "title_id": row.title_id}}


@app.delete("/api/my-list/{id}")
def remove_from_my_list(id: int, profile: Profile = Depends(get_current_profile),
                        db: Session = Depends(get_db)):
    row = db.get(MyList, id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="List entry not found")
    db.delete(row)
    db.commit()
    return {"item": {"id": id, "deleted": True}}


# ── ratings (per profile) ───────────────────────────────────────────────────

class RatingIn(BaseModel):
    value: Optional[int] = Field(default=3, ge=1, le=3)


@app.post("/api/titles/{id}/rating", status_code=200)
def set_rating(id: int, body: Optional[RatingIn] = None,
               profile: Profile = Depends(get_current_profile),
               db: Session = Depends(get_db)):
    if db.get(Title, id) is None:
        raise HTTPException(status_code=404, detail="Title not found")
    value = body.value if body is not None else 3
    row = (db.query(Rating).filter(Rating.profile_id == profile.id,
                                   Rating.title_id == id).first())
    if row:
        row.value = value
    else:
        row = Rating(profile_id=profile.id, title_id=id, value=value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"item": {"id": row.id, "profile_id": row.profile_id, "title_id": id,
                     "value": row.value}}


@app.get("/api/ratings")
def get_ratings(profile: Profile = Depends(get_current_profile),
                db: Session = Depends(get_db)):
    rows = db.query(Rating).filter(Rating.profile_id == profile.id).all()
    return {"items": [{"id": r.id, "title_id": r.title_id, "value": r.value}
                      for r in rows], "total": len(rows)}


# ── continue watching (per profile) ─────────────────────────────────────────

@app.get("/api/continue-watching")
def get_continue_watching(profile: Profile = Depends(get_current_profile),
                          db: Session = Depends(get_db)):
    rows = (db.query(ContinueWatching, Title)
            .join(Title, Title.id == ContinueWatching.title_id)
            .filter(ContinueWatching.profile_id == profile.id)
            .order_by(ContinueWatching.id.desc())
            .all())
    items = []
    for row, t in rows:
        d = title_dict(t)
        d["id"] = row.id
        d["title_id"] = t.id
        d["progress_seconds"] = row.progress_seconds
        items.append(d)
    return {"items": items, "total": len(items)}


class ContinueWatchingIn(BaseModel):
    title_id: int
    progress_seconds: int = 0
    episode_id: Optional[int] = None


@app.post("/api/continue-watching", status_code=201)
def set_continue_watching(body: ContinueWatchingIn,
                          profile: Profile = Depends(get_current_profile),
                          db: Session = Depends(get_db)):
    if db.get(Title, body.title_id) is None:
        raise HTTPException(status_code=404, detail="Title not found")
    row = (db.query(ContinueWatching)
           .filter(ContinueWatching.profile_id == profile.id,
                   ContinueWatching.title_id == body.title_id).first())
    if row:
        row.progress_seconds = max(0, int(body.progress_seconds))
    else:
        row = ContinueWatching(profile_id=profile.id, title_id=body.title_id,
                               progress_seconds=max(0, int(body.progress_seconds)))
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"item": {"id": row.id, "profile_id": row.profile_id, "title_id": body.title_id,
                     "progress_seconds": row.progress_seconds}}


# ── account ─────────────────────────────────────────────────────────────────

@app.get("/api/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = (db.query(Profile).filter(Profile.user_id == user.id)
               .order_by(Profile.id).first())
    return {"item": {"id": user.id, "email": user.email, "name": user.name,
                     "profile": profile_dict(profile) if profile else None}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.getenv("NETFLIX_API_PORT", "8000")),
                loop="asyncio", http="h11")
