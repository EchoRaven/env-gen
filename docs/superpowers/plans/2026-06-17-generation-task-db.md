# Generation-Task DB (GenerationTask registry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GenerationTask` registry table (one rich row per generation attempt — owner, paths, resumable state, lifecycle, resources, result) to the Env Forge backend db, backfilled from existing envs and populated going forward, without breaking the running server.

**Architecture:** Additive first slice of the approved spec (`docs/superpowers/specs/2026-06-17-generation-task-db-redesign.md`). We ADD `GenerationTask` + two columns on `Environment` (`current_task_id`, `archived`) and remove the dead `Run` table. `Environment` keeps `id=name` + `generated_dir` so the 28 `generated_dir` reads in `app/main.py` and the existing tests keep working. The spec's `Environment.id→uuid` + per-task output dirs are a **deliberately deferred follow-up plan** (large blast radius; uuid only pays off once dirs are per-task) — see "Deferred" at the bottom.

**Tech Stack:** SQLAlchemy 2.0 (Mapped/mapped_column), SQLite default (Postgres-ready), FastAPI, pytest. Python: `/home/haibotong/miniconda3/envs/dt/bin/python`.

## Global Constraints

- Run tests from repo root: `cd /data/common/haibotong/forgingground-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/<file> -v`.
- DB writer is the Env Forge server (`app/`); the db stores **pointers + metadata**, never heavy state (state lives in the generated tree). `state_path` = `<project_path>/.checkpoint`.
- Migrations are hand-rolled + idempotent, dialect-agnostic (SQLite + Postgres), run at `init_db()` (mirror the existing `_ensure_tenant_columns`).
- Lifecycle states (exact strings): `queued`, `generating`, `delivered`, `failed`, `killed`, `resumable`.
- Additive only: do NOT change `Environment.id` or remove `Environment.generated_dir` in this plan. Existing tests must stay green.
- No `Co-Authored-By` trailer in commits (user preference).

---

### Task 1: `GenerationTask` model + status helper

**Files:**
- Modify: `app/models.py` (append model + helper + status constants)
- Test: `tests/test_generation_task_db.py` (create)

**Interfaces:**
- Produces: `GenerationTask` ORM model (table `generation_tasks`, PK `task_id`); `TASK_STATUSES: tuple[str, ...]`; `record_status(task: GenerationTask, status: str, reason: str = "") -> None` (sets `task.status` + appends `{status, at, reason}` to `task.status_history_json`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_generation_task_db.py`:
```python
"""GenerationTask registry: model, status history, backfill migration, server wiring."""
import json

from app.db import SessionLocal
from app import models
from app.models import Environment, GenerationTask


def test_generation_task_persists_and_defaults():
    with SessionLocal() as db:
        t = GenerationTask(task_id="t-1", env_id="e-1", tenant_id="ten", created_by="u",
                           name="youtube", project_path="/x/youtube",
                           state_path="/x/youtube/.checkpoint", status="queued")
        db.add(t)
        db.commit()
        got = db.get(GenerationTask, "t-1")
        assert got is not None
        assert got.status == "queued"
        assert got.delivered is False
        assert got.status_history_json == "[]"
        assert got.coordination_ticks == 0 and got.cost_usd == 0.0
        db.delete(got)
        db.commit()


def test_record_status_appends_history_and_sets_status():
    t = GenerationTask(task_id="t-2", env_id="e-1", status="queued")
    models.record_status(t, "generating", "spawned")
    models.record_status(t, "delivered", "gate passed")
    assert t.status == "delivered"
    hist = json.loads(t.status_history_json)
    assert [h["status"] for h in hist] == ["generating", "delivered"]
    assert hist[0]["reason"] == "spawned" and "at" in hist[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/common/haibotong/forgingground-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/test_generation_task_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'GenerationTask'` / `record_status`.

- [ ] **Step 3: Write minimal implementation**

In `app/models.py`, add `Float`-already-imported check (it is) and append after `ChatMessage`:
```python
import json as _json

TASK_STATUSES = ("queued", "generating", "delivered", "failed", "killed", "resumable")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    env_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_by: Mapped[str] = mapped_column(String, default="", index=True)
    name: Mapped[str] = mapped_column(String, default="")
    project_path: Mapped[str] = mapped_column(String, default="")
    state_path: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    status_history_json: Mapped[str] = mapped_column(String, default="[]")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_phase: Mapped[str | None] = mapped_column(String, nullable=True)
    reference: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="")
    scope: Mapped[str] = mapped_column(String, default="")
    requirements: Mapped[str] = mapped_column(String, default="")
    gates_json: Mapped[str] = mapped_column(String, default="[]")
    max_wallclock_min: Mapped[int] = mapped_column(Integer, default=120)
    max_ticks: Mapped[int] = mapped_column(Integer, default=240)
    coordination_ticks: Mapped[int] = mapped_column(Integer, default=0)
    wallclock_sec: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    release_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_gentask_tenant_status", "tenant_id", "status"),)


def record_status(task: GenerationTask, status: str, reason: str = "") -> None:
    """Set ``task.status`` and append a {status, at, reason} entry to history."""
    hist = _json.loads(task.status_history_json or "[]")
    hist.append({"status": status, "at": _now().isoformat(), "reason": reason})
    task.status_history_json = _json.dumps(hist)
    task.status = status
```
Add `Index` to the imports at the top: `from sqlalchemy import DateTime, Float, Index, Integer, String, Boolean`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /data/common/haibotong/forgingground-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/test_generation_task_db.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_generation_task_db.py
git commit -m "feat(db): GenerationTask model + record_status helper"
```

---

### Task 2: Remove dead `Run` table + add `Environment` columns

**Files:**
- Modify: `app/models.py` (delete `Run` class; add 2 columns to `Environment`)
- Modify: `app/db.py` (add `_ensure_environment_columns()`, call it in `init_db`)
- Test: `tests/test_generation_task_db.py` (append)

**Interfaces:**
- Produces: `Environment.current_task_id: str | None`, `Environment.archived: bool`; `app.db._ensure_environment_columns() -> None` (idempotent ALTER, mirrors `_ensure_tenant_columns`).
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test** — append to `tests/test_generation_task_db.py`:
```python
def test_environment_has_current_task_and_archived():
    with SessionLocal() as db:
        e = Environment(id="e-cols", name="e-cols", tenant_id="ten", created_by="u",
                        generated_dir="/x/e-cols", status="generating",
                        current_task_id="t-x", archived=False)
        db.add(e)
        db.commit()
        got = db.get(Environment, "e-cols")
        assert got.current_task_id == "t-x"
        assert got.archived is False
        db.delete(got)
        db.commit()


def test_run_table_removed():
    import app.models as mm
    assert not hasattr(mm, "Run")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_generation_task_db.py::test_environment_has_current_task_and_archived tests/test_generation_task_db.py::test_run_table_removed -v`
Expected: FAIL — `TypeError: 'current_task_id' is an invalid keyword` and `Run` still present.

- [ ] **Step 3: Write minimal implementation**

In `app/models.py`: delete the entire `class Run(Base): ...` block. Add to `Environment` (after `updated_at`):
```python
    current_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
```
In `app/db.py`, add after `_ensure_tenant_columns()`:
```python
def _ensure_environment_columns() -> None:
    """Idempotent ALTER: add current_task_id + archived to a pre-existing
    ``environments`` table (create_all never ALTERs). SQLite + Postgres."""
    insp = inspect(engine)
    if "environments" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("environments")}
    adds = []
    if "current_task_id" not in have:
        adds.append("ADD COLUMN current_task_id VARCHAR")
    if "archived" not in have:
        adds.append("ADD COLUMN archived BOOLEAN DEFAULT 0")
    if not adds:
        return
    with engine.begin() as conn:
        for clause in adds:
            conn.execute(text(f"ALTER TABLE environments {clause}"))
```
And in `init_db()`, add the call after `_ensure_tenant_columns()`:
```python
    _ensure_tenant_columns()
    _ensure_environment_columns()
```

- [ ] **Step 4: Run test to verify it passes**

Run the full file: `... -m pytest tests/test_generation_task_db.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the existing backend suite to confirm no regression**

Run: `cd /data/common/haibotong/forgingground-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/ -q`
Expected: PASS (existing tests still green — Environment only gained columns; nothing referenced `Run`).

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/db.py tests/test_generation_task_db.py
git commit -m "feat(db): drop dead Run table; add Environment.current_task_id + archived"
```

---

### Task 3: Backfill migration (legacy Environment → one GenerationTask)

**Files:**
- Modify: `app/db.py` (add `_backfill_generation_tasks()`, call in `init_db`)
- Test: `tests/test_generation_task_db.py` (append)

**Interfaces:**
- Produces: `app.db._backfill_generation_tasks() -> None` — for every `Environment` with no `GenerationTask`, create one (`task_id=f"{env.id}:backfill"`, `project_path=env.generated_dir`, `state_path=env.generated_dir + "/.checkpoint"`, status mapped from env, config copied, `delivered` copied); set `env.current_task_id` iff delivered. Idempotent.

- [ ] **Step 1: Write the failing test** — append:
```python
def test_backfill_creates_one_task_per_env_and_is_idempotent():
    import app.db as dbmod
    with SessionLocal() as db:
        db.add(Environment(id="bf-env", name="bf-env", tenant_id="ten", created_by="u",
                           generated_dir="/envs/bf-env", status="completed",
                           model="gemini", provider="google", delivered=True))
        db.commit()
    dbmod._backfill_generation_tasks()
    dbmod._backfill_generation_tasks()  # second run must not duplicate
    with SessionLocal() as db:
        tasks = [t for t in db.query(GenerationTask).all() if t.env_id == "bf-env"]
        assert len(tasks) == 1
        t = tasks[0]
        assert t.project_path == "/envs/bf-env"
        assert t.state_path == "/envs/bf-env/.checkpoint"
        assert t.status == "delivered" and t.delivered is True
        assert t.model == "gemini" and t.provider == "google"
        e = db.get(Environment, "bf-env")
        assert e.current_task_id == t.task_id
        # cleanup
        db.delete(t); db.delete(e); db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_generation_task_db.py::test_backfill_creates_one_task_per_env_and_is_idempotent -v`
Expected: FAIL — `AttributeError: module 'app.db' has no attribute '_backfill_generation_tasks'`.

- [ ] **Step 3: Write minimal implementation** — in `app/db.py`, add:
```python
def _backfill_generation_tasks() -> None:
    """One-shot, idempotent: ensure every Environment has at least one
    GenerationTask (the legacy registry had no per-attempt rows). Maps the
    env's status/config onto the task; points current_task_id at it iff
    delivered. Safe to re-run (skips envs that already have a task)."""
    from . import models  # local import avoids a models<->db import cycle
    with SessionLocal() as db:
        envs = db.query(models.Environment).all()
        have = {t.env_id for t in db.query(models.GenerationTask.env_id).all()}
        # query above returns rows of (env_id,) tuples:
        have = {row[0] for row in db.query(models.GenerationTask.env_id).all()}
        made = False
        for e in envs:
            if e.id in have:
                continue
            if e.delivered or e.status in ("completed", "delivered"):
                status = "delivered"
            elif e.status == "failed":
                status = "failed"
            else:
                status = e.status or "queued"
            gd = e.generated_dir or ""
            t = models.GenerationTask(
                task_id=f"{e.id}:backfill", env_id=e.id, tenant_id=e.tenant_id,
                created_by=e.created_by, name=e.name, project_path=gd,
                state_path=(gd + "/.checkpoint") if gd else "",
                status=status, reference=e.reference, model=e.model,
                provider=e.provider, scope=e.scope, requirements=e.requirements,
                gates_json=e.gates_json, max_wallclock_min=e.max_wallclock_min,
                max_ticks=e.max_ticks, delivered=bool(e.delivered),
            )
            models.record_status(t, status, "backfill")
            db.add(t)
            if status == "delivered":
                e.current_task_id = t.task_id
            made = True
        if made:
            db.commit()
```
Remove the duplicate `have = ...` line — keep only the tuple-unpacking one:
```python
        have = {row[0] for row in db.query(models.GenerationTask.env_id).all()}
```
And call it last in `init_db()`:
```python
    _ensure_environment_columns()
    _backfill_generation_tasks()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `... -m pytest tests/test_generation_task_db.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_generation_task_db.py
git commit -m "feat(db): backfill one GenerationTask per existing Environment (idempotent)"
```

---

### Task 4: Server wiring — create a GenerationTask when an env is created

**Files:**
- Modify: `app/main.py` (the create-env endpoint near `:144`)
- Test: `tests/test_generation_task_db.py` (append — uses `TestClient`)

**Interfaces:**
- Consumes: `Environment`, `GenerationTask`, `record_status` from `app.models`; the create endpoint's existing `gen` path + auth context.
- Produces: on env create, a `GenerationTask` row (`status="generating"`, `project_path=gen`, `state_path=gen/.checkpoint`, config from the request) and `Environment.current_task_id` set to it.

- [ ] **Step 1: Write the failing test** — append (mirrors `tests/test_multitenant_auth.py`'s client/token pattern):
```python
import os, time
import jwt
import pytest
from fastapi.testclient import TestClient
import app.main as m

_SECRET = os.environ["AGENTSUITE_JWT_SECRET"]


def _hdr(sub="u", tenant="t"):
    p = {"sub": sub, "is_admin": True, "tenant_id": tenant, "exp": int(time.time()) + 3600}
    return {"Authorization": "Bearer " + jwt.encode(p, _SECRET, algorithm="HS256")}


@pytest.fixture()
def client():
    with TestClient(m.app) as c:
        yield c


def test_create_env_also_creates_generation_task(client):
    r = client.post("/env-forge/environments",
                    json={"name": "wired-env", "reference": "", "model": "gemini",
                          "provider": "google", "requirements": "build X"},
                    headers=_hdr())
    assert r.status_code in (200, 201), r.text
    with SessionLocal() as db:
        tasks = [t for t in db.query(GenerationTask).all() if t.name == "wired-env"]
        assert len(tasks) == 1
        t = tasks[0]
        assert t.status == "generating"
        assert t.state_path.endswith("/.checkpoint")
        assert t.model == "gemini" and t.provider == "google"
        e = db.get(Environment, "wired-env")
        assert e.current_task_id == t.task_id
```
(If the create endpoint's request body field names differ, read `app/main.py:144` and match them — the env-creation Pydantic model defines `name/reference/model/provider/requirements`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `... -m pytest tests/test_generation_task_db.py::test_create_env_also_creates_generation_task -v`
Expected: FAIL — no `GenerationTask` row created (`assert len(tasks) == 1`).

- [ ] **Step 3: Write minimal implementation**

In `app/main.py`, import the new names at the top (where `Environment` is imported): `from app.models import Environment, GenerationTask, record_status` (match the existing import style). In the create-env endpoint, right after `db.add(e)` (≈line 150), before the response, add:
```python
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
```
(Use the same field values the `Environment(...)` constructor already received; `gen` is the resolved generated path already computed at `:138`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `... -m pytest tests/test_generation_task_db.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `cd /data/common/haibotong/forgingground-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/ -q`
Expected: PASS (all backend tests green).

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_generation_task_db.py
git commit -m "feat(db): create a GenerationTask when an env is created (wire current_task_id)"
```

---

## Deferred (follow-up plan, NOT this one)

Per the spec's scope split — these have a large blast radius (`generated_dir` is read 28× in `app/main.py` + constructed in 3 test files) and only pay off together:
- `Environment.id` → uuid + unique(`tenant_id`, `name`); move `generated_dir` reads to `current_task.project_path`.
- **Per-task output dirs** so regeneration stops overwriting `ENVS_ROOT/<name>` (engine `--output` + the create/rescan logic at `app/main.py:144/80`).
- Driving task `status`/`resources`/`finished_at` from the engine checkpoint + process exit (live lifecycle); resume action surfacing.

## Self-Review

- **Spec coverage:** `generation_tasks` table (§4) → Tasks 1–4; lifecycle states + `status_history_json` (§5) → Task 1 `record_status`; migration convert-existing (§6) → Task 3 backfill; population contract (§7) → Task 4 (create wiring) + Deferred (per-task dirs, status-from-checkpoint). `Environment` lean/`current_task_id` (§4) → Task 2 (additive subset; uuid id Deferred). `Run` removal → Task 2. Indexes (§4) → Task 1 (`ix_gentask_tenant_status` + per-column `index=True`). Gap by design: `Environment.id→uuid` + per-task dirs are in Deferred (documented).
- **Placeholder scan:** none — every step has full code/commands.
- **Type consistency:** `GenerationTask`, `record_status(task, status, reason)`, `_ensure_environment_columns()`, `_backfill_generation_tasks()` used consistently across Tasks 1–4.
