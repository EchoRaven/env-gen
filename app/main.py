"""forgingground-gen backend — env/run registry (DB) + live collaboration-hub
state (read from each generated environment). Serves the agentsuite-red Env Forge
UI under ``/env-forge/*``. No hardcoded data: the registry is persisted in the DB
and per-env state is read live from disk.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8095
Env:  DATABASE_URL (default sqlite), ENVS_ROOT (where generated envs live).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import approval_bridge, chat_bridge, hub_reader
from .auth import AuthContext, assert_env_access, current_admin, scope_query
from .db import get_db, init_db, SessionLocal
# NB: ChatMessage table is retained in models.py but no longer read/written here —
# chat now sources truth from the live EventHub via chat_bridge.
from .models import Environment, GenerationTask, record_status

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", str(Path(__file__).resolve().parents[1] / "generated")))

# Env names double as the on-disk directory + PK + URL segment — keep them to a
# strict slug so they can never traverse paths or collide with route parsing.
_SAFE_ENV_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# CORS origins are configurable so prod can restrict to the known UI origin(s);
# default "*" for local dev. (Auth is header-based, so this is defence in depth.)
_CORS_ORIGINS = [o.strip() for o in os.environ.get("AGENTSUITE_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]

app = FastAPI(title="forgingground-gen", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
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


def _within_envs_root(p: Path) -> bool:
    """Defence in depth: a resolved path must live inside ENVS_ROOT before we
    ever read/serve from it, regardless of what generated_dir was stored."""
    root = ENVS_ROOT.resolve()
    p = p.resolve()
    return p == root or root in p.parents


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
    try:  # cheap glob of the approvals store so the env LIST can flag a paused agent
        pending = len(approval_bridge.list_requests(e.generated_dir, "pending")) if e.generated_dir else 0
    except Exception:
        pending = 0
    return {
        "id": e.id, "name": e.name, "reference": e.reference, "model": e.model,
        "requirements": e.requirements or "",
        "status": summ.get("status", e.status),
        "pages": summ.get("pages", 0), "endpoints": summ.get("endpoints", 0),
        "visual_score": summ.get("visual_score"),
        "delivered": summ.get("delivered", e.delivered),
        "run_count": summ.get("run_count", 0),
        "pending_approvals": pending,
        "created_at": e.created_at.isoformat() if e.created_at else "",
        # LIVE updated_at: the DB row's timestamp is written once at registration and never
        # again, so an ACTIVE CLI run (hubs rewritten every few seconds) sorted to the
        # BOTTOM of the list under a weeks-old date — invisible in practice (2026-07-02:
        # run-40 at 78% progress sat at position 31/34 under updated_at=06-22). Use the
        # newest hub-store write when it beats the DB column.
        "updated_at": _live_updated_at(e),
    }


def _live_updated_at(e: Environment) -> str:
    # Normalize the DB value to NAIVE UTC before comparing: sqlite round-trips
    # the aware column default as naive UTC already, but Postgres TIMESTAMPTZ
    # returns an AWARE datetime in the session tz — its isoformat carries an
    # offset suffix, so a lexical max against a naive string compares
    # wall-clock digits and can pick the WRONG value (and the endpoint would
    # emit mixed formats).
    from datetime import datetime as _dt, timezone as _tz
    db_dt = e.updated_at
    if db_dt is not None and db_dt.tzinfo is not None:
        db_dt = db_dt.astimezone(_tz.utc).replace(tzinfo=None)
    db_iso = db_dt.isoformat() if db_dt else ""
    try:
        if not e.generated_dir:
            return db_iso
        hubs = Path(e.generated_dir) / "shared" / "hubs"
        mtime = hub_reader._hub_mtime(hubs)
        if not mtime:
            return db_iso
        # The hub mtime is rendered the same NAIVE-UTC way, else a local-time
        # render (UTC-5 here) always loses the string max to any boot-touched row.
        live_iso = _dt.utcfromtimestamp(mtime).isoformat()
        return max(db_iso, live_iso)
    except Exception:
        return db_iso


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with SessionLocal() as db:
        _sync_envs(db)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "envs_root": str(ENVS_ROOT), "exists": ENVS_ROOT.is_dir()}


@app.get("/env-forge/environments")
def list_environments(db: Session = Depends(get_db),
                      user: AuthContext = Depends(current_admin)) -> list[dict]:
    _sync_envs(db)
    stmt = scope_query(select(Environment), Environment.tenant_id, user)
    envs = db.scalars(stmt).all()
    return sorted((_env_to_dict(e) for e in envs), key=lambda x: x["updated_at"], reverse=True)


@app.post("/env-forge/environments")
def create_environment(body: EnvCreate, db: Session = Depends(get_db),
                       user: AuthContext = Depends(current_admin)) -> dict:
    # The name is the PK *and* the on-disk directory name — sanitize hard so it
    # can never become a path-traversal vector (e.g. '../other-tenant-env').
    name = (body.name or "").strip()
    if not _SAFE_ENV_NAME.match(name):
        raise HTTPException(400, "invalid environment name: use letters, digits, '-' or '_' "
                                 "(1-64 chars, must start alphanumeric, no path separators)")
    gen = (ENVS_ROOT / name).resolve()
    if gen != ENVS_ROOT.resolve() and ENVS_ROOT.resolve() not in gen.parents:
        raise HTTPException(400, "invalid environment name")
    if db.get(Environment, name):
        raise HTTPException(409, f"environment '{name}' already exists")
    import json as _json
    e = Environment(id=name, name=name, reference=body.reference,
                    model=body.model, provider=body.provider, scope=body.scope or "",
                    requirements=body.requirements or "", max_wallclock_min=body.max_wallclock_min,
                    max_ticks=body.max_ticks, gates_json=_json.dumps(body.gates or []),
                    status="generating", generated_dir=str(gen),
                    tenant_id=user.tenant_id, created_by=user.user_id)
    db.add(e)
    # Record this generation as a GenerationTask (the per-attempt registry row).
    # NOTE: still one dir per name today; the per-task-dir cutover is a follow-up
    # (see docs/superpowers/specs/2026-06-17-generation-task-db-redesign.md).
    import uuid as _uuid
    task = GenerationTask(
        task_id=str(_uuid.uuid4()), env_id=e.id, tenant_id=e.tenant_id,
        created_by=e.created_by, name=e.name, project_path=str(gen),
        state_path=str(gen) + "/.checkpoint", status="generating",
        reference=e.reference, model=e.model, provider=e.provider,
        scope=e.scope, requirements=e.requirements, gates_json=e.gates_json,
        max_wallclock_min=e.max_wallclock_min, max_ticks=e.max_ticks,
    )
    record_status(task, "generating", "env created")
    db.add(task)
    e.current_task_id = task.task_id
    db.commit()
    # TODO: kick off the generation pipeline (forgingground-gen run) as a job here,
    # honoring requirements / model / provider / budget / gates / staged references.
    return _env_to_dict(e)


@app.post("/env-forge/environments/{env_id}/references")
def upload_references(env_id: str, body: RefUpload, db: Session = Depends(get_db),
                      user: AuthContext = Depends(current_admin)) -> dict:
    """Stage reference images/docs into the env's design/references dir (created if
    absent) so the generation picks them up. Best-effort base64 decode."""
    import base64
    e = _get_env(db, env_id, user)
    dest = Path(e.generated_dir) / "design" / "references"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    dest_root = dest.resolve()
    for f in body.files:
        name = str(f.get("filename") or "").strip()
        b64 = f.get("content_b64") or ""
        if not name or not b64:
            continue
        # NEVER trust the supplied filename as a path: a value like
        # '../../other-tenant-env/x' would escape into a sibling env (a
        # cross-tenant write). Use the basename only, then clamp the resolved
        # destination inside the references dir as defence in depth.
        safe = Path(name).name
        if not safe or safe in (".", ".."):
            continue
        out = (dest / safe).resolve()
        if out.parent != dest_root:
            continue
        try:
            raw = b64.split(",", 1)[1] if "," in b64 else b64  # strip data: prefix
            out.write_bytes(base64.b64decode(raw))
            saved.append(safe)
        except Exception:
            continue
    return {"saved": saved, "dir": str(dest)}


def _get_env(db: Session, env_id: str, auth: AuthContext) -> Environment:
    """Fetch an env, enforcing tenant ownership (404 on missing or cross-tenant
    so we never reveal that another tenant's environment exists)."""
    return assert_env_access(db.get(Environment, env_id), auth)


@app.get("/env-forge/environments/{env_id}")
def get_environment(env_id: str, db: Session = Depends(get_db),
                    user: AuthContext = Depends(current_admin)) -> dict:
    return _env_to_dict(_get_env(db, env_id, user))


@app.get("/env-forge/environments/{env_id}/runs")
def get_runs(env_id: str, db: Session = Depends(get_db),
             user: AuthContext = Depends(current_admin)) -> list[dict]:
    e = _get_env(db, env_id, user)
    return hub_reader.list_runs(e.generated_dir, env_id) if e.generated_dir else []


@app.get("/env-forge/environments/{env_id}/state")
def get_state(env_id: str, db: Session = Depends(get_db),
              user: AuthContext = Depends(current_admin)) -> dict:
    e = _get_env(db, env_id, user)
    if not e.generated_dir or not Path(e.generated_dir).is_dir():
        raise HTTPException(404, "generated tree not found for this environment")
    return hub_reader.read_state(e.generated_dir)


_FILE_SKIP = {"node_modules", "__pycache__", ".git", ".agent_logs", "dist",
              ".pytest_cache", "worktrees", ".venv", "logs"}


@app.get("/env-forge/environments/{env_id}/files")
def get_files(env_id: str, path: str = "", db: Session = Depends(get_db),
              user: AuthContext = Depends(current_admin)) -> dict:
    """Browse the generated env's source tree: list a directory, or return a text
    file's content. Path-traversal-guarded to the env's generated_dir."""
    e = _get_env(db, env_id, user)
    if not e.generated_dir or not Path(e.generated_dir).is_dir():
        raise HTTPException(404, "generated tree not found")
    root = Path(e.generated_dir).resolve()
    if not _within_envs_root(root):
        raise HTTPException(404, "generated tree not found")
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


@app.get("/env-forge/environments/{env_id}/references/{name}")
def get_reference_file(env_id: str, name: str, db: Session = Depends(get_db),
                       user: AuthContext = Depends(current_admin)):
    """Serve a staged reference file (screenshot/doc) from the env's design/references."""
    e = _get_env(db, env_id, user)
    if not e.generated_dir:
        raise HTTPException(404, "not found")
    root = Path(e.generated_dir).resolve()
    if not _within_envs_root(root):
        raise HTTPException(404, "not found")
    for sub in ("design/references", "design/reference_images"):
        f = (root / sub / name).resolve()
        if root in f.parents and f.is_file():
            return FileResponse(str(f))
    raise HTTPException(404, "reference not found")


class SkillCreate(BaseModel):
    name: str
    body: str = ""


@app.post("/env-forge/environments/{env_id}/skills")
def add_skill(env_id: str, body: SkillCreate, db: Session = Depends(get_db),
              user: AuthContext = Depends(current_admin)) -> dict:
    """Create a skill: write .agents/skills/<name>/SKILL.md so the runtime + UI see it."""
    e = _get_env(db, env_id, user)
    if not e.generated_dir:
        raise HTTPException(404, "not found")
    safe = re.sub(r"[^a-z0-9_-]", "-", body.name.strip().lower()).strip("-")[:60] or "skill"
    d = Path(e.generated_dir) / ".agents" / "skills" / safe
    d.mkdir(parents=True, exist_ok=True)
    content = body.body.strip() or f"---\nname: {body.name}\ndescription: \n---\n"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return {"ok": True, "name": safe}


class GateCreate(BaseModel):
    name: str
    detail: str = ""


def _custom_gates_file(generated_dir: str) -> Path:
    return Path(generated_dir) / "design" / "custom_gates.json"


def _read_custom_gates(p: Path) -> list:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


@app.post("/env-forge/environments/{env_id}/gates")
def add_gate(env_id: str, body: GateCreate, db: Session = Depends(get_db),
             user: AuthContext = Depends(current_admin)) -> dict:
    """Create/update a user-defined custom gate (design/custom_gates.json)."""
    e = _get_env(db, env_id, user)
    if not e.generated_dir:
        raise HTTPException(404, "not found")
    p = _custom_gates_file(e.generated_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    gates = [g for g in _read_custom_gates(p) if g.get("name") != body.name]
    gates.append({"name": body.name, "detail": body.detail, "status": "manual"})
    p.write_text(json.dumps(gates, indent=2), encoding="utf-8")
    return {"ok": True}


@app.delete("/env-forge/environments/{env_id}/gates/{name}")
def delete_gate(env_id: str, name: str, db: Session = Depends(get_db),
                user: AuthContext = Depends(current_admin)) -> dict:
    e = _get_env(db, env_id, user)
    if not e.generated_dir:
        raise HTTPException(404, "not found")
    p = _custom_gates_file(e.generated_dir)
    gates = [g for g in _read_custom_gates(p) if g.get("name") != name]
    p.write_text(json.dumps(gates, indent=2), encoding="utf-8")
    return {"ok": True}


class ChatSend(BaseModel):
    content: str
    recipients: list[str] = []
    thread_id: str = "main"


class ApprovalModeSet(BaseModel):
    mode: str  # "auto" | "ask"


class ApprovalDecision(BaseModel):
    approve: bool
    feedback: str = ""


@app.get("/env-forge/environments/{env_id}/chat")
def list_chat(env_id: str, thread_id: str | None = None, db: Session = Depends(get_db),
              user: AuthContext = Depends(current_admin)) -> list[dict]:
    """Chat transcript — sourced from the LIVE generation's EventHub (human
    messages + agent replies), not the local ChatMessage table. ``thread_id``
    scopes to one conversation; omit it to flatten across every conversation."""
    e = _get_env(db, env_id, user)
    try:
        return chat_bridge.list_messages(e.generated_dir, thread_id=thread_id,
                                         default_user_id=user.user_id)
    except chat_bridge.ChatBridgeError:
        # No hub yet (generation not started) — nothing to show, not an error.
        return []


@app.post("/env-forge/environments/{env_id}/chat")
def send_chat(env_id: str, body: ChatSend, db: Session = Depends(get_db),
              user: AuthContext = Depends(current_admin)) -> dict:
    """Dispatch a human message to the running agents via the env's EventHub
    (HumanConsole). ``from_user`` is the authed admin's id so the 4.7 gate
    accepts it and agents address replies to the right person."""
    e = _get_env(db, env_id, user)
    try:
        return chat_bridge.send(
            e.generated_dir,
            content=body.content,
            recipients=body.recipients,
            thread_id=body.thread_id,
            from_user=user.user_id,
        )
    except chat_bridge.ChatBridgeError as exc:
        raise HTTPException(400, str(exc))


# ── Human-in-the-loop approval (Claude-Code-style permission modes) ──────────
@app.get("/env-forge/environments/{env_id}/approval-mode")
def get_approval_mode(env_id: str, db: Session = Depends(get_db),
                      user: AuthContext = Depends(current_admin)) -> dict:
    """Current approval mode for the env: auto (autonomous) or ask (gate
    structural decisions for human approval)."""
    e = _get_env(db, env_id, user)
    return approval_bridge.get_mode(e.generated_dir)


@app.put("/env-forge/environments/{env_id}/approval-mode")
def set_approval_mode(env_id: str, body: ApprovalModeSet, db: Session = Depends(get_db),
                      user: AuthContext = Depends(current_admin)) -> dict:
    """Flip the env between auto and ask. In ask mode the engine pauses gated
    actions (task/gate creation) until approved here."""
    e = _get_env(db, env_id, user)
    try:
        return approval_bridge.set_mode(e.generated_dir, body.mode)
    except approval_bridge.ApprovalBridgeError as exc:
        raise HTTPException(400, str(exc))


@app.get("/env-forge/environments/{env_id}/approvals")
def list_approvals(env_id: str, status: str | None = None, db: Session = Depends(get_db),
                   user: AuthContext = Depends(current_admin)) -> list[dict]:
    """Approval requests for the env (optionally filtered by status, e.g.
    'pending'). Newest last."""
    e = _get_env(db, env_id, user)
    return approval_bridge.list_requests(e.generated_dir, status)


@app.post("/env-forge/environments/{env_id}/approvals/{req_id}/decision")
def decide_approval(env_id: str, req_id: str, body: ApprovalDecision,
                    db: Session = Depends(get_db),
                    user: AuthContext = Depends(current_admin)) -> dict:
    """Approve or reject a pending request; the paused agent then proceeds or
    revises per the feedback."""
    e = _get_env(db, env_id, user)
    try:
        return approval_bridge.decide(e.generated_dir, req_id, body.approve, body.feedback, user.user_id)
    except approval_bridge.ApprovalBridgeError as exc:
        raise HTTPException(400, str(exc))
