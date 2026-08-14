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


def _is_generic_fallback_page(text: str) -> bool:
    """#222 — content-based detection of the GENERIC framework fallback page.

    r18 (log-verified) defeated marker-based detection: the lane stripped the
    _PAGE_MARKER comment and the data-fallback attribute and tweaked API-call
    formats until the audit credited the untouched generic shell as
    'implemented'. Detect the CONTENT instead: the projection's helper
    constellation (const _imgOf/_titleOf/_subOf/_metaOf — no lane authors
    these) plus the generic list shell survives every cosmetic edit. A #221
    reference-structured projection (data-projected/structured marker, or the
    measured inline canvas paint) is a genuine floor — never flagged here."""
    if not text:
        return False
    try:
        from .frontend_page_projector import _PAGE_MARKER, _STRUCTURED_MARKER
    except Exception:  # pragma: no cover — projector module always present
        _PAGE_MARKER = "frontend_page_projector"
        _STRUCTURED_MARKER = "reference-structured"
    if 'data-projected="ref"' in text or _STRUCTURED_MARKER in text:
        return False
    if 'data-fallback="1"' in text or _PAGE_MARKER in text:
        return True
    helpers = sum(1 for h in ("const _imgOf", "const _titleOf",
                              "const _subOf", "const _metaOf") if h in text)
    shell = ("No data yet" in text) or ("divide-y" in text and "<aside" not in text)
    # a marker-stripped STRUCTURED page still paints the measured canvas inline
    return helpers >= 3 and shell and "style={{ backgroundColor:" not in text


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
            # FIX #146 (run-69 M3 STUCK, live): declared-route vs implemented-
            # route DRIFT — ui_page `messages_page` declared `/messages` but the
            # lane wired MessagesPage at `/direct` (a legitimate choice; real
            # Instagram uses /direct). The page was built and reachable, yet the
            # stale registry string blocked delivery for 7 no-change cycles.
            # When the declared COMPONENT is demonstrably rendered by some OTHER
            # wired route, accept wired-with-drift — the app is the authority on
            # where its screens live. A component rendered nowhere still flags.
            _elem_re = re.compile(
                r"element=\{\s*<" + re.escape(component or "") + r"[\s/>]")
            if not (component and _elem_re.search(app_jsx)):
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
        # #566j: allow an optional FILE EXTENSION on the import path — `import X from
        # '../components/X.jsx'` (or .tsx/.js) is the common style, and the old
        # `components/\w+['"]` (word immediately followed by a quote) MISSED it, so a page
        # that mounts `<X/>` from a .jsx import was falsely inert → ui_page_unwired wedge
        # to the 75-min no-deliver abort (netflix r117/r120: TitleDetailPage mounting a
        # TitleDetailModal.jsx). Extension-agnostic now.
        _composes_child = bool(re.search(
            r"import\s+\w+\s+from\s+['\"][^'\"]*components/\w+(?:\.\w+)?['\"]",
            comp_file_text)) and bool(re.search(r"<[A-Z]\w+[\s/>]", comp_file_text))
        _declared_but_inert = (bool(apis) and not _has_call and not _composes_child
                               and not any(tok in comp_file_text for tok in _HANDLER_TOKENS))
        if _placeholder or _declared_but_inert:
            missing.append(
                f"component `{component}` is a placeholder stub — it renders no real "
                "UI/behavior; build the page's declared content and wire its apis_used")
        # #222: the GENERIC framework fallback is never 'implemented' — detected
        # by CONTENT (helper constellation + list shell), so stripping the
        # marker/attr or reformatting API calls (the r18 gaming moves) cannot
        # flip the verdict. A #221 reference-structured projection passes.
        if _is_generic_fallback_page(comp_file_text):
            missing.append(
                f"component `{component}` is a framework fallback page (generic list) — "
                "author the REAL page for this route (reference layout, real fields, "
                "real controls). Cosmetic edits (removing framework comments/attributes "
                "or reformatting API calls) do not count as implementation")
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

    # FIX #151 (googlemaps run-3, live): the lane can build a real API-calling page
    # (SearchPage: useEffect + api.searchPlaces) AND wire App.jsx's route to a DIFFERENT,
    # hardcoded-mock twin (SearchResults), leaving the real one an orphan. The checks above
    # inspect the DECLARED component, so a route that RENDERS a static mock ships mock data
    # while every gate passes. Verify what the route ACTUALLY renders: if the page declares
    # data (non-empty apis_used) and App.jsx wires the route to a component that is NOT the
    # declared one, HAS its own file, and itself makes no api call nor composes an
    # api-calling child → the user sees a static mock. Empty-apis pages (legit static) and
    # API-calling wired elements never flag. Domain-agnostic; no app specifics.
    if route and apis and not page.get("_is_component"):
        _elem = _route_element(app_jsx, route)
        if _elem and _elem != component:
            _wired_text = None
            for _cand in (frontend_src / "pages" / f"{_elem}.jsx",
                          frontend_src / "components" / f"{_elem}.jsx"):
                if _src_cache.get(str(_cand)) is not None:
                    _wired_text = _src_cache[str(_cand)]
                    break
            if _wired_text is None:
                for _fn, _tx in _src_cache.items():
                    if Path(_fn).stem == _elem:
                        _wired_text = _tx
                        break
            if _wired_text is not None:
                _wired_composes = bool(re.search(
                    r"import\s+\w+\s+from\s+['\"][^'\"]*components/\w+['\"]",
                    _wired_text)) and bool(re.search(r"<[A-Z]\w+[\s/>]", _wired_text))
                if not _has_real_api_call(_wired_text) and not _wired_composes:
                    missing.append(
                        f"route {route} is wired to `{_elem}` which is a STATIC MOCK "
                        f"(no api call) while the page declares apis_used — the real data "
                        f"never renders. Wire the route to the component that calls the API "
                        f"(likely the `{component}`/`...Page` twin) or make `{_elem}` fetch "
                        "its data via src/services/api.js.")
    return (not missing), missing


def _route_matchers(app_jsx: str) -> List:
    """#238: compile each App.jsx route into a regex that a LITERAL nav target
    must fully match. A wired ``/@:username`` (canon ``/@{}``) → ``/@[^/]+`` so
    ``/@alice`` matches but ``/profile`` does not; a static ``/explore`` → exact.
    The catch-all (``*`` / ``/*``) is EXCLUDED — it is the 404 sink, so a link
    that only matches it is precisely a dead link."""
    matchers = []
    for m in re.finditer(r"""path\s*=\s*["']([^"']+)["']""", app_jsx):
        raw = m.group(1).strip()
        if raw in ("*", "/*"):
            continue
        canon = _canon_route(raw)
        if not canon:
            continue
        # canon has params collapsed to literal "{}" segments-or-fragments.
        pat = "^" + re.escape(canon).replace(r"\{\}", r"[^/]+") + "$"
        try:
            matchers.append(re.compile(pat))
        except re.error:
            continue
    return matchers


def _norm_nav_target(target: str) -> str:
    return (str(target or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")) or "/"


def reference_screen_routes(output_dir: Any) -> set:
    """Routes of the measured REFERENCE screens that are real pages (#354).

    #352 assigns every measured screen a route and a kind, so the framework can
    finally tell "a nav item the lane invented" from "a page the reference
    actually shows". Overlays are excluded: they are not URL-addressable, so
    they are not pages to author. Missing/unreadable design system -> empty set,
    which preserves the pre-#354 behaviour exactly.
    """
    try:
        import json as _json
        p = Path(output_dir) / "design" / "design_system.json"
        if not p.exists():
            return set()
        ds = _json.loads(p.read_text(encoding="utf-8")) or {}
        out = set()
        for s in (ds.get("screens") or []):
            if not isinstance(s, dict):
                continue
            if str(s.get("kind") or "").strip().lower() == "overlay":
                continue
            route = str(s.get("route") or "").strip()
            if route.startswith("/"):
                out.add(_norm_nav_target(route))
        return out
    except Exception:
        return set()


def dead_nav_link_remediation(target: str, jsx_name: str, declared_pages: set, reference_routes: Optional[set] = None) -> str:
    """#278 — a DECISIVE one-line fix for a dead nav link, ordered by cost.

    r61 stalled 81 min on /shop + /upload nav links the sidebar drew from the TikTok
    reference but that the contract never declared. The old message ("wire the route OR
    point the link at an existing one") gave two equal options and the lane oscillated
    between authoring a whole new page (expensive: new contract page + endpoints + data) and
    removing the link. When the target is NOT a declared ui_page, authoring a page is the
    wrong first move — it drags in unscoped surface — so name that and put the cheap fix
    first: remove or repoint. When the target IS a declared page, the fix really is to wire
    its missing route.
    """
    # #690: THE ROUTE EXISTS — THE LINK LOST ITS PARAMETER. Checked FIRST because it is now
    # the dominant case and the other three branches all mis-diagnose it.
    #
    # `dead_nav_link` FIRES more in the live era than ever: 212 occurrences in r100+ against 37
    # before. It is not what runs finally die on — era-controlling the terminal `Failed checks:`
    # line shows 13 of those 14 aborted runs are r<100, and the single r100+ one died on
    # business_chain_failing. (An earlier draft of this note claimed 5 of 14 aborted runs blocked
    # here; those 5 are all pre-r100 and the claim is withdrawn.) What it costs is rounds, not
    # the run: each occurrence is a remediation cycle spent on a mis-stated cause. What the gate
    # actually flags:
    #
    #     components/HeroBillboard.jsx:  /watch/        -> /profiles   x34
    #     components/HoverPreview.jsx:   /watch/        -> /profiles   x20
    #     components/GenresDropdown.jsx: /browse/genre/ -> /profiles   x16
    #
    # Every one is a parameterised prefix with NOTHING after it — the template built
    # `/watch/${id}` with an empty id. `/watch/:titleId` is declared and wired; the route is
    # fine. But the three branches below would send the lane to wire a route that exists, author
    # a page that exists, or repoint a link that already points at the right page — none of
    # which is the fix, and all of which cost a round.
    #
    # Detected from data already in hand: the target ends in "/" and a declared route begins
    # with it followed by a `:param` segment.
    _raw = str(target or "").split("?", 1)[0].split("#", 1)[0]
    if _raw.endswith("/") and len(_raw) > 1:
        _param_routes = sorted(
            d for d in (declared_pages or set())
            if d.startswith(_raw) and ":" in d[len(_raw):].split("/", 1)[0])
        if _param_routes:
            return (f"nav link `{target}` ({jsx_name}) is a parameterised route with an EMPTY "
                    f"parameter — the route `{_param_routes[0]}` IS declared and wired, so do "
                    f"NOT add a route or repoint the link. The template interpolated an empty "
                    f"id (e.g. `/watch/${{title.id}}` where `title.id` is undefined). Fix the "
                    f"VALUE: check the field name the API actually returns, and do not render "
                    f"the link at all while the id is missing.")
    t = _norm_nav_target(target)
    if t in (declared_pages or set()):
        return (f"nav link `{target}` ({jsx_name}) points at declared page `{t}` but App.jsx "
                f"has NO matching <Route> → dead control (404). Wire the missing route.")
    # #354 (FE-F5): the sidebar is drawn FROM the reference, so a link to a screen
    # the reference SHOWS is not an "extra nav item" — it is a page the contract
    # has not scoped yet. Telling the lane to delete it is how r93 shipped three
    # routes against an 11-screen reference and r92 shipped 11 StubPages.
    if t in (reference_routes or set()):
        return (f"nav link `{target}` ({jsx_name}) resolves to no route → dead control "
                f"(404), but `{t}` IS a screen in the REFERENCE design. Do NOT remove this "
                f"nav item — the reference shows this page exists. AUTHOR the page: declare "
                f"the ui_page, add its <Route> in App.jsx, and build it from its reference "
                f"screenshot.")
    return (f"nav link `{target}` ({jsx_name}) is NOT a declared ui_page (not in the "
            f"contract) and resolves to no route → dead control (404). CHEAPEST FIX FIRST: "
            f"remove this extra nav item, or repoint it at an existing route; author a new "
            f"page ONLY if this screen is genuinely in scope.")


def dead_nav_link_blockers(frontend_src: Any, limit: int = 20,
                           reference_routes: Optional[set] = None) -> List[str]:
    """#238 (tiktok r27 M1, runtime-verified): the delivered app's own Profile
    nav (SidebarNavigation/TopRightActions ``<Link to="/profile">``) resolved to
    NO route — App.jsx wired only ``/@:username`` — so clicking Profile hit the
    ``*`` 404. A dead nav control is a plain functional break ("功能完备" gap) the
    existing gates miss: ui_page_delivery checks DECLARED routes are wired, never
    that the app's own LINKS resolve. Code-truth, conservative (LITERAL absolute
    targets only; template literals / external / mailto / hash-only skipped;
    catch-all excluded), self-clearing once the lane fixes the link or adds the
    route. ``ENVGEN_DEAD_NAV_GATE=0`` disables (false-block escape hatch, opt-5
    lesson). Best-effort → []."""
    blockers: List[str] = []
    try:
        src = Path(frontend_src)
        app_jsx = src / "App.jsx"
        if not app_jsx.is_file():
            return blockers
        _app_src = app_jsx.read_text(encoding="utf-8", errors="ignore")
        matchers = _route_matchers(_app_src)
        if not matchers:
            return blockers
        # #278: the LITERAL route paths App.jsx declares — used to tell the lane whether a
        # dead link points at a page that merely needs its route wired (declared) or at an
        # extra nav item the contract never scoped (remove/repoint, the cheap fix).
        _declared = set(re.findall(r'path\s*=\s*["\'](/[^"\']*)["\']', _app_src))

        def _resolves(target: str) -> bool:
            t = target.split("?", 1)[0].split("#", 1)[0]
            t = t[:-1] if len(t) > 1 and t.endswith("/") else t
            return any(rx.match(t) for rx in matchers)

        # to="/path" | to='/path' | navigate("/path") | navigate('/path')
        pat = re.compile(
            r"""(?:\bto\s*=\s*|\bnavigate\s*\(\s*)["'](/[^"'{}$]*)["']""")
        seen: set = set()
        for jsx in sorted(src.rglob("*.jsx")):
            if jsx.name == "App.jsx":
                continue
            try:
                text = jsx.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in pat.finditer(text):
                target = m.group(1).strip()
                # skip protocol-relative, root, and non-absolute-ish noise
                if not target.startswith("/") or target.startswith("//"):
                    continue
                key = target.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
                if key in seen or _resolves(target):
                    continue
                seen.add(key)
                blockers.append(
                    dead_nav_link_remediation(target, jsx.name, _declared,
                                              reference_routes=reference_routes))
                if len(blockers) >= limit:
                    return blockers
    except Exception:
        return []
    return blockers


def routed_fallback_page_blockers(frontend_src: Any) -> List[str]:
    """#223 — code-truth sweep for framework fallback pages the registry can't
    see. ui_page_delivery_blockers iterates REGISTERED ui_pages, but the heal
    projector also fills dangling route-wired imports the lane never registered
    (r19: components mis-registered as pages, 300-byte stubs in src/pages/).
    Scan every component route-wired in App.jsx; a generic-fallback body
    (content fingerprint, marker-strip-proof — #222) blocks delivery. Purely
    static, self-clearing once the page is authored. Best-effort → []."""
    blockers: List[str] = []
    try:
        src = Path(frontend_src)
        app_jsx = src / "App.jsx"
        if not app_jsx.is_file():
            return blockers
        app_text = app_jsx.read_text(encoding="utf-8", errors="ignore")
        wired = re.findall(
            r'path\s*=\s*["\']([^"\']+)["\'][^>]*?element\s*=\s*\{\s*<\s*(\w+)', app_text)
        seen: set = set()
        for route, comp in wired:
            if comp in seen or comp in _ROUTE_WRAPPERS:
                continue
            seen.add(comp)
            text = None
            for sub in ("pages", "components", "views", "screens"):
                cand = src / sub / f"{comp}.jsx"
                if cand.is_file():
                    try:
                        text = cand.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        text = None
                    break
            if text and _is_generic_fallback_page(text):
                blockers.append(
                    f"route {route} renders a framework fallback page (`{comp}`) — "
                    "author the REAL page (reference layout, real fields, real "
                    "controls); cosmetic edits do not count")
    except Exception:
        return []
    return blockers


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
        if not isinstance(ep, dict):
            continue
        # #231 (r21): a DEPRECATED endpoint is not part of the live contract —
        # counting it here made the contract-miss check blind while the served
        # backend 404'd the path the frontend was still calling.
        if str(ep.get("status") or "").lower() == "deprecated":
            continue
        m = str(ep.get("method") or "GET").upper()
        p = re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*", "*", str(ep.get("path") or "")).rstrip("/")
        out.add((m, p))
    return out


def _api_registered(api: str, registered: set) -> bool:
    parts = str(api).strip().split()
    m, pth = (parts[0].upper(), parts[1]) if len(parts) == 2 else ("GET", parts[0] if parts else "")
    pth = re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*", "*", pth).rstrip("/")
    return (m, pth) in registered


# #631 — THE SOURCE IS THE LAST DECLARATION OF WHO CONSUMES WHAT.
# #627/#629 registered consumers from what pages and components DECLARE (`apis_used`), taking
# breaking-change delivery from 2.9% to 60.0%. The rest are endpoints nothing declares — and they
# are not unused: of the still-unrouted breaking changes in runs whose frontend survives on disk,
# **163 of 176 (93%)** name a path that IS present in the delivered `app/frontend/src`. They are
# called from the shared api client and from files whose record never listed them.
#
# This audit already walks that source and already holds the registryhub, so the last step costs
# no new machinery: for every REGISTERED endpoint (never a guessed one), if its literal path
# occurs at a URL boundary in the source, the frontend lane is a consumer of it.
#
# The boundary is free precision: bare-substring matching and boundary matching both recover
# 159 of the 176, so the stricter rule is taken — `/api/titles` must be followed by a quote,
# backtick, `?`, `${`, `+`, whitespace, `)` or a digit, not merely by more path (which is how
# `/api/titles` would otherwise claim every hit of `/api/titles/trending`).
_API_URL_BOUNDARY_631 = re.compile(r"""["'`?\s)]|\$\{|\+|\d""")
_MIN_LITERAL_631 = 6   # shorter than "/api/x" is not a path worth matching


def register_source_api_consumers_631(src_cache: Mapping[str, str], registryhub: Any,
                                      project_dir: Any = None) -> int:
    """Register the frontend lane as a consumer of every registered endpoint its source calls.

    Returns the number of consumer rows written. Best-effort: never raises into the audit, and
    the consumer key is ``endpoint:file:agent`` so repeated audits overwrite instead of pile up.
    """
    if registryhub is None or not src_cache:
        return 0
    written = 0
    try:
        endpoints = registryhub.get_endpoints() or {}
    except Exception:
        return 0
    root = Path(project_dir) if project_dir else None
    for endpoint_id, ep in endpoints.items():
        if not isinstance(endpoint_id, str) or " " not in endpoint_id:
            continue
        if str((ep or {}).get("status") or "").lower() == "deprecated":
            continue
        literal = endpoint_id.split(" ", 1)[1].split("{", 1)[0]
        if len(literal) < _MIN_LITERAL_631:
            continue
        hit = None
        for path, text in src_cache.items():
            idx = text.find(literal)
            while idx != -1:
                nxt = text[idx + len(literal):idx + len(literal) + 2] or " "
                if _API_URL_BOUNDARY_631.match(nxt):
                    hit = path
                    break
                idx = text.find(literal, idx + 1)
            if hit:
                break
        if not hit:
            continue
        try:
            rel = str(Path(hit).relative_to(root)) if root else hit
        except Exception:
            rel = hit
        try:
            registryhub.register_consumer(
                endpoint_id=endpoint_id, file_path=rel, agent="frontend",
                metadata={"auto_registered_by": "frontend_audit#631"})
            written += 1
        except Exception:
            continue
    return written


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
        # #631: the source cache is built; use it to close the last declaration gap.
        try:
            out["source_consumers"] = register_source_api_consumers_631(
                cache, registryhub, project_dir)
        except Exception:
            pass
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
                      "is a placeholder stub",  # #39 G2: a stub page = a shipped-blank page
                      "STATIC MOCK",  # #151: a route wired to a mock twin ships mock data
                      "framework fallback page")  # #222: generic fallback never ships


def _is_hard_miss(missing_line: str) -> bool:
    return any(mark in missing_line for mark in _HARD_MISS_MARKERS)


# FIX #166 (gmrun7): a declared MAP page must render a REAL map library, not a fake <div>.
# gmrun7's home_map "map" was a blank `<div className="bg-[#ffffff]">` — leaflet was never
# imported (not in package.json, nowhere in src), so the app's dominant visual element was a
# decorative background. The prompt's <map_surface_template> was IGNORED; a GATE enforces it.
# Egress-robust: a STATIC source check (a tile probe would false-fail offline where OSM tiles
# can't load). Domain-agnostic — no gmaps specifics.
_MAP_LIB_MARKERS = (
    "react-leaflet", "MapContainer", "TileLayer", "from 'leaflet'", 'from "leaflet"',
    "mapbox-gl", "maplibre-gl", "google.maps", "L.map(", "leaflet/dist/leaflet")


def _map_tokens(s: Any) -> set:
    """Word tokens of a name/route, splitting snake/kebab/slash AND camelCase, so ``map`` is a
    WORD (``home_map``/``/map``/``HomeMap`` → has ``map``) but a substring is not
    (``sitemap``/``roadmap`` → does NOT)."""
    txt = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(s or ""))
    return {t for t in re.split(r"[^A-Za-z0-9]+", txt.lower()) if t}


def _is_map_page(name: str, page: Mapping[str, Any]) -> bool:
    """True iff this ui_page is a geographic MAP surface — ``map`` is a word in its name or
    route, or its ``must_have`` names a map. Substring-only matches (sitemap/roadmap) do NOT
    qualify."""
    if not isinstance(page, Mapping):
        return False
    toks = _map_tokens(name) | _map_tokens(page.get("route")) | _map_tokens(page.get("name"))
    if "map" in toks:
        return True
    mh = " ".join(str(x) for x in (page.get("must_have") or []))
    return "map" in _map_tokens(mh)


def _frontend_uses_map_lib(frontend_src: Any) -> bool:
    """True iff ANY frontend source file references a real map library (react-leaflet /
    leaflet / mapbox / maplibre / google.maps). Best-effort; False on any fault."""
    try:
        src = Path(frontend_src)
        if not src.is_dir():
            return False
        for f in (list(src.rglob("*.jsx")) + list(src.rglob("*.js"))
                  + list(src.rglob("*.tsx")) + list(src.rglob("*.ts"))):
            if "node_modules" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if any(m in text for m in _MAP_LIB_MARKERS):
                return True
    except Exception:
        return False
    return False


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
        # FIX #166: if ANY declared page is a MAP surface but the frontend uses NO map
        # library anywhere, the map is a fake background — block delivery on every map page
        # (one static scan, not per-page). "declared but unusable" prefix so it routes to the
        # frontend lane like the other ui_page blockers.
        _map_pages = [n for n, p in pages.items()
                      if isinstance(p, dict)
                      and str(p.get("route") or "").strip().startswith("/")
                      and _is_map_page(n, p)]
        if _map_pages and not _frontend_uses_map_lib(src):
            for _mn in _map_pages:
                blockers.append(
                    f"ui_page `{_mn}` declared but unusable: it is a MAP surface but the "
                    f"frontend uses NO map library (a fake <div> background, not a map) — "
                    f"build the REAL Leaflet map (react-leaflet MapContainer + OSM TileLayer "
                    f"with an explicit height, markers from the places data, per the "
                    f"map_surface_template). A CSS box pretending to be a map is rejected.")
    except Exception:
        pass
    return blockers


# FIX #154 (§6-1, gmrun4 root cause): a component (or the lane's OWN services/api.js —
# gmrun4 overwrote the baseline with a token-less version) calls an authed /api/ endpoint
# with a bare ``fetch()`` that never attaches the Authorization token → every request 401s
# at runtime → empty pages / login wall. api_smoke can never see this (it probes endpoints
# with a FRAMEWORK-minted token) and #151's ``_has_real_api_call`` counts any ``fetch(`` as
# a real call without checking auth. Flag it STATICALLY, with file:line precision — gmrun4's
# lane missed 7 repair attempts because the diagnosis said "blank page", not "this call
# site lacks the token".
#
# Precision-first (HANDOFF §6-1 danger list): only a LITERAL '/api/'-rooted URL counts
# (a variable URL — the baseline api.js ``fetch(path, …)`` wrapper — is invisible to us and
# skipped); the framework control plane ``/api/v1/*`` (TenantPicker's pre-auth tenants
# call) and auth/login/register/health-style public endpoints are allowlisted; ANY auth
# evidence in the call's remaining arguments (Authorization/bearer/token/authHeaders()/
# credential/jwt) clears it; an opaque options identifier (``fetch(url, opts)``) is
# trusted. A missed bare fetch is acceptable (the #152/#153 runtime gates back this up);
# a false block must be near-impossible — and even then the remediation ("route through
# the authed api client") is trivially satisfiable, so the gate is always self-clearing.
_PUBLIC_FETCH_PATH_MARKERS = (
    "/api/v1/",  # framework control plane (tenants/reset/admin) — public infra by design
    "/auth/", "/login", "/register", "/logout", "/signup", "/token", "/oauth",
    "/health", "/public/", "/.well-known/")

_AUTH_EVIDENCE_RE = re.compile(r"auth|bearer|token|credential|jwt|api[-_]?key", re.I)

_BARE_FETCH_RE = re.compile(r"\bfetch\s*\(")


def _balanced_call_span(text: str, open_idx: int) -> str:
    """``text[open_idx:...]`` from the ``(`` at ``open_idx`` through its balanced close.
    Quote-aware ('' "" ``) so parens inside string/template literals never unbalance the
    scan; backslash escapes honored. Falls back to a bounded slice on malformed source."""
    depth, i, n, quote = 0, open_idx, len(text), None
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
        i += 1
    return text[open_idx:open_idx + 600]


def _leading_string_literal(inner: str) -> Tuple[Optional[str], str]:
    """Split a call's argument text into (first string literal, the REST of the args).
    Returns ``(None, inner)`` when the first argument is not a string/template literal."""
    inner = inner.lstrip()
    if not inner or inner[0] not in "'\"`":
        return None, inner
    q, j, chars = inner[0], 1, []
    while j < len(inner):
        c = inner[j]
        if c == "\\" and j + 1 < len(inner):
            chars.append(inner[j:j + 2])
            j += 2
            continue
        if c == q:
            break
        chars.append(c)
        j += 1
    return "".join(chars), inner[j + 1:]


_FW_AUTH_FETCH_MARKER = "__fw_auth_fetch__"

# #566r (netflix r126 — 79-min no-convergence abort on deliverability_bare_authed_fetch): a global
# window.fetch wrapper that attaches the bearer token to same-origin /api/ requests. Installed in
# index.html <head> so it runs before the app bundle and survives the vite build. Makes EVERY bare
# fetch('/api/…') auth'd at runtime → the static gate self-clears (see bare_authed_fetch_blockers'
# early return), independent of lane/remediation/reconcile timing (r126: the lane's fix reached the
# gate-read integration tree only AFTER the abort). Idempotent (guard flag), guarded (try/catch,
# falls back to the original fetch), excludes the /api/v1/ control plane (public by design).
_AUTH_FETCH_WRAPPER = (
    "<script>\n"
    "(function(){\n"
    "  if (typeof window==='undefined' || window.__fw_auth_fetch__) return;\n"
    "  window.__fw_auth_fetch__ = true;\n"
    "  var _f = window.fetch;\n"
    "  if (typeof _f !== 'function') return;\n"
    "  window.fetch = function(input, init){\n"
    "    try {\n"
    "      var url = typeof input==='string' ? input : (input && input.url) || '';\n"
    "      if (url.indexOf('/api/')!==-1 && url.indexOf('/api/v1/')===-1) {\n"
    "        var tok = (window.localStorage && (localStorage.getItem('access_token') || "
    "localStorage.getItem('token'))) || '';\n"
    "        if (tok) {\n"
    "          init = init || {};\n"
    "          var h = new Headers((init && init.headers) || {});\n"
    "          if (!h.has('Authorization')) h.set('Authorization', 'Bearer ' + tok);\n"
    "          init.headers = h;\n"
    "        }\n"
    "      }\n"
    "    } catch (e) {}\n"
    "    return _f.call(this, input, init);\n"
    "  };\n"
    "})();\n"
    "</script>"
)


def _has_global_auth_fetch_wrapper(frontend_src: Any) -> bool:
    """#566r: True iff the global auth-fetch wrapper is installed (marker present in the frontend
    index.html or any src file). When it is, every bare ``fetch('/api/…')`` is auth'd at runtime, so
    a bare call site is not a blocker."""
    try:
        src = Path(frontend_src)
        cands: List[Path] = []
        idx = src.parent / "index.html"
        if idx.is_file():
            cands.append(idx)
        if src.is_dir():
            cands += [f for f in (list(src.rglob("*.js")) + list(src.rglob("*.jsx"))
                                  + list(src.rglob("*.ts")) + list(src.rglob("*.tsx")))
                      if "node_modules" not in f.parts]
        for f in cands:
            try:
                if _FW_AUTH_FETCH_MARKER in f.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def inject_auth_fetch_wrapper(frontend_dir: Any) -> bool:
    """#566r: install the global auth-fetch wrapper into ``<frontend_dir>/index.html`` (before
    </head>), so bare ``fetch('/api/…')`` calls carry the token at runtime and the
    deliverability_bare_authed_fetch gate self-clears. Idempotent + best-effort; returns True iff it
    wrote the wrapper this call."""
    try:
        idx = Path(frontend_dir) / "index.html"
        if not idx.is_file():
            return False
        html = idx.read_text(encoding="utf-8", errors="ignore")
        if _FW_AUTH_FETCH_MARKER in html:
            return False
        if "</head>" in html:
            html = html.replace("</head>", _AUTH_FETCH_WRAPPER + "\n</head>", 1)
        else:
            html = _AUTH_FETCH_WRAPPER + "\n" + html
        idx.write_text(html, encoding="utf-8")
        return True
    except Exception:
        return False


def bare_authed_fetch_blockers(frontend_src: Any, limit: int = 12) -> List[str]:
    """Scan EVERY frontend source file for a bare ``fetch()`` of a literal authed
    ``/api/…`` URL whose call site shows no auth evidence → delivery-blocker strings
    (``app/frontend/src/<rel>:<line>`` precision). Purely static, recomputed from code
    truth each gate tick (self-clearing), best-effort ``[]`` on any fault."""
    blockers: List[str] = []
    try:
        src = Path(frontend_src)
        if not src.is_dir():
            return []
        if _has_global_auth_fetch_wrapper(src):
            return []  # #566r: a global window.fetch wrapper auth's every /api/ request
        files = sorted(
            f for f in (list(src.rglob("*.jsx")) + list(src.rglob("*.js"))
                        + list(src.rglob("*.tsx")) + list(src.rglob("*.ts")))
            if "node_modules" not in f.parts)
        total = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in _BARE_FETCH_RE.finditer(text):
                open_idx = text.index("(", m.start())
                span = _balanced_call_span(text, open_idx)
                literal, rest = _leading_string_literal(span[1:-1])
                if literal is None:
                    continue  # variable URL (e.g. the api.js request(path) wrapper)
                static_text = re.sub(r"\$\{[^}]*\}", "", literal)
                if not static_text.startswith("/api/"):
                    continue  # not an authed same-origin API literal
                if any(p in static_text for p in _PUBLIC_FETCH_PATH_MARKERS):
                    continue  # public endpoint — carries no token by design
                if _AUTH_EVIDENCE_RE.search(rest):
                    continue  # the call site attaches auth some way
                arg2 = rest.lstrip().lstrip(",").strip()
                if arg2 and re.match(r"^[A-Za-z_$][\w$.]*(\(\))?$", arg2):
                    continue  # opaque options identifier — may carry auth built elsewhere
                # #233 (r23 FALSE-BLOCK, 83-min abort): `{ headers: getHeaders() }`
                # / `{ ...buildOpts() }` — the headers come from a HELPER whose
                # body attaches the token. A non-literal headers value (call or
                # identifier) or a spread call inside the options is opaque: the
                # gate only flags PROVABLY bare calls, so excuse it. The lane's
                # api.js was fully correct and the run died on an unwinnable gate.
                # #508 (netflix r83 FALSE-BLOCK → main()=1, no release, 2026-08-05): ALSO
                # excuse ES6 SHORTHAND `{ headers }` (and `{ headers, … }` / `{ …, headers }`).
                # A `headers` VARIABLE passed by shorthand is EXACTLY as opaque as the
                # `headers: ident` case #233 already excuses — the colon-only #233 regex just
                # missed the no-colon shorthand. r83 died here on a CORRECT app (TitleDetail
                # Page: `const headers = token ? {Authorization: `Bearer ${token}`} : {};
                # fetch(url, { headers })` — auth WAS attached via the variable). An inline
                # LITERAL headers object without auth (`{ headers: { 'X': 'y' } }`) still has
                # no colon-identifier / shorthand match → stays flagged (genuinely bare).
                if re.search(r"headers\s*:\s*[A-Za-z_$][\w$.]*\s*(\(|[,}\)])", arg2) \
                        or re.search(r"\.\.\.\s*[A-Za-z_$][\w$.]*\s*\(", arg2) \
                        or re.search(r"[{,]\s*headers\s*[,}]", arg2):
                    continue
                total += 1
                if len(blockers) < limit:
                    rel = f.relative_to(src).as_posix()
                    line = text.count("\n", 0, m.start()) + 1
                    blockers.append(
                        f"frontend calls an authed API via bare unauthenticated fetch(): "
                        f"app/frontend/src/{rel}:{line} fetches '{static_text}' with no "
                        f"Authorization header — at runtime the backend answers 401 and the "
                        f"page renders empty / bounces to the login wall (api_smoke cannot "
                        f"see this: it uses a framework-minted token). Route the call "
                        f"through the authed api client (src/services/api.js attaches "
                        f"authHeaders()) or attach the Bearer token at this call site.")
        if total > len(blockers):
            blockers.append(
                f"… and {total - len(blockers)} more bare unauthenticated fetch() call "
                f"site(s) — the same fix applies to each.")
    except Exception:
        return []
    return blockers


def audit_asset_usage(frontend_dir: Any, design_system: Mapping[str, Any]) -> Dict[str, Any]:
    """ADVISORY (never a hard block): flag each component the Design-Prep design_system maps to a
    REAL asset that no frontend file actually references. For every ``screens[].components[].assets``
    id, resolve its manifest ``file`` and check whether ANY frontend ``src`` file mentions that
    file's basename (e.g. ``ig.svg``); if none do, the lane drew an approximation instead of using
    the real asset → report ``{component, asset, file}``. A1: also returns the same entries scoped
    per screen (``unused_by_screen: {screen_name: [entry,...]}``) so the visual remediation can
    mandate the assets FIRST on exactly the failing screens. Best-effort; empty shapes on any
    error or missing design_system."""
    out: Dict[str, Any] = {"unused_mapped": [], "unused_by_screen": {}}
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
        seen_per_screen = set()
        for screen in (ds.get("screens") or []):
            sname = str(screen.get("name") or "") if isinstance(screen, dict) else ""
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
                    if base in blob:
                        continue
                    entry = {"component": cid, "asset": aid, "file": fname}
                    key = (cid, aid)
                    if key not in seen:
                        seen.add(key)
                        out["unused_mapped"].append(entry)
                    # A1: per-screen scoping — the SAME (component, asset) pair can
                    # legitimately recur on several screens (nav rails), so the
                    # by-screen map dedupes per screen, not globally.
                    skey = (sname, cid, aid)
                    if sname and skey not in seen_per_screen:
                        seen_per_screen.add(skey)
                        out["unused_by_screen"].setdefault(sname, []).append(dict(entry))
    except Exception:
        return {"unused_mapped": [], "unused_by_screen": {}}
    return out


# ── FIX #175: FABRICATED member-field fallbacks (invented-data placeholders) ──────────────
# gmrun9's delivered SearchResultsPage rendered `place.rating || '4.5'`,
# `place.reviews || '1,234'` (the model field is `review_count` — the name DRIFTED so the
# fallback fired on EVERY row), `place.address || 'San Francisco, CA'`, and ternary fakes
# `? selectedPlace.name : 'HI Point Montara Lighthouse'`. Each renders FABRICATED data when
# the real field is absent — the user's "no placeholder/mock" bar. #170 added a PROMPT rule;
# the lane ignored it, so this is the ENFORCING gate. Deterministic + static, best-effort.
_INVENTED_HONEST = frozenset({
    "n/a", "na", "n.a.", "tbd", "tba", "unknown", "none", "null", "nil", "unset",
    "untitled", "anonymous", "guest", "unnamed", "no name", "no title", "placeholder",
    "—", "-", "--", "...", "…", "loading", "loading...", "please wait", "empty",
    "no results", "no data", "not found", "not available", "unavailable", "default",
    # honest STATE/enum defaults (not fabricated DATA — a missing status shown as its
    # base state, not a fake specific value like a rating or a place name)
    "active", "inactive", "pending", "enabled", "disabled", "draft", "published",
    "open", "closed", "online", "offline", "public", "private", "archived",
})
_INVENTED_HONEST_SUBSTR = (
    "error", "fail", "invalid", "loading", "not found", "no results",
    "unavailable", "required", "missing", "please ",
    # "…not available/set/provided/specified" absence phrasings (archive audit)
    "not available", "not set", "not provided", "not specified", "not listed",
    "no data", "no info", "coming soon",
)
# A fallback that SIGNALS ABSENCE (rather than asserting a fabricated value) is honest even
# when multi-word: "No description", "Unknown Place", "Anonymous User". Prefix-matched.
_INVENTED_HONEST_PREFIX = ("no ", "unknown", "anonymous", "select ", "choose ", "enter ",
                           "untitled", "loading", "search")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_ASSET_EXT = re.compile(r"\.(svg|png|jpe?g|gif|webp|ico|avif|bmp)($|\?|#)", re.I)
# member.field || 'literal'     and     ? member.field : 'literal'
# CHECKER regexes (invented_field_fallback_blockers) — member-access LHS only. SOUND; UNTOUCHED.
_INVENTED_OR = re.compile(r"""(\b\w+(?:\.\w+)+)\s*\|\|\s*(['"])(.*?)\2""")
_INVENTED_TERNARY = re.compile(r"""\?\s*(\b\w+(?:\.\w+)+)\s*:\s*(['"])(.*?)\2""")

# ── FIX #496 (netflix r66): HEAL-side WIDENED patterns ────────────────────────────────────
# r66 wedged on `deliverability_fabricated_field_fallback`: `title.live_label || 'Live now'`
# (JSX-text) and `t.title || 'Title details'` (attr) — both member-LHS, so the CHECKER above
# flagged them, and the heal (which shares the checker's member-only regexes) must clear
# exactly these. To make the heal a PROVABLE SUPERSET of the checker — so the gate is ALWAYS
# clearable (round-trip = 0 by construction) and can never drift narrower — the heal drives
# off these widened patterns instead:
#   `_HEAL_EXPR` = `[\w$]+(?:\.[\w$]+)*` matches a member LHS (`a.b.c`) AND a BARE identifier
#   (`x`, 0 dots) AND JS `$`-names — so it strictly CONTAINS the checker's `\w+(?:\.\w+)+`
#   (every checker OR/ternary site is also a heal site). The BARE-identifier LHS and the
#   MIRROR ternary (`cond ? 'lit' : expr`) are forms the checker deliberately does NOT flag;
#   the heal cleans them PROACTIVELY while the checker's proven-sound flag set stays untouched.
# The literal guard `_is_fabricated_fallback_literal` is the SAME classifier the checker uses,
# so legitimate defaults (`count || '0'`, `|| ''`, `|| 'all'`, error/asset/hex/state literals)
# are NEVER rewritten — the heal inherits the checker's soundness on what NOT to touch.
_HEAL_EXPR = r"[\w$]+(?:\.[\w$]+)*"
# `(?<![\w$])` keeps the match anchored at an identifier start (mirrors the checker's `\b`,
# and still permits a leading `.`/`(`/`{`/space, so `a().foo.bar || 'x'` matches `foo.bar`
# exactly as the checker does — parity, no NEW build-break span).
_HEAL_OR = re.compile(r"(?<![\w$])(" + _HEAL_EXPR + r")\s*\|\|\s*(['\"])(.*?)\2")
_HEAL_TERNARY_FALSE = re.compile(r"\?\s*(" + _HEAL_EXPR + r")\s*:\s*(['\"])(.*?)\2")
_HEAL_TERNARY_TRUE = re.compile(r"\?\s*(['\"])(.*?)\1\s*:\s*(" + _HEAL_EXPR + r")")


def _is_fabricated_fallback_literal(s: str) -> bool:
    """True iff a fallback STRING looks like real DOMAIN DATA (a fabricated rating/price/count
    with a digit, a multi-word name/address/sentence, or a capitalized proper noun) rather
    than an honest absence/error/loading convention."""
    t = (s or "").strip()
    if not t:
        return False
    # The lane often writes the honest em-dash / ellipsis empty-state as a JS unicode escape
    # ('—' → '—'). The STATIC source then contains digits (2014) and would false-flag as
    # fabricated → M2 abort. Decode \uXXXX / \xXX to the RENDERED character before classifying
    # (safe: an escape resolves to a single symbol char, never fabricated data).
    if "\\u" in t or "\\x" in t:
        t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)),
                   re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), t)).strip()
        if not t:
            return False
    low = t.lower()
    if low in _INVENTED_HONEST:
        return False
    if any(sub in low for sub in _INVENTED_HONEST_SUBSTR):
        return False
    if low.startswith(_INVENTED_HONEST_PREFIX):   # "No description", "Unknown Place", "Anonymous User"
        return False
    # Styling / placeholder-asset defaults are NOT display DATA: a hex color, or an asset
    # path ('/assets/…', '…/ph-img-1.svg') — a placeholder image is an HONEST "no photo"
    # state, not a fabricated value. (archive audit: gmrun4 #3b82f6, gmrun7 ph-img-1.svg)
    if _HEX_COLOR.match(t):
        return False
    if t.startswith("/") or _ASSET_EXT.search(t):
        return False
    # Honest ZERO / empty-count state — '0', '0.0', '$0', '0%', '0 reviews', '0 results'.
    # gmrun11 ABORTED because `place.review_count || '0'` was flagged as fabricated: '0' is
    # the legitimate "none yet" display, NOT invented data, so the lane could never clear it
    # → 75min non-convergence. Only a NON-ZERO number is a fabricated value.
    _first = re.sub(r"[,$%]", "", t.split()[0]) if t.split() else ""
    try:
        if float(_first) == 0.0:
            return False
    except ValueError:
        pass
    if any(ch.isdigit() for ch in t):            # rating / price / count / date
        return True
    if " " in t:                                 # name / address / sentence
        return True
    if t[:1].isupper() and len(t) >= 4 and t.isalpha():  # proper-noun default (Hotel, Place)
        return True
    return False


def invented_field_fallback_blockers(frontend_src: Any, limit: int = 20) -> List[str]:
    """#175: frontend member-field fallbacks to FABRICATED display literals
    (``place.rating || '4.5'`` / ``? place.name : 'HI Point Montara Lighthouse'``) →
    delivery blockers. Static, recomputed each gate tick, best-effort ``[]`` on any fault.
    ``ENVGEN_INVENTED_FIELD_GATE=0`` disables."""
    import os as _os
    if _os.environ.get("ENVGEN_INVENTED_FIELD_GATE", "1").strip().lower() in (
            "0", "false", "no", "off"):
        return []
    try:
        src = Path(frontend_src)
        if not src.is_dir():
            return []
    except Exception:
        return []
    seen = set()
    blockers: List[str] = []
    try:
        files = list(src.rglob("*.jsx")) + list(src.rglob("*.tsx"))
    except Exception:
        return []
    for f in sorted(files):
        if "node_modules" in f.parts:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for rx in (_INVENTED_OR, _INVENTED_TERNARY):
                for m in rx.finditer(line):
                    member, lit = m.group(1), m.group(3)
                    if not _is_fabricated_fallback_literal(lit):
                        continue
                    key = (f.name, i, member, lit)
                    if key in seen:
                        continue
                    seen.add(key)
                    blockers.append(
                        f"frontend renders a FABRICATED fallback `{member} || '{lit}'` "
                        f"({f.name}:{i}) — it shows invented data whenever `{member}` is "
                        "absent (often ALWAYS, if the field name drifted from the backend). "
                        "Render ONLY the real field (e.g. `{" + member + "}`), or an honest "
                        "empty state ('—' / 'N/A') — never a realistic fake value.")
                    if len(blockers) >= limit:
                        return blockers
    return blockers


def repair_fabricated_fallbacks(frontend_src: Any) -> Dict[str, Any]:
    """FIX #191 (tiktok-r3 NO-CONVERGENCE) + #496 (netflix r66): DETERMINISTIC
    rewrite of the fabricated-fallback sites the #175 gate flags —
    `<expr> || 'fabricated'` → `(<expr> ?? '—')` and ternary fakes' literal
    branch → '—' (an honest empty state per the gate's own remediation text).

    #496: the heal drives off WIDENED patterns that form a PROVABLE SUPERSET of
    the checker (`invented_field_fallback_blockers`) — `_HEAL_EXPR` contains the
    checker's member-access LHS, so EVERY site the checker flags is repaired here
    (r66 wedged 0×-heal-vs-3×-flag on `title.live_label || 'Live now'` /
    `t.title || 'Title details'` — both now cleared). It ALSO cleans the
    bare-identifier LHS (`x || 'Live now'`) and the mirror ternary
    (`cond ? 'lit' : expr`) that the checker deliberately does NOT flag, keeping
    the checker's sound flag set untouched while guaranteeing the gate is always
    clearable: run checker → run heal → run checker = 0 flagged, BY CONSTRUCTION.

    Shares the checker's literal classifier `_is_fabricated_fallback_literal`, so
    legitimate defaults (`count || '0'`, `|| ''`, `|| 'all'`, error/asset/hex/
    state literals) are NEVER rewritten. r3's frontend lane thrashed 75min on
    exactly this edit and the run aborted. The gate stays HARD; field-name drift
    then shows as honest '—' cells, which the no_real_data browser gate owns.
    Idempotent; best-effort; never raises.
    Returns {"repaired": [relpaths], "sites": ["file:line before→after", ...]}."""
    repaired: List[str] = []
    sites: List[str] = []
    try:
        src = Path(frontend_src)
        if not src.is_dir():
            return {"repaired": repaired, "sites": sites}
        files = [f for f in (list(src.rglob("*.jsx")) + list(src.rglob("*.tsx")))
                 if "node_modules" not in f.parts]
    except Exception:
        return {"repaired": repaired, "sites": sites}
    for f in sorted(files):
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        except Exception:
            continue
        changed = False
        new_lines: List[str] = []
        for i, line in enumerate(lines, 1):
            def _sub_or(m):
                expr, lit = m.group(1), m.group(3)
                if not _is_fabricated_fallback_literal(lit):
                    return m.group(0)
                # #239 (tiktok r29 build-break abort): ALWAYS parenthesize the
                # ?? replacement. JS forbids mixing ?? with || / && without parens
                # (`a || b ?? c` is a SyntaxError esbuild rejects). A chain
                # `cur.title || cur.description || 'lit'` rewrites only the LAST
                # `|| 'lit'` → `cur.title || cur.description || ('lit'→)('—')`;
                # without parens `... ?? '—'` broke the vite build → r29 abort.
                # `(x ?? '—')` is always valid, standalone or inside a || / && chain.
                sites.append(f"{f.name}:{i} `{expr} || '{lit}'` → `({expr} ?? '—')`")
                return f"({expr} ?? '—')"

            def _sub_ternary_false(m):
                # `cond ? expr : 'lit'` — fabricated literal in the FALSE branch.
                expr, lit = m.group(1), m.group(3)
                if not _is_fabricated_fallback_literal(lit):
                    return m.group(0)
                sites.append(f"{f.name}:{i} `? {expr} : '{lit}'` → `? {expr} : '—'`")
                return f"? {expr} : '—'"

            def _sub_ternary_true(m):
                # #496 mirror: `cond ? 'lit' : expr` — fabricated literal in the
                # TRUE branch. Rewrite the literal → honest '—'; expr is preserved.
                lit, expr = m.group(2), m.group(3)
                if not _is_fabricated_fallback_literal(lit):
                    return m.group(0)
                sites.append(f"{f.name}:{i} `? '{lit}' : {expr}` → `? '—' : {expr}`")
                return f"? '—' : {expr}"

            new = _HEAL_OR.sub(_sub_or, line)
            new = _HEAL_TERNARY_FALSE.sub(_sub_ternary_false, new)
            new = _HEAL_TERNARY_TRUE.sub(_sub_ternary_true, new)
            if new != line:
                changed = True
            new_lines.append(new)
        if changed:
            try:
                f.write_text("".join(new_lines), encoding="utf-8")
                repaired.append(f.name)
            except Exception:
                continue
    return {"repaired": repaired, "sites": sites}


# #615 — N NAV DESTINATIONS, ONE UNFILTERED COLLECTION. The generic form of "click Games, see
# Movies": distinct routes whose delivered pages fetch an IDENTICAL, unparameterised endpoint
# set therefore render identical content. No product vocabulary is involved — the finding is
# "these k routes are the same page".
#
# Measured over the arc: **32 of 45** runs have at least one such group in the DELIVERED code
# (not merely in the declared `apis_used`). r100 is the worst: `/browse`, `/browse/languages`,
# `/games`, `/movies`, `/new`, `/shows` — SIX routes, each fetching only `/api/titles` with no
# filter.
#
# Deliberately NOT wired as a delivery blocker. At 32/45 it would wedge nearly every run, and
# whether "six identical pages" should block or merely be reported is a calibration decision,
# not a measurement — the same call as the 0.65 fidelity bar. Also worth knowing before anyone
# "fixes" it by inventing filters: the seed gives every title `kind='standard'`, so a
# route-derived filter would return everything or nothing.
# capture the char AFTER the path too: a fetch that continues into `{`, `?`, `$` or `+` is
# PARAMETERISED and therefore differentiates the page. Matching only the literal prefix would
# make `/api/titles/{id}` and `/api/titles?kind=movie` both look like a bare `/api/titles`.
_PAGE_FETCH_RE_615 = re.compile(r"""['"`](/api/[A-Za-z0-9_\-/]+)([^'"`]?)""")


def duplicate_route_content_groups(frontend_src: Any, ui_pages: Any) -> List[Dict[str, Any]]:
    """#615 — groups of DISTINCT routes whose page components fetch the same unfiltered
    endpoint set. ``[]`` when nothing can be resolved, so a caller can always iterate."""
    out: List[Dict[str, Any]] = []
    try:
        pages_dir = Path(str(frontend_src)) / "src" / "pages"
        if not pages_dir.is_dir():
            return out
        by: Dict[frozenset, List[str]] = {}
        seen_routes: Dict[frozenset, set] = {}
        items = (ui_pages or {}).items() if isinstance(ui_pages, Mapping) else [
            (None, p) for p in (ui_pages or [])]
        for _k, page in items:
            if not isinstance(page, Mapping):
                continue
            comp = str(page.get("component") or "").strip()
            route = str(page.get("route") or "").strip()
            if not comp or not route:
                continue
            f = pages_dir / f"{comp}.jsx"
            if not f.is_file():
                continue
            eps = frozenset(
                _e for _e, _next in _PAGE_FETCH_RE_615.findall(
                    f.read_text(encoding="utf-8", errors="ignore"))
                if _next not in ("{", "?", "$", "+") and "{" not in _e and "?" not in _e)
            if not eps:
                continue
            by.setdefault(eps, []).append(comp)
            seen_routes.setdefault(eps, set()).add(route)
        for eps, comps in by.items():
            routes = sorted(seen_routes.get(eps) or ())
            if len(routes) > 1:
                out.append({"routes": routes, "endpoints": sorted(eps),
                            "components": sorted(set(comps))})
    except Exception:
        return out
    return sorted(out, key=lambda g: -len(g["routes"]))
