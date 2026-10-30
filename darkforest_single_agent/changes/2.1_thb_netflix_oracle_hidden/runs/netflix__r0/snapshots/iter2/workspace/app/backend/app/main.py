"""Netflix clone API (FastAPI + PostgreSQL)."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import jwt
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://netflix:netflix@localhost:5432/netflix")
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
JWT_TTL = int(os.environ.get("JWT_TTL_SECONDS", str(7 * 24 * 3600)))
KIDS_GENRES = ("Family", "Animation")
RATING_WORDS = {"down": -1, "thumbs_down": -1, "dislike": -1, "up": 1, "thumbs_up": 1, "like": 1, "love": 2, "two_thumbs": 2}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

pool: Optional[ConnectionPool] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global pool
    # Database may still be starting up inside docker compose.
    for _ in range(90):
        try:
            psycopg.connect(DATABASE_URL, connect_timeout=3).close()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
    yield
    pool.close()


app = FastAPI(title="Netflix Clone API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_handler(_req: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request", "errors": jsonable_errors(exc)})


def jsonable_errors(exc: RequestValidationError):
    return [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]


# ---------------------------------------------------------------- db helpers
def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Any = None) -> Optional[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


# ---------------------------------------------------------------- security
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:  # noqa: BLE001
        return False


def make_token(user: dict) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user["id"]), "email": user["email"], "iat": now, "exp": now + JWT_TTL}, JWT_SECRET, algorithm="HS256")


def unauthorized(msg: str = "Not authenticated"):
    return HTTPException(status_code=401, detail=msg, headers={"WWW-Authenticate": "Bearer"})


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise unauthorized("Invalid or expired token")
    user = fetch_one("SELECT id, email, name FROM users WHERE id = %s", (int(payload.get("sub", 0)),))
    if not user:
        raise unauthorized("User no longer exists")
    return user


def current_profile(
    user: dict = Depends(current_user),
    x_profile_id: Optional[str] = Header(None),
    profile_id: Optional[str] = Query(None),
) -> dict:
    """Resolve the active profile (X-Profile-Id header or ?profile_id=); defaults to the user's first profile."""
    pid = x_profile_id or profile_id
    if pid:
        try:
            pid_int = int(pid)
        except ValueError:
            raise HTTPException(400, "Invalid profile id")
        prof = fetch_one("SELECT * FROM profiles WHERE id = %s AND user_id = %s", (pid_int, user["id"]))
        if not prof:
            raise HTTPException(403, "Profile does not belong to this account")
        return prof
    prof = fetch_one("SELECT * FROM profiles WHERE user_id = %s ORDER BY id LIMIT 1", (user["id"],))
    if not prof:
        prof = fetch_one(
            "INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, %s, 'blue', FALSE) RETURNING *",
            (user["id"], user["name"] or user["email"].split("@")[0]),
        )
    return prof


async def read_body(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    try:
        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            return dict(await request.form())
        raw = await request.body()
        if not raw:
            return {}
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, "Request body must be a JSON object")
        return data
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Malformed request body")


# ---------------------------------------------------------------- serializers
TITLE_COLS = "t.id, t.name, t.kind, t.year, t.genre, t.maturity_rating, t.rating, t.synopsis, t.poster, t.backdrop, t.video_url, t.duration, t.top10_rank, t.language"
GENRES_AGG = "(SELECT COALESCE(array_agg(g.name ORDER BY g.name), '{}') FROM title_genres tg JOIN genres g ON g.id = tg.genre_id WHERE tg.title_id = t.id) AS genres"
SEASONS_AGG = "(SELECT COUNT(DISTINCT e.season) FROM episodes e WHERE e.title_id = t.id) AS seasons, (SELECT COUNT(*) FROM episodes e WHERE e.title_id = t.id) AS episode_count"


def title_select(profile: Optional[dict]) -> tuple[str, list]:
    params: list = []
    extra = ""
    if profile:
        extra = (", EXISTS(SELECT 1 FROM my_list m WHERE m.title_id = t.id AND m.profile_id = %s) AS in_my_list"
                 ", (SELECT r.value FROM ratings r WHERE r.title_id = t.id AND r.profile_id = %s) AS my_rating")
        params = [profile["id"], profile["id"]]
    return f"SELECT {TITLE_COLS}, {GENRES_AGG}, {SEASONS_AGG}{extra} FROM titles t", params


def norm_title(row: dict) -> dict:
    row = dict(row)
    if row.get("rating") is not None:
        row["rating"] = float(row["rating"])
    row["genres"] = list(row.get("genres") or [])
    row.setdefault("in_my_list", False)
    row.setdefault("my_rating", None)
    return row


def kids_clause(profile: Optional[dict]) -> str:
    if profile and profile.get("is_kids"):
        names = ", ".join(f"'{g}'" for g in KIDS_GENRES)
        return f" t.id IN (SELECT tg.title_id FROM title_genres tg JOIN genres g ON g.id = tg.genre_id WHERE g.name IN ({names})) "
    return ""


def query_titles(profile, where: list[str], params: list, order: str = "t.id", limit: Optional[int] = None, offset: int = 0):
    base, p = title_select(profile)
    conds = list(where)
    kc = kids_clause(profile)
    if kc:
        conds.append(kc)
    sql = base + (" WHERE " + " AND ".join(conds) if conds else "") + f" ORDER BY {order}"
    allp = p + params
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        allp += [limit, offset]
    return [norm_title(r) for r in fetch_all(sql, allp)]


def get_title_or_404(title_id: int, profile=None) -> dict:
    rows = query_titles(profile, ["t.id = %s"], [title_id])
    if not rows:
        # kids filter may hide it; distinguish missing from restricted
        raise HTTPException(404, "Title not found")
    return rows[0]


def items(rows: list) -> dict:
    """List responses use the {items, total} envelope."""
    return {"items": rows, "total": len(rows)}


def profile_out(p: dict) -> dict:
    return {"id": p["id"], "user_id": p["user_id"], "name": p["name"], "avatar": p["avatar"], "is_kids": p["is_kids"]}


# ---------------------------------------------------------------- health / auth
@app.get("/health")
def health():
    try:
        fetch_one("SELECT 1 AS ok")
        return {"status": "ok", "database": "ok"}
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})


@app.post("/auth/register", status_code=201)
async def register(request: Request):
    body = await read_body(request)
    email = str(body.get("email") or body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    name = str(body.get("name") or body.get("full_name") or "").strip() or email.split("@")[0]
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "A valid email is required")
    if len(password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    if len(name) > 120:
        raise HTTPException(422, "Name is too long")
    if fetch_one("SELECT id FROM users WHERE email = %s", (email,)):
        raise HTTPException(409, "An account with this email already exists")
    with pool.connection() as conn:
        user = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id, email, name",
            (email, hash_password(password), name),
        ).fetchone()
        conn.execute("INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, %s, 'blue', FALSE)", (user["id"], name[:60]))
        conn.execute("INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, 'Kids', 'kids', TRUE)", (user["id"],))
    return {"access_token": make_token(user), "token_type": "bearer", "user": user}


@app.post("/auth/login")
async def login(request: Request):
    body = await read_body(request)
    email = str(body.get("email") or body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    if not email or not password:
        raise HTTPException(422, "Email and password are required")
    row = fetch_one("SELECT id, email, name, password_hash FROM users WHERE email = %s", (email,))
    if not row or not verify_password(password, row["password_hash"]):
        raise unauthorized("Incorrect email or password")
    user = {"id": row["id"], "email": row["email"], "name": row["name"]}
    return {"access_token": make_token(user), "token_type": "bearer", "user": user}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    profiles = fetch_all("SELECT * FROM profiles WHERE user_id = %s ORDER BY id", (user["id"],))
    return {**user, "profiles": [profile_out(p) for p in profiles]}


# ---------------------------------------------------------------- profiles
AVATARS = ("blue", "red", "yellow", "green", "purple", "kids")


@app.get("/api/profiles")
def list_profiles(user: dict = Depends(current_user)):
    return items([profile_out(p) for p in fetch_all("SELECT * FROM profiles WHERE user_id = %s ORDER BY id", (user["id"],))])


def validate_profile_fields(body: dict, partial: bool = False) -> dict:
    out: dict = {}
    if "name" in body or not partial:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 60:
            raise HTTPException(422, "Profile name is required (max 60 characters)")
        out["name"] = name
    if "avatar" in body and body["avatar"] is not None:
        avatar = str(body["avatar"]).strip()
        if len(avatar) > 255:
            raise HTTPException(422, "Avatar must be at most 255 characters")
        # Built-in avatars are colour keys; any other value (e.g. an image URL) is stored as given.
        out["avatar"] = avatar or "blue"
    if "is_kids" in body:
        v = body["is_kids"]
        out["is_kids"] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
    return out


@app.post("/api/profiles", status_code=201)
async def create_profile(request: Request, user: dict = Depends(current_user)):
    fields = validate_profile_fields(await read_body(request))
    count = fetch_one("SELECT COUNT(*) AS c FROM profiles WHERE user_id = %s", (user["id"],))["c"]
    if count >= 5:
        raise HTTPException(409, "An account can have at most 5 profiles")
    is_kids = fields.get("is_kids", False)
    avatar = fields.get("avatar") or ("kids" if is_kids else AVATARS[count % 5])
    prof = fetch_one(
        "INSERT INTO profiles (user_id, name, avatar, is_kids) VALUES (%s, %s, %s, %s) RETURNING *",
        (user["id"], fields["name"], avatar, is_kids),
    )
    return profile_out(prof)


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int, user: dict = Depends(current_user)):
    prof = fetch_one("SELECT * FROM profiles WHERE id = %s AND user_id = %s", (profile_id, user["id"]))
    if not prof:
        raise HTTPException(404, "Profile not found")
    return profile_out(prof)


@app.patch("/api/profiles/{profile_id}")
@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: int, request: Request, user: dict = Depends(current_user)):
    prof = fetch_one("SELECT * FROM profiles WHERE id = %s AND user_id = %s", (profile_id, user["id"]))
    if not prof:
        raise HTTPException(404, "Profile not found")
    fields = validate_profile_fields(await read_body(request), partial=True)
    if fields:
        sets = ", ".join(f"{k} = %s" for k in fields)
        prof = fetch_one(f"UPDATE profiles SET {sets} WHERE id = %s RETURNING *", (*fields.values(), profile_id))
    return profile_out(prof)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(current_user)):
    prof = fetch_one("SELECT * FROM profiles WHERE id = %s AND user_id = %s", (profile_id, user["id"]))
    if not prof:
        raise HTTPException(404, "Profile not found")
    count = fetch_one("SELECT COUNT(*) AS c FROM profiles WHERE user_id = %s", (user["id"],))["c"]
    if count <= 1:
        raise HTTPException(409, "An account needs at least one profile")
    fetch_one("DELETE FROM profiles WHERE id = %s RETURNING id", (profile_id,))
    return {"deleted": True, "id": profile_id}


# ---------------------------------------------------------------- titles
SORTS = {
    "popular": "t.rating DESC NULLS LAST, t.id",
    "rating": "t.rating DESC NULLS LAST, t.id",
    "new": "t.year DESC NULLS LAST, t.rating DESC NULLS LAST, t.id",
    "year": "t.year DESC NULLS LAST, t.id",
    "name": "t.name, t.id",
    "id": "t.id",
}


def kind_filter(kind: Optional[str], where: list, params: list):
    if kind:
        k = kind.lower()
        k = {"tv": "series", "show": "series", "shows": "series", "movies": "movie"}.get(k, k)
        if k not in ("movie", "series"):
            raise HTTPException(422, "kind must be 'movie' or 'series'")
        where.append("t.kind = %s")
        params.append(k)


@app.get("/api/titles")
def list_titles(
    kind: Optional[str] = None,
    genre: Optional[str] = None,
    language: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "id",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    profile: dict = Depends(current_profile),
):
    where: list = []
    params: list = []
    kind_filter(kind, where, params)
    if genre:
        if genre.isdigit():
            where.append("t.id IN (SELECT title_id FROM title_genres WHERE genre_id = %s)")
            params.append(int(genre))
        else:
            where.append("t.id IN (SELECT tg.title_id FROM title_genres tg JOIN genres g ON g.id = tg.genre_id WHERE lower(g.name) = lower(%s))")
            params.append(genre)
    if language:
        where.append("t.language = %s")
        params.append(language)
    if q:
        where.append("t.name ILIKE %s")
        params.append(f"%{q}%")
    return items(query_titles(profile, where, params, SORTS.get(sort, "t.id"), limit, offset))


@app.get("/api/titles/trending")
def trending(kind: Optional[str] = None, limit: int = Query(20, ge=1, le=100), profile: dict = Depends(current_profile)):
    where: list = ["t.backdrop IS NOT NULL", "t.year >= 2022"]
    params: list = []
    kind_filter(kind, where, params)
    return items(query_titles(profile, where, params, "t.year DESC, t.rating DESC NULLS LAST, t.id", limit))


@app.get("/api/titles/top10")
def top10(kind: Optional[str] = None, profile: dict = Depends(current_profile)):
    where: list = ["t.top10_rank IS NOT NULL"]
    params: list = []
    kind_filter(kind, where, params)
    return items(query_titles(profile, where, params, "t.top10_rank, t.kind DESC, t.id", 20 if not kind else 10))


@app.get("/api/titles/{title_id}")
def get_title(title_id: int, profile: dict = Depends(current_profile)):
    title = get_title_or_404(title_id, profile)
    progress = fetch_one(
        "SELECT progress_seconds, episode_id FROM continue_watching WHERE profile_id = %s AND title_id = %s",
        (profile["id"], title_id),
    )
    title["progress_seconds"] = progress["progress_seconds"] if progress else 0
    title["resume_episode_id"] = progress["episode_id"] if progress else None
    return title


@app.get("/api/titles/{title_id}/episodes")
def get_episodes(title_id: int, season: Optional[int] = None, profile: dict = Depends(current_profile)):
    get_title_or_404(title_id, profile)
    sql = "SELECT id, title_id, season, number, name, synopsis, duration, thumbnail FROM episodes WHERE title_id = %s"
    params: list = [title_id]
    if season is not None:
        sql += " AND season = %s"
        params.append(season)
    return items(fetch_all(sql + " ORDER BY season, number", params))


def parse_rating(v) -> int:
    """-1 = thumbs down, 1 = thumbs up, 2 = love (larger scores up to 10 are kept as-is), 0 = clear."""
    if v is None:
        raise HTTPException(422, "value is required")
    if isinstance(v, str):
        s = v.strip().lower()
        if s in RATING_WORDS:
            return RATING_WORDS[s]
        if s in ("0", "none", "clear", ""):
            return 0
        try:
            v = float(s)
        except ValueError:
            raise HTTPException(422, "value must be -1 (thumbs down), 1 (thumbs up), 2 (love) or 0 (clear)")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not -1 <= int(v) <= 10:
        raise HTTPException(422, "value must be -1 (thumbs down), 1 (thumbs up), 2 (love) or 0 (clear)")
    return int(v)


def body_profile(user_profile: dict, body: dict) -> dict:
    """Allow an explicit profile_id in the JSON body (must belong to the same account)."""
    pid = body.get("profile_id")
    if pid is None or str(pid) == str(user_profile["id"]):
        return user_profile
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise HTTPException(422, "profile_id must be an integer")
    if pid <= 0:  # placeholder id: use the active profile
        return user_profile
    prof = fetch_one("SELECT * FROM profiles WHERE id = %s AND user_id = %s", (pid, user_profile["user_id"]))
    if not prof:
        raise HTTPException(403, "Profile does not belong to this account")
    return prof


@app.post("/api/titles/{title_id}/rating")
async def rate_title(title_id: int, request: Request, profile: dict = Depends(current_profile)):
    body = await read_body(request)
    profile = body_profile(profile, body)
    value = parse_rating(body.get("value", body.get("rating", body.get("score"))))
    get_title_or_404(title_id, profile)
    if value == 0:
        fetch_one("DELETE FROM ratings WHERE profile_id = %s AND title_id = %s RETURNING id", (profile["id"], title_id))
        return {"id": None, "profile_id": profile["id"], "title_id": title_id, "value": None}
    row = fetch_one(
        """INSERT INTO ratings (profile_id, title_id, value) VALUES (%s, %s, %s)
           ON CONFLICT (profile_id, title_id) DO UPDATE SET value = EXCLUDED.value, created_at = now()
           RETURNING id, profile_id, title_id, value""",
        (profile["id"], title_id, value),
    )
    return row


@app.get("/api/ratings")
def list_ratings(profile: dict = Depends(current_profile)):
    return items(fetch_all("SELECT id, profile_id, title_id, value FROM ratings WHERE profile_id = %s ORDER BY created_at DESC", (profile["id"],)))


# ---------------------------------------------------------------- genres / search
@app.get("/api/genres")
def list_genres(kind: Optional[str] = None, profile: dict = Depends(current_profile)):
    where = ["1=1"]
    params: list = []
    kind_filter(kind, where, params)
    kc = kids_clause(profile)
    if kc:
        where.append(kc)
    return items(fetch_all(
        f"""SELECT g.id, g.name, COUNT(t.id) AS title_count
            FROM genres g JOIN title_genres tg ON tg.genre_id = g.id JOIN titles t ON t.id = tg.title_id
            WHERE {' AND '.join(where)} GROUP BY g.id, g.name ORDER BY g.name""",
        params,
    ))


@app.get("/api/genres/{genre_id}")
def get_genre(genre_id: int, user: dict = Depends(current_user)):
    g = fetch_one("SELECT id, name FROM genres WHERE id = %s", (genre_id,))
    if not g:
        raise HTTPException(404, "Genre not found")
    return g


@app.get("/api/genres/{genre_id}/titles")
def genre_titles(genre_id: int, kind: Optional[str] = None, profile: dict = Depends(current_profile)):
    if not fetch_one("SELECT id FROM genres WHERE id = %s", (genre_id,)):
        raise HTTPException(404, "Genre not found")
    where = ["t.id IN (SELECT title_id FROM title_genres WHERE genre_id = %s)"]
    params: list = [genre_id]
    kind_filter(kind, where, params)
    return items(query_titles(profile, where, params, "t.rating DESC NULLS LAST, t.id"))


@app.get("/api/search")
def search(q: str = "", query: Optional[str] = None, profile: dict = Depends(current_profile)):
    term = (query if query is not None else q).strip()
    if not term:
        return items([])
    like = f"%{term}%"
    return items(query_titles(
        profile,
        ["(t.name ILIKE %s OR t.genre ILIKE %s OR t.synopsis ILIKE %s OR t.id IN "
         "(SELECT tg.title_id FROM title_genres tg JOIN genres g ON g.id = tg.genre_id WHERE g.name ILIKE %s))"],
        [like, like, like, like, like],
        "(CASE WHEN t.name ILIKE %s THEN 0 ELSE 1 END), t.rating DESC NULLS LAST, t.id",
        50,
    ))


# ---------------------------------------------------------------- my list
def my_list_rows(profile: dict, where: str = "", params: tuple = ()) -> list[dict]:
    base, p = title_select(profile)
    rows = fetch_all(
        f"""SELECT m.id AS list_id, m.profile_id, m.created_at AS added_at, x.* FROM my_list m
            JOIN ({base}) x ON x.id = m.title_id WHERE m.profile_id = %s {where} ORDER BY m.created_at DESC, m.id DESC""",
        [*p, profile["id"], *params],
    )
    out = []
    for r in rows:
        title = norm_title({k: v for k, v in r.items() if k not in ("list_id", "profile_id", "added_at")})
        out.append({
            "id": r["list_id"], "profile_id": r["profile_id"], "title_id": title["id"], "added_at": r["added_at"],
            "name": title["name"], "poster": title["poster"], "backdrop": title["backdrop"], "title": title,
        })
    return out


@app.get("/api/my-list")
def get_my_list(profile: dict = Depends(current_profile)):
    return items(my_list_rows(profile))


@app.post("/api/my-list", status_code=201)
async def add_my_list(request: Request, profile: dict = Depends(current_profile)):
    body = await read_body(request)
    profile = body_profile(profile, body)
    raw = body.get("title_id", body.get("titleId", body.get("id")))
    try:
        title_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, "title_id (integer) is required")
    if not fetch_one("SELECT id FROM titles WHERE id = %s", (title_id,)):
        raise HTTPException(404, "Title not found")
    fetch_one(
        "INSERT INTO my_list (profile_id, title_id) VALUES (%s, %s) ON CONFLICT (profile_id, title_id) DO NOTHING RETURNING id",
        (profile["id"], title_id),
    )
    return my_list_rows(profile, "AND m.title_id = %s", (title_id,))[0]


@app.get("/api/my-list/{item_id}")
def get_my_list_item(item_id: int, by: Optional[str] = None, profile: dict = Depends(current_profile)):
    """Read one entry by list-entry id (default) or by title id (?by=title, or fallback)."""
    rows = [] if by == "title" else my_list_rows(profile, "AND m.id = %s", (item_id,))
    if not rows and by != "entry":
        rows = my_list_rows(profile, "AND m.title_id = %s", (item_id,))
    if not rows:
        raise HTTPException(404, "Not in My List")
    return rows[0]


@app.put("/api/my-list/{item_id}")
@app.patch("/api/my-list/{item_id}")
async def update_my_list_item(item_id: int, request: Request, profile: dict = Depends(current_profile)):
    """Move an entry to another title (entry id). 404 if the entry isn't in this profile's list."""
    body = await read_body(request)
    entry = fetch_one("SELECT id, title_id FROM my_list WHERE id = %s AND profile_id = %s", (item_id, profile["id"]))
    if not entry:
        raise HTTPException(404, "Not in My List")
    raw = body.get("title_id", entry["title_id"])
    try:
        title_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, "title_id must be an integer")
    if not fetch_one("SELECT id FROM titles WHERE id = %s", (title_id,)):
        raise HTTPException(404, "Title not found")
    if title_id != entry["title_id"]:
        if fetch_one("SELECT id FROM my_list WHERE profile_id = %s AND title_id = %s", (profile["id"], title_id)):
            raise HTTPException(409, "Title is already in My List")
        fetch_one("UPDATE my_list SET title_id = %s WHERE id = %s RETURNING id", (title_id, item_id))
    return my_list_rows(profile, "AND m.id = %s", (item_id,))[0]


@app.get("/api/titles/{title_id}/rating")
def get_rating(title_id: int, profile: dict = Depends(current_profile)):
    get_title_or_404(title_id, profile)
    row = fetch_one("SELECT id, profile_id, title_id, value FROM ratings WHERE profile_id = %s AND title_id = %s", (profile["id"], title_id))
    return row or {"id": None, "profile_id": profile["id"], "title_id": title_id, "value": None}


@app.delete("/api/my-list/{item_id}")
def remove_my_list(item_id: int, by: Optional[str] = None, profile: dict = Depends(current_profile)):
    """Remove by list-entry id (default) or by title id (?by=title, or fallback when no entry has that id)."""
    row = None
    if by != "title":
        row = fetch_one("DELETE FROM my_list WHERE id = %s AND profile_id = %s RETURNING id, title_id", (item_id, profile["id"]))
    if not row and by != "entry":
        row = fetch_one("DELETE FROM my_list WHERE title_id = %s AND profile_id = %s RETURNING id, title_id", (item_id, profile["id"]))
    if not row:
        raise HTTPException(404, "Not in My List")
    return {"deleted": True, "id": row["id"], "title_id": row["title_id"]}


# ---------------------------------------------------------------- continue watching
@app.get("/api/continue-watching")
def continue_watching(profile: dict = Depends(current_profile)):
    base, p = title_select(profile)
    rows = fetch_all(
        f"""SELECT c.id AS cw_id, c.profile_id AS cw_profile, c.progress_seconds, c.episode_id, c.updated_at, x.*
            FROM continue_watching c JOIN ({base}) x ON x.id = c.title_id
            WHERE c.profile_id = %s ORDER BY c.updated_at DESC, c.id DESC""",
        [*p, profile["id"]],
    )
    out = []
    for r in rows:
        title = norm_title({k: v for k, v in r.items() if k not in ("cw_id", "cw_profile", "progress_seconds", "episode_id", "updated_at")})
        out.append({
            "id": r["cw_id"], "profile_id": r["cw_profile"], "title_id": title["id"], "progress_seconds": r["progress_seconds"],
            "episode_id": r["episode_id"], "updated_at": r["updated_at"], "name": title["name"], "poster": title["poster"],
            "backdrop": title["backdrop"], "title": title,
        })
    return items(out)


@app.post("/api/continue-watching")
@app.put("/api/continue-watching")
async def save_progress(request: Request, profile: dict = Depends(current_profile)):
    body = await read_body(request)
    profile = body_profile(profile, body)
    try:
        title_id = int(body.get("title_id"))
        progress = int(float(body.get("progress_seconds", 0)))
    except (TypeError, ValueError):
        raise HTTPException(422, "title_id and progress_seconds are required")
    if progress < 0:
        raise HTTPException(422, "progress_seconds must be >= 0")
    episode_id = body.get("episode_id")
    if episode_id is not None:
        try:
            episode_id = int(episode_id)
        except (TypeError, ValueError):
            raise HTTPException(422, "episode_id must be an integer")
        if not fetch_one("SELECT id FROM episodes WHERE id = %s AND title_id = %s", (episode_id, title_id)):
            raise HTTPException(404, "Episode not found")
    if not fetch_one("SELECT id FROM titles WHERE id = %s", (title_id,)):
        raise HTTPException(404, "Title not found")
    return fetch_one(
        """INSERT INTO continue_watching (profile_id, title_id, progress_seconds, episode_id) VALUES (%s, %s, %s, %s)
           ON CONFLICT (profile_id, title_id) DO UPDATE SET progress_seconds = EXCLUDED.progress_seconds,
             episode_id = EXCLUDED.episode_id, updated_at = now()
           RETURNING id, profile_id, title_id, progress_seconds, episode_id""",
        (profile["id"], title_id, progress, episode_id),
    )


@app.delete("/api/continue-watching/{title_id}")
def remove_progress(title_id: int, profile: dict = Depends(current_profile)):
    row = fetch_one("DELETE FROM continue_watching WHERE profile_id = %s AND title_id = %s RETURNING id", (profile["id"], title_id))
    if not row:
        raise HTTPException(404, "Not in Continue Watching")
    return {"deleted": True, "title_id": title_id}
