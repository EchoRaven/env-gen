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

# Single source of truth for "the same route" — shared with the BACKEND route
# audit (backend_audit.py uses the same two helpers via _norm_route). The
# frontend route-wiring check MUST normalize the same way the backend does, or a
# declared `/channel/:handle` reads as "unwired" against a wired
# `/channel/:channelId` (PROPOSAL #18: the frontend route check was the last
# brittle byte-equality match in an otherwise param-tolerant pipeline).
from .route_projector import _express_to_fastapi, _norm_path

# Tokens that prove a page does real work (a handler or an API call), used by both the
# dead-controls check and the "declared apis but built nothing" stub check.
# PROPOSAL #55: the framework's OWN baseline api client (`_BASELINE_API_JS`, #41) is a
# DEFAULT export used as `import api from '../services/api'` → `api.get(...)` /
# `api.post(...)` / `api.<verb>(...)`, and the prompts tell pages to use exactly that.
# The old token set only recognized the NAMED helpers (apiGet/apiPost) + raw fetch/axios,
# so a real read-only detail page calling `api.get('/api/notes/{id}')` (no <form>, no
# onClick) was FALSELY flagged "placeholder stub — renders no real UI" → a permanent,
# unsatisfiable ui_page_unwired block (smoke-notes 2026-06-19: a 76-line NoteDetailPage
# bounced 5× as a "stub"). Recognize the default-import service style too (`api.` is only
# present when the page imports+uses the api client; a genuine framework stub does not).
_HANDLER_TOKENS = ("onSubmit", "onClick", "fetch(", "apiGet", "apiPost",
                   "apiPut", "apiDelete", "axios", "api.", "await api")

# §2 gate-hardening: a real data page CALLS the api client — it does not merely IMPORT it.
# The old check passed any file containing the string `services/api`, so a page that did
# `import { getTasks } from '../services/api'` but never invoked getTasks() cleared the stub
# gate. Require an actual call EXPRESSION instead.
_API_CALL_RE = re.compile(
    r"\b(?:await\s+)?(?:api|axios)\s*\.\s*(?:get|post|put|patch|delete)\s*\(|"
    r"\bfetch\s*\(|\b(?:apiGet|apiPost|apiPut|apiDelete)\s*\(")


def _names_from_service_import(text: str) -> set:
    """Named identifiers imported from a `services/api` module:
    ``import { getTasks, createTask } from '../services/api'`` → {getTasks, createTask}."""
    out: set = set()
    for m in re.finditer(
            r"import\s*\{([^}]*)\}\s*from\s*['\"][^'\"]*services/api[^'\"]*['\"]", text):
        for tok in m.group(1).split(","):
            tok = tok.split(" as ")[-1].strip()
            if re.match(r"^[A-Za-z_$][\w$]*$", tok):
                out.add(tok)
    return out


def _has_real_api_call(text: str) -> bool:
    """True iff the file CALLS the api client (default `api.get(`/`fetch(`/`apiGet(`, or a
    NAMED helper imported from services/api AND actually invoked) — not merely imports it."""
    if _API_CALL_RE.search(text):
        return True
    for n in _names_from_service_import(text):
        # Accept BOTH a direct call `helper(` AND a method call on an imported
        # SERVICE OBJECT `helper.get(` / `feed.list(`. The api.js service-object
        # pattern (`export const feed = {get: () => api.get('/api/feed')}`;
        # `import {feed} from '../services/api'`; `feed.get()`) is the most common
        # React shape — the direct-call-only check false-flagged every page using
        # it as a "placeholder stub" (run v11: HomeFeedPage called feed.get() /
        # users.getSuggested(), shipped REAL content, yet ui_page_unwired blocked
        # delivery on a non-existent stub). Requires a trailing `(` so a bare
        # property read (`feed.length`) still doesn't count as a call.
        if re.search(r"\b" + re.escape(n) + r"\s*(?:\(|\.\s*\w+\s*\()", text):
            return True
    return False


def _norm_api(entry: str) -> str:
    """'GET /api/posts' → '/api/posts'; '/api/posts' stays."""
    parts = str(entry or "").strip().split()
    return parts[-1] if parts else ""


def _page_dead_controls(text: str) -> bool:
    interactive = ("<form" in text) or ('type="submit"' in text)
    bound = any(tok in text for tok in _HANDLER_TOKENS)
    return interactive and not bound


# Route-guard / layout wrappers that wrap the real PAGE in element={...} — the audit
# resolves a route to its PAGE component, not the auth/layout shell around it.
_ROUTE_WRAPPERS = frozenset({
    "ProtectedRoute", "PrivateRoute", "PublicRoute", "RequireAuth", "RequireAdmin",
    "AuthGuard", "RouteGuard", "Guard", "AuthRoute", "Layout", "AppLayout", "MainLayout",
    "DashboardLayout", "Suspense", "ErrorBoundary", "Fragment", "React",
})


def _tag_span(app_jsx: str, pidx: int) -> str:
    """The full ``<Route ...>`` tag enclosing the ``path=`` at ``pidx`` — bounded by the
    first ``>`` at brace-depth 0, so a ``>`` inside ``element={...}`` (a JS expression, or
    a nested ``<Wrapper><Page/></Wrapper>``) does NOT truncate the tag."""
    start = app_jsx.rfind("<Route", 0, pidx)
    if start == -1:
        start = max(0, pidx - 200)
    depth, i = 0, start
    while i < len(app_jsx):
        ch = app_jsx[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return app_jsx[start:i + 1]
        i += 1
    return app_jsx[start:start + 400]


def _route_element(app_jsx: str, route: str) -> Optional[str]:
    """The PAGE component identifier wired to ``route`` in App.jsx, or None.

    e.g. ``<Route path="/" element={<Home />} />`` for route ``/`` → ``"Home"``, and
    ``element={<ProtectedRoute><InboxPage/></ProtectedRoute>}`` → ``"InboxPage"`` (the
    PAGE, not the guard). The declared ui_page ``component`` is a LOGICAL name; the lane
    may render the route with any actual component file, and the route→element wiring is
    the source of truth for *what renders this page*. Parses the whole ``<Route>`` tag with
    balanced-brace awareness (tolerates attribute order + a ``>`` inside the element
    expression) and skips known route-guard/layout wrappers. Domain-agnostic; matches
    single- or double-quoted paths."""
    if not route:
        return None
    for q in ('"', "'"):
        pat = f"path={q}{route}{q}"
        pidx = app_jsx.find(pat)
        while pidx != -1:
            tag = _tag_span(app_jsx, pidx)
            em = re.search(r"element=\s*\{", tag)
            if em:
                # capture the balanced element={...} expression
                j = tag.find("{", em.start())
                depth, k = 0, j
                while k < len(tag):
                    if tag[k] == "{":
                        depth += 1
                    elif tag[k] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                expr = tag[j:k + 1]
                # opening-tag component names, in source order; the PAGE is the innermost
                # (last) one after dropping known wrappers.
                names = re.findall(r"<\s*([A-Za-z_]\w*)", expr)
                page = [n for n in names if n not in _ROUTE_WRAPPERS] or names
                if page:
                    return page[-1]
            pidx = app_jsx.find(pat, pidx + 1)
    return None


def _canon_route(route: str) -> str:
    """Canonical comparable form of a declared/wired route: Express ``:param`` →
    ``{param}`` (``_express_to_fastapi``) → every param collapsed to ``{}``
    (``_norm_path``), trailing slash trimmed. So ``/channel/:handle`` ==
    ``/channel/:channelId`` == ``/channel/{id}`` — identical to the BACKEND's
    ``_norm_route`` rule, the single source of truth for route identity."""
    c = _norm_path(_express_to_fastapi(str(route or "").strip()))
    return c[:-1] if len(c) > 1 and c.endswith("/") else c


def _wired_route_set(app_jsx: str) -> set:
    """The SET of canonicalised route paths actually wired in App.jsx — parsed
    from every ``path="..."`` / ``path='...'``. A SET, compared by equality (NOT
    a substring scan), so ``/watch`` never spuriously satisfies ``/watchlist``
    and ``/feed`` never satisfies ``/feed/library`` (the old byte-substring check
    risked exactly those false positives)."""
    return {_canon_route(m.group(1))
            for m in re.finditer(r"""path\s*=\s*["']([^"']+)["']""", app_jsx)}


def _route_is_wired(route: str, app_jsx: str) -> bool:
    """Declared ``route`` is wired iff its canonical form is in the wired SET, OR
    — FALLBACK ONLY — it ends in a TRAILING path param that, dropped, matches a
    wired route exactly (a declared ``/watch/:id`` is satisfied by a wired
    ``/watch``: path-param vs query-param/state convention). The fallback drops
    ONLY a trailing ``{}`` segment and requires an EXACT set match of the base,
    so it never over-matches a longer wired route (``/watch/{}/edit``) nor an
    unrelated static route, and never fires for a route whose last segment is
    static (``/feed/library`` stays unwired — correct, it is a genuine
    divergence, not param drift)."""
    canon = _canon_route(route)
    if not canon:
        return True
    wired = _wired_route_set(app_jsx)
    if canon in wired:
        return True
    if canon.endswith("/{}"):
        base = canon[: -len("/{}")] or "/"
        return base in wired
    return False


def _component_resolves(name: str, frontend_src: Path,
                        src_cache: Mapping[str, str], all_src: str) -> bool:
    """True iff a component identifier resolves to real source: an own file
    (``pages/X.jsx`` / ``components/X.jsx`` / any file whose stem is ``X``) OR a
    ``function X`` / ``const X`` definition anywhere. Purely static, layout- and
    domain-agnostic."""
    if not name:
        return False
    for kind_dir in ("pages", "components"):
        if src_cache.get(str(frontend_src / kind_dir / f"{name}.jsx")) is not None:
            return True
    for fname in src_cache:
        if Path(fname).stem == name:
            return True
    return bool(re.search(r"(function|const)\s+" + re.escape(name) + r"\b", all_src))


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

    app_jsx = _src_cache.get(str(frontend_src / "App.jsx")) or ""
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
        # `defined inline somewhere` (component name appears as a function/const
        # definition) counts as resolved but yields NO own file text — keep
        # comp_file_text None so the dead-controls / page-import checks (which
        # must run on the component's OWN file, never the whole src) stay scoped.
        resolved_inline = comp_file_text is None and bool(re.search(
            r"(function|const)\s+" + re.escape(component) + r"\b", all_src))
        if comp_file_text is None and not resolved_inline:
            # ROUTE-ELEMENT RESOLUTION (fix 2026-06-16): the declared ``component``
            # is a LOGICAL page name (e.g. ``HomePage``); the lane is free to render
            # the route with a differently-named real file (``Home.jsx`` →
            # ``element={<Home />}``). The route→element wiring is the source of
            # truth for what renders the page, so resolve THROUGH it before
            # declaring the component missing — otherwise a fully-built, wired,
            # navigable page can never flip defined→implemented (component↔filename
            # mismatch froze run #3's 5 real pages at ``defined`` → the navigable
            # gate reported a blank shell). Domain-agnostic: no app specifics.
            elem = _route_element(app_jsx, route) if not page.get("_is_component") else None
            if elem and _component_resolves(elem, frontend_src, _src_cache, all_src):
                # bind comp_file_text to the element's OWN file when it has one
                # (so dead-controls / page-import still check real source); an
                # inline-defined element resolves without file text, same as above.
                for cand in (frontend_src / "pages" / f"{elem}.jsx",
                             frontend_src / "components" / f"{elem}.jsx"):
                    if _src_cache.get(str(cand)) is not None:
                        comp_file_text = _src_cache[str(cand)]
                        break
                if comp_file_text is None:
                    for fname, text in _src_cache.items():
                        if Path(fname).stem == elem:
                            comp_file_text = text
                            break
            else:
                missing.append(f"component `{component}` not found — expected "
                               f"at src/{kind_dir}/{component}.jsx")
    if route:
        # PROPOSAL #18: normalized SET match (param-name-agnostic, trailing-param
        # fallback) instead of byte-substring — the frontend twin of the backend's
        # _norm_route. Clears cosmetic route drift (`/watch/:id`≡`/watch`,
        # `/channel/:handle`≡`/channel/:channelId`) while still hard-flagging a
        # genuinely-absent route (`/feed/library` with no matching wired path).
        if not _route_is_wired(route, app_jsx):
            missing.append(f"route `{route}` not wired in App.jsx")
    for api in apis:
        # Match the declared path against the source allowing each {param}/:param to be
        # ANY single path segment. The lane writes the call as `/api/posts/${postId}/like`
        # or `/api/posts/`+id+`/like`, so a MID-PATH param must be a wildcard, not removed.
        # The old "strip the param" probe produced a DOUBLE slash (`/api/posts//like`) that
        # never matched a real mid-path-param call — run v12: PostCard/ReelPlayer DID call
        # like/save via `/api/posts/${postId}/like` but were flagged "never referenced",
        # so their component artifacts stayed `defined`, their impl tasks never
        # auto-completed, and the pages depending on them stayed blocked → the lane
        # abandoned 5 components it had actually built. Build a regex: literal segments
        # escaped, each param → one path-segment wildcard.
        segs = re.split(r"\{[^}]+\}|:[A-Za-z_]\w*", api)
        if not any(s.strip("/") for s in segs):
            continue
        pat = r"[^/'\"`\s)]*".join(re.escape(s) for s in segs).rstrip("/")
        if pat and not re.search(pat, all_src):
            missing.append(f"declared API `{api}` never referenced in frontend src")
    if comp_file_text and _page_dead_controls(comp_file_text):
        missing.append(f"component `{component}` renders interactive markup "
                       "with no bound handler (dead controls)")
    # PROPOSAL #39 (G2): catch PLACEHOLDER/STUB pages that _page_dead_controls misses.
    # A pure placeholder ("This section is being set up", no form/button) has
    # interactive=False so dead_controls doesn't fire — yet it ships a blank/empty page.
    # Run #36: ALL declared pages were the framework's _stub_page_component
    # ("This section is being set up") and the lane never filled them. Flag a page that
    # (a) still carries a known placeholder phrase, OR (b) declared apis_used but its file
    # references NO api call / handler / form at all (declared behavior, built nothing).
    # Gated tightly to avoid flagging a legitimately-static page (empty apis_used + real copy).
    if comp_file_text:
        _low = comp_file_text.lower()
        _placeholder = any(p in _low for p in (
            "this section is being set up", "under construction",
            "coming soon", "placeholder page", "todo: implement"))
        # PROPOSAL #55-v2 + §2 gate-hardening: a declared-data page is INERT unless it
        # actually CALLS the api client. #55 recognized the named-helper style
        # (`import { getTasks } from '../services/api'` → `getTasks()`), but the old test
        # only checked for the IMPORT substring `services/api`, so a page that imported a
        # helper yet never invoked it cleared the stub gate. Now require a real call
        # expression (default `api.get(`/`fetch(`/`apiGet(`, or a named services/api helper
        # that is invoked) — a genuine stub imports nothing and calls nothing.
        _has_call = _has_real_api_call(comp_file_text)
        # FIX #126 (run-44 M1 STUCK, live): a page that COMPOSES real child
        # components delegates its fetching + handlers to them — the user's own
        # model ("pages compose COMPONENTS"). HomeFeedPage rendered 5 real children
        # (SideNavigation/MainFeed/RightSidebar/…) that carry the behavior, yet the
        # page file itself had no api call / handler token → falsely flagged an inert
        # stub → deliverability_ui_page_unwired wedged M1 7 cycles on a working app.
        # Mirror the existing service-module delegation tolerance: credit a page that
        # imports >=1 component from a components/ path AND renders a custom JSX child.
        _composes_child = bool(re.search(
            r"import\s+\w+\s+from\s+['\"][^'\"]*components/\w+['\"]",
            comp_file_text)) and bool(re.search(r"<[A-Z]\w+[\s/>]", comp_file_text))
        _declared_but_inert = (bool(apis) and not _has_call and not _composes_child
                               and not any(tok in comp_file_text for tok in _HANDLER_TOKENS))
        if _placeholder or _declared_but_inert:
            missing.append(
                f"component `{component}` is a placeholder stub — it renders no real "
                "UI/behavior; build the page's declared content and wire its apis_used")
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
_HARD_MISS_MARKERS = ("not wired in App.jsx", "not found — expected",
                      "is a placeholder stub")  # #39 G2: a stub page = a shipped-blank page


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
            # PROPOSAL #47 (v2): a thin/placeholder ui_page with no real '/'-route is a
            # design-phase stub (registration is intentionally permissive), not a
            # deliverable page — it has no App.jsx route to wire, so skip it here instead
            # of letting a route-less garbage entry permanently inflate ui_page_unwired
            # (smoke-notes 2026-06-19: a 'login_page' entry with route='' did exactly that).
            # A genuinely-declared page always carries a '/'-anchored route.
            if not isinstance(page, dict) or not str(page.get("route") or "").strip().startswith("/"):
                continue
            _ok, missing = audit_ui_page(src, page, _src_cache=cache)
            hard = [m for m in missing if _is_hard_miss(m)]
            if hard:
                blockers.append(
                    f"ui_page `{name}` declared but unusable: " + "; ".join(hard))
    except Exception:
        pass
    return blockers


def audit_asset_usage(frontend_dir: Any, design_system: Mapping[str, Any]) -> Dict[str, Any]:
    """ADVISORY (never a hard block): flag each component the Design-Prep design_system maps to a
    REAL asset that no frontend file actually references. For every ``screens[].components[].assets``
    id, resolve its manifest ``file`` and check whether ANY frontend ``src`` file mentions that
    file's basename (e.g. ``ig.svg``); if none do, the lane drew an approximation instead of using
    the real asset → report ``{component, asset, file}``. Best-effort; ``{"unused_mapped": []}`` on
    any error or missing design_system."""
    out: Dict[str, Any] = {"unused_mapped": []}
    try:
        ds = design_system or {}
        assets_by_id = {a.get("id"): a for a in (ds.get("assets") or []) if isinstance(a, dict)}
        if not assets_by_id:
            return out
        src = Path(frontend_dir) / "src"
        if not src.is_dir():
            return out
        # concatenate all frontend source once (small; deterministic)
        blob_parts: List[str] = []
        for p in src.rglob("*"):
            if p.is_file() and p.suffix.lower() in (
                    ".jsx", ".tsx", ".js", ".ts", ".css", ".scss", ".html"):
                try:
                    blob_parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
        blob = "\n".join(blob_parts)
        seen = set()
        for screen in (ds.get("screens") or []):
            for comp in (screen.get("components") or []):
                if not isinstance(comp, dict):
                    continue
                cid = comp.get("id")
                for aid in (comp.get("assets") or []):
                    a = assets_by_id.get(aid)
                    if not a:
                        continue
                    fname = a.get("file") or ""
                    base = Path(fname).name
                    if not base:
                        continue
                    key = (cid, aid)
                    if key in seen:
                        continue
                    if base not in blob:
                        seen.add(key)
                        out["unused_mapped"].append(
                            {"component": cid, "asset": aid, "file": fname})
    except Exception:
        return {"unused_mapped": []}
    return out
