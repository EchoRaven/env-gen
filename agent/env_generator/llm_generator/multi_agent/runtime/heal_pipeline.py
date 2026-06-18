"""Delivery-time heal / repair pipeline, extracted from the Orchestrator
(PROPOSAL #8 — HealPipeline).

A group of deterministic, best-effort repairs run against the integrated tree
before framework validation / delivery — each reconciles a recurring lane defect
(wrong-module auth imports, ORM↔DDL drift, declared-but-uncoded routes, handler
FK aliases, raw psycopg DSNs, missing AS wiring / uvicorn entrypoint, frontend
api.js drift) — plus the git merge/commit steps that surface committed lane work
and snapshot the framework's delivery writes.

⚠ CALL-ORDER IS LOAD-BEARING, but the order lives in the ORCHESTRATOR's callers
(merge → skeleton → projection → audit, etc.) — this class only GROUPS the
stateless step bodies; it never sequences them. Each method is an independent,
idempotent wrapper over runtime/* (and agents/runtime/auto_commit) and reads the
orchestrator's collaborators (output_dir / hubs / logger / llm) live via the
back-ref. Stateless → the orchestrator shims construct a fresh HealPipeline(self)
per call, so call sites + tests are unchanged.
"""

from __future__ import annotations

from typing import Any, List


class HealPipeline:
    """Groups the delivery-time repair/merge/commit steps. Stateless; borrows the
    orchestrator (output_dir / hubs / logger / llm) live."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    def repair_backend_auth(self) -> None:
        """FIX #45: the handlers gate on ``Depends(get_current_user)`` but the lane
        writes a placeholder that IGNORES the token (returns the first DB user) —
        the lane itself says "the full auth dependency is provided elsewhere in the
        complete scaffold". So the framework provides it: a real JWT-verifying
        ``auth_dependency.py`` + rewrite each route file's placeholder to import it.
        Best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .backend_scaffold import (
                repair_backend_auth_dependency, repair_auth_import_paths,
                repair_inline_token_auth, repair_auth_enforcement_middleware)
            be_dir = _P(out_dir) / "app" / "backend"
            rep = repair_backend_auth_dependency(be_dir)
            if rep.get("repaired"):
                orch._logger.warning(
                    "Backend auth dependency installed (FIX #45, real JWT auth): "
                    "rewrote %s", rep.get("rewritten"))
            # FIX #48 (run #12 / #18): lanes import get_current_user from the WRONG module
            # (`from oauth_routes import get_current_user` — oauth_routes only exposes
            # build_router) → ImportError → backend crashes on startup → backend_health
            # fails forever. Repoint every wrong-module import at the scaffolded
            # auth_dependency. AST-precise; complements FIX #45 (which fixes placeholder
            # DEFS, not wrong IMPORTS).
            imp = repair_auth_import_paths(be_dir)
            if imp.get("repaired"):
                orch._logger.warning(
                    "Backend auth imports normalized (FIX #48): repointed "
                    "get_current_user to auth_dependency in %s", imp.get("rewritten"))
            # FIX #46 (run #12): handlers that fake-parse a ``user:<id>`` token INLINE
            # (no shared get_current_user to rewrite) → rewrite the fake split to decode
            # the real RS256 JWT, so authed endpoints stop 401'ing 'invalid token'.
            inline = repair_inline_token_auth(be_dir)
            if inline.get("fixed"):
                orch._logger.warning(
                    "Backend inline token auth repaired (FIX #46): %s fake "
                    "'user:<id>' parse site(s) now decode the real JWT.",
                    inline.get("fixed"))
            # FIX #47 (run #16): some lanes write NO auth (handlers fetch the first DB
            # user) → 200 with no token → auth_enforced_401 stalls the milestone. Enforce
            # a valid bearer JWT on every /api/ business route via middleware.
            mw = repair_auth_enforcement_middleware(be_dir)
            if mw.get("injected"):
                orch._logger.warning(
                    "Backend auth-enforcement middleware injected (FIX #47): /api/ "
                    "business routes now require a valid bearer JWT.")
        except Exception as exc:
            orch._logger.debug("backend auth repair skipped: %s", exc)

    def repair_backend_packaging(self) -> None:
        """Ensure the backend is pip-installable in docker. The lane writes a
        hatchling pyproject with a FLAT layout, so the Dockerfile's
        ``uv pip install .`` can't build a wheel → the whole docker build dies →
        docker_up TIMES OUT → no delivery (instagram MM, 2026-06-08: M5 was blocked
        here for 12 min, never delivered, so its declared endpoints — incl. POST
        follow — were never projected). bypass-selection makes the deps install +
        the build succeed. Best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .backend_scaffold import repair_backend_packaging
            rep = repair_backend_packaging(_P(out_dir) / "app" / "backend")
            if rep.get("repaired"):
                orch._logger.warning(
                    "Backend packaging made build-safe (hatchling flat-layout → "
                    "wheel bypass-selection so `pip install .` installs deps without "
                    "failing package detection): %s", rep.get("pyproject"))
        except Exception as exc:
            orch._logger.debug("backend packaging repair skipped: %s", exc)

    def repair_ddl_from_orm(self) -> None:
        """FIX #43 (#2 guaranteed): regenerate the DDL FROM the app's SQLAlchemy
        models so it can never drift from the handlers. The LLM's model+handler
        agree with each other (e.g. ``posts.user_id``) but may diverge from the
        description-derived DDL (``posts.author_id``) → runtime UndefinedColumn.
        The model is the runtime truth, so project the DDL from it. Best-effort:
        leaves the existing spec-DDL in place if models.py can't be introspected."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .database_scaffold import (
                introspect_orm_schema, render_schema_sql)
            be = _P(out_dir) / "app" / "backend"
            tables = introspect_orm_schema(be)
            if not tables:
                return
            ddl_sql = render_schema_sql(tables)
            # Write the spine-correct DDL to the framework's canonical path AND to
            # EVERY path the docker-compose actually MOUNTS as a Postgres init
            # script. The backend routinely authors its OWN app/backend/01_init.sql
            # (its users table carries username/full_name but NOT the spine `name`
            # column the embedded OAuth2 AS register inserts) and points the
            # compose at THAT file — so writing only to app/database/init/ leaves
            # the LIVE DB with the wrong schema (auth_register_login 500: column
            # "name" does not exist, which silently burned a full M1 run on 36
            # validation retries before this fix).
            targets = [_P(out_dir) / "app" / "database" / "init" / "01_init.sql"]
            try:
                import yaml as _yaml
                compose = _P(out_dir) / "docker" / "docker-compose.yml"
                if compose.exists():
                    data = _yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
                    for svc in (data.get("services") or {}).values():
                        if not isinstance(svc, dict):
                            continue
                        for vol in (svc.get("volumes") or []):
                            if not isinstance(vol, str) or "initdb.d" not in vol:
                                continue
                            host = vol.split(":")[0].strip()
                            if not host:
                                continue
                            p = (compose.parent / host).resolve()
                            targets.append(p if host.endswith(".sql") else p / "01_init.sql")
            except Exception:
                pass
            written: List[str] = []
            for t in list(dict.fromkeys(targets)):  # dedup, keep order
                try:
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_text(ddl_sql, encoding="utf-8")
                    written.append(str(t))
                except Exception:
                    continue
            orch._logger.warning(
                "DDL regenerated from the app's ORM models + written to all "
                "compose-mounted init paths (FIX #43 + mount-path fix): tables=%s "
                "targets=%s", sorted(tables), written)
        except Exception as exc:
            orch._logger.debug("ORM-DDL repair skipped: %s", exc)

    def project_missing_routes(self) -> None:
        """ROOT FIX (instagram MM, 2026-06-08): a backend lane DECLARES endpoints in
        RegistryHub but runs out of its loop budget before writing route code for all of
        them — the milestone then delivers HOLLOW (declared endpoints that 404, e.g.
        7/28 on instagram). Trusting RegistryHub status is the trap; the contract surface
        must be PROJECTED from the declared contract, exactly as repair_ddl_from_orm
        projects the DDL from the ORM rather than trusting LLM-written SQL. For every
        business endpoint RegistryHub declares that has no route in main.py, project a
        working handler from the ORM (the lane's real handlers are untouched; this
        only fills the gaps). Idempotent; best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            registryhub = getattr(orch.hubs, "registryhub", None)
            if registryhub is None:
                return
            from pathlib import Path as _P
            from .lifecycle import business_endpoints
            from .route_projector import project_missing_routes
            declared = business_endpoints(registryhub.get_endpoints())
            if not declared:
                return
            res = project_missing_routes(_P(out_dir) / "app" / "backend", declared)
            projected = res.get("projected") or []
            if projected:
                orch._logger.warning(
                    "By-construction route projection: the lane DECLARED %s "
                    "endpoint(s) it never coded — projected working handlers from "
                    "the ORM so the contract is complete (no 404 on declared "
                    "routes): %s", len(projected), projected)
            # PROPOSAL #13: with the skeleton + projection done, audit the registry
            # against CODE TRUTH — flip an endpoint `implemented` only when its route
            # is actually on the SERVED surface (main.py `@app` + the `include_router`
            # chain), and regress phantom-"implemented" routes to `defined`. Hooked
            # HERE — after projection (so projector-filled routes count) and after the
            # merge that always precedes projection — so it audits what actually ships,
            # NOT inside generate_backend_skeleton which runs pre-projection. The backend
            # twin of frontend_audit. Honest flags → api_smoke stops failing
            # "status=implemented but 404" contract lies.
            try:
                from .backend_audit import sync_endpoint_statuses
                _ea = sync_endpoint_statuses(out_dir, registryhub)
                if _ea.get("implemented") or _ea.get("regressed"):
                    orch._logger.warning(
                        "ENDPOINT LIFECYCLE (code-truth): implemented=%s regressed=%s "
                        "pending=%s", _ea.get("implemented"), _ea.get("regressed"),
                        _ea.get("pending"))
            except Exception:
                pass
        except Exception as exc:
            orch._logger.debug("route projection skipped: %s", exc)

    def repair_handler_fk_aliases(self) -> None:
        """ROOT FIX (instagram MM run #9, 2026-06-09): the backend lane authored a
        handler querying ``Post.user_id`` while the Post model's owner FK is
        ``author_id`` → ``AttributeError`` 500 on /api/users/me → api_smoke
        ``business_endpoints_reachable`` stalled out the whole milestone. Like
        repair_ddl_from_orm, repair the handler↔model surface deterministically:
        rewrite ``<Model>.<owner_alias>`` references to the model's real owner FK when
        the alias is not a column (a guaranteed AttributeError) — never touching a valid
        query. Best-effort; idempotent."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .handler_fk_repair import repair_handler_fk_aliases
            res = repair_handler_fk_aliases(_P(out_dir) / "app" / "backend")
            fixed = res.get("fixed") or []
            if fixed:
                orch._logger.warning(
                    "By-construction handler FK-alias repair: rewrote %s handler "
                    "reference(s) to a non-existent owner FK to the model's real one "
                    "(prevents AttributeError 500s): %s", len(fixed), fixed)
        except Exception as exc:
            orch._logger.debug("handler FK-alias repair skipped: %s", exc)

    def repair_psycopg_dsn(self) -> None:
        """ROOT FIX (instagram MM run #10, 2026-06-09): the backend lane opened RAW
        psycopg connections with the SQLAlchemy URL ``postgresql+psycopg://…`` (the env
        ``DATABASE_URL``), which ``psycopg.connect`` rejects (``missing "=" …``) → 500 on
        every such endpoint (/api/users/suggested, /api/feed, /api/explore, … 14+ sites)
        → api_smoke stall. The SQLAlchemy engine needs the +driver form, so only the raw
        call sites are normalised: wrap each ``psycopg.connect(arg)`` with a
        ``_psycopg_dsn(arg)`` helper that strips the dialect. Best-effort; idempotent."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .psycopg_dsn_repair import repair_psycopg_dsn
            res = repair_psycopg_dsn(_P(out_dir) / "app" / "backend")
            wrapped = res.get("wrapped") or 0
            if wrapped:
                orch._logger.warning(
                    "By-construction psycopg DSN repair: wrapped %s raw "
                    "psycopg.connect() site(s) to strip the SQLAlchemy dialect from the "
                    "DSN (prevents 'missing \"=\"' 500s).", wrapped)
        except Exception as exc:
            orch._logger.debug("psycopg DSN repair skipped: %s", exc)

    def run_test_user_validation(self, version: str) -> None:
        """Post-milestone TEST-USER phase (2026-06-09, user-asked): once a release is
        cut, simulate a real user's journey across the API (register → post → feed →
        view-my-posts → follow → comment → like → message) and check the MCP surface is
        complete, writing a feedback report — the automated form of the hand-verification
        that exposed the route_projector bugs (null owner on create, 500 on
        /users/{username}/posts). Blocking (HTTP + subprocess); the caller runs it in a
        thread. Health-pre-checks the app and SKIPS (no false negatives) if it is not
        up — never boots (to avoid racing the next milestone's api_smoke) and never
        raises into delivery. Web screenshots are produced by the orchestrating layer
        (Playwright is not a gen-runtime dependency)."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            registryhub = getattr(orch.hubs, "registryhub", None)
            if not out_dir or registryhub is None:
                return
            from pathlib import Path as _P
            from .lifecycle import business_endpoints
            from .validation_runner import _backend_host_port, _http
            from .test_user_validation import run_test_user_validation
            proj = _P(out_dir)
            compose = proj / "docker" / "docker-compose.yml"
            port = _backend_host_port(compose, compose.parent) if compose.exists() else None
            base = f"http://localhost:{port}" if port else None
            # Health pre-check: only run the journey against a live app.
            healthy = False
            if base:
                for _ in range(3):
                    if _http("GET", f"{base}/health", timeout=5).get("status") == 200:
                        healthy = True
                        break
            if not healthy:
                orch._logger.warning(
                    "TEST-USER validation (v%s): SKIPPED — app not reachable at "
                    "delivery time (no false-negative report).", version)
                return
            eps = business_endpoints(registryhub.get_endpoints())
            report = run_test_user_validation(
                proj, eps, version=version, base_url=base, compose_file=compose,
                llm=getattr(orch, "llm", None))
            summ = report.get("summary", {})
            if summ.get("verdict") == "PASS":
                orch._logger.warning(
                    "TEST-USER validation (v%s): PASS — %s/%s API journey steps OK + "
                    "MCP surface complete.", version,
                    summ.get("api_passed"), summ.get("api_steps"))
            else:
                orch._logger.warning(
                    "TEST-USER validation (v%s): %s — %s/%s journey steps passed; "
                    "BROKEN: %s", version, summ.get("verdict"),
                    summ.get("api_passed"), summ.get("api_steps"), summ.get("broken"))
        except Exception as exc:
            orch._logger.debug("test-user validation skipped: %s", exc)

    def repair_frontend_api(self) -> None:
        """FIX #37: reconcile frontend api.js exports with component imports on the
        integrated tree, so naming drift can't break ``npm run build`` (and thus
        the api_smoke docker_up gate). Deterministic + best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from .frontend_scaffold import (
                repair_frontend_api_exports, scaffold_missing_local_pages)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = repair_frontend_api_exports(fe)
            if rep.get("repaired"):
                orch._logger.warning(
                    "Frontend api.js reconciled: aliased=%s stubbed=%s",
                    rep.get("aliased"), rep.get("stubbed"),
                )
            # Build-integrity: the frontend lane routinely imports a page it never
            # created (e.g. ./pages/MessagesInboxPage) → ``npm run build`` fails →
            # frontend container can't boot. Scaffold a valid stub for any dangling
            # local component import so the app always builds.
            pages = scaffold_missing_local_pages(fe)
            if pages.get("scaffolded"):
                orch._logger.warning(
                    "Frontend dangling imports resolved by stub pages (lane "
                    "imported components it never created): %s",
                    pages.get("scaffolded"),
                )
        except Exception as exc:
            orch._logger.debug("frontend api repair skipped: %s", exc)

    def repair_backend_as_wiring(self) -> None:
        """FIX #39: ensure main.py wires the framework OAuth2 AS router, which now
        owns /oauth/*, /.well-known/*, AND the standard /auth/register +
        /auth/login. The backend lane variably forgets to include it (this run:
        no /oauth/* and no /auth/register at all → auth_register_login 404).
        Inject the include_router right after ``app = FastAPI(...)`` (so its routes
        take precedence over any inline /auth/* the backend wrote). Idempotent +
        best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            be = _P(out_dir) / "app" / "backend"
            main_py = be / "main.py"
            if not main_py.exists() or not (be / "oauth_routes.py").exists():
                return
            src = main_py.read_text(encoding="utf-8")
            if "build_router" in src:
                return  # AS already wired (and the template now includes /auth/*)
            import re as _re
            lines = src.splitlines()
            idx = None
            for i, ln in enumerate(lines):
                if _re.match(r"\s*app\s*=\s*FastAPI\b", ln):
                    depth, j = 0, i
                    while j < len(lines):
                        depth += lines[j].count("(") - lines[j].count(")")
                        if depth <= 0:
                            break
                        j += 1
                    idx = j
                    break
            if idx is None:
                return
            wiring = [
                "",
                "# wire the framework OAuth2 AS (provides /oauth/*,",
                "# /.well-known/*, and the standard /auth/register + /auth/login).",
                "try:",
                "    from oauth_store import OAuthStore as _ASStore",
                "    from jwt_manager import JWTManager as _ASJwt",
                "    from oauth_routes import build_router as _as_build_router",
                "    app.include_router(_as_build_router(_ASStore(), _ASJwt()))",
                "except Exception as _as_exc:  # pragma: no cover",
                "    import logging as _l",
                "    _l.getLogger('uvicorn').warning('AS wiring skipped: %s', _as_exc)",
            ]
            lines[idx + 1:idx + 1] = wiring
            main_py.write_text("\n".join(lines) + "\n", encoding="utf-8")
            orch._logger.warning(
                "Backend main.py: wired the framework OAuth2 AS router "
                "(was missing → /auth/register + /oauth/* absent).")
        except Exception as exc:
            orch._logger.debug("backend AS wiring repair skipped: %s", exc)

    def repair_backend_entrypoint(self) -> None:
        """FIX #38: ensure the backend main.py actually STARTS the server. The
        Dockerfile CMD is ``python main.py``, but the lane sometimes omits the
        ``if __name__ == '__main__': uvicorn.run(...)`` block → the container
        imports main.py and exits(0) without serving → backend_health FAIL → no
        delivery of an otherwise-working app. Append a standard uvicorn entrypoint
        (reading API_PORT, which the compose sets) when missing. Deterministic +
        best-effort."""
        orch = self._orch
        try:
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            main_py = _P(out_dir) / "app" / "backend" / "main.py"
            if not main_py.exists():
                return
            src = main_py.read_text(encoding="utf-8")
            if "uvicorn.run" in src or "__main__" in src:
                return  # already starts the server / has a main guard
            import re as _re
            if not _re.search(r"^\s*app\s*=", src, _re.M):
                return  # no module-level `app` to serve
            entry = (
                "\n\n# ensure `python main.py` actually serves (a missing "
                "entrypoint makes the\n# container exit(0) without starting uvicorn).\n"
                'if __name__ == "__main__":\n'
                "    import os\n"
                "    import uvicorn\n"
                "    uvicorn.run(app, host=\"0.0.0.0\", "
                "port=int(os.environ.get(\"API_PORT\", \"8081\")))\n"
            )
            main_py.write_text(src.rstrip() + entry, encoding="utf-8")
            orch._logger.warning(
                "Backend main.py entrypoint appended (was missing uvicorn.run "
                "→ container would exit(0) without serving).")
        except Exception as exc:
            orch._logger.debug("backend entrypoint repair skipped: %s", exc)

    def merge_committed_agent_work(self) -> None:
        """Merge each lane's COMMITTED agent-branch work into integration so the
        framework validation/delivery runs against the latest code even when the
        authoring lane hasn't 'finished' (its workhub-task bookkeeping can lag the
        code it already wrote+committed). Best-effort, idempotent
        ("nothing to merge" when already integrated), conflict-safe
        (merge_agent_branch_to_main aborts on conflict). Never raises into the loop.
        """
        orch = self._orch
        try:
            from ..agents.runtime.auto_commit import merge_agent_branch_to_main, flush_worktree
        except Exception:
            return
        repo = getattr(orch, "output_dir", None)
        if repo is None:
            return
        from pathlib import Path as _P
        for lane in ("backend", "database", "frontend"):
            # FLUSH FIRST: commit any uncommitted/untracked app work in the lane's
            # worktree so it's part of agent/<lane> before we merge. Without this,
            # files the lane WROTE but never finish-committed (e.g. the frontend's
            # pages authored after its last commit) are invisible to the squash
            # merge → integration ships a blank shell (frontend_navigable: 0) and
            # the run idle-wedges. This is the root fix for that recurring stall.
            try:
                _wt = _P(repo) / "worktrees" / lane
                if _wt.exists():
                    fok, finfo = flush_worktree(worktree_dir=_wt, branch=f"agent/{lane}", author=lane)
                    if fok and all(s not in str(finfo) for s in ("nothing to commit", "no deliverable", "not a git")):
                        orch._logger.warning("🧹 flushed uncommitted %s worktree before merge → %s", lane, finfo)
            except Exception:
                pass
            _superseded: list = []  # PROPOSAL #26 N2
            try:
                ok, info = merge_agent_branch_to_main(
                    repo_root=repo,
                    agent_branch=f"agent/{lane}",
                    main_branch="integration",
                    agent_id=lane,
                    superseded_out=_superseded,
                )
            except Exception:
                continue
            if ok and _superseded:
                # PROPOSAL #26 N2: the heal merge superseded the lane's edit(s) to
                # framework-owned file(s). Notify the lane (inbox_only → next pulse,
                # NO wakeup) so it stops re-editing them → re-conflict.
                try:
                    from .framework_notice import emit_framework_decision
                    _hubs = getattr(orch, "_hubs", None) or getattr(orch, "hubs", None)
                    emit_framework_decision(
                        getattr(_hubs, "eventhub", None),
                        lane=lane, kind="conflict_resolved", paths=_superseded)
                except Exception:
                    pass
            if ok and info and "nothing to merge" not in str(info):
                orch._logger.warning(
                    "🔀 Pre-validation merge agent/%s → integration: %s "
                    "(surfaced committed code the lane had not finish-merged).",
                    lane, info,
                )

    def commit_framework_delivery(self) -> None:
        """Commit the framework's delivery-time writes (backend skeleton, frontend
        infra pin, projected routes/pages) on integration BEFORE the release branch
        is cut. ``create_release`` snapshots the COMMITTED head — without this
        commit every framework write stayed working-tree-only, so each release
        shipped the lane's last committed (broken) state: v1.0.0's snapshot carried
        the lane's mismatched start.sh and NO vite.config.js even though the pin
        had fixed both on disk. Best-effort; "nothing to commit" is fine."""
        orch = self._orch
        try:
            from pathlib import Path as _P
            from ..agents.runtime.auto_commit import _run_git
            repo = getattr(orch, "output_dir", None)
            if not repo:
                return
            repo = _P(repo)
            staged_any = False
            for sub in ("app", "mcp_server", "docker"):
                if not (repo / sub).exists():
                    continue
                rc, _o, _e = _run_git(
                    ["add", "-A", "--", sub,
                     ":(exclude)**/__pycache__/**", ":(exclude)**/*.py[cod]"],
                    cwd=repo)
                staged_any = staged_any or (rc == 0)
            if not staged_any:
                return
            rc, out, err = _run_git(
                ["commit", "-m",
                 "framework delivery: backend skeleton + frontend infra + projections"],
                cwd=repo)
            if rc == 0:
                orch._logger.warning(
                    "Framework delivery writes COMMITTED to integration so the "
                    "release snapshot ships them (skeleton/infra/projections).")
            # rc != 0 → nothing to commit (already clean) — silent.
        except Exception as exc:
            orch._logger.debug("framework delivery commit skipped: %s", exc)
