"""simple_blog reference backend — FastAPI + SQLite + httpOnly cookie auth.

No /api prefix. Cookie-based auth. List endpoint envelope: {"posts": [...]}.
"""
import hashlib
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Cookie, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, EmailStr

DB_PATH = ":memory:"
_conn: sqlite3.Connection = None  # type: ignore
# server-side session store: token -> email
_sessions: dict[str, str] = {}


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               email TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS posts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               body TEXT NOT NULL,
               author_email TEXT NOT NULL
           )"""
    )
    conn.commit()
    return conn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _conn
    _conn = _init_db()
    yield
    _conn.close()


app = FastAPI(lifespan=lifespan)


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class PostBody(BaseModel):
    title: str
    body: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterBody):
    if not payload.password:
        raise HTTPException(status_code=400, detail="password required")
    try:
        cur = _conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (payload.email, _hash(payload.password)),
        )
        _conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="email already registered")
    return {"id": cur.lastrowid, "email": payload.email}


@app.post("/login")
def login(payload: LoginBody, response: Response):
    row = _conn.execute(
        "SELECT password_hash FROM users WHERE email = ?", (payload.email,)
    ).fetchone()
    if row is None or row["password_hash"] != _hash(payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = secrets.token_hex(32)
    _sessions[token] = payload.email
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"email": payload.email}


def _current_user(session_token: Optional[str]) -> str:
    if not session_token or session_token not in _sessions:
        raise HTTPException(status_code=401, detail="authentication required")
    return _sessions[session_token]


@app.post("/posts", status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostBody, session_token: Optional[str] = Cookie(default=None)
):
    email = _current_user(session_token)
    if not payload.title or not payload.body:
        raise HTTPException(status_code=400, detail="title and body required")
    cur = _conn.execute(
        "INSERT INTO posts (title, body, author_email) VALUES (?, ?, ?)",
        (payload.title, payload.body, email),
    )
    _conn.commit()
    return {
        "id": cur.lastrowid,
        "title": payload.title,
        "body": payload.body,
        "author_email": email,
    }


@app.get("/posts/{post_id}")
def get_post(post_id: int):
    row = _conn.execute(
        "SELECT id, title, body, author_email FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "author_email": row["author_email"],
    }


@app.get("/posts")
def list_posts():
    rows = _conn.execute(
        "SELECT id, title, body, author_email FROM posts ORDER BY id"
    ).fetchall()
    return {
        "posts": [
            {
                "id": r["id"],
                "title": r["title"],
                "body": r["body"],
                "author_email": r["author_email"],
            }
            for r in rows
        ]
    }
