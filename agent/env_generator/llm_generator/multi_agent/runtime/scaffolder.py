"""Deterministic project scaffolding, extracted from the Orchestrator
(PROPOSAL #8 — Scaffolder).

Thin orchestration over the ``runtime/*`` scaffold modules — docker-compose,
the database DDL, the deterministic backend skeleton, the embedded OAuth2 AS
base (+ runnable base ``main.py``/``reset.sh``), the MCP projection, and the
frontend baseline + contract-projected page stubs — plus registration of the
fixed contract surface (spine tables + AS/auth/infra endpoints).

Stateless: the Scaffolder borrows the orchestrator for its collaborators
(``output_dir`` / ``hubs`` / ``_logger`` / ``context``) and reads them live, so
it never goes stale if the orchestrator re-wires them. The orchestrator keeps
thin shims (``_generate_docker`` → ``scaffolder.generate_docker()`` …) so every
call site stays unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Runnable BASE backend entrypoint, committed to the git base pre-spawn (see
# Scaffolder.seed_base_scaffold). The backend lane ADDS business route handlers
# to this; the OAuth2 AS + /health + uvicorn entrypoint are framework-owned.
_BASE_MAIN_PY = '''"""FastAPI application entrypoint.

Framework-scaffolded BASE. The backend lane ADDS the app's business route handlers
below (``@app.<method>(...)`` handlers, or ``from <x>_routes import router as r;
app.include_router(r)``). The embedded OAuth2 AS (/oauth/*, /.well-known/*,
/auth/register, /auth/login) and /health are wired here and MUST NOT be re-authored.
"""
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Framework OAuth2 AS — provides /oauth/*, /.well-known/*, /auth/register, /auth/login.
try:
    from oauth_store import OAuthStore
    from jwt_manager import JWTManager
    from oauth_routes import build_router as _as_build_router
    app.include_router(_as_build_router(OAuthStore(), JWTManager()))
except Exception as _as_exc:  # pragma: no cover
    logging.getLogger("uvicorn").warning("AS wiring skipped: %s", _as_exc)


@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================================================================
# BUSINESS ROUTES — the backend lane implements the app's endpoints below.
# Add @app.<method>(...) handlers or include_router(...) for your route modules.
# ============================================================================


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_PORT", "8081")))
'''

# Base reset.sh — the backend's Dockerfile ``COPY reset.sh /reset.sh`` fails the
# image build if it's absent (the lane writes the Dockerfile referencing it but
# may not author the script). Best-effort generic business-data reset over the
# ORM; never fails the build (skips cleanly if models/db aren't importable). The
# backend MAY overwrite with an app-specific version.
_BASE_RESET_SH = '''#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
try:
    from database import SessionLocal, Base
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in ("users", "tenants"):
                db.execute(table.delete())
        db.commit()
    print("backend business data reset complete")
except Exception as exc:
    print(f"reset skipped: {exc}")
PY
'''


def _loop_page_advice_1202gq(names, pages=None) -> str:
    """How to keep a page the projector keeps clobbering — the rule that ACTUALLY governs it.

    #1202at states one exit for every looping page: "#914/#1020 KEEPS a page that imports
    `../components/`". That is `_imports_own_components` and it is right for an ordinary page.
    An AUTH page is decided elsewhere: `scaffold_pages_from_contract`'s auth branch asks
    `_lane_auth_page_is_live_1197` — wired AND drivable AND persists, over the page's whole
    depth-2 import bundle — so for a login/signup page the component rule is neither
    sufficient (a component-based login that never calls /auth/* is still replaced) nor
    necessary (a self-contained one that logs in is kept). r97 filed this task naming
    `LoginPage` SEVEN times; #1197's own comment records 87 clobbers of LoginPage in r26.
    The lane kept doing what it was told and kept losing the page.

    Split by the SAME predicate the projector uses (`_is_auth_page`), so the two can never
    drift into disagreeing about which page is which (#906).
    """
    from .frontend_scaffold import _is_auth_page
    from .message_format import join_capped
    pages = pages or {}
    names = [str(n) for n in (names or [])]
    auth = [n for n in names if _is_auth_page(n, pages.get(n) or {})]
    plain = [n for n in names if n not in auth]

    head = ("The framework has re-projected these pages after you rewrote them, 3+ times each "
            "this run, so none of that work reaches a screenshot: %s. This is not a verdict on "
            "your code — the projector replaces any page it cannot tell apart from a stub."
            % join_capped(names, total=len(names), cap=6))
    parts = [head]
    if plain:
        parts.append(
            "How to keep %s: the projector KEEPS a page that imports from `../components/` "
            "and REPLACES one that does not (#914/#1020). Move the page body into a component "
            "under `src/components/` and have the page import and render it. The same content "
            "then survives every later scaffold pass."
            % join_capped(plain, total=len(plain), cap=6))
    if auth:
        parts.append(
            "How to keep %s: an AUTH page is judged by a different rule (#1197) — importing "
            "`../components/` does NOT protect it. The page is kept only when it is all three, "
            "counted across the files it imports (2 hops), so a component may carry any of "
            "them:\n"
            "  * WIRED — it calls `/auth/login` or `/auth/register` (the framework owns those "
            "endpoints), or it drives useAuth/AuthContext with a login()/register() call;\n"
            "  * DRIVABLE — a NAMED input plus a <form> or type=\"submit\", so the ui_flow "
            "walkthrough can type and submit;\n"
            "  * PERSISTS — it stores the returned token.\n"
            "A page missing any one of them reads as a dead login and is replaced, however "
            "much of it lives in components."
            % join_capped(auth, total=len(auth), cap=6))
    return "\n\n".join(parts)


def ensure_base_gitignore(output_dir: Path) -> list:
    """Keep everything that is NOT deliverable code out of git. Returns the rel-paths to commit.

    ``memory-bank/<lane>/`` is lane scratch (notes + the framework's auto-synced STATE);
    committing it bloated the repo and every release snapshot, and forced a bespoke
    "auto-commit memory-bank before integration pull" dance in auto_commit.py to keep
    ``git stash -u`` from dropping it. Ignoring it is strictly better: ``git status`` stops
    listing it (so that dance no-ops) AND ``stash -u`` SPARES ignored paths, so it survives
    the per-tick merge for free — never committed, never in the deliverable.

    #624: the framework's OWN scratch dirs need the identical treatment for the identical
    reason. Injected skills, per-agent logs, nested worktrees, scratch memory — no lane
    authored them and none can ship, yet git listed them as untracked, which is what makes a
    worktree DIRTY: **42 of the 89 dirty worktrees across 15 runs are dirty for no other
    reason**. A dirty worktree is what forces the step-start ``git stash -u`` whose failure
    (187 times, "could not write index") used to be reported as a merge conflict — the false
    label that ignited #623's 70.8x conflict storm. Removing the stash removes the ignition.

    The list is imported from the prune-set that already treats these as non-content, so the
    two cannot drift. Build artifacts are deliberately excluded — different category,
    different delivery risk, and nothing measured points at them.
    """
    try:
        from ...tools.file_tools import FRAMEWORK_SCRATCH_DIRS
    except Exception:  # pragma: no cover — import-shape safety only
        FRAMEWORK_SCRATCH_DIRS = (
            ".agents", ".agent_logs", "worktrees", ".memory", "snapshots")
    gi = Path(output_dir) / ".gitignore"
    want = ["memory-bank/"] + [f"{d}/" for d in FRAMEWORK_SCRATCH_DIRS]
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    new = [p for p in want if p not in cur.split()]
    if not new:
        return []
    gi.write_text((cur.rstrip() + "\n" if cur.strip() else "") + "\n".join(new) + "\n",
                  encoding="utf-8")
    return [".gitignore"]


class Scaffolder:
    """Deterministic project scaffolding over the runtime/* modules. Borrows the
    orchestrator for output_dir / hubs / logger / context (read live)."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    async def generate_docker(self) -> None:
        """Generate docker-compose.yml."""
        orch = self._orch
        db_port = orch.context.db_port
        backend_port = orch.context.backend_internal_port
        api_port = orch.context.api_port
        ui_port = orch.context.ui_port

        # #1157: NAME THE COMPOSE PROJECT AFTER THE RUN.
        #
        # Without this, the project name comes from the compose file's DIRECTORY, which is
        # `docker` for EVERY run — so every run shares the containers `docker-backend-1`,
        # the networks, the volumes, and (the damaging one) the image tags
        # `docker-backend:latest` / `docker-frontend:latest`.
        #
        # #962 already documented the ambiguity and worked around it for container LOOKUP
        # ("Stop the stale stack, or give the run its own compose project name"), but the
        # project name itself was never fixed, and the lookup was not the worst of it:
        # a later run's build silently REPLACES an earlier run's image. Measured live —
        # r13 delivered and was runtime-verified, r14 then ran and tagged
        # `docker-backend:latest` at 02:20; bringing r13 up afterwards without --build
        # served r14's backend against r13's database, and r14's model declares
        # `titles.genres` while r13's DDL does not. Every /api/titles call answered
        # `UndefinedColumn: column titles.genres does not exist` -> 500, so the browse home
        # had no data and only the empty My List rendered. The artifact had been verified
        # working hours earlier; nothing about it changed except that another run happened.
        #
        # `name:` is Compose-spec and supported by the v2 CLI. Sanitised to the charset
        # Compose accepts (lowercase alnum, dash, underscore) and never empty. Built with
        # str methods, not `re`: #940's checker reads `re` as possibly-unbound here, and
        # the line is PREPENDED rather than placed inside the template because
        # test_compose_db_env_conventions renders that f-string with `.format()` over a
        # fixed key set — a new placeholder inside it is a KeyError, not a compose change.
        _raw1157 = str(getattr(orch.output_dir, "name", "") or "").lower()
        _proj1157 = "".join(
            ch if ((ch.isalnum() and ch.isascii()) or ch in "-_") else "-"
            for ch in _raw1157).strip("-") or "envgen-run"

        docker_compose = f'''version: '3.8'

# Generated with run-specific free host ports.
# Target = forgingground/agentsuite env (see docs/target_env_architecture.md):
# FastAPI backend + stock postgres (schema delivered via init/ mount, NOT a
# custom db image) + React/Vite frontend. Agents may edit host-side port
# mappings if validation finds conflicts.

services:
  database:
    image: postgres:16
    environment:
      POSTGRES_USER: sandbox
      POSTGRES_PASSWORD: sandbox
      POSTGRES_DB: app
      PGPORT: {db_port}
    volumes:
      - ../app/database/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "{db_port}:{db_port}"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sandbox -d app -p {db_port}"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 30s

  backend:
    build: ../app/backend
    environment:
      DATABASE_URL: postgresql+psycopg://sandbox:sandbox@database:{db_port}/app
      # Fix #60 (outlook run-45, live): lanes hand-roll their own DB clients
      # (an asyncpg pool in custom_routes) reading whatever env convention they
      # guess — DB_HOST/DB_PORT/..., PG*, POSTGRES_* — NONE of which existed, so
      # the guess fell back to its localhost defaults and every custom-route
      # read 500'd (OSError: Connect call failed 127.0.0.1). Export the SAME
      # connection facts under all three common conventions so any reasonable
      # guess resolves BY CONSTRUCTION (PG* is also libpq/asyncpg's native
      # fallback; DATABASE_URL is complete, so psycopg never consults PG*).
      DB_HOST: database
      DB_PORT: "{db_port}"
      DB_USER: sandbox
      DB_PASSWORD: sandbox
      DB_NAME: app
      PGHOST: database
      PGPORT: "{db_port}"
      PGUSER: sandbox
      PGPASSWORD: sandbox
      PGDATABASE: app
      POSTGRES_HOST: database
      POSTGRES_PORT: "{db_port}"
      POSTGRES_USER: sandbox
      POSTGRES_PASSWORD: sandbox
      POSTGRES_DB: app
      API_PORT: {backend_port}
      # Audit rank-1 (whack-a-mole eradication): FW_DEBUG makes the generated backend's
      # by-construction fallbacks (_fw_owner_val, the seed loader) LOUD — they print the
      # swallowed exception to stderr (-> `docker logs backend`) instead of silently
      # degrading, so ONE validation run surfaces ALL layered failures. Propagated from the
      # shell that runs `docker compose up`; empty (a total no-op) unless the run exports
      # FW_DEBUG=1, so a normal delivery run is byte-for-byte unaffected.
      FW_DEBUG: "${{FW_DEBUG:-}}"
      # Embedded OAuth2 AS (zoom-style): the env mints its OWN RS256 tokens.
      # OAUTH_ISSUER is intentionally unset → derived from request.base_url.
      OAUTH_DEFAULT_AUDIENCE: app-api
      OAUTH_DEFAULT_SCOPE: app.read app.write app.admin
      OAUTH_ACCESS_TOKEN_TTL: "3600"
      JWT_DATA_DIR: /var/lib/app-auth
      APP_PASSWORD_SALT: app_sandbox_salt_2024
    volumes:
      - app_auth_keys:/var/lib/app-auth   # persist the RSA signing key across restarts
    ports:
      - "{api_port}:{backend_port}"
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{backend_port}/health', timeout=5)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s

  frontend:
    build: ../app/frontend
    environment:
      UI_PORT: 3000
      API_URL: http://backend:{backend_port}
    ports:
      - "{ui_port}:3000"
    depends_on:
      - backend

volumes:
  app_auth_keys:
'''

        docker_dir = orch.output_dir / "docker"
        docker_dir.mkdir(exist_ok=True)
        # #1157: prepended AFTER the template is built, so the template itself stays
        # placeholder-free — test_compose_db_env_conventions locates it by the literal
        # `docker_compose = f'''` and renders it with .format() over a fixed key set.
        docker_compose = f"name: {_proj1157}\n" + docker_compose
        (docker_dir / "docker-compose.yml").write_text(docker_compose)

    async def generate_database(self) -> None:
        """Author ``app/database/`` deterministically from the registered
        SchemaHub tables.

        Closed-by-construction sibling to ``generate_docker``: the
        compose file unconditionally declares a ``database`` service whose
        build context is ``../app/database`` and the delivery gate requires
        ``app/database/*.sql``, but no LLM lane reliably wrote that dir
        (0/10 across smokes #38-49). The kickoff validator guarantees every
        registered table carries a non-empty ``columns: [{name, type}]``
        list, so once kickoff finalizes the runtime holds everything needed
        to emit a faithful ``CREATE TABLE`` schema — no agent, no variance.
        The runtime is the SOLE owner of ``app/database/``.

        Called once, post-``finalize_kickoff`` (tables are registered by
        then). Idempotent — overwrites so the scaffold always reflects the
        current contract."""
        from .database_scaffold import write_database_scaffold, synthesize_missing_tables
        from .lifecycle import business_endpoints

        orch = self._orch
        tables = orch.hubs.schema_hub.list_tables() or {}
        _rh = getattr(orch.hubs, "registryhub", None)
        _eps = business_endpoints(_rh.get_endpoints() or {}) if _rh else []
        # Contract completeness: derive a backing table for any creatable business
        # resource the lane registered an endpoint for but never tabled (large apps).
        tables = synthesize_missing_tables(tables, _eps)
        paths = write_database_scaffold(orch.output_dir, tables)
        try:                                             # #894: stage timeline
            from .stage_contract import record_stage_894
            from progress import EventType as _ET894      # top-level module, not a sibling
            _sql894 = Path(orch.output_dir) / "app" / "database" / "init" / "01_init.sql"
            record_stage_894("database_scaffold", "tables", tables,
                             # #896: ok means THE FILE LANDED, not "tables were passed in".
                             ok=bool(tables) and _sql894.is_file(),
                             progress=getattr(orch, "progress", None),
                             event_type=_ET894.PHASE_START)
        except Exception:
            pass
        orch._logger.info(
            "Authored app/database/ scaffold: %d table(s) → %s",
            paths["table_count"], paths["schema_sql"],
        )

    def generate_backend_skeleton(self) -> None:
        """SKELETON根治 (2026-06-09, user-chosen): generate the ENTIRE backend
        DETERMINISTICALLY from the contract (SchemaHub tables + RegistryHub endpoints) — ORM
        models, all CRUD handlers, fixed storage/auth/infra — OVERWRITING whatever the
        lane wrote. This removes the lane's STRUCTURAL non-determinism at the source
        (across runs it wrote ORM/raw-SQL/file-based-JSON/fragmented apps that DB-centric
        repairs couldn't all cover): the same contract now always yields a consistent,
        complete, auth-enforced, all-2xx backend with real persistence (reconstruction-
        proven by a docker build+boot). The lane's role shrinks to AUTHORING THE
        CONTRACT. Best-effort; idempotent (deterministic → byte-identical)."""
        orch = self._orch
        registryhub = getattr(orch.hubs, "registryhub", None)
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            # #891: the backend is the first consumer of the DDL. 12 of 151 corpus runs reached
            # here with app/database/init empty — the app then has no tables and every query
            # fails at RUNTIME, five links from the cause.
            try:
                from .stage_contract import require_stage_input_891
                _init = Path(orch.output_dir) / "app" / "database" / "init"
                require_stage_input_891(
                    "backend skeleton", "app/database/init/*.sql", "the database scaffold",
                    present=lambda: sorted(_init.glob("*.sql")) if _init.is_dir() else [],
                    detail="the generated app will start against an empty database.")
            except Exception:
                pass
            from .backend_skeleton import write_backend_skeleton
            from .lifecycle import business_endpoints
            from .database_scaffold import (synthesize_missing_tables,
                                             synthesize_missing_create_endpoints)
            sh = getattr(orch.hubs, "schema_hub", None)
            tables = (sh.list_tables() if sh else {}) or {}
            endpoints = business_endpoints(registryhub.get_endpoints() or {}) if registryhub else []
            if not tables and not endpoints:
                return  # contract not finalized yet — nothing to project
            # Contract completeness: derive a backing table for any creatable
            # business resource that has an endpoint but no registered table, so
            # the projector emits a REAL handler (not a stub) for it (large apps).
            tables = synthesize_missing_tables(tables, endpoints)
            # Contract completeness #76 (outlook run-63): a resource that is demonstrably
            # MUTABLE (collection GET + reply/forward/patch/delete) but whose plain CREATE
            # (POST /api/<collection>) the kickoff LLM dropped → create 405 → the
            # business_chain can't make a row → nested ${id} unresolved → 422 → STUCK. Add
            # the missing create so the projector emits a real handler (never for a read-only
            # collection). run-62 had it; run-63 (same env) didn't — pure LLM variance.
            endpoints, _synth_created = synthesize_missing_create_endpoints(endpoints, tables)
            if _synth_created:
                # Register in the RegistryHub too (not just the local projection list) so ALL
                # consumers agree: the route projector emits the create handler AND the
                # verifier's business_chain (which reads the registry via business_endpoints)
                # gets a POST /collection to create the parent → nested ${id} resolves. status
                # 'implemented' so it never blocks the all-endpoints-implemented gate.
                if registryhub is not None:
                    for _ep in endpoints:
                        if (_ep.get("path") in _synth_created
                                and str(_ep.get("method", "")).upper() == "POST"):
                            try:
                                registryhub.register_endpoint(
                                    method="POST", path=_ep["path"], schema=_ep.get("schema"),
                                    agent="orchestrator", status="implemented",
                                    kind="business", synthesized_create=True)
                            except Exception:
                                pass
                orch._logger.warning(
                    "CONTRACT COMPLETENESS: synthesized + registered missing CREATE endpoint(s) "
                    "for mutable resources whose POST /collection the lane dropped: %s",
                    _synth_created)
            # VERIFIER-DRIVEN read isolation at the FULL-SKELETON site (outlook run-34):
            # render_skeleton_main owner-scopes reads from table METADATA only, and the
            # chain-probed union previously applied ONLY in project_missing_routes (which
            # never touches routes the skeleton already wrote) — so the full regen kept
            # emitting UNSCOPED by-id GETs for isolation-probed tables. Once the lane's
            # (properly scoped) custom route died at import, the unscoped projected read
            # leaked cross-user rows → isolation probes failed 7 cycles → STUCK abort.
            # Union the probe signal into the LOCAL metadata before rendering — derived
            # from persisted chains, so it re-applies deterministically every regen.
            # Each SIGNAL gets its own try, and the application sits outside both. Sharing
            # one would mean a failure in either — a circular import, a hub that is not
            # there — silently disabling the other, which is the shape of most of the
            # defects this file's comments describe.
            _probed = set()
            try:
                from .heal_pipeline import _isolation_scoped_tables_from_chains
                _probed = set(_isolation_scoped_tables_from_chains(
                    registryhub, set(tables.keys())) if registryhub else set())
            except Exception as _e1201a:
                from .message_format import warn_once_1201
                warn_once_1201("isolation_scoped_tables",
                               "the chain-probe owner-scoping signal", _e1201a)
            # #1200: the lane's own READ filter is the same judgment as a probe, and r23 had
            # it while the probe was missing — its custom_routes filtered
            # `Profile.user_id == _user_id(user)` while the projection that replaced it
            # shipped `db.query(Profile).limit(100).all()` and leaked every user's profiles.
            # Union it in; empty set == previous behaviour.
            try:
                from .backend_skeleton import _lane_owner_scoped_read_tables_1200
                _probed |= _lane_owner_scoped_read_tables_1200(
                    Path(out_dir) / "app" / "backend", tables)
            except Exception as _e1201b:
                from .message_format import warn_once_1201
                warn_once_1201("lane_read_signal_wiring",
                               "the lane-read owner-scoping signal (#1200)", _e1201b)
            # #1202: the signal that asks nothing of any agent — a table other rows are
            # OWNED BY is per-user identity, whatever its column shape. Its own try, per
            # #1201, so neither of the other two can switch it off.
            try:
                from .backend_skeleton import _sub_entity_owner_tables_1202
                _probed |= _sub_entity_owner_tables_1202(tables)
            except Exception as _e1202:
                from .message_format import warn_once_1201
                warn_once_1201("sub_entity_owner_1202",
                               "the sub-entity owner-scoping signal (#1202)", _e1202)
            for _t in _probed:
                _rec = tables.get(_t)
                if isinstance(_rec, dict):
                    _md = dict(_rec.get("metadata") or {})
                    _md["owner_scoped_reads"] = True
                    _rec = dict(_rec)
                    _rec["metadata"] = _md
                    tables[_t] = _rec
            res = write_backend_skeleton(out_dir, endpoints, tables)
            # #1202h: report routes the app serves that the contract never declared — they are
            # ungated BY CONSTRUCTION, since every gate reads the registry. Own try (#1201).
            try:
                from .backend_skeleton import unregistered_routes_1202h
                from .message_format import join_capped
                _un1202h = unregistered_routes_1202h(
                    Path(out_dir) / "app" / "backend", endpoints)
                if _un1202h:
                    orch._logger.warning(
                        "#1202h %d route(s) are SERVED but never registered, so no gate "
                        "sees them — not auth, not owner-scoping, not coverage. Five of the "
                        "eight found across the corpus were debug/admin scaffolding that "
                        "shipped (/api/debug_routes2, /api/admin/fix). Register them or "
                        "remove them: %s",
                        len(_un1202h), join_capped(_un1202h, total=len(_un1202h)))
            except Exception as _e1202h:
                from .message_format import warn_once_1201
                warn_once_1201("unregistered_routes_1202h",
                               "the unregistered-route report (#1202h)", _e1202h)
            # #1202ad: this states an unchanging fact once per scaffold pass — r30/r31/r32
            # logged 281 copies between them. Report the STATE (what was written for which
            # contract size); a contract that grows is news, a re-run of the same one is not.
            from .message_format import state_changed_1202ad as _sc1202ad
            if _sc1202ad("backend_skeleton",
                         (len(tables), len(endpoints), tuple(sorted(res.get("written") or ())))):
              orch._logger.warning(
                "BACKEND SKELETON generated by-construction from the contract "
                "(%d tables, %d endpoints) — the whole backend is framework-owned "
                "(deterministic, consistent, auth-enforced): %s",
                len(tables), len(endpoints), res.get("written"))
              # #1202az: the projection above is faithful, which is exactly why a table
              # registered with only `id` is dangerous — it materialises a one-column table,
              # the staged rows cannot land, and every consumer fails far from the cause.
              # netflix-r30 registered `titles` with 1 column while its dataset carried 12
              # fields per row; r32, same environment two days later, registered 13. r30 then
              # spent 148 minutes and $930 on `GET /api/genres/11/titles -> 404` (x15, the id
              # correctly substituted from the list endpoint) before DELIVERY-GATE
              # NO-CONVERGENCE ABORT, and nothing in that chain of symptoms names the cause.
              # Both halves are in hand right here. Own try (#1201).
              try:
                  from .backend_audit import underspecified_tables_1202az
                  from .message_format import join_capped as _jc1202az
                  from pathlib import Path as _Path1202az
                  _us1202az = underspecified_tables_1202az(
                      tables, _Path1202az(out_dir))
                  if _us1202az:
                      orch._logger.error(
                          "#1202az %d contract table(s) hold a primary key and nothing else "
                          "while data is staged for them: %s. The skeleton just materialised "
                          "them exactly as registered, so the rows cannot land and the "
                          "failures will surface far from here (r30: 148min and $930 of "
                          "`GET /api/genres/{id}/titles -> 404` before a no-convergence abort).",
                          len(_us1202az), _jc1202az(_us1202az, total=len(_us1202az), cap=3))
                      # #1202bn: file on a CHANGED finding, not once per scaffold pass.
                      # create_task has no duplicate check — #672 only REPORTS a twin and
                      # says so ("This does NOT block") — and the scaffold ran 117 times in
                      # r32, so a finding that persists until a lane fixes it would file 117
                      # tasks. The corpus already measures that cost: of 838 cancelled tasks,
                      # 462 (55%, across 79 of 144 runs) were cancelled as duplicates.
                      from .message_format import state_changed_1202ad as _sc1202az
                      if _sc1202az("task:underspecified_tables", tuple(sorted(map(str, _us1202az)))):
                          orch.hubs.workhub.create_task(
                              title=("Register the columns for %d table(s) that have only an id"
                                     % len(_us1202az))[:180],
                              description=(
                                  "These tables are registered with a primary key and nothing else, "
                                  "but the staged dataset carries far more per row, so the framework "
                                  "projected a one-column table and the data has nowhere to go: "
                                  "%s.\n\nRegister the real columns for each and the skeleton will "
                                  "re-project them. Symptoms otherwise appear far away — a genre "
                                  "lookup 404ing on an id the list endpoint just returned, for one."
                                  % _jc1202az(_us1202az, total=len(_us1202az), cap=6)),
                              assignee="backend", agent="scaffolder", priority="P1", kind="contract")
                      # #1202gv: the materials say a row is for EVERYONE and the contract
                      # scopes its read to the author. Nothing compared those two before, so
                      # the disagreement only ever surfaced three surfaces away — r100's feed
                      # answered `{"items": []}` to a fresh actor, the videoId save captured
                      # nothing, and 38 of 73 chain steps 404'd behind a substituted id.
                      # Every other reader of `visibility` is reactive; this one speaks first.
                      from .backend_audit import public_content_scoped_away_1202gv
                      _spec1202gv = {}
                      try:
                          import json as _j1202gv
                          _sp1202gv = _Path1202az(out_dir) / "design" / "reference_spec.json"
                          if _sp1202gv.is_file():
                              _spec1202gv = _j1202gv.loads(
                                  _sp1202gv.read_text(encoding="utf-8"))
                      except Exception:
                          _spec1202gv = {}
                      _gv = public_content_scoped_away_1202gv(_spec1202gv, tables)
                      if _gv and _sc1202az("task:public_content_scoped_away",
                                           tuple(sorted(map(str, _gv)))):
                          orch.hubs.workhub.create_task(
                              title=("Reconcile %d table(s) the materials call public with "
                                     "the contract that owner-scopes them" % len(_gv))[:180],
                              description=(
                                  "The reference materials declare %s as PUBLIC content — in "
                                  "the compile instructions' words, \"every row is content "
                                  "PUBLISHED for all users to read ... a reader who is not the "
                                  "author still sees the row, and seeing it is the point\". "
                                  "The contract sets `owner_scoped_reads: true` on the same "
                                  "table(s), so the projected read is `WHERE <owner> = "
                                  "<caller>` and a reader who is not the author sees NOTHING.\n\n"
                                  "One of the two is wrong and only you can settle it. If these "
                                  "rows really are published content, clear "
                                  "`owner_scoped_reads` for them; if they are per-user after "
                                  "all, the materials' declaration is what should change.\n\n"
                                  "This is worth settling EARLY because the symptom appears far "
                                  "away: an owner-scoped feed answers `{\"items\": []}` to a "
                                  "fresh actor, so a chain step that captures `items.0.id` "
                                  "saves nothing and every later step 404s on a substituted id."
                                  % _jc1202az(_gv, total=len(_gv), cap=6)),
                              assignee="backend", agent="scaffolder", priority="P1",
                              kind="contract")
              except Exception as _e1202az:
                  from .message_format import warn_once_1201 as _w1202az
                  _w1202az("underspecified_tables_1202az",
                           "the empty-table-contract report (#1202az)", _e1202az)
            # Mechanism #43 (round 32: 17 endpoint tasks cancelled in cascade):
            # the skeleton just MATERIALIZED every contract table as ORM+DDL,
            # but their RegistryHub status stayed 'defined' — so the impl.table.*
            # dispatch tasks never auto-completed, every impl.endpoint.* task
            # stayed depends_on-blocked, and the backend talked the
            # orchestrator into bulk-cancelling the plan. Flip the generated
            # tables to implemented (by-construction truth); register_table
            # cascades sync_impl_table_completed → tasks complete → deps clear.
            if registryhub is not None:
                for _tname in (tables or {}):
                    try:
                        _cur = registryhub.get_table(_tname) or {}
                        if (_cur.get("status") or "").lower() != "implemented":
                            registryhub.register_table(
                                _tname, agent="orchestrator", status="implemented")
                    except Exception:
                        pass
        except Exception as exc:
            orch._logger.debug("backend skeleton generation skipped: %s", exc)
        # Mechanism #50: audit the registered ui_pages against the actual
        # frontend code and flip defined→implemented (cascades impl.page.*
        # completion) — the frontend's analog of the table flip above.
        try:
            # #1090: register the components the framework MANDATES but nobody declares, so
            # the audit on the next line can see them (see the helper for the measurement).
            from .frontend_audit import register_mandated_ui_components_1090
            _newc = register_mandated_ui_components_1090(
                orch.output_dir, getattr(orch.hubs, "registryhub", None))
            if _newc:
                orch._logger.info("#1090 registered mandated ui_component(s): %s", _newc)
        except Exception:
            pass
        try:
            from .frontend_audit import sync_ui_page_statuses
            _pa = sync_ui_page_statuses(orch.output_dir, orch.hubs.workhub,
                                        registryhub=getattr(orch.hubs, "registryhub", None))
            # #1202bc: `component_drift` has been computed and returned all along and
            # nobody reads it. r31 reported 12 pages whose declared components the
            # delivered page renders NONE of — `landing` declares public_header and
            # landing_hero, and the shipped LandingPage.jsx is 45 lines with no component
            # tag and no ../components/ import at all. Checked against the clobber loop
            # first, and it is a different fault: r31 logged zero PROJECTION CLOBBER and
            # zero SCAFFOLD LOOP.
            #
            # The condition is already conservative — it fires only when EVERY declared
            # component is missing — and the frontend lane both owns the pages and can fix
            # it, so this is #780's "a finding nobody is assigned" once more. The advice
            # doubles as #1202at's: a page built out of ../components/ is also the shape
            # the projector keeps.
            try:
                _cd1202bc = _pa.get("component_drift") or {}
                if _cd1202bc:
                    from .message_format import join_capped as _jc1202bc
                    _pg1202bc = sorted(_cd1202bc)
                    # #1202bn: file on a CHANGED finding, not once per scaffold pass.
                    # create_task has no duplicate check — #672 only REPORTS a twin and
                    # says so ("This does NOT block") — and the scaffold ran 117 times in
                    # r32, so a finding that persists until a lane fixes it would file 117
                    # tasks. The corpus already measures that cost: of 838 cancelled tasks,
                    # 462 (55%, across 79 of 144 runs) were cancelled as duplicates.
                    from .message_format import state_changed_1202ad as _sc1202bc
                    if _sc1202bc("task:component_drift", tuple(sorted(map(str, _pg1202bc)))):
                        orch.hubs.workhub.create_task(
                            title=("Build the %d page(s) whose declared components are missing"
                                   % len(_pg1202bc))[:180],
                            description=(
                                "These pages declare components in the contract and the delivered "
                                "page renders none of them, so the contract describes a page that "
                                "was not shipped: %s.\n\nBuild each declared component under "
                                "`src/components/` and have the page import and render it. That is "
                                "also the shape the projector KEEPS (#914/#1020) — a page built "
                                "from ../components/ survives later scaffold passes, one written "
                                "inline does not."
                                % _jc1202bc(
                                ["%s (%s)" % (n, _jc1202bc(
                                    _cd1202bc[n], total=len(_cd1202bc[n]), cap=3))
                                 for n in _pg1202bc],
                                total=len(_pg1202bc), cap=6)),
                            assignee="frontend", agent="scaffolder", priority="P2", kind="fidelity")
            except Exception as _e1202bc:
                from .message_format import warn_once_1201 as _w1202bc
                _w1202bc("component_drift_1202bc",
                         "the component-drift report (#1202bc)", _e1202bc)
            if _pa.get("implemented") or _pa.get("regressed"):
                orch._logger.warning(
                    "UI-PAGE LIFECYCLE: implemented=%s regressed=%s pending=%s",
                    _pa.get("implemented"), _pa.get("regressed"),
                    list((_pa.get("pending") or {}).keys()))
        except Exception:
            pass

    async def seed_base_scaffold(self) -> None:
        """Seed the FIXED contract surface into the git base, pre-spawn.

        The target env IS its own OAuth2 AS (zoom-style); its three modules —
        ``jwt_manager.py`` (RS256 sign + JWKS), ``oauth_store.py`` (psycopg3 store
        over the spine), ``oauth_routes.py`` (authorize/token/register + PKCE
        S256) — are pure infrastructure with zero business logic, and the
        backend's ``main.py`` IMPORTS them. Re-authoring an OAuth2 AS per run via
        an LLM lane is the textbook drift source (a salt mismatch, a missing PKCE
        check, a ``sub`` that isn't the user id → no token mints or verifies).

        So the runtime emits them verbatim AND commits them to the git base
        BEFORE any agent worktree exists. Because every ``agent/<id>`` worktree
        branches off base HEAD (and ``integration`` is bootstrapped from the
        first agent branch), all lanes inherit the AS modules by construction:
        the backend's imports/lint resolve in-worktree, and git — not a prompt
        convention — owns the "do not author these" boundary. Idempotent."""
        from .oauth_scaffold import write_oauth_as, AS_MODULES

        orch = self._orch
        # ensure the git repo exists before we commit (it is otherwise lazily
        # init'd by the first register_agent_worktree, which runs during spawn).
        orch.hubs.codehub.ensure_repo()
        result = write_oauth_as(orch.output_dir)
        rel_paths = [f"app/backend/{m}" for m in AS_MODULES]
        # Scaffold a runnable BASE ``main.py`` too. The backend lane BLOCKS trying to
        # READ app/backend/main.py to add its route handlers — but nothing creates it
        # (the framework owns only the AS modules), so the lane spins reporting
        # "scaffold exists but main.py absent" instead of writing code. Provide a
        # valid FastAPI app (AS wired, /health, uvicorn entrypoint) committed to the
        # git base pre-spawn so every lane inherits it.
        #
        # #1005: this comment used to end "the backend then ADDS business routes to it",
        # and that is not true — `main.py` is in `_BACKEND_FRAMEWORK_OWNED`, so
        # `is_framework_owned()` makes the write guard DENY every lane edit to it. The
        # projector states the real contract: "the lane implements the real handler in
        # custom_routes.py" (route_projector), which main.py discovers and includes.
        #
        # The stale sentence is very likely where the mistake spread from: #1004's
        # remediation text and #1005's worked example in backend_agent.j2 both told the
        # lane to wire routes in main.py, and both were written by someone reading this.
        # A wrong comment in the framework becomes a wrong instruction to an agent.
        main_py = orch.output_dir / "app" / "backend" / "main.py"
        if not main_py.exists():
            main_py.parent.mkdir(parents=True, exist_ok=True)
            main_py.write_text(_BASE_MAIN_PY, encoding="utf-8")
            rel_paths.append("app/backend/main.py")
        # The backend Dockerfile COPYs reset.sh; scaffold a base one so the image
        # always builds (the lane may overwrite it with an app-specific reset).
        reset_sh = orch.output_dir / "app" / "backend" / "reset.sh"
        if not reset_sh.exists():
            reset_sh.parent.mkdir(parents=True, exist_ok=True)
            reset_sh.write_text(_BASE_RESET_SH, encoding="utf-8")
            try:
                reset_sh.chmod(0o755)
            except Exception:
                pass
            rel_paths.append("app/backend/reset.sh")
        # Author + commit docker-compose.yml in the BASE bootstrap commit too. Ports are
        # allocated at init (before this runs), so the compose can be written now. Without
        # it in the base, the compose only lands in a LATE framework-delivery commit, and
        # the integration tree's HEAD can lack it at the moment framework validation checks
        # compose_present → the 7-cycle compose_present wedge that aborted instagram_fresh
        # (committed in a framework-delivery commit, yet absent from integration HEAD). In
        # the root commit it's inherited by every worktree + integration HEAD from t=0; the
        # later generate_docker() rewrites it byte-identically (idempotent).
        try:
            await self.generate_docker()
            if (orch.output_dir / "docker" / "docker-compose.yml").exists():
                rel_paths.append("docker/docker-compose.yml")
        except Exception as _dc_err:
            orch._logger.warning("base-scaffold compose write failed: %s", _dc_err)
        try:
            rel_paths.extend(ensure_base_gitignore(orch.output_dir))
        except Exception as _gi_err:
            orch._logger.warning("base-scaffold .gitignore write failed: %s", _gi_err)
        sha = orch.hubs.codehub.commit_runtime_scaffold(
            rel_paths,
            "bootstrap: embedded OAuth2 AS modules + base main.py + docker-compose (runtime-owned)",
        )
        orch._logger.info(
            "Seeded base scaffold (commit %s): %s",
            (sha or "noop")[:12], ", ".join(Path(p).name for p in result["written"]),
        )

    def register_contract_surface(self) -> None:
        """Register the FIXED contract surface (spine tables + AS/auth endpoints)
        in RegistryHub/SchemaHub under actor='orchestrator', post-kickoff.

        Consistency-by-construction: the tenancy spine tables and the embedded-AS
        / first-party-auth endpoints are deterministic and runtime-owned, so the
        orchestrator publishes them to the contract truth-source rather than
        relying on prose + a hardcoded delivery-gate exemption. The AS/auth
        endpoints are tagged ``kind='auth'|'oauth'`` so the frontend's
        response_key-keyed api.js generator SKIPS them (they are fixed-spec with
        heterogeneous shapes — a 302 redirect, a {access_token}, a JWKS doc).

        Idempotent: RegistryHub/SchemaHub register_* are merge-upserts keyed on
        (method, path) / table name (Charter §8 — re-registration never errors)."""
        from .database_scaffold import SPINE_TABLE_RECORDS
        from .oauth_scaffold import AS_CONTRACT_ENDPOINTS
        from .control_plane import CONTROL_SURFACE_ENDPOINTS

        orch = self._orch
        tables_n = 0
        for rec in SPINE_TABLE_RECORDS:
            try:
                orch.hubs.schema_hub.register_table(
                    name=rec["name"],
                    schema={"columns": rec["columns"]},
                    provider="backend",
                    agent="orchestrator",
                    status="implemented",
                    kind="spine",
                )
                tables_n += 1
            except Exception as exc:  # never block the run on a contract publish
                orch._logger.warning("spine table register failed (%s): %s", rec["name"], exc)

        eps_n = 0
        for ep in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS):
            try:
                orch.hubs.registryhub.register_endpoint(
                    method=ep["method"],
                    path=ep["path"],
                    schema={"request": ep.get("request", {}), "response": ep.get("response", {})},
                    provider="backend",
                    agent="orchestrator",
                    status="implemented",
                    kind=ep["kind"],
                    auth_required=ep.get("auth_required", False),
                    summary=ep.get("summary", ""),
                )
                eps_n += 1
            except Exception as exc:
                orch._logger.warning("fixed endpoint register failed (%s %s): %s",
                                     ep["method"], ep["path"], exc)

        orch._logger.info(
            "Registered fixed contract surface: %d spine table(s) + %d auth/oauth/infra endpoint(s)",
            tables_n, eps_n,
        )

    async def generate_mcp(self) -> None:
        """Project the FastMCP server (``mcp_server/<env>/``) 1:1 from the
        registered BUSINESS endpoints + register the server and its tools.

        Consistency-by-construction (Phase 3c): the MCP tool surface is a
        deterministic projection of the RegistryHub business contract, so it cannot
        drift from the endpoints — the runtime emits it; an LLM never re-authors
        an MCP server. Only BUSINESS endpoints become tools; the fixed
        auth/oauth/infra/spine surface is excluded (it's protocol/infra, not an
        agent-drivable operation).

        Registered with ``status='implemented'`` — which (a) exempts the tools
        from the dead-tool coverage gate (they are consumed by the EXTERNAL
        red-team agent, not the env's own frontend, so zero internal consumers is
        correct by construction) and (b) makes RunHub skip the in-run liveness
        probe (the agentsuite-red pool launches + probes the MCP, not env-gen).
        Post-kickoff, untracked ``output_dir`` write (like the DB DDL)."""
        from .mcp_scaffold import write_mcp_server, business_endpoints

        orch = self._orch
        endpoints = orch.hubs.registryhub.get_endpoints() or {}
        if not business_endpoints(endpoints):
            orch._logger.info("No business endpoints registered — skipping MCP projection.")
            return

        env_name = "app"
        # SPEC TOOL NAMES (2026-06-11): when the compiled reference spec binds
        # MCP tools to endpoints, the server emits the SPEC'S semantic names
        # (get_profile_info, publish_media, ...) — the 22 mcp_tool_exists
        # deliverability gates then bind by construction instead of failing on
        # derived endpoint-style names.
        _aliases = {}
        try:
            from .mcp_scaffold import spec_tool_aliases
            import json as _json
            _spec_path = Path(orch.output_dir) / "design" / "reference_spec.json"
            if _spec_path.is_file():
                _aliases = spec_tool_aliases(_json.loads(_spec_path.read_text()))
                if _aliases:
                    orch._logger.info("MCP spec tool aliases: %d bound", len(_aliases))
        except Exception:
            _aliases = {}
        result = write_mcp_server(orch.output_dir, endpoints, env_name=env_name,
                                  tool_aliases=_aliases)

        mcp_reg = getattr(orch.hubs, "mcp_registry", None)
        if mcp_reg is None:
            orch._logger.warning(
                "mcp_registry unavailable — emitted mcp_server/%s/ (%d tools) but did not register.",
                env_name, result["tool_count"],
            )
            return

        try:
            mcp_reg.register_mcp_server(
                name=env_name, transport="http",
                endpoint=f"mcp_server/{env_name}/main.py",
                provider="backend", agent="orchestrator", status="implemented",
            )
            registered = 0
            for rec in result["tools"]:
                res = mcp_reg.register_mcp_tool(
                    server_name=env_name, tool_name=rec["tool_name"],
                    schema=rec["schema"], provider="backend",
                    agent="orchestrator", status="implemented",
                )
                if isinstance(res, dict) and res.get("error"):
                    orch._logger.warning("MCP tool register failed (%s): %s",
                                         rec["tool_name"], res["error"])
                else:
                    registered += 1
            orch._logger.info(
                "Projected MCP server mcp_server/%s/: %d tool(s) emitted, %d registered.",
                env_name, result["tool_count"], registered,
            )
        except Exception as exc:  # never block the run on a contract publish
            orch._logger.warning("MCP registration failed: %s", exc)

    def scaffold_design_readme(self) -> None:
        """The delivery gate requires ``design/README.md`` (a design artifact the
        kickoff coordinator is meant to author). When no lane writes it, the run
        cuts a release via api_smoke but the FINAL delivery gate fails on the
        missing file → Status FAILED on an otherwise-working app. Framework-scaffold
        a project README from the registered contract (write-if-missing, idempotent,
        best-effort)."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            readme = out_dir / "design" / "README.md"
            if readme.exists() and readme.read_text(encoding="utf-8", errors="ignore").strip():
                return
            name = out_dir.name or "app"
            lines = [
                f"# {name}", "",
                "Generated full-stack application — FastAPI backend, React/Vite "
                "frontend, PostgreSQL, embedded OAuth2 (RS256 JWT).", "",
            ]
            eps = []
            registryhub = getattr(getattr(orch, "hubs", None), "registryhub", None)
            if registryhub is not None:
                try:
                    from .lifecycle import business_endpoints
                    for e in business_endpoints(registryhub.get_endpoints() or {}):
                        if isinstance(e, dict) and e.get("method") and e.get("path"):
                            eps.append((str(e["method"]).upper(), str(e["path"]),
                                        str(e.get("summary") or "")))
                except Exception:
                    pass
            if eps:
                lines += ["## API", ""]
                for m, p, s in sorted(set(eps)):
                    lines.append(f"- `{m} {p}`" + (f" — {s}" if s else ""))
                lines.append("")
            lines += ["## Run", "", "```bash",
                      "cd docker && docker compose up -d --build", "```", ""]
            readme.parent.mkdir(parents=True, exist_ok=True)
            readme.write_text("\n".join(lines), encoding="utf-8")
            _log = getattr(orch, "_logger", None)
            if _log is not None:
                _log.warning(
                    "Scaffolded design/README.md (delivery-gate required artifact)")
        except Exception:
            pass  # best-effort; logger may be absent in minimal/test contexts

    def scaffold_frontend_baseline(self) -> None:
        """FIX #40: gap-fill a minimal buildable frontend (infra + login/feed UI)
        for any standard file the frontend lane left missing/empty. The frontend
        lane variably produces NOTHING (empty app/frontend/ → no Dockerfile →
        docker build can't start → docker_up FAIL → no delivery). Best-effort;
        never clobbers files the lane wrote."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from .frontend_scaffold import (
                scaffold_frontend_baseline, pin_frontend_build_tooling)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = scaffold_frontend_baseline(fe)
            if rep.get("scaffolded"):
                orch._logger.warning(
                    "Frontend baseline scaffolded (lane left it incomplete): %s",
                    rep.get("written"))
            # FIX #44: force the build tooling to known-good pinned versions so the
            # image always builds (the lane writes "latest" everywhere → tailwind v4
            # vs v3 postcss config → npm build dies).
            pin = pin_frontend_build_tooling(fe)
            if pin.get("pinned"):
                orch._logger.warning(
                    "Frontend build tooling pinned to known-good: %s", pin.get("changed"))
        except Exception as exc:
            orch._logger.debug("frontend baseline scaffold skipped: %s", exc)

    def scaffold_frontend_pages(self) -> None:
        """Project a page-component STUB per registered ui_page + wire React-Router
        routes — the frontend analogue of the deterministic backend skeleton
        (generate_database / backend models from the contract).

        Closes the build-asymmetry root cause (youtube run #13): the backend is
        framework-scaffolded so it completes reliably; the frontend had to
        hand-author every page + routing from scratch → built 1 page, left the
        rest in_progress, declared a hallucinated done (blank shell). Run once
        after finalize: the lane then FILLS page bodies (write/edit) instead of
        authoring from nothing, and the app is navigable-by-construction. Stubs
        are written only-if-missing; App.jsx only (re)written while it carries the
        @framework-managed-routes marker (the lane deletes it to take over). Also
        replaces the social-shaped baseline App.jsx (login/feed) with a generic
        router → domain-agnostic. Best-effort; never raises."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            ui_pages = []
            registryhub = getattr(orch.hubs, "registryhub", None)
            if registryhub is not None and hasattr(registryhub, "list_ui_pages"):
                ui_pages = list((registryhub.list_ui_pages() or {}).values())
            # #225: the measured design screens are ground truth for the page
            # set — register a ui_page for every classified page route the
            # kickoff under-declared (r19: ONE page declared for the whole
            # surface). Idempotent (route-covered screens skip).
            if registryhub is not None and hasattr(registryhub, "register_ui_page"):
                try:
                    import json as _json
                    from pathlib import Path as _DP
                    from .frontend_scaffold import missing_design_screen_pages, backfill_page_apis
                    _ds_p = _DP(out_dir) / "design" / "design_system.json"
                    if _ds_p.exists():
                        _design = _json.loads(_ds_p.read_text(encoding="utf-8"))
                        _eps = []
                        if hasattr(registryhub, "get_endpoints"):
                            _eps = list((registryhub.get_endpoints() or {}).values())
                        for _spec in missing_design_screen_pages(_design, ui_pages, _eps):
                            try:
                                registryhub.register_ui_page(
                                    _spec["name"], route=_spec["route"],
                                    component=_spec["component"],
                                    apis_used=_spec["apis_used"],
                                    agent="orchestrator",
                                    **(_spec.get("metadata") or {}))
                                orch._logger.info(
                                    "#225 registered design-screen ui_page %s (%s)",
                                    _spec["name"], _spec["route"])
                            except Exception:
                                continue
                        ui_pages = list((registryhub.list_ui_pages() or {}).values())
                    # Backfill apis_used for pages that declared none (e.g. kickoff's
                    # profiles/search) so they project a REAL data floor, not a fallback
                    # stub the delivery gate rejects (deliverability_frontend_fallback_page).
                    ui_pages = backfill_page_apis(ui_pages, _eps)
                except Exception as _exc:
                    orch._logger.debug("#225 design-screen page seeding skipped: %s", _exc)
            if not ui_pages:
                return
            from .frontend_scaffold import (drop_component_page_twins_1087,
                                             scaffold_pages_from_contract)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            # #1087: a name registered as a ui_COMPONENT is a component — do not project a
            # page stub for its blank-route page twin (see the helper for the measurement).
            ui_pages = drop_component_page_twins_1087(ui_pages, registryhub)
            rep = scaffold_pages_from_contract(fe, ui_pages)
            # #1202at: #951 detects the projector/lane tug-of-war, calls it "waste either
            # way", and then clobbers anyway while telling nobody who could stop it. r32
            # burned three rounds each on GenresPage and LoginPage; the lane never learns
            # its work was discarded, so it rewrites the page and loses it again.
            #
            # The exit is a fact only the framework holds: #914/#1020 KEEPS a lane page
            # that imports `../components/` and replaces one that does not. So the lane
            # can keep every line it wrote by moving the body into a component — no
            # policy change, no judge weakened, and the same projection still wins for
            # the stubs it was built for. Own try (#1201); #672's twin-check stops a
            # re-run filing it twice.
            try:
                from .frontend_scaffold import scaffold_loop_pages_1202at
                from .message_format import join_capped
                _loop1202at = scaffold_loop_pages_1202at(fe)
                if _loop1202at:
                    _names = sorted(_loop1202at)
                    # #1202bn: one task per CHANGED finding, not one per scaffold pass —
                    # create_task does not deduplicate (#672 only reports a twin).
                    from .message_format import state_changed_1202ad as _sc1202at
                    if _sc1202at("task:scaffold_loop_pages", tuple(sorted(map(str, _loop1202at or ())))):
                        orch.hubs.workhub.create_task(
                            title=("Keep %d page(s) the projector keeps overwriting"
                                   % len(_names))[:180],
                            description=_loop_page_advice_1202gq(
                                _names, {str(p.get("name") or ""): p
                                         for p in (ui_pages or []) if isinstance(p, dict)}),
                            assignee="frontend", agent="scaffolder", priority="P1",
                            kind="fidelity")
            except Exception as _t1202at:
                orch._logger.warning(
                    "#1202at could not tell the frontend lane about the projection loop "
                    "(%s: %s) — the loop stays invisible to the only agent that can end "
                    "it, which is the state this exists to fix.",
                    type(_t1202at).__name__, str(_t1202at)[:110])
            # #1199: REPORT pages whose `apis_used` disagrees with the code that shipped. The
            # declaration is written once at registration and nothing checks it again, while
            # 84 call sites read it (gates, `_all_get_endpoints`, the #627/#629 consumer
            # index). Runs post-merge, so it sees the lane's page. Never wipes: a page whose
            # endpoints cannot be resolved is left exactly as declared.
            # #1202j: an asset the code references that nothing ever staged is a 404 the
            # visual judge scores as a broken render. Own try (#1201).
            try:
                from .frontend_scaffold import unstaged_asset_refs_1202j
                from .message_format import join_capped
                _as1202j = unstaged_asset_refs_1202j(
                    fe, _P(out_dir) / "app" / "backend" / "seed_data.json")
                # #1202ac: once per DISTINCT set, not once per scaffold pass. r32 logged
                # 117 copies of this line for one unchanging list — the same noise I removed
                # from the heal declines (#1202n), the drift report (#1202p), the seed audit
                # (#1202v) and the lane-page verdict (#1202ab), reintroduced by me here. A
                # set that CHANGES is reported again; standing still is quiet.
                if _as1202j:
                    _key1202ac = tuple(sorted(_as1202j))
                    if getattr(orch, "_unstaged_assets_said_1202ac", None) != _key1202ac:
                        orch._unstaged_assets_said_1202ac = _key1202ac
                        orch._logger.warning(
                            "#1202j %d asset path(s) are referenced but exist nowhere in the "
                            "tree — they will 404 and the visual judge will score the hole they "
                            "leave (#113's symptom, a cause it does not cover). Stage them into "
                            "design/assets or stop referencing them: %s",
                            len(_as1202j), join_capped(_as1202j, total=len(_as1202j)))
            except Exception as _e1202j:
                from .message_format import warn_once_1201
                warn_once_1201("unstaged_asset_refs_1202j",
                               "the unstaged-asset report (#1202j)", _e1202j)
            # #1202cp: the same reference WITHOUT the leading slash. #1202j requires one, so
            # the relative form was invisible to it, which is how #1202co survived: the DB
            # held `assets/posters/x.jpg`, twelve render sites emitted it verbatim, and on
            # /browse the browser asked for /browse/assets/posters/x.jpg and got 200 +
            # index.html from the SPA fallback. Not a 404 — so no probe, no console error and
            # no gate ever saw it, and eleven screens scored a median 0.27 with every hero
            # black. #1202co fixes the source; this catches whatever gets past it. Own try.
            try:
                from .frontend_scaffold import relative_asset_refs_1202cp
                from .message_format import join_capped as _jc1202cp
                from .message_format import state_changed_1202ad as _sc1202cp
                _rel = relative_asset_refs_1202cp(
                    fe, _P(out_dir) / "app" / "backend" / "seed_dataset.json")
                if _rel and _sc1202cp("rel_assets:%s" % out_dir, tuple(_rel)):
                    orch._logger.warning(
                        "#1202cp %d asset path(s) are NOT root-relative — they resolve "
                        "against whatever route is open, and on a SPA every one of those "
                        "URLs answers 200 with the app shell, so the image renders as "
                        "nothing and reports no error: %s",
                        len(_rel), _jc1202cp(_rel, total=len(_rel), cap=4))
                    try:
                        if _sc1202cp("task:rel_assets", tuple(sorted(map(str, _rel or ())))):
                            orch.hubs.workhub.create_task(
                                title=("Root-relative %d asset path(s) — they fetch the app "
                                       "shell, not the image" % len(_rel))[:180],
                                description=(
                                    "These paths lack a leading slash, so the browser "
                                    "resolves them against the current route:\n\n"
                                    + _jc1202cp(["  - " + x for x in _rel],
                                                total=len(_rel), cap=12, sep="\n")
                                    + "\n\nOn /browse, `assets/posters/x.jpg` is fetched as "
                                    "/browse/assets/posters/x.jpg, and the SPA fallback "
                                    "answers 200 with index.html — NOT a 404. The <img> "
                                    "receives HTML, renders nothing, and no console error, "
                                    "network error or gate can see it. Prefix each with `/` "
                                    "so it resolves from the site root on every route "
                                    "(#1202cp)."),
                                assignee="frontend", agent="scaffolder", priority="P1",
                                kind="fidelity")
                    except Exception:
                        pass
            except Exception as _e1202cp:
                from .message_format import warn_once_1201
                warn_once_1201("relative_asset_refs_1202cp",
                               "the relative-asset report (#1202cp)", _e1202cp)
            # #1202ax: a seeded media URL on an RFC 2606 reserved domain is a guaranteed
            # 404 — example.com exists so that it never serves real content — and the
            # visual judge scores it as a broken render. #1202j catches a LOCAL path that
            # is missing; an external URL walks past it because there is no local path to
            # miss. 20 of 119 corpus runs with a delivered app ship at least one, three
            # hand-checked, and one of them (`https://example.com/avatar{i}.jpg`) is an
            # unformatted f-string that reached the data as literal text.
            #
            # Unlike #844's unseeded entity, which the lane provably CANNOT fix (#807
            # replaces its rows wholesale), this lives in files the backend lane owns,
            # so it is worth its inbox. Own try (#1201).
            try:
                from .backend_audit import placeholder_media_urls_1202ax
                from .message_format import join_capped
                _ph1202ax = placeholder_media_urls_1202ax(_P(out_dir))
                if _ph1202ax:
                    # #1202bn: one task per CHANGED finding, not one per scaffold pass —
                    # create_task does not deduplicate (#672 only reports a twin).
                    from .message_format import state_changed_1202ad as _sc1202ax
                    if _sc1202ax("task:reserved_domain_urls", tuple(sorted(map(str, _ph1202ax or ())))):
                        orch.hubs.workhub.create_task(
                            title=("Replace %d seeded media URL(s) that can never load"
                                   % len(_ph1202ax))[:180],
                            description=(
                                "These seeded URLs point at example.com/.org/.net, which RFC "
                                "2606 reserves so that it NEVER serves real content — every one "
                                "renders as a broken image and the visual judge scores it that "
                                "way: %s.\n\nPoint them at an asset that is actually staged in "
                                "this project, or drop the field. If one contains a literal "
                                "`{...}`, it is an unformatted f-string that reached the data as "
                                "text." % join_capped(_ph1202ax, total=len(_ph1202ax), cap=6)),
                            assignee="backend", agent="scaffolder", priority="P2",
                            kind="fidelity")
            except Exception as _e1202ax:
                warn_once_1201("placeholder_media_urls_1202ax",
                               "the reserved-domain media URL report (#1202ax)", _e1202ax)
            # #1202bm: a handler that judges an input INVALID and then stores a valid one in
            # its place. r32, live: `POST /api/titles/1/rating {"value":"garbage_not_a_rating"}`
            # returns 201 and records "thumbs_up". The lane wrote the reason and the reason is
            # the point — "persist a valid default instead of rejecting the multi-step business
            # flow" — so a chain step that would 400 was made unable to, and the endpoint now
            # records a positive rating for anything, including nothing. The frontend has had a
            # fabricated-fallback gate since #191; the backend had none. Own try (#1201).
            try:
                from .backend_audit import invalid_value_defaults_1202bm
                from .message_format import join_capped as _jc1202bm
                _iv1202bm = invalid_value_defaults_1202bm(_P(out_dir))
                if _iv1202bm:
                    # #1202bn: file on a CHANGED finding, not once per scaffold pass.
                    # create_task has no duplicate check — #672 only REPORTS a twin and
                    # says so ("This does NOT block") — and the scaffold ran 117 times in
                    # r32, so a finding that persists until a lane fixes it would file 117
                    # tasks. The corpus already measures that cost: of 838 cancelled tasks,
                    # 462 (55%, across 79 of 144 runs) were cancelled as duplicates.
                    from .message_format import state_changed_1202ad as _sc1202bm
                    if _sc1202bm("task:invalid_value_defaults", tuple(sorted(map(str, _iv1202bm)))):
                        orch.hubs.workhub.create_task(
                            title=("Reject %d invalid value(s) instead of storing a substitute"
                                   % len(_iv1202bm))[:180],
                            description=(
                                "These handlers decide an input is invalid and then store a "
                                "different, valid-looking value and answer 201, so the caller is "
                                "told its value was saved when a substitute was: %s.\n\nRaise "
                                "HTTPException(400) instead. Normalising aliases (\"like\" -> "
                                "\"thumbs_up\") is correct and is not what this is about; the "
                                "problem is the branch that has already judged the input invalid. "
                                "If a chain sends a value the schema cannot take, the chain or the "
                                "contract is what needs fixing."
                                % _jc1202bm(_iv1202bm, total=len(_iv1202bm), cap=5)),
                            assignee="backend", agent="scaffolder", priority="P2", kind="fidelity")
            except Exception as _e1202bm:
                warn_once_1201("invalid_value_defaults_1202bm",
                               "the invalid-value-substitution report (#1202bm)", _e1202bm)
            # #1202ai: a prop the component never declares is dropped by React with no
            # runtime symptom — no console error, no failed request — so every gate stays
            # green while the feature does nothing. 232 occurrences across 51 of the 117
            # corpus environments. Reports; the inference is static and #1199 already taught
            # this repo what static inference costs when it writes. Own try (#1201).
            try:
                from .frontend_audit import dropped_prop_findings_1202ai
                from .message_format import join_capped, state_changed_1202ad
                _dp = dropped_prop_findings_1202ai(fe / "src")
                if _dp and state_changed_1202ad("dropped_props:%s" % out_dir, tuple(_dp)):
                    orch._logger.warning(
                        "#1202ai %d prop(s) are passed to a component that never declares or "
                        "mentions them — React drops them silently, so whatever they were for "
                        "does nothing and no gate can see it: %s",
                        len(_dp), join_capped(_dp, total=len(_dp), cap=4))
                    # #1202aj: and to the LANE, not only to the logger. A finding nobody is
                    # assigned is a finding nobody fixes — #780 exists for exactly that reason
                    # and measured its own log-only fallback at 1 filed task across 154 runs.
                    # This defect has no runtime symptom at all, so the log line is the ONLY
                    # thing standing between it and shipping: 232 occurrences across 51 of the
                    # 117 corpus environments, every gate green in all of them. create_task's
                    # own #672 twin-check keeps a re-run from filing it twice.
                    try:
                        # #1202bn: one task per CHANGED finding, not one per scaffold pass —
                        # create_task does not deduplicate (#672 only reports a twin).
                        from .message_format import state_changed_1202ad as _sc1202aj
                        if _sc1202aj("task:dropped_props", tuple(sorted(map(str, _dp or ())))):
                            orch.hubs.workhub.create_task(
                                title=("Wire %d dropped prop(s) — passed but never received"
                                       % len(_dp))[:180],
                                description=(
                                    "These props are passed in JSX to a component that never "
                                    "declares or mentions them, so React drops them and the "
                                    "behaviour they were for does nothing:\n\n"
                                    # #1034: a count must not sit beside a silently truncated
                                    # list — join_capped declares the remainder it drops.
                                    + join_capped(["  - " + x for x in _dp],
                                                  total=len(_dp), cap=12, sep="\n")
                                    + "\n\nThere is NO runtime symptom — no console error, no "
                                    "failed request, no 404 — so no gate can catch this. Fix each "
                                    "by destructuring the prop in the component and using it, or "
                                    "by removing it from the call if it is genuinely unwanted. "
                                    "Measured across the corpus: 232 occurrences in 51 of 117 "
                                    "environments (#1202ai)."),
                                assignee="frontend", agent="scaffolder", priority="P2",
                                kind="fidelity")
                    except Exception as _t1202aj:
                        orch._logger.warning(
                            "#1202aj could not file the dropped-prop task (%s: %s) — the "
                            "finding is log-only again, which is the state this exists to end.",
                            type(_t1202aj).__name__, str(_t1202aj)[:110])
            except Exception as _e1202ai:
                from .message_format import warn_once_1201
                warn_once_1201("dropped_prop_findings_1202ai",
                               "the dropped-prop report (#1202ai)", _e1202ai)
            # #1202cj: a routed authenticated page that imports nothing from components/
            # while its siblings do. `components` is the weakest of the seven judged
            # dimensions across 31 netflix runs and 333 screen judgments (0.478 mean; color,
            # which design-prep measures deterministically, is the strongest at 0.676), and
            # a page that shares nothing re-invents the chrome — usually omitting it.
            # Corpus: 13 of 130 routed auth pages, clustered rather than spread (r13 alone
            # has eight). REPORTS only, like #1202ai: a full-screen player legitimately owns
            # its whole surface, which is why the finding names the sibling count instead of
            # asserting a rule. Own try (#1201).
            try:
                from .frontend_audit import orphan_auth_page_findings_1202cj
                from .message_format import join_capped as _jc1202cj
                from .message_format import state_changed_1202ad as _sc1202cj
                _op = orphan_auth_page_findings_1202cj(fe / "src")
                if _op and _sc1202cj("orphan_auth_pages:%s" % out_dir, tuple(_op)):
                    # r37 reported this twenty times in an hour with the count swinging
                    # 11/3/12/10/4, and a reader could not tell why. The scaffolder runs per
                    # LANE WORKTREE, so each number was true of a different tree — the state
                    # gate was keyed correctly (`fe` is derived from `out_dir`) and the trees
                    # genuinely differ. What was missing is which tree, so name it: an
                    # oscillation that is legible is a measurement, one that is not is noise.
                    try:
                        _where = str(_P(out_dir).name)
                        if _P(out_dir).parent.name == "worktrees":
                            _where = "worktrees/" + _where
                    except Exception:
                        _where = "?"
                    orch._logger.warning(
                        "#1202cj [%s] %d authenticated page(s) share no component with their "
                        "siblings — each re-invents the shared chrome, and the visual "
                        "judge's most repeated component deviation is a missing header/nav: "
                        "%s", _where, len(_op), _jc1202cj(_op, total=len(_op), cap=4))
                    # #780 / #947: a finding that reaches only a logger reaches nobody —
                    # measured at 1 filed task across 154 runs. File it, and let the LANE
                    # judge the exception: a full-screen player legitimately owns its whole
                    # surface, which is why the task asks rather than asserts.
                    try:
                        if _sc1202cj("task:orphan_auth_pages",
                                     tuple(sorted(map(str, _op or ())))):
                            orch.hubs.workhub.create_task(
                                title=("Give %d page(s) the shared chrome, or say why they "
                                       "own their surface" % len(_op))[:180],
                                description=(
                                    "These pages are routed behind RequireAuth and import "
                                    "nothing from components/, while their siblings do. A "
                                    "page that shares nothing re-invents the chrome and "
                                    "usually omits it:\n\n"
                                    + _jc1202cj(["  - " + x for x in _op],
                                                total=len(_op), cap=12, sep="\n")
                                    + "\n\nFor each: mount the same header/nav its siblings "
                                    "use, OR — if the screen genuinely owns its whole surface, "
                                    "as a full-screen player does — reply saying so and leave "
                                    "it. `components` is the weakest of the seven judged "
                                    "dimensions (0.478 mean over 31 runs and 333 screen "
                                    "judgments; `color`, which is measured deterministically, "
                                    "is strongest at 0.676), and the judge's most repeated "
                                    "component deviation is a missing header/nav. Scanned "
                                    "tree: " + _where + " (#1202cj)."),
                                assignee="frontend", agent="scaffolder", priority="P2",
                                kind="fidelity")
                    except Exception:
                        pass
            except Exception as _e1202cj:
                from .message_format import warn_once_1201
                warn_once_1201("orphan_auth_page_findings_1202cj",
                               "the orphan auth-page report (#1202cj)", _e1202cj)
            # #1202bg: a handler that is present and does nothing. `onClick={() => {}}` renders
            # a control that looks live, hovers, and answers a click with silence — the shape of
            # "everything renders and nothing works". 24 of 117 delivered frontends carry one;
            # tiktok-web-r91's login modal wires EVERY option row that way, so QR / Facebook /
            # Google / Apple sign-in all look available and do nothing.
            #
            # No existing check sees it: the element is there, the prop is there, the page
            # renders, so dead-nav, fallback-page, bare-fetch and invented-field all pass it.
            # The frontend lane owns these files, so it gets the task. Own try (#1201).
            try:
                from .frontend_audit import noop_handler_findings_1202bg
                from .message_format import join_capped as _jc1202bg
                _nh1202bg = noop_handler_findings_1202bg(fe / "src")
                if _nh1202bg:
                    # #1202bn: file on a CHANGED finding, not once per scaffold pass.
                    # create_task has no duplicate check — #672 only REPORTS a twin and
                    # says so ("This does NOT block") — and the scaffold ran 117 times in
                    # r32, so a finding that persists until a lane fixes it would file 117
                    # tasks. The corpus already measures that cost: of 838 cancelled tasks,
                    # 462 (55%, across 79 of 144 runs) were cancelled as duplicates.
                    from .message_format import state_changed_1202ad as _sc1202bg
                    if _sc1202bg("task:noop_handlers", tuple(sorted(map(str, _nh1202bg)))):
                        orch.hubs.workhub.create_task(
                            title=("Wire %d control(s) whose handler does nothing"
                                   % len(_nh1202bg))[:180],
                            description=(
                                "These handlers have an empty body, so the control renders, hovers "
                                "and responds to a click by doing nothing — it looks available and "
                                "is not: %s.\n\nGive each one its real behaviour, or remove the "
                                "control. A console.log-only body counts here too: it is a debugging "
                                "stub that reached delivery."
                                % _jc1202bg(_nh1202bg, total=len(_nh1202bg), cap=6)),
                            assignee="frontend", agent="scaffolder", priority="P1",
                            kind="fidelity")
            except Exception as _e1202bg:
                from .message_format import warn_once_1201 as _w1202bg
                _w1202bg("noop_handler_findings_1202bg",
                         "the no-op handler report (#1202bg)", _e1202bg)
            try:
                from .frontend_scaffold import reconcile_ui_page_apis_1199
                _rec1199 = reconcile_ui_page_apis_1199(fe, ui_pages, registryhub)
                if _rec1199.get("reconciled"):
                    # #1034: a count must not sit beside a silently truncated list.
                    from .message_format import join_capped
                    orch._logger.warning(
                        "#1199 %d ui_page declaration(s) disagree with the shipped code (reported, not rewritten — see #1202d): %s",
                        len(_rec1199["reconciled"]),
                        join_capped([r["page"] for r in _rec1199["reconciled"]],
                                    total=len(_rec1199["reconciled"])))
                    # #1202bh: and to the LANE, not only the logger. The reconciler's own comment
                    # says the finding belongs to "the lane that owns it", and it has never been
                    # handed there — frontend_scaffold files no tasks at all. This one is worth an
                    # inbox more than most: `apis_used` is read by 84 call sites INCLUDING THE
                    # GATES, so a wrong declaration means a gate checks the wrong endpoint and
                    # passes. r30 shipped `browse_by_languages_page` declaring ['/api/profiles']
                    # while the page reaches ['/api/titles'].
                    #
                    # Reporting, still not rewriting: #1202d made this report-only because
                    # auto-rewriting produced false rewrites on tiktok, googlemaps and instagram.
                    # A task changes nothing on disk, so that decision is untouched.
                    try:
                        _pairs1202bh = [
                            "%s: declares %s, code reaches %s" % (
                                r.get("page"),
                                join_capped(r.get("was") or [], total=len(r.get("was") or []), cap=3),
                                join_capped(r.get("now") or [], total=len(r.get("now") or []), cap=3))
                            for r in _rec1199["reconciled"]]
                        # #1202bn: one task per CHANGED finding, not one per scaffold pass —
                        # create_task does not deduplicate (#672 only reports a twin).
                        from .message_format import state_changed_1202ad as _sc1202bh
                        if _sc1202bh("task:declaration_drift", tuple(sorted(map(str, _pairs1202bh or ())))):
                            orch.hubs.workhub.create_task(
                                title=("Fix %d ui_page api declaration(s) that disagree with the code"
                                       % len(_pairs1202bh))[:180],
                                description=(
                                    "The `apis_used` on these pages does not match what the shipped code "
                                    "calls: %s.\n\n84 call sites read that field, including the delivery "
                                    "gates, so a wrong declaration makes a gate check an endpoint the page "
                                    "never touches — and pass. Re-register each page with the endpoints it "
                                    "actually calls, or change the page to call what it declared. Nothing "
                                    "was rewritten for you: #1202d found auto-reconciliation produced false "
                                    "rewrites, so this is yours to decide."
                                    % join_capped(_pairs1202bh, total=len(_pairs1202bh), cap=6)),
                                assignee="frontend", agent="scaffolder", priority="P1", kind="contract")
                    except Exception as _e1202bh:
                        warn_once_1201("declaration_drift_1202bh",
                                       "the declaration-drift task (#1202bh)", _e1202bh)
            except Exception as _e1201c:
                # #1201: the import itself can fail here, and this guard used to end in
                # `pass` — the detector that intersects "guarded import" with "log marker
                # never seen in the corpus" pointed at this exact line.
                from .message_format import warn_once_1201
                warn_once_1201("reconcile_wiring_1199",
                               "apis_used reconciliation wiring (#1199)", _e1201c)
            if rep.get("scaffolded") or rep.get("app_wired"):
                orch._logger.info(
                    "Frontend pages projected from contract: %d stub(s), "
                    "%d route(s) wired (app_wired=%s)",
                    len(rep.get("scaffolded") or []), rep.get("routes", 0),
                    rep.get("app_wired"))
            # #440: recover the lane's HIGH-FIDELITY nav (e.g. NetflixTopNav) into the
            # projector pages — the lane authors a rich nav/header component but leaves
            # it ORPHANED while the projector's generic inline nav ships. Safe no-op
            # when the lane authored none / it isn't merged into `fe` yet; never raises.
            try:
                from .frontend_scaffold import recover_agent_nav
                _nrep = recover_agent_nav(fe)
                if _nrep.get("rewired"):
                    orch._logger.info(
                        "#440 recovered agent nav '%s' into %d page(s): %s",
                        _nrep.get("nav"), len(_nrep["rewired"]), _nrep["rewired"])
            except Exception as _e:
                orch._logger.debug("#440 agent-nav recovery skipped: %s", _e)
            # #576: a projected page that renders NO nav is invisible to #440 (which only
            # REWIRES an existing one), so it ships without the app's own chrome — r139
            # genre_category 0.28 vs browse_home 0.85, the single screen holding the visual
            # average under the bar. Mount the app's majority-shared component on it.
            try:
                from .frontend_scaffold import mount_shared_nav_on_projected_pages
                _mrep = mount_shared_nav_on_projected_pages(fe)
                if _mrep.get("mounted"):
                    orch._logger.info(
                        "#576 mounted shared nav '%s' on %d chrome-less projected page(s): %s",
                        _mrep.get("nav"), len(_mrep["mounted"]), _mrep["mounted"])
            except Exception as _e:
                orch._logger.debug("#576 shared-nav mount skipped: %s", _e)
            # #534/#535: wire the CORRECT-but-unwired archetype components — a detail
            # route mis-shipped as a video player gets the lane's detail modal; an
            # owned-items list page (My List) gets the shared nav + poster-grid shell.
            # Both are safe no-ops (byte-identical) when the components are absent.
            try:
                from .frontend_scaffold import (
                    wire_detail_modal_534, wire_owned_list_shell_535)
                _dm = wire_detail_modal_534(fe)
                if _dm.get("wired"):
                    orch._logger.info("#534 wired detail modal '%s' into %s",
                                      _dm.get("modal"), _dm.get("wired"))
                _ol = wire_owned_list_shell_535(fe)
                if _ol.get("wired"):
                    orch._logger.info(
                        "#535 wired owned-list shell (nav '%s', grid '%s') into %s",
                        _ol.get("nav"), _ol.get("grid"), _ol["wired"])
            except Exception as _e:
                orch._logger.debug("#534/#535 archetype wiring skipped: %s", _e)
        except Exception as exc:
            orch._logger.debug("frontend page projection skipped: %s", exc)
