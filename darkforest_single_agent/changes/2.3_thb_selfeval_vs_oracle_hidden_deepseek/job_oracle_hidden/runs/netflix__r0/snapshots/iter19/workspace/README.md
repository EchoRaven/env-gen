# Netflix Streaming Catalog Clone

## Run

```bash
docker compose -f docker/docker-compose.yml up --build
```

- Frontend: http://localhost:3000 (also available on http://localhost:5173)
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Demo account

- Email: `demo@netflix.com`
- Password: `password123`
- Profiles: Alex, Maya, Little Ones

The catalog is seeded from `design/dataset/titles.json`. Posters, backdrops, icons, fonts, and trailer clips are bundled into both the frontend and backend images, so the stack does not depend on host mounts or external media URLs.

My List, ratings, and Continue Watching use the selected profile (`X-Profile-Id`) and remain private to that profile.
