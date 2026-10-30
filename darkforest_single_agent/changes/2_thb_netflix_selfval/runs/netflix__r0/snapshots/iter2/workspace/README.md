# Netflix clone

Multi-profile streaming catalog: FastAPI + Postgres 16 + React/Vite, seeded from
`design/dataset/titles.json` with the real posters, backdrops and trailer clips.

## Run

    docker compose -f docker/docker-compose.yml up --build

- Frontend: http://localhost:3000 (nginx serves the SPA + `/assets`, proxies `/api` and `/auth`)
- Backend:  http://localhost:8000 (`GET /health`)
- Demo account: `demo@netflix.local` / `netflix123` (profiles Demo, Alex, Kids)

## Notes

- Per-profile data (My List, ratings, Continue Watching) is selected with the
  `X-Profile-Id` header; the backend verifies the profile belongs to the token's user.
  Without the header the account's first profile is used.
- `POST /api/titles/{id}/rating` takes `{"value": -1 | 1 | 2 | 0}` (down / up / love / clear — omitting `value` also clears;
  also `"down"`, `"up"`, `"love"`).
- Extra endpoints beyond the contract: `GET /api/me`, `PUT/DELETE /api/profiles/{id}`,
  `PUT /api/my-list/{id}` (move to top; `DELETE /api/my-list/{id}` is idempotent), `POST/DELETE /api/continue-watching`,
  `GET /api/ratings`, `GET /api/languages`, `GET /api/genres/{id}`.
- Kids profiles only see Family / Animation titles.
- The dataset has no runtimes, cast or episode metadata: durations shown are the real
  lengths of the attached clips, series get numbered episodes (only E1 carries the show's
  real synopsis), and there are no games, so the Games page shows an honest empty state.
- Regenerate the seed: `python3 app/database/generate_seed.py design/dataset/titles.json`.
