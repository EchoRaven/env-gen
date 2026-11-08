"""Netflix catalog clone API.

The public contract is the 17 endpoints listed in the product specification. A few
additional endpoints (profile editing, playback progress, notifications) back visible
UI controls so the interface never contains a dead control.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg2 import IntegrityError

from .auth import create_token, decode_token, hash_password, verify_password
from .db import db_cursor, init_database

BASE_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = BASE_DIR / "static" / "assets"

app = FastAPI(title="Netflix Catalog API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if ASSET_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSET_DIR)), name="assets")


@app.on_event("startup")
def startup() -> None:
    init_database()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise _unauthorized(str(exc)) from exc
    with db_cursor() as cur:
        cur.execute("SELECT id, email, name FROM users WHERE id = %s", (int(payload["sub"]),))
        user = cur.fetchone()
    if not user:
        raise _unauthorized("User no longer exists")
    return dict(user)


async def payload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            return body if isinstance(body, dict) else {}
        except Exception:
            return {}
    if "form" in content_type:
        form = await request.form()
        return dict(form)
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def get_profile(user_id: int, request: Request, requested: Any = None) -> dict:
    """Resolve the profile for private data.

    The X-Profile-Id header is used by the React client. A profile_id field is also
    accepted so bearer-token API clients can scope writes explicitly.
    """
    profile_id = requested
    if profile_id in (None, "", "undefined", "null"):
        profile_id = request.query_params.get("profile_id")
    if profile_id in (None, "", "undefined", "null"):
        profile_id = request.headers.get("x-profile-id")
    with db_cursor() as cur:
        if profile_id not in (None, "", "undefined", "null"):
            try:
                profile_id = int(profile_id)
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail="Invalid profile_id") from exc
            cur.execute(
                "SELECT id, user_id, name, avatar, is_kids FROM profiles WHERE id=%s AND user_id=%s",
                (profile_id, user_id),
            )
            profile = cur.fetchone()
            if not profile:
                raise HTTPException(status_code=403, detail="Profile does not belong to this account")
            return dict(profile)
        cur.execute(
            "SELECT id, user_id, name, avatar, is_kids FROM profiles WHERE user_id=%s ORDER BY id LIMIT 1",
            (user_id,),
        )
        profile = cur.fetchone()
    if not profile:
        raise HTTPException(status_code=400, detail="Create a profile before using this feature")
    return dict(profile)


def _rating_to_int(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else -1
    if isinstance(value, (int, float)):
        value = int(value)
        if value in (-1, 0, 1, 2):
            return value
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"down", "thumbs_down", "thumb_down", "dislike"}:
        return -1
    if text in {"up", "thumbs_up", "thumb_up", "like"}:
        return 1
    if text in {"love", "two_thumbs", "two_thumbs_up", "double_thumbs_up"}:
        return 2
    try:
        number = int(float(text))
        if number in (-1, 0, 1, 2):
            return number
    except ValueError:
        pass
    raise HTTPException(status_code=422, detail="rating value must be -1, 1, or 2")


TITLE_FIELDS = """
    t.id, t.name, t.kind, t.year, t.genre, t.maturity_rating, t.rating,
    t.synopsis, t.poster, t.backdrop, t.video_url, t.duration, t.top10_rank,
    t.language,
    COALESCE((
        SELECT array_agg(g.name ORDER BY g.name)
        FROM title_genres tg JOIN genres g ON g.id = tg.genre_id
        WHERE tg.title_id = t.id
    ), ARRAY[]::text[]) AS genres,
    EXISTS(SELECT 1 FROM my_list ml WHERE ml.profile_id = %s AND ml.title_id = t.id) AS is_in_my_list,
    (SELECT r.value FROM ratings r WHERE r.profile_id = %s AND r.title_id = t.id LIMIT 1) AS my_rating,
    COALESCE((SELECT cw.progress_seconds FROM continue_watching cw
              WHERE cw.profile_id = %s AND cw.title_id = t.id LIMIT 1), 0) AS progress_seconds,
    COALESCE((SELECT MAX(e.season) FROM episodes e WHERE e.title_id = t.id), 0) AS seasons,
    COALESCE((SELECT COUNT(*) FROM episodes e WHERE e.title_id = t.id), 0) AS episode_count
"""


def serialize_title(row: dict) -> dict:
    item = dict(row)
    item["id"] = int(item["id"])
    item["year"] = int(item["year"]) if item.get("year") is not None else None
    item["rating"] = float(item["rating"] or 0)
    item["duration"] = int(item["duration"] or 0)
    item["top10_rank"] = int(item["top10_rank"]) if item.get("top10_rank") is not None else None
    item["genres"] = list(item.get("genres") or [])
    item["is_in_my_list"] = bool(item.get("is_in_my_list"))
    item["in_my_list"] = item["is_in_my_list"]
    item["my_rating"] = int(item["my_rating"]) if item.get("my_rating") is not None else None
    item["progress_seconds"] = int(item.get("progress_seconds") or 0)
    item["seasons"] = int(item.get("seasons") or 0)
    item["episode_count"] = int(item.get("episode_count") or 0)
    item["kind_label"] = "TV Show" if item.get("kind") == "series" else "Movie"
    item["duration_label"] = format_duration(item["duration"])
    return item


def format_duration(seconds: int) -> str:
    if not seconds:
        return "—"
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def fetch_titles(
    profile_id: int,
    *,
    where: str = "",
    params: tuple = (),
    order: str = "t.id",
    order_params: tuple = (),
    limit: int | None = None,
) -> list[dict]:
    clause = f" WHERE {where}" if where else ""
    sql = f"SELECT {TITLE_FIELDS} FROM titles t{clause} ORDER BY {order}"
    query_params: list[Any] = [profile_id, profile_id, profile_id, *params, *order_params]
    if limit is not None:
        sql += " LIMIT %s"
        query_params.append(int(limit))
    with db_cursor() as cur:
        cur.execute(sql, tuple(query_params))
        rows = cur.fetchall()
    return [serialize_title(row) for row in rows]


def fetch_one_title(profile_id: int, title_id: int) -> dict | None:
    rows = fetch_titles(profile_id, where="t.id = %s", params=(title_id,), limit=1)
    return rows[0] if rows else None


def require_title(cur, title_id: int) -> dict:
    cur.execute("SELECT * FROM titles WHERE id=%s", (title_id,))
    title = cur.fetchone()
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    return dict(title)


def _normalize_kind(kind: str | None) -> str | None:
    if not kind:
        return None
    lookup = {"tv": "series", "show": "series", "shows": "series", "series": "series", "movie": "movie", "movies": "movie"}
    return lookup.get(kind.lower(), kind.lower())


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@app.post("/auth/register")
async def register(request: Request):
    body = await payload(request)
    email = str(body.get("email") or body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    name = str(body.get("name") or body.get("display_name") or "").strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="A valid email is required")
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="Password must be at least 4 characters")
    if not name:
        name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO users (email,password_hash,name) VALUES (%s,%s,%s) RETURNING id,email,name",
                (email, hash_password(password), name),
            )
            user = dict(cur.fetchone())
            # Give new accounts a usable default profile immediately.
            cur.execute(
                "INSERT INTO profiles (user_id,name,avatar,is_kids) VALUES (%s,%s,%s,false) RETURNING id,name,avatar,is_kids",
                (user["id"], name.split()[0] if name else "Viewer", random.choice(["red", "blue", "green", "yellow"])),
            )
            profile = dict(cur.fetchone())
    except IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    return {
        "access_token": create_token(user["id"], user["email"]),
        "token_type": "bearer",
        "user": user,
        "profile": profile,
    }


@app.post("/auth/login")
async def login(request: Request):
    body = await payload(request)
    email = str(body.get("email") or body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    with db_cursor() as cur:
        cur.execute("SELECT id,email,password_hash,name FROM users WHERE lower(email)=%s", (email,))
        user = cur.fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    clean_user = {"id": user["id"], "email": user["email"], "name": user["name"]}
    return {
        "access_token": create_token(user["id"], user["email"]),
        "token_type": "bearer",
        "user": clean_user,
    }


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@app.get("/api/profiles")
def list_profiles(user: dict = Depends(current_user)):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id,user_id,name,avatar,is_kids FROM profiles WHERE user_id=%s ORDER BY id",
            (user["id"],),
        )
        return [dict(row) for row in cur.fetchall()]


@app.post("/api/profiles")
async def create_profile(request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Profile name is required")
    avatar = str(body.get("avatar") or random.choice(["red", "blue", "green", "yellow"]))
    is_kids = body.get("is_kids", False)
    if isinstance(is_kids, str):
        is_kids = is_kids.lower() in {"1", "true", "yes", "on"}
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO profiles (user_id,name,avatar,is_kids) VALUES (%s,%s,%s,%s) RETURNING id,user_id,name,avatar,is_kids",
            (user["id"], name, avatar, bool(is_kids)),
        )
        return dict(cur.fetchone())


@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: int, request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id FROM profiles WHERE id=%s AND user_id=%s", (profile_id, user["id"])
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Profile not found")
        cur.execute(
            "UPDATE profiles SET name=COALESCE(%s,name), avatar=COALESCE(%s,avatar), is_kids=COALESCE(%s,is_kids) WHERE id=%s RETURNING id,user_id,name,avatar,is_kids",
            (body.get("name"), body.get("avatar"), body.get("is_kids"), profile_id),
        )
        return dict(cur.fetchone())


@app.get("/api/notifications")
def notifications(user: dict = Depends(current_user)):
    """The supplied catalog has no notification feed; return an honest empty state."""
    return []


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(current_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) AS count FROM profiles WHERE user_id=%s", (user["id"],))
        if int(cur.fetchone()["count"]) <= 1:
            raise HTTPException(status_code=400, detail="An account must keep at least one profile")
        cur.execute("DELETE FROM profiles WHERE id=%s AND user_id=%s RETURNING id", (profile_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Profile not found")
    return {"success": True, "deleted_id": profile_id}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@app.get("/api/titles")
def list_titles(
    request: Request,
    kind: str | None = None,
    genre: str | None = None,
    genre_id: int | None = None,
    q: str | None = None,
    language: str | None = None,
    year: int | None = None,
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(current_user),
):
    profile = get_profile(user["id"], request)
    clauses: list[str] = []
    params: list[Any] = []
    normalized_kind = _normalize_kind(kind)
    if normalized_kind:
        clauses.append("t.kind = %s")
        params.append(normalized_kind)
    if genre:
        clauses.append("(t.genre ILIKE %s OR EXISTS (SELECT 1 FROM title_genres tg JOIN genres g ON g.id=tg.genre_id WHERE tg.title_id=t.id AND g.name ILIKE %s))")
        params.extend([f"%{genre}%", f"%{genre}%"])
    if genre_id:
        clauses.append("EXISTS (SELECT 1 FROM title_genres tg WHERE tg.title_id=t.id AND tg.genre_id=%s)")
        params.append(genre_id)
    if q:
        clauses.append("(t.name ILIKE %s OR COALESCE(t.genre,'') ILIKE %s OR COALESCE(t.synopsis,'') ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if language:
        clauses.append("t.language = %s")
        params.append(language)
    if year:
        clauses.append("t.year = %s")
        params.append(year)
    where = " AND ".join(clauses)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows = fetch_titles(
        profile["id"],
        where=where,
        params=tuple(params),
        order="COALESCE(t.top10_rank,999), t.rating DESC, t.id",
        limit=limit,
    )
    return rows[offset:]


@app.get("/api/titles/trending")
def trending(
    request: Request,
    kind: str | None = None,
    limit: int = 20,
    user: dict = Depends(current_user),
):
    profile = get_profile(user["id"], request)
    normalized_kind = _normalize_kind(kind)
    where = "t.kind = %s" if normalized_kind else ""
    params: tuple = (normalized_kind,) if normalized_kind else ()
    return fetch_titles(
        profile["id"],
        where=where,
        params=params,
        order="CASE WHEN t.top10_rank IS NULL THEN 1 ELSE 0 END, t.top10_rank, t.rating DESC, t.id",
        limit=max(1, min(int(limit), 60)),
    )


@app.get("/api/titles/top10")
def top10(
    request: Request,
    kind: str | None = None,
    user: dict = Depends(current_user),
):
    profile = get_profile(user["id"], request)
    normalized_kind = _normalize_kind(kind)
    where = "t.kind = %s" if normalized_kind else ""
    params: tuple = (normalized_kind,) if normalized_kind else ()
    rows = fetch_titles(
        profile["id"],
        where=where,
        params=params,
        order="CASE WHEN t.top10_rank IS NULL THEN 1 ELSE 0 END, t.top10_rank, t.rating DESC, t.id",
        limit=10,
    )
    for index, row in enumerate(rows, 1):
        row["top10_rank"] = index
    return rows


@app.get("/api/titles/{title_id}")
def get_title(title_id: int, request: Request, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    title = fetch_one_title(profile["id"], title_id)
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    with db_cursor() as cur:
        cur.execute(
            "SELECT id,name FROM genres g WHERE EXISTS (SELECT 1 FROM title_genres tg WHERE tg.genre_id=g.id AND tg.title_id=%s) ORDER BY name",
            (title_id,),
        )
        title["genre_details"] = [dict(row) for row in cur.fetchall()]
        cur.execute(
            "SELECT cw.progress_seconds FROM continue_watching cw WHERE cw.profile_id=%s AND cw.title_id=%s",
            (profile["id"], title_id),
        )
        progress = cur.fetchone()
        title["progress_seconds"] = int(progress["progress_seconds"]) if progress else 0
    return title


@app.get("/api/titles/{title_id}/episodes")
def get_episodes(title_id: int, request: Request, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    with db_cursor() as cur:
        require_title(cur, title_id)
        cur.execute(
            "SELECT id,title_id,season,number,name,synopsis,duration,thumbnail FROM episodes WHERE title_id=%s ORDER BY season,number",
            (title_id,),
        )
        episodes = []
        for row in cur.fetchall():
            episode = dict(row)
            episode["duration_label"] = format_duration(int(episode["duration"] or 0))
            episode["progress_seconds"] = 0
            episodes.append(episode)
    return episodes


@app.get("/api/genres")
def list_genres(request: Request, kind: str | None = None, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    normalized_kind = _normalize_kind(kind)
    sql = """
        SELECT g.id, g.name, COUNT(DISTINCT t.id)::int AS title_count
        FROM genres g
        JOIN title_genres tg ON tg.genre_id = g.id
        JOIN titles t ON t.id = tg.title_id
    """
    params: list[Any] = []
    if normalized_kind:
        sql += " WHERE t.kind = %s"
        params.append(normalized_kind)
    sql += " GROUP BY g.id,g.name HAVING COUNT(DISTINCT t.id) > 0 ORDER BY g.name"
    with db_cursor() as cur:
        cur.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]


@app.get("/api/genres/{genre_id}/titles")
def genre_titles(
    genre_id: int,
    request: Request,
    kind: str | None = None,
    user: dict = Depends(current_user),
):
    profile = get_profile(user["id"], request)
    with db_cursor() as cur:
        cur.execute("SELECT id,name FROM genres WHERE id=%s", (genre_id,))
        genre = cur.fetchone()
        if not genre:
            raise HTTPException(status_code=404, detail="Genre not found")
    clauses = ["EXISTS (SELECT 1 FROM title_genres tg WHERE tg.title_id=t.id AND tg.genre_id=%s)"]
    params: list[Any] = [genre_id]
    normalized_kind = _normalize_kind(kind)
    if normalized_kind:
        clauses.append("t.kind=%s")
        params.append(normalized_kind)
    return fetch_titles(
        profile["id"],
        where=" AND ".join(clauses),
        params=tuple(params),
        order="t.rating DESC, t.id",
    )


@app.get("/api/search")
def search(
    request: Request,
    q: str | None = None,
    query: str | None = None,
    kind: str | None = None,
    user: dict = Depends(current_user),
):
    profile = get_profile(user["id"], request)
    term = (q or query or "").strip()
    if not term:
        return []
    params: list[Any] = [f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%"]
    where = (
        "(t.name ILIKE %s OR COALESCE(t.genre,'') ILIKE %s "
        "OR COALESCE(t.synopsis,'') ILIKE %s OR EXISTS ("
        "SELECT 1 FROM title_genres tg JOIN genres g ON g.id=tg.genre_id "
        "WHERE tg.title_id=t.id AND g.name ILIKE %s))"
    )
    normalized_kind = _normalize_kind(kind)
    if normalized_kind:
        where += " AND t.kind=%s"
        params.append(normalized_kind)
    normalized_term = term.lower()
    prefix = f"{normalized_term}%"
    return fetch_titles(
        profile["id"],
        where=where,
        params=tuple(params),
        order="CASE WHEN lower(t.name)=%s THEN 0 WHEN lower(t.name) LIKE %s THEN 1 ELSE 2 END, t.rating DESC, t.id",
        order_params=(normalized_term, prefix),
        limit=60,
    )


# ---------------------------------------------------------------------------
# Profile-private collections
# ---------------------------------------------------------------------------


@app.get("/api/my-list")
def my_list(request: Request, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    rows = fetch_titles(
        profile["id"],
        where="EXISTS (SELECT 1 FROM my_list ml WHERE ml.profile_id=%s AND ml.title_id=t.id)",
        params=(profile["id"],),
        order="(SELECT ml.id FROM my_list ml WHERE ml.profile_id=%s AND ml.title_id=t.id) DESC",
        order_params=(profile["id"],),
    )
    if rows:
        with db_cursor() as cur:
            cur.execute(
                "SELECT title_id,id AS my_list_id FROM my_list WHERE profile_id=%s",
                (profile["id"],),
            )
            ids = {int(r["title_id"]): int(r["my_list_id"]) for r in cur.fetchall()}
        for row in rows:
            row["my_list_id"] = ids.get(row["id"])
            row["is_in_my_list"] = True
            row["in_my_list"] = True
    return rows


@app.post("/api/my-list")
async def add_to_my_list(request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    profile = get_profile(user["id"], request, body.get("profile_id"))
    raw_title_id = body.get("title_id", body.get("titleId", body.get("id")))
    try:
        title_id = int(raw_title_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="title_id is required") from exc
    with db_cursor(commit=True) as cur:
        require_title(cur, title_id)
        cur.execute(
            "INSERT INTO my_list (profile_id,title_id) VALUES (%s,%s) ON CONFLICT (profile_id,title_id) DO NOTHING RETURNING id",
            (profile["id"], title_id),
        )
        inserted = cur.fetchone()
        cur.execute(
            "SELECT id FROM my_list WHERE profile_id=%s AND title_id=%s",
            (profile["id"], title_id),
        )
        item = cur.fetchone()
    title = fetch_one_title(profile["id"], title_id)
    return {
        "id": int(item["id"]),
        "my_list_id": int(item["id"]),
        "profile_id": profile["id"],
        "title_id": title_id,
        "created": bool(inserted),
        "title": title,
    }


@app.put("/api/my-list/{item_id}")
async def update_my_list_item(item_id: int, request: Request, user: dict = Depends(current_user)):
    """Update an existing My List entry.

    The UI exposes add/remove, while PUT keeps the profile-scoped resource
    contract complete. Missing or foreign entries return 404.
    """
    body = await payload(request)
    profile = get_profile(user["id"], request, body.get("profile_id"))
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, profile_id, title_id FROM my_list WHERE profile_id=%s AND (id=%s OR title_id=%s) LIMIT 1",
            (profile["id"], item_id, item_id),
        )
        item = cur.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Title is not in this profile's My List")
        requested_title = body.get("title_id")
        if requested_title is not None:
            try:
                new_title_id = int(requested_title)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="title_id must be an integer") from exc
            require_title(cur, new_title_id)
            try:
                cur.execute(
                    "UPDATE my_list SET title_id=%s WHERE id=%s RETURNING id, profile_id, title_id",
                    (new_title_id, item["id"]),
                )
                item = cur.fetchone()
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Title is already in this profile's My List")
    return {
        "id": int(item["id"]),
        "profile_id": int(item["profile_id"]),
        "title_id": int(item["title_id"]),
    }


@app.delete("/api/my-list/{item_id}")
async def remove_from_my_list(item_id: int, request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    profile = get_profile(user["id"], request, body.get("profile_id"))
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM my_list WHERE profile_id=%s AND (id=%s OR title_id=%s) RETURNING id,title_id",
            (profile["id"], item_id, item_id),
        )
        deleted = cur.fetchone()
    if not deleted:
        raise HTTPException(status_code=404, detail="Title is not in this profile's My List")
    return {"success": True, "deleted_id": int(deleted["id"]), "title_id": int(deleted["title_id"])}


@app.post("/api/titles/{title_id}/rating")
async def rate_title(title_id: int, request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    profile = get_profile(user["id"], request, body.get("profile_id"))
    value = _rating_to_int(body.get("value", body.get("rating")))
    with db_cursor(commit=True) as cur:
        require_title(cur, title_id)
        cur.execute(
            """
            INSERT INTO ratings (profile_id,title_id,value) VALUES (%s,%s,%s)
            ON CONFLICT (profile_id,title_id) DO UPDATE SET value=EXCLUDED.value
            RETURNING id,profile_id,title_id,value
            """,
            (profile["id"], title_id, value),
        )
        rating = dict(cur.fetchone())
    return rating


@app.get("/api/continue-watching")
def continue_watching(request: Request, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    rows = fetch_titles(
        profile["id"],
        where="EXISTS (SELECT 1 FROM continue_watching cw WHERE cw.profile_id=%s AND cw.title_id=t.id)",
        params=(profile["id"],),
        order="(SELECT cw.updated_at FROM continue_watching cw WHERE cw.profile_id=%s AND cw.title_id=t.id) DESC",
        order_params=(profile["id"],),
    )
    with db_cursor() as cur:
        cur.execute(
            "SELECT id,title_id,progress_seconds FROM continue_watching WHERE profile_id=%s",
            (profile["id"],),
        )
        progress = {int(r["title_id"]): r for r in cur.fetchall()}
    for row in rows:
        record = progress.get(row["id"])
        if record:
            row["continue_watching_id"] = int(record["id"])
            row["progress_seconds"] = int(record["progress_seconds"])
            row["progress_percent"] = round(
                min(100, 100 * row["progress_seconds"] / max(1, row["duration"])), 1
            )
    return rows


@app.post("/api/continue-watching")
async def update_continue_watching(request: Request, user: dict = Depends(current_user)):
    body = await payload(request)
    profile = get_profile(user["id"], request, body.get("profile_id"))
    try:
        title_id = int(body.get("title_id", body.get("titleId")))
        progress_seconds = max(0, int(float(body.get("progress_seconds", body.get("progress", 0)))))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="title_id and progress_seconds are required") from exc
    episode_id = body.get("episode_id")
    with db_cursor(commit=True) as cur:
        require_title(cur, title_id)
        cur.execute(
            """
            INSERT INTO continue_watching (profile_id,title_id,progress_seconds,updated_at)
            VALUES (%s,%s,%s,NOW())
            ON CONFLICT (profile_id,title_id) DO UPDATE
              SET progress_seconds=EXCLUDED.progress_seconds, updated_at=NOW()
            RETURNING id,profile_id,title_id,progress_seconds
            """,
            (profile["id"], title_id, progress_seconds),
        )
        record = dict(cur.fetchone())
    record["episode_id"] = episode_id
    return record


@app.delete("/api/continue-watching/{title_id}")
def delete_continue_watching(title_id: int, request: Request, user: dict = Depends(current_user)):
    profile = get_profile(user["id"], request)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM continue_watching WHERE profile_id=%s AND title_id=%s RETURNING id",
            (profile["id"], title_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Not in Continue Watching")
    return {"success": True, "title_id": title_id}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers or {},
    )
