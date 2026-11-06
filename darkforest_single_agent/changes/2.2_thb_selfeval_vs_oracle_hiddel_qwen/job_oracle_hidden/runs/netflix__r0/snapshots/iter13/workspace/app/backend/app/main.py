import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import auth, continue_watching, genres, mylist, profiles, search, titles

app = FastAPI(title="Netflix Clone API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "netflix-clone-backend"}


@app.get("/")
def root():
    return {"service": "netflix-clone-backend", "docs": "/docs", "health": "/health"}


app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(titles.router)
app.include_router(genres.router)
app.include_router(search.router)
app.include_router(mylist.router)
app.include_router(continue_watching.router)

MEDIA_DIR = os.environ.get("MEDIA_DIR", "/app/media")
if os.path.isdir(MEDIA_DIR):
    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
else:
    @app.get("/media/{path:path}")
    def media_fallback(path: str):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="media not mounted")
