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
            from .backend_skeleton import write_backend_skeleton
            from .lifecycle import business_endpoints
            from .database_scaffold import synthesize_missing_tables
            sh = getattr(orch.hubs, "schema_hub", None)
            tables = (sh.list_tables() if sh else {}) or {}
            endpoints = business_endpoints(registryhub.get_endpoints() or {}) if registryhub else []
            if not tables and not endpoints:
                return  # contract not finalized yet — nothing to project
            # Contract completeness: derive a backing table for any creatable
            # business resource that has an endpoint but no registered table, so
            # the projector emits a REAL handler (not a stub) for it (large apps).
            tables = synthesize_missing_tables(tables, endpoints)
            # VERIFIER-DRIVEN read isolation at the FULL-SKELETON site (outlook run-34):
            # render_skeleton_main owner-scopes reads from table METADATA only, and the
            # chain-probed union previously applied ONLY in project_missing_routes (which
            # never touches routes the skeleton already wrote) — so the full regen kept
            # emitting UNSCOPED by-id GETs for isolation-probed tables. Once the lane's
            # (properly scoped) custom route died at import, the unscoped projected read
            # leaked cross-user rows → isolation probes failed 7 cycles → STUCK abort.
            # Union the probe signal into the LOCAL metadata before rendering — derived
            # from persisted chains, so it re-applies deterministically every regen.
            try:
                from .heal_pipeline import _isolation_scoped_tables_from_chains
                _probed = _isolation_scoped_tables_from_chains(
                    registryhub, set(tables.keys())) if registryhub else set()
                for _t in _probed:
                    _rec = tables.get(_t)
                    if isinstance(_rec, dict):
                        _md = dict(_rec.get("metadata") or {})
                        _md["owner_scoped_reads"] = True
                        _rec = dict(_rec)
                        _rec["metadata"] = _md
                        tables[_t] = _rec
            except Exception:
                pass
            res = write_backend_skeleton(out_dir, endpoints, tables)
            orch._logger.warning(
                "BACKEND SKELETON generated by-construction from the contract "
                "(%d tables, %d endpoints) — the whole backend is framework-owned "
                "(deterministic, consistent, auth-enforced): %s",
                len(tables), len(endpoints), res.get("written"))
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
            from .frontend_audit import sync_ui_page_statuses
            _pa = sync_ui_page_statuses(orch.output_dir, orch.hubs.workhub,
                                        registryhub=getattr(orch.hubs, "registryhub", None))
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
        # git base pre-spawn so every lane inherits it; the backend then ADDS business
        # routes to it. Same "framework owns the boilerplate" basis as the AS modules.
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
        # Keep each lane's WORKING MEMORY out of git. memory-bank/<lane>/ is scratch
        # (the lane's notes + the framework's auto-synced STATE) — NOT deliverable code;
        # committing it bloated the repo + every release snapshot, and forced a bespoke
        # "auto-commit memory-bank before integration pull" dance (auto_commit.py) to keep
        # `git stash -u` from dropping it. Gitignoring it is strictly better: `git status`
        # no longer lists it (so that dance no-ops) AND `stash -u` SPARES ignored paths, so
        # it survives the per-tick merge for free — never committed, never in the deliverable.
        try:
            _gi = orch.output_dir / ".gitignore"
            _want = ["memory-bank/"]
            _cur = _gi.read_text(encoding="utf-8") if _gi.exists() else ""
            _new = [p for p in _want if p not in _cur.split()]
            if _new:
                _gi.write_text(
                    (_cur.rstrip() + "\n" if _cur.strip() else "") + "\n".join(_new) + "\n",
                    encoding="utf-8")
                rel_paths.append(".gitignore")
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
            if not ui_pages:
                return
            from .frontend_scaffold import scaffold_pages_from_contract
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = scaffold_pages_from_contract(fe, ui_pages)
            if rep.get("scaffolded") or rep.get("app_wired"):
                orch._logger.info(
                    "Frontend pages projected from contract: %d stub(s), "
                    "%d route(s) wired (app_wired=%s)",
                    len(rep.get("scaffolded") or []), rep.get("routes", 0),
                    rep.get("app_wired"))
        except Exception as exc:
            orch._logger.debug("frontend page projection skipped: %s", exc)
