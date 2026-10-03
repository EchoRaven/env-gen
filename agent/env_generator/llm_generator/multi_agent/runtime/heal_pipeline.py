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

import re
import time
from typing import Any, List

from .message_format import join_capped  # #1034


def _write_py_995(path, text, *, what: str = ""):
    """#995 guard, imported defensively.

    Some modules here are imported STANDALONE by tests (no package context), where a relative
    import raises. The guard degrades to a plain write in that case rather than breaking the
    import — and says so in this docstring rather than pretending it is still checking.
    """
    try:
        from .safe_code_write import write_py_if_still_parses as _w
    except Exception:
        path.write_text(text, encoding="utf-8")  # raw: #995 documented degradation
        return True
    return _w(path, text, what=what)


# #1202td: this module REPAIRS lane files (the seed, page components, App.jsx), so its writes
# belong at the same choke point the three projectors use. #1202cw's ratchet enforced that on a
# hardcoded list of three filenames, and this module was not on it. Imported defensively, for
# the standalone-import case #995 documents just above.
try:
    from .path_routed_workspace import framework_write_1202cw as _fw_write_1202cw
except Exception:   # pragma: no cover - standalone import without package context
    def _fw_write_1202cw(_p, _text, **_kw):
        # `Path` is imported per-function in this module (`from pathlib import Path as _P`),
        # never at module level -- #940's ratchet caught the first version reading a name that
        # is not bound here, which is the class this project keeps paying for.
        from pathlib import Path as _P1202td
        _P1202td(str(_p)).write_text(_text, encoding=_kw.get("encoding", "utf-8"))  # raw: shim
        return True


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


def reconcile_integration_seed(repo_root, logger=None) -> dict:
    """#322 — the backend authors ``app/backend/seed_data.json`` in ITS worktree, but it
    was not reliably reaching the INTEGRATION tree the delivery gate (deliverability_
    check) + the shipped docker image read: integration kept the ``{}`` placeholder that
    ``_ensure_seed_json`` writes, so 'authored seed missing' blocked delivery FOREVER
    even though the lane's seed was a valid populated file (r86 + r91: ~50 tasks; r91
    burned the whole 6h wall-clock on it).

    Called right AFTER the per-tick lane→integration merge: if integration's
    seed_data.json is empty/``{}`` but a lane's worktree has a populated one, copy the
    MOST-populated lane seed onto integration so the gate + the image see the real data.
    NEVER overwrites a non-empty integration seed; best-effort, never raises. Returns
    ``{"reconciled": path, "rows": n}`` or ``{}`` when there is nothing to do."""
    try:
        from pathlib import Path as _P
        import json as _json

        def _rows(p):
            try:
                d = _json.loads(_P(p).read_text(encoding="utf-8"))
            except Exception:
                return 0
            return (sum(len(v) for v in d.values() if isinstance(v, list))
                    if isinstance(d, dict) else 0)

        repo = _P(repo_root)
        integ = repo / "app" / "backend" / "seed_data.json"
        if _rows(integ) > 0:
            return {}                       # integration already has real authored data
        best, best_rows = None, 0
        wt = repo / "worktrees"
        if wt.is_dir():
            for d in sorted(wt.iterdir()):
                cand = d / "app" / "backend" / "seed_data.json"
                r = _rows(cand)
                if r > best_rows:
                    best, best_rows = cand, r
        if best is None or best_rows == 0:
            return {}
        integ.parent.mkdir(parents=True, exist_ok=True)
        _fw_write_1202cw(integ, _P(best).read_text(encoding="utf-8"),
                         clobber_ok="#322: integration must carry the seed the lane "
                                    "authored in its own worktree")
        if logger is not None:
            try:
                logger.warning(
                    "🌱 #322 reconciled integration seed_data.json from %s (%d rows) — the "
                    "authored seed had not reached integration (was empty {}); the delivery "
                    "gate was chronically blocked on 'authored seed missing'.", best, best_rows)
            except Exception:
                pass
        return {"reconciled": str(best), "rows": best_rows}
    except Exception:
        return {}


def _page_referenced_1202ns(src_root, page_filename) -> bool:
    """#1202ns: does any source file under integration's `src/` import this page component?"""
    from pathlib import Path as _P
    stem = _P(str(page_filename)).stem
    pat = re.compile(r"""['"][^'"]*/pages/%s(?:\.[jt]sx?)?['"]""" % re.escape(stem))
    try:
        for f in _P(src_root).rglob("*"):
            if f.suffix not in (".js", ".jsx", ".ts", ".tsx") or "node_modules" in f.parts:
                continue
            if f.name == page_filename and f.parent.name == "pages":
                continue
            try:
                if pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except Exception:
                continue
    except Exception as _e1202ns:
        # unknowable → keep the old restore-on-missing behaviour, and say so (#1202be)
        from .message_format import warn_once_1201
        warn_once_1201("page_referenced_1202ns",
                       "cannot scan integration sources for page imports; a deleted page may be "
                       "restored from a lane worktree", _e1202ns)
        return True
    return False


def reconcile_integration_frontend_pages(repo_root, logger=None) -> dict:
    """#566b (netflix r113 — fail-fast rc=1) — the frontend lane authors a REAL page
    component in ITS worktree, but the integration tree the delivery gate audits
    (deliverability_ui_page_unwired) can still hold the projector STUB / framework-fallback
    for that page until a lane→integration merge lands. Between merges every gate poll
    re-reads the stub and reports the page 'declared but unusable'; if it persists
    FWVAL_STUCK_ABORT_AFTER ticks the run FAIL-FAST aborts (r113: TitleDetailPage was a real
    390-line page in the lane worktree, a stub in integration → STUCK-ABORT ~1s after the
    real page finally flipped app_wired=True).

    Mirror reconcile_integration_seed: when an integration page file is a stub/fallback (or
    missing) but a lane worktree has a REAL version (calls the api client OR wires handlers,
    and is not the framework fallback), copy the real one onto integration BEFORE the audit
    reads. NEVER clobbers a real integration page; best-effort, never raises. Generalizable
    — no product literals; the real-vs-stub decision reuses the frontend_audit predicates.
    Returns ``{"reconciled": [names], "count": n}`` or ``{}`` when there is nothing to do."""
    try:
        from pathlib import Path as _P
        from .frontend_audit import _has_real_api_call, _is_generic_fallback_page
        _PLACEHOLDER = ("this section is being set up", "under construction",
                        "coming soon", "placeholder page", "todo: implement")
        _HANDLERS = ("onSubmit", "onClick", "fetch(", "apiGet", "apiPost",
                     "apiPut", "apiDelete", "axios", "api.", "await api")

        def _read(p):
            try:
                return _P(p).read_text(encoding="utf-8")
            except Exception:
                return None

        def _is_stub(text) -> bool:
            if not text:
                return True                       # missing → treat as stub
            if any(m in text.lower() for m in _PLACEHOLDER):
                return True
            return _is_generic_fallback_page(text)

        def _is_real(text) -> bool:
            if not text or _is_stub(text):
                return False
            return _has_real_api_call(text) or any(t in text for t in _HANDLERS)

        repo = _P(repo_root)
        wt = repo / "worktrees"
        if not wt.is_dir():
            return {}
        integ_pages = repo / "app" / "frontend" / "src" / "pages"
        # best (longest) REAL candidate per page filename across all lane worktrees
        best = {}
        for d in sorted(wt.iterdir()):
            wt_pages = d / "app" / "frontend" / "src" / "pages"
            if not wt_pages.is_dir():
                continue
            for wt_file in sorted(list(wt_pages.glob("*.jsx")) + list(wt_pages.glob("*.tsx"))):
                wt_text = _read(wt_file)
                if not _is_real(wt_text):
                    continue
                cur = best.get(wt_file.name)
                if cur is None or len(wt_text) > len(cur[1]):
                    best[wt_file.name] = (wt_file, wt_text)
        reconciled = []
        src_root = repo / "app" / "frontend" / "src"
        for name, (_wt_file, wt_text) in best.items():
            integ_file = integ_pages / name
            integ_text = _read(integ_file)
            if not _is_stub(integ_text):
                continue                          # integration already real → never clobber
            # #1202ns: MISSING is not STUB. A page absent from integration that nothing in
            # integration imports was DELETED there, not left unmerged — copying a lane
            # worktree's older copy back resurrects it. tiktok-r125 M3: the frontend removed
            # `MessagesPage.jsx` at 10:12 (dead file); its own worktree still held the file, this
            # reconcile — called with no logger on every gate evaluation, so it never said so —
            # wrote it back, framework delivery committed it at 10:18 and 10:33, the coverage
            # audit flagged the dead file again, and the lane was re-dispatched four times
            # between 10:23 and 10:56. A missing page is restored only when integration still
            # references it (the #566b case: a wired page whose component had not merged yet).
            if integ_text is None and not _page_referenced_1202ns(src_root, name):
                continue
            try:
                integ_file.parent.mkdir(parents=True, exist_ok=True)
                _fw_write_1202cw(integ_file, wt_text,
                                 clobber_ok="#566b: restores the lane's real page into "
                                            "integration")
                reconciled.append(name)
            except Exception:
                continue
        if reconciled and logger is not None:
            try:
                logger.warning(
                    "🔀 #566b reconciled %d integration frontend page(s) from lane worktrees "
                    "(stub/fallback in integration, real in lane): %s — the delivery gate was "
                    "reading a stale stub for a page the lane had already built.",
                    len(reconciled), ", ".join(sorted(reconciled)))
            except Exception:
                pass
        return {"reconciled": sorted(reconciled), "count": len(reconciled)} if reconciled else {}
    except Exception:
        return {}


def reconcile_integration_frontend_app_jsx(repo_root, ui_pages, logger=None) -> dict:
    """#566e (netflix r117 — 75-min M1 timeout via ui-page churn): the App.jsx ROUTE analogue of
    #566b (which reconciles page COMPONENTS). The delivery gate audits integration's
    ``<repo>/app/frontend/src/App.jsx`` and hard-blocks on ``route `/x` not wired in App.jsx``. A
    frontend lane's committed App.jsx route edit reaches integration ONLY via
    merge_committed_agent_work, which aborts-on-conflict + SUPERSEDES lane edits to framework-touched
    files — and the framework rewrites App.jsx every heal tick — so a committed route edit can sit
    unmerged across every gate poll → deliverability_ui_page_unwired stays red → re-dispatch churn
    (r117: 96 finishes in ~9 min) → STUCK / no-deliver timeout.

    Deterministically wire every DECLARED ui_page route into the integration App.jsx before the audit
    reads, reusing the additive, idempotent, gate-predicate-sharing injector
    ``frontend_scaffold.project_missing_ui_routes`` (only injects routes the gate would flag as
    unwired; never removes/rewrites a lane route; never raises). Best-effort; byte-identical when every
    declared route is already wired or App.jsx is absent. No product literals. Returns
    ``{"injected": [...], "count": n}`` or ``{}``."""
    try:
        from pathlib import Path as _P
        from .frontend_scaffold import project_missing_ui_routes
        app = _P(repo_root) / "app" / "frontend" / "src" / "App.jsx"
        if not app.is_file():
            return {}
        try:
            text = app.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {}
        new_text, injected = project_missing_ui_routes(text, list(ui_pages or []))
        if injected and new_text != text:
            _fw_write_1202cw(app, new_text,
                             clobber_ok="#566e: injects the routes the lane's own "
                                        "ui_pages declare")
            if logger is not None:
                try:
                    logger.warning(
                        "🔀 #566e wired %d declared route(s) into integration App.jsx (lane route "
                        "committed-but-unmerged or absent): %s — the delivery gate was reading a "
                        "route the declared page needs but App.jsx did not wire.",
                        len(injected), ", ".join(injected))
                except Exception:
                    pass
            return {"injected": injected, "count": len(injected)}
        return {}
    except Exception:
        return {}


# #512 (netflix r84, 2026-08-05, user-surfaced) — DISTRIBUTE REAL SEED MEDIA. The LLM-authored
# seed wired the SAME single image to every catalog row's poster/backdrop (r84: all 30 titles →
# '/assets/crops/browse_home__poster-card-1.png'), so every rail rendered 30 IDENTICAL cards —
# nothing like the reference's varied poster wall → content screens stuck ~0.4-0.5 fidelity —
# while 60 real posters + 59 real backdrops sat STAGED and unused in public/assets/. Deterministic
# heal: when a catalog table's media field is DEGENERATE (all-same / a design-'/crops/' fragment /
# empty) AND real assets are staged, round-robin distinct real assets across the rows. GENERALIZES
# (field-name + asset-dir heuristics; no product literals). Sound for visual fidelity: the judge
# scores layout + imagery richness, not whether a poster matches its title (this is a demo). Never
# clobbers already-distinct real media; best-effort, never raises.
_POSTER_FIELD_RE = re.compile(r"poster|cover|thumb|artwork|card[_-]?img|(^|_)art$|image", re.I)
_BACKDROP_FIELD_RE = re.compile(r"backdrop|hero|banner|background|still", re.I)


def _asset_url_pool(assets_dir, subdir) -> list:
    """Sorted '/assets/<subdir>/<file>' URLs for staged images under public/assets/<subdir>."""
    from pathlib import Path as _P
    d = _P(assets_dir) / subdir
    if not d.is_dir():
        return []
    exts = (".jpg", ".jpeg", ".png", ".webp", ".avif")
    return [f"/assets/{subdir}/{f.name}" for f in sorted(d.iterdir())
            if f.is_file() and f.suffix.lower() in exts]


_IMG_VALUE_RE = re.compile(
    r"\.(?:jpg|jpeg|png|webp|avif|gif|svg)(?:\?|#|$)|"
    r"/(?:assets|crops|images|img|media|static|uploads)/", re.I)


def _looks_like_image_ref(v) -> bool:
    """A string value that plausibly IS an image path/URL (has an image extension or lives under a
    conventional image directory). Keeps media distribution off non-image string fields."""
    return isinstance(v, str) and bool(_IMG_VALUE_RE.search(v))


# #991: the stock image hosts a generated app must not depend on. Mirrors
# frontend_scaffold._STOCK_HOST_RE, which already localises these in literal JSX <img>;
# API-delivered URLs never passed through that path.
_STOCK_HOST_991 = re.compile(
    r"//(?:[a-z0-9-]+\.)*(?:picsum\.photos|unsplash\.com|pravatar\.cc|placeholder\.com|"
    r"placehold\.(?:co|it)|dummyimage\.com|placekitten\.com|loremflickr\.com|"
    r"placeimg\.com|fakeimg\.pl|via\.placeholder\.com)/", re.I)


def _field_is_degenerate(rows, field) -> bool:
    """A media field is degenerate (needs distributing) when its values across the rows are
    all-empty, all-identical, or point at design '/crops/' fragments rather than real media.

    #512-review (2026-08-05): TYPE + VALUE guards so a name-regex match on a NON-media field can
    never corrupt the seed. (1) If ANY value is non-null and non-string (int/bool/float — e.g.
    ``thumbs_up_count``=0 matches 'thumb', ``has_image``=False matches 'image'), this is not a
    string media field → return False (overwriting it with a URL STRING would fail the backend seed
    load → docker_up fails → false-block/wedge). (2) When the field HAS non-empty string values,
    they must ALL look like image refs — else it holds real non-image data (a slug, prose, a status)
    that must not be clobbered with posters. All-null media-named fields stay fillable (the primary
    intended case). Generalizes: no product literals."""
    vals = [r.get(field) for r in rows if isinstance(r, dict) and field in r]
    if not vals:
        return False
    # (1) TYPE guard — one non-null non-string value means this is not a string media field.
    if any(v is not None and not isinstance(v, str) for v in vals):
        return False
    nonempty = [v for v in vals if isinstance(v, str) and v.strip()]
    if not nonempty:
        return True                                   # all null/empty string → safe to fill
    # (2) VALUE guard — non-empty values must actually look like image refs to be degenerate media.
    # #991: a STOCK-PHOTO HOST is degenerate media, and it must be tested BEFORE the
    # image-ref guard below. `backend_skeleton` seeds image columns with
    # `https://picsum.photos/seed/<table><i>/<size>` — no file extension, so
    # `_looks_like_image_ref` says False and this function returns early. THAT is why #512's
    # heal never fired on them while 60 real posters sat staged in public/assets/: not a
    # missing degeneracy rule, a value guard that rejected the input first.
    #
    # r161's only real blocker. Every page rendering a poster logged
    # `Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED` (unreachable from the
    # sandbox), console errors failed the UI-evidence gate, and `blank=[]` confirmed the
    # pages otherwise RENDER. Majority rule matches the `/crops/` test below, so one stray
    # placeholder in a real catalogue does not trigger a rewrite.
    #
    # Self-containment is right independent of this sandbox: a generated demo whose images
    # need the public internet is broken offline too.
    # #994: a FRAMEWORK PLACEHOLDER is degenerate too. #993 made the seed emit an inline
    # `data:image/svg+xml` swatch so the app renders with no network and no console error —
    # correct as a floor, but a wall of flat rectangles is exactly the "30 identical cards"
    # look #512 exists to prevent, and the visual judge scores imagery richness.
    #
    # `_seed_cell` is a pure function with no filesystem access, so it CANNOT know whether
    # real posters are staged; #512 runs later and can. Marking the placeholder degenerate is
    # what connects them: self-contained by default, upgraded to real assets whenever the
    # pool exists. Asked proactively this time — #993's lesson was that a producer and its
    # consumer have to be checked together, and here the consumer would have skipped the
    # placeholder exactly as it skipped picsum.
    if sum(1 for v in nonempty if v.startswith("data:image/")) >= max(1, len(nonempty) // 2):
        return True
    if sum(1 for v in nonempty if _STOCK_HOST_991.search(v)) >= max(1, len(nonempty) // 2):
        return True
    if not all(_looks_like_image_ref(v) for v in nonempty):
        return False
    if len(set(nonempty)) <= 1 and len(rows) > 1:
        return True                                   # one image repeated across the catalog
    if sum(1 for v in nonempty if "/crops/" in v) >= max(1, len(nonempty) // 2):
        return True                                   # majority are design-crop fragments
    return False


def _distribute_media_over_seed(seed, poster_pool, backdrop_pool) -> int:
    """Pure: round-robin distinct real assets over DEGENERATE poster/backdrop fields of every
    catalog-like table (rows carrying such a field). Mutates ``seed`` in place; returns the
    number of (table, field) groups rewritten. Only touches degenerate fields."""
    if not isinstance(seed, dict):
        return 0
    changed = 0
    for _tbl, rows in seed.items():
        if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
            continue
        fields = set()
        for r in rows:
            if isinstance(r, dict):
                fields.update(r.keys())
        for field in sorted(fields):
            if _POSTER_FIELD_RE.search(field):
                pool = poster_pool or backdrop_pool
            elif _BACKDROP_FIELD_RE.search(field):
                pool = backdrop_pool or poster_pool
            else:
                continue
            if not pool or not _field_is_degenerate(rows, field):
                continue
            i = 0
            for r in rows:
                if isinstance(r, dict) and field in r:
                    r[field] = pool[i % len(pool)]
                    i += 1
            changed += 1
    return changed


def distribute_seed_media(repo_root, logger=None) -> dict:
    """#512 — rewrite degenerate catalog poster/backdrop fields in app/backend/seed_data.json to
    distinct real staged assets (public/assets/posters|backdrops). Best-effort; returns
    ``{"distributed": n_groups}`` or ``{}`` when nothing to do. Never raises."""
    try:
        from pathlib import Path as _P
        import json as _json
        repo = _P(repo_root)
        seed_path = repo / "app" / "backend" / "seed_data.json"
        assets_dir = repo / "app" / "frontend" / "public" / "assets"
        if not seed_path.is_file() or not assets_dir.is_dir():
            return {}
        seed = _json.loads(seed_path.read_text(encoding="utf-8"))
        posters = _asset_url_pool(assets_dir, "posters")
        backdrops = _asset_url_pool(assets_dir, "backdrops")
        if not posters and not backdrops:
            return {}
        n = _distribute_media_over_seed(seed, posters, backdrops)
        if n <= 0:
            return {}
        _fw_write_1202cw(seed_path,
                         _json.dumps(seed, indent=2, ensure_ascii=False),
                         clobber_ok="#512: rewrites degenerate poster/backdrop fields "
                                    "in the lane's seed")
        if logger is not None:
            try:
                logger.warning(
                    "🖼️ #512 distributed real seed media across %d degenerate catalog media "
                    "field(s): %d posters + %d backdrops round-robined over the catalog rows "
                    "(was a single repeated crop → varied real poster wall for Part-A fidelity).",
                    n, len(posters), len(backdrops))
            except Exception:
                pass
        return {"distributed": n, "posters": len(posters), "backdrops": len(backdrops)}
    except Exception:
        return {}


def heal_state_write_endpoints(backend_dir, registryhub, tables=None,
                               owner_scoped_tables=None, logger=None) -> dict:
    """#556 state-write HEAL as a standalone, reusable step (the #557 oracle's heal side).

    For every STATE-BEARING entity that is READABLE (has a GET) but has NO write
    (POST/PUT/PATCH) — the EXACT set the #557 completeness oracle flags — project an
    idempotent UPSERT write handler into ``main.py`` AND register it in RegistryHub,
    so coverage, the #557 oracle, and the frontend all see the new write path.
    Detection is delegated to the single #557 classifier
    (``completeness_audit.state_entities_missing_write`` via
    ``route_projector.project_state_write_endpoints``), so the heal closes precisely
    what the oracle detects.

    Extracted from ``HealPipeline.project_missing_routes`` so BOTH the delivery-time
    heal loop AND the delivery gate's HEAL-THEN-ENFORCE step (#557 R4-core,
    ``delivery_gate.enforce_completeness``) run the SAME projection + registration —
    never a duplicate. Idempotent + best-effort: byte-identical when there is nothing
    to heal (no state entity missing a write, or no ORM model backs the entity →
    nothing projected/registered), and re-running after it already ran is a no-op
    (the write is then seen as already-routed + already-registered). Never raises.

    Returns the ``project_state_write_endpoints`` result
    (``{"projected": [...], "endpoints": [...]}``), or ``{"projected": [],
    "endpoints": []}`` when it could not run (no registryhub / no backend)."""
    result: dict = {"projected": [], "endpoints": []}
    if registryhub is None:
        return result
    try:
        from pathlib import Path as _P
        from .route_projector import project_state_write_endpoints
        _tbls = tables
        if _tbls is None:
            try:
                _tbls = registryhub.list_tables() or {}
            except Exception:
                _tbls = {}
        try:
            _eps = registryhub.get_endpoints() or {}
        except Exception:
            _eps = {}
        _sw = project_state_write_endpoints(
            _P(backend_dir), _eps, _tbls, owner_scoped_tables=owner_scoped_tables)
        for _ep in (_sw.get("endpoints") or []):
            try:
                # #566d (netflix r115 advisory journey): emit a `request` sub-schema from
                # the subject FK(s) so contract-derived probes (test-user _probe_body, chain
                # synth, frontend) send them. Without it a projected state-write create (e.g.
                # POST /api/continue-watching) sent no title_id → NOT-NULL 400. Subject FKs are
                # ids (int); the projected handler drops any non-column key and maps a bad FK to
                # 404 (tolerated), so this only ever ADDS the missing required id. No literals.
                _req_schema = {
                    str(_fk): "int" for _fk in (_ep.get("subject_fks") or []) if _fk}
                _schema = {"response_key": _ep.get("response_key", "item"),
                           "auth_required": bool(_ep.get("auth_required"))}
                if _req_schema:
                    _schema["request"] = _req_schema
                registryhub.register_endpoint(
                    method=_ep["method"], path=_ep["path"],
                    schema=_schema,
                    provider="orchestrator", agent="orchestrator",
                    status="implemented",
                    response_key=_ep.get("response_key", "item"),
                    auth_required=bool(_ep.get("auth_required")),
                    projected_by="completeness_state_write_heal_556",
                    state_columns=list(_ep.get("state_columns") or []),
                    natural_keys=list(_ep.get("natural_keys") or []),
                    # #556-pt2: the subject FK(s) + owner FK let the FRONTEND
                    # (frontend_scaffold._load_state_write_endpoints_556b) fire this
                    # write from the player action with the right body keys (owner is
                    # server-derived; body carries subject + state).
                    subject_fks=list(_ep.get("subject_fks") or []),
                    owner_fk=_ep.get("owner_fk"))
            except Exception as _rex:
                if logger is not None:
                    try:
                        logger.debug(
                            "state-write endpoint registration skipped (%s %s): %s",
                            _ep.get("method"), _ep.get("path"), _rex)
                    except Exception:
                        pass
        if _sw.get("projected") and logger is not None:
            try:
                logger.warning(
                    "By-construction STATE-WRITE projection (#556): %s state entity "
                    "read-but-no-write gap(s) healed — projected an idempotent upsert "
                    "write path + registered it so the feature is functional (not "
                    "seed-only): %s", len(_sw["projected"]), _sw["projected"])
            except Exception:
                pass
        result = _sw
    except Exception as exc:
        if logger is not None:
            try:
                logger.debug("state-write projection skipped: %s", exc)
            except Exception:
                pass
    # #566f note: request-schema completion for lane-declared creates runs in the delivery-time
    # heal loop (see the heal_state_write_endpoints call site), NOT here — so it stays OUT of the
    # #557 R4 completeness-enforce path (a distinct concern: that gate is state-write completeness).
    return result


def heal_create_endpoint_request_schemas(registryhub, backend_dir, logger=None) -> dict:
    """#566f (netflix r115/r117): a LANE-DECLARED create (e.g. POST /api/my-list) can be registered
    with NO ``schema.request`` and no subject_fks, so the test-user journey's ``_probe_body`` — and
    chain synth / frontend — omit the target table's required subject FK (``title_id``) → NOT-NULL 400.
    #566d fixed only the #556-PROJECTED state-writes (which already carry ``subject_fks``); a
    lane-declared create carries none, so #566d never reached it.

    Generalize: for EVERY registered ``POST`` create on a COLLECTION whose target table has non-owner
    FK columns missing from ``schema.request``, ADD them (flat ``{fk: "int"}``, the shape ``_probe_body``
    reads). Reuses the #556 subject-FK derivation (``_fk_columns`` minus ``_owner_fk``) — the framework
    does not model column nullability, so a non-owner ``_id``/ForeignKey is treated as a required subject
    FK by the same convention #556/#566d already use.

    BYTE-SAFE: only ADDS missing non-owner FK ids; never overwrites an existing request field; EXCLUDES
    the server-derived owner FK (the projected handler injects it from the session); preserves the
    endpoint's provider/status/metadata. The projected handler drops any non-column key and maps a bad
    FK to 404, so this can only ever add the missing required id. Best-effort, never raises. No product
    literals. Returns ``{"healed": [{"path", "added"}, ...]}``."""
    healed: List[dict] = []
    if registryhub is None:
        return {"healed": healed}
    try:
        from pathlib import Path as _P
        from .route_projector import (_orm_models, _resource_model, _fk_columns,
                                      _owner_fk, _match_model)
        try:
            from .kickoff.contract import FIXED_ENDPOINT_KINDS as _FIXED
        except Exception:
            _FIXED = frozenset()
        try:
            models = _orm_models(_P(backend_dir))
        except Exception:
            models = {}
        if not models:
            return {"healed": healed}
        try:
            eps = registryhub.get_endpoints() or {}
        except Exception:
            return {"healed": healed}
        for _rec in list(eps.values() if isinstance(eps, dict) else eps):
            try:
                if not isinstance(_rec, dict):
                    continue
                if str(_rec.get("method") or "").upper() != "POST":
                    continue
                path = str(_rec.get("path") or "")
                if not path.startswith("/"):
                    continue
                segs = [s for s in path.strip("/").split("/") if s]
                # #566n: heal a genuine COLLECTION create — top-level (POST /api/my-list) OR
                # NESTED (POST /api/titles/{id}/rating). Skip only ITEM ops (last segment is a
                # path param, e.g. DELETE-shaped /api/my-list/{id}). The last-segment-matches-table
                # guard below then excludes ACTION verbs (/{id}/toggle, /{id}/like).
                if not segs:
                    continue
                _last = segs[-1]
                if _last.startswith("{") or _last.startswith(":"):
                    continue
                _kind = str((_rec.get("metadata") or {}).get("kind") or _rec.get("kind") or "")
                if _kind in _FIXED:
                    continue
                res = _resource_model(path, models)
                if not res:
                    continue
                _table, meta = res
                # Only a genuine collection create: the LAST segment must NAME the resolved table
                # (plural/singular). An action verb (/{id}/toggle) resolves to a PARENT via fallback,
                # and force-adding the parent's required columns to an action body would be wrong.
                _lm = _match_model(_last, models)
                if not _lm or _lm[0] != _table:
                    continue
                owner_fk = _owner_fk(meta)
                _cols = list(meta.get("cols", []) or [])
                _types = dict(meta.get("types", {}) or {})
                _required = list(meta.get("required", []) or [])
                subject_fks = [c for c in _fk_columns(meta) if c != owner_fk]

                def _sa_typestr(_sa):
                    _s = str(_sa or "").lower()
                    if "bool" in _s:
                        return "bool"
                    if ("float" in _s or "numeric" in _s or "decimal" in _s
                            or "double" in _s or "real" in _s):
                        return "float"
                    if "int" in _s:
                        return "int"
                    return "str"

                # #566i (r119): also complete common REQUIRED non-FK TEXT columns. A create like
                # POST /api/profiles NOT-NULL-violates on `name` when the probe omits it
                # (IntegrityError 23502 → the handler's "invalid field value" 400) — `name` is not a
                # FK, so the subject-FK pass alone skipped it. Generic scalar names, no product literal.
                _REQ_TEXT = ("name", "title", "label", "display_name", "nickname")
                _to_add = {}
                for _fk in subject_fks:
                    _to_add[_fk] = "int"
                for _c in _cols:
                    if _c in _REQ_TEXT and _c != owner_fk and _c not in subject_fks:
                        _to_add.setdefault(_c, "str")
                # #566n (r124): add every genuinely-REQUIRED column (NOT-NULL, non-PK, no default —
                # parsed from the ORM) that the body must supply — e.g. rating.value (a NOT-NULL
                # numeric on a NESTED create POST /api/titles/{id}/rating that the subject-FK/text
                # passes miss) → business_chain 400 "DB constraint on missing field". Typed from the
                # ORM column; owner FK excluded (server-derived). Precise (nullable=False only), so no
                # optional/defaulted column is force-sent.
                for _c in _required:
                    if _c == owner_fk:
                        continue
                    _to_add.setdefault(_c, _sa_typestr(_types.get(_c)))
                if not _to_add:
                    continue
                schema = dict(_rec.get("schema") or {})
                _req = schema.get("request")
                existing_req = dict(_req) if isinstance(_req, dict) else {}
                missing = {k: v for k, v in _to_add.items() if k not in existing_req}
                if not missing:
                    continue
                schema["request"] = {**existing_req, **missing}
                from .registryhub import _resolved_auth_1202gr
                registryhub.register_endpoint(
                    method=_rec.get("method"), path=path,
                    schema=schema,
                    provider=_rec.get("provider") or "backend",
                    agent="orchestrator",
                    status=_rec.get("status") or "defined",
                    response_key=(_rec.get("metadata") or {}).get("response_key")
                    or schema.get("response_key") or "item",
                    # #1202gr: this was `bool(metadata or schema)` — an OR, not the
                    # precedence #1202ga established, so a STALE mirror True beat the lane's
                    # fresh schema False and was WRITTEN BACK here as the current value. It
                    # fired 3x in r98 / 4x in r97 / 4x in r96 on exactly the endpoints those
                    # runs' chains failed against (/api/videos/{id}/comments, .../like,
                    # .../save, /api/users/{id}/follow), and re-registering with a flipped
                    # auth is what then read as `auth_added` downstream.
                    auth_required=_resolved_auth_1202gr(_rec))
                healed.append({"path": path, "added": sorted(missing.keys())})
                if logger is not None:
                    try:
                        logger.warning(
                            "🔧 #566f/#566i/#566n completed request schema of %s — create omitted "
                            "required field(s) %s (subject FK / NOT-NULL text / NOT-NULL typed column), "
                            "so probes/chains/frontend sent no value → NOT-NULL 400. Added them "
                            "(server-derived owner FK excluded).", path, sorted(missing.keys()))
                    except Exception:
                        pass
            except Exception:
                continue
        return {"healed": healed}
    except Exception:
        return {"healed": healed}


def _stack_serving_1202ne(base: str, api_base: "str | None", timeout_s: float = 180.0,
                          poll_s: float = 3.0) -> bool:
    """#1202ne: wait (bounded) for a recycled stack to serve its frontend and backend again."""
    from .validation_runner import _http
    deadline = time.time() + timeout_s
    while True:
        fe_ok = _http("GET", base, timeout=5).get("status") == 200
        be_ok = (not api_base) or _http("GET", f"{api_base}/health", timeout=5).get("status") == 200
        if fe_ok and be_ok:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(poll_s)




# ── #1202zb — two tables with one shape, and the API reads the emptier one ────────
_TWIN_SKIP_COLS_1202ZB = ("id", "created_at", "updated_at")
# #1202zb: the floor is where the JOIN-TABLE class ends, measured by grouping every model on
# its column set (id/created_at/updated_at dropped) across the 159 corpus app trees that have
# an ORM, out of 182 run directories:
#   2 cols -> 84 groups in 83 of those 159 runs -- every one a `(user_id, <x>_id)` pair
#             such as likes/reposts or likes/saves, all legitimate
#   3 cols ->  9 groups in  9 runs -- the same class, video_likes/video_saves
#   4 cols ->  7 groups in  6 runs -- the class is gone; these are real twins
# So 4 is not a taste: at 3 the check reports nine join-table pairs that are correct by
# construction, and at 2 it fires on half the corpus.
_TWIN_MIN_COLS_1202ZB = 4


def _cols_1202zb(model: Any) -> tuple:
    """A model's column names minus the three every table carries.

    `_models_919` spells them `cols` (a flat list of names); `columns` is read too because
    the registry dialect uses that name with dicts inside. The first draft of this read ONLY
    `columns` and therefore matched NOTHING anywhere in the corpus -- the six pairs measured
    below appeared only once the key was right, so the reading order here is load-bearing and
    a "0 hits" from this helper means suspect the locator first.
    """
    c = model.get("cols") if isinstance(model, dict) else None
    if not c and isinstance(model, dict):
        c = model.get("columns")
    if isinstance(c, dict):
        names = list(c)
    elif isinstance(c, (list, tuple)):
        names = [(x.get("name") if isinstance(x, dict) else x) for x in c]
    else:
        return ()
    return tuple(sorted(str(n) for n in names
                        if n and str(n) not in _TWIN_SKIP_COLS_1202ZB))


def _name_variants_1202zb(a: Any, b: Any) -> bool:
    """True when two table names differ ONLY in plural/separator spelling.

    This EXCLUDES a pair rather than flagging it. The finding rests on `_resource_model`
    saying which of the two tables an endpoint reads, and that resolver matches a path
    segment against table names plural-OR-singular -- so for `comment` beside `comments` it
    can only pick one, and WHICH one it picks is not evidence about which one the handler
    queries. `_match_model` settles this: its loop `return`s the FIRST table whose name
    matches, and `cand.rstrip("s") == table.rstrip("s")` makes both twins match equally --
    so the answer is decided by dict insertion order. Measured on r125's real model set:
    `/api/comments` resolves to `comment`, the 8-row twin, while `comments` holds 295.
    Both pairs this drops are exactly the two the resolver could not tell apart.

    The rule is per TOKEN: `message_conversations` and `messages_conversations` differ in the
    FIRST token, and a rule that strips only a trailing `s` calls them unrelated and reports
    the pair. `_singular_1202ru` rather than a second spelling authority of my own (#1032).
    """
    from .material_prep import _singular_1202ru
    def _key(n):
        return tuple(_singular_1202ru(t)
                     for t in str(n).replace("-", "_").lower().split("_") if t)
    return _key(a) == _key(b)


def _unreachable_twin_tables_1202zb(out_dir: Any, registryhub: Any) -> dict:
    """``{"measured": bool, "why": str, "findings": [...]}``.

    r140 SHIPPED this in a released 1.0.0. `videos` and `feed` carry byte-identical columns;
    `videos` held 35 rows and `feed` 8, their contents DISJOINT; the app's only collection
    read is `GET /api/feed` and no GET anywhere resolves to `videos`. So 35 authored videos
    -- the whole point of the seed -- were unreachable through the delivered app, and nothing
    said a word. Verified by curl against that run's own stack.

    MEASURED over the 47 corpus runs carrying live row counts: SIX pairs in four runs match
    the raw shape, and reading every one is what produced the exclusion above:

        r140  videos(35)               no GET | feed(8)                   GET /api/feed
        r105  live_streams(3)          no GET | live(0)                   GET /api/live
        r105  creator_profiles(5)      no GET | suggested_creators(0)     GET /api/suggested-creators
        r99   conversations(7)         no GET | messages(6)               GET /api/messages
        r125  comments(295)            no GET | comment(8)                EXCLUDED, variant
        r125  message_conversations(8) no GET | messages_conversations(6) EXCLUDED, variant

    r99 looked like a false positive on its names and is not: both tables carry
    `peer_id, last_message, unread`, i.e. the lane modelled one conversation list twice.

    ``measured`` is False whenever the answer carries no information -- no ORM on disk, or no
    row counts from THIS validation cycle. #1202z5 is the same lesson one module over: a
    `count: 0` from an audit that inspected nothing must not read as clean.

    Endpoints come from the registry rather than `lifecycle.business_endpoints`, which drops
    the auth and control-plane routes by design (#1202xg). The wider list can only SUPPRESS a
    finding -- one more GET that resolves to the unread table -- never invent one.
    """
    out: dict = {"measured": False, "why": "", "findings": []}
    try:
        from pathlib import Path as _P1202zb
        from .backend_audit import _models_919
        from .route_projector import _resource_model
        from .seed_audit import recent_live_counts_1202dj, _project_root_1202dj
        root = _project_root_1202dj(out_dir)
        models, _ = _models_919(_P1202zb(root) / "app" / "backend")
        if not models:
            out["why"] = "no ORM models on disk"
            return out
        counts = recent_live_counts_1202dj(str(root)) or {}
        if not counts:
            # Deliberate: `recent_live_counts_1202dj` refuses counts older than its TTL,
            # because the stack is torn down and rebuilt around each validation and a stale
            # count would describe a different database.
            out["why"] = "no live row counts from this validation cycle"
            return out
        out["measured"] = True
        # #1202rm already paid for guessing this accessor once: it is `get_endpoints`.
        _rh = getattr(registryhub, "registryhub", None) or registryhub
        _get = (getattr(_rh, "get_endpoints", None)
                or getattr(_rh, "list_endpoints", None))
        if not callable(_get):
            out["measured"] = False
            out["why"] = "no endpoint accessor on the registry"
            return out
        eps = _get() or {}
        by_shape: dict = {}
        for name, m in models.items():
            c = _cols_1202zb(m)
            if len(c) >= _TWIN_MIN_COLS_1202ZB:
                by_shape.setdefault(c, []).append(str(name))
        read_by_get: dict = {}
        via: dict = {}
        _unresolved = 0
        for rec in (eps.values() if isinstance(eps, dict) else (eps or [])):
            if not isinstance(rec, dict):
                continue
            if str(rec.get("status")) != "implemented":
                continue
            if str(rec.get("method") or "").upper() != "GET":
                continue
            p = str(rec.get("path") or "")
            if not p:
                continue
            try:
                r = _resource_model(p, models)
            except Exception:
                r = None
                _unresolved += 1
            if r:
                read_by_get[r[0]] = read_by_get.get(r[0], 0) + 1
                via.setdefault(r[0], p)
        if _unresolved:
            # #883: an empty default born inside a handler is how a check goes quiet. A route
            # the resolver threw on might have been the unread table's only GET, so the record
            # must not imply the resolution was total.
            out["why"] = ("%d route(s) did not resolve to a table; a read may be missed"
                          % _unresolved)
        for names in by_shape.values():
            known = [n for n in names if n in counts]
            if len(known) < 2:
                continue
            for a in known:
                if read_by_get.get(a):
                    continue                      # the API reads it; nothing is hidden
                _ra = int(counts.get(a) or 0)
                for b in known:
                    if b == a or not read_by_get.get(b):
                        continue
                    # Strictly fewer rows on the served side. This also settles the empty
                    # case without a second guard: an unread table with 0 rows hides no
                    # content, and every row count is >= 0, so `counts[b] >= 0` excludes it
                    # here. A draft carried `if _ra <= 0: continue` above as well; removing
                    # the mutation-proof guard is the point -- it could not change an answer.
                    if int(counts.get(b) or 0) >= _ra:
                        continue
                    if _name_variants_1202zb(a, b):
                        continue
                    out["findings"].append({
                        "unread": a, "unread_rows": _ra,
                        "served": b, "served_rows": int(counts.get(b) or 0),
                        "via": via.get(b, ""), "columns": len(_cols_1202zb(models[a])),
                    })
        return out
    except Exception as _e1202zb:
        try:
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.unreachable_twin_tables_1202zb",
                "seeded content sitting in a table no endpoint reads, beside an "
                "identically-shaped table the API does read, goes unreported", _e1202zb)
        except Exception:
            pass
        return out


def _report_unreachable_twins_1202zb(orch, out_dir, registryhub) -> None:
    """Land #1202zb where a lane can read it, and in an artifact.

    A TASK, not a blocker. #1202w0 struck the same bargain for the same harm class one module
    over -- "the artifact is the whole of its output; the next runs' files are the evidence
    for whether it earns a gate check" -- and two things here argue for keeping it: the
    `no GET resolves to A` leg rests on `_resource_model`, which the variant exclusion shows
    cannot always tell two tables apart, and a wrong blocker costs what r140's M1.1 cost, 95
    minutes of a cycling gate. What this adds over #1202w0 is the audience: today's #1202z0
    and #1202z4 are both the same finding -- computed correctly, delivered to a log nobody
    reads. Deduped by title prefix (#794).

    The unmeasured case is announced ONCE rather than appended every heal cycle: a run has
    hundreds of them, and hundreds of "could not measure" lines would bury the findings the
    artifact exists to hold. Silent it is not -- that is what `warn_once_1201` is for.
    """
    try:
        res = _unreachable_twin_tables_1202zb(out_dir, registryhub)
        if not res.get("measured"):
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.twins_1202zb_unmeasured",
                "the unreachable-twin-table check could not run (%s), so a run that ships "
                "content no endpoint reads would look the same as one that does not"
                % (res.get("why") or "reason not recorded"),
                None)
            return
        findings = res.get("findings") or []
        if not findings:
            return
        try:
            import json as _j1202zb
            import time as _t1202zb
            from pathlib import Path as _P2
            _art = _P2(str(out_dir)) / "logs" / "unreachable_twin_table_1202zb.jsonl"
            _art.parent.mkdir(parents=True, exist_ok=True)
            with open(_art, "a", encoding="utf-8") as fh:
                fh.write(_j1202zb.dumps({"at": _t1202zb.time(),
                                         "measured": True,
                                         "why": str(res.get("why") or ""),
                                         "count": len(findings),
                                         "findings": findings[:20]}) + "\n")
        except Exception:
            pass          # the task below is the part a lane can act on
        wh = getattr(getattr(orch, "hubs", None), "workhub", None)
        if wh is None:
            return
        base = "Seeded rows no endpoint reads, beside an identical table the API serves"
        try:
            for t in (wh.list_tasks() or []):
                if (isinstance(t, dict)
                        and str(t.get("title") or "").startswith(base)
                        and str(t.get("status")) in ("pending", "in_progress", "open")):
                    return
        except Exception:
            pass          # best-effort dedupe: on any fault, file
        lines = ["  - `%s` holds %d row(s) and NO GET endpoint reads it, while `%s` holds "
                 "%d and is what `GET %s` returns -- the two have the same %d columns."
                 % (f["unread"], f["unread_rows"], f["served"], f["served_rows"],
                    f["via"], f["columns"]) for f in findings[:8]]
        wh.create_task(
            title="%s (%d)" % (base, len(findings)),
            description=(
                "\n".join(lines)
                + ("\n  ... and %d more" % (len(findings) - 8) if len(findings) > 8 else "")
                + "\n\nRow counts are from this validation cycle's live database, not the "
                "seed file. Two tables with the same columns SPLIT the seed, and the app can "
                "only show the half its handler reads: r140 shipped a released 1.0.0 whose "
                "front page served 8 rows from `feed` while 35 authored videos sat in "
                "`videos` with no route to reach them.\n\nPick one: point the existing "
                "read at the populated table, or give the populated table its own list "
                "endpoint, or collapse the two tables into one and reseed. Do NOT copy rows "
                "between them -- that leaves two sources of truth for the same content."),
            assignee="backend", agent="orchestrator", priority="P1")
    except Exception as _e2:
        try:
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.report_unreachable_twins_1202zb",
                "content seeded into a table the API never reads stays unreported", _e2)
        except Exception:
            pass


def _lane_middleware_task_1202zu(orch, out_dir) -> None:
    """#1202zu — tell the lane that its own middleware answers before the framework's guard.

    `framework_guard_tampering_1202lj` blocks a lane that edits the route table or the auth
    allow-list. A lane-installed `@app.middleware("http")` does neither and still runs OUTER of
    `_framework_auth_guard` (Starlette builds the stack in reverse), so one that returns a
    Response without awaiting `call_next` answers with the guard never consulted. r139's own
    docstring says it knew: "It does not mutate framework route tables or guard allow-lists."

    REPORTED, NOT BLOCKED. Measured: 22 short-circuiting lane middlewares across 17 runs, 6 of
    them intercepting an auth path — but on the still-running r139 stack the intercepted
    `POST /auth/login` REFUSES a wrong password (401 `invalid credentials`, identical to the
    un-intercepted r135) because the lane's handler delegates to the framework's own `login()`.
    So the mechanism is invisible rather than harmful today, and blocking it would stop the shape
    in 17 runs while the pressure that produces it — a contract-public feed answering 401 — is
    what #1202zn and #1202zr just removed. Blocking a lane for the only move that works is
    r140's M1.1 over again (#1202z0's reasoning).

    Deduped by title prefix (#794), and the artifact carries every site so the count in the
    title can be checked against something.
    """
    try:
        from pathlib import Path as _P1202zu
        from .backend_audit import lane_installed_middleware_1202zu
        hits = lane_installed_middleware_1202zu(
            _P1202zu(str(out_dir)) / "app" / "backend") or []
        if not hits:
            return
        try:
            import json as _j1202zu
            _p = _P1202zu(str(out_dir)) / "logs" / "lane_middleware_1202zu.jsonl"
            _p.parent.mkdir(parents=True, exist_ok=True)
            with open(_p, "a", encoding="utf-8") as _fh:
                _fh.write(_j1202zu.dumps({"at": time.time(), "sites": hits}) + "\n")
        except Exception:
            pass          # the artifact is evidence, not the finding
        wh = getattr(getattr(orch, "hubs", None), "workhub", None)
        if wh is None:
            return
        base = "Lane middleware answers before the framework's auth guard"
        try:
            for t in (wh.list_tasks() or []):
                if (isinstance(t, dict)
                        and str(t.get("title") or "").startswith(base)
                        and str(t.get("status")) in ("pending", "in_progress", "open")):
                    return
        except Exception:
            pass          # best-effort dedupe; on any fault, file
        _auth = [h for h in hits if h.get("auth_paths")]
        lines = []
        for h in hits[:8]:
            # #1034: the per-site path list is capped too, and a cap beside a count has to
            # declare itself — a site that intercepts nine paths must not show four in silence.
            _ip1202zu = list(h.get("intercepts") or [])
            _shown1202zu = ", ".join(_ip1202zu[:4]) or "(no literal path)"
            if len(_ip1202zu) > 4:
                _shown1202zu += " +%d more" % (len(_ip1202zu) - 4)
            lines.append("  - %s:%s `%s` intercepts %s%s" % (
                h.get("file"), h.get("line"), h.get("func"), _shown1202zu,
                "   ← AUTH PATH" if h.get("auth_paths") else ""))
        wh.create_task(
            title="%s (%d)" % (base, len(hits)),
            description=(
                "These functions are decorated `@app.middleware(\"http\")` in lane code and "
                "return a Response WITHOUT awaiting `call_next`:\n"
                + "\n".join(lines)
                + ("\n  ... and %d more" % (len(hits) - 8) if len(hits) > 8 else "")
                + "\n\nStarlette builds the middleware stack in reverse, so middleware added "
                "later runs OUTSIDE the framework's `_framework_auth_guard`. A short-circuit "
                "there answers the request with the guard never consulted — the route is public "
                "in effect, and nothing in the contract, the materials or the guard's public "
                "list records that. It is not caught by the guard-tampering blocker, which "
                "looks at route tables and allow-list names.\n\n"
                "This is a REPORT, not a refusal: your handler may well be correct (r139's "
                "delegates to the framework's own `login()` and still refuses a wrong "
                "password). What is wrong is that the decision is invisible. If the read is "
                "meant to be public, say so in the CONTRACT (`auth_required: false` on a READ) "
                "and let the framework project and list it; then delete the middleware. If it "
                "is not meant to be public, delete the middleware and let the guard answer."
                + ("\n\n%d of these intercept an AUTH path. Re-implementing login or signup "
                   "in middleware means the framework's own AS no longer decides who is signed "
                   "in — if you keep it, it must call the AS, never compare a password itself."
                   % len(_auth) if _auth else "")),
            assignee="backend", agent="orchestrator", priority="P1")
    except Exception as _e1202zu:
        try:
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.lane_middleware_task_1202zu",
                "lane middleware that answers before the auth guard stays unreported, so a "
                "short-circuited route reads as a framework decision", _e1202zu)
        except Exception:
            pass


def _unstaged_seed_media_task_1202zf(orch, out_dir) -> None:
    """#1202zf — tell the frontend lane about seeded media that is still missing AT DELIVERY.

    `unstaged_seed_media_1202xn` already finds it and `record_unstaged_seed_media_1202xn`
    already lands it in `logs/unstaged_seed_media_1202xn.jsonl`. The harm is a card that renders
    its thumbnail -- which IS an image and therefore IS staged -- and 404s the moment a viewer
    presses play.

    THE FINDING REACHES NO LANE, and what the corpus shows instead is worse than silence: the
    ticket token appears in ZERO hub files across every run, and twice an agent PAID TO
    REDISCOVER IT from a browser 404. r121's debugger wrote the root cause itself -- "synthetic
    local media paths ... that are not staged frontend assets; feed responses returned them
    verbatim, causing browser 404s" -- and r62's verifier recorded "file not staged in frontend
    /assets/real_videos/ or missing from static build" as a test result. The framework knew
    both answers before either agent started looking. (`real_videos` does appear in hubs 3403
    times, but as seed paths inside chains and documents, not as this finding.)

    ★ WHY LATE AND NOT WHERE THE DETECTOR ALREADY RUNS. The existing call sits in
    `stage_missing_frontend_assets`, i.e. at SCAFFOLD time, and most of what it reports there
    is transient. Measured on r139: 36 ledger lines carrying 35 videos "excluded from the image
    by .dockerignore", 1260 entries in all -- and the delivered tree is CLEAN, because the
    framework's own baseline copy rewrote `.dockerignore` ten seconds after the last report
    (file mtime 00:14:57, last ledger line 00:14:47) and all 35 files are on disk. Reporting a
    state that the framework itself is about to repair is how a signal teaches its reader to
    skip it.

    What survives to delivery is real. r140 shipped THREE seeded videos that are still absent
    from the delivered tree -- `jasonderulo__7658062942529097015.mp4`,
    `khaby.lame__7655124220186492182.mp4`, `gordonramsayofficial__7659188408110628126.mp4` --
    while 35 other videos ARE staged. Same shape in r124 (2), r129 (3) and r135 (1).

    A TASK, NOT A BLOCKER, and no placeholder is synthesised: the framework stages REAL media
    and a grey stand-in is worse than a named gap (#1202xn's own reasoning, kept). The lane can
    act because staged alternatives exist -- the count is in the task text for exactly that
    reason.
    """
    try:
        from .frontend_scaffold import unstaged_seed_media_1202xn
        missing = unstaged_seed_media_1202xn(out_dir) or []
        if not missing:
            return
        wh = getattr(getattr(orch, "hubs", None), "workhub", None)
        if wh is None:
            return
        base = "Seeded media missing at delivery — cards render a thumbnail and 404 on play"
        try:
            for t in (wh.list_tasks() or []):
                if (isinstance(t, dict)
                        and str(t.get("title") or "").startswith(base)
                        and str(t.get("status")) in ("pending", "in_progress", "open")):
                    return
        except Exception:
            pass          # best-effort dedupe; on any fault, file
        staged = 0
        try:
            from pathlib import Path as _P1202zf
            _vd = _P1202zf(str(out_dir)) / "app" / "frontend" / "public" / "assets"
            if _vd.is_dir():
                staged = sum(1 for _p in _vd.rglob("*")
                             if _p.is_file() and _p.suffix.lower() in
                             (".mp4", ".mov", ".webm", ".m4v"))
        except Exception:
            staged = 0
        wh.create_task(
            title="%s (%d)" % (base, len(missing)),
            description=(
                "The seed points at local media that is NOT in the delivered app:\n"
                + "\n".join("  - %s" % m for m in missing[:12])
                + ("\n  ... and %d more" % (len(missing) - 12) if len(missing) > 12 else "")
                + "\n\nThe card still LOOKS right: `thumbnail_url` is an image, images are "
                "staged, so the failure only appears when a viewer presses play. %d playable "
                "media file(s) ARE staged under `public/assets`, so repointing is possible."
                "\n\nFix the SEED ROW, not the page: point it at a file that is staged, or "
                "drop the row. Do NOT add a placeholder or a grey stand-in — the framework "
                "stages real media and a fake one hides the gap instead of closing it. An "
                "entry marked `excluded from the image by .dockerignore` is the other cause: "
                "the file exists on disk and your `.dockerignore` keeps it out of the image — "
                "remove that pattern, and if a large file broke the build, replace the FILE."
                % (staged)),
            assignee="frontend", agent="orchestrator", priority="P1")
    except Exception as _e1202zf:
        try:
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.unstaged_seed_media_task_1202zf",
                "seeded media that is missing at delivery stays in a log the lane that can "
                "fix it never reads", _e1202zf)
        except Exception:
            pass

def _ui_friction_lines_1203c8(ui):
    """``(lines, screens, dropped)`` from an LLM test-user `ui` section. #1203c8

    Pure, so the formatting is testable without a hub. `lines` are rendered per screen plus the
    overall `top_issues`; `screens` names the screens that carried a problem (for the title);
    `dropped` is how many problem entries the cap left out, which the body must state (#1034).
    """
    if not isinstance(ui, dict):
        return [], [], 0
    CAP_PER_SCREEN = 5
    lines = []
    screens = []
    dropped = 0
    for sc in (ui.get("screens") or []):
        if not isinstance(sc, dict):
            continue
        probs = [str(p).strip() for p in (sc.get("problems") or []) if str(p).strip()]
        if not probs:
            continue
        name = str(sc.get("name") or "?").strip() or "?"
        screens.append(name)
        lines.append("  %s:" % name)
        for p in probs[:CAP_PER_SCREEN]:
            lines.append("    - %s" % p)
        dropped += max(0, len(probs) - CAP_PER_SCREEN)
    tops = [str(t).strip() for t in (ui.get("top_issues") or []) if str(t).strip()]
    if tops:
        lines.append("  the test-user's own ranking of what to fix FIRST:")
        for t in tops[:8]:
            lines.append("    %d. %s" % (tops.index(t) + 1, t))
        dropped += max(0, len(tops) - 8)
    return lines, screens, dropped


def _file_ui_friction_task_1203c8(orch, ui, version: str = "") -> None:
    """#1203c8 — route the LLM test-user's screen findings to the frontend lane.

    `top_issues` and the per-screen `problems` had ZERO readers: two occurrences each in the
    whole tree, the prompt that asks and the line that stores. 969 screen records with
    `problems` and 690 ranked frictions across 107 runs went only to a JSON file.

    P1 and never a blocker: delivery must not hinge on an LLM's aesthetic judgement, and
    #1202z4 established that when the framework cannot show the finding is objectively wrong,
    what changes is the audience. The browser walk's objective P0 path is untouched.
    """
    try:
        lines, screens, dropped = _ui_friction_lines_1203c8(ui)
        if not lines:
            return
        wh = getattr(getattr(orch, "hubs", None), "workhub", None)
        if wh is None:
            return
        base = "Test-user named user-visible UI frictions (screen walkthrough) — fix"
        try:
            for t in (wh.list_tasks() or []):
                if (isinstance(t, dict)
                        and str(t.get("title") or "").startswith(base)
                        and str(t.get("status")) in ("pending", "in_progress", "open")):
                    return
        except Exception:
            pass        # best-effort: on any fault, file rather than stay silent
        try:
            from .remediation_dispatcher import _instanced_gate_title_1202ss
            title = _instanced_gate_title_1202ss(base, screens)
        except Exception:
            title = "%s (%d screens)" % (base, len(screens))
        wh.create_task(
            title=title,
            description=(
                "An LLM test-user walked the RUNNING app%s with screenshots and reported what "
                "a first-time user hits. These are its own words, per screen:\n\n"
                % ((" at v%s" % version) if version else "")
                + "\n".join(lines)
                + ("\n\n  (%d further problem entries not shown)" % dropped if dropped else "")
                + "\n\nThis is NOT a delivery blocker — it is the most user-proximate feedback "
                "the pipeline produces, and until now it reached a JSON file and nothing else. "
                "Fix what is objectively wrong (clipped/overflowing layout, content hidden "
                "behind another element, a control that looks usable but cannot work, missing "
                "empty states). Where you judge an item to be a matter of taste or already "
                "intended, say so in the task and move on — do not silence it by deleting the "
                "affordance it describes."),
            assignee="frontend", agent="orchestrator", priority="P1")
        orch._logger.warning(
            "TEST-USER UI frictions dispatched to frontend (#1203c8): %d screen(s), "
            "%d line(s)%s", len(screens), len(lines),
            (", %d entries capped" % dropped) if dropped else "")
    except Exception as _exc1203c8:
        try:
            orch._logger.error("ui friction dispatch failed (#1203c8): %s", _exc1203c8)
        except Exception:
            pass


def _file_shadowed_route_task_1202z4(orch, duplicated) -> None:
    """#1202z4 — tell the lane that a route it wrote twice never runs.

    `backend_audit` already computes this and `sync_endpoint_statuses` already returns it in
    `out["duplicated"]`. Everything that happens to the finding is one `_logger.warning`, and
    a lane reads WorkHub, not the orchestrator's log. Measured over the 158 run logs: it
    reports in 4 of them and reaches a hub in NONE — grep of every `shared/hubs/` file in
    every run for `DUPLICATE/shadowed` returns nothing.

    Rare (3%) and severe when it fires: r136 reported TWENTY-THREE shadowed endpoints, 47
    times over the run, and nothing was ever dispatched. `duplicated_routes` finds only
    INTRA-module collisions — the same (method, path) decorated twice in one file — which its
    own docstring calls "always a lane bug"; a cross-module override (main.py's projected
    handler plus a custom_routes.py override) is deliberately not flagged. So there is no
    judgement call to make here: FastAPI mounts the first definition and the second body
    never executes, however right it is.

    A TASK, not a blocker, on the same reasoning as #1202z0: the framework has never
    established that the shadowed copy is the one that mattered, and blocking delivery on a
    duplicate that happens to be identical would stop a run for nothing. It changes the
    audience, not the verdict.

    Deduped by title prefix (#794) so the 47 reports of one run re-wake one task.
    """
    try:
        if not duplicated:
            return
        wh = getattr(getattr(orch, "hubs", None), "workhub", None)
        if wh is None:
            return
        base = "Route defined twice in one file — the second never runs"
        try:
            for t in (wh.list_tasks() or []):
                if (isinstance(t, dict)
                        and str(t.get("title") or "").startswith(base)
                        and str(t.get("status")) in ("pending", "in_progress", "open")):
                    return
        except Exception:
            pass        # best-effort: on any fault, file as before
        names = [str(x) for x in duplicated]
        wh.create_task(
            title="%s (%d)" % (base, len(names)),
            description=(
                "These routes are decorated MORE THAN ONCE inside a single served module:\n"
                + "\n".join("  - %s" % n for n in names[:20])
                + ("\n  ... and %d more" % (len(names) - 20) if len(names) > 20 else "")
                + "\n\nFastAPI mounts the FIRST definition and never reaches the second, so "
                "whichever body you wrote later is dead code — including when it is the "
                "correct implementation and the first is an early stub. Nothing in the app's "
                "behaviour shows this: the route answers, it just answers from the other "
                "function.\n\nDelete the definition you do not want. This is about DUPLICATES "
                "WITHIN ONE FILE only; a handler in custom_routes.py that overrides main.py's "
                "projected one is a different thing and is not reported here."),
            assignee="backend", agent="orchestrator", priority="P1")
    except Exception as _e1202z4:
        try:
            from .message_format import warn_once_1201
            warn_once_1201(
                "heal_pipeline.shadowed_route_task_1202z4",
                "the shadowed-route finding stays in the log only, so a lane keeps editing "
                "a function that never runs", _e1202z4)
        except Exception:
            pass

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
            # #1149: every repair above returns a ``reason`` when it declines and
            # NOTHING logged it — so a heal that correctly no-ops ("already
            # present", because the scaffold now emits it by construction) and a
            # heal whose detector is broken ("no FastAPI app") were indistinguish‐
            # able in the log. That blind spot is exactly what forces a live run to
            # tell the two apart. Say which declined, and why.
            _declined_1149 = [
                (_n, _r.get("reason") or _r.get("error") or "(no cause reported)")
                for _n, _r, _k in (
                    ("router_prologue", _rp, "repaired"),
                    ("auth_dependency_45", rep, "repaired"),
                    ("auth_imports_48", imp, "repaired"),
                    ("inline_token_46", inline, "fixed"),
                    ("auth_middleware_47", mw, "injected"),
                    ("integrity_map_82", ih, "injected"),
                    ("custom_routes_db_86", dbh, "repaired"),
                    ("param_types_106", pt, "fixed"),
                )
                if isinstance(_r, dict) and not _r.get(_k)
            ]
            if _declined_1149:
                # #1202n: say it when it CHANGES, not once per tick. #1149 exists so a
                # declined heal states its cause, and the cause is right — every entry reads
                # "the defect this heal exists for is not present". But the state it describes
                # barely moves: measured across r22-r26, each run emits 27 to 135 copies of
                # this line for exactly TWO distinct cause-sets (r26: 134 lines, 2 states).
                #
                # Repeating an unchanged line 134 times is its own way of hiding a signal —
                # the inverse of the silence #1102 is about, and the same reason #1201 reports
                # once per site. Every distinct state is still logged, and a transition back
                # to a state already seen is logged again, so nothing that MOVED is lost.
                _cause_1202n = "; ".join("%s=%s" % (_n, _w) for _n, _w in _declined_1149)
                if getattr(orch, "_heal_decline_cause_1202n", None) != _cause_1202n:
                    orch._heal_decline_cause_1202n = _cause_1202n
                    orch._logger.info(
                        "#1149 backend heals declined (no-op) with cause: %s", _cause_1202n)
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
                    _fw_write_1202cw(t, ddl_sql)   # framework-owned DDL; no clobber
                    written.append(str(t))
                except Exception:
                    continue
            # #1202ad: 273 copies across r30/r31/r32 for one unchanging set of tables and
            # targets. A schema that CHANGES is news; regenerating the same DDL is not.
            from .message_format import state_changed_1202ad as _sc1202ad
            if _sc1202ad("orm_ddl_regen", (tuple(sorted(tables)), tuple(sorted(written)))):
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
            _tbls: dict = {}
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

            # #556 (HEAL for the missing-write-path class — the #557 oracle's heal
            # side): a STATE-BEARING entity (a table with a mutable data column —
            # progress_seconds / status / position / is_*) that is READABLE (GET) but
            # has NO write endpoint is non-functional (Netflix "resume watching" only
            # reflects seed data because playback progress can never be recorded). The
            # declared-contract coverage gate is BLIND to it (the write was never
            # declared). Auto-project an idempotent UPSERT write handler for each such
            # entity (keyed off the table's natural owner+subject FKs) and REGISTER it in
            # RegistryHub, so the loop closes end-to-end and the #557 oracle goes clean.
            # Runs BEFORE project_missing_routes: the handler it writes into main.py is
            # then seen as already-routed (deduped), and the registered POST is visible to
            # coverage + the frontend. Detection reuses the single #557 classifier; a
            # no-state-entity app is byte-identical (nothing projected/registered).
            # Extracted to module-level heal_state_write_endpoints so the delivery gate's
            # HEAL-THEN-ENFORCE step (#557 R4-core) runs the SAME projection+registration.
            heal_state_write_endpoints(
                _P(out_dir) / "app" / "backend", registryhub,
                tables=_tbls, owner_scoped_tables=owner_scoped_tables,
                logger=orch._logger)
            # #566f: complete request schemas for LANE-DECLARED creates (superset of #566d,
            # which only reaches #556-projected state-writes) — so the test-user journey probe /
            # chain synth / frontend send the target table's required subject FK(s). Runs in the
            # delivery-time heal loop only (NOT the #557 R4 enforce path). Best-effort.
            try:
                heal_create_endpoint_request_schemas(
                    registryhub, _P(out_dir) / "app" / "backend", logger=orch._logger)
            except Exception:
                pass

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
            # #1156: name the endpoints that project to the SAME body. r13 delivered
            # /api/titles, /api/titles/trending and /api/titles/top10 all answering the
            # same 60 rows; #1155 fixes top10 (a `top10_rank` column exists to rank by)
            # and `trending` has no backing column at all -- a CONTRACT gap only the
            # lane can close. Read from the FINAL main.py, not from this call's
            # bookkeeping: r14's handlers came from backend_skeleton, not from
            # project_missing_routes, and a check living inside either generator sees
            # only half the runs. Never a failed_check: a duplicate list is a quality
            # defect, not a broken app, and a false blocker costs a run (#566j).
            try:
                from .route_projector import identical_projected_bodies_1156
                _dupes = identical_projected_bodies_1156(
                    _P(out_dir) / "app" / "backend")
                if _dupes:
                    orch._logger.warning(
                        "#1156 %d group(s) of declared endpoints project the IDENTICAL "
                        "handler body — they will answer the same rows: %s. Each needs "
                        "either a column to rank/filter by (then the projection uses it, "
                        "#1155) or a narrower contract; the framework will not guess an "
                        "ordering for a segment no column supports.",
                        len(_dupes),
                        join_capped(["+".join(g) for g in _dupes], len(_dupes), cap=6))
            except Exception:
                pass
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
                _file_shadowed_route_task_1202z4(orch, _ea.get("duplicated") or [])
                _report_unreachable_twins_1202zb(orch, out_dir, registryhub)
                _unstaged_seed_media_task_1202zf(orch, out_dir)
                _lane_middleware_task_1202zu(orch, out_dir)
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
            # #784: a model the repair REFUSED to guess on. Silence here used to mean both
            # "nothing was broken" and "something was broken and I picked an actor at random".
            for amb in (res.get("ambiguous") or []):
                orch._logger.warning(
                    "handler FK-alias repair DECLINED (ambiguous owner): %s carries more than "
                    "one owner-ish FK, so a broken reference cannot be resolved to an actor "
                    "without guessing. Left as an AttributeError 500 on purpose — a loud failure "
                    "beats a silent wrong-owner query.", amb)
            # #974: a narrowing DEDUCTION is not a guess, but it is still an owner-scoping
            # decision — it must be as visible as the refusal above, or the next person
            # debugging a too-empty list has no way to know the framework chose the actor.
            for nar in (res.get("narrowed") or []):
                orch._logger.warning(
                    "handler FK-alias repair NARROWED (#974): %s — the second actor table "
                    "references the first, so it is the narrower scope and was chosen. A "
                    "narrower actor can only under-return, never leak across users.", nar)
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
        # #1202qe: the API journey and the browser walk register users and write rows into the
        # app's own data; put the seeded state back when they finish (see verification_isolation).
        from .verification_isolation import isolated_verification_1202qe
        with isolated_verification_1202qe(getattr(orch, "output_dir", None),
                                          "test_user_validation", getattr(orch, "_logger", None)):
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
                # #1202qj: the API journey needs the stack up for its whole length, like the browser
                # walk. Without a lease, tiktok-r127's api_smoke validation ran `down -v` at
                # 23:19:30 in the middle of it and the journey reported "0/0 steps passed".
                from .compose_mutex import stack_lease_1202nx as _lease_1202qj
                with _lease_1202qj(proj, "test-user API journey"):
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
                    # #1038: this printed only `broken`, but PARTIAL is DEFINED as "nothing
                    # broken — only missing endpoints (404/405) or an incomplete MCP surface".
                    # So every PARTIAL was structurally guaranteed to read "BROKEN: []" and name
                    # nothing: 84 of them across r1-r175, 100% of the PARTIAL verdicts. Report
                    # whichever cause actually produced the verdict.
                    from .test_user_validation import describe_non_pass_1038
                    orch._logger.warning(
                        "TEST-USER validation (v%s): %s — %s/%s journey steps passed; %s",
                        version, summ.get("verdict"), summ.get("api_passed"),
                        summ.get("api_steps"),
                        describe_non_pass_1038(
                            summ, (report.get("mcp") or {}) if isinstance(report, dict) else {}))
                # #1203c8: the LLM walk's own findings go to the lane, not just
                # to the report file. P1, never a blocker — see the helper.
                _file_ui_friction_task_1203c8(orch, report.get("ui"), version)
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
        def _walk():
            from .compose_mutex import stack_lease_1202nx   # #1202nx: the walk needs the stack up
            with stack_lease_1202nx(proj, "browser test-user walk"):
                # #1202qt: judge a SERVING stack or none. The walk resolved ports and went; when a
                # validation cycle had just recreated the stack, nginx answered 502 and the walk
                # reported auth_ok=False with console errors on every page and filed a P0 against
                # the frontend (tiktok-r128 16:42, backend still booting). The API journey already
                # health-checks; this one never did.
                from .validation_runner import wait_backend_ready as _ready_1202qt
                if not _ready_1202qt(proj, timeout_s=120):
                    orch._logger.warning(
                        "#1202qt browser test-user SKIPPED: the backend is not serving yet "
                        "(stack recently recreated) - a walk against a booting stack reports "
                        "failures the app does not have.")
                    return {"ran": False, "summary": "backend not serving (stack booting)"}
                # #1202qj: its own data scope, taken on the database the walk actually uses. The
                # enclosing test_user_validation scope snapshots the database as it was when that
                # phase began; r127's stack was recreated before the walk, so the outer restore
                # found no snapshot and the walk's accounts stayed in the app.
                from .verification_isolation import isolated_verification_1202qe
                with isolated_verification_1202qe(proj, "browser_walk", orch._logger):
                    return asyncio.run(run_browser_test_user(
                        base, pages, out_dir, register=True, api_base_url=api_base,
                        demo_login=_seed_demo_login(proj), seed_values=_seed_vals))

        # #1202ne: a walk the stack was recycled under says nothing about the app. tiktok-r125
        # v1.1.0: the verifier's `docker_up(fresh=True)` ran `down -v` 22s into this walk; the
        # login page was captured at that second and the next 12 pages came back blank, so the
        # frontend got a P0 for "12 blank pages" and the release was deferred, while the walk
        # eight minutes earlier had rendered real data on the same code. Compare the stack's
        # containers across the walk; if they changed, discard it and walk once more when the
        # stack is serving again — never judge, dispatch or record from the broken one.
        # #1202ra: hold the lease ACROSS the two identity samples, not only inside the walk.
        # `_walk()` takes its own lease (#1202nx) and releases it when it returns, so the
        # "after" sample was taken with the stack unprotected. tiktok-r129 20:52: the walk
        # finished, validation_runner ran `down -v` at 20:52:29, the sample at 20:52:32 read
        # 3 -> 0 containers, and a walk that had completed on a live stack was discarded as
        # "recycled under". The lease is a token set, not a mutex, so nesting it is free and
        # the inner one still protects the walk itself.
        from .compose_mutex import stack_identity_1202ne, stack_lease_1202nx as _lease_1202ra
        with _lease_1202ra(proj, "browser walk verdict"):
            _stack_before = stack_identity_1202ne(compose)
            report = _walk()
            _stack_after_1202ra = stack_identity_1202ne(compose)
        for _rewalk in (True, False):
            if not report.get("ran") or not _stack_before:
                break
            _stack_after = _stack_after_1202ra   # re-walks below refresh it
            if _stack_after is None or _stack_after == _stack_before:
                break
            orch._logger.warning(
                "#1202ne BROWSER test-user (v%s): the stack's containers changed DURING the "
                "walk (%d -> %d running; a lane or validation recycled it) — this walk's "
                "verdict is discarded, not dispatched (%s)", version, len(_stack_before),
                len(_stack_after), "re-walking once the stack serves" if _rewalk
                else "second walk overlapped a recycle too; no browser verdict this pass")
            if not _rewalk or not _stack_serving_1202ne(base, api_base):
                return None
            with _lease_1202ra(proj, "browser walk verdict"):
                _stack_before = stack_identity_1202ne(compose)
                report = _walk()
                _stack_after_1202ra = stack_identity_1202ne(compose)
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
        # #240: record deterministic ui_flow PASSES for the pages this AUTHENTICATED
        # walk rendered cleanly — so the delivery-gate ui_flow check clears from the
        # reliable framework walk instead of the flaky verifier-LLM manual driving
        # (r29/r30: 3 aborts on ui_flow_failed while the delivered app rendered
        # perfectly). PASS-ONLY: never records a failure, so it can only unblock a
        # working app; the LLM/visual/business-chain gates still catch real breakage.
        try:
            from .test_user_runner import clean_ui_flow_passes
            from .hub_registry import DETERMINISTIC_EVIDENCE_KEY
            _passed_flows = clean_ui_flow_passes(report)
            for _flow in _passed_flows:
                orch.hubs.record_validation_result(
                    task_id=f"ui_flow:{_flow}", status="success",
                    agent="framework-testuser", execution_mode="browser",
                    summary="authenticated browser walk rendered this page cleanly "
                            "(no blank/console-error/login-bounce/fallback)",
                    metadata={"check": "ui_flow", "flow": _flow,
                              # #254: this is a MEASURED result (DOM probe on a real
                              # authenticated page), so it outranks an LLM's report of
                              # the same flow — r51 had 7 of these erased by
                              # evidence-free verifier 'failure' rows and aborted on a
                              # working app.
                              DETERMINISTIC_EVIDENCE_KEY: True})
            if _passed_flows:
                orch._logger.warning(
                    "#240: recorded %s deterministic ui_flow PASS record(s) from the "
                    "authenticated walk: %s", len(_passed_flows), _passed_flows[:12])
        except Exception as _ufexc:
            orch._logger.debug("#240 ui_flow pass recording skipped: %s", _ufexc)
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
                # #1202st: name the PAGES in the title, same class as #1202ss one layer over
                # (the gate-repair table). This title hid 88 distinct defect sets across 17
                # corpus runs, and it is filed once per pre-release walk with no de-dup, so a
                # lane reading the workhub listing saw N identical rows for N different apps'
                # worth of defects. The body already carries the full report; the title
                # carries the pages so the listing is readable. Every list here holds plain
                # page NAMES (test_user_runner builds them as `p["name"]`).
                _pages_1202st = [
                    _p for _k in ("blank_pages", "error_pages", "auth_redirect_pages",
                                  "visual_mismatches", "fake_map_pages")
                    for _p in (report.get(_k) or [])]
                if not _pages_1202st and not report.get("auth_ok"):
                    _pages_1202st = ["login"]   # the walk broke before any page was reached
                from .remediation_dispatcher import _instanced_gate_title_1202ss
                orch.hubs.workhub.create_task(
                    title=_instanced_gate_title_1202ss(
                        "Test-user found UI defects (browser walkthrough) — fix",
                        _pages_1202st),
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
                normalize_frontend_token_key,
                repair_frontend_escaped_backticks, repair_frontend_unimported_icons,
                repair_frontend_default_export_wrapper,
                repair_frontend_cjs_module_exports,
                neutralize_frontend_external_backgrounds,
                enforce_measured_dark_theme)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            # SYNTAX FIRST: the lane intermittently escapes template-literal delimiters
            # (`className={\`...\`}`) → esbuild "Invalid or unexpected token" → the whole
            # `npm run build` fails, so EVERY other repair below is moot until the file
            # parses. Un-escape delimiter backticks before anything else (run-13: this
            # wedged docker_up for many cycles, fixed one file at a time). Runs before each
            # api_smoke docker_up (framework_validation) AND at delivery.
            # #1202sd: a route React Router cannot match, wherever the LANE wrote it.
            # #1202iy fixed the framework's own emitter; every run from r119 through r130
            # still shipped the lane's `/@:username`, so no profile page was reachable from
            # anywhere in the app. Runs beside the other deterministic repairs, before the
            # build that would otherwise ship it.
            try:
                from .frontend_scaffold import repair_frontend_unmatchable_routes_1202sd
                _ur = repair_frontend_unmatchable_routes_1202sd(fe)
                if _ur.get("repaired"):
                    orch._logger.warning(
                        "#1202sd rewrote %s <Route path> that React Router cannot match "
                        "(a `:` must follow a `/`, so `/@:username` compiles to a literal and "
                        "the page is unreachable): %s", _ur.get("routes"), _ur.get("repaired"))
            except Exception as _ur_err:
                orch._logger.debug("#1202sd route repair skipped: %s", _ur_err)
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
            # FIX #194 (§3-6 second half): a re-emitted WHOLE component/const →
            # "X already declared" build FAIL. Byte-identical later copies are
            # removed deterministically; different bodies are only reported.
            try:
                from .frontend_scaffold import repair_frontend_duplicate_declarations
                _dd = repair_frontend_duplicate_declarations(fe)
                if _dd.get("repaired"):
                    orch._logger.warning(
                        "Frontend byte-identical duplicate declarations removed "
                        "(already-declared build-wedge fix): %s", _dd.get("repaired"))
                if _dd.get("conflicts"):
                    orch._logger.warning(
                        "Frontend duplicate declarations with DIFFERENT bodies left "
                        "for the lane: %s", (_dd.get("conflicts") or [])[:6])
            except Exception as _dde:
                orch._logger.debug("duplicate-declaration dedup skipped: %s", _dde)
            # FIX #191 (tiktok-r3 NO-CONVERGENCE): deterministically rewrite the
            # exact fabricated-fallback sites the #175 HARD gate flags
            # (`x.rating || '4.5'` → `x.rating ?? '—'`) — r3's lane thrashed
            # 75min on this edit and the run aborted. Shares the gate's regexes,
            # so the heal clears precisely what the gate blocks.
            try:
                from .frontend_audit import repair_fabricated_fallbacks
                _ff = repair_fabricated_fallbacks(fe / "src")
                if _ff.get("repaired"):
                    orch._logger.warning(
                        "Fabricated member-field fallbacks rewritten to honest empty "
                        "states (#175 gate sites, deterministic): %s",
                        (_ff.get("sites") or [])[:8])
            except Exception as _ffe:
                orch._logger.debug("fabricated-fallback heal skipped: %s", _ffe)
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
            # #490 (netflix r63): the icon heal just injected `import {X} from 'lucide-react'`,
            # but the scaffold-time dep auto-add already ran → lucide-react (and any lane-late
            # import) is missing from package.json → the safe-icon plugin's `import * as _real
            # from 'lucide-react'` fails the vite build ("missing npm dependency") → docker_up
            # red → verification_checklist_not_ready (r63 wedged ONE blocker from first delivery).
            # Re-sync package.json deps against the final src tree, POST-heal. Generalizes to any
            # import added after scaffold. Idempotent; best-effort.
            try:
                from .frontend_scaffold import sync_frontend_package_json_deps
                _dep = sync_frontend_package_json_deps(fe)
                if _dep.get("added"):
                    orch._logger.warning(
                        "Frontend package.json deps synced post-heal (#490, missing-npm-dep "
                        "build fix): %s", _dep.get("added"))
            except Exception as _depe:
                orch._logger.debug("package.json dep sync skipped: %s", _depe)
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
            # #317: canonicalize the auth-token localStorage key so api.js/AuthProvider/
            # pages can't mismatch (r85/r86 ui_flow wedge: api.js read 'tt_token' while
            # pages wrote 'token'/'access_token' → token unreadable → app looked logged
            # out → signup/feed flow failed). Framework enforces one key; lane can't drift.
            _tk = normalize_frontend_token_key(fe)
            if _tk.get("normalized"):
                orch._logger.warning(
                    "Frontend auth-token localStorage key canonicalized to 'access_token' "
                    "(lane used a divergent key api.js/pages disagreed on): %s", _tk.get("normalized"))
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
            # FIX #209 (tiktok-r14 autopsy, companion to #208): the lane renders a LIGHT
            # page for a DARK reference (`min-h-screen bg-zinc-50 text-zinc-900`, nav
            # `bg-white`) — a page-level light background paints over the measured black
            # body (#208) → the app reads ~0.5 fidelity despite the palette being wired in.
            # The measured colors reach the theme tokens but the lane hand-writes generic
            # zinc/white classes instead (visual GAP 3, soft consumption). When the MEASURED
            # theme is dark, invert the common light-neutral utilities to dark equivalents
            # so the page renders dark like the reference — deterministic, gated on
            # theme==dark (light apps untouched), brand/accent utilities preserved.
            try:
                _dk = enforce_measured_dark_theme(fe)
                if _dk.get("replacements"):
                    orch._logger.warning(
                        "Frontend light-neutral utilities darkened to the MEASURED dark "
                        "theme (%s swaps across %s files; lane wrote a light page for a dark "
                        "reference): %s", _dk.get("replacements"),
                        len(_dk.get("darkened") or []), (_dk.get("darkened") or [])[:8])
            except Exception as _dke:
                orch._logger.debug("measured-dark-theme enforcement skipped: %s", _dke)
            # FIX #111 (companion to #75b, runs 24+26 autopsy): external <img src> hosts
            # (pravatar/unsplash/placeholder — seen in live artifacts, in BOTH frontend
            # source and seed rows) can never resolve in the offline sandbox → the
            # broken-image glyph is a permanent visual-score wound. Localize image-signaled
            # external URLs to staged /assets/ by filename token; one that matches nothing is
            # LEFT ALONE (#1202qo — a generated placeholder glyph is a substitute that hides
            # the failure). Navigation hrefs/API bases are never image-signaled → untouched.
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
                # #1202jq: which BRANCH each of those took. A staged real asset and a
                # generated glyph are very different apps, and only the file list was ever
                # reported — so a run whose imagery went entirely to placeholders looked
                # like one that matched real media every time. tiktok-r109 is the instance.
                _ph = int(_li.get("unmatched") or 0) + int(_ls.get("unmatched") or 0)  # #1202qo
                _st = int(_li.get("staged") or 0) + int(_ls.get("staged") or 0)
                # #1202re: a THIRD outcome now exists -- a real staged asset chosen by design-
                # prep's own category when no filename token matched. Counting it as "staged"
                # would hide how often the token match actually wins; counting it as unmatched
                # would say the picture is broken when it is a real photograph.
                _cat1202re = (int(_li.get("category_1202re") or 0)
                              + int(_ls.get("category_1202re") or 0))
                if _cat1202re:
                    orch._logger.warning(
                        "#1202re %d image ref(s) matched no staged asset BY NAME and were bound "
                        "to a real staged asset of the right kind instead (design-prep stages "
                        "media under content-hash names, which share no token with a semantic "
                        "URL -- r130 matched 5 of 55 by name, r129 matched 0 of 27). These are "
                        "photographs from this env's own reference material, not placeholders.",
                        _cat1202re)
                if _ph:
                    # #1202jq: the counts, and the staged-asset population beside them —
                    # WITHOUT naming a repair. "The picture was never staged" was the first
                    # draft and it is false: r109 and r110 stage the same 144 assets and only
                    # r109's refs fell back. A high share means these URLs matched nothing by
                    # filename token, which is a different thing from nothing being there.
                    try:
                        _pool = len([q for q in (fe / "public" / "assets").rglob("*")
                                     if q.is_file() and "placeholders" not in q.parts])
                    except Exception:
                        _pool = -1
                    orch._logger.warning(
                        "IMAGE LOCALIZATION: %d ref(s) matched a STAGED asset by filename "
                        "token; %d matched nothing and were LEFT AT THEIR EXTERNAL URL "
                        "(%.0f%%), which resolves nowhere in the offline sandbox -- those "
                        "<img> render as the browser's broken-image mark (#1202qo: a "
                        "generated glyph in their place made a missing picture look like a "
                        "working one). %s real asset(s) are staged, so what failed is the "
                        "filename-token match, not the staging.",
                        _st, _ph, 100.0 * _ph / max(1, _ph + _st),
                        _pool if _pool >= 0 else "an unknown number of")
            except Exception as _lie:
                orch._logger.debug("external-image localization skipped: %s", _lie)
            # CJS→ESM FIRST: a lane authors api.js in CommonJS (`module.exports = api`)
            # which Vite's ESM build turns into an EMPTY default import → `api.isAuthed
            # is not a function` white-screens every auth-gated page (netflix r58, live;
            # r5/r51/r54). Convert to ESM BEFORE the export reconcilers below so they see
            # a proper `export default api` (and default_api_import never appends the
            # bogus `export default {};` that cements the empty object).
            # #1202rb: a stylesheet nothing imports never reaches the bundle, and Vite says
            # nothing about it. r129's `visual-fixes.css` carried 20 of LiveDiscoverPage's
            # class names; the page shipped as an unstyled column of text and scored 0.14.
            try:
                from .frontend_scaffold import import_orphan_stylesheets_1202rb
                _orph = import_orphan_stylesheets_1202rb(fe)
                if _orph.get("imported"):
                    orch._logger.warning(
                        "#1202rb %d stylesheet(s) under src/ were imported by NOTHING, so Vite "
                        "dropped them and the pages using their classes shipped unstyled: %s. "
                        "Imported from %s, last, so they override what came before.",
                        len(_orph["imported"]), _orph["imported"], _orph.get("entry"))
            except Exception as _orphe:
                orch._logger.debug("orphan-stylesheet import skipped: %s", _orphe)
            try:
                _cjs = repair_frontend_cjs_module_exports(fe)
                if _cjs.get("repaired"):
                    orch._logger.warning(
                        "Frontend CJS module.exports converted to ESM (Vite interop): %s",
                        _cjs.get("repaired"))
            except Exception as _cjse:
                orch._logger.debug("frontend cjs→esm repair skipped: %s", _cjse)
            rep = repair_frontend_api_exports(fe)
            if rep.get("repaired"):
                orch._logger.warning(
                    "Frontend api.js reconciled: aliased=%s stubbed=%s",
                    rep.get("aliased"), rep.get("stubbed"),
                )
            # #1108: the scaffolded login page stores the token under 'access_token';
            # a lane api.js that namespaces its own key reads null, sends no
            # Authorization header, and every authenticated request 401s — the user
            # logs in and the app stays on the login wall. Driven in a real browser,
            # tiktok-r54 went from 2053 chars of rendered text and 17 401s to 14668
            # and 0. Runs AFTER the api.js repairs above so it sees the final key.
            try:
                from .frontend_scaffold import repair_token_key_mismatch_1108
                _tk = repair_token_key_mismatch_1108(fe)
                if _tk.get("added"):
                    orch._logger.warning(
                        "Frontend token key reconciled — the login page now also stores "
                        "the key api.js reads: %s", _tk.get("added"))
            except Exception as _tke:
                orch._logger.debug("token key repair skipped: %s", _tke)
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
            # #1202cb: a DEFAULT import against a named-only target breaks Rollup the same
            # way, and when neither a default export nor a matching name exists there is no
            # repair that is not a guess. Say so HERE, where it is cheap, rather than letting
            # it surface as a failed docker build and a P0 several minutes later.
            for _u in (_nd.get("unrepairable") or [])[:4]:
                orch._logger.warning("#1202cb frontend build-breaker: %s", _u)
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
            # #488: a DECLARED page routed in App.jsx that shipped as an INERT STUB (exists but a
            # lone heading, no api/behavior) trips deliverability_ui_page_unwired and blocks
            # delivery (r61 LandingPage). scaffold_missing_local_pages only fills MISSING files, so
            # overwrite existing DEFINITIVE stubs with the real projection (guarded: never clobbers
            # a real page). Clears the stub gate deterministically + lifts fidelity for all apps.
            try:
                from .frontend_scaffold import repair_stub_declared_pages
                _sp = repair_stub_declared_pages(fe, ui_pages=_uip)
                if _sp.get("repaired"):
                    orch._logger.warning(
                        "Frontend stub declared-pages filled with real projected content "
                        "(#488, deliverability_ui_page_unwired fix): %s", _sp.get("repaired"))
            except Exception as _spe:
                orch._logger.debug("stub declared-page fill skipped: %s", _spe)
            # #495 (netflix r66 task#47): a DECLARED page routed in App.jsx that shipped as the
            # FRAMEWORK FALLBACK (the generic data-list placeholder, not the real projected page)
            # trips deliverability_ui_page_unwired ("component X is a framework fallback page
            # (generic list)") and blocks delivery — and the LLM frontend lane repeatedly fails to
            # author it (r66 wedged ~7min on ProfilesPage). Overwrite a CONFIRMED fallback (the
            # gate's own _is_generic_fallback_page fingerprint) with the real projection — the
            # sibling of #488 for STUBS; guarded so a real page is never clobbered.
            try:
                from .frontend_scaffold import repair_fallback_declared_pages
                _fp = repair_fallback_declared_pages(fe, ui_pages=_uip)
                if _fp.get("repaired"):
                    orch._logger.warning(
                        "Frontend framework-fallback declared-pages overwritten with real "
                        "projected content (#495, deliverability_ui_page_unwired fix): %s",
                        _fp.get("repaired"))
            except Exception as _fpe:
                orch._logger.debug("fallback declared-page fill skipped: %s", _fpe)
            # #493 (netflix r60/r64 task#47): a DEAD nav link (`to="/x"`/`navigate("/x")` whose
            # absolute target resolves to no App.jsx <Route>) trips deliverability_dead_nav_link
            # and blocks delivery — and the LLM frontend lane repeatedly fails to clear it (r60
            # stalled 81min; r64 shipped 2× persistent /profiles + /account links, never cleared).
            # Deterministically REPOINT each LLM-invented dead target (Case 3: not a declared
            # App.jsx route AND not a reference screen) at the nearest existing route via a MINIMAL
            # target-literal swap (no element removal → no JSX-corruption risk). Declared (Case 1)
            # / reference (Case 2) targets are LEFT for route-injection / the page projector.
            # reference_routes come from the design dir (app_root.parent = fe.parent.parent).
            try:
                from .frontend_scaffold import repair_dead_nav_links
                from .frontend_audit import reference_screen_routes
                _dnl = repair_dead_nav_links(
                    fe, reference_routes=reference_screen_routes(fe.parent.parent))
                if _dnl.get("repaired"):
                    orch._logger.warning(
                        "Frontend dead nav links repointed at existing routes "
                        "(#493, deliverability_dead_nav_link fix): %s", _dnl.get("repaired"))
            except Exception as _dnle:
                orch._logger.debug("dead-nav-link repoint skipped: %s", _dnle)
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
                        # #231 (r21): a DEPRECATED path must not count as
                        # registered — it made the reconciler early-exit on the
                        # dead path the frontend was still calling (/api/feed 404).
                        if str(_v.get("status") or "").lower() == "deprecated":
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
            _write_py_995(main_py, "\n".join(lines) + "\n", what="repair_backend_as_wiring")
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
            _write_py_995(main_py, src.rstrip() + entry, what="repair_backend_entrypoint")
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
        # #322: after merging the lane branches, guarantee the integration seed is the
        # authoring lane's POPULATED seed, not the {} placeholder — else deliverability
        # chronically 'authored seed missing'-blocks delivery (r86/r91). See fn docstring.
        try:
            reconcile_integration_seed(repo, logger=getattr(orch, "_logger", None))
        except Exception:
            pass
        # #512: after the real seed reaches integration, distribute distinct real staged
        # posters/backdrops over degenerate catalog media (a single repeated crop → varied
        # real poster wall) — the dominant content-screen Part-A fidelity lever. Best-effort.
        try:
            distribute_seed_media(repo, logger=getattr(orch, "_logger", None))
        except Exception:
            pass

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
            # #1148: the guard below asks whether the SUBTREE ROOT exists, and #691's own
            # mechanism can strand a file INSIDE a subtree that does exist. netflix-local-r11:
            # `app/` was present (backend + frontend), so this loop skipped — while
            # `app/database/init/01_init.sql` (2855 bytes, written by this very delivery) sat
            # on `main` at 43ef69a, which is NOT an ancestor of `integration`, exactly as #691
            # describes for mcp_server. The file never reached the delivered tree and
            # `database_sql_missing` blocked 20 of that run's 21 gate evaluations — its
            # dominant cause of failure. r10, same code, had it on integration and delivered
            # its gate past that check.
            #
            # So the recovery set is the delivery gate's own required ARTIFACTS, not just the
            # three top-level directories: a partially-present `app/` must not hide a missing
            # one. `app/database` is checked for a .sql because that is literally what
            # `database_sql_missing` tests (`(output_dir/"app/database").glob("**/*.sql")`).
            _subs_1148 = ["app", "mcp_server", "docker"]
            try:
                _appdb = repo / "app" / "database"
                if (repo / "app").exists() and not any(_appdb.glob("**/*.sql")):
                    _subs_1148.append("app/database")
            except Exception:
                pass
            # #1150: #1148 special-cased ONE stranded artifact; the mechanism strands
            # arbitrary FILES. Measured on the kept repos, every run has exactly the same
            # shape — `main` holds one orphan commit ("framework delivery: backend skeleton
            # + frontend infra + projections") that `integration` never sees, and the
            # release is cut from `integration`:
            #
            #   r5   main..integration 106   integration..main 1   files stranded: 0
            #   r8   main..integration  79   integration..main 1   files stranded: 0
            #   r11  main..integration 108   integration..main 1   files stranded: 2
            #
            # Most of the orphan's ~500 files escape because the projector rewrites them
            # every round. The tail does not, and WHICH files fall in it varies per run:
            # r11 stranded `app/database/init/01_init.sql` (#1148, which killed that run)
            # AND `app/frontend/src/pages/LoginPage.jsx`, which a subtree-root check can
            # never see because `app/` exists. Enumerating subtrees is whack-a-mole; ask
            # the question at the granularity the damage happens at.
            #
            # Safety: restore ONLY a file this branch has never known. If a lane deliberately
            # deleted it, HEAD's history carries that file and we leave it alone — absence is
            # then a decision, not an accident. Best-effort throughout: a failed sweep must
            # fall through to the subtree loop below, never break the delivery commit.
            try:
                _roots_1150 = ("app/", "mcp_server/", "docker/")
                # Ask for the FRAMEWORK'S OWN stranded delivery commit, not for every
                # commit off HEAD. Measured on r11, a bare `--all --not HEAD` returns ~200
                # commits — every lane branch's un-merged WIP — and the one that matters
                # sorts LAST, so a cap would have missed it while the rest would have
                # dragged un-merged lane work into the release. Grepping the framework's
                # own commit subject yields exactly one commit in r8 and in r11: the
                # orphan this whole defect family is about.
                _rc_o, _orphans, _ = _run_git(
                    ["log", "--all", "--not", "HEAD", "--format=%H",
                     "--grep=^framework delivery"], cwd=repo)
                _rescued_1150 = []
                for _osha in (_orphans or "").split()[:40]:
                    _rc_l, _files, _ = _run_git(
                        ["show", "--name-only", "--format=", _osha], cwd=repo)
                    if _rc_l != 0:
                        continue
                    for _rel in (_files or "").splitlines():
                        _rel = _rel.strip()
                        if not _rel or not _rel.startswith(_roots_1150):
                            continue
                        if (repo / _rel).exists():
                            continue
                        _rc_h, _hist, _ = _run_git(
                            ["log", "HEAD", "-1", "--format=%H", "--", _rel], cwd=repo)
                        if (_hist or "").strip():
                            continue  # this branch knows the file; its absence is deliberate
                        _rc_c, _, _ = _run_git(["checkout", _osha, "--", _rel], cwd=repo)
                        if _rc_c == 0 and (repo / _rel).exists():
                            _rescued_1150.append(_rel)
                if _rescued_1150:
                    orch._logger.warning(
                        "#1150 recovered %d stranded delivery file(s) — committed on a branch "
                        "the release is not cut from, and this branch has never known them: "
                        "%s", len(_rescued_1150),
                        join_capped(sorted(_rescued_1150), len(_rescued_1150), cap=12))
            except Exception as _exc_1150:
                orch._logger.debug("#1150 stranded-file sweep skipped: %s", _exc_1150)
            for sub in _subs_1148:
                if not (repo / sub).exists() or (
                        sub == "app/database" and not any((repo / sub).glob("**/*.sql"))):
                    # #691: SAY WHEN A DELIVERY SUBTREE IS NOT THERE TO SHIP.
                    # This skip was silent, and one of the three is routinely absent: the MCP
                    # server. r145 and r146 both log "mcp_server/app/: 15 tool(s) emitted, 15
                    # registered" and both end with NO mcp_server/ in the delivered tree —
                    # 125 of 144 corpus runs are missing it too.
                    #
                    # The mechanism, identical in both runs: the writer commits mcp_server/ on
                    # `main` (r146 60c738f, r145 0b0e81b), delivery runs on `integration`, and
                    # `git merge-base --is-ancestor` says main is NOT an ancestor of integration.
                    # So at delivery time the directory genuinely is not in the working tree and
                    # this guard is correct to skip — but the registry still advertises the
                    # surface (registryhub_mcp_registry: 16 entries in r146), so the run ships a
                    # contract it does not contain and nothing says so.
                    #
                    # A silently absent delivery subtree must not be silent: WARNING when a hub
                    # still claims the surface, INFO otherwise. #691b below then RESTORES it —
                    # the reflog turned what looked like a branch-topology preference into an
                    # ordering defect with one correct repair. See its comment for the timeline.
                    try:
                        _claimed = 0
                        if sub == "mcp_server":
                            # Read the STORE, not the object graph: MCPRegistry is its own
                            # class rather than a registryhub mixin, so a getattr chain here
                            # would be a guess that silently evaluates to 0 and never warns.
                            # The store file is derivable from `repo` alone.
                            import json as _json
                            _f = repo / "shared" / "hubs" / "registryhub_mcp_registry.json"
                            if _f.exists():
                                _v = _json.loads(_f.read_text() or "{}")
                                _claimed = sum(
                                    1 for k, r in (_v or {}).items()
                                    if not str(k).startswith("_")
                                    and isinstance(r, dict)
                                    and r.get("kind") in ("tool", "server")
                                )
                        _msg = ("delivery subtree %r is not in the working tree at "
                                "commit time — nothing from it will ship")
                        if _claimed:
                            # "entries", not "tools": the store holds 1 server + 15 tools in
                            # both measured runs, and saying "16 tools" would contradict the
                            # writer's own "15 tool(s) emitted, 15 registered" log line.
                            orch._logger.warning(_msg + " while the registry still advertises "
                                                 "%d registered MCP entries (servers + tools). "
                                                 "Check which BRANCH wrote it: the delivery "
                                                 "commit runs on the integration branch and a "
                                                 "subtree committed only on `main` is invisible "
                                                 "here.", sub, _claimed)
                        else:
                            orch._logger.info(_msg, sub)
                    except Exception:
                        pass
                    # #691b: RESTORE IT RATHER THAN SHIP WITHOUT IT.
                    # Warning alone leaves the run shipping a registry it does not honour, and
                    # the reflog says this is an ORDERING defect with a correct repair, not a
                    # topology preference. r146, to the second:
                    #
                    #   22:53:11  bootstrap                        26067f8   on main
                    #   23:10:47  "branch: Created from agent/backend"  -> integration planted
                    #             at 26067f8. `create_branch_at` plants a REF and deliberately
                    #             does not move HEAD, so HEAD stays on main.
                    #   23:12:41  first framework delivery commits ON MAIN  60c738f  <- the
                    #             mcp_server/ write lands here, on the wrong side of the fork
                    #   later     HEAD switches to integration; git removes the now-untracked
                    #             subtree from the working tree, and every later delivery
                    #             (23:44, 23:46, 23:47, 23:48) finds it absent
                    #
                    # `git diff --name-status integration main` gives the whole blast radius as
                    # exactly three files — the mcp_server subtree and nothing else. app/ and
                    # docker/ escape because the projector rewrites them every round; the MCP
                    # writer runs ONCE per run, so it alone has no second chance. That is why
                    # this subtree, and only this subtree, is missing from 125 of 144 runs.
                    #
                    # So: if some commit in this repo has the subtree and the working tree does
                    # not, take it. Best-effort throughout — a failed restore must fall through
                    # to the original skip, never break the delivery commit.
                    try:
                        rc_f, sha, _e = _run_git(
                            ["log", "--all", "-1", "--format=%H",
                             "--diff-filter=AM", "--", sub], cwd=repo)
                        sha = (sha or "").strip()
                        if rc_f == 0 and sha:
                            rc_r, _o2, _e2 = _run_git(["checkout", sha, "--", sub], cwd=repo)
                            if rc_r == 0 and (repo / sub).exists():
                                orch._logger.warning(
                                    "recovered delivery subtree %r from %s — it was committed "
                                    "on a branch the release is not cut from. Shipping it.",
                                    sub, sha[:9])
                            else:
                                continue
                        else:
                            continue
                    except Exception:
                        continue
                rc, _o, _e = _run_git(
                    ["add", "-A", "--", sub,
                     ":(exclude)**/__pycache__/**", ":(exclude)**/*.py[cod]"],
                    cwd=repo)
                staged_any = staged_any or (rc == 0)
            # #1202gf: THE GATE'S OTHER REQUIRED ARTIFACT NEVER SHIPPED. `required_files`
            # in delivery_gate is ["docker/docker-compose.yml", "design/README.md"], and
            # only the first is under a directory this loop stages. Measured across the 136
            # kept repos: 113 have design/README.md in the working tree and **2** have it
            # committed to integration -- so in 111 of 113 the gate passes on a file the
            # release does not carry. It is consumer-facing (the app's name, its whole API
            # surface, and the `docker compose up` line), which is exactly what someone
            # receiving the environment needs.
            #
            # Staged as a single FILE, never as `design/`: that directory also holds the
            # reference images and screenshots, 170-265 MB of them, and #1202cs exists
            # because they must not enter the run's git history.
            try:
                if (repo / "design" / "README.md").is_file():
                    _rc_gf, _o_gf, _e_gf = _run_git(
                        ["add", "-A", "--", "design/README.md"], cwd=repo)
                    staged_any = staged_any or (_rc_gf == 0)
            except Exception as _exc_gf:
                orch._logger.debug("#1202gf README stage skipped: %s", _exc_gf)
            if not staged_any:
                return
            # #1014: name the lane-owned files this phase is about to commit.
            #
            # r164's oscillation-filtered sweep says the framework genuinely clobbers 18
            # files — 12 pages, BrowseHeader (alt=99), App.jsx (alt=56, DECLARED lane-owned),
            # api.jsx, AuthForm, seed_data.json — and every framework-side commit on all
            # three surfaces carries THIS message. So one bulk phase writes them all, and
            # precise wiring needs to know which projector inside it touched what.
            #
            # Reading the code to find out has a 0-for-3 record today: reconcile_integration_
            # seed, wire_owned_list_shell_535 and reconcile_integration_frontend_app_jsx all
            # look like clobberers by name and all three are correctly guarded. The one real
            # offender (#1013) was found from runtime evidence. So: log it instead of guessing.
            try:
                _rc2, _staged, _ = _run_git(["diff", "--cached", "--name-only"], cwd=repo)
                if _rc2 == 0 and _staged:
                    _LANE_1014 = ("app/frontend/src/pages/", "app/frontend/src/components/",
                                  "app/frontend/src/services/", "app/frontend/src/App.jsx",
                                  "app/backend/custom_routes.py", "app/backend/seed_data.json")
                    _hits = [p for p in _staged.splitlines()
                             if p.strip() and any(p.strip().startswith(x) for x in _LANE_1014)]
                    if _hits:
                        orch._logger.warning(
                            "#1014 framework delivery is committing %d LANE-OWNED path(s): %s",
                            len(_hits), join_capped(_hits, len(_hits), cap=10))
            except Exception:
                pass
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
