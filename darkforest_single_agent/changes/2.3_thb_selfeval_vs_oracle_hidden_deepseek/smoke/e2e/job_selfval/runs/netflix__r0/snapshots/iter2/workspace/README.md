# Netflix catalog clone

A full-stack, multi-profile Netflix-style streaming catalog built from the supplied reference
design and dataset.

## Run

```bash
docker compose -f docker/docker-compose.yml up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Health: http://localhost:8000/health

Demo account: `demo@netflix.com` / `demo123`

The database initializes from `app/database/init/01_schema.sql` and `02_seed.sql`. The demo
account has three private profiles (Alex, Jordan, Kids), each with its own My List, ratings,
and Continue Watching data. New accounts also get a starter profile automatically.

## Stack

- FastAPI + SQLAlchemy + PostgreSQL 16
- React 18 + Vite 5, served by nginx in production
- Bearer-token authentication with PBKDF2 password hashing
- Per-profile data scoping through the active profile selected in the UI
