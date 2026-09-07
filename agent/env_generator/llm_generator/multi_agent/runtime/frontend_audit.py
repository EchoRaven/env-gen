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
import logging

_LOG_791 = logging.getLogger(__name__)

# --- #791: a blocker scan that throws must not ERASE the blockers it already found -------------
# `routed_fallback_page_blockers` and `bare_authed_fetch_blockers` collect into `blockers` inside
# a try and returned `[]` from the handler — so an exception on file 6 discarded the five real
# findings from files 1-5, and deliverability.py (the release-BLOCKING path) read "clean". That is
# strictly worse than a permissive default: it is not falling back, it is destroying evidence,
# the same shape as #737's blank capture erasing the record. Partial results are now returned,
# and the truncation is announced — a partial scan is not a clean one.
_SCAN_ERRORS_791: List[str] = []


def _scan_truncated_791(where: str, exc: BaseException, kept: int) -> None:
    """Record + announce a blocker scan that ended early. Never raises."""
    try:
        note = "%s: %s (%s) — kept %d finding(s) already made" % (
            where, type(exc).__name__, exc, kept)
        if note not in _SCAN_ERRORS_791:
            _SCAN_ERRORS_791.append(note)
            _LOG_791.warning(
                "BLOCKER SCAN TRUNCATED (#791): %s. The findings so far are RETURNED (they used "
                "to be discarded, which read as a clean scan on the release-blocking path), but "
                "the rest of the tree was never examined — absence of further blockers here is "
                "not evidence there are none.", note)
    except Exception:
        pass


def scan_errors_791() -> List[str]:
    """Blocker scans that ended early this process. Empty is the normal, healthy state."""
    return list(_SCAN_ERRORS_791)


def reset_scan_errors_791() -> None:
    _SCAN_ERRORS_791.clear()

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Single source of truth for "the same route" — shared with the BACKEND route
# audit (backend_audit.py uses the same two helpers via _norm_route). The
# frontend route-wiring check MUST normalize the same way the backend does, or a
# declared `/channel/:handle` reads as "unwired" against a wired
# `/channel/:channelId` (PROPOSAL #18: the frontend route check was the last
# brittle byte-equality match in an otherwise param-tolerant pipeline).
from .route_projector import _express_to_fastapi, _norm_path
# #906: the canonical "is this record a real, deliverable page?" test, shared with the ui_flow gate
# so the two cannot drift apart again — this module open-coded its own copy and #905 disproved the
# premise both copies rested on. Module-level on purpose: `flow_coverage` imports nothing from the
# package (no cycle), and a function-local import here would raise INSIDE the `except Exception:
# pass` that wraps the ui_page audit, silently disabling every blocker it produces (#827's shape).
from .flow_coverage import _is_navigable_page
from .message_format import join_capped  # #1034

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
        # #1202gk: HANDING THE HELPER TO SOMETHING THAT CALLS IT IS USING IT.
        #
        # The two forms above both require the helper to be INVOKED syntactically in this
        # file. React's other idiom passes it instead -- `useApiList(getVideos, [])` -- and
        # the hook does the fetching. tiktok-r98's ExploreGridPage imports `getVideos` from
        # services/api, hands it to `useApiList`, and renders `videos.items`; it is a real
        # page that really loads data, and ui_page_unwired called it "a STATIC MOCK (no api
        # call)" and blocked delivery on it, together with /live and /messages.
        #
        # This is the same widening the service-object case above already records ("the
        # direct-call-only check false-flagged every page using it as a placeholder stub"),
        # for the third syntactic shape of one behaviour. Measured over the 1922 page files
        # on this machine: 766 read as call-less today, and 20 of those (4 runs) pass an
        # imported service helper into a call. Narrow by construction -- the name must be
        # imported from services/api AND appear as an ARGUMENT, so a bare mention or a
        # property read still does not count.
        if re.search(r"\w+\s*\([^)]*\b" + re.escape(n) + r"\b", text):
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


def _span_truncated_810(where: str, n: int) -> None:
    """#810: a bounded-slice fallback fired, so the caller is parsing a FRAGMENT.

    `_tag_span`, `_element_span` and `_balanced_call_span` all scan for a balanced delimiter and
    fall back to a fixed-width slice when the source is unbalanced. The fallback is correct — the
    alternative is reading to end-of-file — but it was silent, and `_balanced_call_span` feeds
    `bare_authed_fetch_blockers`, i.e. the release-BLOCKING path. A truncated span there means the
    audit judged a call site it only half saw, in either direction: a missed blocker or an
    invented one.

    Reuses #791's say-once list rather than adding a fourth reporting mechanism (#792's lesson),
    which also means it already reaches the delivery gate through #793's merge.
    """
    try:
        note = "%s: unbalanced source, parsed a bounded %d-char fragment" % (where, n)
        if note not in _SCAN_ERRORS_791:
            _SCAN_ERRORS_791.append(note)
            _LOG_791.warning(
                "AUDIT PARSED A FRAGMENT (#810): %s. The scan could not find the closing "
                "delimiter, so this verdict rests on a truncated span -- treat a finding here, "
                "or the absence of one, as unconfirmed.", note)
    except Exception:
        pass


def _tag_span(app_jsx: str, pidx: int) -> str:
    """The full ``<Route ...>`` tag enclosing the ``path=`` at ``pidx`` — bounded by the
    first ``>`` at brace-depth 0, so a ``>`` inside ``element={...}`` (a JS expression, or
    a nested ``<Wrapper><Page/></Wrapper>``) does NOT truncate the tag."""
    start = app_jsx.rfind("<Route", 0, pidx)
    if start == -1:
        _span_truncated_810("_tag_span:no-<Route>-before", 200)
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
    _span_truncated_810("_tag_span", 400)
    return app_jsx[start:start + 400]


def _app_import_module_1082(app_jsx: str, ident: str) -> str:
    """The MODULE STEM App.jsx imports ``ident`` from, or "" — the app's own answer to
    "which file is this component?".

    `_route_element` answers a different question (which IDENTIFIER a route renders) and
    cannot see this divergence, because the import is what aliases the two: run67 writes
    ``import DirectMessagesPage from './pages/DirectMessages'``, so the element name matches
    the declaration and only the path differs."""
    m = re.search(r"import\s+" + re.escape(str(ident or "")) +
                  r"\s+from\s+['\"]([^'\"]+)['\"]", str(app_jsx or ""))
    if not m:
        return ""
    stem = m.group(1).rstrip("/").split("/")[-1]
    return stem[:-4] if stem.endswith(".jsx") else stem


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


_JSX_TAG_909 = re.compile(r"<([A-Z]\w*)")


class _Skip925(Exception):
    """Raised to skip a repeated report; the call site's `except Exception: pass` absorbs it.

    ★ Deliberate: the reports already sit inside a bare `except` (an observability call must not
    take down the status sync), so a sentinel reuses that guard instead of adding a second branch
    around each `_LOG_791.warning`. The `out[...]` dict is populated BEFORE the skip, so a caller
    reading `component_drift` / `api_unreachable` still sees every finding every tick — only the
    LOG is deduped."""


# #925: transition-dedup for the two REPORTS below, the way #899 does it for the stage timeline.
# `sync_ui_page_statuses` is called from `generate_backend_skeleton`, which re-runs on EVERY
# delivery tick — r153 logged 34 `database_scaffold` records from that same loop. Without this,
# #909 and #918 would print 5x34 and 4x34 lines for an unchanging state, which is precisely #845's
# rule ("a line that repeats every tick stops being read") — a rule #909's own docstring cites and
# then did not follow. Keyed on the FINDING, so a page whose orphan set changes still speaks.
_SAID_925: dict = {}


def reset_said_925() -> None:
    """Test hook; also safe to call per run so a long session does not silence a later one."""
    _SAID_925.clear()


def _say_once_925(kind: str, name: str, finding) -> bool:
    """True the first time this exact finding is seen for this page, and whenever it CHANGES."""
    try:
        key = (kind, str(name))
        sig = tuple(sorted(str(x) for x in (finding or ())))
        if _SAID_925.get(key) == sig:
            return False
        _SAID_925[key] = sig
        return True
    except Exception:
        return True


_IMPORT_918 = re.compile(r"""from\s+['"](\.[^'"]+)['"]""")


def _page_closure_918(page: Mapping[str, Any], src_cache: Dict[str, str]) -> Dict[str, str]:
    """#918: every file a page can actually REACH — its own source plus everything it imports or
    renders, transitively.

    Distinct from `_rendered_components_909` on purpose. #909 asks *"does the page render the
    components it declares"*; this asks *"can the page reach the APIs it declares"*, and the API
    call usually lives in `services/api.js`, which a page IMPORTS rather than renders. Following
    only JSX tags therefore reports every page as unreachable — that was the first version of this,
    and `profiles` (which does call `/api/profiles`, through `api.js`) read as 0 of 2.

    Cache-only and total: never touches disk, never raises. Keys are normalised through
    `Path(...).resolve()` on BOTH sides — the second version of this failed because the cache is
    keyed on the caller's walk (relative) while `(parent / spec).resolve()` is absolute, so no
    import ever matched and the noise looked like signal.
    """
    out: Dict[str, str] = {}
    try:
        files = {}
        for _k, _v in (src_cache or {}).items():
            try:
                files[Path(_k).resolve()] = _v
            except Exception:
                continue
        by_stem = {p.stem: p for p in files}
        _rel = str(page.get("path") or "").replace("\\", "/")
        stem = Path(_rel).stem if _rel else str(page.get("component") or "")
        start = by_stem.get(stem)
        if start is None:
            return out
        stack, seen = [start], set()
        while stack:
            p = stack.pop()
            if p in seen or p not in files:
                continue
            seen.add(p)
            text = files[p]
            out[str(p)] = text
            for m in _IMPORT_918.finditer(text):
                q = (p.parent / m.group(1)).resolve()
                for cand in (q, q.with_suffix(".jsx"), q.with_suffix(".js")):
                    if cand in files:
                        stack.append(cand)
                        break
            for tag in _JSX_TAG_909.findall(text):
                if tag in by_stem:
                    stack.append(by_stem[tag])
    except Exception:
        return {}
    return out


def _rendered_components_909(frontend_src: Path, page: Mapping[str, Any],
                             src_cache: Dict[str, str]) -> set:
    """#909: the components a page actually renders, following the tree TRANSITIVELY.

    A page that renders `<PosterRail/>` uses `PosterCard` too, so a direct-tag comparison would
    report drift that is not there. Reads only the already-populated cache — never touches disk,
    never raises: this feeds a WARNING inside the loop that maintains every ui_page's status, and
    an observability call that throws there would take the status sync down with it (#906/#827).
    """
    try:
        by_stem: Dict[str, str] = {}
        for _fn, _tx in (src_cache or {}).items():
            try:
                by_stem.setdefault(Path(_fn).stem, _tx)
            except Exception:
                continue
        _rel = str(page.get("path") or "").replace("\\", "/")
        _stem = Path(_rel).stem if _rel else str(page.get("component") or "")
        start = by_stem.get(_stem)
        if start is None:
            return set()
        seen: set = set()
        stack = list(_JSX_TAG_909.findall(start))
        while stack:
            tag = stack.pop()
            if tag in seen or tag not in by_stem:
                continue
            seen.add(tag)
            stack.extend(_JSX_TAG_909.findall(by_stem[tag]))
        return seen
    except Exception:
        return set()


def audit_ui_page(frontend_src: Path, page: Mapping[str, Any],
                  *, _src_cache: Optional[Dict[str, str]] = None,
                  ) -> Tuple[bool, List[str]]:
    """One page → (implemented?, missing list). Purely static."""
    missing: List[str] = []
    component = str(page.get("component") or "").strip()
    route = str(page.get("route") or "").strip()
    apis = [a for a in (_norm_api(x) for x in (page.get("apis_used") or []))
            if a]

    # #907: `if not _src_cache`, not `is None`. Passed a dict, this function trusts it as the WHOLE
    # source tree — `_src_cache.get(str(canonical))` is the only place it looks for a component — so
    # an EMPTY dict does not mean "nothing cached yet", it means "there are no source files", and
    # every page audits as unusable. All four real call sites fill the cache first, so nothing in
    # the framework was wrong; a measurement of mine passed `_src_cache={}` and produced a confident
    # false blocker that reached a commit message (item 251). The tell was that the same record
    # returned ok=True without the argument and ok=False with it — a result that changes when you
    # add an "optional" argument is the argument saying it is not optional.
    #
    # Falling back to the walk on an empty dict costs one rglob in the only case where the old
    # behaviour was a silent lie; a genuinely empty tree still yields an empty cache and the same
    # verdict. Callers that pass a POPULATED cache are byte-identical.
    if not _src_cache:
        _src_cache = {}
        for f in list(frontend_src.rglob("*.jsx")) + list(frontend_src.rglob("*.js")):
            try:
                _src_cache[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
    all_src = "\n".join(_src_cache.values())

    app_jsx = _src_cache.get(str(frontend_src / "App.jsx")) or ""

    # #1077 — A QUERY/FRAGMENT ROUTE WHOSE BASE PATH IS WIRED IS A **STATE** OF THAT PAGE.
    # That is not a new rule: it is #913's, decided by the PROJECTOR
    # (`frontend_scaffold.scaffold_pages_from_contract`), which for this exact shape adds NO
    # route for the record and releases its component — *"the query is a STATE of the base
    # page, so when that path is already claimed, this record adds no route"*. The auditor
    # then failed the same record for having no route, up to three ways at once (canonical
    # page path + never-match + not-wired), none of them fixable by writing code — only by
    # re-registering. #913's own comment asks for the opposite: *"One rule, one producer."*
    #
    # Corpus: 9 records in 9 DISTINCT runs (r35/r52/r54/r55/r74/r79/r86/r87/r89), always the
    # same shape — a comments panel registered at `/?comments=1` while `/` is the feed. On
    # those runs' delivered frontends it is the single largest reason a page audits
    # unimplemented (7 of 37), i.e. `deliverability_ui_page_unwired` on a working app.
    #
    # A state is audited with the COMPONENT semantics this function already implements: its
    # home is `src/components/`, it owns no route, and the page-composes-page rule does not
    # apply to it. The route check is not simply dropped — it is replaced by the reachability
    # question an overlay actually has: somebody must MOUNT it (below).
    _state_of_base_1077 = False
    if route and ("?" in route or "#" in route):
        _base_1077 = route.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
        _state_of_base_1077 = _route_is_wired(_base_1077, app_jsx)
    _as_component_1077 = bool(page.get("_is_component")) or _state_of_base_1077

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
        if comp_file_text is None and _state_of_base_1077:
            # #1077: the canonical-layout rule splits on ROUTE ownership ("a page's root
            # component lives in src/pages/, a reusable component in src/components/"), and a
            # state owns no route — so the rule does not pick a side for it. The corpus has it
            # BOTH ways: r74/r54 author `CommentsPanelPage.jsx`/`FYPFeedPage.jsx` under pages/,
            # while a panel-shaped state belongs under components/. Both are canonical here;
            # neither is drift. (Reporting drift for the second spelling is a regression I
            # measured on the 67-run corpus before this line existed: 6 new findings, none of
            # them a defect in the app.)
            comp_file_text = _src_cache.get(
                str(frontend_src / "components" / f"{component}.jsx"))
        if comp_file_text is not None and _is_generic_fallback_page(comp_file_text):
            # #1082 — THE CANONICAL PATH IS A CONVENTION; THE IMPORT IS THE AUTHORITY.
            # run67 (*** 3 MILESTONES VALIDATED ***) ships DirectMessagesPage.jsx (the
            # framework's own 55-line generic projection, imported by nobody) beside the
            # lane's real DirectMessages.jsx, and App.jsx binds the SECOND under the FIRST's
            # name: `import DirectMessagesPage from './pages/DirectMessages'`. Resolving the
            # declaration by convention grades the orphan and tells the lane to "author the
            # REAL page" for a page that has one — 3 false blockers there, feeding
            # `deliverability_frontend_fallback_page` (1253 across 201 run logs, the #3
            # blocker). This is FIX #146's principle ("the app is the authority on where its
            # screens live") applied to the one input it never read.
            #
            # Narrow on purpose, this being a delivery-BLOCKING path: followed only when the
            # canonical file is the framework's OWN fallback, and only onto a target that is
            # not itself one. A lane page at the canonical path is never second-guessed, and
            # a missing target falls through unchanged. Measured: 3 of 448 resolvable
            # declarations drift this way.
            _mod_1082 = _app_import_module_1082(app_jsx, component)
            if _mod_1082 and _mod_1082 != component:
                for _cand_1082 in (frontend_src / "pages" / f"{_mod_1082}.jsx",
                                   frontend_src / "components" / f"{_mod_1082}.jsx"):
                    _txt_1082 = _src_cache.get(str(_cand_1082))
                    if _txt_1082 is not None and not _is_generic_fallback_page(_txt_1082):
                        comp_file_text = _txt_1082
                        break
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
            elem = _route_element(app_jsx, route) if not _as_component_1077 else None
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
    if route and _state_of_base_1077:
        # #1077 — the state owns no route, so "is it wired" is the wrong question. The right
        # one is whether anybody MOUNTS it: an overlay nothing renders is exactly as dead as
        # an unwired page, and the projector's release of the component (`seen_components.
        # discard`) means no other check will notice. `<Component` anywhere in src, because a
        # state is mounted by its parent page, not by the router.
        if component and not re.search(r"<\s*" + re.escape(component) + r"[\s/>]", all_src):
            missing.append(
                f"state `{component}` (registered at `{route}` — a state of `{_base_1077}`, "
                f"which IS wired) is never mounted: no `<{component}>` anywhere in src. "
                f"Render it from the `{_base_1077}` page behind the control that opens it, "
                f"or drop the record.")
    elif route:
        # PROPOSAL #18: normalized SET match (param-name-agnostic, trailing-param
        # fallback) instead of byte-substring — the frontend twin of the backend's
        # _norm_route. Clears cosmetic route drift (`/watch/:id`≡`/watch`,
        # `/channel/:handle`≡`/channel/:channelId`) while still hard-flagging a
        # genuinely-absent route (`/feed/library` with no matching wired path).
        # #913b: a route carrying a QUERY or FRAGMENT can never match — React Router matches the
        # PATHNAME only. `_route_is_wired` is a string/set match, so when the lane copies the
        # declared route into App.jsx verbatim the wiring check is SATISFIED by a route that can
        # never fire: the audit confirms a dead route as wired.
        #
        # `design_prep` already knows the class (#355, r93's `/?comments=1`: *"a dead route"*) and
        # handles it for DESIGN screens; a ui_page record carrying the same shape reaches here
        # unfiltered. r153 registered `title_detail` at `/browse?title=:id`, the lane wired it
        # verbatim, and the audit was happy. Corpus: 1 in 2120 routes — rare, and it is in the
        # arc's best run, where it was the only `detail`-ish param route, so
        # `wire_detail_modal_534` found no target and `TitleDetailModal` + `EpisodeList` +
        # `GET /api/titles/{id}/episodes` shipped complete and unreachable.
        #
        # Reported, not hard: a contract typo should not wedge a run, and the message names the
        # fix precisely enough to act on.
        if "?" in route or "#" in route:
            _base_913b = route.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
            missing.append(
                f"route `{route}` carries a query/fragment and can NEVER match — React Router "
                f"matches the pathname only. Register the page at `{_base_913b}` and open this "
                f"state from that page (it is a STATE of `{_base_913b}`, not a second route).")
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
        # #912: the wildcard standing in for a path param used to be `[^/'"`\s)]*` — it excluded
        # quotes, whitespace and `)`. That matches `${postId}` and `'+id+'` and rejects the
        # SAFEST spelling of the same call:
        #
        #     '/api/titles/' + encodeURIComponent(id) + '/episodes'
        #                    ^^^^^^^^^^^^^^^^^^^^^^^^^^ quotes, spaces AND parens
        #
        # r153 declared `/api/titles/{id}/episodes`, `services/api.js:200` calls it exactly that
        # way, and the audit reported *"never referenced in frontend src"*. Measured over the
        # corpus: **136 of 2476 declared API references (5.5%) are false** — `/api/genres/{id}/
        # titles` and `/api/titles/{id}/rating` the recurring pair, both written with a
        # `' + var + '` concatenation.
        #
        # A soft miss does not block, but it feeds `pages_pending` and the remediation prompt, so
        # the lane is told to wire a call it already wrote — the churn class #910b measures. The
        # honest expression of "one path segment, however it is spelled" is "anything but a
        # slash", bounded so a pathological line cannot backtrack.
        pat = r"[^/\n]{0,80}".join(re.escape(s) for s in segs).rstrip("/")
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
    if comp_file_text and not _as_component_1077:
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
    if route and apis and not _as_component_1077:
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


# #820: a string literal immediately followed by `+` is the PREFIX of a concatenation, not the
# whole nav target. `navigate('/watch/' + tid)` is correctly parameterised code; the extractor
# captured `/watch/` and stopped at the closing quote, so it was reported as "a parameterised
# route with an EMPTY parameter" — a defect that does not exist and that the lane cannot fix,
# because every correct spelling produces the same capture.
#
# r151 died of this. It aborted STUCK after 75 minutes and 2 coordination ticks with:
#     nav link `/title/` (HoverPreviewCard.jsx) is a parameterised route with an EMPTY parameter
#     nav link `/watch/` (ContinueWatchingRail.jsx) ...
# Both files are lane-authored and both lines read `navigate('/title/' + tid)`. The abort message
# offered two hypotheses — a lane-phase desync, or "a framework artifact regenerated every cycle"
# — and the truth was neither: an unsatisfiable expectation, the #566z class, where the remedy
# the gate demands cannot exist.
#
# The template-literal spellings were already excluded by the character class; `+` was not.
_CONCAT_AFTER_820 = re.compile(r"\s*\+")


def _is_concat_prefix_820(text: str, end: int) -> bool:
    """True when the literal ending at ``end`` is followed by ``+`` — i.e. the id IS supplied."""
    return bool(_CONCAT_AFTER_820.match(text, end))

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


def is_empty_param_prefix_690(target: str, declared_routes: Any) -> bool:
    """#690's test, extracted so the two consumers cannot drift — see #764.

    True when `target` is a parameterised route whose PARAMETER came out empty:
    `/watch/` where `/watch/:titleId` is declared and wired. The route is fine; the template
    interpolated an undefined id. It is NOT a routing defect and must not be treated as one.

    #690 taught the MESSAGE path this. `repair_dead_nav_links` (#493) re-implemented the same
    classification by hand — its docstring says "Classification mirrors
    dead_nav_link_remediation" — and never learned it, so it repointed `/watch/` at whatever
    route shared a token, MUTATING the source. r149: `/watch/ -> /tenants` and `/title/ ->
    /tenants` across four components of a video app. One predicate, two callers, from now on.
    """
    raw = str(target or "").split("?", 1)[0].split("#", 1)[0]
    if not raw.endswith("/") or len(raw) <= 1:
        return False
    return any(d.startswith(raw) and ":" in d[len(raw):].split("/", 1)[0]
               for d in (declared_routes or set()))


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
    if is_empty_param_prefix_690(target, declared_pages):   # #764: one predicate, two callers
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

        # to="/path" | to='/path' | navigate("/path") | navigate('/path') | href="/path"
        #
        # #1165: `href` was missing, and a plain <a href> is a dead control exactly the
        # way a <Link to> is — it just fails LOUDER, with a full page load onto the SPA's
        # catch-all. netflix-local-r13 shipped `<a href="/home">Home</a>` in
        # NewAndPopularPage while App.jsx declares no `/home` route, and this detector —
        # which exists for precisely that defect (#238) — logged nothing all run.
        pat = re.compile(
            r"""(?:\bto\s*=\s*|\bnavigate\s*\(\s*|\bhref\s*=\s*)["'](/[^"'{}$]*)["']""")
        # An `href` can also point at a STATIC FILE, which is not a route and must not be
        # reported as a dead one. `to=`/`navigate()` never do, so this only narrows the
        # newly-admitted spelling.
        _ASSET_1165 = ("/assets/", "/static/", "/public/", "/media/", "/img/", "/images/",
                       "/fonts/", "/favicon")
        seen: set = set()
        for jsx in sorted(src.rglob("*.jsx")):
            if jsx.name == "App.jsx":
                continue
            try:
                text = jsx.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in pat.finditer(text):
                _t1165 = m.group(1)
                if _t1165.startswith(_ASSET_1165) or re.search(r"\.[A-Za-z0-9]{2,5}$", _t1165):
                    continue   # #1165: a file, not a route
                target = m.group(1).strip()
                if _is_concat_prefix_820(text, m.end()):
                    continue          # `navigate('/watch/' + id)` — the id is supplied
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
    except Exception as _exc_1153:
        # #1153: `[]` from here is read as "no dead nav links" and the gate passes.
        # A blanket except wrapping the WHOLE scan means one unreadable JSX file
        # silently converts every remaining page into a clean verdict. Report it
        # through #790's channel so the release records the axis as unverified
        # instead of as passed. Behaviour is unchanged -- still permissive.
        try:
            from .delivery_gate import _swallowed_790
            _swallowed_790("dead_nav_link_blockers", _exc_1153,
                           "[] = no dead nav links")
        except Exception:
            pass
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
    except Exception as exc:
        _scan_truncated_791("routed_fallback_page_blockers", exc, len(blockers))
        return blockers
    return blockers


# #1090 — REGISTER WHAT YOU MANDATE. `agents_config.yaml` gates the frontend lane's finish on
# `app/frontend/src/components/TenantPicker.jsx` existing ("mandatory auth/tenancy UI"),
# `backend_skeleton` mounts `GET /api/v1/tenants` for it BY NAME ("the login template's
# TenantPicker calls it on MOUNT"), and the prompt has LoginPage embed `<TenantPicker/>`.
# Three places mandate it and none checks the outcome: across the delivered corpus 63 apps
# carry the file and 39 (62%) never mount it, so the backend provisions an endpoint for a
# picker the app does not show. #1089 added the check that catches exactly this, but it is
# registry-driven and TenantPicker is registered in 0 of 63 runs — so with a record present,
# an existing SOFT finding does the work and nothing new can wedge a run.
#
# ONLY the picker, not the LoginPage in the same YAML group: the two are mandated as FILES but
# differ in KIND. LoginPage is a routed page (every `/login` in the corpus renders one), and
# registering a page as a component is the mis-declaration #1087 had to undo.
_MANDATED_UI_COMPONENTS_1090 = ("TenantPicker",)


def register_mandated_ui_components_1090(output_dir, registryhub) -> List[str]:
    """Register each mandated component whose file exists and that nothing has registered yet.

    Returns the names newly registered. Never raises and never overwrites an existing record —
    a lane that registered it with its own component name keeps that."""
    if registryhub is None:
        return []
    out: List[str] = []
    try:
        src = Path(output_dir) / "app" / "frontend" / "src"
        existing = set((registryhub.list_ui_components() or {}).keys())
        for comp in _MANDATED_UI_COMPONENTS_1090:
            if not any((src / "components" / f"{comp}{ext}").exists()
                       for ext in (".jsx", ".tsx")):
                continue
            name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", comp).lower()
            if name in existing:
                continue
            registryhub.register_ui_component(
                name=name, component=comp, agent="orchestrator",
                mandated_by="agents_config.required_files#1090")
            out.append(name)
    except Exception:
        return out
    return out


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
    ok, missing = audit_ui_page(frontend_src, page_like, _src_cache=_src_cache)

    # #1089 — AND SOMETHING HAS TO RENDER IT. The three checks above are file presence, apis
    # referenced, and no dead controls in its own file: a component whose file exists and
    # whose apis are called from a service module flipped to `implemented` while no page ever
    # mounted it. Measured over the 67 delivered frontends, 144 of the 1003 registered
    # components whose file EXISTS are never rendered — no `<Name>` anywhere in src (LoginForm
    # 8 runs, SignupForm 7, FooterLinks 6, MessagesDock/SideNavigation/PostDetailModal/TopBar
    # 4 each). Dead UI, which is the one thing the standing rule about UI forbids outright.
    #
    # SOFT on purpose. This verdict flips a component between `implemented` and `defined` and
    # does not reach the delivery gate (`components_implemented` appears nowhere in
    # delivery_gate / deliverability), and the wording stays clear of _HARD_MISS_MARKERS so it
    # cannot become a blocker by accident. The point is to stop telling the lane a component
    # is finished when nothing shows it — not to wedge a run on it.
    _name_1089 = str(comp.get("component") or "").strip()
    if _name_1089 and not _component_is_rendered_1089(_name_1089, frontend_src, _src_cache):
        missing = list(missing) + [
            f"component `{_name_1089}` is never rendered — no `<{_name_1089}>` anywhere in "
            f"src. A component nothing mounts is dead UI: render it from the page that owns "
            f"it, or drop the declaration."]
        ok = False
    return ok, missing


def _component_is_rendered_1089(name: str, frontend_src: Path,
                                src_cache: Optional[Dict[str, str]] = None) -> bool:
    """Is ``name`` mounted anywhere in the tree — JSX or ``createElement``?

    Its own file counts: a self-recursive component (a comment tree, a nested menu) renders
    itself and is otherwise indistinguishable here, and false-flagging one costs more than
    the vanishing case of a component that only ever renders itself."""
    try:
        if src_cache:
            text = "\n".join(src_cache.values())
        else:
            parts = []
            for f in list(frontend_src.rglob("*.jsx")) + list(frontend_src.rglob("*.js")):
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
            text = "\n".join(parts)
        esc = re.escape(name)
        return bool(re.search(r"<\s*" + esc + r"[\s/>]", text)
                    or re.search(r"createElement\s*\(\s*" + esc + r"\b", text))
    except Exception:
        return True    # never fail a component because the probe could not look


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
            # #909: the rollup above asks whether each declared component EXISTS. Nothing has
            # ever asked whether the delivered page USES it — and mostly it does not.
            #
            #     components authored across 131 runs        1761
            #     ★ never reachable from ANY page            1239   70%
            #     declared component references in ui_pages  1431
            #     ★ reachable from the page the record names  479   33%
            #     ★ pages rendering ZERO of their own          246   45%
            #
            # r153: 28 of 34 components orphaned; 11 of 12 pages render none of what they
            # declare. `browse_home_page` claims HeroBillboard + PosterRail + PosterCard +
            # TitleDetailModal and the shipped file imports only React. The lane builds a
            # component library, a framework page writer (the #221 projector, or the auth/landing
            # overwrite) replaces the page with generic inline markup, and the registry keeps
            # describing the page the lane meant to ship. `player_page` — 4 declared components,
            # all orphaned — scored 0.35 on the visual gate.
            #
            # ★ REPORTED, never enforced, and deliberately kept OUT of `ok`: feeding it into
            # `missing` would flip the page to `defined` on the next tick (#891's rule — the run
            # is not wrong here, the description is), and re-projecting is a separate decision
            # with its own risk. This only ends the silence.
            # #918: CAN A USER REACH THIS PAGE'S DECLARED APIs FROM THIS PAGE?
            #
            # The sibling question to #909, and the one that catches the case #909 alone does not
            # name. r153 registers `title_detail` with five APIs including
            # `GET /api/titles/{id}/episodes`; the endpoint exists, `services/api.js` calls it,
            # `EpisodeList` renders it — and the page the record points at is the #910 projection,
            # a 166-line file importing nothing but React. Every existing check passes: the API is
            # implemented, the component is implemented, and #912 finds the call SOMEWHERE in src.
            # None of them asks whether THIS page can make it.
            #
            #     corpus: 1534 pages declare an API; 735 of 2472 declared references (30%) are
            #     unreachable from the page's own closure, and 696 pages (45%) are ISLANDS whose
            #     closure is the file itself — the same 45% #909 measures from the other side.
            #
            # Reported only, total-miss only, out of `ok` — same disposition as #909: a page
            # reaching 2 of 3 is a partial, and folding this into `ok` would flip half the pages
            # to `defined` every tick.
            _apis_918 = [str(a).split()[-1] for a in (page.get("apis_used") or []) if "/" in str(a)]
            if _apis_918:
                _reach = _page_closure_918(page, cache)
                _blob = "\n".join(_reach.values())
                _unreachable = []
                for _a in _apis_918:
                    _segs = re.split(r"\{[^}]+\}|:[A-Za-z_]\w*", _a)
                    _pat = r"[^/\n]{0,80}".join(re.escape(s) for s in _segs).rstrip("/")
                    if _pat and not re.search(_pat, _blob):
                        _unreachable.append(_a)
                if _unreachable and len(_unreachable) == len(_apis_918):
                    out.setdefault("api_unreachable", {})[name] = _unreachable
                    try:
                        if not _say_once_925("api", name, _unreachable):
                            raise _Skip925
                        _LOG_791.warning(
                            "API UNREACHABLE FROM ITS PAGE: ui_page `%s` declares %d API(s) and "
                            "NONE is reachable from the page's own import/render closure (%d "
                            "file(s)): %s. The call may exist elsewhere in src — a user on this "
                            "page still cannot make it (#918).",
                            name, len(_unreachable), len(_reach),
                            join_capped(_unreachable, len(_unreachable), cap=4, sep=", "))
                    except Exception:
                        pass
            _decl_909 = [str(c) for c in (page.get("components") or []) if str(c) in comp_status]
            if _decl_909:
                _used_909 = _rendered_components_909(frontend_src, page, cache)
                _orphaned = [c for c in _decl_909 if c not in _used_909]
                if len(_orphaned) == len(_decl_909):
                    out.setdefault("component_drift", {})[name] = _orphaned
                    try:
                        if not _say_once_925("drift", name, _orphaned):
                            raise _Skip925
                        _LOG_791.warning(
                            "COMPONENT DRIFT: ui_page `%s` declares %d component(s) and the "
                            "delivered page renders NONE of them (%s). The contract describes a "
                            "page that was not shipped (#909).",
                            name, len(_orphaned),
                            join_capped(_orphaned, len(_orphaned), cap=6, sep=", "))
                    except Exception:
                        pass
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
            #
            # ★ #906: the last line of that reasoning used to read *"A genuinely-declared page
            # always carries a '/'-anchored route"*, and the corpus says otherwise —
            # `register_ui_page(route: str = "")` defaults to empty and **644 records across 153
            # runs are real pages under `src/pages/` with no route** (#905). They were skipped
            # here too, so "declared but unusable" never looked at them. Use the shared test:
            # a component file stays skipped (#47's class, and #243's), a page file does not.
            # Measured before changing: including them yields ZERO hard blockers across 153 runs
            # (the first measurement said one; it was an artifact of handing `audit_ui_page` an
            # EMPTY `_src_cache`, which that function treats as the whole tree — item 251).
            if not isinstance(page, dict) or not _is_navigable_page(page):
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
        # #906: same predicate, same reason — a map surface registered without a route was
        # exempt from the fake-map check entirely. Not measurable on this corpus (netflix has no
        # map pages), which is exactly why it should not stay divergent from the line above.
        _map_pages = [n for n, p in pages.items()
                      if isinstance(p, dict)
                      and _is_navigable_page(p)
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
    _span_truncated_810("_balanced_call_span", 600)
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
    except Exception as exc:
        _scan_truncated_791("bare_authed_fetch_blockers", exc, len(blockers))
        return blockers
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
# #992: verbs and control words a UI puts ON a control. Not data, never fabricated —
# rewriting them to "—" blanks the button and fails the walk that looks for them.
_UI_ACTION_LABELS_992 = frozenset({
    "continue", "submit", "cancel", "save", "delete", "remove", "edit", "close", "back",
    "next", "previous", "prev", "confirm", "apply", "reset", "clear", "search", "filter",
    "sort", "login", "log in", "logout", "log out", "signin", "sign in", "signup",
    "sign up", "register", "subscribe", "send", "share", "copy", "download", "upload",
    "retry", "refresh", "reload", "more", "less", "show", "hide", "open", "view",
    "create", "add", "update", "select", "choose", "browse", "play", "pause", "resume",
    "skip", "done", "finish", "start", "stop", "yes", "no", "ok", "okay", "accept",
    "decline", "dismiss", "settings", "profile", "account", "home", "menu", "help",
})

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
    # #1012: measured against the corpus — 228 literals the heal actually considers, 6
    # rewritten, and three of those six were wrong. `Nothing here yet.` and `Unable to load
    # title.` are the honest empty/error states this heal exists to PRODUCE, and it was
    # turning them into '—'. Found by feeding the guard its real input shape (item 435's
    # method); the earlier sweep that fed it whole page files reported a meaningless 21.
    "nothing here", "nothing to show", "nothing yet", "unable to", "cannot load",
    "can't load", "try again", "check back",
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
    # #992: a UI ACTION LABEL is not fabricated data. The proper-noun rule below fires on
    # `Continue` / `Submit` / `Cancel` / `Search` — uppercase, alphabetic, >=4 chars — and
    # r161 rewrote `? 'Continue' : mode` to `? '—' : mode`, putting a dash on the button.
    # 72 firings in that run, and a browser walk hunting for "Continue" cannot find a dash,
    # so the heal that exists to remove fake DATA was breaking real UI COPY and failing the
    # very flows it was meant to keep honest.
    #
    # The distinction is what the literal DENOTES: `Hotel` standing in for a missing name is
    # invented content; `Continue` on a button is the control's own text, present whether or
    # not any record exists behind it.
    if low in _UI_ACTION_LABELS_992:
        return False
    # #1012: a utility-class string is styling, not content. The corpus produced
    # `item.size || 'w-8 h-8'` — rewriting that to '—' feeds a dash into className and the
    # element loses its dimensions. Tailwind utilities are the common case: short tokens,
    # every one matching a size/spacing/colour/layout shape, no prose.
    _toks = t.split()
    if _toks and len(_toks) <= 6 and all(
            re.fullmatch(r"[a-z]+(-[a-z0-9./\[\]%]+)+|[a-z]{1,3}-\d+|flex|grid|block|hidden",
                         _x) for _x in _toks):
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
    except Exception as _e1202af:
        # #1202af: this feeds the #175 delivery blocker, so an empty return reads as "no
        # invented values" whether it checked or died. The wrapper's #792 announcement only
        # fires when the CALL raises; an exception swallowed here never reaches it. Same
        # default, same behaviour — only the silence is gone.
        from .message_format import warn_once_1201
        warn_once_1201("invented_field_fallback_blockers",
                       "the invented-field scan (#175) — displayed values are NOT known real",
                       _e1202af)
        return []
    seen = set()
    blockers: List[str] = []
    try:
        files = list(src.rglob("*.jsx")) + list(src.rglob("*.tsx"))
    except Exception as _e1202af:
        # #1202af: this feeds the #175 delivery blocker, so an empty return reads as "no
        # invented values" whether it checked or died. The wrapper's #792 announcement only
        # fires when the CALL raises; an exception swallowed here never reaches it. Same
        # default, same behaviour — only the silence is gone.
        from .message_format import warn_once_1201
        warn_once_1201("invented_field_fallback_blockers",
                       "the invented-field scan (#175) — displayed values are NOT known real",
                       _e1202af)
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
# #705 RE-MEASURED 2026-08-14 at full corpus scale, by running this detector over every kept run
# that has both a frontend and ui_pages: **112 of 136 (82%)**, against the 32/45 (71%) above.
# The premise has not gone stale in direction — it got stronger — and the distribution is new:
#
#     max group size   2:10  3:19  4:27  5:28  6:23  7:4  8:1   runs
#
# so the MEDIAN affected run has five routes rendering the same list, and the worst has eight.
# That reinforces the calibration call below rather than overturning it: at 82% a blocker would
# wedge more runs than the 71% this decision was made on, not fewer. It also raises the value of
# reporting it (#700) — this is not a rare defect, it is the normal state of a delivered app.
#
# Deliberately NOT wired as a delivery blocker. At 32/45 it would wedge nearly every run, and
# whether "six identical pages" should block or merely be reported is a calibration decision,
# not a measurement — the same call as the 0.65 fidelity bar. ~~Also worth knowing before anyone
# "fixes" it by inventing filters: the seed gives every title `kind='standard'`, so a
# route-derived filter would return everything or nothing.~~
#
# #708 — THAT LAST SENTENCE IS STALE, and it is the one that discourages fixing the CAUSE.
# The delivered app ships two seed files and both discriminate:
#
#     app/backend/seed_dataset.json   60 titles   kind: movie 28 / series 32   (framework-owned
#                                                 REAL data; the lane cannot clobber it)
#     app/backend/seed_data.json      15 titles   kind: series 8 / movie 7
#
# with real genres in both (Horror/Comedy/Action & Adventure/Animation/…). `kind='standard'`
# survives only in the framework's 6-row fallback seed, which is not the shipped catalog — I
# measured that fallback first and nearly repeated the stale claim from it.
#
# So a route-derived filter would NOT "return everything or nothing": /movies -> kind=movie (28),
# /shows -> kind=series (32), and the genre pages have `/api/genres/{id}/titles` already in the
# contract. Whoever picks this up next can fix the cause rather than only reporting it — the
# reason recorded for not doing so no longer holds. The calibration question above is untouched;
# only the technical objection is withdrawn.
# capture the char AFTER the path too: a fetch that continues into `{`, `?`, `$` or `+` is
# PARAMETERISED and therefore differentiates the page. Matching only the literal prefix would
# make `/api/titles/{id}` and `/api/titles?kind=movie` both look like a bare `/api/titles`.
_PAGE_FETCH_RE_615 = re.compile(r"""['"`](/api/[A-Za-z0-9_\-/]+)([^'"`]?)""")


def _route_tokens_728(text: Any) -> set:
    """Meaningful path words, crudely stemmed. `genre` and `genres` must be the same token —
    the first version of this check did not stem, and so missed the very case that motivated it:
    `/browse/genre/:genreId` against `/api/genres/{id}/titles` shares nothing until the plural
    is folded, and the detector reported a clean zero on the run where the bug shipped."""
    import re as _re
    out = set()
    for t in _re.split(r"[/:{}\-_]+", str(text or "").lower()):
        if len(t) > 2 and t not in ("api", "v1", "get", "post", "put", "delete", "the"):
            out.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return out


def crossed_page_endpoints_728(ui_pages: Any, endpoints: Any) -> List[Dict[str, Any]]:
    """#728: pages calling ANOTHER page's endpoint while their own sits implemented and unused.

    r148 shipped `GenreCategoryPage.jsx` fetching `/api/my-list`: click any genre, see your
    watchlist. `GET /api/genres/{id}/titles` was registered AND implemented, and nothing used it.
    Nothing caught it because the page DECLARED `apis_used: ['GET /api/my-list']` too — code and
    declaration agree, so every consistency audit passes. They agree on the wrong thing.

    Across the runs it is a rotation rather than a slip:

        r146   genre_category -> /api/my-list, my_list -> /api/titles,
               title_detail -> /api/genres          three pages, each holding the next one's
        r147   none                                 same framework, same prompt — so it is
        r148   genre_category -> /api/my-list,      avoidable, not inherent
               title_detail -> /api/genres

    The test needs no product standard, which is why it is wired rather than filed: a page whose
    declared APIs share NO token with its own route, while an implemented endpoint DOES share
    one, is wrong under any reading. That is narrower than "every implemented endpoint should
    have a UI caller" — 12 of 16 endpoints are unused in r146 and r148, and whether that is a
    defect is a judgement about product scope, deliberately not made here.

    Report-only, like #700 beside which it is emitted.
    """
    out: List[Dict[str, Any]] = []
    try:
        pages = ui_pages if isinstance(ui_pages, dict) else {}
        eps = endpoints if isinstance(endpoints, dict) else {}
        impl = []
        for k, v in eps.items():
            if str(k).startswith("_") or not isinstance(v, dict):
                continue
            if str(v.get("status")) != "implemented":
                continue
            impl.append((f"{v.get('method')} {v.get('path')}", _route_tokens_728(v.get("path"))))
        for k, v in pages.items():
            if str(k).startswith("_") or not isinstance(v, dict):
                continue
            route = v.get("route")
            used = [str(a) for a in (v.get("apis_used") or []) if str(a).strip()]
            rt = _route_tokens_728(route)
            if not rt or not used:
                continue
            if any(_route_tokens_728(a) & rt for a in used):
                continue
            # Rank by how much of the route the endpoint accounts for, then by brevity. Sorting
            # alphabetically named the WORSE candidate: for `/title/:id` it put
            # `GET /api/genres/{id}/titles` ahead of `GET /api/titles/{id}`, both of which match
            # on "title". A suggestion that points at the wrong endpoint is worse than none.
            better = sorted(((len(et & rt), -len(e), e) for e, et in impl if et & rt),
                            reverse=True)
            if better:
                out.append({"page": v.get("name") or k, "route": str(route),
                            "declares": used, "unused_match": [e for _, _, e in better][:3]})
    except Exception:
        return []
    return out


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


# --- #1202ai: a prop the component never declares is silently dropped -------------------
# React does not complain about an attribute a component does not destructure, so this class
# of break has NO runtime symptom: no console error, no failed request, no 404. Every gate
# this repo owns stays green while a feature quietly does nothing.
#
# Measured over the 117 corpus environments, counting only cases where the prop name appears
# NOWHERE in the component's own source file (so it cannot be read off `props` or forwarded):
#
#     232 occurrences in 51 of 117 runs (44%)
#
#     <ResultsSidebar hoveredPlaceId onHover>  declares {error, isPharmacy, loading}
#                                              -> map/list hover linkage is dead
#     <PostHeader createdAt>                   declares {user}      -> no timestamp
#     <PostHeader onFollowToggle>              declares {isFollowed, setIsFollowed, user}
#     <LoginForm setToken>                     declares {setIsRegister} -> token never stored
#     <NetflixChrome title subtitle>  (r32)    declares {children, activeLabel, menuOpen}
#
# REPORTS, does not block. The inference is static and this repo has been burned by static
# inference before — #1199 was downgraded from rewriting `apis_used` to reporting it after
# false rewrites on tiktok/googlemaps/instagram. Components taking `props` wholesale, using a
# rest element, or wrapped in memo/forwardRef/HOC are excluded rather than guessed at.
_PROP_DECL_FN_1202AI = re.compile(r"function\s+(\w+)\s*\(\s*\{([^}]*)\}")
_PROP_DECL_ARROW_1202AI = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*(?:React\.)?(?:memo|forwardRef)?\(?\s*\(?\s*\{([^}]*)\}", re.S)
_PROP_OPAQUE_1202AI = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\w+\.)?(?:memo|forwardRef|withRouter|connect|styled)[\s(]"
    r"|(?:const|let|var)\s+(\w+)\s*=\s*\(?\s*props\s*\)?\s*=>"
    r"|function\s+(\w+)\s*\(\s*props\s*\)")
_PROP_USE_1202AI = re.compile(r"<([A-Z]\w*)\s+([^/>]{0,300})")
_PROP_ATTR_1202AI = re.compile(r"(\w+)\s*=")
_PROP_SAFE_1202AI = frozenset({
    "key", "ref", "className", "style", "children", "data-testid", "id", "onClick",
    "aria-label"})


def dropped_prop_findings_1202ai(frontend_src: Any, limit: int = 12) -> List[str]:
    """Props passed to a component that never declares or mentions them. Never raises."""
    out: List[str] = []
    try:
        root = Path(frontend_src)
        if not root.is_dir():
            return []
        files = [f for f in list(root.rglob("*.jsx")) + list(root.rglob("*.tsx"))
                 if "node_modules" not in f.parts]
        # #1202ak: key declarations by (FILE, name), not by name alone. r32 has two
        # components called `TitleCard` — `TitleGrid.jsx` declares {title, rank} and
        # `NetflixUI.jsx` declares {title, rank, onOpen, showLabel} — and a name-keyed map
        # judged one file's call site against the other file's declaration, reporting
        # `onOpen` as dropped when the component it actually resolves to declares and uses
        # it. Resolution now follows the caller's own import, and a component that cannot be
        # resolved to a single declaration is skipped rather than guessed at.
        decls: Dict[Any, set] = {}
        bodies: Dict[Any, str] = {}
        by_name: Dict[str, list] = {}
        opaque: set = set()
        texts: Dict[Any, str] = {}
        for f in files[:400]:
            try:
                texts[f] = f.read_text(encoding="utf-8")
            except Exception:
                continue
            t = texts[f]
            for m in _PROP_OPAQUE_1202AI.finditer(t):
                opaque.add(m.group(1) or m.group(2) or m.group(3))
            for rx in (_PROP_DECL_FN_1202AI, _PROP_DECL_ARROW_1202AI):
                for m in rx.finditer(t):
                    if "..." in m.group(2):
                        opaque.add(m.group(1))
                        continue
                    props = {p.split("=")[0].split(":")[0].strip()
                             for p in m.group(2).split(",") if p.strip()}
                    if props:
                        key = (f, m.group(1))
                        decls.setdefault(key, props)
                        bodies.setdefault(key, t)
                        by_name.setdefault(m.group(1), []).append(key)
        seen = set()
        _imp = re.compile(r"""import\s+(?:\{[^}]*\}|\w+)[^'"]*from\s+['"](\.[^'"]+)['"]""")
        for f, t in texts.items():
            # Which file does each name in THIS file come from? A relative import wins; a
            # local declaration in the same file wins over that.
            local = {n: (f, n) for (ff, n) in decls if ff == f}
            imported = {}
            for m in _imp.finditer(t):
                for suf in ("", ".jsx", ".js", ".tsx"):
                    cand = (f.parent / (m.group(1) + suf)).resolve()
                    hits = [k for k in decls if k[0].resolve() == cand] if cand.exists() else []
                    for k in hits:
                        imported.setdefault(k[1], k)
                    if hits:
                        break
            for m in _PROP_USE_1202AI.finditer(t):
                comp = m.group(1)
                if comp in opaque:
                    continue
                key = local.get(comp) or imported.get(comp)
                if key is None:
                    # unresolved, or the name exists in several files with no import to
                    # disambiguate -> say nothing rather than guess
                    continue
                passed = set(_PROP_ATTR_1202AI.findall(m.group(2)))
                for attr in sorted(passed - decls[key] - _PROP_SAFE_1202AI):
                    if re.search(r"\b" + re.escape(attr) + r"\b", bodies[key]):
                        continue          # mentioned somewhere in the component -> not dropped
                    dedupe = (comp, attr)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    out.append(
                        "%s: <%s %s={...}> — %s never declares or mentions `%s`, so React "
                        "drops it silently and whatever it was for does nothing. The "
                        "component takes {%s}."
                        % (f.name, comp, attr, comp, attr, ", ".join(sorted(decls[key])[:6])))
                    if len(out) >= limit:
                        return out
    except Exception as _e1202ai:
        from .message_format import warn_once_1201
        warn_once_1201("dropped_prop_findings_1202ai",
                       "the dropped-prop scan (#1202ai) — passed props are NOT known received",
                       _e1202ai)
        return []
    return out


# #1202bg: a handler that is syntactically present and does nothing. `onClick={() => {}}`
# renders a control that looks live, responds to hover, and answers a click with silence.
_NOOP_HANDLER_1202BG = re.compile(
    r"""on[A-Z]\w+=\{\s*(?:\(\s*[\w,\s]*\)|\w+)\s*=>\s*(?:\{\s*\}|console\.\w+\([^()]*\))\s*\}"""
    r"""|on[A-Z]\w+=\{\s*function\s*\([^)]*\)\s*\{\s*\}\s*\}""")


def noop_handler_findings_1202bg(frontend_src: Any, limit: int = 12) -> List[str]:
    """Event handlers wired to an empty body — controls that cannot do anything. (#1202bg)

    Measured across the corpus: 24 of 117 delivered frontends carry at least one. The
    clearest is tiktok-web-r91's login modal, where EVERY option row is wired this way —

        <LoginOptionRow icon={<Ic.QR />}       label="Use QR code"            onClick={() => {}} />
        <LoginOptionRow icon={<Ic.Google />}   label="Continue with Google"   onClick={() => {}} />
        <LoginOptionRow icon={<Ic.Apple />}    label="Continue with Apple"    onClick={() => {}} />

    — five sign-in routes that look available and answer with nothing. No existing check
    sees this: the element is present, the prop is present, the page renders, so
    dead-nav, fallback-page, bare-fetch and invented-field all pass it. It is the shape
    of "everything renders and nothing works".

    A console.log-only body counts too: it is a debugging stub that reached delivery.

    None of the three current-era runs (r30/r31/r32) carries one, so this may already be
    rarer than the corpus average — which costs nothing when clean and catches it if it
    returns. Never raises.
    """
    out: List[str] = []
    try:
        root = Path(frontend_src)
        if not root.is_dir():
            return out
        for f in sorted(root.rglob("*")):
            if f.suffix not in (".jsx", ".tsx") or "node_modules" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in _NOOP_HANDLER_1202BG.finditer(text):
                _h = " ".join(m.group(0).split())
                # #1034: declare the cut rather than showing a slice as the whole handler.
                out.append("%s: %s" % (
                    f.name, _h[:90] + ("…" if len(_h) > 90 else "")))
                if len(out) >= limit:
                    return out
    except Exception as _exc:
        from .message_format import warn_once_1201
        warn_once_1201("noop_handler_findings_1202bg",
                       "the scan for event handlers with an empty body", _exc)
    return out


# ---------------------------------------------------------------------------
# #1202cj — an authenticated page that shares nothing with its siblings.
# ---------------------------------------------------------------------------
_AUTH_ROUTE_1202CJ = re.compile(r"element=\{<RequireAuth>\s*<(\w+)")
_SHARED_IMPORT_1202CJ = re.compile(
    r"^import\s+(?:\{[^}]*\}|\w+)(?:\s*,\s*\{[^}]*\})?\s+from\s+'\.\.?/components/", re.M)


def orphan_auth_page_findings_1202cj(frontend_src: Any, limit: int = 12) -> List[str]:
    """Routed, authenticated pages that import NO shared component while their siblings do.

    The visual judge's most repeated component-level deviation, across 31 netflix runs and
    333 screen judgments, is some form of "implementation lacks the logo and full navigation
    bar" — and `components` is the weakest dimension of the seven (0.478 mean; `color`, which
    design-prep measures deterministically, is the strongest at 0.676). Those two facts meet
    in the code: in r35 `BrowseHomePage` imports NetflixHeader and scores well, while
    `GamesPage` and `NewAndPopularPage` import nothing at all and score 0.50 and 0.495. A
    page that shares nothing re-invents the chrome, and usually omits it.

    Measured across the corpus: 13 of 130 routed authenticated pages (10%) import no shared
    component, clustered into a few runs rather than spread evenly.

    DOMAIN-AGNOSTIC by construction. Two earlier versions of this scan were wrong in
    opposite directions and both are the reason it is written this way:

      * matching component NAMES (`NavBar|Header|Shell`) reported 49%, because instagram
        calls its chrome `NavRail`. Names are lane variance; this counts IMPORTS instead.
      * requiring the shared component to be used by a MAJORITY of pages reported 9%,
        because it silently skipped every app whose chrome is used by a minority — which is
        exactly the app with the problem. r35 was excluded by that filter.

    So the predicate is only: this page imports nothing from components/, and at least one
    sibling auth page does. No name, no threshold, no app knowledge.

    REPORTS, does not block — the same disposition as #1202ai, and for the same reason: a
    page legitimately owns its whole surface sometimes (a full-screen player is the honest
    example, and it is why this names the siblings rather than asserting a rule).
    """
    out: List[str] = []
    try:
        src = Path(frontend_src)
        app = src / "App.jsx"
        if not app.is_file():
            return out
        try:
            routes = app.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return out
        bodies: Dict[str, str] = {}
        for comp in _AUTH_ROUTE_1202CJ.findall(routes):
            f = src / "pages" / f"{comp}.jsx"
            if not f.is_file():
                continue
            try:
                bodies[comp] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
        if len(bodies) < 3:
            return out
        shares = {c: bool(_SHARED_IMPORT_1202CJ.search(b)) for c, b in bodies.items()}
        if not any(shares.values()):
            # No page in this app shares anything — that is a different (whole-app) shape and
            # naming one page for it would be arbitrary.
            return out
        for comp in sorted(c for c, ok in shares.items() if not ok):
            out.append(
                f"{comp}.jsx is routed behind RequireAuth and imports nothing from "
                f"components/, while {sum(1 for v in shares.values() if v)} sibling auth "
                f"page(s) do — it will re-invent (and usually omit) the shared chrome")
            if len(out) >= limit:
                break
    except Exception:
        return out
    return out
