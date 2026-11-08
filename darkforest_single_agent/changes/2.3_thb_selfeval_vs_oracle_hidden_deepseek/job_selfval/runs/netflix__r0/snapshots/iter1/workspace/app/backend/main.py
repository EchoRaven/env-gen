import os

import starlette.concurrency
import fastapi.routing
import fastapi.dependencies.utils


async def _run_without_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)


starlette.concurrency.run_in_threadpool = _run_without_threadpool
fastapi.routing.run_in_threadpool = _run_without_threadpool
fastapi.dependencies.utils.run_in_threadpool = _run_without_threadpool

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_profile,
    get_current_user,
    hash_password,
    verify_password,
)
from database import Base, engine, get_db, wait_for_database
from models import ContinueWatching, Episode, Genre, MyList, Profile, Rating, Title, TitleGenre, User
from schemas import LoginRequest, MyListCreate, ProfileCreate, ProgressCreate, RatingCreate, RegisterRequest

app = FastAPI(title="Netflix Clone API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    wait_for_database()
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        return {"status": "unhealthy"}


@app.get("/")
def root():
    return {"name": "Netflix Clone API", "docs": "/docs", "health": "/health"}


def _profile_dict(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "name": profile.name,
        "avatar": profile.avatar,
        "is_kids": bool(profile.is_kids),
    }


def _user_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name}


def _auth_payload(user: User, db: Session) -> dict:
    profiles = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).all()
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": _user_dict(user),
        "profiles": [_profile_dict(p) for p in profiles],
    }


def _normalise_email(value: str | None) -> str:
    return (value or "").strip().lower()


@app.post("/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = _normalise_email(payload.email or payload.username)
    password = payload.password or ""
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    name = (payload.name or payload.full_name or email.split("@", 1)[0]).strip() or "Viewer"
    user = User(email=email, password_hash=hash_password(password), name=name)
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, name=name[:24] or "You", avatar="/assets/avatars/avatar_1.svg", is_kids=False))
    db.commit()
    db.refresh(user)
    return _auth_payload(user, db)


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = _normalise_email(payload.email or payload.username)
    password = payload.password or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return _auth_payload(user, db)


@app.get("/api/account")
def get_account(user: User = Depends(get_current_user)):
    return {"item": _user_dict(user)}


@app.get("/api/profiles")
def list_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id.asc()).all()
    return {"items": [_profile_dict(p) for p in profiles], "total": len(profiles)}


@app.post("/api/profiles", status_code=201)
def create_profile(payload: ProfileCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    count = db.query(Profile).filter(Profile.user_id == user.id).count()
    if count >= 5:
        raise HTTPException(status_code=400, detail="Netflix profiles are limited to 5 per account")
    avatar = (payload.avatar or "/assets/avatars/avatar_1.svg").strip()
    profile = Profile(user_id=user.id, name=name[:32], avatar=avatar, is_kids=bool(payload.is_kids))
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"item": _profile_dict(profile)}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    count = db.query(Profile).filter(Profile.user_id == user.id).count()
    if count <= 1:
        raise HTTPException(status_code=400, detail="At least one profile is required")
    db.delete(profile)
    db.commit()
    return {"item": {"id": profile_id, "deleted": True}}


def _title_dicts(titles, db: Session, profile: Profile | None):
    if not titles:
        return []
    ids = [title.id for title in titles]
    saved = set()
    ratings = {}
    entry_ids = {}
    if profile is not None:
        rows = db.query(MyList).filter(MyList.profile_id == profile.id, MyList.title_id.in_(ids)).all()
        saved = {row.title_id for row in rows}
        entry_ids = {row.title_id: row.id for row in rows}
        rating_rows = db.query(Rating).filter(Rating.profile_id == profile.id, Rating.title_id.in_(ids)).all()
        ratings = {row.title_id: row.value for row in rating_rows}
    genre_map = {}
    for title_id, genre_name in (
        db.query(TitleGenre.title_id, Genre.name)
        .join(Genre, Genre.id == TitleGenre.genre_id)
        .filter(TitleGenre.title_id.in_(ids))
        .order_by(Genre.name.asc())
        .all()
    ):
        genre_map.setdefault(title_id, []).append(genre_name)
    result = []
    for title in titles:
        genres = genre_map.get(title.id) or ([title.genre] if title.genre else [])
        result.append({
            "id": title.id,
            "name": title.name,
            "kind": title.kind,
            "year": title.year,
            "genre": title.genre,
            "genres": genres,
            "maturity_rating": title.maturity_rating,
            "rating": float(title.rating or 0),
            "synopsis": title.synopsis or "",
            "poster": title.poster,
            "backdrop": title.backdrop or title.poster,
            "video_url": title.video_url,
            "duration": title.duration or 0,
            "top10_rank": title.top10_rank,
            "language": title.language,
            "language_name": title.language_name,
            "in_my_list": title.id in saved,
            "my_list_id": entry_ids.get(title.id),
            "user_rating": ratings.get(title.id),
        })
    return result


def _title_dict(title: Title, db: Session, profile: Profile | None):
    item = _title_dicts([title], db, profile)[0]
    episodes = db.query(Episode).filter(Episode.title_id == title.id).order_by(Episode.season, Episode.number).all()
    item["seasons"] = len({ep.season for ep in episodes}) or (1 if title.kind == "series" else 0)
    item["episode_count"] = len(episodes)
    return item


@app.get("/api/titles/trending")
def trending_titles(
    limit: int = Query(default=24, ge=1, le=100),
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    titles = db.query(Title).order_by(Title.rating.desc(), Title.year.desc(), Title.name.asc()).limit(limit).all()
    items = _title_dicts(titles, db, profile)
    return {"items": items, "total": len(items)}


@app.get("/api/titles/top10")
def top10_titles(
    kind: str | None = None,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    query = db.query(Title)
    if kind:
        query = query.filter(Title.kind == kind)
    titles = query.order_by(Title.rating.desc(), Title.name.asc()).limit(10).all()
    items = _title_dicts(titles, db, profile)
    for index, item in enumerate(items, start=1):
        item["top10_rank"] = index
    return {"items": items, "total": len(items)}


@app.get("/api/titles")
def list_titles(
    kind: str | None = None,
    genre: str | None = None,
    language: str | None = None,
    sort: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    query = db.query(Title)
    if kind:
        query = query.filter(Title.kind == kind)
    if genre:
        query = query.filter(
            or_(Title.genre.ilike(f"%{genre}%"), Title.id.in_(
                db.query(TitleGenre.title_id).join(Genre, Genre.id == TitleGenre.genre_id).filter(Genre.name.ilike(f"%{genre}%"))
            ))
        )
    if language:
        query = query.filter(or_(Title.language == language, Title.language_name.ilike(language)))
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(or_(Title.name.ilike(needle), Title.genre.ilike(needle), Title.synopsis.ilike(needle)))
    if sort == "new":
        query = query.order_by(Title.year.desc(), Title.id.desc())
    elif sort == "rating":
        query = query.order_by(Title.rating.desc(), Title.name.asc())
    elif sort == "name":
        query = query.order_by(Title.name.asc())
    else:
        query = query.order_by(Title.id.asc())
    total = query.count()
    titles = query.offset(offset).limit(limit).all()
    return {"items": _title_dicts(titles, db, profile), "total": total}


@app.get("/api/titles/{title_id}")
def get_title(title_id: int, profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    title = db.query(Title).filter(Title.id == title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    return {"item": _title_dict(title, db, profile)}


@app.get("/api/titles/{title_id}/episodes")
def get_episodes(title_id: int, season: int | None = None, db: Session = Depends(get_db), _profile: Profile = Depends(get_current_profile)):
    title = db.query(Title).filter(Title.id == title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    query = db.query(Episode).filter(Episode.title_id == title_id)
    if season is not None:
        query = query.filter(Episode.season == season)
    episodes = query.order_by(Episode.season, Episode.number).all()
    items = [
        {
            "id": ep.id,
            "title_id": ep.title_id,
            "season": ep.season,
            "number": ep.number,
            "name": ep.name,
            "synopsis": ep.synopsis or "",
            "duration": ep.duration or 0,
            "thumbnail": ep.thumbnail or title.backdrop or title.poster,
        }
        for ep in episodes
    ]
    return {"items": items, "total": len(items)}


@app.get("/api/genres")
def list_genres(db: Session = Depends(get_db), _profile: Profile = Depends(get_current_profile)):
    rows = (
        db.query(Genre.id, Genre.name, func.count(TitleGenre.title_id).label("title_count"))
        .outerjoin(TitleGenre, TitleGenre.genre_id == Genre.id)
        .group_by(Genre.id, Genre.name)
        .order_by(Genre.name.asc())
        .all()
    )
    items = [{"id": row.id, "name": row.name, "title_count": int(row.title_count or 0)} for row in rows]
    return {"items": items, "total": len(items)}


@app.get("/api/genres/{genre_id}/titles")
def genre_titles(genre_id: int, profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    genre = db.query(Genre).filter(Genre.id == genre_id).first()
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    titles = (
        db.query(Title)
        .join(TitleGenre, TitleGenre.title_id == Title.id)
        .filter(TitleGenre.genre_id == genre_id)
        .order_by(Title.rating.desc(), Title.name.asc())
        .all()
    )
    return {"items": _title_dicts(titles, db, profile), "total": len(titles), "genre": {"id": genre.id, "name": genre.name}}


@app.get("/api/search")
def search_titles(
    q: str = "",
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    needle = (q or "").strip()
    if not needle:
        return {"items": [], "total": 0, "query": needle}
    like = f"%{needle}%"
    titles = (
        db.query(Title)
        .outerjoin(TitleGenre, TitleGenre.title_id == Title.id)
        .outerjoin(Genre, Genre.id == TitleGenre.genre_id)
        .filter(or_(Title.name.ilike(like), Title.genre.ilike(like), Genre.name.ilike(like), Title.synopsis.ilike(like)))
        .distinct()
        .order_by(Title.rating.desc(), Title.name.asc())
        .limit(100)
        .all()
    )
    return {"items": _title_dicts(titles, db, profile), "total": len(titles), "query": needle}


@app.get("/api/my-list")
def get_my_list(profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    rows = (
        db.query(MyList, Title)
        .join(Title, Title.id == MyList.title_id)
        .filter(MyList.profile_id == profile.id)
        .order_by(MyList.created_at.desc(), MyList.id.desc())
        .all()
    )
    items = _title_dicts([title for _row, title in rows], db, profile)
    by_title = {item["id"]: item for item in items}
    for row, title in rows:
        by_title[title.id]["my_list_id"] = row.id
    return {"items": items, "total": len(items)}


@app.post("/api/my-list", status_code=201)
def add_to_my_list(payload: MyListCreate, profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    if payload.title_id is None:
        raise HTTPException(status_code=400, detail="title_id is required")
    title = db.query(Title).filter(Title.id == payload.title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Referenced title not found")
    entry = db.query(MyList).filter(MyList.profile_id == profile.id, MyList.title_id == title.id).first()
    created = False
    if not entry:
        entry = MyList(profile_id=profile.id, title_id=title.id)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        created = True
    item = _title_dict(title, db, profile)
    item["my_list_id"] = entry.id
    return {"item": item, "created": created}


@app.delete("/api/my-list/{entry_id}")
def remove_from_my_list(entry_id: int, profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    entry = db.query(MyList).filter(MyList.id == entry_id, MyList.profile_id == profile.id).first()
    if not entry:
        entry = db.query(MyList).filter(MyList.title_id == entry_id, MyList.profile_id == profile.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="My List entry not found")
    removed_id = entry.id
    title_id = entry.title_id
    db.delete(entry)
    db.commit()
    return {"item": {"id": removed_id, "title_id": title_id, "deleted": True}}


@app.put("/api/my-list/{entry_id}")
def update_my_list_entry(entry_id: int, profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    entry = db.query(MyList).filter(MyList.id == entry_id, MyList.profile_id == profile.id).first()
    if not entry:
        entry = db.query(MyList).filter(MyList.title_id == entry_id, MyList.profile_id == profile.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="My List entry not found")
    title = db.query(Title).filter(Title.id == entry.title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Referenced title not found")
    item = _title_dict(title, db, profile)
    item["my_list_id"] = entry.id
    return {"item": item}


@app.post("/api/titles/{title_id}/rating")
def rate_title(
    title_id: int,
    payload: RatingCreate,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    value = payload.value if payload.value is not None else payload.rating
    if value is None:
        raise HTTPException(status_code=400, detail="A rating value is required")
    if value not in (-1, 1, 2):
        raise HTTPException(status_code=400, detail="Rating must be -1, 1 or 2")
    title = db.query(Title).filter(Title.id == title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    row = db.query(Rating).filter(Rating.profile_id == profile.id, Rating.title_id == title_id).first()
    if value == 0:
        if row:
            db.delete(row)
            db.commit()
    elif row:
        row.value = value
        db.commit()
    else:
        db.add(Rating(profile_id=profile.id, title_id=title_id, value=value))
        db.commit()
    item = _title_dict(title, db, profile)
    return {"item": item, "rating": item.get("user_rating")}


@app.get("/api/continue-watching")
def get_continue_watching(profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    rows = (
        db.query(ContinueWatching, Title)
        .join(Title, Title.id == ContinueWatching.title_id)
        .filter(ContinueWatching.profile_id == profile.id, ContinueWatching.progress_seconds > 0)
        .order_by(ContinueWatching.updated_at.desc(), ContinueWatching.id.desc())
        .all()
    )
    titles = [title for _row, title in rows]
    items = _title_dicts(titles, db, profile)
    by_title = {item["id"]: item for item in items}
    for row, title in rows:
        item = by_title[title.id]
        item["cw_id"] = row.id
        item["progress_seconds"] = row.progress_seconds
        item["progress_percent"] = min(95, max(1, round((row.progress_seconds / max(title.duration or 1, 1)) * 100)))
    return {"items": items, "total": len(items)}


@app.post("/api/continue-watching")
def save_continue_watching(
    payload: ProgressCreate,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    if payload.title_id is None:
        raise HTTPException(status_code=400, detail="title_id is required")
    title = db.query(Title).filter(Title.id == payload.title_id).first()
    if not title:
        raise HTTPException(status_code=404, detail="Referenced title not found")
    progress = max(0, int(payload.progress_seconds or 0))
    row = db.query(ContinueWatching).filter(
        ContinueWatching.profile_id == profile.id, ContinueWatching.title_id == title.id
    ).first()
    if row:
        row.progress_seconds = progress
        row.updated_at = func.now()
    else:
        row = ContinueWatching(profile_id=profile.id, title_id=title.id, progress_seconds=progress)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"item": {"id": row.id, "title_id": title.id, "progress_seconds": row.progress_seconds}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BACKEND_PORT", "8000")), loop="asyncio", http="h11")
