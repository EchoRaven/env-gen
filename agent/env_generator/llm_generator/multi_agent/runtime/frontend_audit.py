"""Deterministic UI-page implementation auditor (mechanism #50).

USER DESIGN (2026-06-11): the frontend mirrors the backend's by-construction
lifecycle. A ui_page is DECLARED at kickoff (name + route + component +
apis_used) and registered ``defined``; this auditor decides ``implemented``
from the CODE alone — no LLM, no template, no style judgment:

  * the declared component exists under ``src/`` (its own file, or the
    component name appears in a page/component source);
  * the declared route is wired in ``App.jsx``;
  * every declared API appears in the frontend source (loose path match —
    the call site may build the URL, so we look for the path literal);
  * the page's interactive markup is bound (no dead controls).

Flipping a page to ``implemented`` via ``workhub.update_ui_page`` completes
its ``impl.page.<name>`` task through cross-hub sync — exactly how
``impl.table.*`` flows. A page that regresses flips back to ``defined``
(lifecycle is recomputed from code truth each audit).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_HANDLER_TOKENS = ("onSubmit", "onClick", "fetch(", "apiGet", "apiPost",
                   "apiPut", "apiDelete", "axios")


def _norm_api(entry: str) -> str:
    """'GET /api/posts' → '/api/posts'; '/api/posts' stays."""
    parts = str(entry or "").strip().split()
    return parts[-1] if parts else ""


def _page_dead_controls(text: str) -> bool:
    interactive = ("<form" in text) or ('type="submit"' in text)
    bound = any(tok in text for tok in _HANDLER_TOKENS)
    return interactive and not bound


def audit_ui_page(frontend_src: Path, page: Mapping[str, Any],
                  *, _src_cache: Optional[Dict[str, str]] = None,
                  ) -> Tuple[bool, List[str]]:
    """One page → (implemented?, missing list). Purely static."""
    missing: List[str] = []
    component = str(page.get("component") or "").strip()
    route = str(page.get("route") or "").strip()
    apis = [a for a in (_norm_api(x) for x in (page.get("apis_used") or []))
            if a]

    if _src_cache is None:
        _src_cache = {}
        for f in list(frontend_src.rglob("*.jsx")) + list(frontend_src.rglob("*.js")):
            try:
                _src_cache[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
    all_src = "\n".join(_src_cache.values())

    comp_file_text = None
    if component:
        # CANONICAL LAYOUT (user decision 2026-06-11): declared structure maps
        # to fixed paths — a page's root component lives in src/pages/, a
        # reusable component in src/components/, name == filename. The audit
        # checks the canonical path FIRST and says exactly where the file is
        # expected; any-location fallback keeps老树兼容 but reports the drift.
        kind_dir = "components" if page.get("_is_component") else "pages"
        canonical = frontend_src / kind_dir / f"{component}.jsx"
        comp_file_text = _src_cache.get(str(canonical))
        if comp_file_text is None:
            for fname, text in _src_cache.items():
                if Path(fname).stem == component:
                    comp_file_text = text
                    missing.append(
                        f"`{component}` exists but NOT at the canonical path "
                        f"src/{kind_dir}/{component}.jsx — move it there")
                    break
        if comp_file_text is None:
            if not re.search(r"(function|const)\s+" + re.escape(component) + r"\b",
                             all_src):
                missing.append(f"component `{component}` not found — expected "
                               f"at src/{kind_dir}/{component}.jsx")
    if route:
        app_jsx = _src_cache.get(str(frontend_src / "App.jsx")) or ""
        if f'path="{route}"' not in app_jsx and f"path='{route}'" not in app_jsx:
            missing.append(f"route `{route}` not wired in App.jsx")
    for api in apis:
        # loose: the path literal (or its parametrized prefix) appears anywhere
        probe = re.sub(r"\{[^}]+\}", "", api).rstrip("/")
        if probe and probe not in all_src:
            missing.append(f"declared API `{api}` never referenced in frontend src")
    if comp_file_text and _page_dead_controls(comp_file_text):
        missing.append(f"component `{component}` renders interactive markup "
                       "with no bound handler (dead controls)")
    # MODEL RULE (user design): pages compose COMPONENTS; page→page is
    # NAVIGATION (a route/link), never composition. A page importing another
    # page means shared UI that belongs in src/components/.
    if comp_file_text and not page.get("_is_component"):
        for _imp in re.findall(r"import\s+(\w+)\s+from\s+['\"][^'\"]*pages/(\w+)['\"]",
                               comp_file_text):
            missing.append(
                f"page imports page `{_imp[1]}` — pages may only compose "
                "components; extract the shared UI into src/components/ and "
                "navigate between pages via routes/links")
    return (not missing), missing


def audit_ui_component(frontend_src: Path, comp: Mapping[str, Any],
                       *, _src_cache: Optional[Dict[str, str]] = None,
                       ) -> Tuple[bool, List[str]]:
    """Component audit (mechanism #52): code presence + ITS apis referenced
    (component file first, whole src as fallback — calls are often delegated
    to a service module) + no dead controls in its own file."""
    page_like = {"component": comp.get("component") or "",
                 "route": "",  # components have no route
                 "_is_component": True,
                 "apis_used": comp.get("apis_used") or []}
    return audit_ui_page(frontend_src, page_like, _src_cache=_src_cache)


def _registered_paths(registryhub: Any) -> Optional[set]:
    """Normalized (METHOD, /path) set from the registry, or None if no hub."""
    if registryhub is None:
        return None
    try:
        eps = registryhub.get_endpoints() or {}
    except Exception:
        return None
    out = set()
    for ep in eps.values() if isinstance(eps, dict) else []:
        m = str(ep.get("method") or "GET").upper()
        p = re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*", "*", str(ep.get("path") or "")).rstrip("/")
        out.add((m, p))
    return out


def _api_registered(api: str, registered: set) -> bool:
    parts = str(api).strip().split()
    m, pth = (parts[0].upper(), parts[1]) if len(parts) == 2 else ("GET", parts[0] if parts else "")
    pth = re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*", "*", pth).rstrip("/")
    return (m, pth) in registered


def sync_ui_page_statuses(project_dir: Any, workhub: Any,
                          registryhub: Any = None) -> Dict[str, Any]:
    """Audit every registered ui_page against the code; flip statuses through
    ``update_ui_page`` (which cascades impl.page.* completion). Best-effort —
    returns {implemented: [...], regressed: [...], pending: {name: missing}}."""
    out: Dict[str, Any] = {"implemented": [], "regressed": [], "pending": {}}
    try:
        frontend_src = Path(project_dir) / "app" / "frontend" / "src"
        if not frontend_src.is_dir():
            return out
        pages = workhub.get_ui_pages() or {}
        components = (workhub.get_ui_components() or {}) if hasattr(workhub, "get_ui_components") else {}
        if not pages and not components:
            return out
        cache: Dict[str, str] = {}
        for f in list(frontend_src.rglob("*.jsx")) + list(frontend_src.rglob("*.js")):
            try:
                cache[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
        registered = _registered_paths(registryhub)
        def _contract_misses(item):
            if registered is None:
                return []
            return [f"declared API `{a}` is NOT in the registered contract"
                    for a in (item.get("apis_used") or [])
                    if str(a).strip() and not _api_registered(a, registered)]
        comp_status: Dict[str, bool] = {}
        for cname, comp in components.items():
            cok, cmissing = audit_ui_component(frontend_src, comp, _src_cache=cache)
            _cm = _contract_misses(comp)
            if _cm:
                cok = False
                cmissing = list(cmissing) + _cm
            comp_status[cname] = cok
            cstat = str(comp.get("status") or "").lower()
            if cok and cstat != "implemented":
                workhub.update_ui_component(cname, {"status": "implemented"},
                                            agent="orchestrator")
                out.setdefault("components_implemented", []).append(cname)
            elif not cok and cstat == "implemented":
                workhub.update_ui_component(cname, {"status": "defined"},
                                            agent="orchestrator")
            elif not cok:
                out.setdefault("components_pending", {})[cname] = cmissing
        for name, page in pages.items():
            status = str(page.get("status") or "").lower()
            ok, missing = audit_ui_page(frontend_src, page, _src_cache=cache)
            _pm = _contract_misses(page)
            if _pm:
                ok = False
                missing = list(missing) + _pm
            # rollup: every component the page references must be implemented
            for ref in (page.get("components") or []):
                ref = str(ref)
                if ref in comp_status and not comp_status[ref]:
                    ok = False
                    missing = list(missing) + [
                        f"referenced component `{ref}` not implemented yet"]
            if ok and status != "implemented":
                workhub.update_ui_page(name, {"status": "implemented"},
                                       agent="orchestrator")
                out["implemented"].append(name)
            elif not ok and status == "implemented":
                workhub.update_ui_page(name, {"status": "defined"},
                                       agent="orchestrator")
                out["regressed"].append(name)
            elif not ok:
                out["pending"][name] = missing
    except Exception:
        pass
    return out


# Which audit misses are HARD — deterministic, low-false-positive, and render
# the declared page UNUSABLE (route absent → page won't open; component file
# absent → render crashes). These gate delivery EVEN on a functionally-
# validated app, because the framework api_smoke probes the BACKEND only — it
# never opens a frontend page (round 44: /login declared, only `/` wired,
# api_smoke green, blank screen shipped). apis_used loose-match and dead-
# controls are SOFTER (the call site may build the URL; a handler may be wired
# indirectly) → NOT promoted to hard blockers here.
_HARD_MISS_MARKERS = ("not wired in App.jsx", "not found — expected")


def _is_hard_miss(missing_line: str) -> bool:
    return any(mark in missing_line for mark in _HARD_MISS_MARKERS)


def ui_page_delivery_blockers(frontend_src: Any, workhub: Any) -> List[str]:
    """Declared ui_pages with a HARD wiring defect → delivery blocker strings.

    Purely static, recomputed from code truth — a page wired correctly clears
    it, so this is never a permanent block (lane fixes the route/component and
    the next gate tick passes). Returns ``[]`` on any fault (best-effort: the
    gate must never crash on a frontend-audit hiccup)."""
    blockers: List[str] = []
    try:
        src = Path(frontend_src)
        if not src.is_dir():
            return blockers
        pages = workhub.get_ui_pages() or {}
        if not pages:
            return blockers
        cache: Dict[str, str] = {}
        for f in list(src.rglob("*.jsx")) + list(src.rglob("*.js")):
            try:
                cache[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
        for name, page in pages.items():
            _ok, missing = audit_ui_page(src, page, _src_cache=cache)
            hard = [m for m in missing if _is_hard_miss(m)]
            if hard:
                blockers.append(
                    f"ui_page `{name}` declared but unusable: " + "; ".join(hard))
    except Exception:
        pass
    return blockers
