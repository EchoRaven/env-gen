"""Deterministic backend route implementation auditor — the backend twin of
``frontend_audit`` (PROPOSAL #13). A business endpoint is registered ``defined`` by
the lane; this auditor decides ``implemented`` from the CODE alone (no LLM):

  the endpoint's METHOD+PATH must have a handler on the SERVED surface — main.py's
  own ``@app.<method>`` routes PLUS the ``@router.<method>`` routes of every module
  main.py actually ``include_router()``s (the include chain). Modules whose
  decorators exist but are NEVER included (e.g. an orphan ``append_routes.py``) do
  NOT count, and a route the projector just added IS counted — so the flag tracks
  what the running app actually serves.

Why: unlike the frontend (which already has this auditor), a backend endpoint's
``implemented`` status was LANE-SELF-DECLARED via ``registryhub.register_endpoint``
with no code check — so a lane could mark ``implemented`` a route it never wired,
and api_smoke then correctly fails the "404 on status=implemented = contract lie"
(validation_runner GATE-C1) and the run grinds. This makes the flag HONEST: served
→ ``implemented``; not served → regress to ``defined`` (recomputed each audit), so
remediation routes to the genuinely-unimplemented endpoints.

NECESSARY, not sufficient: honest flags don't make a wedged lane (BUG #3) act on
the truthful "implement these" signal — that's a separate fix.

Must run on the FINAL SERVED tree: AFTER route projection (so projector-filled
routes count) AND after the agent-branch merge (so it audits what ships, not a lane
worktree). Mirrors ``frontend_audit.sync_ui_page_statuses``.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from .route_projector import (
    _duplicate_routes, _existing_routes, _express_to_fastapi, _norm_path,
    # #919: the ownership vocabulary, shared rather than re-derived — #908 was caused by two
    # functions ten lines apart holding different evidence standards for the same column.
    _owner_fk, _is_per_user_sub_entity_fk, _is_user_content_relation,
)
# Part B: the ONE shared fixed-surface definition (see kickoff/contract.py).
# Previously this file redefined ``_FIXED_KINDS`` as {auth,oauth,spine,control,
# health} — MISSING ``infra``, the kind the tenant/health control plane actually
# registers under (control_plane.CONTROL_SURFACE_ENDPOINTS) — so this auditor
# (unlike lifecycle / database_scaffold / cross_check_suite, which carried
# ``infra``) did NOT skip the control surface and repeatedly demoted it to
# ``regressed`` + hand-reimplemented it. Now every gate points at the same set.
from .kickoff.contract import (
    FIXED_ENDPOINT_KINDS as _FIXED_KINDS,
    is_control_surface_path,
)

_logger = logging.getLogger(__name__)


class BackendAuditError(RuntimeError):
    """Raised when ``sync_endpoint_statuses`` fails mid-audit (part C).

    The endpoint lifecycle this auditor maintains is a GATE input: a downstream
    delivery gate reads the resulting endpoint statuses as PASS/BLOCK. The body
    used to be wrapped in ``except Exception: pass`` and return a success-shaped
    (empty / partially-mutated) result — so a crashed audit looked like a clean
    PASS and shipped a contract lie. We now fail LOUD: log ERROR+traceback and
    raise this, so no caller can mistake a degraded audit for a clean lifecycle.
    """


def _norm_route(method: Any, path: Any) -> Tuple[str, str]:
    """(METHOD, path) → the canonical key both sides compare on — uppercase method,
    Express ``:id``→``{id}``, then every ``{param}`` collapsed to ``{}`` (so a
    declared ``/api/videos/{videoId}`` matches the decorator's ``/api/videos/{id}``).
    Same normalization route_projector / GATE-C1 use."""
    return (str(method or "").upper(),
            _norm_path(_express_to_fastapi(str(path or ""))))


def _included_modules(main_src: str) -> Dict[str, str]:
    """Modules main.py actually ``app.include_router()``s → {module_name: prefix}.

    Follows the import chain: a router NAME passed to include_router is resolved to
    the module it was imported from (``from <mod> import router as <name>``).
    ``include_router(build_router(...))`` (a Call — e.g. the OAuth AS router) is
    skipped: it isn't a statically-resolvable lane module, and its endpoints are the
    fixed AS surface anyway. Keying on the include chain (NOT hardcoded filenames)
    is what makes this correct across run shapes — custom_routes.py (run #20),
    video_routes/channel_routes/other_routes (run #18) — while excluding an orphan
    append_routes.py for free.
    """
    out: Dict[str, str] = {}
    try:
        tree = ast.parse(main_src)
    except SyntaxError:
        return out
    imported: Dict[str, str] = {}  # local_name -> source module
    plain: Dict[str, str] = {}     # #344: `import <mod> [as <alias>]`
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                plain[alias.asname or alias.name] = alias.name
    _dynamic: set = set()
    _referenced: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            _referenced.add(node.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "include_router"):
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if not isinstance(arg0, ast.Name):
            continue  # include_router(build_router(...)) etc. — not a lane module
        mod = imported.get(arg0.id)
        if not mod:
            # #344: the framework's OWN main.py mounts dynamically —
            # `import custom_routes as _custom_mod` (a plain Import) then
            # `for _custom_router in _routers: app.include_router(_custom_router)`
            # (a loop variable). Neither resolves through `imported`, so this
            # auditor returned {} for the file the framework itself emits and
            # every lane route was silently demoted implemented -> defined
            # (r91: the backend re-registered 4 auth endpoints 56 times).
            # An unresolvable include argument means a DYNAMIC mount: credit the
            # plainly-imported modules this file actually references. A module
            # that is never imported here (an orphan *_routes.py) still is not.
            _dynamic.add(arg0.id)
            continue
        prefix = ""
        for kw in (node.keywords or []):
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                prefix = kw.value.value
        out[mod] = prefix
    if _dynamic:
        for alias, mod in plain.items():
            if alias in _referenced:
                out.setdefault(mod, "")
    return out


def _apirouter_prefix(module_src: str) -> str:
    """PROPOSAL #55-v2 (BUG C): the prefix a module sets on its OWN router via
    ``router = APIRouter(prefix="/api/foo")``. A route ``@router.get("/bar")`` under such
    a router mounts at ``/api/foo/bar``, but ``_existing_routes`` sees only ``/bar`` and
    ``_included_modules`` only reads a prefix from the ``include_router(prefix=...)`` site
    — so without this the real endpoint is FALSE-DEMOTED (the 404=contract-lie revert) and
    never satisfies business_endpoints_implemented. Returns the first APIRouter prefix
    found in the module, else ''. (FastAPI idiom + the lane's editable custom_routes.py.)"""
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "APIRouter")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "APIRouter")):
            for kw in (node.keywords or []):
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    return kw.value.value
    return ""


def served_routes(backend_dir: Path) -> Set[Tuple[str, str]]:
    """The (METHOD, normpath) set actually MOUNTED on the served app: main.py's own
    ``@app`` routes PLUS the ``@router`` routes of every module main.py includes
    (with that include's prefix). Orphan, never-included modules are excluded."""
    served: Set[Tuple[str, str]] = set()
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return served
    try:
        main_src = main_py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return served
    served |= _existing_routes(main_src)  # main.py @app.<method> (already normalized)
    for mod, prefix in _included_modules(main_src).items():
        modfile = backend_dir / f"{mod}.py"
        if not modfile.exists():
            continue
        try:
            msrc = modfile.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Effective mount prefix = include-site prefix + the module's own
        # APIRouter(prefix=...) (BUG C: the latter was previously ignored → false demote).
        eff_prefix = (prefix or "") + _apirouter_prefix(msrc)
        for method, path in _existing_routes(msrc):
            # _existing_routes already normalized path; re-normalize with the
            # effective prefix prepended (no-op when it's "").
            served.add((method, _norm_path(eff_prefix + path) if eff_prefix else path))
    return served


def duplicated_routes(backend_dir: Path) -> Set[Tuple[str, str]]:
    """(METHOD, normpath) routes defined 2+ times WITHIN a single served module —
    intra-module collisions FastAPI silently shadows (it mounts only the FIRST). A
    cross-module override (main.py's projected handler + a custom_routes.py override)
    is NOT flagged — only same-file duplicates, which are always a lane bug. See
    route_projector._duplicate_routes / audit #6."""
    dups: Set[Tuple[str, str]] = set()
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return dups
    try:
        main_src = main_py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return dups
    dups |= _duplicate_routes(main_src)
    for mod, prefix in _included_modules(main_src).items():
        modfile = backend_dir / f"{mod}.py"
        if not modfile.exists():
            continue
        try:
            msrc = modfile.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        eff_prefix = (prefix or "") + _apirouter_prefix(msrc)
        for method, path in _duplicate_routes(msrc):
            dups.add((method, _norm_path(eff_prefix + path) if eff_prefix else path))
    return dups


def sync_endpoint_statuses(project_dir: Any, registryhub: Any) -> Dict[str, Any]:
    """Audit every registered BUSINESS endpoint against the served code; flip its
    status through ``register_endpoint`` (orchestrator actor — fires
    ``endpoint_implemented`` only on a real transition). Best-effort, idempotent,
    recompute-both-ways. Returns {implemented:[...], regressed:[...], pending:[...]}.
    """
    out: Dict[str, Any] = {"implemented": [], "regressed": [], "pending": []}
    try:
        backend_dir = Path(project_dir) / "app" / "backend"
        if registryhub is None or not backend_dir.is_dir():
            return out
        served = served_routes(backend_dir)
        dups = duplicated_routes(backend_dir)
        endpoints = registryhub.get_endpoints() or {}
        for ep in endpoints.values():
            md = ep.get("metadata") or {}
            method = str(ep.get("method") or "").upper()
            path = ep.get("path") or ""
            # Skip the fixed runtime-owned surface by KIND (shared set incl. infra/
            # control) OR by PATH (behavior net, part A): the tenant/health/admin
            # control plane (/health, /api/v1/admin/*, /api/v1/reset, /api/v1/tenants*,
            # init-tenant) is served by the control plane — never a lane business
            # endpoint — so it must not be demoted/regressed even if its ``kind`` tag
            # is absent or wrong.
            if (str(md.get("kind") or "").lower() in _FIXED_KINDS
                    or is_control_surface_path(path)):
                continue
            if not method or not path:
                continue
            status = str(ep.get("status") or "").lower()
            _nr = _norm_route(method, path)
            is_served = _nr in served
            if _nr in dups:
                # Intra-module DUPLICATE route: FastAPI mounts only the first def and
                # shadows the rest, so which handler actually serves is ambiguous and a
                # broken first def would ship green (audit #6). Refuse to credit it as
                # implemented — demote if it was — so the gate + remediation force the
                # lane to remove the duplicate. Behavior-based, not presence-based.
                if status == "implemented":
                    registryhub.register_endpoint(
                        method, path, agent="orchestrator", status="defined")
                out.setdefault("duplicated", []).append(f"{method} {path}")
            elif is_served and status != "implemented":
                registryhub.register_endpoint(
                    method, path, agent="orchestrator", status="implemented")
                out["implemented"].append(f"{method} {path}")
            elif not is_served and status == "implemented":
                registryhub.register_endpoint(
                    method, path, agent="orchestrator", status="defined")
                out["regressed"].append(f"{method} {path}")
            elif not is_served:
                out["pending"].append(f"{method} {path}")
        if out.get("regressed"):
            # #344: a demotion REVERSES a lane's own write, and it used to be
            # silent — `grep -c "ENDPOINT LIFECYCLE"` over r91 returns 0 while
            # the backend re-registered the same 4 endpoints 56 times over
            # 5h41m, each time being told it was wrong. A gate input that
            # overrules an agent must be visible in the run log.
            _logger.warning(
                "ENDPOINT LIFECYCLE: %d endpoint(s) demoted implemented -> defined "
                "because no mounted route was found for them in main.py's include "
                "graph. If the lane DID author these, the auditor is blind to how "
                "they are mounted (see #344): %s",
                len(out["regressed"]), out["regressed"],
            )
        if out.get("duplicated"):
            _logger.warning(
                "backend_audit: %d endpoint(s) have DUPLICATE/shadowed route defs "
                "(FastAPI serves only the first — remove the dup in custom_routes.py): %s",
                len(out["duplicated"]), out["duplicated"],
            )
    except Exception as exc:
        # Part C — FAIL LOUD. This audit's output is a GATE input: a swallowed
        # failure used to return a success-shaped (empty / partially-mutated)
        # lifecycle that the delivery gate read as PASS, shipping a contract lie.
        # Log the real cause WITH traceback at ERROR, mark the result degraded,
        # and re-raise a typed BackendAuditError so the caller cannot treat a
        # crashed/partial audit as a clean run. (No silent fallback.)
        out["degraded"] = True
        out["error"] = repr(exc)
        _logger.error(
            "backend_audit.sync_endpoint_statuses FAILED mid-audit (endpoint "
            "lifecycle is DEGRADED/partial — must not be read as PASS): %s",
            exc, exc_info=True,
        )
        raise BackendAuditError(
            "backend endpoint-status audit failed; endpoint lifecycle is "
            f"degraded and must not be trusted as a delivery-gate PASS: {exc!r}"
        ) from exc
    return out


# ── FIX #173: PLACEHOLDER-STUB backend handlers ───────────────────────────────
# gmrun9 shipped a GET handler `def get_departures(...): return {"items": []}` (the lane's
# comment literally said "This is a stub for departures") even though real seed data existed
# (transit_stops.line_refs → transit_lines). The DeparturesPage then permanently rendered
# "No departures found." — a placeholder page. The no_real_data browser gate was fooled by a
# weak token on the walk. A GET route handler that never touches the DB and returns a
# hardcoded EMPTY collection can NEVER serve real data → catch it by construction here (the
# backend twin of frontend_audit's ui_page_delivery_blockers), so delivery HOLDS until the
# handler queries the real table. Deterministic AST, best-effort, recomputed each gate tick.
_COLLECTION_KEYS = frozenset({
    "items", "results", "data", "rows", "list", "records", "departures", "entries",
    "content", "docs", "objects", "elements", "collection",
})
# Attribute/name calls that indicate the handler actually reads the DB (so it's not a
# constant stub even if one branch returns an empty guard).
# NB: exclude the ambiguous ``get`` (dict.get / query_params.get) — it would mask a real
# stub. The listed attrs are strong SQLAlchemy read signals.
_DB_CALL_ATTRS = frozenset({
    "query", "execute", "scalars", "scalar", "all", "first", "one", "one_or_none",
    "filter", "filter_by", "count", "fetchall", "fetchone", "exec",
})
_DB_CALL_NAMES = frozenset({"select", "text"})


def _handler_routes(fn: Any) -> Set[Tuple[str, str]]:
    """The (METHOD, normalized-path) routes this function serves — parsed from its
    ``@router.get("/x")`` / ``@app.post("/y")`` decorators. Empty ⇒ not a route handler.
    A function can carry several route decorators (e.g. ``/api/x`` + ``/api/v1/x``)."""
    routes: Set[Tuple[str, str]] = set()
    for dec in getattr(fn, "decorator_list", []) or []:
        if not isinstance(dec, ast.Call):
            continue
        target = dec.func
        if not (isinstance(target, ast.Attribute) and target.attr.lower() in (
                "get", "post", "put", "patch", "delete", "options", "head")):
            continue
        method = target.attr.upper()
        path = None
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            path = dec.args[0].value
        else:  # @router.get(path="/x")
            for kw in dec.keywords or []:
                if kw.arg == "path" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    path = kw.value.value
        if path:
            # Skip framework-owned CONTROL-SURFACE routes (tenants / control plane / health /
            # oauth …): a hardcoded default there (e.g. get_tenants → the "default" tenant) is
            # intentional infra, not an app placeholder — the lane can't/shouldn't rewrite it,
            # so flagging it would churn to a NO-CONVERGENCE abort. Mirrors the FIXED_KINDS
            # skip every other backend audit already applies.
            try:
                if is_control_surface_path(path):
                    continue
            except Exception:
                pass
            routes.add(_norm_route(method, path))
    return routes


def _constant_row_1083(node: Any) -> bool:
    """Every value in ``node`` is a literal — no name, call, f-string or comprehension.

    #173's mock-row rule keyed on "a list element is a dict", and its own docstring's example
    of what that means is ``[{"id": "dep_1", "line": "A"}]`` — all constants. It never
    checked. gmrun7 (`2of3-forcedeliver`) returns a directions row whose every field is
    computed from the query params (``round(dist, 2)``, ``int(dist * 10)``, an f-string), and
    a computed endpoint cannot take the remedy the blocker gives it ("query the real seeded
    table"). Measured over the 83 generated backends: of the returns carrying a dict literal
    inside a list, 87 have a dynamic value and 5 are entirely constant — the premise is wrong
    far more often than right, so require what the docstring always described."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_constant_row_1083(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_constant_row_1083(v) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        return _constant_row_1083(node.operand)
    return False


def _placeholder_collection_literal(node: Any) -> bool:
    """True iff ``node`` is a HARDCODED collection with no real data behind it:
      • an empty list ``[]`` (the classic stub), or
      • a list whose elements include a dict/object literal (hardcoded MOCK rows —
        ``[{"id": "dep_1", "line": "A"}]``), or
      • a dict-envelope whose collection key(s) (``items`` / ``results`` / …) map to
        either of the above (``{"items": []}`` / ``{"items": [{...}]}``).
    A NON-empty list of scalars (static options ``["driving", "walking"]``) or a dynamic
    value (a comprehension over query rows) is NOT a placeholder."""
    if isinstance(node, ast.List):
        if len(node.elts) == 0:
            return True  # empty stub
        if not any(isinstance(e, ast.Dict) for e in node.elts):
            return False
        # #1083: hardcoded mock rows means CONSTANT rows. A row computed from the request
        # (gmrun7's directions) is a real answer, not a fixture — see _constant_row_1083.
        return all(_constant_row_1083(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        saw_collection = False
        for k, v in zip(node.keys, node.values):
            key = (k.value.lower() if isinstance(k, ast.Constant)
                   and isinstance(k.value, str) else None)
            if key in _COLLECTION_KEYS:
                if _placeholder_collection_literal(v):
                    saw_collection = True
                else:
                    return False  # collection key with real/dynamic/scalar value ⇒ not placeholder
        return saw_collection
    return False


def _returns_only_placeholder_collections(fn: Any) -> bool:
    """Every value-bearing ``return`` in the body is a placeholder-collection literal (empty
    or hardcoded mock rows), and there is at least one — the handler emits only fake data."""
    # Walk only the BODY (not decorator_list / arg defaults) so nothing outside the
    # implementation is mistaken for a return.
    returns = [n for stmt in fn.body for n in ast.walk(stmt)
               if isinstance(n, ast.Return) and n.value is not None]
    if not returns:
        return False
    return all(_placeholder_collection_literal(r.value) for r in returns)


def _reads_db(fn: Any) -> bool:
    """The handler body calls something that reads the DB (``db.query(...)``, ``.all()``,
    ``select(...)`` …) — then an empty return is a legitimate empty result, not a stub.
    Walks only ``fn.body`` — CRUCIALLY not the decorator_list, so the handler's own
    ``@router.get`` (a ``.get`` Call) is not mistaken for a DB read."""
    for stmt in fn.body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Attribute) and f.attr.lower() in _DB_CALL_ATTRS:
                    return True
                if isinstance(f, ast.Name) and f.id.lower() in _DB_CALL_NAMES:
                    return True
    return False


_OWNED_READ_919 = "unscoped owner read"


def _models_919(backend_dir: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Tables and their columns/FKs, parsed from the delivered ORM. Returns ({table: meta},
    {ClassName: table}); best-effort and total."""
    models: Dict[str, Dict[str, Any]] = {}
    cls2tbl: Dict[str, str] = {}
    try:
        for fname in ("models.py", "main.py"):
            f = Path(backend_dir) / fname
            if not f.is_file():
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, ast.ClassDef):
                    continue
                tbl = None
                cols: List[str] = []
                fks: Dict[str, str] = {}
                for a in n.body:
                    if not (isinstance(a, ast.Assign) and a.targets
                            and isinstance(a.targets[0], ast.Name)):
                        continue
                    nm = a.targets[0].id
                    if nm == "__tablename__" and isinstance(a.value, ast.Constant):
                        tbl = str(a.value.value)
                    if isinstance(a.value, ast.Call) and getattr(
                            a.value.func, "id", getattr(a.value.func, "attr", "")) == "Column":
                        cols.append(nm)
                        for arg in a.value.args:
                            if (isinstance(arg, ast.Call)
                                    and getattr(arg.func, "id", "") == "ForeignKey"
                                    and arg.args and isinstance(arg.args[0], ast.Constant)):
                                fks[nm] = str(arg.args[0].value).split(".")[0]
                if tbl and tbl not in models:
                    models[tbl] = {"cols": cols, "fks": fks}
                    cls2tbl[n.name] = tbl
    except Exception:
        return {}, {}
    return models, cls2tbl


def unscoped_owner_read_findings(backend_dir: Any) -> List[str]:
    """#919: a served GET that returns rows of an OWNED table without filtering by the caller.

    The page-level privacy axis. #908 was a live cross-user leak in r153 -- `GET /api/my-list`
    answering `db.query(MyList).limit(100).all()` to any authenticated caller, beside a POST that
    403s a foreign `profile_id` -- and it passed every gate in the framework, because no gate asks
    this question. It was found by reading the delivered app by hand.

    The decision is not re-derived here: `_owner_fk` recognises the owner column and
    `_is_per_user_sub_entity_fk` / `_is_user_content_relation` decide whether the read SHOULD be
    scoped, exactly as `route_projector` decides whether to EMIT the filter. Sharing them is the
    point -- #908 existed because two functions ten lines apart held different evidence standards
    for the same column.

    Measured over the 153 delivered backends: **159 findings, and only two distinct endpoints** --
    `/api/my-list` (79) and `/api/continue-watching` (80), both genuinely per-user. No other path
    fires, so the signal is the leak itself rather than a class of near-misses.

    Best-effort ``[]`` on any fault; the caller decides the disposition.
    """
    out: List[str] = []
    try:
        main = Path(backend_dir) / "main.py"
        if not main.is_file():
            return []
        src = main.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
        models, cls2tbl = _models_919(backend_dir)
        if not models:
            return []
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            paths = [d.args[0].value for d in n.decorator_list
                     if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and d.func.attr == "get" and d.args
                     and isinstance(d.args[0], ast.Constant)]
            if not paths:
                continue
            body = ast.get_source_segment(src, n) or ""
            # any filter at all -- ORM or raw SQL -- means the handler took a position on scope
            if ".filter(" in body or "WHERE" in body.upper():
                continue
            model = None
            for c in ast.walk(n):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "query" and c.args):
                    model = getattr(c.args[0], "id", None)
            meta = models.get(cls2tbl.get(model or "") or "")
            if not meta:
                continue
            fk = _owner_fk(meta)
            if not fk:
                continue                      # a public catalog table -- unfiltered is correct
            if not (_is_per_user_sub_entity_fk(meta, fk, models)
                    or _is_user_content_relation(meta, fk)):
                continue                      # ambiguous ownership -- the projector leaves it too
            out.append(
                "%s: GET %s returns every row of `%s` to any authenticated caller -- the table is "
                "owned via `%s` and the handler applies no owner filter, while its paired write "
                "refuses a foreign owner. Scope the read to the caller (#919)."
                % (_OWNED_READ_919, paths[0], cls2tbl.get(model or "", "?"), fk))
    except Exception:
        return []
    return out


# ── #1100: a handler that does NOTHING, on ANY verb ───────────────────────────
# `stub_handler_blockers` examines GET only (`r[0] == "GET"`), because its subject
# is a page that renders no real data. A handler whose ENTIRE body is `pass` has a
# different and verb-independent failure: FastAPI serializes the implicit None, the
# route answers `null`, and any caller that reads a field off the response throws.
# tiktok-r50 shipped `def auth_signup_stub(): pass` on POST /auth/signup, whose own
# frontend does `const data = await fetchApi('/auth/signup', …); return data.item` —
# a delivered app in which no account can be created. The three stubs there are the
# only genuine ones in the corpus (65 backends, 2873 route handlers), and all three
# sit on /auth/*, which `lifecycle.is_business` removes from every other check on the
# grounds that the framework owns that prefix — but the AS template owns exactly six
# paths, and signup is not one of them. Two exclusions overlapping leaves the code
# nobody looks at.
_NO_CONTENT_STATUS_1100 = frozenset({204, 205, 304})


def _declares_no_content_1100(fn: Any) -> bool:
    """True iff a route decorator declares a status that CARRIES no body.

    ``@router.post("/auth/logout", status_code=204)`` + ``return None`` is the
    correct way to write a no-content endpoint, not a stub — four of the seven
    empty-bodied handlers in the corpus are exactly this and must never be flagged.
    """
    for dec in getattr(fn, "decorator_list", []) or []:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
            continue
        for kw in dec.keywords or []:
            if (kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
                    and kw.value.value in _NO_CONTENT_STATUS_1100):
                return True
    return False


def _is_empty_body_1100(fn: Any) -> bool:
    """True iff the function body is a single no-op, ignoring its docstring.

    `pass`, `...`, a bare `return`, `return None`, and `raise NotImplementedError`
    are the shapes an LLM writes when it means "not written yet". Nothing else is
    accepted, so this cannot fire on a handler that does any work at all.
    """
    body = [b for b in getattr(fn, "body", []) or []
            if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                    and isinstance(b.value.value, str))]
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis):
        return True
    if isinstance(stmt, ast.Return) and (
            stmt.value is None
            or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)):
        return True
    if isinstance(stmt, ast.Raise):
        exc = stmt.exc
        name = getattr(getattr(exc, "func", exc), "id", None) \
            or getattr(getattr(exc, "func", exc), "attr", None)
        if name == "NotImplementedError":
            return True
    return False


def stub_handler_blockers(backend_dir: Any) -> List[str]:
    """Delivery blockers for PLACEHOLDER-STUB backend handlers: a GET route whose SERVED
    handler does NO DB read and returns only a hardcoded EMPTY-or-MOCK collection.

    Route-aware so a dead PROJECTED fallback (``_projected_*``, shadowed by a real custom
    handler that is registered first / wins) is never flagged — only the handler that
    actually serves the route. gmrun9 v1.3.0: the projected departures stub was shadowed by
    a custom handler returning MOCK rows (``[{"line": "A", "time": "5 min"}]``) — the served
    handler was the mock, so THAT is the placeholder, not the (shadowed) projected one.

    Best-effort + pure; ``[]`` on any fault or a non-dir path.
    ``ENVGEN_STUB_HANDLER_GATE=0`` disables."""
    import os as _os
    from collections import defaultdict
    if _os.environ.get("ENVGEN_STUB_HANDLER_GATE", "1").strip().lower() in (
            "0", "false", "no", "off"):
        return []
    root = Path(backend_dir)
    if not root.is_dir():
        return []
    # 1) collect every GET route handler with its verdicts
    handlers: List[Dict[str, Any]] = []
    # #1100: every route handler on ANY verb, for the empty-body check. Collected in
    # the same walk (one parse) and BEFORE the GET filter below, which would otherwise
    # drop the POST/PUT/DELETE handlers this check exists to see.
    all_handlers_1100: List[Dict[str, Any]] = []
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _routes_1100 = _handler_routes(node)
            if _routes_1100:
                all_handlers_1100.append({
                    "name": node.name,
                    "file": py.name,
                    "projected": node.name.startswith("_projected_"),
                    "empty": _is_empty_body_1100(node),
                    "no_content": _declares_no_content_1100(node),
                    "routes": _routes_1100,
                })
            get_routes = {r for r in _routes_1100 if r[0] == "GET"}
            if not get_routes:
                continue
            handlers.append({
                "name": node.name,
                "file": py.name,
                "projected": node.name.startswith("_projected_"),
                "reads_db": _reads_db(node),
                "placeholder": _returns_only_placeholder_collections(node),
                "routes": get_routes,
            })
    # 2) group by route; the SERVED handler wins (a non-projected custom handler shadows the
    #    projected fallback). Flag a route only when EVERY served handler is a no-DB placeholder.
    by_route: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for h in handlers:
        for r in h["routes"]:
            by_route[r].append(h)
    # FIX #206: aggregate/computed qualifiers. A FRAMEWORK stub whose route ends in
    # one of these ('suggested creators', 'trending videos') is a genuinely-computed
    # view with no plain backing table — an honest empty state, not a fixable stub.
    # SOFT (skip) it; the no_real_data browser gate stays the backstop. Lane-custom
    # stubs + non-aggregate framework stubs stay HARD. ENVGEN_AGGREGATE_STUB_SOFT=0 off.
    _AGG = {"suggested", "recommended", "popular", "trending", "featured",
            "discover", "explore", "nearby", "foryou", "for-you", "top",
            "highlights", "picks", "spotlight"}
    _agg_soft = _os.environ.get("ENVGEN_AGGREGATE_STUB_SOFT", "1").strip().lower() \
        not in ("0", "false", "no", "off")

    def _is_aggregate_route(routes) -> bool:
        for r in routes:
            _p = str(r[1] if isinstance(r, tuple) else r).split("?", 1)[0]
            _segs = [s for s in _p.strip("/").split("/")
                     if s and not (s.startswith("{") or s.startswith(":"))]
            if _segs and _segs[-1].lower().replace("_", "").replace("-", "") in {
                    a.replace("_", "").replace("-", "") for a in _AGG}:
                return True
        return False

    flagged: Dict[str, Dict[str, Any]] = {}  # handler name → {file, projected, routes}
    for _route, hs in by_route.items():
        non_projected = [h for h in hs if not h["projected"]]
        served = non_projected or hs
        if served and all((not h["reads_db"] and h["placeholder"]) for h in served):
            # #206: a PROJECTED stub on an aggregate route is a soft/honest empty
            # state — skip it (only when ALL served handlers are framework-projected;
            # a lane custom handler on the route keeps it HARD, the lane owns it).
            if (_agg_soft and all(h["projected"] for h in served)
                    and _is_aggregate_route([_route])):
                continue
            for h in served:
                rec = flagged.setdefault(
                    h["name"], {"file": h["file"], "projected": h["projected"],
                                "routes": set()})
                rec["routes"] |= {f"{m} {p}" for m, p in h["routes"]}

    # #1100: a route whose every SERVED handler does nothing. Grouped over ALL
    # handlers on the route (not just the empty ones) so a real implementation
    # shadows a stub: tiktok-r50's `pass` on POST /auth/login sits behind the AS
    # template's real login, which main.py includes FIRST and which therefore
    # serves the route — flagging it would be a false positive. Its /auth/signup
    # and /auth/logout stubs have no such shadow and are the true finding.
    empty_flagged_1100: Dict[str, Dict[str, Any]] = {}
    by_any_route_1100: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for h in all_handlers_1100:
        for r in h["routes"]:
            by_any_route_1100[r].append(h)
    for _route, hs in by_any_route_1100.items():
        non_projected = [h for h in hs if not h["projected"]]
        served = non_projected or hs
        # `no_content` is not "empty" — a 204 handler returning None is CORRECT, and
        # one such handler on the route means the route is answered properly.
        if not (served and all(h["empty"] and not h["no_content"] for h in served)):
            continue
        for h in served:
            rec = empty_flagged_1100.setdefault(
                h["name"], {"file": h["file"], "routes": set()})
            rec["routes"] |= {f"{m} {p}" for m, p in h["routes"]}

    def _msg_empty_1100(name: str, rec: Dict[str, Any]) -> str:
        _routes = ", ".join(sorted(rec["routes"]))
        return (
            f"backend handler `{name}` ({rec['file']}) serving {_routes} has an EMPTY "
            "BODY — it does no work and returns nothing, so the route answers `null` and "
            "any caller reading a field off the response throws (tiktok-r50 wrote this "
            "on POST /auth/signup while its own UI does `data.item` on the reply, so no "
            "account could be created). Implement the handler. If the endpoint genuinely returns "
            "no content, say so on the route — `status_code=204` — instead of leaving the "
            "body empty.")

    def _msg(name: str, rec: Dict[str, Any]) -> str:
        _routes = ", ".join(sorted(rec["routes"])) or "a GET route"
        if rec["projected"]:
            # FIX #201 (r10 wall): a FRAMEWORK `_projected_*` stub is regenerated in
            # main.py every cycle — the lane CANNOT edit it, so "replace the handler"
            # is non-actionable and #173 walls forever. The projector stubs a GET only
            # when the path maps to NO table (#200 resolves name/segment drift), so the
            # lane-actionable remedy is a CONTRACT change it owns: declare the backing
            # table, or drop the endpoint. NOT a HARD-vs-SOFT change — still blocks.
            return (
                f"endpoint {_routes} has a FRAMEWORK-projected PLACEHOLDER STUB "
                f"(`{name}` in {rec['file']}) returning an empty/mock collection with NO "
                "database query — because the path maps to NO backing table. You CANNOT "
                "edit the projected handler; instead make the endpoint resolvable: declare "
                "the backing table for this resource (kickoff_declare_table / "
                "registryhub_register_table with the columns its page needs), or if the "
                "endpoint is not real, REMOVE it from the contract. Once a table backs the "
                "route the projector reads it automatically.")
        return (
            f"backend handler `{name}` ({rec['file']}) is a PLACEHOLDER STUB — the served "
            f"handler for {_routes} returns a hardcoded empty/mock collection with NO "
            "database query, so its page can never render real data (gmrun9 shipped exactly "
            "this for transit departures). Query the real seeded table(s) and return the "
            "rows. Do NOT return a hardcoded empty/mock collection.")

    return ([_msg(name, rec) for name, rec in sorted(flagged.items())]
            + [_msg_empty_1100(name, rec)
               for name, rec in sorted(empty_flagged_1100.items())])


def unreachable_but_mounted(backend_dir: Path, unreachable: Iterable[str]) -> List[str]:
    """#1006: endpoints the smoke could not reach that main.py DOES mount.

    A framework-owned file declares the route, the static route table agrees it is mounted,
    and the running app answers 405/404 anyway. **Nobody can fix that.** `main.py` is in
    `_BACKEND_FRAMEWORK_OWNED`, so the write guard denies every lane edit to it — dispatching
    this to a backend lane cannot succeed no matter how capable the lane is.

    r162 is the case this exists for. `POST /api/continue-watching` sat in `served_routes()`
    from 11:46, four rebuilds followed, and the smoke still reported 405 from 12:18 to the end
    of the run. The framework read that as a lane failure and dispatched 17 tasks against it;
    the run then died on `unresolved_failed_tasks`, counting its own undeliverable work.

    Three explanations were tested against the artifacts and all three failed: the image
    builds from the worktree (not a branch, so `main` lacking the commit is irrelevant), four
    rebuilds happened after the fix landed, and the framework's own `duplicated_routes` audit
    reports zero intra-module shadowing. Whatever the runtime cause turns out to be, the
    CLASSIFICATION is knowable statically and is what this returns.

    Accepts the `METHOD path → status` fragments the validation runner already produces.
    """
    mounted = served_routes(backend_dir)
    out: List[str] = []
    for item in unreachable or ():
        m = re.match(r"\s*([A-Z]+)\s+(\S+)", str(item))
        if not m:
            continue
        if _norm_route(m.group(1), m.group(2)) in mounted:
            out.append(str(item).strip())
    return out


__all__ = ["served_routes", "sync_endpoint_statuses", "BackendAuditError",
           "stub_handler_blockers", "unreachable_but_mounted"]


# --- #1202s: lane code must not take over authentication -------------------------------
# r30 delivered its first milestone at 13:32:37 with this in `custom_routes.py`, merged at
# 13:10:30 — twenty-two minutes earlier:
#
#     _orig_verify_user_password = _OAuthStore.verify_user_password
#     def _sandbox_verify_or_create_user(self, email, password, tenant_id="default"):
#         user = _orig_verify_user_password(self, email, password, tenant_id=tenant_id)
#         if user is not None:
#             return user
#         ...  # wrong password on an EXISTING user -> overwrite its password_hash and return it
#         ...  # unknown email                      -> create the account and return it
#     _OAuthStore.verify_user_password = _sandbox_verify_or_create_user
#
# Verified against the delivered stack: `ava.chen@example.com` with WRONG_PASSWORD returns 200
# and a valid bearer token, and so does `nobody@nowhere.invalid`. Only an EMPTY pair is
# refused. The app has no authentication, and it shipped.
#
# The lane's own comment says why: "The verifier's login-page flow ... treats the initial 401
# as a network failure". It disabled the check to make a validator complaint go away — which
# is the one failure mode an environment built to TEST agent security cannot have.
#
# The framework caught it eventually: a denial-probe chain (`POST /auth/login -> 200, expected
# [401, 400]`) failed and blocked milestone 2 until the run aborted STUCK. That is 148 minutes
# too late and one release too late, because the probe runs in validation while the release
# gate had already passed.
#
# So check the property structurally instead of behaviourally: the framework universally owns
# /auth/register and /auth/login, therefore lane code REASSIGNING an auth primitive is never
# legitimate, whatever it is trying to fix. AST, so a rename or a reformat cannot slip past a
# text match, and it reads only lane-owned files — the framework's own modules define these
# functions and must not flag themselves.
_AUTH_PRIMITIVES_1202S = frozenset({
    "verify_user_password", "verify_user_by_username", "_hash_password",
    "check_password", "verify_password", "authenticate_user", "get_current_user",
})
_LANE_OWNED_1202S = ("custom_routes.py",)
# Replacing the PASSWORD CHECK with a provisioner is a bypass in every reading; replacing a
# request-scoped identity resolver can be a tightening. Only the first blocks.
_BLOCKING_AUTH_PRIMITIVES_1202S = frozenset({
    "verify_user_password", "verify_user_by_username", "check_password", "verify_password"})


def _writes_users_1202s(fn: Any) -> bool:
    """Does this replacement WRITE to the user store? (#1202s)

    The distinction that keeps this check honest. Reassigning an auth primitive is not by
    itself a bypass — measured over 93 runs, 5 do it and they do opposite things:

        r30, r24  verify_user_password -> creates the account, or resets its password, when
                  the original refused.  A bypass.
        r73       get_current_user -> _tenant_scoped_get_current_user.  Adds tenant isolation,
                  which is the multi-tenancy the framework asks for.  NARROWER.
        r24       get_current_user -> _strict_current_user.  Narrower again.
        r21       accepts framework-minted tokens through a store race.  Ambiguous.

    A check that only narrows is a check. What makes r30's a bypass is that it PROVISIONS:
    an INSERT or UPDATE against the user store inside the verification path means the
    function hands out an identity it was asked to verify. Blocking on the reassignment alone
    would have blocked r73 for tightening security, so the write is the signal.
    """
    import ast as _ast
    for n in _ast.walk(fn):
        if isinstance(n, _ast.Constant) and isinstance(n.value, str):
            t = n.value.strip().upper()
            if (t.startswith("INSERT INTO USERS") or t.startswith("UPDATE USERS")
                    or "UPDATE USERS SET" in t or "INSERT INTO USERS" in t):
                return True
        if isinstance(n, _ast.Call):
            f = n.func
            nm = getattr(f, "attr", None) or getattr(f, "id", None)
            if nm in ("create_user", "_create_user", "register_user", "add_user"):
                return True
    return False


def _widens_auth_1202s(tree: Any, assign_node: Any) -> bool:
    """True when the value assigned to an auth primitive provisions users. (#1202s)"""
    import ast as _ast
    try:
        val = getattr(assign_node, "value", None)
        target_names = set()
        if isinstance(val, _ast.Name):
            target_names.add(val.id)
        elif isinstance(val, _ast.Attribute):
            target_names.add(val.attr)
        elif isinstance(val, (_ast.Lambda, _ast.Call)):
            return False        # not a named replacement we can read
        if not target_names:
            return False
        for n in _ast.walk(tree):
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name in target_names:
                if _writes_users_1202s(n):
                    return True
        return False
    except Exception as _e1202ae:
        # #1202ae: a detector that CRASHED must not read as a detector that found
        # nothing. The gate wrapper announces via #792 when it cannot run, but it only sees
        # this function's return value — a bare `[]` here makes the wrapper report "clean"
        # and the announcement never fires. That is the exact shape this session kept
        # finding in other people's code (#1201, #1039, the seed audit), written by me into
        # a SECURITY gate.
        from .message_format import warn_once_1201
        warn_once_1201("_widens_auth_1202s", "the auth-provisioning check (#1202s) — a bypass may go unblocked", _e1202ae)
        return False


def auth_override_findings_1202s(backend_dir: Any) -> List[str]:
    """Lane-owned code reassigning a framework auth primitive. Static; `[]` on any failure."""
    out: List[str] = []
    try:
        import ast as _ast
        base = Path(backend_dir)
        for fname in _LANE_OWNED_1202S:
            f = base / fname
            if not f.is_file():
                continue
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in _ast.walk(tree):
                targets = []
                if isinstance(node, _ast.Assign):
                    targets = node.targets
                elif isinstance(node, _ast.AnnAssign) and node.target is not None:
                    targets = [node.target]
                for t in targets:
                    name = None
                    if isinstance(t, _ast.Attribute):
                        name = t.attr
                    elif isinstance(t, _ast.Name):
                        name = t.id
                    # #1202s: BLOCK only the unambiguous case — the password check itself
                    # replaced by something that provisions users. Measured over 93 runs, the
                    # other primitives are genuinely ambiguous: r21 replaces `get_current_user`
                    # with a wrapper that pyjwt-VERIFIES the framework's own signature and then
                    # materializes the local row for an identity already proven, and r73's
                    # replacement adds tenant scoping. Blocking those would block a lane for
                    # tightening security, which is the #566j failure mode this repo has already
                    # paid 75 minutes for.
                    if (name in _BLOCKING_AUTH_PRIMITIVES_1202S
                            and _widens_auth_1202s(tree, node)):
                        out.append(
                            "%s reassigns the auth primitive `%s` (line %d). The framework owns "
                            "/auth/login and /auth/register; a lane that replaces the password "
                            "check turns the app into one that accepts any credentials — r30 "
                            "shipped exactly that. Fix the flow the validator is complaining "
                            "about, not the check it complains through."
                            % (fname, name, getattr(node, "lineno", 0)))
    except Exception as _e1202ae:
        # #1202ae: a detector that CRASHED must not read as a detector that found
        # nothing. The gate wrapper announces via #792 when it cannot run, but it only sees
        # this function's return value — a bare `[]` here makes the wrapper report "clean"
        # and the announcement never fires. That is the exact shape this session kept
        # finding in other people's code (#1201, #1039, the seed audit), written by me into
        # a SECURITY gate.
        from .message_format import warn_once_1201
        warn_once_1201("auth_override_findings_1202s", "the lane auth-override gate (#1202s) — delivery is NOT known clean", _e1202ae)
        return []
    return sorted(set(out))
