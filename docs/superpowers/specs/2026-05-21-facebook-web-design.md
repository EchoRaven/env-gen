# facebook-web — Design Spec

**Date:** 2026-05-21
**Output directory:** `env-gen/generated/facebook-web/`
**Reference images:** `env-gen/reference_images/facebook/`

## Goal

Hand-scaffold a runnable Facebook-style social application that follows the env-gen project structure (so it slots into the same Docker / monitor / verification pipeline the LLM generator produces) but is built directly instead of via the multi-agent generator. The app must be visually faithful to the 8 reference screenshots and runnable end-to-end with one Docker Compose command.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS + react-router-dom v6 + axios |
| Backend | FastAPI + SQLAlchemy 2.0 (async) + asyncpg + Pydantic v2 + bcrypt |
| Database | PostgreSQL 16 (separate container) |
| Orchestration | Docker Compose (prod + dev compose files); nginx serves built frontend in prod |
| Tests | pytest (backend); no frontend test framework in v1 |

## Top-level layout

```
facebook-web/
├── app/
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── api/                   # axios client + per-resource modules
│   │   │   ├── components/            # Sidebar, TopNav, PostCard, Composer, etc.
│   │   │   ├── context/AuthContext.jsx
│   │   │   ├── pages/                 # one per route
│   │   │   ├── hooks/
│   │   │   └── styles/
│   │   ├── index.html
│   │   ├── package.json
│   │   └── vite.config.js
│   ├── backend/
│   │   ├── src/
│   │   │   ├── main.py                # FastAPI app entry
│   │   │   ├── db.py                  # async engine + session factory
│   │   │   ├── auth.py                # session-token cookie middleware
│   │   │   ├── models/                # SQLAlchemy ORM
│   │   │   ├── schemas/               # Pydantic
│   │   │   ├── routes/                # auth, users, posts, comments, reactions,
│   │   │   │                          #   friends, reels, marketplace, settings,
│   │   │   │                          #   notifications, messages
│   │   │   ├── deps.py                # FastAPI dependencies (current_user, require_role)
│   │   │   ├── seed.py                # idempotent synthetic seeder
│   │   │   └── seed_content.py        # curated content pools (posts, listings, etc.)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── requirements.txt
│   └── database/
│       └── init/
│           ├── 01_schema.sql          # idempotent CREATE TABLE IF NOT EXISTS
│           └── 02_seed_minimal.sql    # tiny fallback if Python seeder skipped
├── docker/
│   ├── docker-compose.yml             # db + db_init + backend + frontend (nginx)
│   ├── docker-compose.dev.yml         # vite dev server + uvicorn --reload
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── nginx.conf                     # serves built frontend, proxies /api → backend
├── scripts/
│   ├── start.sh                       # one-shot prod up
│   └── reset_db.sh
├── README.md
└── STRUCTURE.md
```

## Auth model

- **Session token in HttpOnly cookie** (`sid`). No JWT. The env-gen template explicitly favors simplicity over crypto correctness for agent-training environments.
- `POST /api/auth/login` → validate creds (bcrypt), insert row into `sessions(id, user_id, expires_at)`, set `Set-Cookie: sid=<uuid>; HttpOnly; SameSite=Lax`.
- `POST /api/auth/logout` → delete session row, clear cookie.
- `POST /api/auth/register` → create user (role=`member`), then call login flow.
- FastAPI dependency `current_user()` reads cookie, looks up session, returns user or 401.
- `require_role("admin")` dependency for admin-only endpoints.

**Test credentials seeded:**
- `admin@example.com / admin123` — role `admin`
- `haibo@example.com / password123` — role `member` (matches the login screenshot's profile)
- `viewer@example.com / viewer123` — role `viewer` (read-only — cannot post, react, send friend requests)

## Data model

Tables (PostgreSQL):

```
users(id pk, email unique, password_hash, name, username unique,
      avatar_url, cover_url, bio, role enum(admin,member,viewer),
      created_at)

sessions(id pk uuid, user_id fk, expires_at, created_at)

friendships(id pk, requester_id fk, addressee_id fk,
            status enum(pending,accepted,blocked),
            created_at, unique(requester_id,addressee_id))

posts(id pk, author_id fk, content text, visibility enum(public,friends,only_me),
      created_at, updated_at)

post_media(id pk, post_id fk, kind enum(image,video), url, order_index)

comments(id pk, post_id fk, author_id fk, parent_comment_id fk null,
         content text, created_at)

reactions(id pk, user_id fk, target_kind enum(post,comment), target_id,
          type enum(like,love,haha,wow,sad,angry),
          unique(user_id,target_kind,target_id))

saved_posts(user_id fk, post_id fk, created_at, pk(user_id,post_id))

reels(id pk, creator_id fk, caption text, media_url,
      thumbnail_url, duration_seconds int, created_at)

reel_reactions(id pk, user_id fk, reel_id fk, type, unique(user_id,reel_id))

marketplace_listings(id pk, seller_id fk, title, description, price_cents int,
                     currency text default 'USD', category text, location text,
                     image_url, status enum(active,sold,archived),
                     created_at)

listing_saves(user_id fk, listing_id fk, created_at, pk(user_id,listing_id))

notifications(id pk, user_id fk, kind, payload jsonb, read boolean,
              created_at)

messages(id pk, sender_id fk, recipient_id fk, body text, read boolean,
         created_at)

user_settings(user_id pk fk, theme enum(light,dark,system),
              language text, notify_email boolean, notify_push boolean,
              profile_visibility enum(public,friends,only_me),
              show_active_status boolean, allow_friend_requests boolean,
              blocked_user_ids jsonb default '[]')
```

All `CREATE TABLE` statements wrapped in `IF NOT EXISTS`; enums created via `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object ... END $$;` so init is idempotent and `db_init` can run on every compose up.

## Pages → reference image mapping

| Route | Reference | Depth | Notes |
|---|---|---|---|
| `/login` | `login.png` | Full | Split-pane: left marketing collage, right profile selector with "Continue", "Use another profile", "Create new account". Pre-fills `Haibo Tong` for visual match (clicks `Continue` → password prompt → home). |
| `/register` | `create_account.png` | Full | Standard signup form, client + server validation, redirects to home on success. |
| `/` (Home) | `home.png` | Full | 3-col: left nav (Friends, Memories, Saved, Groups, Reels, Marketplace, Feeds, Events, Ads Manager), center composer + feed, right contacts/suggestions. Reaction bar, inline comments, share. "Remember Password" dismissible banner at top. |
| `/post/:id` | `post_details.png` | Full | Modal overlay over current page; full post with media, reactions summary, threaded comments, commenter input at bottom. Dismiss returns to previous route. |
| `/friends` | `people.png` | Full | Tabs: Suggestions, Friend Requests, All Friends, Search. Cards with add/remove/mutual count. |
| `/reels` | `reals.png` | Medium | Vertical scroll of reel cards (placeholder gradient backgrounds + creator avatar — no real video playback in v1). Right-side reaction column. |
| `/marketplace` | `marketplace.png` | Medium | Grid + left sidebar with category/price/location filters. Click → detail drawer with seller info and Save/Contact buttons. |
| `/settings` | `settings.png` | Medium | Sidebar nav: Account, Privacy, Notifications, Security, Appearance, Blocking. Forms persist to `user_settings`. |

## Role-based behavior

- **admin**: can delete any post/comment/listing; can see `/admin/users` page (out of v1 scope but endpoint stub exists).
- **member**: standard user — post, react, comment, send friend requests, create listings.
- **viewer**: read-only. Composer disabled, reaction/comment buttons disabled with tooltip, "Add friend" buttons hidden, "Create listing" button hidden. Backend returns 403 if a viewer tries the action via API.

## Seed data — fully synthetic

The seeder (`backend/src/seed.py`) is idempotent (only runs if `users` table is empty). All data is generated locally so the app boots without network access.

1. **Users** (~50) via Faker — name, username, email, avatar from `https://i.pravatar.cc/150?u=<username>` (deterministic per username), bio paragraph. Includes the 3 fixed test accounts.
2. **Posts** (~300) — content from a curated pool of ~80 hand-written social-style post templates (`"Just got back from {place} and I have to say..."`, `"Hot take: {opinion}"`, status updates, life events, food pics) combined with Faker fillers. ~30% have an attached image URL pointing to `https://picsum.photos/seed/<post_id>/800/600` (deterministic placeholder service — no upload, just URLs). Posts spread across the past 30 days for a believable feed.
3. **Comments** (~3 per post) — Faker sentence + emoji injection from a small pool, optional `@mentions` of friends.
4. **Reactions** — random distribution across the 6 types, biased toward `like` (60% like, 15% love, 10% haha, 5% wow, 5% sad, 5% angry).
5. **Reels** (~80) — caption from a curated pool, "video" represented by a gradient placeholder (CSS-generated client-side, seeded by reel id) + creator overlay; `duration_seconds` random 7-60.
6. **Marketplace listings** (~120) — title and description from a curated pool grouped by category (Electronics, Furniture, Vehicles, Clothing, Home & Garden, Hobbies, Free Stuff), price randomized within category-appropriate ranges, image from `https://picsum.photos/seed/listing-<id>/600/600`, location from a fixed list of 20 US cities.
7. **Friendships** — each user gets 5-20 random accepted friendships + a few pending requests targeting the 3 test accounts (so the Friend Requests tab has content on first login).
8. **Notifications & messages** — ~5 each for the 3 test accounts.

The curated content pools live in `app/backend/src/seed_content.py` so they're easy to extend.

## API surface (REST, JSON, prefixed `/api`)

```
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/users/profiles            # for login screen profile picker
GET    /api/users/:id
PATCH  /api/users/me                  # update profile

GET    /api/posts                     # ?cursor=&limit= feed (friends + own)
POST   /api/posts                     # member+
GET    /api/posts/:id
DELETE /api/posts/:id                 # author or admin
POST   /api/posts/:id/save            # toggle
GET    /api/posts/saved

GET    /api/posts/:id/comments
POST   /api/posts/:id/comments
DELETE /api/comments/:id              # author or admin

POST   /api/reactions                 # body: {target_kind, target_id, type}; toggle/replace
DELETE /api/reactions                 # remove

GET    /api/friends                   # ?status=accepted|pending|incoming
POST   /api/friends/request           # body: {user_id}
POST   /api/friends/:id/accept
DELETE /api/friends/:id               # decline/unfriend
GET    /api/friends/suggestions

GET    /api/reels                     # paginated
POST   /api/reels/:id/react

GET    /api/marketplace               # ?category=&min_price=&max_price=&location=&q=
GET    /api/marketplace/:id
POST   /api/marketplace               # member+
POST   /api/marketplace/:id/save      # toggle

GET    /api/notifications
PATCH  /api/notifications/:id         # mark read

GET    /api/messages                  # threads with each contact
POST   /api/messages                  # send

GET    /api/settings
PATCH  /api/settings

GET    /health                        # for compose healthcheck
```

## Docker layout

`docker/docker-compose.yml` services:

- `db` — postgres:16-alpine, healthcheck via `pg_isready`, named volume `postgres_data`.
- `db_init` — postgres:16-alpine one-shot. Depends on `db: service_healthy`. Runs only `psql -v ON_ERROR_STOP=1 -f /init/01_schema.sql`. The Python seeder runs from inside the backend container on startup, gated by an "is users table empty?" check (so it's idempotent across restarts). `02_seed_minimal.sql` is unused in normal operation and exists only as a manual fallback if you want to bring up the DB without the backend.
- `backend` — built from `docker/backend.Dockerfile` (python:3.11-slim + uvicorn). Depends on `db: service_healthy` and `db_init: service_completed_successfully`. Env: `DATABASE_URL=postgresql+asyncpg://fb:fb@db:5432/facebook`, `SESSION_SECRET`. Healthcheck hits `/health`.
- `frontend` — built from `docker/frontend.Dockerfile` (multi-stage: node build + nginx serve). Depends on `backend: service_healthy`. nginx config proxies `/api/*` → `http://backend:8000`. Published on host port `5173:80`.

Dev compose mounts source and runs `uvicorn --reload` + `vite --host`.

## Tests (backend, pytest)

Minimal but real coverage on the auth + core domain paths:

- `test_auth.py` — register, login sets cookie, logout clears, /me returns user, 401 without cookie.
- `test_posts.py` — member can create post; viewer gets 403; feed returns own + friends' posts; delete by author works; delete by stranger 403; delete by admin works.
- `test_reactions.py` — toggle reaction, switch reaction type, unique constraint.
- `test_friends.py` — request → accept flow, decline, suggestions exclude existing friends.
- `test_marketplace.py` — create listing (member), filter by category/price range.
- `test_permissions.py` — viewer cannot mutate; admin can delete others' content.

Backend tests run against a separate postgres test DB spun up via a `pytest` fixture or against `TESTING=1 sqlite` if we want zero-infra (decision: use a `docker compose -f docker/docker-compose.test.yml` postgres so we test against the real engine).

## What's intentionally NOT in v1

Calling these out so they don't sneak into scope:

- Real video playback for reels (placeholder gradient cards only)
- Real-time chat / WebSocket — `messages` table exists, REST endpoints exist, no chat UI page
- Stories carousel (the data model has no `stories` table)
- Mobile-first / mobile-specific layouts (desktop-first; Tailwind responsive helpers but designed at 1280px)
- File uploads — `avatar_url`, `cover_url`, `post_media.url` accept URL strings; no upload endpoint
- Email sending / OAuth / 2FA
- Frontend tests (Vitest setup deferred)
- Admin moderation UI (admin endpoints exist; UI page is a stub)

## Run command

```bash
cd env-gen/generated/facebook-web
docker compose -f docker/docker-compose.yml up --build
# → frontend:  http://localhost:5173
# → backend:   http://localhost:8000
# → postgres:  localhost:5432  (db=facebook user=fb pass=fb)
```

First boot takes ~30s for the synthetic seeder to populate the DB. Subsequent boots skip the seeder (idempotent check on `users` count).
