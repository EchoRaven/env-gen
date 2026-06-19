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
from pathlib import Path
from typing import Any, Dict, Set, Tuple

from .route_projector import _existing_routes, _express_to_fastapi, _norm_path

# Fixed runtime-owned contract surface — registered by the orchestrator, not the
# lane's business code, and served by the AS / control plane (not the audited
# route modules). Never regress these.
_FIXED_KINDS = {"auth", "oauth", "spine", "control", "health"}


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
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
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
            continue
        prefix = ""
        for kw in (node.keywords or []):
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                prefix = kw.value.value
        out[mod] = prefix
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
        endpoints = registryhub.get_endpoints() or {}
        for ep in endpoints.values():
            md = ep.get("metadata") or {}
            if str(md.get("kind") or "").lower() in _FIXED_KINDS:
                continue  # fixed AS/auth/spine/control surface — not lane business
            method = str(ep.get("method") or "").upper()
            path = ep.get("path") or ""
            if not method or not path:
                continue
            status = str(ep.get("status") or "").lower()
            is_served = _norm_route(method, path) in served
            if is_served and status != "implemented":
                registryhub.register_endpoint(
                    method, path, agent="orchestrator", status="implemented")
                out["implemented"].append(f"{method} {path}")
            elif not is_served and status == "implemented":
                registryhub.register_endpoint(
                    method, path, agent="orchestrator", status="defined")
                out["regressed"].append(f"{method} {path}")
            elif not is_served:
                out["pending"].append(f"{method} {path}")
    except Exception:
        pass
    return out


__all__ = ["served_routes", "sync_endpoint_statuses"]
