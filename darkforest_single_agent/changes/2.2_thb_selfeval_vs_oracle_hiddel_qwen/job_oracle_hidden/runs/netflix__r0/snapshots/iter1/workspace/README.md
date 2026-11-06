# Netflix Clone — full-stack multi-profile streaming catalog

Pixel-faithful Netflix clone: FastAPI + Postgres 16 + React/Vite, seeded from the real
`design/dataset/titles.json` catalog with the real posters, backdrops, trailer clips,
logo, icon set and fonts.

## Run

```bash
cd docker
docker compose up --build -d
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000  (`/health`, OpenAPI docs at `/docs`)
- Postgres: localhost:5432 (netflix/netflix)

## Demo account

- Email: `demo@netflix.example`
- Password: `demo1234`
- Profiles: Alex, Priya, Kids (each with its own My List / ratings / Continue Watching)

## Layout

- `docker/docker-compose.yml` — services `database`, `backend`, `frontend`
- `app/backend/` — FastAPI app (auth/JWT, all 17 contract endpoints, media serving)
- `app/frontend/` — React app (`src/pages/` = one component per screen)
- `app/database/init/` — Postgres schema + seed (generated from the dataset via `tools/gen_seed.py`)
- `app/assets/` — real assets (posters, backdrops, video clips, brand, icons, fonts)
- `tools/` — seed generator + local smoke/E2E test scripts

## Contract endpoints

POST /auth/register · POST /auth/login ·
GET/POST /api/profiles · GET /api/titles · GET /api/titles/{id} · GET /api/titles/{id}/episodes ·
GET /api/titles/trending · GET /api/titles/top10 · GET /api/genres · GET /api/genres/{id}/titles ·
GET /api/search · GET/POST /api/my-list · DELETE /api/my-list/{id} ·
POST /api/titles/{id}/rating · GET /api/continue-watching

All `/api/*` routes require `Authorization: Bearer <token>` (401 otherwise). Per-profile
private data (My List, ratings, Continue Watching) is selected via the `X-Profile-Id`
header, falling back to the user's first profile.
