# facebook-web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hand-scaffold a runnable Facebook-style social app at `env-gen/generated/facebook-web/` matching the 8 reference screenshots, with React+Vite frontend, FastAPI+SQLAlchemy backend, PostgreSQL 16, and one-command Docker Compose startup.

**Architecture:** Three-tier (frontend / backend / db) in separate containers. Frontend is a Vite SPA served by nginx in prod, which proxies `/api` to the backend. Backend is async FastAPI with SQLAlchemy 2.0 async sessions on asyncpg. Auth via opaque session-token cookie. Synthetic seed runs once inside the backend container on first boot.

**Tech Stack:** React 18, Vite 5, Tailwind 3, react-router-dom 6, axios; Python 3.11, FastAPI, SQLAlchemy 2.0, asyncpg, Pydantic v2, bcrypt, Faker, pytest; PostgreSQL 16; Docker Compose v2; nginx (alpine).

**Spec:** `docs/superpowers/specs/2026-05-21-facebook-web-design.md`

---

## File Structure

All paths relative to `env-gen/generated/facebook-web/`.

### Backend (`app/backend/`)

| File | Responsibility |
|---|---|
| `src/main.py` | FastAPI app, CORS, router wiring, startup hook that calls seeder |
| `src/db.py` | Async engine, session factory, `get_db` dependency |
| `src/config.py` | Settings via pydantic-settings (DATABASE_URL, SESSION_SECRET) |
| `src/models/__init__.py` | Re-exports all ORM models |
| `src/models/base.py` | `Base` (DeclarativeBase) + common columns |
| `src/models/user.py` | `User`, `Session` |
| `src/models/social.py` | `Friendship`, `Post`, `PostMedia`, `Comment`, `Reaction`, `SavedPost` |
| `src/models/reel.py` | `Reel`, `ReelReaction` |
| `src/models/marketplace.py` | `MarketplaceListing`, `ListingSave` |
| `src/models/misc.py` | `Notification`, `Message`, `UserSettings` |
| `src/schemas/__init__.py` | Re-export Pydantic schemas |
| `src/schemas/user.py` | UserOut, UserCreate, LoginIn, ProfileUpdate |
| `src/schemas/social.py` | PostOut, PostCreate, CommentOut, CommentCreate, ReactionIn, FriendshipOut |
| `src/schemas/reel.py` | ReelOut |
| `src/schemas/marketplace.py` | ListingOut, ListingCreate, ListingFilter |
| `src/schemas/misc.py` | NotificationOut, MessageOut, SettingsOut, SettingsUpdate |
| `src/deps.py` | `get_db`, `current_user`, `require_role`, `optional_user` |
| `src/auth.py` | `hash_password`, `verify_password`, `create_session`, `delete_session`, cookie helpers |
| `src/routes/__init__.py` | Router aggregator |
| `src/routes/auth.py` | `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me` |
| `src/routes/users.py` | `/users/profiles`, `/users/:id`, `/users/me` |
| `src/routes/posts.py` | feed + CRUD + save |
| `src/routes/comments.py` | comment CRUD |
| `src/routes/reactions.py` | reaction toggle |
| `src/routes/friends.py` | suggestions, request, accept, decline, list |
| `src/routes/reels.py` | list + react |
| `src/routes/marketplace.py` | list + filter + CRUD + save |
| `src/routes/notifications.py` | list + mark read |
| `src/routes/messages.py` | threads + send |
| `src/routes/settings.py` | get + update |
| `src/seed.py` | Idempotent synthetic seeder (orchestrates other modules) |
| `src/seed_content.py` | Curated content pools (post templates, listing categories, etc.) |
| `src/requirements.txt` | Pinned dependencies |
| `pyproject.toml` | Project metadata, ruff/pytest config |
| `tests/conftest.py` | Test fixtures: temp DB, client, seeded users |
| `tests/test_auth.py` | Auth flows |
| `tests/test_posts.py` | Post CRUD + viewer 403 |
| `tests/test_reactions.py` | Toggle + uniqueness |
| `tests/test_friends.py` | Request → accept flow |
| `tests/test_marketplace.py` | Filter + create |
| `tests/test_permissions.py` | Role enforcement |

### Database (`app/database/`)

| File | Responsibility |
|---|---|
| `init/01_schema.sql` | Idempotent `CREATE TYPE` + `CREATE TABLE IF NOT EXISTS` for every table |
| `init/02_seed_minimal.sql` | Tiny fallback seed (3 users, 1 post) — manual use only |

### Frontend (`app/frontend/`)

| File | Responsibility |
|---|---|
| `package.json` | React, Vite, Tailwind, axios, react-router, lucide-react |
| `vite.config.js` | Dev server, `/api` proxy to `http://localhost:8000` |
| `tailwind.config.js`, `postcss.config.js` | Tailwind setup |
| `index.html` | Root HTML with `#root` |
| `src/main.jsx` | Bootstrap ReactDOM, Router, AuthProvider |
| `src/App.jsx` | Route definitions + ProtectedRoute wrapper |
| `src/styles/global.css` | Tailwind directives, base resets, Facebook color palette |
| `src/api/client.js` | axios instance with `withCredentials: true`, baseURL `/api` |
| `src/api/auth.js` | login, register, logout, me |
| `src/api/posts.js` | feed, get, create, delete, save, savedList |
| `src/api/comments.js` | list, create, delete |
| `src/api/reactions.js` | toggle |
| `src/api/friends.js` | suggestions, request, accept, decline, list |
| `src/api/reels.js` | list, react |
| `src/api/marketplace.js` | list, get, create, save |
| `src/api/notifications.js` | list, markRead |
| `src/api/settings.js` | get, update |
| `src/context/AuthContext.jsx` | useAuth hook, login/logout, current user, role helpers |
| `src/components/ProtectedRoute.jsx` | Redirect to /login if no user |
| `src/components/TopNav.jsx` | Search bar, center nav (home/friends/profile icons), right cluster (find friends, menu, messenger, notif, profile) |
| `src/components/Sidebar.jsx` | Left nav for home/friends/marketplace/etc with active state |
| `src/components/RightRail.jsx` | Sponsored + contacts + birthdays |
| `src/components/Composer.jsx` | "What's on your mind?" + photo/feeling controls |
| `src/components/PostCard.jsx` | Single post with avatar, content, media, reactions bar, comment toggle |
| `src/components/ReactionPicker.jsx` | Hover-emoji picker |
| `src/components/CommentList.jsx` | Recursive (1 level) comment thread |
| `src/components/CommentInput.jsx` | Avatar + text input |
| `src/components/FriendCard.jsx` | Avatar, name, mutuals, action buttons |
| `src/components/ReelCard.jsx` | Gradient placeholder + creator overlay + caption + reactions column |
| `src/components/ListingCard.jsx` | Image + price + title + location |
| `src/components/Modal.jsx` | Reusable overlay (used by PostDetail) |
| `src/components/EmptyState.jsx` | Generic empty list helper |
| `src/components/RememberPasswordBanner.jsx` | The dismissible banner shown in home.png |
| `src/pages/Login.jsx` | Split-pane marketing + profile selector |
| `src/pages/Register.jsx` | Create-account form |
| `src/pages/Home.jsx` | 3-column layout, composer, feed |
| `src/pages/PostDetail.jsx` | Modal showing single post + full comments |
| `src/pages/People.jsx` | Tabs: Suggestions / Friend Requests / All Friends |
| `src/pages/Reels.jsx` | Vertical reel scroller |
| `src/pages/Marketplace.jsx` | Filter sidebar + grid + detail drawer |
| `src/pages/Settings.jsx` | Settings tabs + forms |
| `src/hooks/useFeed.js` | Cursor-based feed fetcher |

### Docker (`docker/`)

| File | Responsibility |
|---|---|
| `docker-compose.yml` | Prod: db, db_init, backend, frontend(nginx) |
| `docker-compose.dev.yml` | Dev: bind mounts + uvicorn --reload + vite dev |
| `backend.Dockerfile` | python:3.11-slim, install reqs, uvicorn entrypoint |
| `frontend.Dockerfile` | Multi-stage: node 20 builder + nginx:alpine runtime |
| `nginx.conf` | Serve `/`, proxy `/api/*` → `http://backend:8000` |

### Root

| File | Responsibility |
|---|---|
| `README.md` | Run instructions, test creds, architecture summary |
| `STRUCTURE.md` | Map of the directory tree |
| `scripts/start.sh` | `docker compose up --build -d` + wait-for-healthy |
| `scripts/reset_db.sh` | `docker compose down -v && docker compose up --build` |
| `.gitignore` | node_modules, __pycache__, .env, dist |

---

## Phase 0 — Repo skeleton

### Task 0.1: Create directory tree + .gitignore

**Files:**
- Create: `env-gen/generated/facebook-web/.gitignore`

- [ ] **Step 1: Make all directories**

```bash
cd /data/common/haibotong/env-gen/generated
mkdir -p facebook-web/app/{frontend/src/{api,components,context,hooks,pages,styles},backend/src/{models,schemas,routes},backend/tests,database/init}
mkdir -p facebook-web/{docker,scripts}
```

- [ ] **Step 2: Write `.gitignore`**

```
node_modules/
dist/
__pycache__/
*.pyc
.venv/
.env
.env.local
*.log
.DS_Store
.pytest_cache/
```

---

## Phase 1 — Database schema

### Task 1.1: Write `01_schema.sql`

**Files:**
- Create: `app/database/init/01_schema.sql`

- [ ] **Step 1: Write the file**

Full content — every `CREATE TYPE` wrapped in idempotent DO-block, every table uses `IF NOT EXISTS`:

```sql
-- facebook-web schema (idempotent)

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin','member','viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE friendship_status AS ENUM ('pending','accepted','blocked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE post_visibility AS ENUM ('public','friends','only_me');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE media_kind AS ENUM ('image','video');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE reaction_target AS ENUM ('post','comment');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE reaction_type AS ENUM ('like','love','haha','wow','sad','angry');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE listing_status AS ENUM ('active','sold','archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE theme_pref AS ENUM ('light','dark','system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE visibility_pref AS ENUM ('public','friends','only_me');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    username        VARCHAR(64)  UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    name            VARCHAR(120) NOT NULL,
    avatar_url      TEXT,
    cover_url       TEXT,
    bio             TEXT,
    role            user_role NOT NULL DEFAULT 'member',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);

CREATE TABLE IF NOT EXISTS friendships (
    id            SERIAL PRIMARY KEY,
    requester_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        friendship_status NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (requester_id, addressee_id),
    CHECK (requester_id <> addressee_id)
);
CREATE INDEX IF NOT EXISTS ix_friendships_addressee ON friendships(addressee_id);

CREATE TABLE IF NOT EXISTS posts (
    id         SERIAL PRIMARY KEY,
    author_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    visibility post_visibility NOT NULL DEFAULT 'public',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_posts_author_created ON posts(author_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_posts_created ON posts(created_at DESC);

CREATE TABLE IF NOT EXISTS post_media (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    kind        media_kind NOT NULL,
    url         TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_post_media_post ON post_media(post_id);

CREATE TABLE IF NOT EXISTS comments (
    id                SERIAL PRIMARY KEY,
    post_id           INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    content           TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_comments_post ON comments(post_id, created_at);

CREATE TABLE IF NOT EXISTS reactions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_kind reaction_target NOT NULL,
    target_id   INTEGER NOT NULL,
    type        reaction_type NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS ix_reactions_target ON reactions(target_kind, target_id);

CREATE TABLE IF NOT EXISTS saved_posts (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, post_id)
);

CREATE TABLE IF NOT EXISTS reels (
    id               SERIAL PRIMARY KEY,
    creator_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    caption          TEXT,
    media_url        TEXT,
    thumbnail_url    TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 15,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reels_created ON reels(created_at DESC);

CREATE TABLE IF NOT EXISTS reel_reactions (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reel_id    INTEGER NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    type       reaction_type NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, reel_id)
);

CREATE TABLE IF NOT EXISTS marketplace_listings (
    id          SERIAL PRIMARY KEY,
    seller_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(200) NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL,
    currency    VARCHAR(3) NOT NULL DEFAULT 'USD',
    category    VARCHAR(64) NOT NULL,
    location    VARCHAR(120),
    image_url   TEXT,
    status      listing_status NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_listings_category ON marketplace_listings(category);
CREATE INDEX IF NOT EXISTS ix_listings_created ON marketplace_listings(created_at DESC);

CREATE TABLE IF NOT EXISTS listing_saves (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id INTEGER NOT NULL REFERENCES marketplace_listings(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       VARCHAR(64) NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    read       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_notifications_user_read ON notifications(user_id, read, created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id           SERIAL PRIMARY KEY,
    sender_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body         TEXT NOT NULL,
    read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_pair ON messages(sender_id, recipient_id, created_at);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id                INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme                  theme_pref NOT NULL DEFAULT 'light',
    language               VARCHAR(8) NOT NULL DEFAULT 'en',
    notify_email           BOOLEAN NOT NULL DEFAULT TRUE,
    notify_push            BOOLEAN NOT NULL DEFAULT TRUE,
    profile_visibility     visibility_pref NOT NULL DEFAULT 'public',
    show_active_status     BOOLEAN NOT NULL DEFAULT TRUE,
    allow_friend_requests  BOOLEAN NOT NULL DEFAULT TRUE,
    blocked_user_ids       JSONB NOT NULL DEFAULT '[]'::jsonb
);
```

- [ ] **Step 2: Write `02_seed_minimal.sql` (fallback only)**

```sql
-- Minimal manual fallback; the Python seeder is the normal path.
INSERT INTO users (email, username, password_hash, name, role)
VALUES
  ('admin@example.com','admin','$2b$12$placeholder','Admin User','admin'),
  ('haibo@example.com','haibo','$2b$12$placeholder','Haibo Tong','member'),
  ('viewer@example.com','viewer','$2b$12$placeholder','Viewer User','viewer')
ON CONFLICT (email) DO NOTHING;
```

---

## Phase 2 — Backend foundation

### Task 2.1: Requirements + pyproject

**Files:**
- Create: `app/backend/src/requirements.txt`
- Create: `app/backend/pyproject.toml`

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
pydantic==2.9.2
pydantic-settings==2.5.2
bcrypt==4.2.0
python-multipart==0.0.12
faker==30.3.0
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "facebook-web-backend"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

### Task 2.2: Config + DB + Base model

**Files:**
- Create: `app/backend/src/config.py`
- Create: `app/backend/src/db.py`
- Create: `app/backend/src/models/__init__.py`
- Create: `app/backend/src/models/base.py`

- [ ] **Step 1: `config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fb:fb@db:5432/facebook"
    session_secret: str = "dev-secret-change-me"
    session_ttl_days: int = 30
    cors_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

- [ ] **Step 2: `db.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from .config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 3: `models/base.py`**

```python
from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

### Task 2.3: ORM models

**Files:**
- Create: `app/backend/src/models/user.py`
- Create: `app/backend/src/models/social.py`
- Create: `app/backend/src/models/reel.py`
- Create: `app/backend/src/models/marketplace.py`
- Create: `app/backend/src/models/misc.py`

- [ ] **Step 1: `user.py`**

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Enum, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

USER_ROLES = ("admin", "member", "viewer")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Enum(*USER_ROLES, name="user_role", create_type=False), default="member"
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=None
    )
```

- [ ] **Step 2: `social.py`** — `Friendship`, `Post`, `PostMedia`, `Comment`, `Reaction`, `SavedPost`. Use the same enum + mapped_column pattern, foreign-keying to `users.id` and `posts.id`. Reaction has `(user_id, target_kind, target_id, type)` with composite unique.

```python
from datetime import datetime
from sqlalchemy import String, Text, Enum, ForeignKey, DateTime, Integer, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

FRIENDSHIP_STATUS = ("pending", "accepted", "blocked")
POST_VISIBILITY = ("public", "friends", "only_me")
MEDIA_KIND = ("image", "video")
REACTION_TARGET = ("post", "comment")
REACTION_TYPE = ("like", "love", "haha", "wow", "sad", "angry")


class Friendship(Base, TimestampMixin):
    __tablename__ = "friendships"
    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    addressee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(
        Enum(*FRIENDSHIP_STATUS, name="friendship_status", create_type=False),
        default="pending",
    )
    __table_args__ = (UniqueConstraint("requester_id", "addressee_id"),)


class Post(Base, TimestampMixin):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(
        Enum(*POST_VISIBILITY, name="post_visibility", create_type=False),
        default="public",
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostMedia(Base):
    __tablename__ = "post_media"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Enum(*MEDIA_KIND, name="media_kind", create_type=False))
    url: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text)


class Reaction(Base, TimestampMixin):
    __tablename__ = "reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_kind: Mapped[str] = mapped_column(
        Enum(*REACTION_TARGET, name="reaction_target", create_type=False)
    )
    target_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(
        Enum(*REACTION_TYPE, name="reaction_type", create_type=False)
    )
    __table_args__ = (
        UniqueConstraint("user_id", "target_kind", "target_id"),
        Index("ix_reactions_target", "target_kind", "target_id"),
    )


class SavedPost(Base, TimestampMixin):
    __tablename__ = "saved_posts"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
```

- [ ] **Step 3: `reel.py`**

```python
from sqlalchemy import Text, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin
from .social import REACTION_TYPE


class Reel(Base, TimestampMixin):
    __tablename__ = "reels"
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=15)


class ReelReaction(Base, TimestampMixin):
    __tablename__ = "reel_reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reel_id: Mapped[int] = mapped_column(ForeignKey("reels.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(
        Enum(*REACTION_TYPE, name="reaction_type", create_type=False)
    )
    __table_args__ = (UniqueConstraint("user_id", "reel_id"),)
```

- [ ] **Step 4: `marketplace.py`**

```python
from sqlalchemy import String, Text, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

LISTING_STATUS = ("active", "sold", "archived")


class MarketplaceListing(Base, TimestampMixin):
    __tablename__ = "marketplace_listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    category: Mapped[str] = mapped_column(String(64), index=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*LISTING_STATUS, name="listing_status", create_type=False),
        default="active",
    )


class ListingSave(Base, TimestampMixin):
    __tablename__ = "listing_saves"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), primary_key=True
    )
```

- [ ] **Step 5: `misc.py`**

```python
from sqlalchemy import String, Text, Boolean, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

THEME_PREF = ("light", "dark", "system")
VIS_PREF = ("public", "friends", "only_me")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(
        Enum(*THEME_PREF, name="theme_pref", create_type=False), default="light"
    )
    language: Mapped[str] = mapped_column(String(8), default="en")
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_push: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_visibility: Mapped[str] = mapped_column(
        Enum(*VIS_PREF, name="visibility_pref", create_type=False), default="public"
    )
    show_active_status: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_friend_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked_user_ids: Mapped[list] = mapped_column(JSONB, default=list)
```

- [ ] **Step 6: `models/__init__.py`**

```python
from .base import Base
from .user import User, Session, USER_ROLES
from .social import (
    Friendship, Post, PostMedia, Comment, Reaction, SavedPost,
    FRIENDSHIP_STATUS, POST_VISIBILITY, MEDIA_KIND, REACTION_TARGET, REACTION_TYPE,
)
from .reel import Reel, ReelReaction
from .marketplace import MarketplaceListing, ListingSave, LISTING_STATUS
from .misc import Notification, Message, UserSettings, THEME_PREF, VIS_PREF

__all__ = [
    "Base", "User", "Session", "USER_ROLES",
    "Friendship", "Post", "PostMedia", "Comment", "Reaction", "SavedPost",
    "FRIENDSHIP_STATUS", "POST_VISIBILITY", "MEDIA_KIND", "REACTION_TARGET", "REACTION_TYPE",
    "Reel", "ReelReaction",
    "MarketplaceListing", "ListingSave", "LISTING_STATUS",
    "Notification", "Message", "UserSettings", "THEME_PREF", "VIS_PREF",
]
```

### Task 2.4: Auth helpers + deps

**Files:**
- Create: `app/backend/src/auth.py`
- Create: `app/backend/src/deps.py`

- [ ] **Step 1: `auth.py`**

```python
import bcrypt
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Session as DBSession

COOKIE_NAME = "sid"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


async def create_session(db: AsyncSession, user_id: int, response: Response) -> uuid.UUID:
    sid = uuid.uuid4()
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.add(DBSession(id=sid, user_id=user_id, expires_at=expires))
    await db.commit()
    response.set_cookie(
        COOKIE_NAME, str(sid),
        httponly=True, samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    return sid


async def delete_session(db: AsyncSession, sid: str, response: Response) -> None:
    from sqlalchemy import delete
    await db.execute(delete(DBSession).where(DBSession.id == uuid.UUID(sid)))
    await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
```

- [ ] **Step 2: `deps.py`**

```python
import uuid
from datetime import datetime, timezone
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import Session as DBSession, User
from .auth import COOKIE_NAME


async def optional_user(
    sid: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not sid:
        return None
    try:
        sid_uuid = uuid.UUID(sid)
    except ValueError:
        return None
    row = (await db.execute(
        select(DBSession, User).join(User, User.id == DBSession.user_id)
        .where(DBSession.id == sid_uuid)
    )).first()
    if not row:
        return None
    session, user = row
    if session.expires_at < datetime.now(timezone.utc):
        return None
    return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


def require_role(*roles: str):
    async def _check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user
    return _check
```

### Task 2.5: Pydantic schemas

**Files:**
- Create: `app/backend/src/schemas/__init__.py`
- Create: `app/backend/src/schemas/user.py`
- Create: `app/backend/src/schemas/social.py`
- Create: `app/backend/src/schemas/reel.py`
- Create: `app/backend/src/schemas/marketplace.py`
- Create: `app/backend/src/schemas/misc.py`

- [ ] **Step 1: `user.py`**

```python
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id: int
    email: EmailStr
    username: str
    name: str
    avatar_url: str | None = None
    cover_url: str | None = None
    bio: str | None = None
    role: str
    created_at: datetime
    model_config = {"from_attributes": True}


class UserPublic(BaseModel):
    id: int
    username: str
    name: str
    avatar_url: str | None = None
    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    cover_url: str | None = None
```

- [ ] **Step 2: `social.py`**

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from .user import UserPublic

ReactionType = Literal["like", "love", "haha", "wow", "sad", "angry"]


class MediaOut(BaseModel):
    id: int
    kind: Literal["image", "video"]
    url: str
    order_index: int = 0
    model_config = {"from_attributes": True}


class ReactionSummary(BaseModel):
    counts: dict[str, int] = {}
    total: int = 0
    my_reaction: ReactionType | None = None


class PostOut(BaseModel):
    id: int
    author: UserPublic
    content: str
    visibility: Literal["public", "friends", "only_me"]
    media: list[MediaOut] = []
    reactions: ReactionSummary
    comment_count: int = 0
    saved: bool = False
    created_at: datetime


class PostCreate(BaseModel):
    content: str
    visibility: Literal["public", "friends", "only_me"] = "public"
    media_urls: list[str] = []


class CommentOut(BaseModel):
    id: int
    post_id: int
    author: UserPublic
    parent_comment_id: int | None
    content: str
    created_at: datetime
    reactions: ReactionSummary


class CommentCreate(BaseModel):
    content: str
    parent_comment_id: int | None = None


class ReactionIn(BaseModel):
    target_kind: Literal["post", "comment"]
    target_id: int
    type: ReactionType


class FriendshipOut(BaseModel):
    id: int
    other_user: UserPublic
    status: Literal["pending", "accepted", "blocked"]
    direction: Literal["outgoing", "incoming"]
    created_at: datetime
```

- [ ] **Step 3: `reel.py`**

```python
from datetime import datetime
from pydantic import BaseModel

from .user import UserPublic
from .social import ReactionSummary


class ReelOut(BaseModel):
    id: int
    creator: UserPublic
    caption: str | None
    media_url: str | None
    thumbnail_url: str | None
    duration_seconds: int
    created_at: datetime
    reactions: ReactionSummary
```

- [ ] **Step 4: `marketplace.py`**

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

from .user import UserPublic


class ListingOut(BaseModel):
    id: int
    seller: UserPublic
    title: str
    description: str | None
    price_cents: int
    currency: str
    category: str
    location: str | None
    image_url: str | None
    status: Literal["active", "sold", "archived"]
    saved: bool = False
    created_at: datetime


class ListingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price_cents: int = Field(ge=0)
    currency: str = "USD"
    category: str
    location: str | None = None
    image_url: str | None = None


class ListingFilter(BaseModel):
    category: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    location: str | None = None
    q: str | None = None
```

- [ ] **Step 5: `misc.py`**

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from .user import UserPublic


class NotificationOut(BaseModel):
    id: int
    kind: str
    payload: dict
    read: bool
    created_at: datetime


class MessageOut(BaseModel):
    id: int
    sender: UserPublic
    recipient: UserPublic
    body: str
    read: bool
    created_at: datetime


class MessageCreate(BaseModel):
    recipient_id: int
    body: str


class SettingsOut(BaseModel):
    theme: Literal["light", "dark", "system"]
    language: str
    notify_email: bool
    notify_push: bool
    profile_visibility: Literal["public", "friends", "only_me"]
    show_active_status: bool
    allow_friend_requests: bool
    blocked_user_ids: list[int] = []


class SettingsUpdate(BaseModel):
    theme: Literal["light", "dark", "system"] | None = None
    language: str | None = None
    notify_email: bool | None = None
    notify_push: bool | None = None
    profile_visibility: Literal["public", "friends", "only_me"] | None = None
    show_active_status: bool | None = None
    allow_friend_requests: bool | None = None
    blocked_user_ids: list[int] | None = None
```

- [ ] **Step 6: `schemas/__init__.py`**

```python
from .user import UserOut, UserPublic, UserCreate, LoginIn, ProfileUpdate
from .social import (
    MediaOut, ReactionSummary, PostOut, PostCreate,
    CommentOut, CommentCreate, ReactionIn, FriendshipOut, ReactionType,
)
from .reel import ReelOut
from .marketplace import ListingOut, ListingCreate, ListingFilter
from .misc import NotificationOut, MessageOut, MessageCreate, SettingsOut, SettingsUpdate
```

---

## Phase 3 — Backend routes

### Task 3.1: `routes/__init__.py` aggregator

**Files:**
- Create: `app/backend/src/routes/__init__.py`

- [ ] **Step 1: Write aggregator**

```python
from fastapi import APIRouter
from . import auth, users, posts, comments, reactions, friends, reels, marketplace, notifications, messages, settings

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(posts.router, prefix="/posts", tags=["posts"])
api_router.include_router(comments.router, tags=["comments"])
api_router.include_router(reactions.router, prefix="/reactions", tags=["reactions"])
api_router.include_router(friends.router, prefix="/friends", tags=["friends"])
api_router.include_router(reels.router, prefix="/reels", tags=["reels"])
api_router.include_router(marketplace.router, prefix="/marketplace", tags=["marketplace"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
```

### Task 3.2: Auth routes

**Files:**
- Create: `app/backend/src/routes/auth.py`

- [ ] **Step 1: Write the file**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User, UserSettings
from ..schemas import UserCreate, LoginIn, UserOut
from ..auth import hash_password, verify_password, create_session, delete_session, COOKIE_NAME
from ..deps import current_user

router = APIRouter()


@router.post("/register", response_model=UserOut)
async def register(body: UserCreate, response: Response, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "email or username already registered")
    user = User(
        email=body.email, username=body.username,
        password_hash=hash_password(body.password), name=body.name,
        avatar_url=f"https://i.pravatar.cc/150?u={body.username}",
    )
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    await create_session(db, user.id, response)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    await create_session(db, user.id, response)
    return user


@router.post("/logout")
async def logout(
    response: Response,
    sid: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    if sid:
        await delete_session(db, sid, response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
```

### Task 3.3: Backend route pattern — apply to all resource routes

The remaining routers follow the same pattern. Each:
1. `router = APIRouter()`
2. List endpoint: filtered query, returns Pydantic out-model
3. Detail endpoint by id
4. Mutation endpoints guarded with `current_user` (and `require_role(...)` for admin-only or non-viewer-only)
5. Helper at the bottom that converts ORM row(s) → Pydantic schemas (denormalizing `author`, `reactions`, etc.)

Implement these files in order. Each is one task. Use the patterns established in `auth.py` and the schema definitions:

- [ ] **Step 1: `routes/users.py`** — `GET /profiles` (returns the 3 test accounts for login picker), `GET /:id` (UserPublic), `PATCH /me` (ProfileUpdate, current_user)
- [ ] **Step 2: `routes/posts.py`** — `GET /` (cursor pagination: `?cursor=&limit=20`; joins author, media, reaction summary, comment_count, saved flag; orders by created_at desc; restricts visibility=friends to friends-only); `POST /` (require not-viewer); `GET /:id`; `DELETE /:id` (author or admin); `POST /:id/save` (toggle); `GET /saved`
- [ ] **Step 3: `routes/comments.py`** — `GET /posts/{id}/comments`, `POST /posts/{id}/comments` (not-viewer), `DELETE /comments/{id}` (author or admin)
- [ ] **Step 4: `routes/reactions.py`** — `POST /` (upsert by user+target; if same type → delete = toggle off; else replace type; not-viewer); `DELETE /` body=`ReactionIn`
- [ ] **Step 5: `routes/friends.py`** — `GET /` (`?status=`), `GET /suggestions` (users not already friends/blocked, limit 10, sorted by mutual count), `POST /request` (not-viewer), `POST /{id}/accept` (must be addressee), `DELETE /{id}` (decline or unfriend)
- [ ] **Step 6: `routes/reels.py`** — `GET /` (paginated), `POST /{id}/react` (not-viewer; same upsert pattern)
- [ ] **Step 7: `routes/marketplace.py`** — `GET /` with `ListingFilter` query params, `GET /{id}`, `POST /` (not-viewer), `POST /{id}/save` (toggle)
- [ ] **Step 8: `routes/notifications.py`** — `GET /` (unread first), `PATCH /{id}` (`{read: true}`)
- [ ] **Step 9: `routes/messages.py`** — `GET /` (groups by other party, returns latest per thread), `GET /{user_id}` (full thread), `POST /` (not-viewer)
- [ ] **Step 10: `routes/settings.py`** — `GET /` returns `UserSettings` row (creates default if missing), `PATCH /` applies `SettingsUpdate`

**Pattern note for the reaction-summary join:** instead of N+1 queries, fetch all reactions for the page in one query keyed by `(target_kind, target_id IN (...))`, then bucket in Python. Same approach for comment counts (`SELECT post_id, count(*) FROM comments WHERE post_id = ANY(:ids) GROUP BY post_id`).

**Commit cadence:** commit after each route file.

### Task 3.4: `main.py` — wire everything

**Files:**
- Create: `app/backend/src/main.py`

- [ ] **Step 1: Write the file**

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import User
from .routes import api_router
from .seed import run_seed

log = logging.getLogger("fb")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        count = (await db.execute(select(User))).scalars().first()
        if count is None:
            log.info("Empty users table — running synthetic seed…")
            await run_seed(db)
            log.info("Seed complete.")
        else:
            log.info("Users present — skipping seed.")
    yield


app = FastAPI(title="facebook-web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"ok": True}
```

---

## Phase 4 — Seeder

### Task 4.1: `seed_content.py` — curated pools

**Files:**
- Create: `app/backend/src/seed_content.py`

- [ ] **Step 1: Write content pools**

```python
POST_TEMPLATES = [
    "Just got back from {place}, what a trip 🌴 Can't wait to do it again.",
    "Hot take: {opinion}. Fight me in the comments.",
    "Feeling grateful for {thing} today. Small things matter.",
    "New PR at the gym 💪 {number} reps and counting.",
    "Why does coffee taste so much better on a {day}?",
    "Anyone else watching the new season of {show}? No spoilers!",
    "Spent the whole afternoon cooking {dish}. Worth every minute. 🍳",
    "{milestone} years today. Time flies.",
    "Tested the new {gadget}. Honest review: {opinion}.",
    "Took the dog to {place}. Best decision of the week. 🐕",
    "Reading {book} right now. Slow start but it grew on me.",
    "Public service announcement: {advice}. You're welcome.",
    "When you finally fix the bug that's been haunting you all week 😤➡️🎉",
    "Pro tip: {advice}. Saved me hours.",
    "Family dinner tonight. Missing everyone who couldn't make it ❤️",
    "Quick coffee ☕ before the chaos starts.",
    "Sunset from the balcony. Some days the view is enough.",
    "Office vibes today 🎶 productivity through the roof.",
    "Trying {hobby} for the first time. Worst case: I have a story.",
    "Don't sleep on {thing}. Game changer.",
]

PLACES = ["Tokyo", "Lisbon", "Mexico City", "Reykjavik", "Tulum", "Bali", "Cape Town",
          "Marrakech", "Buenos Aires", "Vancouver", "Oslo", "Seoul"]
OPINIONS = ["pineapple belongs on pizza", "the office finale was perfect", "vim > emacs",
            "tabs over spaces", "tea is better than coffee", "weekends should be 3 days"]
THINGS = ["my coworkers", "sunny mornings", "long walks", "good coffee", "old friends",
          "Sunday breakfasts", "this playlist"]
DAYS = ["Monday", "Sunday", "Friday", "rainy day", "Tuesday"]
SHOWS = ["Severance", "The Bear", "House of the Dragon", "Slow Horses", "Andor"]
DISHES = ["pad thai", "shakshuka", "carbonara", "ramen", "tacos al pastor", "ceviche"]
GADGETS = ["mechanical keyboard", "AirPods Pro", "Steam Deck", "Kindle Scribe"]
BOOKS = ["Project Hail Mary", "The Three-Body Problem", "Tomorrow and Tomorrow and Tomorrow"]
ADVICE = [
    "drink water before coffee", "stretch every 45 minutes",
    "back up your dotfiles", "always read the changelog",
    "buy the boots that fit", "use a smaller monitor when debugging",
]
HOBBIES = ["pottery", "rock climbing", "sourdough baking", "skateboarding", "watercolor"]
MILESTONES = [1, 3, 5, 7, 10]
NUMBERS = [5, 8, 10, 12, 15, 20]

EMOJI_TAILS = ["", "", "", " 😂", " 🔥", " ✨", " 🙌", " ❤️", " 🤷", " 😅"]

REEL_CAPTIONS = [
    "POV: it's Monday morning 😅",
    "When the code finally compiles 💻✨",
    "Watch till the end 👀",
    "Recipe in the comments 👇",
    "Day {n} of trying new things",
    "Sound on 🔊 trust me",
    "Wait for it… 😳",
    "How is this real life 😍",
    "{place} hits different at night.",
    "Tutorial: how to make {dish} in 60 seconds.",
]

MARKETPLACE_CATEGORIES = {
    "Electronics": (5000, 250000, [
        "Sony WH-1000XM5 Headphones", "iPhone 14 Pro 256GB", "Nintendo Switch OLED",
        "Sonos Beam Soundbar", "DJI Mini 3 Drone", "iPad Air 5th Gen",
        "MacBook Air M2", "Bose QuietComfort 45", "GoPro Hero 11",
        "Samsung 55\" 4K TV", "Logitech MX Master 3", "Kindle Paperwhite",
    ]),
    "Furniture": (3000, 200000, [
        "IKEA Karlstad Sofa", "West Elm Coffee Table", "Mid-century dining chairs (set of 4)",
        "Standing desk, electric", "Queen bed frame, oak", "Velvet accent chair",
        "Bookshelf, solid pine", "Outdoor patio set, 6-piece",
    ]),
    "Vehicles": (50000, 4000000, [
        "2019 Toyota Camry, low miles", "2017 Subaru Outback", "Vintage Vespa scooter",
        "2020 Tesla Model 3", "Trek road bike, large frame", "2015 Ford F-150",
    ]),
    "Clothing": (500, 30000, [
        "Levi's vintage denim jacket", "Patagonia Nano Puff (M)", "Nike Air Force 1 (size 10)",
        "Carhartt WIP beanie", "Lululemon ABC pants (32x32)", "Doc Martens 1460",
    ]),
    "Home & Garden": (1000, 50000, [
        "Sage Barista Express", "Le Creuset Dutch oven", "Vitamix A3500",
        "Dyson V11 vacuum", "Set of 6 raised garden beds", "Outdoor fire pit",
    ]),
    "Hobbies": (1000, 80000, [
        "Yamaha acoustic guitar", "Fender Strat (American)", "Canon EOS R6 body",
        "Watercolor starter kit", "Lego Millennium Falcon (used)", "Tabletop loom",
    ]),
    "Free Stuff": (0, 0, [
        "Free moving boxes (lots!)", "Free firewood, you haul",
        "Free books — fiction & textbooks", "Free pile of houseplants",
    ]),
}

CITIES = [
    "San Francisco, CA", "Brooklyn, NY", "Austin, TX", "Seattle, WA", "Boston, MA",
    "Chicago, IL", "Portland, OR", "Denver, CO", "Atlanta, GA", "Nashville, TN",
    "Los Angeles, CA", "Miami, FL", "Minneapolis, MN", "Pittsburgh, PA",
    "Philadelphia, PA", "Phoenix, AZ", "Madison, WI", "Asheville, NC",
    "Salt Lake City, UT", "Burlington, VT",
]

NOTIFICATION_KINDS = [
    "friend_request", "friend_accepted", "post_reaction",
    "comment", "comment_reaction", "mention", "tagged",
]
```

### Task 4.2: `seed.py` — synthetic seeder

**Files:**
- Create: `app/backend/src/seed.py`

- [ ] **Step 1: Write the seeder**

```python
import random
from datetime import datetime, timezone, timedelta
from faker import Faker
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import hash_password
from .models import (
    User, UserSettings, Friendship, Post, PostMedia, Comment, Reaction,
    Reel, MarketplaceListing, Notification, Message,
)
from . import seed_content as sc

FAKER_SEED = 1337
USERS_TOTAL = 50
POSTS_TOTAL = 300
COMMENTS_PER_POST = (1, 5)
REACTIONS_PER_POST = (3, 25)
REELS_TOTAL = 80
LISTINGS_TOTAL = 120
FRIENDSHIPS_PER_USER = (5, 20)

fake = Faker()
Faker.seed(FAKER_SEED)
random.seed(FAKER_SEED)


REACTION_TYPES = ["like", "love", "haha", "wow", "sad", "angry"]
REACTION_WEIGHTS = [60, 15, 10, 5, 5, 5]


def _fill(template: str) -> str:
    return template.format(
        place=random.choice(sc.PLACES), opinion=random.choice(sc.OPINIONS),
        thing=random.choice(sc.THINGS), day=random.choice(sc.DAYS),
        show=random.choice(sc.SHOWS), dish=random.choice(sc.DISHES),
        gadget=random.choice(sc.GADGETS), book=random.choice(sc.BOOKS),
        advice=random.choice(sc.ADVICE), hobby=random.choice(sc.HOBBIES),
        milestone=random.choice(sc.MILESTONES), number=random.choice(sc.NUMBERS),
        n=random.randint(1, 365),
    )


def _post_text() -> str:
    return _fill(random.choice(sc.POST_TEMPLATES)) + random.choice(sc.EMOJI_TAILS)


def _reel_caption() -> str:
    return _fill(random.choice(sc.REEL_CAPTIONS))


def _avatar(username: str) -> str:
    return f"https://i.pravatar.cc/300?u={username}"


def _cover(username: str) -> str:
    return f"https://picsum.photos/seed/cover-{username}/1200/300"


def _post_image(post_id: int) -> str:
    return f"https://picsum.photos/seed/post-{post_id}/800/600"


async def run_seed(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)

    # 1. Fixed test users
    fixed = [
        ("admin@example.com", "admin", "admin123", "Admin User", "admin"),
        ("haibo@example.com", "haibo", "password123", "Haibo Tong", "member"),
        ("viewer@example.com", "viewer", "viewer123", "Viewer User", "viewer"),
    ]
    users: list[User] = []
    for email, uname, pw, name, role in fixed:
        u = User(
            email=email, username=uname, password_hash=hash_password(pw),
            name=name, role=role, avatar_url=_avatar(uname), cover_url=_cover(uname),
            bio=f"Hi, I'm {name}.",
        )
        db.add(u); users.append(u)

    # 2. Random users
    used_usernames = {u.username for u in users}
    used_emails = {u.email for u in users}
    while len(users) < USERS_TOTAL:
        first = fake.first_name(); last = fake.last_name()
        uname = f"{first}.{last}".lower().replace(" ", "")[:60]
        if uname in used_usernames:
            uname = f"{uname}{random.randint(10,9999)}"
        email = f"{uname}@example.com"
        if email in used_emails:
            continue
        used_usernames.add(uname); used_emails.add(email)
        u = User(
            email=email, username=uname, password_hash=hash_password("password"),
            name=f"{first} {last}", role="member",
            avatar_url=_avatar(uname), cover_url=_cover(uname),
            bio=fake.sentence(nb_words=12),
        )
        db.add(u); users.append(u)

    await db.flush()  # populate ids

    # 3. Settings for everyone
    for u in users:
        db.add(UserSettings(user_id=u.id))

    # 4. Friendship graph
    user_ids = [u.id for u in users]
    pairs: set[tuple[int, int]] = set()
    for u in users:
        n = random.randint(*FRIENDSHIPS_PER_USER)
        others = random.sample([oid for oid in user_ids if oid != u.id], k=min(n, len(user_ids)-1))
        for oid in others:
            a, b = sorted((u.id, oid))
            if (a, b) in pairs:
                continue
            pairs.add((a, b))
            db.add(Friendship(requester_id=a, addressee_id=b, status="accepted"))

    # Pending requests targeting the 3 test accounts
    for target in users[:3]:
        for requester in random.sample([u for u in users[3:]], k=5):
            a, b = sorted((requester.id, target.id))
            if (a, b) in pairs:
                continue
            pairs.add((a, b))
            db.add(Friendship(requester_id=requester.id, addressee_id=target.id, status="pending"))

    # 5. Posts
    posts: list[Post] = []
    for i in range(POSTS_TOTAL):
        author = random.choice(users)
        created = now - timedelta(minutes=random.randint(0, 30*24*60))
        p = Post(
            author_id=author.id,
            content=_post_text(),
            visibility=random.choices(["public","friends","only_me"], weights=[80,18,2])[0],
        )
        p.updated_at = created
        # SQLAlchemy server_default for created_at won't honor this unless we override:
        p.created_at = created  # type: ignore[assignment]
        db.add(p); posts.append(p)
    await db.flush()

    # 6. Post media (~30%)
    for p in posts:
        if random.random() < 0.30:
            db.add(PostMedia(post_id=p.id, kind="image", url=_post_image(p.id), order_index=0))

    # 7. Comments
    for p in posts:
        for _ in range(random.randint(*COMMENTS_PER_POST)):
            author = random.choice(users)
            db.add(Comment(
                post_id=p.id, author_id=author.id,
                content=fake.sentence(nb_words=random.randint(4, 18)),
            ))

    # 8. Reactions on posts
    for p in posts:
        reactors = random.sample(users, k=min(random.randint(*REACTIONS_PER_POST), len(users)))
        for r in reactors:
            db.add(Reaction(
                user_id=r.id, target_kind="post", target_id=p.id,
                type=random.choices(REACTION_TYPES, weights=REACTION_WEIGHTS)[0],
            ))

    # 9. Reels
    for i in range(REELS_TOTAL):
        creator = random.choice(users)
        db.add(Reel(
            creator_id=creator.id,
            caption=_reel_caption(),
            media_url=None,
            thumbnail_url=f"https://picsum.photos/seed/reel-{i}/400/700",
            duration_seconds=random.randint(7, 60),
        ))

    # 10. Marketplace listings
    for i in range(LISTINGS_TOTAL):
        seller = random.choice(users)
        category = random.choice(list(sc.MARKETPLACE_CATEGORIES.keys()))
        lo, hi, titles = sc.MARKETPLACE_CATEGORIES[category]
        title = random.choice(titles)
        price = 0 if category == "Free Stuff" else random.randint(lo, hi)
        db.add(MarketplaceListing(
            seller_id=seller.id, title=title,
            description=fake.paragraph(nb_sentences=random.randint(2, 5)),
            price_cents=price, category=category,
            location=random.choice(sc.CITIES),
            image_url=f"https://picsum.photos/seed/listing-{i}/600/600",
            status="active",
        ))

    # 11. Notifications for the 3 fixed accounts
    for target in users[:3]:
        for _ in range(5):
            actor = random.choice(users[3:])
            kind = random.choice(sc.NOTIFICATION_KINDS)
            db.add(Notification(
                user_id=target.id, kind=kind,
                payload={"actor_id": actor.id, "actor_name": actor.name},
                read=random.random() < 0.5,
            ))

    # 12. Messages
    for target in users[:3]:
        contacts = random.sample(users[3:], k=3)
        for c in contacts:
            for _ in range(random.randint(2, 5)):
                sender, recipient = random.sample([target, c], k=2)
                db.add(Message(
                    sender_id=sender.id, recipient_id=recipient.id,
                    body=fake.sentence(nb_words=random.randint(4, 14)),
                    read=random.random() < 0.7,
                ))

    await db.commit()
```

---

## Phase 5 — Backend tests

### Task 5.1: `tests/conftest.py`

**Files:**
- Create: `app/backend/tests/conftest.py`

- [ ] **Step 1: Write fixtures**

```python
import asyncio
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://fb:fb@localhost:5432/facebook_test",
)

from src.main import app  # noqa: E402
from src.db import SessionLocal  # noqa: E402
from src.models import Base  # noqa: E402
from src import db as db_module  # noqa: E402
from src.seed import run_seed  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def _engine():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    db_module.engine = engine
    db_module.SessionLocal = Session
    async with Session() as s:
        await run_seed(s)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(_engine):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def haibo_client(client):
    r = await client.post("/api/auth/login", json={
        "email": "haibo@example.com", "password": "password123"
    })
    assert r.status_code == 200
    return client


@pytest_asyncio.fixture
async def viewer_client(client):
    r = await client.post("/api/auth/login", json={
        "email": "viewer@example.com", "password": "viewer123"
    })
    assert r.status_code == 200
    return client
```

### Task 5.2: Write each test file

Each test file (~5 tests, ~80 lines). Implement in order:

- [ ] **Step 1: `tests/test_auth.py`** — register success, register conflict, login success sets cookie, login wrong pw 401, /me returns user, /me without cookie 401, logout clears cookie
- [ ] **Step 2: `tests/test_posts.py`** — feed returns posts, member can create, viewer create returns 403, get by id, delete own works, delete others 403, delete as admin works
- [ ] **Step 3: `tests/test_reactions.py`** — first POST adds, same-type POST removes (toggle), different-type POST replaces, unique constraint holds
- [ ] **Step 4: `tests/test_friends.py`** — suggestions don't include existing friends, request creates pending, accept moves to accepted, decline deletes
- [ ] **Step 5: `tests/test_marketplace.py`** — list returns all, filter by category, filter by price range, create as member works, create as viewer 403
- [ ] **Step 6: `tests/test_permissions.py`** — viewer cannot react, viewer cannot comment, viewer cannot send friend request, admin can delete others' posts

Run after each: `cd app/backend && pytest tests/test_<name>.py -v` (expect green). Commit per file.

---

## Phase 6 — Frontend foundation

### Task 6.1: `package.json` + Vite + Tailwind

**Files:**
- Create: `app/frontend/package.json`
- Create: `app/frontend/vite.config.js`
- Create: `app/frontend/tailwind.config.js`
- Create: `app/frontend/postcss.config.js`
- Create: `app/frontend/index.html`

- [ ] **Step 1: `package.json`**

```json
{
  "name": "facebook-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0 --port 5173 --strictPort",
    "build": "vite build",
    "preview": "vite preview --host 0.0.0.0 --port 5173"
  },
  "dependencies": {
    "axios": "^1.7.7",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.16",
    "vite": "^5.4.11"
  }
}
```

- [ ] **Step 2: `vite.config.js`**

```js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: mode === 'docker' ? 'http://backend:8000' : 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}));
```

- [ ] **Step 3: `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        fb: {
          blue: '#1877F2',
          blueHover: '#166FE5',
          dark: '#050505',
          gray: '#65676B',
          surface: '#FFFFFF',
          page: '#F0F2F5',
          divider: '#CED0D4',
          card: '#FFFFFF',
          hover: '#F2F2F2',
          active: '#E7F3FF',
          accent: '#0866FF',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.1)',
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 4: `postcss.config.js`**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 5: `index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%231877F2%22><circle cx=%2212%22 cy=%2212%22 r=%2212%22/><text x=%2212%22 y=%2218%22 text-anchor=%22middle%22 font-family=%22Arial,sans-serif%22 font-weight=%22bold%22 fill=%22white%22 font-size=%2216%22>f</text></svg>" />
    <title>Facebook</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

### Task 6.2: Global styles + entry

**Files:**
- Create: `app/frontend/src/styles/global.css`
- Create: `app/frontend/src/main.jsx`

- [ ] **Step 1: `global.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; }
body {
  margin: 0;
  font-family: 'SF Pro Text', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
               Helvetica, Arial, sans-serif;
  background: #F0F2F5;
  color: #050505;
}

button { font: inherit; }
input, textarea { font: inherit; }
a { color: inherit; text-decoration: none; }
```

- [ ] **Step 2: `main.jsx`**

```jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import { AuthProvider } from './context/AuthContext.jsx';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
```

### Task 6.3: API client + per-resource modules

**Files:**
- Create: `app/frontend/src/api/client.js`
- Create: `app/frontend/src/api/{auth,posts,comments,reactions,friends,reels,marketplace,notifications,settings}.js`

- [ ] **Step 1: `client.js`**

```js
import axios from 'axios';
const client = axios.create({ baseURL: '/api', withCredentials: true });
export default client;
```

- [ ] **Step 2: Per-resource modules — same pattern, one file each**

```js
// auth.js
import c from './client';
export const login = (email, password) => c.post('/auth/login', { email, password }).then(r => r.data);
export const register = (body) => c.post('/auth/register', body).then(r => r.data);
export const logout = () => c.post('/auth/logout').then(r => r.data);
export const me = () => c.get('/auth/me').then(r => r.data);
export const profiles = () => c.get('/users/profiles').then(r => r.data);
```

```js
// posts.js
import c from './client';
export const feed = (cursor, limit = 20) => c.get('/posts', { params: { cursor, limit } }).then(r => r.data);
export const get = (id) => c.get(`/posts/${id}`).then(r => r.data);
export const create = (body) => c.post('/posts', body).then(r => r.data);
export const remove = (id) => c.delete(`/posts/${id}`);
export const save = (id) => c.post(`/posts/${id}/save`).then(r => r.data);
export const saved = () => c.get('/posts/saved').then(r => r.data);
```

Apply the same one-liner-per-endpoint pattern to: `comments.js`, `reactions.js`, `friends.js`, `reels.js`, `marketplace.js`, `notifications.js`, `settings.js`. Map every backend endpoint to a named export.

### Task 6.4: AuthContext + ProtectedRoute

**Files:**
- Create: `app/frontend/src/context/AuthContext.jsx`
- Create: `app/frontend/src/components/ProtectedRoute.jsx`

- [ ] **Step 1: `AuthContext.jsx`**

```jsx
import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { me as fetchMe, login as apiLogin, logout as apiLogout } from '../api/auth';

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try { setUser(await fetchMe()); }
    catch { setUser(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async (email, password) => {
    const u = await apiLogin(email, password);
    setUser(u);
    return u;
  };

  const logout = async () => {
    await apiLogout();
    setUser(null);
  };

  const isViewer = user?.role === 'viewer';
  const isAdmin = user?.role === 'admin';

  return (
    <Ctx.Provider value={{ user, loading, login, logout, refresh, isViewer, isAdmin }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
```

- [ ] **Step 2: `ProtectedRoute.jsx`**

```jsx
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8 text-center text-fb-gray">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
```

### Task 6.5: App.jsx + router

**Files:**
- Create: `app/frontend/src/App.jsx`

- [ ] **Step 1: Write router**

```jsx
import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import Home from './pages/Home';
import PostDetail from './pages/PostDetail';
import People from './pages/People';
import Reels from './pages/Reels';
import Marketplace from './pages/Marketplace';
import Settings from './pages/Settings';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<ProtectedRoute><Home /></ProtectedRoute>} />
      <Route path="/post/:id" element={<ProtectedRoute><PostDetail /></ProtectedRoute>} />
      <Route path="/friends" element={<ProtectedRoute><People /></ProtectedRoute>} />
      <Route path="/reels" element={<ProtectedRoute><Reels /></ProtectedRoute>} />
      <Route path="/marketplace" element={<ProtectedRoute><Marketplace /></ProtectedRoute>} />
      <Route path="/settings/*" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

---

## Phase 7 — Shared frontend components

Files in `app/frontend/src/components/`. Each is ~50-150 lines of JSX+Tailwind matching the reference screenshots.

### Task 7.1: TopNav

- [ ] **Step 1: Build `TopNav.jsx`** matching `home.png` top bar — white bg, Facebook "f" logo + search pill on left, center icon nav (home/friends/profile) with active blue underline, right cluster (Find friends button, 3x3 grid, messenger, notifications, profile dropdown). Use `lucide-react` icons.

### Task 7.2: Sidebar

- [ ] **Step 1: Build `Sidebar.jsx`** — left rail matching `home.png`: avatar+name link, Meta AI, Friends, Memories, Saved, Groups, Reels, Marketplace, Feeds, Events, Ads Manager, See more. Each row 36px height, icon + text, hover bg fb-hover, active row bg fb-active. `NavLink` from react-router for active styling.

### Task 7.3: RightRail

- [ ] **Step 1: Build `RightRail.jsx`** — Sponsored block (text-only placeholder), Contacts list (online friends with green dot), Group chats, Birthdays. Each header is text-sm uppercase gray.

### Task 7.4: PostCard + ReactionPicker

- [ ] **Step 1: Build `PostCard.jsx`** — avatar + name + timestamp header, content, optional image, reaction bar (like/comment/share count row above, then 3 action buttons), inline comments collapsed by default. Like button shows current reaction emoji if user reacted. Hovering Like opens `ReactionPicker`.
- [ ] **Step 2: Build `ReactionPicker.jsx`** — 6 emoji buttons that scale on hover.

### Task 7.5: CommentList + CommentInput

- [ ] **Step 1: Build `CommentList.jsx`** — rendered as a vertical list with avatar | bubble (gray bg, rounded-2xl) | reply/like footer. Supports 1 level of nesting for replies.
- [ ] **Step 2: Build `CommentInput.jsx`** — circular avatar + rounded-full text input. Submits on Enter.

### Task 7.6: Composer

- [ ] **Step 1: Build `Composer.jsx`** — card with avatar + "What's on your mind, {firstName}?" pill button that opens a modal with full content textarea + visibility select + create button. Plus Live video / Photo/video / Feeling buttons row below.

### Task 7.7: Other components

- [ ] **Step 1: `RememberPasswordBanner.jsx`** — the white card from `home.png` with "Remember Password" + monitor icon + OK / Not Now buttons. Dismissible via state (sessionStorage so it doesn't reappear in the same session).
- [ ] **Step 2: `FriendCard.jsx`** — square card, large avatar, name, mutuals, Confirm / Delete buttons (for requests) or Add Friend / Remove (for suggestions).
- [ ] **Step 3: `ReelCard.jsx`** — 9:16 card with gradient bg (deterministic per id), creator avatar overlay top-left, caption bottom, vertical reaction column.
- [ ] **Step 4: `ListingCard.jsx`** — square image, bold price below, title (clamped 2 lines), location below.
- [ ] **Step 5: `Modal.jsx`** — overlay with backdrop click-to-close, ESC handler, max-w + max-h with internal scroll.
- [ ] **Step 6: `EmptyState.jsx`** — centered icon + heading + subtitle.

---

## Phase 8 — Pages

### Task 8.1: Login

**Files:**
- Create: `app/frontend/src/pages/Login.jsx`

- [ ] **Step 1: Build the page** — split-pane matching `login.png`:
  - Left half: gradient bg #f0f2f5, Facebook logo top-left, marketing collage (4 image placeholders arranged like screenshot), "Explore the things you love." headline.
  - Right half: vertically-centered profile card. Loads `/api/users/profiles` to fetch the 3 test accounts; default selection = Haibo Tong (matches screenshot). Shows avatar + name, then `Continue` (opens password prompt for that account), `Use another profile` link (full email+password form), `Create new account` link (→ /register).
  - Bottom: language switcher (text-only).
  - On submit → call `login()` from AuthContext → on success navigate `/`.

### Task 8.2: Register

**Files:**
- Create: `app/frontend/src/pages/Register.jsx`

- [ ] **Step 1: Build the page** matching `create_account.png` — name, email, username, password fields, client-side validation, posts to `/auth/register`, on success navigates `/`.

### Task 8.3: Home

**Files:**
- Create: `app/frontend/src/pages/Home.jsx`
- Create: `app/frontend/src/hooks/useFeed.js`

- [ ] **Step 1: `useFeed.js`** — cursor pagination hook returning `{ posts, loadMore, loading, hasMore }`.
- [ ] **Step 2: `Home.jsx`** — 3-column layout (Sidebar | Center | RightRail) with TopNav above. Center column: RememberPasswordBanner, Composer, "Create story" card, then the feed (PostCard list) with intersection observer for infinite scroll.

### Task 8.4: PostDetail (modal)

**Files:**
- Create: `app/frontend/src/pages/PostDetail.jsx`

- [ ] **Step 1: Build modal page** — uses `<Modal>` from Phase 7. Header "{Author}'s Post" with close X (navigates back). Body: full post content, large image, reactions summary, threaded comment list, sticky `CommentInput` at bottom. Renders over the Home layout (use `location.state.background` pattern or render Home as backdrop).

### Task 8.5: People

**Files:**
- Create: `app/frontend/src/pages/People.jsx`

- [ ] **Step 1: Build page** matching `people.png` — Sidebar + TopNav as on Home. Center: tab strip (Home / Friend Requests / Suggestions / All Friends / Birthdays / Custom Lists) with the tab content as a grid of `FriendCard`s. Each tab hits a different `/api/friends?status=` query.

### Task 8.6: Reels

**Files:**
- Create: `app/frontend/src/pages/Reels.jsx`

- [ ] **Step 1: Build page** matching `reals.png` — full-height vertical-scroll snap container (`scroll-snap-type: y mandatory`) with `ReelCard`s 9:16 centered. Right side column with reaction stack. Top has small sidebar with reel categories (Live / Reels / Saved).

### Task 8.7: Marketplace

**Files:**
- Create: `app/frontend/src/pages/Marketplace.jsx`

- [ ] **Step 1: Build page** matching `marketplace.png` — 3-pane: left filter rail (Categories list, Location combobox, Price range slider, Date listed select), center "Today's picks" grid of `ListingCard`s, right detail drawer that slides in when a card is clicked (seller info, Save, Message Seller buttons).

### Task 8.8: Settings

**Files:**
- Create: `app/frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Build page** matching `settings.png` — left nav with sections (Account, Privacy, Notifications, Security & login, Appearance, Blocking), right panel with the active section's form. Forms hit `PATCH /api/settings`. Sub-routing via `/settings/:section`.

---

## Phase 9 — Docker

### Task 9.1: Backend Dockerfile

**Files:**
- Create: `docker/backend.Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY app/backend/src/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt

COPY app/backend /app
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Task 9.2: Frontend Dockerfile + nginx

**Files:**
- Create: `docker/frontend.Dockerfile`
- Create: `docker/nginx.conf`

- [ ] **Step 1: `frontend.Dockerfile`** (multi-stage)

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY app/frontend/package.json app/frontend/package-lock.json* ./
RUN npm install
COPY app/frontend .
RUN npm run build

FROM nginx:alpine AS prod
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 2: `nginx.conf`**

```nginx
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

### Task 9.3: Compose files

**Files:**
- Create: `docker/docker-compose.yml`
- Create: `docker/docker-compose.dev.yml`

- [ ] **Step 1: `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: fb-db
    environment:
      POSTGRES_DB: facebook
      POSTGRES_USER: fb
      POSTGRES_PASSWORD: fb
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ../app/database/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fb -d facebook"]
      interval: 5s
      timeout: 3s
      retries: 20
    networks:
      - fb_net

  db_init:
    image: postgres:16-alpine
    container_name: fb-db-init
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGHOST: db
      PGPORT: 5432
      PGDATABASE: facebook
      PGUSER: fb
      PGPASSWORD: fb
    volumes:
      - ../app/database/init:/init:ro
    command: ["sh", "-lc", "psql -v ON_ERROR_STOP=1 -f /init/01_schema.sql"]
    restart: "no"
    networks:
      - fb_net

  backend:
    build:
      context: ..
      dockerfile: docker/backend.Dockerfile
    container_name: fb-backend
    environment:
      DATABASE_URL: postgresql+asyncpg://fb:fb@db:5432/facebook
      SESSION_SECRET: dev-secret-change-me
      CORS_ORIGIN: http://localhost:5173
    depends_on:
      db:
        condition: service_healthy
      db_init:
        condition: service_completed_successfully
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)\""]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 20s
    networks:
      - fb_net

  frontend:
    build:
      context: ..
      dockerfile: docker/frontend.Dockerfile
      target: prod
    container_name: fb-frontend
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "5173:80"
    networks:
      - fb_net

volumes:
  postgres_data:

networks:
  fb_net:
    driver: bridge
```

- [ ] **Step 2: `docker-compose.dev.yml`** — overrides backend command to `uvicorn src.main:app --reload --host 0.0.0.0 --port 8000` with bind mount of `../app/backend`, and runs frontend with `npm run dev -- --mode docker` mounting `../app/frontend`.

### Task 9.4: Scripts + README + STRUCTURE.md

**Files:**
- Create: `scripts/start.sh`
- Create: `scripts/reset_db.sh`
- Create: `README.md`
- Create: `STRUCTURE.md`

- [ ] **Step 1: `scripts/start.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker/docker-compose.yml up --build -d
echo "Waiting for backend to be healthy…"
for i in {1..60}; do
  status=$(docker inspect --format='{{.State.Health.Status}}' fb-backend 2>/dev/null || echo "starting")
  if [ "$status" = "healthy" ]; then
    echo "Ready! → http://localhost:5173"
    exit 0
  fi
  sleep 2
done
echo "Backend did not become healthy in time." >&2
exit 1
```

- [ ] **Step 2: `scripts/reset_db.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up --build -d
```

- [ ] **Step 3: `README.md`** — run instructions, the 3 test credentials, architecture diagram, link to STRUCTURE.md.

- [ ] **Step 4: `STRUCTURE.md`** — directory tree with one-line description per file (compressed version of this plan's File Structure section).

---

## Phase 10 — End-to-end verification

### Task 10.1: Smoke run

- [ ] **Step 1: Run** `bash scripts/start.sh`. Wait for healthy.
- [ ] **Step 2: Smoke-test** `curl -fsS http://localhost:8000/health` → `{"ok":true}`.
- [ ] **Step 3: Login from CLI** `curl -c /tmp/cookies -X POST http://localhost:8000/api/auth/login -H 'content-type: application/json' -d '{"email":"haibo@example.com","password":"password123"}'` → returns user JSON.
- [ ] **Step 4: Fetch feed** `curl -b /tmp/cookies http://localhost:8000/api/posts | head -c 400` → returns array of posts.
- [ ] **Step 5: Open browser** at `http://localhost:5173`. Use the verify skill / Playwright to confirm:
  - `/login` matches `login.png` (profile picker visible, "Haibo Tong" preselected)
  - Login with `haibo@example.com / password123` lands on `/`
  - Home shows banner, composer, sidebar, feed, right rail
  - Click a post → PostDetail modal opens
  - Click Friends → People page renders requests + suggestions
  - Click Reels → reels scroll page renders
  - Click Marketplace → grid + filters render
  - Click Settings → settings nav + a form render
- [ ] **Step 6: Visual diff** — for each page, take a screenshot and compare side-by-side to the reference image. Any obvious misses get fixed in a follow-up commit.
- [ ] **Step 7: Test login as viewer** — composer should be disabled, friend-request buttons hidden, listing-create button hidden.

### Task 10.2: Final commit + cleanup

- [ ] **Step 1: `docker compose -f docker/docker-compose.yml down`** (leave volume so seed persists)
- [ ] **Step 2: Verify `git status` is clean** (everything committed during phases)
- [ ] **Step 3: Tag** the working state if desired.

---

## Self-review checklist (run after writing this plan)

- ✅ Spec coverage: every section in `2026-05-21-facebook-web-design.md` is covered by a phase.
- ✅ No HuggingFace references (removed per user request).
- ✅ Types match between phases (e.g. `ReactionType` literal is used identically in `social.py` schemas and `reel.py` schemas).
- ✅ Phase ordering is correct (schema → models → schemas → auth → routes → seed → main → tests → frontend → docker → verify).
- ✅ Each file's responsibility is named once and only once.
- ✅ Test phase tests against a real Postgres (per spec).
