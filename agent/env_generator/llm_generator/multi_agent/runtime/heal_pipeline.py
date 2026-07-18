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

_ROUTE_FILE_SUFFIXES = (".jsx", ".tsx", ".js", ".ts", ".vue", ".mjs", ".css", ".html", ".json")


def _is_walkable_route(route) -> bool:
    """A registered ui_page is walkable by the browser test-user only if its ``route`` is a
    real SPA URL route — i.e. it STARTS WITH ``/`` and is not a SOURCE FILE PATH.

    The frontend lane routinely registers junk ui_page entries whose ``route`` is the page's
    SOURCE FILE (``src/pages/OutlookInboxPage.jsx``, ``app/frontend/src/components/
    ReplyComposer.jsx``) or registers non-navigable COMPONENTS (folder_rail / message_list /
    calendar_grid …) as ui_pages. Walking those navigates the SPA to a non-route → it renders
    BLANK → the browser gate reports a FALSE 'unusable', churns its bounded deferral, and
    escape-ships 'loudly' on a perfectly usable app (outlook run-28 v1.1.0, live-confirmed:
    EVERY 'blank' page was a file-path/component entry while the real routes ``/`` ``/inbox``
    ``/calendar`` rendered fine and ``auth_ok=True``). A relative file path fails
    ``startswith('/')``; an absolute one is caught by the source-file suffix.

    PARAM routes (``/inbox/message/:id``, ``/calendar/event/{eventId}``) are excluded too
    (outlook run-30, live): the walker navigates to the LITERAL ``:id`` → the page fetches
    resource ":id" → nothing → renders empty → a FALSE 'blank' that burned the whole M1
    deferral budget + escape-shipped while every param-free page was fine. A real user
    reaches a detail page by CLICKING a list row — that is the click-through/squad tests'
    coverage, not the URL walk's. ENV-AGNOSTIC."""
    r = str(route or "").strip()
    if not r.startswith("/"):
        return False
    r = r.split("?", 1)[0]
    if "{" in r or any(seg.startswith(":") for seg in r.split("/")):
        return False                               # unresolved param → not URL-walkable
    return not r.rstrip("/").lower().endswith(_ROUTE_FILE_SUFFIXES)


def _isolation_scoped_tables_from_chains(registryhub, table_names) -> set:
    """Tables the verifier's REGISTERED chains probe for CROSS-USER READ ISOLATION — a by-id
    GET the verifier asserts must be DENIED (403/404) to a NON-owner. A cross-user GET denial
    IS the verifier's domain judgment that the resource is per-user-PRIVATE-TO-READ, so its
    reads must be owner-scoped BY CONSTRUCTION. (#77: a cross-user PUT/DELETE denial is NOT
    used — it proves only WRITE authz, which is true for PUBLIC resources too; using it wrongly
    scoped a world-readable feed's reads to the caller.) This closes the cross-user data leak the
    backend agent unreliably declares via owner_scoped_reads (outlook run-9/10: it scoped
    `messages`, forgot `events` → GET /api/events/{id} returned any user's row → business_
    chain isolation FAIL → 7-cycle wedge). ENV-AGNOSTIC + no global default flip: a PUBLIC
    resource (social feed) gets NO isolation probe, so it is never scoped and stays open.
    Best-effort; empty on any failure."""
    out: set = set()
    try:
        from .chain_executor import _is_cross_user_denial, normalize_steps
        chains = registryhub.get_verification_chains() or {}
        names = set(table_names or ())
        for chain in (chains.values() if isinstance(chains, dict) else (chains or [])):
            if not isinstance(chain, dict):
                continue
            steps, _ = normalize_steps(chain.get("steps") or [])
            for st in steps:
                if not _is_cross_user_denial(st):
                    continue
                # #77: READ-SCOPING may only be inferred from a cross-user GET denial. A
                # cross-user PUT/DELETE/PATCH denial proves only WRITE authz ("you may not
                # edit/delete someone else's row") — a near-universal property that ALSO
                # holds for PUBLIC resources (a forum comment, a social post). Deriving
                # read-scoping from it wrongly scopes a world-readable resource's reads to
                # the caller → the public feed silently shows only your own rows, and it
                # ships GREEN (the write-denial still passes). Mutations enforce their own
                # authz; only a GET denial proves reads must be owner-scoped.
                if str(st.get("method") or "GET").upper() != "GET":
                    continue
                # the resource COLLECTION of the by-id TARGET → the table name. For a by-id
                # probe (last seg is a path param) that is the segment BEFORE the param
                # (/api/events/{id} -> 'events'; /api/posts/{id}/comments/{cid} -> 'comments',
                # NOT 'posts'); for a bare-collection denial it is the last segment. Using
                # segs[0] mis-attributed a nested by-id denial to the PARENT collection.
                segs = [s for s in str(st.get("path") or "").split("?", 1)[0].split("/")
                        if s and s.lower() != "api"]
                if not segs:
                    continue
                _last_is_param = segs[-1].startswith(("{", ":", "${"))
                _res = (segs[-2] if _last_is_param and len(segs) >= 2 else segs[-1])
                if _res in names:
                    out.add(_res)
    except Exception:
        pass
    return out


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
                repair_inline_token_auth, repair_auth_enforcement_middleware,
                repair_custom_routes_router_prologue, repair_integrity_error_handler,
                repair_custom_routes_db_handle, repair_custom_routes_param_types)
            be_dir = _P(out_dir) / "app" / "backend"
            # custom_routes using @router.<verb> without defining router (run-34):
            # NameError at import silently killed the WHOLE custom router — including the
            # lane's owner-scoped reads → cross-user leak → isolation wedge → STUCK.
            _rp = repair_custom_routes_router_prologue(be_dir)
            if _rp.get("repaired"):
                orch._logger.warning(
                    "custom_routes.py used @router without defining it — canonical "
                    "APIRouter prologue inserted (import-crash fix).")
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
            # FIX #82 (instagram run-2): unchecked path-id FK INSERTs surface DB
            # ForeignKeyViolation as a raw 500 — chains tolerate 404 on by-id actions,
            # never 500 → business_chain wedges. Map integrity errors to REST statuses.
            ih = repair_integrity_error_handler(be_dir)
            if ih.get("injected"):
                orch._logger.warning(
                    "Backend IntegrityError→REST mapping injected (FIX #82): FK "
                    "violation → 404, unique → 409, other integrity → 400 (no raw 500s).")
            # FIX #86 (run-7 M3): a lane-local raw-psycopg get_db in custom_routes
            # shadows the framework Session → every text()/.mappings() handler 500s.
            dbh = repair_custom_routes_db_handle(be_dir)
            if dbh.get("repaired"):
                orch._logger.warning(
                    "custom_routes.py lane get_db (raw psycopg) rewritten to delegate to "
                    "the framework Session (FIX #86) — dual-style DB handle restored.")
            # FIX #118 (run-33): a lane-written jwt.decode without audience= rejects
            # every aud-carrying framework token (PyJWT InvalidAudienceError) → 401
            # "Invalid token" on all authed endpoints → business_chain wedge.
            try:
                from .backend_scaffold import repair_jwt_decode_audience
                _jda = repair_jwt_decode_audience(be_dir)
                if _jda.get("repaired"):
                    orch._logger.warning(
                        "lane jwt.decode calls made aud-tolerant (verify_aud=False, "
                        "FIX #118 — framework tokens carry aud; signature checks "
                        "untouched): %s", _jda.get("repaired"))
            except Exception as _jda_exc:
                orch._logger.debug("jwt-decode audience repair skipped: %s", _jda_exc)
            # FIX #106 (run-23): a `param: str` annotation on an integer-PK by-id route
            # makes Postgres reject the comparison (int = varchar) → 500 on every read,
            # and the lane's by-id GET shadows the projected one by design.
            # FIX #119 (run-35 M4): the PROJECTED signature is the contract truth for
            # path-param types in BOTH directions (run-35: lane wrote username: int on
            # a string-keyed route → every real username 422/500 → STUCK).
            try:
                from .backend_scaffold import repair_custom_routes_param_types_vs_projection
                _pv = repair_custom_routes_param_types_vs_projection(be_dir)
                if _pv.get("fixed"):
                    orch._logger.warning(
                        "custom_routes.py path-param annotations aligned to the PROJECTED "
                        "signatures (FIX #119): %s param(s) corrected.", _pv.get("fixed"))
            except Exception as _pv_exc:
                orch._logger.debug("param-vs-projection repair skipped: %s", _pv_exc)
            pt = repair_custom_routes_param_types(be_dir)
            if pt.get("fixed"):
                orch._logger.warning(
                    "custom_routes.py path-param annotations corrected (FIX #106): %s "
                    "str→int on integer-PK routes.", pt.get("fixed"))
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
            from .backend_scaffold import (repair_backend_packaging,
                                           sanitize_pyproject_local_deps)
            rep = repair_backend_packaging(_P(out_dir) / "app" / "backend")
            if rep.get("repaired"):
                orch._logger.warning(
                    "Backend packaging made build-safe (hatchling flat-layout → "
                    "wheel bypass-selection so `pip install .` installs deps without "
                    "failing package detection): %s", rep.get("pyproject"))
            # FIX #189 (tiktok-r5): a hallucinated LOCAL-module dep
            # (custom_routes.py listed as pip dep "custom-routes") kills uv
            # resolution → docker_up wedges to STUCK-ABORT. Deterministic strip.
            rep2 = sanitize_pyproject_local_deps(_P(out_dir) / "app" / "backend")
            if rep2.get("repaired"):
                orch._logger.warning(
                    "Backend pyproject sanitized: dropped local-module dep(s) %s — "
                    "these are the app's OWN files, not pip packages (uv would fail "
                    "the whole docker build on them): %s",
                    rep2.get("dropped"), rep2.get("pyproject"))
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
            # Per-user-PRIVATE tables (owner_scoped_reads in table metadata): their
            # reads are projected owner-scoped by construction so the isolation chain
            # passes without a lane override (which fd56c2e closed for CRUD). One
            # decision per table at kickoff; default empty ⇒ open reads (public feed).
            try:
                _tbls = registryhub.list_tables() or {}
                owner_scoped_tables = {
                    name for name, t in _tbls.items()
                    if str(((t or {}).get("metadata") or {}).get("owner_scoped_reads")
                           ).strip().lower() in {"true", "1", "yes", "y", "on"}
                }
                # VERIFIER-DRIVEN read isolation (2026-06-30): ALSO owner-scope any table the
                # verifier's registered chains probe for cross-user isolation. The agent's
                # owner_scoped_reads declaration is unreliable (run-9/10 leaked `events`); the
                # verifier's isolation probe IS the reliable, domain-correct privacy signal —
                # and a PUBLIC resource gets no probe, so this never over-scopes a social feed.
                owner_scoped_tables |= _isolation_scoped_tables_from_chains(
                    registryhub, set(_tbls.keys()))
            except Exception:
                owner_scoped_tables = set()
            res = project_missing_routes(
                _P(out_dir) / "app" / "backend", declared,
                owner_scoped_tables=owner_scoped_tables)
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
            except Exception as exc:
                # Non-fatal (don't crash the heal run) but LOUD: backend_audit raises
                # BackendAuditError on a real failure and silently swallowing it
                # re-hides the very signal it was added to surface.
                orch._logger.error(
                    "backend_audit.sync_endpoint_statuses FAILED (endpoint lifecycle "
                    "NOT synced; flags may be stale): %s", exc)
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

    def run_test_user_validation(self, version: str) -> "dict | None":
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
            try:
                from .llm_overrides import get_component_llm
                _tu_llm = get_component_llm(orch, "test_user_judge") or getattr(orch, "llm", None)
            except Exception:
                _tu_llm = getattr(orch, "llm", None)
            report = run_test_user_validation(
                proj, eps, version=version, base_url=base, compose_file=compose,
                llm=_tu_llm)
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
            # BROWSER test-user (2026-06-22): drive a real browser through the frontend
            # — the auth FLOW (catches a dead login form) + every declared page route
            # (screenshot + blank/console-error checks). The structured feedback is
            # logged AND routed to the frontend lane as remediation, then re-tested next
            # milestone — the user's intended "recruit -> test via web tools -> key-node
            # screenshots -> feedback -> fix" loop. Best-effort; never blocks.
            try:
                # Returns the browser report (auth_ok/blank_pages/…) so a PRE-RELEASE
                # caller can gate the release on it; None if it could not run.
                return self._run_browser_test_user(proj, compose, registryhub, version)
            except Exception as _bexc:
                orch._logger.debug("browser test-user skipped: %s", _bexc)
        except Exception as exc:
            orch._logger.debug("test-user validation skipped: %s", exc)
        return None

    def _run_browser_test_user(self, proj, compose, registryhub, version) -> "dict | None":
        """Recruit the browser test-user against the running FRONTEND: auth flow +
        per-page screenshot/blank/console checks; log feedback + route blank/broken
        pages back to the frontend lane for repair. Best-effort; never raises out."""
        import asyncio
        orch = self._orch
        from .visual_fidelity import _service_host_port
        from .validation_runner import _backend_host_port
        from .test_user_runner import (
            run_browser_test_user, format_feedback, judge_against_references,
            extract_seed_display_values)
        cwd = compose.parent
        fe_port = (_service_host_port(compose, cwd, "frontend")
                   or _service_host_port(compose, cwd, "ui") or 8080)
        base = f"http://localhost:{fe_port}"
        # The backend base lets the test-user register its account via the API first, so it
        # tests the LOGIN ui in isolation instead of false-flagging a working staged login.
        be_port = _backend_host_port(compose, cwd) if compose.exists() else None
        api_base = f"http://localhost:{be_port}" if be_port else None
        # pages to walk: the registered ui_pages with a real route (+ landing/login).
        pages = [{"name": "login", "route": "/login", "auth": False}]
        # Fix #35 (complete form): a PARAM route (/inbox/message/:id) is not URL-
        # walkable as written — resolve a REAL row id via the backend (as the
        # SEEDED demo user, whose owner-scoped lists are populated) and walk the
        # concrete route; only an unresolvable param route is skipped. One lazy
        # token mint for the whole page list.
        _param_tok = {"tried": False, "v": None}

        def _resolver_token():
            if not _param_tok["tried"]:
                _param_tok["tried"] = True
                try:
                    if be_port:
                        from .visual_fidelity import _mint_token, _seed_demo_login
                        _param_tok["v"] = _mint_token(be_port, timeout_s=20,
                                                      demo=_seed_demo_login(proj))
                except Exception:
                    pass
            return _param_tok["v"]

        try:
            from .test_user_runner import _is_param_seg, resolve_param_route
            for name, pg in (registryhub.list_ui_pages() or {}).items():
                if not isinstance(pg, dict):
                    continue
                route = str(pg.get("route") or pg.get("path") or "").strip()
                if (api_base and route.startswith("/")
                        and any(_is_param_seg(s) for s in route.split("/"))):
                    route = resolve_param_route(route, api_base, _resolver_token()) or route
                # Skip junk entries whose "route" is a SOURCE FILE PATH or a non-navigable
                # component — walking them renders BLANK and false-flags a usable app (#26).
                # An unresolved param route still lands here and is skipped (#35 interim).
                if route and _is_walkable_route(route):
                    low = route.rstrip("/").lower()
                    pages.append({"name": str(name), "route": route,
                                  "auth": low not in ("/login", "/signup", "/signin", "/register", "", "/")})
        except Exception:
            pass
        out_dir = proj / "design" / "test_user"
        # Log in as the SEEDED demo user (populated screens that match the references) rather
        # than a fresh user that, under tenant-scoping, sees empty lists on every page.
        from .visual_fidelity import _seed_demo_login
        # B-direction: the salient real seeded values (place names, authors, addresses) the
        # walk asserts render SOMEWHERE — catches a mock-twin / placeholder / no-token fetch
        # frontend that logs in + renders but shows zero real backend data (run-3). Empty →
        # the assertion self-skips (never false-flags a static app). Best-effort.
        try:
            _seed_vals = extract_seed_display_values(proj)
        except Exception:
            _seed_vals = []
        report = asyncio.run(run_browser_test_user(
            base, pages, out_dir, register=True, api_base_url=api_base,
            demo_login=_seed_demo_login(proj), seed_values=_seed_vals))
        if not report.get("ran"):
            orch._logger.warning("BROWSER test-user (v%s): could not run — %s",
                                 version, report.get("summary"))
            return None
        # KEY-NODE vs REFERENCE: LLM-compare each captured page screenshot to the reference
        # image that depicts that route, so the feedback says "inbox doesn't match
        # outlook_inbox.png — missing folder rail", not merely "blank/console-error". The
        # browser captured a screenshot of the REAL logged-in app per route; this folds the
        # visual verdict into the same report (PIPELINE_HANDOFF §5/§8.1). Best-effort.
        refs = list(getattr(orch, "_reference_images", None) or [])
        llm = getattr(orch, "llm", None)
        if refs and llm is not None:
            try:
                asyncio.run(judge_against_references(report, refs, llm))
            except Exception as _vexc:
                orch._logger.debug("test-user visual judging skipped: %s", _vexc)
        orch._logger.warning("BROWSER test-user (v%s): %s; visual_mismatches=%s",
                             version, report.get("summary"), report.get("visual_mismatches") or "∅")
        # Route concrete UI defects (dead auth form / blank pages / console errors / a screen
        # that does not match its reference) back to the frontend lane as a P0 task — the
        # "give feedback, keep fixing" step. (The task is the durable signal the lane claims;
        # the message_bus send is skipped here because this runs in a worker thread off the
        # orchestrator's event loop.)
        # HOLLOW FRONTEND (login wall): a logged-in test-user that bounces back to the
        # login form on the protected pages means the app is unusable even though it
        # builds + serves — the single worst preview defect and exactly what slipped
        # through before (outlook MM: a hardcoded absolute API origin failed every call).
        # It MUST escalate to a P0 fix like any other UI defect.
        broken = ((not report.get("auth_ok")) or report.get("blank_pages")
                  or report.get("error_pages") or report.get("visual_mismatches")
                  or report.get("hollow_frontend") or report.get("auth_redirect_pages")
                  or report.get("fake_map_pages"))  # #172: fake-div map surface
        if broken:
            try:
                fb = format_feedback(report)
                orch.hubs.workhub.create_task(
                    title="Test-user found UI defects (browser walkthrough) — fix",
                    description=("A real-browser test-user walked the running app and found "
                                 "issues. Fix EACH, then finish:\n" + fb),
                    assignee="frontend", agent="orchestrator", priority="P0")
                orch._logger.warning(
                    "BROWSER test-user dispatched a P0 fix task to frontend: auth_ok=%s "
                    "blank=%s console_errors=%s hollow=%s login_wall=%s visual_mismatches=%s",
                    report.get("auth_ok"), report.get("blank_pages"), report.get("error_pages"),
                    report.get("hollow_frontend"), report.get("auth_redirect_pages"),
                    report.get("visual_mismatches"))
            except Exception as _dexc:
                orch._logger.error("browser test-user feedback dispatch failed: %s", _dexc)
        # Return the report so a PRE-RELEASE caller can gate the release on it (the delivery
        # flow blocks a cut when the app is objectively unusable). Advisory POST-release
        # callers ignore the return; behaviour there is unchanged.
        return report

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
                repair_frontend_api_exports, scaffold_missing_local_pages,
                repair_frontend_named_default_imports, reroute_inline_stub_routes,
                repair_frontend_missing_local_exports, normalize_frontend_api_base,
                repair_frontend_escaped_backticks, repair_frontend_unimported_icons,
                repair_frontend_default_export_wrapper,
                neutralize_frontend_external_backgrounds)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            # SYNTAX FIRST: the lane intermittently escapes template-literal delimiters
            # (`className={\`...\`}`) → esbuild "Invalid or unexpected token" → the whole
            # `npm run build` fails, so EVERY other repair below is moot until the file
            # parses. Un-escape delimiter backticks before anything else (run-13: this
            # wedged docker_up for many cycles, fixed one file at a time). Runs before each
            # api_smoke docker_up (framework_validation) AND at delivery.
            _eb = repair_frontend_escaped_backticks(fe)
            if _eb.get("repaired"):
                orch._logger.warning(
                    "Frontend escaped-backtick template delimiters un-escaped (esbuild "
                    "parse fix, prevents docker_up build wedge): %s", _eb.get("repaired"))
            # FIX #190 (§3-6, gmrun3/5/7/8/11 + tiktok-r1): a re-emitted import →
            # "Identifier 'X' has already been declared" → build FAIL → docker_up
            # wedge. Parse-level like the backtick fix, so it runs right after it.
            try:
                from .frontend_scaffold import repair_frontend_duplicate_imports
                _di = repair_frontend_duplicate_imports(fe)
                if _di.get("repaired"):
                    orch._logger.warning(
                        "Frontend duplicate import bindings deduped (identifier-"
                        "already-declared build-wedge fix): %s", _di.get("repaired"))
                if _di.get("conflicts"):
                    orch._logger.warning(
                        "Frontend import-binding CONFLICTS left for the lane (mixed "
                        "clauses, not auto-fixable): %s",
                        (_di.get("conflicts") or [])[:6])
            except Exception as _die:
                orch._logger.debug("duplicate-import dedup skipped: %s", _die)
            # USED-BUT-UNIMPORTED JSX identifiers (#40, run-33 M1): `<Mail/>` with no
            # import BUILDS fine but crashes the page at render (ReferenceError → blank +
            # console error → browser-gate deferral churn). Import them via lucide-react —
            # the safe-icon plugin renders real icons and degrades unknown names to a
            # placeholder, so this is crash-proof by construction.
            _ui = repair_frontend_unimported_icons(fe)
            if _ui.get("repaired"):
                orch._logger.warning(
                    "Frontend unimported JSX identifiers imported via lucide-react "
                    "(render-crash fix): %s", _ui.get("repaired"))
            # DEFAULT-EXPORT WRAPPER (run-35 /inbox): `export default { api };` makes every
            # default-import consumer's member call undefined → blank page.
            _dw = repair_frontend_default_export_wrapper(fe)
            if _dw.get("repaired"):
                orch._logger.warning(
                    "Frontend default-export wrapper unwrapped (member-call blank-page "
                    "fix): %s", _dw.get("repaired"))
            # Same-origin discipline FIRST: a lane that hardcodes an absolute
            # `http://localhost:<in-container-port>` API base (outlook MM, 2026-06-29)
            # bypasses the nginx reverse proxy AND targets the wrong host port, so the
            # browser's login + every authed call fails → the SPA is stuck on the login
            # form (a "hollow preview" of identical Sign-in pages). Strip such origins to
            # relative URLs so requests flow through the proxy regardless of host port.
            _nb = normalize_frontend_api_base(fe)
            if _nb.get("normalized"):
                orch._logger.warning(
                    "Frontend absolute localhost API origins normalized to same-origin "
                    "relative URLs (lane bypassed the nginx proxy): %s", _nb.get("normalized"))
            # VISUAL/self-contained (#75b, outlook run-62): a lane paints a CONTENT surface
            # (inbox reading-pane / feed / dashboard) with a full-bleed EXTERNAL stock photo
            # (a mountain unsplash bg) — it doesn't match the clean reference AND is an
            # external network dep in the offline sandbox (a page mid-hydration over a
            # pending image is the blank 0.00 the visual gate can't refund). Replace such
            # external CSS backgrounds with a subtle neutral gradient in the app's own
            # palette; landing/marketing/auth hero photos + all <img> content imagery kept.
            _bg = neutralize_frontend_external_backgrounds(fe)
            if _bg.get("neutralized"):
                orch._logger.warning(
                    "Frontend external stock-photo backgrounds neutralized to an in-palette "
                    "gradient (self-contained + reference-matching): %s", _bg.get("neutralized"))
            # FIX #111 (companion to #75b, runs 24+26 autopsy): external <img src> hosts
            # (pravatar/unsplash/placeholder — seen in live artifacts, in BOTH frontend
            # source and seed rows) can never resolve in the offline sandbox → the
            # broken-image glyph is a permanent visual-score wound. Localize image-signaled
            # external URLs to staged /assets/ (token match) or a deterministic placeholder
            # SVG; navigation hrefs/API bases are never image-signaled → untouched.
            try:
                from .frontend_scaffold import (
                    localize_frontend_external_images, localize_seed_external_images)
                _li = localize_frontend_external_images(fe)
                if _li.get("localized"):
                    orch._logger.warning(
                        "Frontend external image URLs localized to /assets/ (offline "
                        "sandbox, broken-image fix): %s", _li.get("localized"))
                _ls = localize_seed_external_images(_P(out_dir) / "app" / "backend", fe)
                if _ls.get("localized"):
                    orch._logger.warning(
                        "Seed-data external image URLs localized to /assets/ (%s fields; "
                        "seed fingerprint changes → loader re-seeds on next boot)",
                        _ls.get("localized"))
            except Exception as _lie:
                orch._logger.debug("external-image localization skipped: %s", _lie)
            rep = repair_frontend_api_exports(fe)
            if rep.get("repaired"):
                orch._logger.warning(
                    "Frontend api.js reconciled: aliased=%s stubbed=%s",
                    rep.get("aliased"), rep.get("stubbed"),
                )
            # INVERSE of the above: a component DEFAULT-imports api (`import api from
            # '../services/api'`) but api.js has only NAMED exports → Rollup "default is not
            # exported by api.js" → build FAIL → no delivery (outlook M2 2026-06-29). Add a
            # default export aggregating the named members.
            try:
                from .frontend_scaffold import repair_frontend_default_api_import
                _di = repair_frontend_default_api_import(fe)
                if _di.get("repaired"):
                    orch._logger.warning(
                        "Frontend api.js default export added (a component default-imports api): %s",
                        _di.get("default_export_added"))
            except Exception as _die:
                orch._logger.debug("frontend default-api-import repair skipped: %s", _die)
            # Generalize export reconciliation to ALL local modules (not just api.js):
            # a named import from a local module that doesn't export it HARD-fails the
            # Vite/rollup build (instagram_v5: PlusSquareIcon) → frontend won't build →
            # docker_up FAIL → no successful run → no delivery. Stub the missing export.
            _me = repair_frontend_missing_local_exports(fe)
            if _me.get("repaired"):
                orch._logger.warning(
                    "Frontend missing local exports stubbed (lane import/export drift): %s",
                    _me.get("repaired"))
            # Build-integrity: a page doing `import { X } from './Comp'` against a
            # default-only Comp HARD-fails the Rollup build (live: NotesListPage
            # imported { NavBar } from a default-export NavBar.jsx → docker_up FAIL).
            _nd = repair_frontend_named_default_imports(fe)
            if _nd.get("repaired"):
                orch._logger.warning(
                    "Frontend named→default imports reconciled: %s", _nd.get("fixed"))
            # Build-integrity: the frontend lane routinely imports a page it never
            # created (e.g. ./pages/MessagesInboxPage) → ``npm run build`` fails →
            # frontend container can't boot. Scaffold a valid stub for any dangling
            # local component import so the app always builds.
            # Pass the registered ui_pages so a dangling PAGE import wired at a known
            # route is projected as a REAL data page (matched to that route's contract
            # endpoint + the shared nav), not a dead heading (outlook run #8: /inbox ->
            # OutlookInbox shipped a bare <h2> while the good InboxPage sat unrouted).
            _uip = None
            try:
                _rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
                if _rh is not None and hasattr(_rh, "list_ui_pages"):
                    _uip = list((_rh.list_ui_pages() or {}).values())
            except Exception:
                _uip = None
            pages = scaffold_missing_local_pages(fe, ui_pages=_uip)
            if pages.get("scaffolded"):
                orch._logger.warning(
                    "Frontend dangling imports resolved by stub pages (lane "
                    "imported components it never created): %s",
                    pages.get("scaffolded"),
                )
            # Usability: the lane sometimes routes App.jsx to an INLINE placeholder div
            # (`element={<div>Login Page Stub</div>}`) instead of the real page that
            # already exists on disk → /login dead, /inbox blank (outlook run #9). Re-point
            # such routes to their real component so the routed pages are the real ones.
            _rr = reroute_inline_stub_routes(fe)
            if _rr.get("rerouted"):
                orch._logger.warning(
                    "Frontend inline-stub routes re-pointed to real pages: %s",
                    _rr.get("rerouted"))
            # Reconcile api-call PATHS to the registered contract (not just export
            # NAMES above): the lane drifts a path (instagram_v5: '/api/posts/feed'
            # vs the contract's '/api/feed') → runtime 404 on those pages AND the
            # delivery-gate 'frontend calls unregistered endpoint' hard-block. Rewrite
            # a unique near-miss to the registered path. GENERAL; conservative; best-effort.
            try:
                from .frontend_scaffold import reconcile_frontend_api_paths
                from ..delivery.contract_extract import param_agnostic
                _rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
                _reg_paths = set()
                if _rh is not None:
                    for _k, _v in (_rh.get_endpoints() or {}).items():
                        if _k == "_meta" or not isinstance(_v, dict):
                            continue
                        _p = _v.get("path") or ""
                        if _p:
                            _pa = param_agnostic(f"{_v.get('method') or 'GET'} {_p}")
                            _reg_paths.add(_pa.split(" ", 1)[1] if " " in _pa else _pa)
                if _reg_paths:
                    _pr = reconcile_frontend_api_paths(fe, _reg_paths)
                    if _pr.get("rewritten"):
                        orch._logger.warning(
                            "Frontend api PATHS reconciled to contract: %s",
                            _pr.get("rewritten")[:10])
            except Exception as _pp_exc:
                orch._logger.debug("frontend api-path reconcile skipped: %s", _pp_exc)
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
        for lane in ("backend", "frontend"):
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
