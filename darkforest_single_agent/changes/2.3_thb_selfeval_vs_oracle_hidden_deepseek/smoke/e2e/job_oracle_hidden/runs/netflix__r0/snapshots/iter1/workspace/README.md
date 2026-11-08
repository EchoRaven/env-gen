# Netflix catalog clone

Run from this repository:

```bash
docker compose -f docker/docker-compose.yml up --build
```

- Frontend: http://localhost:5173
- API + health: http://localhost:8000/health
- Demo account: `demo@netflix.com` / `password123`

The database is seeded from the supplied real catalog (60 titles), artwork, and trailer clips.
My List, ratings, and Continue Watching are scoped to the selected profile through the
`X-Profile-Id` header (or a `profile_id` field for API clients).
