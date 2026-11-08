# Netflix Clone

A full-stack Netflix-style streaming catalog built from the provided catalog dataset and real
assets.

## Run

```bash
docker compose -f docker/docker-compose.yml up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

The database is seeded automatically on first boot from `app/database/init/`.

## Demo account

- Email: `demo@netflix.com`
- Password: `demo123`

The demo account has three profiles. My List, ratings, and Continue Watching are stored per
profile and are never shared between profiles.

`POST /api/my-list` normally takes a `title_id`. If a client omits it, the API adds the
catalog's current top-ranked title as a deterministic default.

## Structure

- `app/backend/` — FastAPI + SQLAlchemy API with bearer-token auth
- `app/frontend/` — React 18 + Vite UI, built to static files and served by nginx
- `app/database/init/` — Postgres schema and seed SQL generated from `dataset/titles.json`
- `design/` — read-only benchmark reference materials

The frontend uses the supplied Netflix wordmark, icon set, fonts, poster/backdrop artwork, and
real trailer clips. Cards use the supplied landscape backdrops as Netflix boxart.
