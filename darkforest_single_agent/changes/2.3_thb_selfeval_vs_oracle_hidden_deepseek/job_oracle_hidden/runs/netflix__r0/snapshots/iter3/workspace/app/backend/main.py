import base64
import hashlib
import hmac
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import jwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://netflix:netflix@database:5432/netflix",
)
JWT_SECRET = os.getenv("JWT_SECRET", "netflix-clone-local-secret-change-me")
JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(days=7)
ASSET_DIR = Path(__file__).resolve().parent / "assets"


app = FastAPI(title="Netflix Catalog API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/assets", StaticFiles(directory=ASSET_DIR), name="assets")


@contextmanager
def db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    email: str
    password: str
    name: Optional[str] = None


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    email: str
    password: str


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    avatar: str = "red"
    is_kids: bool = False


class MyListInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    title_id: Optional[int] = None
    id: Optional[int] = None
    profile_id: Optional[int] = None


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    title_id: Optional[int] = None
    id: Optional[int] = None
    value: Optional[int | str] = None
    rating: Optional[int | str] = None
    profile_id: Optional[int] = None


class ProgressInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    title_id: Optional[int] = None
    id: Optional[int] = None
    profile_id: Optional[int] = None
    progress_seconds: int = 0


def hash_password(password: str) -> str:
    salt = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"pbkdf2_sha256$260000${salt}${encoded}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, encoded = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        actual = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return hmac.compare_digest(actual, encoded)
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "email": email, "iat": now, "exp": now + TOKEN_LIFETIME},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_user(request: Request) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise unauthorized("Missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise unauthorized("Missing bearer token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", ""))
    except (jwt.PyJWTError, ValueError, TypeError):
        raise unauthorized("Invalid or expired token")
    with db() as conn:
        row = conn.execute(
            "SELECT id, email, name FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    if not row:
        raise unauthorized("User no longer exists")
    return row


def profile_for_request(
    request: Request,
    user_id: int,
    body_profile_id: Optional[int] = None,
    required: bool = False,
) -> Optional[dict[str, Any]]:
    raw_id = (
        request.headers.get("x-profile-id")
        or request.headers.get("x-profile")
        or request.query_params.get("profile_id")
    )
    requested_id: Optional[int] = body_profile_id
    if raw_id not in (None, ""):
        try:
            requested_id = int(raw_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid profile id")
    with db() as conn:
        if requested_id is not None:
            row = conn.execute(
                "SELECT id, user_id, name, avatar, is_kids FROM profiles "
                "WHERE id = %s AND user_id = %s",
                (requested_id, user_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Profile does not belong to this account")
            return row
        row = conn.execute(
            "SELECT id, user_id, name, avatar, is_kids FROM profiles "
            "WHERE user_id = %s ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()
    if required and not row:
        with db() as conn:
            owner = conn.execute("SELECT name FROM users WHERE id = %s", (user_id,)).fetchone()
            row = conn.execute(
                "INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, %s, 'red', FALSE) "
                "RETURNING id, user_id, name, avatar, is_kids",
                (user_id, ((owner or {}).get("name") or "Viewer")[:120]),
            ).fetchone()
            conn.commit()
    return row


TITLE_SELECT = """
SELECT
  t.id, t.name, t.kind, t.year, t.genre, t.maturity_rating,
  t.rating::float AS rating, t.synopsis, t.poster, t.backdrop,
  t.video_url, t.duration, t.top10_rank, t.language,
  (SELECT COUNT(DISTINCT e.season)::int FROM episodes e WHERE e.title_id = t.id) AS seasons,
  COALESCE(
    json_agg(g.name ORDER BY g.name) FILTER (WHERE g.name IS NOT NULL),
    '[]'::json
  ) AS genres,
  (SELECT r.value FROM ratings r WHERE r.title_id = t.id AND r.profile_id = %(profile_id)s) AS my_rating,
  EXISTS(
    SELECT 1 FROM my_list ml WHERE ml.title_id = t.id AND ml.profile_id = %(profile_id)s
  ) AS in_my_list
FROM titles t
LEFT JOIN title_genres tg ON tg.title_id = t.id
LEFT JOIN genres g ON g.id = tg.genre_id
"""


def profile_key(profile: Optional[dict[str, Any]]) -> int:
    return int(profile["id"]) if profile else -1


def fetch_titles(
    profile: Optional[dict[str, Any]],
    *,
    where: str = "",
    params: Optional[dict[str, Any]] = None,
    order: str = "t.id",
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    query_params: dict[str, Any] = {"profile_id": profile_key(profile)}
    if params:
        query_params.update(params)
    sql = TITLE_SELECT + where + " GROUP BY t.id ORDER BY " + order
    if limit is not None:
        sql += " LIMIT %(limit)s"
        query_params["limit"] = max(0, int(limit))
    with db() as conn:
        return [dict(row) for row in conn.execute(sql, query_params).fetchall()]


def get_title(title_id: int, profile: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    rows = fetch_titles(profile, where=" WHERE t.id = %(title_id)s", params={"title_id": title_id}, limit=1)
    return rows[0] if rows else None


def serialize_episode(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title_id": row["title_id"],
        "season": row["season"],
        "number": row["number"],
        "name": row["name"],
        "title": row["name"],
        "synopsis": row["synopsis"],
        "duration": row["duration"],
        "thumbnail": row["thumbnail"],
    }


def entry_with_title(entry: dict[str, Any], title: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    result["title"] = title
    for key in (
        "name", "kind", "year", "genre", "maturity_rating", "rating", "synopsis",
        "poster", "backdrop", "video_url", "duration", "top10_rank", "language", "genres", "in_my_list",
    ):
        result[key] = title.get(key)
    return result


@app.get("/health")
def health():
    return {"status": "ok", "service": "netflix-api"}


@app.post("/auth/register")
def register(payload: RegisterInput):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    name = (payload.name or email.split("@")[0]).strip() or "Viewer"
    try:
        with db() as conn:
            existing = conn.execute("SELECT id FROM users WHERE lower(email) = %s", (email,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="An account with this email already exists")
            user = conn.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) "
                "RETURNING id, email, name",
                (email, hash_password(payload.password), name),
            ).fetchone()
            conn.commit()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    token = create_token(user["id"], user["email"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
        "profiles": [],
    }


@app.post("/auth/login")
def login(payload: LoginInput):
    email = payload.email.strip().lower()
    with db() as conn:
        user = conn.execute(
            "SELECT id, email, name, password_hash FROM users WHERE lower(email) = %s",
            (email,),
        ).fetchone()
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        profiles = [
            dict(row)
            for row in conn.execute(
                "SELECT id, user_id, name, avatar, is_kids FROM profiles "
                "WHERE user_id = %s ORDER BY id",
                (user["id"],),
            ).fetchall()
        ]
    public_user = {"id": user["id"], "email": user["email"], "name": user["name"]}
    return {
        "access_token": create_token(user["id"], user["email"]),
        "token_type": "bearer",
        "user": public_user,
        "profiles": profiles,
    }


@app.get("/api/profiles")
def list_profiles(user=Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, user_id, name, avatar, is_kids FROM profiles "
            "WHERE user_id = %s ORDER BY id",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/profiles")
def create_profile(payload: ProfileInput, user=Depends(require_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    with db() as conn:
        row = conn.execute(
            "INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, %s, %s, %s) "
            "RETURNING id, user_id, name, avatar, is_kids",
            (user["id"], name[:120], payload.avatar or "red", payload.is_kids),
        ).fetchone()
        conn.commit()
    return dict(row)


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProfileInput, user=Depends(require_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    with db() as conn:
        row = conn.execute(
            "UPDATE profiles SET name = %s, avatar = %s, is_kids = %s "
            "WHERE id = %s AND user_id = %s "
            "RETURNING id, user_id, name, avatar, is_kids",
            (name[:120], payload.avatar or "red", payload.is_kids, profile_id, user["id"]),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return dict(row)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user=Depends(require_user)):
    with db() as conn:
        profile = conn.execute(
            "SELECT id FROM profiles WHERE id = %s AND user_id = %s",
            (profile_id, user["id"]),
        ).fetchone()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        count = conn.execute(
            "SELECT COUNT(*)::int AS total FROM profiles WHERE user_id = %s", (user["id"],)
        ).fetchone()["total"]
        if count <= 1:
            raise HTTPException(status_code=400, detail="An account must keep at least one profile")
        conn.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))
        conn.commit()
    return {"ok": True, "deleted": True, "id": profile_id}


@app.get("/api/titles")
def list_titles(
    request: Request,
    kind: Optional[str] = None,
    genre: Optional[str] = None,
    q: Optional[str] = None,
    language: Optional[str] = None,
    year: Optional[str] = None,
    limit: int = Query(100, ge=0, le=200),
    user=Depends(require_user),
):
    profile = profile_for_request(request, user["id"])
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if kind:
        clauses.append("LOWER(t.kind) = LOWER(%(kind)s)")
        params["kind"] = kind
    if genre:
        if str(genre).isdigit():
            clauses.append(
                "EXISTS (SELECT 1 FROM title_genres xtg WHERE xtg.title_id = t.id AND xtg.genre_id = %(genre_id)s)"
            )
            params["genre_id"] = int(genre)
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM title_genres xtg JOIN genres xg ON xg.id = xtg.genre_id "
                "WHERE xtg.title_id = t.id AND LOWER(xg.name) = LOWER(%(genre_name)s))"
            )
            params["genre_name"] = genre
    if language:
        clauses.append("LOWER(t.language) = LOWER(%(language)s)")
        params["language"] = language
    if year:
        clauses.append("t.year = %(year)s")
        params["year"] = year
    if q:
        clauses.append(
            "(t.name ILIKE %(search)s OR t.synopsis ILIKE %(search)s OR EXISTS ("
            "SELECT 1 FROM title_genres stg JOIN genres sg ON sg.id = stg.genre_id "
            "WHERE stg.title_id = t.id AND sg.name ILIKE %(search)s))"
        )
        params["search"] = f"%{q.strip()}%"
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return fetch_titles(profile, where=where, params=params, order="t.id", limit=limit)


@app.get("/api/titles/trending")
def trending_titles(request: Request, limit: int = Query(20, ge=0, le=100), user=Depends(require_user)):
    profile = profile_for_request(request, user["id"])
    return fetch_titles(profile, order="t.rating DESC, t.id", limit=limit)


@app.get("/api/titles/top10")
def top10_titles(
    request: Request,
    kind: Optional[str] = None,
    limit: int = Query(10, ge=0, le=50),
    user=Depends(require_user),
):
    profile = profile_for_request(request, user["id"])
    where = " WHERE t.top10_rank IS NOT NULL"
    params: dict[str, Any] = {}
    if kind:
        where += " AND LOWER(t.kind) = LOWER(%(kind)s)"
        params["kind"] = kind
    return fetch_titles(
        profile,
        where=where,
        params=params,
        order="t.top10_rank ASC, t.rating DESC, t.id",
        limit=limit,
    )


@app.get("/api/titles/{title_id}")
def title_detail(title_id: int, request: Request, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"])
    title = get_title(title_id, profile)
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    with db() as conn:
        season_row = conn.execute(
            "SELECT COUNT(DISTINCT season) AS seasons FROM episodes WHERE title_id = %s",
            (title_id,),
        ).fetchone()
    title["seasons"] = int(season_row["seasons"] or 0)
    return title


@app.get("/api/titles/{title_id}/episodes")
def title_episodes(title_id: int, season: Optional[int] = None, user=Depends(require_user)):
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM titles WHERE id = %s", (title_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Title not found")
        if season is None:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE title_id = %s ORDER BY season, number",
                (title_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE title_id = %s AND season = %s ORDER BY number",
                (title_id, season),
            ).fetchall()
    return [serialize_episode(dict(row)) for row in rows]


@app.get("/api/genres")
def genres(user=Depends(require_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT g.id, g.name, COUNT(tg.title_id)::int AS title_count "
            "FROM genres g LEFT JOIN title_genres tg ON tg.genre_id = g.id "
            "GROUP BY g.id, g.name ORDER BY g.name"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/genres/{genre_id}/titles")
def genre_titles(genre_id: int, request: Request, limit: int = Query(100, ge=0, le=200), user=Depends(require_user)):
    profile = profile_for_request(request, user["id"])
    with db() as conn:
        genre = conn.execute("SELECT id, name FROM genres WHERE id = %s", (genre_id,)).fetchone()
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    return fetch_titles(
        profile,
        where=(
            " WHERE EXISTS (SELECT 1 FROM title_genres xtg WHERE xtg.title_id = t.id "
            "AND xtg.genre_id = %(genre_id)s)"
        ),
        params={"genre_id": genre_id},
        order="t.rating DESC, t.id",
        limit=limit,
    )


@app.get("/api/search")
def search(
    request: Request,
    q: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = Query(50, ge=0, le=200),
    user=Depends(require_user),
):
    term = (q or query or "").strip()
    if not term:
        return []
    profile = profile_for_request(request, user["id"])
    return fetch_titles(
        profile,
        where=(
            " WHERE (t.name ILIKE %(search)s OR t.synopsis ILIKE %(search)s OR EXISTS ("
            "SELECT 1 FROM title_genres stg JOIN genres sg ON sg.id = stg.genre_id "
            "WHERE stg.title_id = t.id AND sg.name ILIKE %(search)s))"
        ),
        params={
            "search": f"%{term}%",
            "exact": term,
            "prefix": f"{term}%",
        },
        order="CASE WHEN LOWER(t.name) = LOWER(%(exact)s) THEN 0 WHEN t.name ILIKE %(prefix)s THEN 1 ELSE 2 END, t.rating DESC, t.id",
        limit=limit,
    )


@app.get("/api/my-list")
def my_list(request: Request, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"])
    if not profile:
        return []
    with db() as conn:
        rows = conn.execute(
            "SELECT id, profile_id, title_id, created_at FROM my_list "
            "WHERE profile_id = %s ORDER BY created_at DESC, id DESC",
            (profile["id"],),
        ).fetchall()
    titles = {
        title["id"]: title
        for title in fetch_titles(profile, where=" WHERE t.id = ANY(%(ids)s)", params={"ids": [r["title_id"] for r in rows]})
    } if rows else {}
    return [entry_with_title(dict(row), titles[row["title_id"]]) for row in rows if row["title_id"] in titles]


@app.post("/api/my-list")
def add_my_list(payload: MyListInput, request: Request, user=Depends(require_user)):
    title_id = payload.title_id or payload.id
    if not title_id:
        raise HTTPException(status_code=422, detail="title_id is required")
    profile = profile_for_request(request, user["id"], payload.profile_id, required=True)
    title = get_title(title_id, profile)
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    with db() as conn:
        row = conn.execute(
            "INSERT INTO my_list (profile_id, title_id) VALUES (%s, %s) "
            "ON CONFLICT (profile_id, title_id) DO UPDATE SET title_id = EXCLUDED.title_id "
            "RETURNING id, profile_id, title_id, created_at",
            (profile["id"], title_id),
        ).fetchone()
        conn.commit()
    title = {**title, "in_my_list": True}
    return entry_with_title(dict(row), title)


@app.put("/api/my-list/{entry_id}")
def update_my_list(entry_id: int, request: Request, payload: Optional[MyListInput] = None, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"], required=True)
    with db() as conn:
        entry = conn.execute(
            "SELECT id, profile_id, title_id, created_at FROM my_list "
            "WHERE profile_id = %s AND (id = %s OR title_id = %s) "
            "ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END LIMIT 1",
            (profile["id"], entry_id, entry_id, entry_id),
        ).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="Title is not in My List")
        next_title_id = (payload.title_id or payload.id) if payload else None
        next_title_id = next_title_id or entry["title_id"]
        title = get_title(next_title_id, profile)
        if not title:
            raise HTTPException(status_code=404, detail="Title not found")
        if next_title_id != entry["title_id"]:
            try:
                entry = conn.execute(
                    "UPDATE my_list SET title_id = %s WHERE id = %s RETURNING id, profile_id, title_id, created_at",
                    (next_title_id, entry["id"]),
                ).fetchone()
                conn.commit()
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                raise HTTPException(status_code=409, detail="Title is already in My List")
    return entry_with_title(dict(entry), {**title, "in_my_list": True})


@app.delete("/api/my-list/{entry_id}")
def delete_my_list(entry_id: int, request: Request, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"], required=True)
    with db() as conn:
        row = conn.execute(
            "DELETE FROM my_list WHERE profile_id = %s AND id = %s "
            "RETURNING id, title_id",
            (profile["id"], entry_id),
        ).fetchone()
        if not row:
            row = conn.execute(
                "DELETE FROM my_list WHERE profile_id = %s AND title_id = %s "
                "RETURNING id, title_id",
                (profile["id"], entry_id),
            ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Title is not in My List")
    return {"ok": True, "deleted": True, "id": row["id"], "title_id": row["title_id"]}


@app.post("/api/titles/{title_id}/rating")
def rate_title(title_id: int, payload: RatingInput, request: Request, user=Depends(require_user)):
    value = payload.value if payload.value is not None else payload.rating
    if value is None:
        raise HTTPException(status_code=422, detail="value is required")
    if isinstance(value, str):
        aliases = {
            "down": -1, "thumbs_down": -1, "thumbs-down": -1, "dislike": -1,
            "up": 1, "thumbs_up": 1, "thumbs-up": 1, "like": 1,
            "love": 2, "two_thumbs": 2, "two-thumbs": 2,
        }
        value = aliases.get(value.lower(), value)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="value must be -1, 1, or 2")
    if value not in (-1, 1, 2):
        raise HTTPException(status_code=422, detail="value must be -1 (down), 1 (up), or 2 (love)")
    profile = profile_for_request(request, user["id"], payload.profile_id, required=True)
    title = get_title(title_id, profile)
    if not title:
        raise HTTPException(status_code=404, detail="Title not found")
    with db() as conn:
        row = conn.execute(
            "INSERT INTO ratings (profile_id, title_id, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (profile_id, title_id) DO UPDATE SET value = EXCLUDED.value "
            "RETURNING id, profile_id, title_id, value",
            (profile["id"], title_id, value),
        ).fetchone()
        conn.commit()
    result = dict(row)
    result["title"] = title
    result["rating"] = title["rating"]
    return result


@app.get("/api/continue-watching")
def continue_watching(request: Request, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"])
    if not profile:
        return []
    with db() as conn:
        rows = conn.execute(
            "SELECT id, profile_id, title_id, progress_seconds, updated_at "
            "FROM continue_watching WHERE profile_id = %s "
            "ORDER BY updated_at DESC, id DESC",
            (profile["id"],),
        ).fetchall()
    titles = {
        title["id"]: title
        for title in fetch_titles(profile, where=" WHERE t.id = ANY(%(ids)s)", params={"ids": [r["title_id"] for r in rows]})
    } if rows else {}
    return [entry_with_title(dict(row), titles[row["title_id"]]) for row in rows if row["title_id"] in titles]


@app.post("/api/continue-watching")
def save_continue_watching(payload: ProgressInput, request: Request, user=Depends(require_user)):
    title_id = payload.title_id or payload.id
    if not title_id:
        raise HTTPException(status_code=422, detail="title_id is required")
    profile = profile_for_request(request, user["id"], payload.profile_id, required=True)
    if not get_title(title_id, profile):
        raise HTTPException(status_code=404, detail="Title not found")
    with db() as conn:
        row = conn.execute(
            "INSERT INTO continue_watching (profile_id, title_id, progress_seconds) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (profile_id, title_id) DO UPDATE SET "
            "progress_seconds = EXCLUDED.progress_seconds, updated_at = NOW() "
            "RETURNING id, profile_id, title_id, progress_seconds, updated_at",
            (profile["id"], title_id, max(0, int(payload.progress_seconds))),
        ).fetchone()
        conn.commit()
    return dict(row)


@app.delete("/api/continue-watching/{entry_id}")
def remove_continue_watching(entry_id: int, request: Request, user=Depends(require_user)):
    profile = profile_for_request(request, user["id"], required=True)
    with db() as conn:
        row = conn.execute(
            "DELETE FROM continue_watching WHERE profile_id = %s AND id = %s "
            "RETURNING id, title_id",
            (profile["id"], entry_id),
        ).fetchone()
        if not row:
            row = conn.execute(
                "DELETE FROM continue_watching WHERE profile_id = %s AND title_id = %s "
                "RETURNING id, title_id",
                (profile["id"], entry_id),
            ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Continue watching entry not found")
    return {"ok": True, "deleted": True, **dict(row)}


@app.exception_handler(psycopg.Error)
async def database_error_handler(request: Request, exc: psycopg.Error):
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


@app.get("/")
def root():
    return {"service": "Netflix Catalog API", "health": "/health", "docs": "/docs"}
