"""forgingground-gen backend — env/run registry (DB) + live collaboration-hub
state (read from each generated environment). Serves the agentsuite-red Env Forge
UI under ``/env-forge/*``. No hardcoded data: the registry is persisted in the DB
and per-env state is read live from disk.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8095
Env:  DATABASE_URL (default sqlite), ENVS_ROOT (where generated envs live).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import hub_reader
from .db import get_db, init_db, SessionLocal
from .models import Environment, ChatMessage

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", str(Path(__file__).resolve().parents[1] / "generated")))

app = FastAPI(title="forgingground-gen", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class EnvCreate(BaseModel):
    name: str
    reference: str
    model: str
    provider: str
    scope: str | None = None
    requirements: str | None = None
    max_wallclock_min: int = 120
    max_ticks: int = 240
    gates: list[dict] = []


class RefUpload(BaseModel):
    files: list[dict] = []  # [{filename, content_b64}]


def _is_env_dir(p: Path) -> bool:
    return p.is_dir() and (p / "shared" / "hubs").is_dir()


def _sync_envs(db: Session) -> None:
    """Register any generated env on disk that isn't in the registry yet.
    The DB owns env metadata; disk is the source of truth for what exists."""
    if not ENVS_ROOT.is_dir():
        return
    known = {e.id for e in db.scalars(select(Environment)).all()}
    for d in sorted(ENVS_ROOT.iterdir()):
        if not _is_env_dir(d) or d.name in known:
            continue
        db.add(Environment(id=d.name, name=d.name, generated_dir=str(d.resolve()),
                            reference="", model="", status="completed"))
    db.commit()


def _env_to_dict(e: Environment) -> dict:
    summ = hub_reader.env_summary(e.generated_dir) if e.generated_dir else {}
    return {
        "id": e.id, "name": e.name, "reference": e.reference, "model": e.model,
        "requirements": e.requirements or "",
        "status": summ.get("status", e.status),
        "pages": summ.get("pages", 0), "endpoints": summ.get("endpoints", 0),
        "visual_score": summ.get("visual_score"),
        "delivered": summ.get("delivered", e.delivered),
        "run_count": summ.get("run_count", 0),
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "updated_at": e.updated_at.isoformat() if e.updated_at else "",
    }


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with SessionLocal() as db:
        _sync_envs(db)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "envs_root": str(ENVS_ROOT), "exists": ENVS_ROOT.is_dir()}


@app.get("/env-forge/environments")
def list_environments(db: Session = Depends(get_db)) -> list[dict]:
    _sync_envs(db)
    envs = db.scalars(select(Environment)).all()
    return sorted((_env_to_dict(e) for e in envs), key=lambda x: x["updated_at"], reverse=True)


@app.post("/env-forge/environments")
def create_environment(body: EnvCreate, db: Session = Depends(get_db)) -> dict:
    if db.get(Environment, body.name):
        raise HTTPException(409, f"environment '{body.name}' already exists")
    import json as _json
    gen = ENVS_ROOT / body.name
    e = Environment(id=body.name, name=body.name, reference=body.reference,
                    model=body.model, provider=body.provider, scope=body.scope or "",
                    requirements=body.requirements or "", max_wallclock_min=body.max_wallclock_min,
                    max_ticks=body.max_ticks, gates_json=_json.dumps(body.gates or []),
                    status="generating", generated_dir=str(gen.resolve()))
    db.add(e)
    db.commit()
    # TODO: kick off the generation pipeline (forgingground-gen run) as a job here,
    # honoring requirements / model / provider / budget / gates / staged references.
    return _env_to_dict(e)


@app.post("/env-forge/environments/{env_id}/references")
def upload_references(env_id: str, body: RefUpload, db: Session = Depends(get_db)) -> dict:
    """Stage reference images/docs into the env's design/references dir (created if
    absent) so the generation picks them up. Best-effort base64 decode."""
    import base64
    e = _get_env(db, env_id)
    dest = Path(e.generated_dir) / "design" / "references"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in body.files:
        name = str(f.get("filename") or "").strip()
        b64 = f.get("content_b64") or ""
        if not name or not b64:
            continue
        try:
            raw = b64.split(",", 1)[1] if "," in b64 else b64  # strip data: prefix
            (dest / name).write_bytes(base64.b64decode(raw))
            saved.append(name)
        except Exception:
            continue
    return {"saved": saved, "dir": str(dest)}


def _get_env(db: Session, env_id: str) -> Environment:
    e = db.get(Environment, env_id)
    if not e:
        raise HTTPException(404, f"environment '{env_id}' not found")
    return e


@app.get("/env-forge/environments/{env_id}")
def get_environment(env_id: str, db: Session = Depends(get_db)) -> dict:
    return _env_to_dict(_get_env(db, env_id))


@app.get("/env-forge/environments/{env_id}/runs")
def get_runs(env_id: str, db: Session = Depends(get_db)) -> list[dict]:
    e = _get_env(db, env_id)
    return hub_reader.list_runs(e.generated_dir, env_id) if e.generated_dir else []


@app.get("/env-forge/environments/{env_id}/state")
def get_state(env_id: str, db: Session = Depends(get_db)) -> dict:
    e = _get_env(db, env_id)
    if not e.generated_dir or not Path(e.generated_dir).is_dir():
        raise HTTPException(404, "generated tree not found for this environment")
    return hub_reader.read_state(e.generated_dir)


_FILE_SKIP = {"node_modules", "__pycache__", ".git", ".agent_logs", "dist",
              ".pytest_cache", "worktrees", ".venv", "logs"}


@app.get("/env-forge/environments/{env_id}/files")
def get_files(env_id: str, path: str = "", db: Session = Depends(get_db)) -> dict:
    """Browse the generated env's source tree: list a directory, or return a text
    file's content. Path-traversal-guarded to the env's generated_dir."""
    e = _get_env(db, env_id)
    if not e.generated_dir or not Path(e.generated_dir).is_dir():
        raise HTTPException(404, "generated tree not found")
    root = Path(e.generated_dir).resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, "path outside environment")
    if target.is_dir():
        entries = []
        for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in _FILE_SKIP or p.name.startswith("."):
                continue
            entries.append({"name": p.name, "path": str(p.relative_to(root)),
                            "is_dir": p.is_dir(),
                            "size": p.stat().st_size if p.is_file() else 0})
        return {"dir": "" if target == root else str(target.relative_to(root)), "entries": entries}
    if target.is_file():
        if target.stat().st_size > 400_000:
            raise HTTPException(413, "file too large to preview")
        try:
            text = target.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            raise HTTPException(415, "not a text file")
        return {"file": str(target.relative_to(root)), "content": text}
    raise HTTPException(404, "not found")


class ChatSend(BaseModel):
    content: str
    recipients: list[str] = []
    thread_id: str = "main"


def _chat_to_dict(m: ChatMessage) -> dict:
    return {"id": m.id, "thread_id": m.thread_id, "sender": m.sender,
            "recipients": [r for r in (m.recipients or "").split(",") if r],
            "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else ""}


@app.get("/env-forge/environments/{env_id}/chat")
def list_chat(env_id: str, db: Session = Depends(get_db)) -> list[dict]:
    _get_env(db, env_id)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.env_id == env_id)).all()
    return [_chat_to_dict(m) for m in sorted(msgs, key=lambda x: x.id)]


@app.post("/env-forge/environments/{env_id}/chat")
def send_chat(env_id: str, body: ChatSend, db: Session = Depends(get_db)) -> dict:
    _get_env(db, env_id)
    m = ChatMessage(env_id=env_id, thread_id=body.thread_id, sender="user",
                    recipients=",".join(body.recipients), content=body.content)
    db.add(m)
    db.commit()
    db.refresh(m)
    # TODO: when the generation pipeline is live, dispatch this to the selected
    # agents' chat mini-loop and persist their replies as sender=<agent_id>.
    return _chat_to_dict(m)
