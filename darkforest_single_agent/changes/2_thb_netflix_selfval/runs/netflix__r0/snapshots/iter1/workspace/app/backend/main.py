"""Netflix clone API — FastAPI + Postgres (psycopg3).

Per-profile private data (My List, ratings, Continue Watching) is scoped by the
`X-Profile-Id` header, which must name a profile owned by the authenticated
user. Without the header the user's first profile is used.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from contextlib import contextmanager
from typing import Any, Optional

# Sandbox hosts may block new pthreads: run sync endpoints inline (no threadpool).
import starlette.concurrency
import fastapi.routing
import fastapi.dependencies.utils


async def _run_without_threadpool(func, *args, **kwargs):
    return func(*args, **kwargs)


starlette.concurrency.run_in_threadpool = _run_without_threadpool
fastapi.routing.run_in_threadpool = _run_without_threadpool
fastapi.dependencies.utils.run_in_threadpool = _run_without_threadpool

import jwt
import psycopg
from psycopg.rows import dict_row
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://netflix:netflix@127.0.0.1:5432/netflix")
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
JWT_TTL = int(os.getenv("JWT_TTL_SECONDS", str(7 * 24 * 3600)))
PBKDF2_ROUNDS = 120_000
AVATARS = ("blue", "red", "yellow", "green", "purple", "kids")

app = FastAPI(title="Netflix API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)


@app.exception_handler(RequestValidationError)
async def _validation_handler(_req: Request, exc: RequestValidationError):
    errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errs})


# ---------------------------------------------------------------- database
@contextmanager
def db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wait_for_db(timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with db() as c:
                c.execute("SELECT 1 FROM titles LIMIT 1")
            return
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(1.5)


# ---------------------------------------------------------------- auth utils
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        PBKDF2_ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def make_token(user: dict) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user["id"]), "email": user["email"], "name": user["name"],
                       "iat": now, "exp": now + JWT_TTL, "jti": secrets.token_hex(8)},
                      JWT_SECRET, algorithm="HS256")


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        uid = int(claims["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    with db() as c:
        row = c.execute("SELECT id, email, name FROM users WHERE id=%s", (uid,)).fetchone()
    if not row:
        raise HTTPException(401, "User no longer exists")
    return row


def current_profile(user: dict = Depends(current_user),
                    x_profile_id: Optional[str] = Header(default=None)) -> dict:
    with db() as c:
        if x_profile_id:
            try:
                pid = int(x_profile_id)
            except ValueError:
                raise HTTPException(400, "X-Profile-Id must be an integer")
            row = c.execute("SELECT * FROM profiles WHERE id=%s AND user_id=%s",
                            (pid, user["id"])).fetchone()
            if not row:
                raise HTTPException(403, "Profile does not belong to this account")
            return row
        row = c.execute("SELECT * FROM profiles WHERE user_id=%s ORDER BY id LIMIT 1",
                        (user["id"],)).fetchone()
        if not row:
            row = c.execute(
                "INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s,%s,'blue',FALSE)"
                " RETURNING *", (user["id"], user["name"] or "Me")).fetchone()
        return row


# ---------------------------------------------------------------- serializers
TITLE_COLS = ("t.id, t.name, t.kind, t.year, t.genre, t.maturity_rating, t.rating, t.synopsis, "
              "t.poster, t.backdrop, t.video_url, t.duration, t.top10_rank, t.language")


def title_out(r: dict) -> dict:
    d = dict(r)
    if d.get("rating") is not None:
        d["rating"] = float(d["rating"])
    return d


def kids_clause(profile: dict, alias: str = "t") -> str:
    """Kids profiles only see family / animation titles."""
    if not profile.get("is_kids"):
        return ""
    return (f" AND EXISTS (SELECT 1 FROM title_genres kg JOIN genres g2 ON g2.id=kg.genre_id "
            f"WHERE kg.title_id={alias}.id AND g2.name IN ('Family','Animation','Kids'))")


def attach_genres(c, rows: list) -> list:
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    gm: dict = {}
    for g in c.execute(
            "SELECT tg.title_id, g.id, g.name FROM title_genres tg JOIN genres g ON g.id=tg.genre_id"
            " WHERE tg.title_id = ANY(%s) ORDER BY tg.id", (ids,)).fetchall():
        gm.setdefault(g["title_id"], []).append({"id": g["id"], "name": g["name"]})
    sm = {s["title_id"]: s for s in c.execute(
        "SELECT title_id, COUNT(DISTINCT season) AS seasons, COUNT(*) AS episodes FROM episodes"
        " WHERE title_id = ANY(%s) GROUP BY title_id", (ids,)).fetchall()}
    out = []
    for r in rows:
        d = title_out(r)
        d["genres"] = gm.get(r["id"], [])
        s = sm.get(r["id"])
        d["seasons"] = int(s["seasons"]) if s else 0
        d["episode_count"] = int(s["episodes"]) if s else 0
        out.append(d)
    return out


def attach_profile_state(c, profile: dict, rows: list) -> list:
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    in_list = {r["title_id"] for r in c.execute(
        "SELECT title_id FROM my_list WHERE profile_id=%s AND title_id = ANY(%s)",
        (profile["id"], ids)).fetchall()}
    rates = {r["title_id"]: r["value"] for r in c.execute(
        "SELECT title_id, value FROM ratings WHERE profile_id=%s AND title_id = ANY(%s)",
        (profile["id"], ids)).fetchall()}
    for r in rows:
        r["in_my_list"] = r["id"] in in_list
        r["my_rating"] = rates.get(r["id"])
    return rows


def full_titles(c, profile: dict, rows: list) -> list:
    return attach_profile_state(c, profile, attach_genres(c, rows))


# ---------------------------------------------------------------- schemas
class RegisterIn(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str
    name: Optional[str] = None


class LoginIn(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str


class ProfileIn(BaseModel):
    name: str
    avatar: Optional[str] = None
    is_kids: Optional[bool] = False


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    is_kids: Optional[bool] = None


class MyListIn(BaseModel):
    title_id: int


class RatingIn(BaseModel):
    value: Any


class ProgressIn(BaseModel):
    title_id: int
    progress_seconds: float
    episode_id: Optional[int] = None


# ---------------------------------------------------------------- public
@app.get("/")
def root():
    return {"service": "netflix-api", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def _norm_email(body) -> str:
    raw = (body.email or body.username or "").strip().lower()
    if not raw:
        raise HTTPException(422, "email is required")
    if "@" not in raw:
        raw = raw + "@users.local"
    return raw


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn):
    email = _norm_email(body)
    if len(body.password or "") < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    name = (body.name or email.split("@")[0]).strip()[:60] or "Me"
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists")
        user = c.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (%s,%s,%s)"
            " RETURNING id, email, name", (email, hash_password(body.password), name)).fetchone()
        c.execute("INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s,%s,'blue',FALSE)",
                  (user["id"], name[:30]))
        c.execute("INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s,'Kids','kids',TRUE)",
                  (user["id"],))
    return {"access_token": make_token(user), "token_type": "bearer", "user": user}


@app.post("/auth/login")
def login(body: LoginIn):
    email = _norm_email(body)
    with db() as c:
        user = c.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    pub = {"id": user["id"], "email": user["email"], "name": user["name"]}
    return {"access_token": make_token(pub), "token_type": "bearer", "user": pub}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"item": user}


# ---------------------------------------------------------------- profiles
def _profile_out(p: dict) -> dict:
    return {"id": p["id"], "user_id": p["user_id"], "name": p["name"],
            "avatar": p["avatar"], "is_kids": bool(p["is_kids"])}


@app.get("/api/profiles")
def list_profiles(user: dict = Depends(current_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM profiles WHERE user_id=%s ORDER BY id",
                         (user["id"],)).fetchall()
    return {"items": [_profile_out(p) for p in rows], "total": len(rows)}


@app.post("/api/profiles", status_code=201)
def create_profile(body: ProfileIn, user: dict = Depends(current_user)):
    name = (body.name or "").strip()[:30]
    if not name:
        raise HTTPException(422, "Profile name is required")
    avatar = body.avatar if body.avatar in AVATARS else ("kids" if body.is_kids else "blue")
    with db() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM profiles WHERE user_id=%s",
                      (user["id"],)).fetchone()["n"]
        if n >= 5:
            raise HTTPException(409, "An account can have at most 5 profiles")
        p = c.execute("INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s,%s,%s,%s)"
                      " RETURNING *", (user["id"], name, avatar, bool(body.is_kids))).fetchone()
    return {"item": _profile_out(p)}


def _own_profile(c, pid: int, user: dict) -> dict:
    p = c.execute("SELECT * FROM profiles WHERE id=%s AND user_id=%s", (pid, user["id"])).fetchone()
    if not p:
        raise HTTPException(404, "Profile not found")
    return p


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int, user: dict = Depends(current_user)):
    with db() as c:
        return {"item": _profile_out(_own_profile(c, profile_id, user))}


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdate, user: dict = Depends(current_user)):
    with db() as c:
        p = _own_profile(c, profile_id, user)
        name = (body.name.strip()[:30] if body.name is not None else p["name"]) or p["name"]
        avatar = body.avatar if body.avatar in AVATARS else p["avatar"]
        kids = p["is_kids"] if body.is_kids is None else bool(body.is_kids)
        p = c.execute("UPDATE profiles SET name=%s, avatar=%s, is_kids=%s WHERE id=%s RETURNING *",
                      (name, avatar, kids, profile_id)).fetchone()
    return {"item": _profile_out(p)}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(current_user)):
    with db() as c:
        p = _own_profile(c, profile_id, user)
        n = c.execute("SELECT COUNT(*) AS n FROM profiles WHERE user_id=%s",
                      (user["id"],)).fetchone()["n"]
        if n <= 1:
            raise HTTPException(409, "An account needs at least one profile")
        c.execute("DELETE FROM profiles WHERE id=%s", (profile_id,))
    return {"item": _profile_out(p)}


# ---------------------------------------------------------------- titles
SORTS = {"popular": "t.id", "rating": "t.rating DESC NULLS LAST, t.id",
         "new": "t.year DESC, t.id", "name": "t.name", "az": "t.name", "za": "t.name DESC"}


@app.get("/api/titles")
def list_titles(kind: Optional[str] = None, genre_id: Optional[int] = None,
                language: Optional[str] = None, year: Optional[str] = None,
                sort: str = "popular", limit: int = Query(100, ge=1, le=200),
                offset: int = Query(0, ge=0), profile: dict = Depends(current_profile)):
    where, args = ["1=1"], []
    if kind:
        k = {"show": "series", "shows": "series", "tv": "series", "movies": "movie"}.get(kind, kind)
        where.append("t.kind=%s"); args.append(k)
    if genre_id:
        where.append("EXISTS (SELECT 1 FROM title_genres x WHERE x.title_id=t.id AND x.genre_id=%s)")
        args.append(genre_id)
    if language:
        where.append("t.language=%s"); args.append(language)
    if year:
        where.append("t.year=%s"); args.append(year)
    clause = " AND ".join(where) + kids_clause(profile)
    order = SORTS.get(sort, "t.id")
    with db() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM titles t WHERE {clause}", args).fetchone()["n"]
        rows = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE {clause} ORDER BY {order}"
                         f" LIMIT %s OFFSET %s", args + [limit, offset]).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/titles/trending")
def trending(kind: Optional[str] = None, limit: int = Query(20, ge=1, le=100),
             profile: dict = Depends(current_profile)):
    # Dataset order is TMDB's weekly-trending order; interleave movies and series.
    where, args = "t.trending_rank IS NOT NULL", []
    if kind:
        where += " AND t.kind=%s"; args.append("series" if kind in ("tv", "show", "shows") else kind)
    with db() as c:
        rows = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE {where}{kids_clause(profile)}"
                         f" ORDER BY t.trending_rank LIMIT %s", args + [limit]).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": len(items)}


@app.get("/api/titles/top10")
def top10(kind: Optional[str] = None, profile: dict = Depends(current_profile)):
    where, args = "t.top10_rank IS NOT NULL", []
    if kind:
        where += " AND t.kind=%s"; args.append("series" if kind in ("tv", "show", "shows") else kind)
    with db() as c:
        rows = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE {where}{kids_clause(profile)}"
                         f" ORDER BY t.top10_rank, t.kind", args).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": len(items)}


def _get_title(c, title_id: int, profile: dict) -> dict:
    row = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE t.id=%s{kids_clause(profile)}",
                    (title_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Title not found")
    return row


@app.get("/api/titles/{title_id}")
def get_title(title_id: int, profile: dict = Depends(current_profile)):
    with db() as c:
        item = full_titles(c, profile, [_get_title(c, title_id, profile)])[0]
        cw = c.execute("SELECT progress_seconds, episode_id FROM continue_watching"
                       " WHERE profile_id=%s AND title_id=%s", (profile["id"], title_id)).fetchone()
        item["progress_seconds"] = float(cw["progress_seconds"]) if cw else None
        item["resume_episode_id"] = cw["episode_id"] if cw else None
    return {"item": item}


@app.get("/api/titles/{title_id}/episodes")
def episodes(title_id: int, season: Optional[int] = None, profile: dict = Depends(current_profile)):
    with db() as c:
        _get_title(c, title_id, profile)
        q, args = "SELECT * FROM episodes WHERE title_id=%s", [title_id]
        if season:
            q += " AND season=%s"; args.append(season)
        rows = c.execute(q + " ORDER BY season, number", args).fetchall()
    return {"items": rows, "total": len(rows),
            "seasons": sorted({r["season"] for r in rows})}


RATING_ALIASES = {"down": -1, "thumbs_down": -1, "dislike": -1, "-1": -1,
                  "up": 1, "thumbs_up": 1, "like": 1, "1": 1,
                  "love": 2, "two_thumbs": 2, "2": 2, "none": 0, "clear": 0, "0": 0}


@app.post("/api/titles/{title_id}/rating")
def rate(title_id: int, body: RatingIn, profile: dict = Depends(current_profile)):
    value = RATING_ALIASES.get(str(body.value).strip().lower())
    if value is None:
        raise HTTPException(422, "value must be one of -1 (down), 1 (up), 2 (love) or 0 (clear)")
    with db() as c:
        _get_title(c, title_id, profile)
        if value == 0:
            c.execute("DELETE FROM ratings WHERE profile_id=%s AND title_id=%s",
                      (profile["id"], title_id))
            return {"item": {"id": None, "profile_id": profile["id"], "title_id": title_id,
                             "value": None}}
        row = c.execute(
            "INSERT INTO ratings (profile_id, title_id, value) VALUES (%s,%s,%s)"
            " ON CONFLICT (profile_id, title_id) DO UPDATE SET value=EXCLUDED.value RETURNING *",
            (profile["id"], title_id, value)).fetchone()
    return {"item": row}


@app.get("/api/ratings")
def my_ratings(profile: dict = Depends(current_profile)):
    with db() as c:
        rows = c.execute("SELECT * FROM ratings WHERE profile_id=%s ORDER BY id DESC",
                         (profile["id"],)).fetchall()
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------- genres
@app.get("/api/genres")
def list_genres(kind: Optional[str] = None, profile: dict = Depends(current_profile)):
    args: list = []
    kw = ""
    if kind:
        kw = " AND t.kind=%s"; args.append("series" if kind in ("tv", "show", "shows") else kind)
    with db() as c:
        rows = c.execute(
            "SELECT g.id, g.name, COUNT(t.id) AS title_count FROM genres g"
            " JOIN title_genres tg ON tg.genre_id=g.id JOIN titles t ON t.id=tg.title_id"
            f" WHERE 1=1{kw}{kids_clause(profile)} GROUP BY g.id, g.name ORDER BY g.name",
            args).fetchall()
    return {"items": rows, "total": len(rows)}


@app.get("/api/genres/{genre_id}")
def get_genre(genre_id: int, user: dict = Depends(current_user)):
    with db() as c:
        g = c.execute("SELECT id, name FROM genres WHERE id=%s", (genre_id,)).fetchone()
    if not g:
        raise HTTPException(404, "Genre not found")
    return {"item": g}


@app.get("/api/genres/{genre_id}/titles")
def genre_titles(genre_id: int, kind: Optional[str] = None,
                 profile: dict = Depends(current_profile)):
    with db() as c:
        g = c.execute("SELECT id, name FROM genres WHERE id=%s", (genre_id,)).fetchone()
        if not g:
            raise HTTPException(404, "Genre not found")
        args: list = [genre_id]
        kw = ""
        if kind:
            kw = " AND t.kind=%s"; args.append("series" if kind in ("tv", "show", "shows") else kind)
        rows = c.execute(
            f"SELECT {TITLE_COLS} FROM titles t JOIN title_genres tg ON tg.title_id=t.id"
            f" WHERE tg.genre_id=%s{kw}{kids_clause(profile)} ORDER BY t.id", args).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": len(items), "genre": g}


# ---------------------------------------------------------------- search
@app.get("/api/search")
def search(q: str = "", limit: int = Query(60, ge=1, le=200),
           profile: dict = Depends(current_profile)):
    q = q.strip()
    if not q:
        return {"items": [], "total": 0, "query": q}
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db() as c:
        rows = c.execute(
            f"SELECT {TITLE_COLS} FROM titles t WHERE (t.name ILIKE %s OR t.synopsis ILIKE %s OR"
            " EXISTS (SELECT 1 FROM title_genres sg JOIN genres g ON g.id=sg.genre_id"
            f" WHERE sg.title_id=t.id AND g.name ILIKE %s)){kids_clause(profile)}"
            " ORDER BY (t.name ILIKE %s) DESC, t.id LIMIT %s",
            (like, like, like, like, limit)).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": len(items), "query": q}


# ---------------------------------------------------------------- my list
@app.get("/api/my-list")
def get_my_list(profile: dict = Depends(current_profile)):
    with db() as c:
        rows = c.execute(
            f"SELECT {TITLE_COLS}, m.id AS list_id FROM my_list m JOIN titles t ON t.id=m.title_id"
            " WHERE m.profile_id=%s ORDER BY m.created_at DESC, m.id DESC", (profile["id"],)).fetchall()
        items = full_titles(c, profile, rows)
    return {"items": items, "total": len(items), "profile_id": profile["id"]}


@app.post("/api/my-list", status_code=201)
def add_my_list(body: MyListIn, profile: dict = Depends(current_profile)):
    with db() as c:
        t = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE t.id=%s{kids_clause(profile)}",
                      (body.title_id,)).fetchone()
        if not t:
            raise HTTPException(404, "referenced title does not exist")
        row = c.execute(
            "INSERT INTO my_list (profile_id, title_id) VALUES (%s,%s)"
            " ON CONFLICT (profile_id, title_id) DO UPDATE SET title_id=EXCLUDED.title_id"
            " RETURNING id", (profile["id"], body.title_id)).fetchone()
        item = title_out(t)
        item.update({"list_id": row["id"], "title_id": t["id"], "profile_id": profile["id"],
                     "in_my_list": True})
    # `id` is the title id: My List rows are keyed by title for the profile.
    return {"item": item}


@app.put("/api/my-list/{title_id}")
def bump_my_list(title_id: int, profile: dict = Depends(current_profile)):
    """Move a title that is already in this profile's list to the front."""
    with db() as c:
        row = c.execute("UPDATE my_list SET created_at=clock_timestamp() WHERE profile_id=%s AND title_id=%s"
                        " RETURNING id", (profile["id"], title_id)).fetchone()
        if not row:
            raise HTTPException(404, "Title is not in My List")
        t = c.execute(f"SELECT {TITLE_COLS} FROM titles t WHERE t.id=%s", (title_id,)).fetchone()
    item = title_out(t)
    item.update({"list_id": row["id"], "title_id": title_id, "profile_id": profile["id"], "in_my_list": True})
    return {"item": item}


@app.delete("/api/my-list/{title_id}")
def remove_my_list(title_id: int, profile: dict = Depends(current_profile)):
    with db() as c:
        row = c.execute("DELETE FROM my_list WHERE profile_id=%s AND title_id=%s RETURNING id",
                        (profile["id"], title_id)).fetchone()
    if not row:
        raise HTTPException(404, "Title is not in My List")
    return {"item": {"id": title_id, "title_id": title_id, "list_id": row["id"],
                     "profile_id": profile["id"], "in_my_list": False}}


# ---------------------------------------------------------------- continue watching
@app.get("/api/continue-watching")
def continue_watching(profile: dict = Depends(current_profile)):
    with db() as c:
        rows = c.execute(
            f"SELECT {TITLE_COLS}, cw.progress_seconds, cw.episode_id, cw.id AS cw_id,"
            " e.season AS ep_season, e.number AS ep_number, e.name AS ep_name"
            " FROM continue_watching cw JOIN titles t ON t.id=cw.title_id"
            " LEFT JOIN episodes e ON e.id=cw.episode_id"
            f" WHERE cw.profile_id=%s{kids_clause(profile)} ORDER BY cw.updated_at DESC",
            (profile["id"],)).fetchall()
        items = full_titles(c, profile, rows)
        for i in items:
            i["progress_seconds"] = float(i["progress_seconds"] or 0)
    return {"items": items, "total": len(items)}


@app.post("/api/continue-watching")
def save_progress(body: ProgressIn, profile: dict = Depends(current_profile)):
    with db() as c:
        _get_title(c, body.title_id, profile)
        if body.episode_id is not None and not c.execute(
                "SELECT 1 FROM episodes WHERE id=%s AND title_id=%s",
                (body.episode_id, body.title_id)).fetchone():
            raise HTTPException(404, "referenced episode does not exist")
        row = c.execute(
            "INSERT INTO continue_watching (profile_id, title_id, progress_seconds, episode_id)"
            " VALUES (%s,%s,%s,%s) ON CONFLICT (profile_id, title_id) DO UPDATE SET"
            " progress_seconds=EXCLUDED.progress_seconds, episode_id=EXCLUDED.episode_id,"
            " updated_at=NOW() RETURNING *",
            (profile["id"], body.title_id, max(0.0, body.progress_seconds), body.episode_id)).fetchone()
    row["progress_seconds"] = float(row["progress_seconds"])
    return {"item": row}


@app.delete("/api/continue-watching/{title_id}")
def remove_progress(title_id: int, profile: dict = Depends(current_profile)):
    with db() as c:
        row = c.execute("DELETE FROM continue_watching WHERE profile_id=%s AND title_id=%s"
                        " RETURNING id", (profile["id"], title_id)).fetchone()
    if not row:
        raise HTTPException(404, "Title is not in Continue Watching")
    return {"item": {"id": title_id, "title_id": title_id}}


# ---------------------------------------------------------------- languages
@app.get("/api/languages")
def languages(profile: dict = Depends(current_profile)):
    with db() as c:
        rows = c.execute(f"SELECT t.language AS code, COUNT(*) AS title_count FROM titles t"
                         f" WHERE 1=1{kids_clause(profile)} GROUP BY t.language ORDER BY t.language"
                         ).fetchall()
    return {"items": rows, "total": len(rows)}


if __name__ == "__main__":
    wait_for_db()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                loop="asyncio", http="h11")
