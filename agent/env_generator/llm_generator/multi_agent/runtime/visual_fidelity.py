"""Framework-owned VISUAL FIDELITY gate.

The pipeline's goal is an app whose UI matches the provided reference images.
Visual design is the FRONTEND LANE's job (it reads the references and builds the
screens); this module is the GATE that enforces it: after api_smoke passes, it
screenshots the running frontend on the routes the reference images depict,
asks a vision model to compare each (reference, screenshot) pair, and returns a
structured verdict with CONCRETE deviations. Failures feed back to the frontend
lane as actionable remediation tasks — quality by gate, content by agent.

Deterministic in wiring (route mapping, capture, thresholding), LLM only in the
judgment. Both the capture and the judge are injectable for tests.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .validation_runner import _service_host_port


def _resolve_app_port(resolver, service_names):
    """FIX #207: the app's OWN host port for the first resolvable service name, or
    None. NEVER a magic fallback (:8080/:3001 host a persistent gmaps demo — a
    fixed fallback made the visual gate screenshot the WRONG app and score it
    against this env's references; r13 scored a Google-Maps login). None → the
    caller must SKIP honestly, not capture a possibly-unrelated service."""
    for _svc in service_names:
        try:
            _p = resolver(_svc)
        except Exception:
            _p = None
        if _p:
            return int(_p)
    return None

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference-image → route mapping. Reference screenshots are conventionally
# named after the screen they depict; keyword order matters (create_account
# must win over create). A name that maps to no route is skipped (reported).
# ---------------------------------------------------------------------------
# #356: the keyword table keeps its ROUTE column and loses its AUTH column.
#
# The route half is real capability: `home` -> /feed, `search` -> /explore,
# `video` -> /reels are SEMANTIC synonyms no filename-token matcher can derive,
# and every entry is gated on the app actually serving that route. #352's
# authoritative classifications cover MEASURED screens, but an unmeasured
# reference image still needs this.
#
# The auth half was the defect. Only two rows ever set False, they matched on a
# filename token, and after the loop's `break` the flag was applied whether or
# not that row's ROUTE had been used — so any reference merely CONTAINING
# "register" or "signin" was captured logged-out, and a protected page then
# renders the login wall and scores ~0. (The True rows were always inert: True
# is the default.) Auth now follows the RESOLVED route.
_ROUTE_KEYWORDS: tuple = (
    (("create_account", "signup", "sign_up", "register"), "/signup"),
    (("login", "sign_in", "signin"), "/login"),
    (("home", "feed", "timeline"), "/feed"),
    (("search", "explore", "discover"), "/explore"),
    (("video", "reel", "watch"), "/reels"),
    (("create", "new_post", "upload", "compose"), "/create"),
    (("profile", "account"), "/profile"),
    (("message", "inbox", "direct", "dm"), "/messages"),
    (("saved", "bookmark", "collection"), "/saved"),
    (("people", "suggested", "friends"), "/people"),
)
# Public BY CONSTRUCTION: the framework injects these itself and a login page
# must be reachable logged-out. A fact about framework-owned routes, not a guess
# about the app's domain.
_FRAMEWORK_PUBLIC_ROUTES: frozenset = frozenset({"/login", "/signup"})

# Home/landing screens conventionally live at the root route in ANY app, so a
# "home"/"dashboard"/… reference maps to "/" when the app serves it — domain-
# agnostic, independent of the social catalog above.
_HOME_STEMS: frozenset = frozenset(
    {"home", "index", "landing", "main", "dashboard", "overview", "start"})

# ---------------------------------------------------------------------------
# UI-fidelity dimensions — KNOWLEDGE for the models, not hard rules. The same
# dimensions serve two prompts: the frontend agent receives them as DESIGN
# PREMISES when replicating the references, and the vision judge receives them
# as the evaluation rubric. Similarity itself is the model's holistic judgment
# (image similarity cannot be computed by rules); per-dimension notes exist so
# failures come back as actionable, structured feedback.
_DIMENSIONS: tuple = (
    {"key": "layout", "title": "Layout structure",
     "rubric": (
        "Navigation paradigm and placement: top bar / left rail / bottom tabs / "
        "hamburger; sticky or scrolling; collapsed (icons-only) vs expanded (with "
        "labels). Page skeleton: single column / multi-column / grid; presence and "
        "width of sidebars; header/footer presence. Content max-width and centered "
        "vs full-bleed. Relative proportions and positions of major regions; which "
        "region dominates. Section ORDER down the page (hero, feed, panels). "
        "Alignment discipline: consistent gutters and grid lines. Scroll paradigm "
        "visible in the shot: vertical feed, horizontal carousels/rows, pagination. "
        "PER-SCREEN CHROME: each screen carries exactly the chrome ITS OWN "
        "reference shows — no more, no less. Chrome the reference lacks (or "
        "missing chrome the reference shows) is a MAJOR layout deviation. "
        "Consequence for routing: screens whose reference shows no shared "
        "chrome cannot live inside the shared layout wrapper — give them "
        "their own router branch.")},
    {"key": "components", "title": "Component completeness & function",
     "rubric": (
        "INVENTORY: every component visible in the reference exists in the "
        "implementation — nav items (count them), search bars, buttons, cards, "
        "lists, tables, charts, forms and inputs, dropdowns, tabs, chips, badges "
        "and notification dots, avatars, breadcrumbs, pagination, floating action "
        "buttons, banners, modals/launchers, footers. FUNCTION: each has the "
        "equivalent affordance (a follow button, a like/comment/share row, a "
        "search input with placeholder — not just a lookalike box). STATES: "
        "selected/active highlighting, counters, disabled looks where the "
        "reference shows them. PLACEMENT of each component matches. Penalize "
        "INVENTED components the reference does not have (visual noise). List "
        "every MISSING or functionally different component by name in `missing`.")},
    {"key": "style", "title": "Style character",
     "rubric": (
        "Overall personality: minimal vs ornate/flashy; professional/utilitarian "
        "vs playful/marketing. Surface treatment: flat / subtle-depth / "
        "glassmorphism / neumorphism / skeuomorphic. CORNER RADII scale: square / "
        "slightly rounded / heavily rounded / pill — and consistency across "
        "components. Shadows and elevation: none / soft diffuse / hard; layering "
        "depth. Borders and dividers: hairline vs heavy; divider-separated vs "
        "whitespace-separated. Density and whitespace rhythm: padding scale, "
        "compact-utility vs airy. Decoration level: gradients, blurs, textures, "
        "illustrations. One design language used consistently across the screen.")},
    {"key": "color", "title": "Color & contrast",
     "rubric": (
        "Scheme: light / dark / mixed; background hierarchy (page base vs card "
        "surface vs elevated surface). Brand and accent hues: are they the SAME "
        "colors, applied in the same places (CTAs, links, active states, "
        "highlights)? Neutral palette temperature: warm vs cool grays. Semantic "
        "colors (success/error/warning) where shown. Contrast level: punchy "
        "high-contrast vs muted/soft. Overall colorfulness: monochrome with one "
        "accent vs multi-color. Gradients: presence, direction, hues. Text "
        "readability on its surfaces.")},
    {"key": "typography", "title": "Typography",
     "rubric": (
        "Font character: serif / sans / mono / display; geometric vs humanist; "
        "brand wordmark fidelity. Size hierarchy: number of distinct levels and "
        "the contrast between title/subtitle/body/caption. Weight usage: where "
        "bold/semibold sit vs regular. Case and emphasis: all-caps labels, letter "
        "spacing. Line height and paragraph rhythm; text alignment (left vs "
        "centered). Secondary/metadata text styling (timestamps, counts, captions "
        "— size and gray level).")},
    {"key": "iconography", "title": "Iconography & imagery",
     "rubric": (
        "Icon style: line/outline vs filled vs duotone vs emoji vs custom brand "
        "set; stroke weight and corner style; size consistency and alignment with "
        "labels. Avatars: shape (circle / rounded square), sizes, ring or border "
        "treatments. Media/imagery: aspect ratios, crop style (cover vs contain), "
        "corner radius on images, grid gaps. Logo rendering fidelity (wordmark vs "
        "symbol, correct style). Empty-state and placeholder visual style.")},
    {"key": "copy", "title": "UI copy & labels",
     "rubric": (
        "Wording of UI chrome (NOT user content): nav labels, button text and CTA "
        "phrasing ('Log in' vs 'Sign in'), section headings, input placeholders, "
        "helper/footer text, terminology consistency with the reference product. "
        "Language and tone match (terse vs friendly). Casing conventions.")},
)


def design_premises_text() -> str:
    """The dimensions as DESIGN PREMISES for the frontend agent's prompt — one
    compact block so the lane designs against the same criteria it will be
    judged on."""
    lines = ["When replicating the reference designs, match them along these "
             "dimensions (you will be evaluated on the same ones):"]
    for d in _DIMENSIONS:
        lines.append(f"- {d['title']}: {d['rubric']}")
    return "\n".join(lines)


_VIEWPORT = {"width": 1380, "height": 900}


def load_screen_classifications(project_dir: Any) -> Dict[str, Dict[str, Any]]:
    """FIX #132 — the AUTHORITATIVE reference->screen classification from
    design_system.json (the design-prep analyst labels every reference with
    kind=page|overlay, requires_auth and a suggested route BY LOOKING AT THE
    PIXELS). Returns {screen_name: {kind?, requires_auth?, route?}} keyed by the
    screens[].name (= reference filename stem). Empty dict on any failure —
    the filename heuristics below remain the fallback."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        dsp = Path(project_dir) / "design" / "design_system.json"
        if not dsp.is_file():
            return out
        ds = json.loads(dsp.read_text(encoding="utf-8"))
        for s in ds.get("screens") or []:
            if not isinstance(s, Mapping) or not s.get("name"):
                continue
            rec: Dict[str, Any] = {}
            for k in ("kind", "requires_auth", "route"):
                if s.get(k) is not None:
                    rec[k] = s[k]
            if rec:
                out[str(s["name"])] = rec
    except Exception:
        return {}
    return out


def load_ui_pages(project_dir: Any) -> List[Dict[str, Any]]:
    """FIX #416 — the app's REGISTERED ui_pages (shared/hubs/registryhub_ui_pages.json)
    as [{name, route, component}] for every page carrying a real route. This is the
    app's OWN authoritative statement of which routed pages it actually built. The
    visual gate uses it to link a measured design screen to the ACTUAL app route of
    its page (routes are the stable key — a param route like /title/:id no filename
    token derives), and to catch a real page the pixel-only design-prep analyst
    (#132) mislabeled an overlay. Empty on any failure — the heuristics remain."""
    out: List[Dict[str, Any]] = []
    try:
        up = Path(project_dir) / "shared" / "hubs" / "registryhub_ui_pages.json"
        if not up.is_file():
            return out
        raw = json.loads(up.read_text(encoding="utf-8"))
        if isinstance(raw, Mapping):
            items = [{"name": v.get("name") or k, "route": v.get("route"),
                      "component": v.get("component")}
                     for k, v in raw.items()
                     if k != "_meta" and isinstance(v, Mapping)]
        elif isinstance(raw, list):
            items = [v for v in raw if isinstance(v, Mapping)]
        else:
            items = []
        for v in items:
            route = str(v.get("route") or "").strip()
            if not route:
                continue
            out.append({"name": str(v.get("name") or ""), "route": route,
                        "component": str(v.get("component") or "")})
    except Exception:
        return []
    return out


# #416: the #226 screen<->page reconciliation vocabulary, kept as a LOCAL copy of
# frontend_scaffold._semantic_tokens_226 / _FUZZY_STOPWORDS_226 so the gate can
# link a design screen to a registered ui_page WITHOUT importing the heavy
# frontend_scaffold module (this file is exec'd in isolation under test). Keep in
# sync with frontend_scaffold. Generic layout/UI words never carry a match alone.
_UI_PAGE_STOPWORDS: frozenset = frozenset({
    "page", "screen", "view", "views", "main", "own", "my", "the", "of", "and",
    "grid", "list", "menu", "modal", "empty", "logged", "out", "in", "panel",
})


def _screen_name_tokens(*texts) -> set:
    """Lowercase word tokens (+ crude singulars) of a screen/page name, minus the
    generic layout words — the fuzzy vocabulary for screen<->page reconciliation.
    camelCase is split first so 'BrowseHomePage' yields {browse, home} (#229)."""
    toks: set = set()
    for t in texts:
        s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(t or ""))
        toks |= set(re.findall(r"[a-z]+", s.lower()))
    toks |= {t[:-1] for t in list(toks) if t.endswith("s") and len(t) > 3}
    return toks - _UI_PAGE_STOPWORDS


def _match_ui_page(screen_tokens: set, ui_pages: List[Mapping[str, Any]],
                   known: set) -> Optional[Mapping[str, Any]]:
    """FIX #416 — the registered ui_page the app built FOR this design screen, or
    None. The AUTHORITATIVE design_screen<->ui_page<->route link.

    A STRONG match only: the ui_page's name/component tokens must EQUAL the
    screen's name tokens (after the #226 stopword/singular normalization) — the
    app's own statement that it authored a DEDICATED routed page for this screen
    (browse_home <-> browse_home_page/BrowseHomePage; title_detail <->
    title_detail_page/TitleDetailPage). Equality (not mere overlap) keeps a
    variant/overlay (browse_home_ROWS, shows_genres_MENU, title_EPISODES) from
    grafting onto the base page — those carry extra tokens the page lacks. The
    ui_page's route must be one the app actually serves (in ``known``) so a
    promotion never navigates to a 404."""
    if not screen_tokens:
        return None
    kn = {str(r).rstrip("/") or "/" for r in (known or set())}
    for up in ui_pages or []:
        route = str(up.get("route") or "").strip()
        if not route:
            continue
        if kn and (route.rstrip("/") or "/") not in kn:
            continue
        if _screen_name_tokens(up.get("name"), up.get("component")) == screen_tokens:
            return up
    return None


def map_reference_screens(
    reference_images: List[Any],
    known_routes: Optional[set] = None,
    classifications: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ui_pages: Optional[List[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """[{name, path, route, auth}] for every reference image whose filename maps
    to a route. Layers, most authoritative first: the app's REGISTERED ui_pages
    (#416), the design-prep classification (#132), the common-screen keyword
    table, then a GENERIC fallback matching the filename against the app's actual
    routes (so an arbitrary app's "boards.png" maps to its /boards screen without
    any catalog). Unmappable images get route=None (skipped, not failed).

    FIX #416: ``ui_pages`` (from load_ui_pages) is the app's OWN list of routed
    pages it built. When a measured screen STRONGLY matches a registered ui_page
    (name/component tokens equal — browse_home <-> browse_home_page), the gate
    uses that page's ACTUAL route (the authoritative design_screen<->ui_page<->route
    link — handles param routes like /title/:id and semantic renames) AND judges
    it as a blocking page even if #132 mislabeled it an overlay: the app clearly
    built a dedicated page for it, so the gate must score its own hero screens
    (r13: browse_home/title_detail had real BrowseHomePage/TitleDetailPage pages
    yet were dropped as advisory, so the fidelity metric never saw them). A screen
    whose NAME is a structural overlay token (*_menu, *_dropdown) is NEVER promoted
    (the #128 rule holds — dropdowns/popups stay advisory), and the promotion is
    gated on the app actually serving the route (never a 404).

    FIX #132: ``classifications`` (from load_screen_classifications) is the
    per-screen mapping the design-prep analyst produced from the reference PIXELS.
    When present for a screen it wins over the filename heuristics: kind=='overlay'
    -> advisory (the #128 name regex becomes the fallback); requires_auth -> auth;
    route -> used when the app actually serves it (a semantic suggestion never
    navigates to a 404)."""
    known = {str(r) for r in (known_routes or set())}
    cls = classifications or {}
    pages = [p for p in (ui_pages or []) if isinstance(p, Mapping)]
    screens: List[Dict[str, Any]] = []
    for ref in reference_images or []:
        p = Path(ref)
        if not p.is_file():
            continue
        stem = re.sub(r"[^a-z0-9]+", "_", p.stem.lower())
        segs = [s for s in stem.split("_") if s]
        route, auth = None, True
        _cl = cls.get(p.stem) or cls.get(stem) or {}
        if isinstance(_cl.get("requires_auth"), bool):
            auth = _cl["requires_auth"]
        # #416: authoritative design_screen -> ui_page -> route link FIRST. A
        # registered ui_page the app built for THIS screen (strong name match)
        # supplies the real served route, ahead of the classification/filename
        # guesses below (all of which stay as fallbacks when there is no match).
        # A screen whose NAME is a structural overlay token (*_menu, *_dropdown)
        # is deliberately excluded from the ui_page link — the #128 rule owns it,
        # so a dropdown never inherits a page's route OR gets promoted, even if its
        # stopword-stripped tokens coincidentally equal a page's (account_menu ->
        # {account} == account_menu_page).
        _overlay_by_name = bool(_OVERLAY_NAME_RE.search(stem))
        _matched_page = (None if _overlay_by_name
                         else _match_ui_page(_screen_name_tokens(p.stem, stem), pages, known))
        if _matched_page is not None:
            route = str(_matched_page.get("route") or "").strip() or None
        _cl_route = str(_cl.get("route") or "").strip()
        if route is None and _cl_route and known and _cl_route in known:
            route = _cl_route  # authoritative route the app actually serves
        # Candidates from the full stem AND every TRAILING suffix of its segments.
        # Reference files are conventionally named ``<appname>_<screen>`` (e.g.
        # ``outlook_inbox``, ``outlook_calendar_event``); the leading app-name segment
        # is NOT part of the route, so ``outlook_inbox`` must match ``/inbox`` and
        # ``outlook_calendar`` ``/calendar`` (run #8: the full-stem-only match mapped
        # 2/9 outlook references → the visual gate was blind to inbox/calendar/landing).
        cands: List[str] = []
        def _add(tok: str) -> None:
            for v in (f"/{tok}", f"/{tok}s", f"/{tok.rstrip('s')}",
                      "/" + tok.replace("_", "-"), "/" + tok.replace("_", ""),
                      "/" + tok.replace("_", "/")):
                if v and v not in cands:
                    cands.append(v)
        _add(stem)
        for i in range(1, len(segs)):
            _add("_".join(segs[i:]))   # drop leading segment(s) — the app name
        # #356: also drop TRAILING segment(s) — reference files are as often
        # ``<screen>_<state>`` (login_modal, feed_logged_out, profile_own) as
        # ``<app>_<screen>``. Without this the deleted social catalog was the
        # only thing resolving login_modal -> /login. Added AFTER the fuller
        # candidates so a more specific route still wins, and every candidate is
        # still gated on the app actually serving it.
        for i in range(len(segs) - 1, 0, -1):
            _add("_".join(segs[:i]))
        if segs:
            _add(segs[-1])             # the trailing screen token alone
        # GENERIC (domain-agnostic): match the screenshot filename to a declared
        # route, or "/" for a home/landing screen — so an arbitrary app's screens
        # map without the social catalog biasing ambiguous names. #132: only when
        # the AUTHORITATIVE route above did not already resolve.
        if known and route is None:
            route = next((c for c in cands if c in known), None)
            if route is None and (stem in _HOME_STEMS or (segs and segs[-1] in _HOME_STEMS)) and "/" in known:
                route = "/"
        # The keyword catalog still supplies the public/auth flag (a login/landing
        # screen is public) and fills the ROUTE only as a LAST resort (never
        # overriding a generic match, and only when the app serves it) — so a
        # non-social app whose screen name contains a social token isn't mis-routed.
        if route is None:
            for keys, r in _ROUTE_KEYWORDS:
                if any(k in stem for k in keys) and ((not known) or r in known):
                    route = r
                    break
        # #356: auth follows the RESOLVED route, never a filename token. A
        # measured requires_auth still wins over both.
        if (route in _FRAMEWORK_PUBLIC_ROUTES
                and not isinstance(_cl.get("requires_auth"), bool)):
            auth = False
        # FIX #128 (visual-gate autopsy, run-47): an OVERLAY / interaction-STATE
        # reference (search_flyout = feed + a notifications MODAL; *_dropdown, *_popup,
        # …) has no URL route that reproduces it — route capture navigates to the base
        # page, so the judge compares unrelated images → PERMANENT 0.00 → the "every
        # screen ≥ min" gate is mathematically unpassable and every milestone escapes
        # below-threshold, while the false 0.00 pollutes the frontend's remediation
        # with an un-fixable target. Mark such screens ADVISORY: still judged +
        # reported, but excluded from the BLOCKING pass criterion. FIX #132: the
        # analyst's pixel-level kind classification is authoritative when present
        # ('overlay' -> advisory, 'page' -> blocking even if the filename says
        # otherwise); the name regex remains the fallback.
        _kind = str(_cl.get("kind") or "").strip().lower()
        if _matched_page is not None:
            # #416: the app REGISTERED a dedicated routed page for this screen
            # (and its name is not a structural overlay token — enforced when
            # _matched_page was resolved) -> it is a real page, judged BLOCKING
            # even if #132's pixel-only pass mislabeled it kind='overlay' (it can't
            # see that the app built a page for it). This is the ONLY path that
            # overrides the overlay label; a genuine overlay with no dedicated page
            # (account_menu, *_dropdown) never matches a ui_page, so #128 holds and
            # it stays advisory.
            advisory = False
        elif _kind in ("page", "overlay"):
            advisory = _kind == "overlay"
        else:
            advisory = _overlay_by_name
        screens.append({"name": p.stem, "path": str(p), "route": route,
                        "auth": auth, "advisory": advisory})
    return screens


def _select_judged_screens(screens: List[Dict[str, Any]], max_screens: int) -> List[Dict[str, Any]]:
    """Which mapped screens the gate actually judges. EVERY blocking (page) screen
    is judged: ``visual_gate_verdict`` FAILS any OWNED screen left unjudged, so a
    flat ``[:max_screens]`` cap that drops one makes the gate mathematically
    UNPASSABLE for any app with more page screens than the cap — no frontend work
    can clear it (netflix r10: 13 mappable page screens vs cap 8 → 5 owned screens
    'never judged', a permanent block). The cap now only trims ADVISORY
    (overlay/interaction-state) overflow — those are EXCLUDED from the blocking
    pass criterion (#128), so bounding THEM keeps cost sane without breaking the
    gate. Only routed screens are judgeable; blocking screens come first so the
    remaining cap budget goes to advisory extras."""
    routed = [s for s in screens if s.get("route")]
    blocking = [s for s in routed if not s.get("advisory")]
    advisory = [s for s in routed if s.get("advisory")]
    return blocking + advisory[:max(0, max_screens - len(blocking))]


# Interaction-STATE name tokens — a reference so named is an overlay reachable only by
# a click/hover, never a URL route, so it can't be fairly scored by route-capture.
_OVERLAY_NAME_RE = re.compile(
    r"(?:^|_)(?:flyout|modal|popup|pop_?over|dropdown|drop_?down|overlay|dialog|"
    r"drawer|tooltip|toast|sheet|menu|context_?menu|lightbox)(?:_|$)")


# ---------------------------------------------------------------------------
# App boot + auth (the smoke validation tears the env down with ``down -v``,
# so the gate boots the already-built images itself).
# ---------------------------------------------------------------------------
def visual_gate_verdict(*, results, owned=None):
    """The gate verdict, scoped to the milestone's DECLARED screens (#353).

    `all([])` is True, so the old rule passed on an empty exam -- r92 logged
    "PASSED (login_modal=0.08): all 0 screens >= 0.65". The denominator was
    "screens that happen to map to a route the app already serves", and an
    unmapped screen was skipped rather than failed, so not building a page
    removed it from its own exam.

    `owned` is the milestone's commitment: measured `kind == page` screens whose
    route matches a REGISTERED ui_page. A milestone is judged on its own pages,
    not on ones a later milestone owns.

      * an owned screen that was never judged is a FAILURE, not a skip;
      * a non-empty owned set with zero BLOCKING judgments cannot pass
        (advisory judgments alone never carry the verdict).

    With no ui_page registered yet the owned set is empty and the verdict is
    exactly the old one -- blocking there would wedge every pre-kickoff tick.
    """
    rs = [r for r in (results or []) if isinstance(r, dict)]
    blocking = [r for r in rs if not r.get("advisory")]
    own = [str(n) for n in (owned or [])]
    own_set = set(own)
    judged = {str(r.get("name") or "") for r in rs}
    unjudged = sorted(n for n in own if n not in judged)

    scoped = [r for r in blocking if not own_set or str(r.get("name") or "") in own_set]
    all_scoped_pass = all(bool(r.get("passed")) for r in scoped)

    if not own_set:
        return {"passed": all_scoped_pass, "unjudged": [], "reason": ""}

    if unjudged:
        return {
            "passed": False, "unjudged": unjudged,
            "reason": (f"{len(unjudged)} declared screen(s) were never judged: "
                       f"{unjudged}. An unbuilt page is not exempt from its own "
                       f"exam — author the page so it can be captured and scored."),
        }
    if not scoped:
        return {
            "passed": False, "unjudged": [],
            "reason": ("no BLOCKING screen was judged although the milestone "
                       "declares pages — advisory screens alone cannot carry "
                       "the verdict; author the declared pages."),
        }
    return {"passed": all_scoped_pass, "unjudged": [], "reason": ""}


def screen_coverage(*, results, measured, owned=None):
    """How much of the reference the visual gate actually judged (#351).

    The gate's verdict is `all(r["passed"] for r in blocking)`, and `all([])` is
    True -- r92 logged "Visual fidelity PASSED (login_modal=0.08): all 0 screens
    >= 0.65" while its one capturable screen scored 0.08.

    That is not statistical dilution, it is structural self-exemption: a
    reference only enters the judged set if it maps to a route the app ALREADY
    SERVES, and one that does not is skipped rather than failed. So the
    denominator is "screens that happen to be built" -- not building a page
    removes it from its own exam, and the fewer pages exist the easier the gate
    passes.

    This reports; it does not judge. `owned` narrows the denominator to one
    milestone's screens once a STRUCTURED owned set exists -- milestone->screen
    attribution is currently only LLM prose in `description_slice`, which no
    prompt mandates, so it is not parsed here.
    """
    judged = {str(r.get("name") or "") for r in (results or []) if isinstance(r, dict)}
    denom = [str(n) for n in (owned if owned is not None else (measured or []))]
    unjudged = sorted(n for n in denom if n not in judged)
    blocking = [r for r in (results or [])
                if isinstance(r, dict) and not r.get("advisory")
                and str(r.get("name") or "") in set(denom)]
    total = len(denom)
    return {
        "measured": total,
        "judged": sum(1 for n in denom if n in judged),
        "blocking_judged": len(blocking),
        "unjudged": unjudged,
        "coverage": (round((total - len(unjudged)) / total, 4) if total else 0.0),
    }


def _compose_up(project_dir: Path,
                timeout: int = int(os.environ.get("ENVGEN_VISUAL_COMPOSE_TIMEOUT", "900") or 900)) -> Optional[str]:
    compose_file = project_dir / "docker" / "docker-compose.yml"
    cwd = project_dir / "docker"
    if not compose_file.exists():
        return f"no compose file at {compose_file}"
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return (r.stderr or r.stdout or "compose up failed")[-400:]
    except Exception as exc:
        return str(exc)[:400]
    return None


def _http_json(url: str, payload: Optional[dict] = None, timeout: int = 10) -> tuple:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


def _seed_demo_login(project_dir: Any) -> Optional[Dict[str, str]]:
    """Credentials of the SEEDED demo user (the first user the LOADER actually inserts), whose
    password is the framework's fixed seed password. The QA tooling logs in AS this user so it
    validates the POPULATED app — the references depict screens WITH data, and a fresh throwaway
    user sees empty lists (owner-scoped reads), making every page look blank/mismatched.

    MUST read the SAME source the loader loads: the agent-authored ``seed_data.json`` (what
    actually populates the DB), NOT the embedded ``_SEED`` fallback in ``seed_data.py``. Live
    2026-06-30 (outlook): the JSON's first user was ``demo@example.com`` but the .py ``_SEED``
    default was ``avachen@example.com``; reading only ``_SEED`` returned a user the DB was NOT
    seeded with → ``run_browser_test_user`` REGISTERED that email as a fresh empty account and
    browsed as it → EVERY data page false-flagged blank → the frontend churned on phantom
    blank-page fixes (eating the milestone time budget). JSON first, ``_SEED`` fallback.
    Domain-agnostic; None if no seed."""
    backend = Path(project_dir) / "app" / "backend"

    def _creds_from_users(users) -> Optional[Dict[str, str]]:
        if users and isinstance(users[0], dict) and users[0].get("email"):
            return {"email": str(users[0]["email"]), "password": "password",  # backend_skeleton._SEED_PASSWORD
                    "name": str(users[0].get("name") or "Demo")}
        return None

    # 1) the agent-authored JSON the loader inserts into the DB (authoritative)
    try:
        sj = backend / "seed_data.json"
        if sj.is_file():
            import json as _json
            data = _json.loads(sj.read_text(encoding="utf-8", errors="ignore"))
            creds = _creds_from_users((data or {}).get("users") or [])
            if creds:
                return creds
    except Exception:
        pass
    # 2) fallback: the embedded _SEED default in the loader (used only when no JSON)
    try:
        import ast
        sd = backend / "seed_data.py"
        if not sd.is_file():
            return None
        m = re.search(r"_SEED\s*=\s*(\{.*\})", sd.read_text(encoding="utf-8", errors="ignore"))
        if not m:
            return None
        seed = ast.literal_eval(m.group(1))
        return _creds_from_users((seed or {}).get("users") or [])
    except Exception:
        return None


def _mint_token(backend_port: int, timeout_s: int = 60,
                demo: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """A bearer token for screenshots. Prefer the SEEDED demo user (populated screens that
    match the references); fall back to a throwaway register only if no demo user is known."""
    suffix = str(int(time.time()))[-7:]
    if demo and demo.get("email"):
        # the seeded user already exists — log in (don't register); it owns the seed data.
        _st, _d = _http_json(f"http://localhost:{backend_port}/auth/login",
                             {"email": demo["email"], "password": demo.get("password") or "password"})
        _tok = _d.get("access_token") or _d.get("token")
        if _tok:
            return str(_tok)
    payload = {
        "email": f"vf_{suffix}@gate.local", "password": "VfGate123!",
        "username": f"vf_{suffix}", "full_name": "Visual Gate",
    }
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, data = _http_json(f"http://localhost:{backend_port}/auth/register", payload)
        if status in (200, 201):
            tok = data.get("access_token") or data.get("token") or (
                (data.get("item") or {}).get("access_token") if isinstance(data.get("item"), dict) else None)
            if tok:
                return str(tok)
            # 200/201 but no token in the body → the user now exists, so re-registering
            # would 409 every iteration to the 60s deadline. Stop the futile retries.
            break
        if status == 409 or (status == 400 and "exist" in json.dumps(data).lower()):
            status, data = _http_json(f"http://localhost:{backend_port}/auth/login",
                                      {"email": payload["email"], "password": payload["password"]})
            tok = data.get("access_token") or data.get("token")
            if tok:
                return str(tok)
        time.sleep(3)
    return None


# FIX #75a (outlook run-62): networkidle can still be a bare un-hydrated SPA shell
# (``<div id="root"></div>`` mid-rebuild). A shot of it IS written, so run_visual_fidelity
# never hits capture_unavailable — the blank is judged 0.00 and BURNS one of the 3 per-source
# attempts with no refund, exhausting the budget → the 900s escape. Detect the shell (BOTH
# tiny innerText AND few nodes — a hydrated-but-data-empty "No messages" page has short text
# but dozens of chrome nodes, so it is NOT flagged) and re-poll like fix #68 before skipping.
_CAPTURE_BLANK_TEXT = 12
_CAPTURE_BLANK_NODES = 8
_CAPTURE_BLANK_PROBE = (
    "() => { const t=(document.body&&document.body.innerText||'').trim();"
    " const n=document.body?document.body.querySelectorAll('*').length:0;"
    " return {textLen: t.length, nodes: n}; }")


# FIX #141 — theme-variant capture. run-64 M2 live: login_dark.png ≡
# login_light.png (identical md5, mean=249 near-white) — the capture never
# switched the app to dark, so the dark reference variant was judged against
# LIGHT pixels and structurally capped ~0.3; a blocking screen that can never
# pass ran every visual window to the 3600s anchor. A dark/light screen is
# captured with (1) prefers-color-scheme emulation, (2) common theme storage
# keys pre-set + reload so class-strategy apps BOOT themed, and (3) a post-load
# force of the `dark` class / data-theme. All three are inert on apps that
# ignore them.
_THEME_TOKEN_RE = re.compile(r"(?:^|[_\-])(dark|light)(?:[_\-]|$)", re.IGNORECASE)
_THEME_STORAGE_KEYS = ("theme", "color-theme", "ui-theme", "darkMode")


def screen_color_scheme(screen: Mapping[str, Any]) -> Optional[str]:
    """'dark'/'light' for a theme-variant screen, else None. An explicit
    screen['scheme'] (future design-prep classification) wins over the
    name-token heuristic (login_dark / feed-light reference stems)."""
    _s = str(screen.get("scheme") or "").strip().lower()
    if _s in ("dark", "light"):
        return _s
    m = _THEME_TOKEN_RE.search(str(screen.get("name") or ""))
    return m.group(1).lower() if m else None


def _theme_storage_js(scheme: Optional[str]) -> str:
    """JS that pre-sets (or, scheme=None, clears) the common theme storage
    keys so the app boots in the wanted theme after a reload."""
    if scheme is None:
        body = ";".join(f"localStorage.removeItem('{k}')"
                        for k in _THEME_STORAGE_KEYS)
    else:
        vals = {"theme": scheme, "color-theme": scheme, "ui-theme": scheme,
                "darkMode": "true" if scheme == "dark" else "false"}
        body = ";".join(f"localStorage.setItem('{k}', '{v}')"
                        for k, v in vals.items())
    return "try { " + body + " } catch (e) {}"


def _theme_class_js(scheme: str) -> str:
    """JS that force-applies the theme AFTER the app booted — covers apps
    that read a root class/attribute but no storage key."""
    add = "add" if scheme == "dark" else "remove"
    return ("(() => { const de = document.documentElement; "
            f"de.classList.{add}('dark'); "
            f"document.body && document.body.classList.{add}('dark'); "
            f"de.setAttribute('data-theme', '{scheme}'); "
            f"de.style.colorScheme = '{scheme}';" + " })()")


async def capture_route_screenshots(
    base_url: str,
    screens: List[Dict[str, Any]],
    token: Optional[str],
    out_dir: Path,
    auth_redirected: Optional[List[str]] = None,
    blank_screens: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Screenshot each screen's route; returns {screen name → png path}. A
    failed navigation skips that screen (reported upstream as missing). An
    AUTH screen whose final URL bounced to /login|/signup is NOT shot — the
    judge must never compare the login page against a feed reference (round
    31: every auth screen scored 0.2 against the wrong pixels). Bounced
    names are appended to ``auth_redirected`` when the caller passes one. A
    still-un-hydrated BLANK shell (FIX #75a) is re-polled ~5s then, if still
    blank, appended to ``blank_screens`` and its shot skipped (a blank 0.00
    that would waste the visual attempt budget)."""
    from playwright.async_api import async_playwright  # lazy: heavy dep

    out_dir.mkdir(parents=True, exist_ok=True)
    shots: Dict[str, str] = {}
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
        except Exception as _launch_exc:
            # #234: heal a missing browser binary once in-process, then retry.
            from ...tools.browser._bootstrap import heal_missing_browser
            if not heal_missing_browser(_launch_exc):
                raise
            browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            ctx = await browser.new_context(viewport=_VIEWPORT)
            if token:
                # FIX #103 (runs 9+21, live): the app's storage KEY is pure lane variance
                # ('token' vs 'access_token' vs camelCase …) — a mismatch bounced every
                # auth route to /login ("authenticated session rejected — skipping
                # judgment") and collapsed visual coverage to the login screens. Inject
                # the SAME token under every common alias in BOTH storages; extra keys
                # are inert to the app.
                _tok_js = json.dumps(token)
                _aliases = ("token", "access_token", "auth_token",
                            "authToken", "accessToken", "jwt")
                await ctx.add_init_script(";".join(
                    f"localStorage.setItem('{k}', {_tok_js});"
                    f"sessionStorage.setItem('{k}', {_tok_js})"
                    for k in _aliases) + ";")
            page = await ctx.new_page()
            _applied_scheme: Optional[str] = None   # FIX #141 emulation state
            _storage_dirty = False                  # theme keys we set last screen
            for screen in screens:
                if not screen.get("route"):
                    continue
                try:
                    # FIX #141: theme-variant screens (login_dark/login_light)
                    # boot the app in the wanted scheme; unthemed screens after
                    # a themed one get the keys cleared so nothing leaks.
                    _scheme = screen_color_scheme(screen)
                    _want = _scheme or "light"
                    if _want != (_applied_scheme or "light"):
                        await page.emulate_media(color_scheme=_want)
                        _applied_scheme = _want
                    await page.goto(base_url + screen["route"],
                                    wait_until="networkidle", timeout=20000)
                    if _scheme or _storage_dirty:
                        await page.evaluate(_theme_storage_js(_scheme))
                        _storage_dirty = _scheme is not None
                        await page.reload(wait_until="networkidle",
                                          timeout=20000)
                    await page.wait_for_timeout(1200)
                    if screen.get("auth"):
                        final = (page.url or "").split("?", 1)[0].rstrip("/")
                        if final.endswith("/login") or final.endswith("/signup"):
                            if auth_redirected is not None:
                                auth_redirected.append(screen["name"])
                            continue
                    # FIX #75a: an un-hydrated blank shell — re-poll before concluding.
                    try:
                        _p = await page.evaluate(_CAPTURE_BLANK_PROBE)
                        _txt, _nd = _p.get("textLen", 0), _p.get("nodes", 0)
                        if _txt < _CAPTURE_BLANK_TEXT and _nd < _CAPTURE_BLANK_NODES:
                            for _ in range(3):
                                await page.wait_for_timeout(1200)
                                _p = await page.evaluate(_CAPTURE_BLANK_PROBE)
                                _txt, _nd = _p.get("textLen", 0), _p.get("nodes", 0)
                                if _txt >= _CAPTURE_BLANK_TEXT or _nd >= _CAPTURE_BLANK_NODES:
                                    break
                        if _txt < _CAPTURE_BLANK_TEXT and _nd < _CAPTURE_BLANK_NODES:
                            if blank_screens is not None:
                                blank_screens.append(screen["name"])
                            continue  # skip the shot — do not feed a blank 0.00 to the judge
                    except Exception:
                        pass  # probe error → treat as non-blank (never false-skip)
                    if _scheme:
                        # FIX #141 (3): class/attribute-strategy apps with no
                        # storage key — force the theme on the booted document.
                        try:
                            await page.evaluate(_theme_class_js(_scheme))
                            await page.wait_for_timeout(400)
                        except Exception:
                            pass
                    dest = out_dir / f"{screen['name']}.png"
                    await page.screenshot(path=str(dest))
                    shots[screen["name"]] = str(dest)
                    # #141b: keep a per-round copy — run-64 M2's 0.00↔0.40
                    # score oscillation could not be root-caused because every
                    # judge round overwrote these files. Soft-capped; failures
                    # never break the capture.
                    try:
                        _hist = out_dir / "history"
                        _hist.mkdir(exist_ok=True)
                        if sum(1 for _ in _hist.iterdir()) < 500:
                            import shutil as _sh
                            from datetime import datetime as _dt
                            _stamp = _dt.now().strftime("%H%M%S")
                            _sh.copyfile(dest,
                                         _hist / f"{_stamp}_{screen['name']}.png")
                    except Exception:
                        pass
                except Exception:
                    continue
        finally:
            await browser.close()
    return shots


# ---------------------------------------------------------------------------
# Vision judgment
# ---------------------------------------------------------------------------
_JUDGE_INSTRUCTIONS = (
    "You are a strict UI-fidelity reviewer. The FIRST image is the REFERENCE "
    "design for the '{name}' screen; the SECOND image is a screenshot of the "
    "implemented app at route '{route}'.\n"
    "IGNORE differences in user-generated content (different photos, usernames, "
    "counts) and empty states caused by missing data — judge the DESIGN.\n\n"
    "Assess each dimension (these are your evaluation criteria):\n"
    "{rubric_block}\n\n"
    "Then judge OVERALL similarity holistically (1.0 = a user would take the "
    "implementation for the reference product; 0.5 = clearly related but with "
    "significant gaps; 0.0 = unrelated). Weigh component completeness and "
    "layout most heavily.\n"
    "Respond with ONLY a JSON object:\n"
    "{{\n"
    '  "dimensions": {{"<key>": {{"score": <0.0-1.0>, '
    '"notes": "<concrete: what matches / what differs>", '
    '"fix": "<the concrete change that closes this dimension\'s gap — name the '
    'element and the target state, e.g. \'narrow the left rail to ~245px, '
    'icons + labels, logo wordmark top-left\'>"}}, ...'
    ' — for "components" also include "missing": ["<component>", ...]}},\n'
    '  "similarity": <0.0-1.0 overall>,\n'
    '  "empty_state": <true|false — true when the implementation shows an EMPTY/'
    "placeholder state (e.g. 'No items yet') because its data is missing, so the "
    "reference's real design skeleton never rendered and cannot be judged>,\n"
    '  "deviations": ["<WHERE on the screen + WHAT differs, ordered by impact, '
    'e.g. \'header: implementation centers the logo; reference left-aligns it '
    'next to search\'>", ...],\n'
    '  "fixes": ["<ordered TO-DO list for the implementer: the smallest set of '
    'concrete edits that would make a user mistake this screen for the '
    'reference>", ...],\n'
    '  "summary": "<one line>"\n'
    "}}"
)


def _rubric_block() -> str:
    return "\n".join(
        f"- {d['key']} ({d['title']}): {d['rubric']}" for d in _DIMENSIONS)


def _b64(path: str) -> str:
    """Base64 for the vision payload — routed through the shared compression
    cache (mechanism #41): a multi-MB reference/screenshot is downscaled once
    and reused across every judgment instead of re-shipped at full size."""
    src = Path(path)
    try:
        from tools.file_tools import _compressed_image_for_llm
        cached = _compressed_image_for_llm(src)
        if cached is not None:
            src = cached
    except Exception:
        pass
    return base64.b64encode(src.read_bytes()).decode()


def _clamp01(v: Any) -> Optional[float]:
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return None


def _parse_verdict(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"similarity": 0.0, "dimensions": {}, "deviations": ["judge returned no JSON"],
                "summary": str(text)[:200]}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"similarity": 0.0, "dimensions": {}, "deviations": ["judge JSON unparseable"],
                "summary": m.group(0)[:200]}
    dims: Dict[str, Any] = {}
    raw_dims = data.get("dimensions") or {}
    if isinstance(raw_dims, Mapping):
        for d in _DIMENSIONS:
            entry = raw_dims.get(d["key"])
            if not isinstance(entry, Mapping):
                continue
            sc = _clamp01(entry.get("score"))
            rec: Dict[str, Any] = {"score": sc if sc is not None else 0.0,
                                   "notes": str(entry.get("notes", ""))[:400]}
            if str(entry.get("fix", "")).strip():
                rec["fix"] = str(entry.get("fix"))[:400]
            if d["key"] == "components":
                rec["missing"] = [str(x)[:120] for x in (entry.get("missing") or [])
                                  if str(x).strip()][:15]
            dims[d["key"]] = rec
    sim = _clamp01(data.get("similarity"))
    if sim is None:
        # model omitted the overall judgment — average its dimension scores
        scores = [r["score"] for r in dims.values()]
        sim = round(sum(scores) / len(scores), 3) if scores else 0.0
    devs = [str(x)[:300] for x in (data.get("deviations") or []) if str(x).strip()][:10]
    fixes = [str(x)[:300] for x in (data.get("fixes") or []) if str(x).strip()][:10]
    return {"similarity": sim, "dimensions": dims, "deviations": devs,
            "fixes": fixes, "summary": str(data.get("summary", ""))[:300],
            # FIX #133: the judge's empty-state observation becomes REPORTABLE (it was
            # told to ignore data-empty states — now it also flags them so the framework
            # can remind the BACKEND lane to seed the missing rows).
            "empty_state": bool(data.get("empty_state"))}


async def judge_screen_pair(llm: Any, screen: Mapping[str, Any], screenshot_path: str) -> Dict[str, Any]:
    """One vision call comparing a reference image to the implementation
    screenshot. Defensive: any failure returns similarity=0 with the error as a
    deviation (a broken judge must not crash the orchestrator loop)."""
    from utils.llm import Message

    prompt = _JUDGE_INSTRUCTIONS.format(name=screen["name"], route=screen["route"],
                                        rubric_block=_rubric_block())
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{_b64(screen['path'])}", "detail": "high"}},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{_b64(screenshot_path)}", "detail": "high"}},
    ]
    try:
        # The high-level LLM wrapper's chat() takes a prompt STRING; multimodal
        # messages need the underlying provider client (BaseLLMClient.chat).
        client = getattr(llm, "_client", llm)
        resp = await client.chat([Message.user_multimodal(parts)],
                                 temperature=0.0, max_tokens=3000)
        return _parse_verdict(getattr(resp, "content", "") or "")
    except Exception as exc:
        # judge_error marks a TRANSIENT failure — #142 must never cache it
        # (a frozen 0.0 would pin a healthy screen for the whole milestone).
        return {"similarity": 0.0, "dimensions": {}, "deviations": [f"judge call failed: {exc}"[:200]],
                "summary": "judge error", "judge_error": True}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
async def run_visual_fidelity(
    project_dir: Any,
    reference_images: List[Any],
    llm: Any,
    *,
    min_similarity: Optional[float] = None,
    max_screens: int = 8,
    out_dir: Optional[Path] = None,
    capture_fn: Optional[Callable] = None,
    judge_fn: Optional[Callable] = None,
    verdict_cache: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compare the running app against the reference designs.

    Returns {"passed": bool, "summary": str, "screens": [{name, route,
    similarity, passed, deviations, screenshot}], "skipped": [names]}.
    ``passed`` is True iff every judged screen reaches ``min_similarity``
    (default 0.65, env ENVGEN_VISUAL_MIN). No mappable references → passes
    vacuously with a summary saying so (the gate only binds when references
    exist — that's the user-provided design contract)."""
    project_dir = Path(project_dir).resolve()
    if min_similarity is None:
        try:
            min_similarity = float(os.environ.get("ENVGEN_VISUAL_MIN", "0.65"))
        except Exception:
            min_similarity = 0.65
    known_routes: set = set()
    try:
        _app = project_dir / "app" / "frontend" / "src" / "App.jsx"
        if _app.exists():
            known_routes = set(re.findall(
                r'<Route\s+path=["\']([^"\']+)["\']',
                _app.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        pass
    screens = map_reference_screens(
        reference_images, known_routes,
        classifications=load_screen_classifications(project_dir),  # FIX #132
        ui_pages=load_ui_pages(project_dir))                       # FIX #416
    judged_screens = _select_judged_screens(screens, max_screens)
    skipped = [s["name"] for s in screens if not s.get("route")]
    if not judged_screens:
        return {"passed": True, "summary": "no mappable reference screens — visual gate vacuous",
                "screens": [], "skipped": skipped}

    capture = capture_fn
    if capture is None:
        err = _compose_up(project_dir)
        if err:
            return {"passed": False, "summary": f"visual gate could not boot app: {err}",
                    "screens": [], "skipped": skipped}
        compose_file = project_dir / "docker" / "docker-compose.yml"
        cwd = project_dir / "docker"
        # FIX #207: resolve THIS app's OWN host ports — retry within the readiness
        # window (the container isn't `docker compose ps`-visible the instant
        # _compose_up returns, so an immediate resolve returned None and the old
        # `or 8080`/`or 3001` fallback screenshotted the persistent gmaps demo,
        # scoring a Google-Maps login against this env's references — r13). Poll
        # until the frontend port resolves AND serves, then SKIP honestly if it
        # never does — never capture a possibly-unrelated service.
        def _fe(svc):
            return _service_host_port(compose_file, cwd, svc)
        _deadline = time.time() + 240
        fe_port = be_port = None
        while time.time() < _deadline:
            fe_port = fe_port or _resolve_app_port(_fe, ("frontend", "ui"))
            be_port = be_port or _resolve_app_port(_fe, ("backend", "api"))
            if fe_port:
                try:
                    with urllib.request.urlopen(
                            urllib.request.Request(
                                f"http://localhost:{fe_port}", method="GET"),
                            timeout=4) as _r:
                        if 200 <= _r.status < 500:
                            break
                except Exception:
                    pass
            time.sleep(3)
        if not fe_port:
            return {"passed": False, "port_unresolved": True,
                    "summary": ("visual gate could not resolve the app's OWN frontend "
                                "host port after 240s — refusing to screenshot a "
                                "possibly-unrelated :8080 service; skipping judgment"),
                    "screens": [], "skipped": skipped}
        auth_needed = any(s["auth"] for s in judged_screens)
        # Log in as the SEEDED demo user so authed screens render POPULATED (matching the
        # references), not the empty lists a fresh throwaway user sees under tenant-scoping.
        token = _mint_token(be_port, demo=_seed_demo_login(project_dir)) if auth_needed else None
        if auth_needed and not token:
            # Not a judgment: without a session every auth route renders the
            # login page. Report it; the orchestrator refunds the attempt.
            return {"passed": False, "auth_unavailable": True,
                    "summary": ("auth token mint failed (POST /auth/register on "
                                f"port {be_port}) — auth screens would all render "
                                "the login page; skipping judgment"),
                    "screens": [], "skipped": skipped}
        # #207: fe_port is resolved AND confirmed-serving above (the readiness
        # poll broke on a 2xx-4xx from THIS app's own port), so base_url points at
        # the real generated app, never the :8080 gmaps demo.
        base_url = f"http://localhost:{fe_port}"
        shots_dir = out_dir or (project_dir / "design" / "visual_gate")

        _auth_bounced: List[str] = []
        _blank_screens: List[str] = []

        async def capture(scr):  # noqa: F811 — default capture closes over the boot
            return await capture_route_screenshots(
                base_url, scr, token, shots_dir, auth_redirected=_auth_bounced,
                blank_screens=_blank_screens)

    else:
        _auth_bounced = []
        _blank_screens = []

    shots = await capture(judged_screens)
    _auth_routes = [s["name"] for s in judged_screens if s.get("auth")]
    if _auth_routes and set(_auth_bounced) >= set(_auth_routes):
        # FIX #105 (run-22 live, recurring): the wholesale rejection is usually a RACE —
        # a parallel validation cycle reset the DB (down -v → reseed → the token's sub
        # points at a user that no longer exists) or rotated the JWT keys between the
        # mint and the capture. Re-mint ONCE against the current app state and retry
        # the capture before skipping the whole judgment.
        try:
            token2 = _mint_token(be_port, demo=_seed_demo_login(project_dir))
        except Exception:
            token2 = None
        if token2 and token2 != token:
            token = token2          # `capture` late-binds `token` — no redefinition needed
            _auth_bounced.clear()
            _blank_screens.clear()
            shots = await capture(judged_screens)
    if _auth_routes and set(_auth_bounced) >= set(_auth_routes):
        # The minted token was rejected wholesale (e.g. the validation cycle
        # rebuilt the app between mint and capture, rotating the JWT keys).
        return {"passed": False, "auth_unavailable": True,
                "summary": ("authenticated session rejected — every auth route "
                            "redirected to /login despite a freshly minted "
                            "token (incl. one re-mint retry); skipping judgment"),
                "screens": [], "skipped": skipped}
    if judged_screens and not shots and not _blank_screens:
        return {"passed": False,
                "summary": "capture unavailable — app not reachable; not judged",
                "screens": [], "skipped": skipped,
                "capture_unavailable": True,
                "min_similarity": min_similarity}
    judge = judge_fn or judge_screen_pair

    results: List[Dict[str, Any]] = []
    for screen in judged_screens:
        shot = shots.get(screen["name"])
        if not shot:
            if screen["name"] in _blank_screens:
                _dev = (f"route {screen['route']} rendered BLANK — navigated + reached "
                        "networkidle but the SPA never hydrated after ~5s re-poll (a bare "
                        "<div id=root> shell). If transient (mid-rebuild) it is refunded a "
                        "few times; if it persists it is a real render/data-fetch failure "
                        "on this route — fix the page's mount/data load, not its styling")
            elif screen["name"] in _auth_bounced:
                _dev = (f"route {screen['route']} redirected to /login — the auth guard "
                        "rejected the session on THIS route only; fix the route's auth "
                        "handling, not its styling")
            else:
                _dev = f"route {screen['route']} could not be captured"
            results.append({"name": screen["name"], "route": screen["route"],
                            "similarity": 0.0, "passed": False, "dimensions": {},
                            "deviations": [_dev],
                            "blank": screen["name"] in _blank_screens,
                            "advisory": bool(screen.get("advisory")),
                            "screenshot": None,
                            "reference": screen.get("path")})
            continue
        # FIX #142: identical pixels ⇒ identical verdict. run-65 M4 (#141b
        # history): 3 byte-identical explore captures scored 0.00 then 0.30 —
        # ±0.3 judge noise on unchanged screens phantom-reset #138 plateau
        # tracking and made #129 sticky-pass luck-dependent. Cache the verdict
        # by (screen, capture md5) for the milestone; pixels change → re-judge.
        _ck = None
        if verdict_cache is not None:
            try:
                import hashlib as _hl
                _ck = f"{screen['name']}:{_hl.md5(Path(shot).read_bytes()).hexdigest()}"
            except Exception:
                _ck = None
        if _ck is not None and _ck in verdict_cache:
            verdict = verdict_cache[_ck]
        else:
            verdict = await judge(llm, screen, shot)
            if _ck is not None and isinstance(verdict, dict) \
                    and verdict.get("similarity") is not None \
                    and not verdict.get("judge_error"):
                verdict_cache[_ck] = verdict
        results.append({"name": screen["name"], "route": screen["route"],
                        "similarity": verdict["similarity"],
                        "passed": verdict["similarity"] >= min_similarity,
                        "advisory": bool(screen.get("advisory")),
                        "empty_state": bool(verdict.get("empty_state")),  # FIX #133
                        "dimensions": verdict.get("dimensions", {}),
                        "deviations": verdict["deviations"],
                        "fixes": verdict.get("fixes", []),
                        "screenshot": shot,
                        "reference": screen.get("path"),
                        # Fix #52 — the deterministic per-component color diff
                        # (spec hex vs the SAME fractional region sampled from
                        # this screenshot). Facts beside the judge's opinion.
                        "measured_deviations": _measured_deviations(
                            project_dir, screen["name"], shot),
                        "summary": verdict.get("summary", "")})

    # FIX #128: ADVISORY screens (overlay/flyout/modal interaction states) are judged +
    # reported but never BLOCK — they have no URL route that reproduces them, so their
    # score is a route-capture artifact, not a frontend-quality signal.
    _blocking = [r for r in results if not r.get("advisory")]
    # #353: the milestone's DECLARED scope — measured page screens whose route
    # the app has actually registered a ui_page for. Judging against "whatever
    # mapped to a built route" let an unbuilt page exempt itself.
    _registered_routes: set = set()
    try:
        import json as _json
        _up = Path(project_dir) / "shared" / "hubs" / "registryhub_ui_pages.json"
        if _up.exists():
            _raw = _json.loads(_up.read_text(encoding="utf-8"))
            for _v in (_raw if isinstance(_raw, list) else (_raw or {}).values()):
                if isinstance(_v, dict) and str(_v.get("route") or "").startswith("/"):
                    _registered_routes.add(str(_v["route"]).rstrip("/") or "/")
    except Exception:
        _registered_routes = set()
    _owned = [s["name"] for s in screens
              if not s.get("advisory")
              and (str(s.get("route") or "").rstrip("/") or "/") in _registered_routes]
    _verdict = visual_gate_verdict(results=results, owned=_owned)
    passed = _verdict["passed"]
    if _verdict.get("reason"):
        _LOG.warning("VISUAL GATE BLOCKS: %s", _verdict["reason"])
    # #351 (reporting only): name what the gate did NOT judge. `passed` above is
    # deliberately untouched — turning this into a blocker comes after the
    # page-seeding fix, or every run would start failing a gate it cannot yet
    # satisfy.
    _coverage = screen_coverage(
        results=results, measured=[s.get("name") for s in screens])
    if _coverage["unjudged"]:
        _LOG.warning(
            "VISUAL COVERAGE: judged %d/%d measured reference screen(s) "
            "(%.0f%%). NOT judged: %s — an unmapped screen is skipped, not "
            "failed, so these are exempt from the verdict above.",
            _coverage["judged"], _coverage["measured"],
            100.0 * _coverage["coverage"], _coverage["unjudged"],
        )
    failing = [f"{r['name']}({r['similarity']:.2f})" for r in _blocking if not r["passed"]]
    _adv_note = [f"{r['name']}({r['similarity']:.2f})" for r in results
                 if r.get("advisory")]
    summary = ("all %d screens ≥ %.2f" % (len(_blocking), min_similarity) if passed
               else "below %.2f: %s" % (min_similarity, ", ".join(failing)))
    if _adv_note:
        summary += " [advisory (overlay, non-blocking): %s]" % ", ".join(_adv_note)
    if _blank_screens:
        summary += " [blank capture: %s]" % ", ".join(_blank_screens)
    # FIX #75a: a REFUNDABLE transient ONLY when EVERY judged screen was a blank shell
    # (no real verdict obtained). If SOME screens produced real shots, do NOT refund —
    # their verdicts + remediation must flow this tick (a partial-blank must not discard
    # a fixable sibling's 0.55 and suppress its remediation).
    return {"passed": passed, "summary": summary, "screens": results, "skipped": skipped,
            "coverage": _coverage,  # #351: reporting only — does not gate

            "capture_transient": bool(_blank_screens) and not shots,
            "min_similarity": min_similarity}


def _measured_deviations(project_dir: Any, screen_name: str, screenshot_path: str) -> List[Dict[str, Any]]:
    """Fix #52 — deterministic per-component color diff for one judged screen.

    Loads the pre-measured spec (design/component_specs/<screen>.json, written by
    the material-prep phase before any lane woke) and samples the SAME fractional
    regions from the gate's screenshot via material_prep.spec_color_deviations.
    Best-effort: [] when the spec is absent or anything fails — the LLM judge
    remains the structural verdict; this only ADDS measured facts."""
    try:
        p = Path(project_dir) / "design" / "component_specs" / f"{screen_name}.json"
        if not p.exists():
            return []
        spec = json.loads(p.read_text(encoding="utf-8"))
        from .material_prep import spec_color_deviations
        return spec_color_deviations(spec, screenshot_path)
    except Exception:
        return []


def _lane_visible_reference(output_dir: Any, raw_path: Any) -> Optional[str]:
    """The WORKSPACE-RELATIVE staged copy of a reference image, if present.

    ``screen["path"]`` is the orchestrator-side ORIGINAL (often a host-absolute
    CLI path the lane's workspace cannot resolve — review w6x6art4t); the
    framework stages lane-visible copies under design/references/ and
    screenshots/. Prefer those; None when neither exists."""
    try:
        name = Path(str(raw_path)).name
        if not name or output_dir is None:
            return None
        for rel in (f"design/references/{name}", f"screenshots/{name}"):
            if (Path(output_dir) / rel).exists():
                return rel
    except Exception:
        pass
    return None


def _measured_diff_lines(r: Mapping[str, Any], output_dir: Any = None) -> List[str]:
    """Render a screen result's measured color deviations (#52) + the
    measure-don't-eyeball verification mandate (#53) as remediation lines."""
    devs = r.get("measured_deviations") or []
    lines: List[str] = []
    # Fix #65 — a WHOLESALE theme inversion dwarfs any per-component color tweak
    # (large-area background is the #1 similarity lever). If most backgrounds are
    # inverted the same way, lead with ONE structural instruction instead of
    # burying it under a scattered per-component list.
    if devs:
        try:
            from .material_prep import theme_inversion
            _want = theme_inversion(devs)
        except Exception:
            _want = None
        if _want:
            _have = "light" if _want == "dark" else "dark"
            lines.append(
                f"⚠ WRONG BASE THEME: the reference is {_want.upper()} but your "
                f"build renders {_have.upper()} (most component backgrounds are "
                f"inverted). Reference images WIN over any 'theme' wording in the "
                f"text spec — flip the app's BASE theme to {_want} FIRST (the page/"
                f"surface/card background tokens), then the per-component colors "
                f"below fall into place. This single change moves similarity far "
                f"more than any individual tweak.")
    if devs:
        lines.append(
            "MEASURED COLOR DIFF (deterministic pixel sampling of the gate "
            "screenshot vs the reference spec — facts, not the judge's opinion; "
            "apply these EXACT values):")
        for d in devs[:10]:
            if d.get("kind") == "accent_missing":
                lines.append(
                    f"  · {d.get('component')}: {d.get('hue')} accent MISSING — the "
                    f"reference measures {d.get('expected')} in this region; restore it "
                    "(semantic color loss: unread-dots/badges/buttons going gray)")
            else:
                lines.append(
                    f"  · {d.get('component')}: background renders {d.get('actual')} but "
                    f"the reference measures {d.get('expected')} "
                    f"(Δ{d.get('distance', 0):.0f}) → set it to {d.get('expected')}")
    # Fix #53 — zoom_compare adoption: the tool has been in the surface since
    # brick 3 with ZERO calls across runs 30-38 (the lane fixes by eyeball).
    # Same lever as #50: put the exact, EXECUTABLE call — lane-resolvable
    # reference path, every required argument (save_as is required — a taught
    # call that TypeErrors teaches the lane the tool is broken), the worst
    # region — inside the task so following it is easier than ignoring it.
    ref = _lane_visible_reference(output_dir, r.get("reference")) or r.get("reference")
    if ref:
        region = ""
        if devs and devs[0].get("region"):
            region = f", region={[round(v, 3) for v in devs[0]['region']]}"
        name = str(r.get("name") or "screen")
        lines.append(
            "VERIFY LIKE AN ENGINEER (measure, don't eyeball): after fixing, "
            "capture_webpage this route, then run "
            f"zoom_compare(reference=\"{ref}\", mine=\"<your capture .png>\", "
            f"save_as=\"design/compare/{name}_check.png\"{region}, scale=2) "
            "and view_image the saved comparison — the colors above must match "
            "before you consider this screen done.")
    return lines


def _spec_snippet(output_dir: Any, screen_name: str) -> str:
    """The pre-computed component spec's MEASURED values for one screen, compact.

    The framework decomposes every reference into design/component_specs/<screen>.json
    (named components + measured background/accent hex) before the lanes wake — but runs
    30-38 show the lane reads it ~once per run, then fixes visual tasks by eyeball. Embed
    the numbers directly in the remediation task so the fixing lane holds the exact spec
    (quality by gate, per the material-prep architecture rule). Empty on any failure."""
    try:
        p = Path(output_dir) / "design" / "component_specs" / f"{screen_name}.json"
        if not p.exists():
            return ""
        spec = json.loads(p.read_text(encoding="utf-8"))
        rows = []
        for c in (spec.get("components") or [])[:12]:
            acc = ", ".join(f"{k}={v}" for k, v in (c.get("accents") or {}).items())
            rows.append(f"  · {c.get('name')}: bg {c.get('background')}"
                        + (f", accents {acc}" if acc else "")
                        + (f" — {c.get('state')}" if c.get("state") else ""))
        if not rows:
            return ""
        return ("MEASURED SPEC (design/component_specs/" + screen_name + ".json — use these "
                "EXACT hex values, never eyeball):\n" + "\n".join(rows))
    except Exception:
        return ""


def remediation_text(result: Mapping[str, Any], output_dir: Any = None,
                     latched: Optional[set] = None) -> str:
    """Actionable task body for the frontend lane from a failed gate result —
    per screen: missing components first, then the judge's per-dimension notes
    (weakest dimension first), then the ordered deviations.

    ``latched`` (FIX #129) = the milestone's sticky-passed screen names. A screen
    that already cleared the bar in a prior round is EXCLUDED from the fix list
    even if the noisy judge scored it low THIS round — otherwise the frontend is
    told to re-work a screen it already got right and can REGRESS it. The gate is
    still open (some OTHER screen never latched), so remediation must focus the
    lane's effort on the screens that have never hit the bar."""
    latched = latched or set()
    lines = ["Visual fidelity below threshold vs the reference designs. "
             "Fix the implemented screens to match the references:"]
    dim_titles = {d["key"]: d["title"] for d in _DIMENSIONS}
    # A1/A2: load the design system + run the staged-asset audit ONCE;
    # per-screen results feed the first-position mandates and the geometry
    # blocks below, the audit remainder feeds the tail advisory.
    _ds = _load_design_system(output_dir)
    _audit = _load_asset_audit(output_dir, ds=_ds)
    _ab_on = _brand_asset_fix_enabled()
    _geo_on = _layout_geometry_enabled()
    _emitted: set = set()
    _mandated_screens = 0
    for r in result.get("screens", []):
        if r.get("passed") or r.get("name") in latched:
            continue
        lines.append(f"\n## {r['name']}  (route {r['route']}, similarity {r['similarity']:.2f})")
        if _ab_on and _audit is not None:
            # A1: a failing screen whose reference components map to staged real
            # assets the code never references gets the asset mandate FIRST —
            # run-50 class: the lane draws a generic approximation while the
            # real wordmark/glyph sits staged and unreferenced, and the judge
            # correctly scores the brand-less screen 0.2-0.4.
            _fx, _em = _screen_asset_fix_lines(
                str(r.get("name") or ""), str(r.get("route") or ""),
                _audit.get("unused_by_screen") or {}, output_dir)
            if _fx:
                lines.extend(_fx)
                _emitted |= _em
                _mandated_screens += 1
        if _geo_on:
            # A2: numeric skeleton right after the asset mandate, before the
            # measured colors — structure first, then paint.
            lines.extend(_layout_geometry_lines(_ds, str(r.get("name") or "")))
        if _theme_variant_enabled():
            # A2b: theme-variant screens need the RENDER MECHANISM stated, not
            # just the hex values.
            lines.extend(_theme_variant_lines(
                str(r.get("name") or ""), output_dir, str(r.get("route") or "")))
        if output_dir is not None:
            _sn = _spec_snippet(output_dir, str(r.get("name") or ""))
            if _sn:
                lines.append(_sn)
        lines.extend(_measured_diff_lines(r, output_dir))
        dims = r.get("dimensions") or {}
        missing = (dims.get("components") or {}).get("missing") or []
        if missing:
            lines.append("Missing components (build these first): " + ", ".join(missing))
        for key, rec in sorted(dims.items(), key=lambda kv: kv[1].get("score", 0.0)):
            if rec.get("notes"):
                lines.append(f"- [{dim_titles.get(key, key)} {rec.get('score', 0):.2f}] {rec['notes']}")
            if rec.get("fix"):
                lines.append(f"  FIX: {rec['fix']}")
        devs = r.get("deviations") or []
        if devs:
            lines.append("Differences (where + what):")
            for d in devs:
                lines.append(f"- {d}")
        fixes = r.get("fixes") or []
        if fixes:
            lines.append("Do these, in order:")
            for i, f in enumerate(fixes, 1):
                lines.append(f"{i}. {f}")
    adv = _asset_usage_advisory(
        output_dir, exclude=_emitted,
        unused=(_audit.get("unused_mapped") if _audit is not None else None))
    if adv:
        lines.append(adv)
    if _audit is not None:
        # A1 observability: one stable-prefix line per remediation build so the
        # per-round trend is greppable across runs (gate the escalate-to-gate
        # decision on this data).
        _LOG.info(
            "BRAND-ASSET AUDIT: %d unused mapped asset(s) total; %d mandated "
            "first-position on %d failing screen(s)",
            len(_audit.get("unused_mapped") or []), len(_emitted), _mandated_screens)
    lines.append("\nReference images: use list_reference_images / view_image. "
                 "Your screenshots from the last gate run are in design/visual_gate/.")
    return "\n".join(lines)


def _brand_asset_fix_enabled() -> bool:
    """A1 kill switch: ENVGEN_BRAND_ASSET_FIX=0 reverts to the tail-advisory-only
    behavior (first-position mandates off)."""
    return str(os.environ.get("ENVGEN_BRAND_ASSET_FIX", "1")).strip().lower() \
        not in ("0", "false", "no", "off")


def _load_design_system(output_dir: Any) -> Optional[Dict[str, Any]]:
    """design/design_system.json as a dict; None when absent/invalid (a
    references-only run) — the A-direction remediation enrichments key off
    this one load."""
    if output_dir is None:
        return None
    try:
        ds_path = Path(output_dir) / "design" / "design_system.json"
        if not ds_path.is_file():
            return None
        return json.loads(ds_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_asset_audit(output_dir: Any, ds: Optional[Mapping[str, Any]] = None
                      ) -> Optional[Dict[str, Any]]:
    """Run the staged-asset usage audit once per remediation build. None when
    there is no design_system (references-only run) or on any error."""
    if ds is None:
        ds = _load_design_system(output_dir)
    if ds is None:
        return None
    try:
        from .frontend_audit import audit_asset_usage
        return audit_asset_usage(Path(output_dir) / "app" / "frontend", ds)
    except Exception:
        return None


def _layout_geometry_enabled() -> bool:
    """A2 kill switch: ENVGEN_LAYOUT_GEOMETRY_FIX=0 drops the geometry block."""
    return str(os.environ.get("ENVGEN_LAYOUT_GEOMETRY_FIX", "1")).strip().lower() \
        not in ("0", "false", "no", "off")


def _layout_geometry_lines(ds: Optional[Mapping[str, Any]], screen_name: str) -> List[str]:
    """A2: the measured LAYOUT GEOMETRY block for one failing screen — the
    analyst layout sentence + each component's normalized region rendered as
    viewport percentages (+ bg hex). A1 validation (run-75) drove asset
    coverage on the failing screens to 100% while their scores stayed
    0.15-0.40: the residual gap is the SKELETON (single- vs two-column login =
    the 0.0→0.4 jump class), which was never stated numerically — #52's
    _spec_snippet carries colors, this carries geometry. Empty when nothing
    is measured."""
    if ds is None:
        return []
    try:
        screen = next(
            (s for s in (ds.get("screens") or [])
             if isinstance(s, dict) and str(s.get("name") or "") == screen_name),
            None)
        if screen is None:
            return []
        rows: List[str] = []
        layout = str(screen.get("layout") or "").strip()
        for comp in (screen.get("components") or [])[:10]:
            if not isinstance(comp, dict):
                continue
            reg = comp.get("region")
            if not (isinstance(reg, (list, tuple)) and len(reg) == 4):
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in reg)
            except Exception:
                continue
            bg = (comp.get("colors") or {}).get("bg") if isinstance(
                comp.get("colors"), Mapping) else None
            rows.append(
                f"  · {comp.get('id')}: x {x1 * 100:.0f}-{x2 * 100:.0f}% "
                f"(width {(x2 - x1) * 100:.0f}%), y {y1 * 100:.0f}-{y2 * 100:.0f}% "
                f"(height {(y2 - y1) * 100:.0f}%)"
                + (f", bg {bg}" if bg else ""))
        if not rows and not layout:
            return []
        lines = ["LAYOUT GEOMETRY (measured from the reference — match the "
                 "SKELETON first, then style):"]
        if layout:
            lines.append(f"  structure: {layout}")
        lines.extend(rows)
        return lines
    except Exception:
        return []


def _page_component_for_route(output_dir: Any, route: str) -> str:
    """Resolve the ui_page COMPONENT wired at ``route`` from the registry store
    (shared/hubs/registryhub_ui_pages.json) by ROUTE equality — the visual screen
    name (login_dark) and the ui_page name (login) do not align, routes do
    (A1 supervisor requirement: route↔route, no name fuzzy-matching). '' when
    the store is absent or no page declares the route."""
    try:
        recs = json.loads(
            (Path(output_dir) / "shared" / "hubs" / "registryhub_ui_pages.json")
            .read_text(encoding="utf-8"))
        want = str(route or "").rstrip("/") or "/"
        for name, rec in (recs.items() if isinstance(recs, dict) else []):
            if name == "_meta" or not isinstance(rec, dict):
                continue
            have = str(rec.get("route") or "").rstrip("/") or "/"
            if have == want and rec.get("component"):
                return str(rec["component"])
    except Exception:
        pass
    return ""


def _screen_asset_fix_lines(screen_name: str, route: str,
                            unused_by_screen: Mapping[str, Any],
                            output_dir: Any) -> tuple:
    """A1: the FIRST-position block for one failing screen — mandate rendering
    the staged real assets its reference components map to, naming the target
    page file (route-aligned) and the exact /assets/ path. Returns
    (lines, {(component, asset), ...}) — the pairs are excluded from the tail
    advisory so nothing is stated twice."""
    ents = list(unused_by_screen.get(screen_name) or [])
    if not ents:
        return [], set()
    comp = _page_component_for_route(output_dir, route)
    where = (f"app/frontend/src/pages/{comp}.jsx (the page wired at route {route})"
             if comp else f"the page component wired at route {route}")
    lines = ["USE THE REAL STAGED ASSETS FIRST — this screen's reference "
             "components are mapped to staged files your code never references; "
             "render them before any other fix:"]
    emitted = set()
    for u in ents[:6]:
        lines.append(
            f"- render `/assets/{u['file']}` for component `{u['component']}` in "
            f"{where} (<img src='/assets/{u['file']}'/> or import the SVG) — "
            "do NOT draw an approximation.")
        emitted.add((u.get("component"), u.get("asset")))
    if len(ents) > 6:
        lines.append(f"- (+{len(ents) - 6} more mapped assets unreferenced on this "
                     f"screen — see design/design_system.json screens `{screen_name}`)")
    return lines, emitted



def _theme_variant_enabled() -> bool:
    """A2b kill switch: ENVGEN_THEME_VARIANT_FIX=0 drops the mechanism block."""
    return str(os.environ.get("ENVGEN_THEME_VARIANT_FIX", "1")).strip().lower() \
        not in ("0", "false", "no", "off")


def _theme_variant_lines(screen_name: str, output_dir: Any = None,
                         route: str = "") -> List[str]:
    """A2b: the THEME MECHANISM block for a theme-variant failing screen.
    login_dark sat at 0.15 across run-73/75/76 while its measured dark hexes
    were already inlined (A2): the missing piece was HOW a dark variant is
    rendered — the gate (#141) captures the SAME route component with
    html.dark + [data-theme=dark] + prefers-color-scheme:dark, so without
    dark-variant CSS the dark capture photographs light pixels and the judge's
    low score is honest (run-65). State the mechanism; forbid a forked page."""
    scheme = screen_color_scheme({"name": screen_name})
    if scheme is None:
        return []
    if scheme == "dark":
        how = ("the gate renders this route with `html.dark` set, "
               "`[data-theme=\"dark\"]`, and prefers-color-scheme:dark emulated. "
               "Implement the dark styles on the SAME page component via Tailwind "
               "`dark:` variants (set `darkMode: 'class'` in tailwind.config) or "
               "`.dark`-scoped CSS — do NOT fork a separate page. Use the "
               "measured dark hex values from the geometry/spec blocks above.")
    else:
        how = ("the gate renders this route in LIGHT mode (theme storage keys "
               "cleared, no `html.dark`). The light appearance must come from "
               "the default (non-dark:) styles of the SAME page component that "
               "also serves the dark variant — do NOT fork a separate page.")
    lines = [f"THEME VARIANT ({scheme.upper()} capture): {how}"]
    if scheme == "dark" and output_dir is not None and route:
        # run-78 autopsy: the lane wrote perfect dark: variants (measured
        # hexes) into components no page imports, while the WIRED page file
        # stayed bg-white — point the work at the file that actually renders.
        try:
            comp = _page_component_for_route(output_dir, route)
            if comp:
                _pf = (Path(output_dir) / "app" / "frontend" / "src" / "pages"
                       / f"{comp}.jsx")
                if _pf.is_file() and "dark:" not in _pf.read_text(
                        encoding="utf-8", errors="ignore"):
                    lines.append(
                        f"  ⚠ app/frontend/src/pages/{comp}.jsx (the file WIRED at "
                        f"{route}) currently has no `dark:` variant at all — dark "
                        "styles written in any other file that this page does not "
                        "import are DEAD code and never render. Add the dark: "
                        "variants IN THIS FILE (or in components it actually "
                        "imports).")
        except Exception:
            pass
    return lines


def _asset_usage_advisory(output_dir: Any, exclude: Optional[set] = None,
                          unused: Optional[List[dict]] = None) -> str:
    """ADVISORY block (Design-Prep): when design/design_system.json maps components to REAL staged
    assets that the frontend does not reference, tell the lane to use them instead of drawing
    approximations. A1: ``exclude`` = (component, asset) pairs already mandated first-position on a
    failing screen (not repeated here); ``unused`` = precomputed audit rows (audit runs once).
    Best-effort; '' when there is no design_system or nothing to flag."""
    if output_dir is None:
        return ""
    try:
        if unused is None:
            _audit = _load_asset_audit(output_dir)
            unused = (_audit.get("unused_mapped") if _audit is not None else None) or []
        excl = exclude or set()
        rows = [u for u in unused if (u.get("component"), u.get("asset")) not in excl]
        if not rows:
            return ""
        out = ["\n## Real assets not used (advisory — use the STAGED asset, do not draw it):"]
        for u in rows[:20]:
            out.append(f"- component `{u['component']}` should render real asset "
                       f"`{u['asset']}` → reference `/assets/{u['file']}` "
                       f"(<img src='/assets/{u['file']}'/> or import it), not a hand-drawn shape.")
        return "\n".join(out)
    except Exception:
        return ""


try:  # FIX #75a: how many mid-rebuild blank captures to absorb before a still-blank
    # route becomes a real 0.00 verdict (so a truly-broken app can't defer forever).
    _TRANSIENT_REFUND_CAP = int(os.environ.get("ENVGEN_VISUAL_BLANK_REFUNDS", "3"))
except Exception:
    _TRANSIENT_REFUND_CAP = 3


def _apply_sticky_pass(passed_names: set, screens: List[Mapping[str, Any]]) -> bool:
    """FIX #129 — STICKY per-screen pass across re-judge rounds WITHIN a milestone.

    The vision JUDGE (Gemini) self-compresses similarity toward the center and
    noise-wiggles the same UNCHANGED pixels by ±0.2–0.4 between calls (run-47:
    "adjusting the extreme values … closer to a central point"; the JUDGE-ON-CHANGE
    guard at maybe_run exists precisely because "scores just noise-wiggled").
    Requiring EVERY blocking screen to clear ``min_similarity`` on the SAME
    re-judge is therefore a joint-probability wall: with N center-clustered noisy
    screens the run essentially never passes and every milestone ships via the
    below-threshold escape (never a real pass). Instead, LATCH each blocking
    screen the first round it clears the bar; the gate is satisfied once every
    blocking screen has cleared AT LEAST ONCE this milestone.

    ``passed_names`` is the milestone-anchored latch set (mutated in place; reset
    in ``reset_for_milestone``). Advisory (overlay) screens are excluded upstream
    (#128), so they never enter the criterion. Env-agnostic. Trade-off: a screen
    that passed at source v1 and later regressed at v2 stays latched — accepted
    because judge noise (±0.4) makes a single low re-sample indistinguishable from
    a real regression, and app CORRECTNESS is enforced by the functional gates
    (api_smoke / page_build), not this design-fidelity gate.
    """
    blocking = [s for s in screens if not s.get("advisory")]
    for s in blocking:
        if s.get("passed"):
            passed_names.add(s.get("name"))
    return bool(blocking) and all(s.get("name") in passed_names for s in blocking)


class VisualFidelityGate:
    """Stateful visual-fidelity gate extracted from the Orchestrator (PROPOSAL
    #8 — VisualFidelity slice B). Owns the per-source judging budget + pass
    latch and the per-milestone deferral counters (the seven ``_vf_*`` fields
    the orchestrator used to carry inline) and runs the bounded
    judge-and-remediate loop. It borrows the orchestrator for I/O collaborators
    (the app-source signature, the run's LLM / output_dir / logger, the workhub
    and message bus) — this gate is a decomposed PART of the orchestrator, not a
    general utility.

    The blocking RELEASE decision stays in the orchestrator's deliver flow
    (``_visual_release_decision``); it reads + anchors this gate's counters
    (``passed`` / ``deferred_since`` / ``attempts`` / ``total_judgments``).
    """

    def __init__(self, orch: Any) -> None:
        self._orch = orch
        self.sig = None                # current app-source signature
        self.attempts = 0              # judged runs on the CURRENT source (cap 3)
        self.passed = False            # latched pass for the current source
        self.deferred_since = None     # wall-clock anchor of the milestone's FIRST defer
        self.total_judgments = 0       # per-milestone real-verdict count (backstop)
        self.transient_refunds = 0     # per-milestone bounded blank-capture refunds (#75a)
        self.last_result = None
        self.last_judged_sig = None
        self._passed_screens: set = set()  # #129: milestone-anchored sticky per-screen pass latch
        self._seed_reminder_sent = False   # #133: one backend seed reminder per milestone
        self._best_by_screen: Dict[str, float] = {}  # #138: best similarity per blocking screen
        self.plateau_rounds = 0            # #138: consecutive judgments with no new best
        self._verdict_cache: Dict[str, Dict[str, Any]] = {}  # #142: (screen, shot-md5) → verdict
        self.last_judgment_at = None       # #145: wall-clock of the last real judgment

    def reset_for_milestone(self) -> None:
        """Anchor the deferral clock + total-judgment backstop to a NEW milestone
        (PIPE-C3: within a milestone neither is reset by lane churn)."""
        self.deferred_since = None
        self.total_judgments = 0
        self.transient_refunds = 0     # #75a: milestone-anchored, not reset by sig churn
        self._passed_screens = set()   # #129: latch cleared per milestone, not by sig churn
        self._seed_reminder_sent = False  # #133: re-armed per milestone
        self._best_by_screen = {}      # #138: plateau tracking is per milestone
        self.plateau_rounds = 0
        self._verdict_cache = {}       # #142: pixel-keyed verdicts are per milestone
        self.last_judgment_at = None   # #145: idle-source stamp is per milestone

    def _frontend_wiring_blockers(self) -> list:
        """#417: declared ui_pages with a HARD wiring defect (declared route not
        wired in App.jsx, or the component file missing), via the delivery gate's
        OWN static check (``ui_page_delivery_blockers``). Used to gate the visual
        judge so it NEVER scores a pre-wiring app: api_smoke (which triggers this
        loop) probes the BACKEND only, so it goes green while frontend routes are
        still unwired — those routes fall through App.jsx's ``*`` catch-all and
        render a redirect/404 (a NON-blank page, so the capture_transient refund
        misses it), and the judge scores the projected UI at ~0.00. Best-effort
        ``[]`` on any fault — an audit hiccup must never wedge the judge shut."""
        orch = self._orch
        try:
            from .frontend_audit import ui_page_delivery_blockers
            from pathlib import Path as _P
            out = getattr(orch, "output_dir", None)
            workhub = getattr(getattr(orch, "hubs", None), "workhub", None)
            if not out or workhub is None:
                return []
            src = _P(out) / "app" / "frontend" / "src"
            if not src.exists():
                src = _P(out) / "frontend" / "src"
            return ui_page_delivery_blockers(src, workhub) or []
        except Exception:
            return []

    async def maybe_run(self) -> None:
        """VISUAL FIDELITY gate — runs after api_smoke passes. Screenshots the
        running frontend on the routes the reference images depict, has the
        vision model compare each pair, and on failure files an ACTIONABLE
        remediation task for the frontend lane (concrete per-screen deviations).
        Visual design stays the lane's job; this is the enforcement loop that
        makes the app converge to the references instead of to whatever the
        lane happened to ship. Bounded: 3 judged runs per app-source signature
        (each is N vision calls); a pass latches until the source changes.
        Best-effort — never raises into the coordination loop."""
        orch = self._orch
        try:
            refs = list(getattr(orch, "_reference_images", None) or [])
            if not refs:
                return
            sig = orch._compute_app_source_signature()
            if sig != self.sig:
                self.sig = sig
                self.attempts = 0   # fresh per-source judging budget (new pixels deserve a verdict)
                self.passed = False
                # PIPE-C3: do NOT reset deferred_since here. The deferral
                # wall-clock is anchored to the milestone's FIRST defer (set in
                # _maybe_framework_deliver, zeroed only at milestone start) — a
                # frontend lane that churns files on every visual-fail must NOT be
                # able to keep rewinding the 900s escape clock (the livelock that
                # left delivery deferred until the run's budget died).
            if self.passed:
                return
            if self.attempts >= 3:
                return  # budget spent on this source state — wait for lane changes
            if sig is not None and sig == self.last_judged_sig:
                # JUDGE-ON-CHANGE: identical source ⇒ identical pixels — re-
                # judging burns 7 vision calls to learn nothing (round 30:
                # 3 attempts on one source, scores just noise-wiggled). The
                # attempt budget counts DISTINCT source versions, so do NOT
                # spend an attempt on an unchanged signature (increment AFTER
                # this check).
                return
            # #417 (2026-08-02, live r13 diagnosis): do NOT judge until the
            # frontend is actually WIRED. api_smoke (which gates this loop via
            # framework_validation) probes the BACKEND only, so it goes green while
            # declared ui_pages are still unwired — their routes fall through
            # App.jsx's `*` catch-all and render a redirect/404 (NOT a blank shell,
            # so the capture_transient refund below never catches them). r13 judged
            # 12 screens at 18:22 (player.png 9.7KB, my_list.png 14KB — empty),
            # scored them 0.00–0.35, filed a misleading "UI doesn't match" P1, and
            # BURNED its one real attempt — yet the frontend didn't wire App.jsx
            # until 18:51 (24min later) and the projector's REAL output was never
            # judged (delivered below-threshold). Skip while pages are unwired: no
            # attempt spent, no verdict recorded, no misleading remediation. The
            # delivery gate's OWN deliverability_ui_page_unwired check already
            # blocks release until the lane wires them (orchestrator returns "not
            # deliverable yet" before the visual deferral clock is even anchored),
            # so this loop then makes its FIRST judgment on the WIRED app. Reuses
            # the delivery gate's single-source wiring check — env/app-agnostic.
            _unwired = self._frontend_wiring_blockers()
            if _unwired:
                orch._logger.warning(
                    "Visual fidelity: %s ui_page(s) still UNWIRED (e.g. %s) — "
                    "deferring the judge until the frontend is wired (no attempt "
                    "spent). Scoring a pre-wiring app judges catch-all/404 routes, "
                    "not the projected UI.",
                    len(_unwired), str(_unwired[0])[:120])
                return
            self.attempts = self.attempts + 1
            # Per-component MODEL config: the visual JUDGE may run its own model
            # (component_models.visual_judge / ENVGEN_MODEL_VISUAL_JUDGE).
            try:
                from .llm_overrides import get_component_llm
                _judge_llm = get_component_llm(orch, "visual_judge") or orch.llm
            except Exception:
                _judge_llm = orch.llm
            result = await run_visual_fidelity(orch.output_dir, refs, _judge_llm,
                                               verdict_cache=self._verdict_cache)
            if result.get("capture_unavailable") or result.get("auth_unavailable"):
                # Not a judgment — the app wasn't reachable (mid-rebuild) or
                # the authed session was rejected wholesale (token mint failed
                # / every auth route bounced to /login — round 31 judged the
                # LOGIN PAGE against feed/profile references, 0.2s across the
                # board). Refund so the budget only counts REAL verdicts.
                self.attempts = max(0, self.attempts - 1)
                orch._logger.warning(
                    "Visual fidelity: %s — attempt refunded, will retry next tick.",
                    result.get("summary") or "capture/auth unavailable")
                return
            # FIX #75a: EVERY judged screen was an un-hydrated blank shell (capture_transient
            # ⇒ no real verdict obtained) — a mid-rebuild snapshot, not a design failure.
            # Refund the attempt so the blank doesn't burn the 3-run budget, BOUNDED by
            # _TRANSIENT_REFUND_CAP (milestone-anchored) so a GENUINELY blank app can't defer
            # forever: past the cap this branch is skipped and the blank 0.00 flows to a real
            # verdict + remediation below. Partial-blank captures set capture_transient=False
            # (they carry real sibling verdicts), so they are judged/remediated normally here.
            if result.get("capture_transient") and self.transient_refunds < _TRANSIENT_REFUND_CAP:
                self.transient_refunds += 1
                self.attempts = max(0, self.attempts - 1)
                orch._logger.warning(
                    "Visual fidelity: %s — blank capture, attempt refunded "
                    "(transient %s/%s).", result.get("summary") or "blank shell",
                    self.transient_refunds, _TRANSIENT_REFUND_CAP)
                return
            screens = result.get("screens") or []
            self.last_result = result
            self.last_judged_sig = sig
            # PIPE-C3: per-milestone real-judgment counter (NOT reset on sig
            # change — only at milestone start). A vision-cost backstop escape so a
            # churning lane that keeps flipping the source signature can't drive
            # unbounded judging even before the 900s wall-clock escape fires.
            self.total_judgments = self.total_judgments + 1
            self.last_judgment_at = time.time()  # #145: idle-source escape stamp
            # FIX #138: plateau tracking — a real judgment where NO blocking screen
            # beats its best-so-far (+0.02 noise epsilon) increments plateau_rounds;
            # ANY genuine improvement re-arms it. _visual_release_decision escapes
            # early once the scores have flatlined (log-mining runs 50-62: the final
            # window averaged ~65min, ~40% of total wall-clock, and never passed).
            _improved = False
            for _s in screens:
                if _s.get("advisory"):
                    continue
                _n, _sim = str(_s.get("name")), float(_s.get("similarity") or 0.0)
                if _sim > self._best_by_screen.get(_n, 0.0) + 0.02:
                    self._best_by_screen[_n] = _sim
                    _improved = True
                elif _n not in self._best_by_screen:
                    self._best_by_screen[_n] = _sim
            self.plateau_rounds = 0 if _improved else self.plateau_rounds + 1
            # FIX #129: latch each blocking screen that cleared the bar this round;
            # the gate passes once EVERY blocking screen has cleared at least once
            # this milestone (defeats the joint-probability wall the noisy judge
            # otherwise makes unpassable — see _apply_sticky_pass).
            sticky_pass = _apply_sticky_pass(self._passed_screens, screens)
            if result.get("passed") or sticky_pass:
                self.passed = True
                _how = "" if result.get("passed") else (
                    " [sticky: every blocking screen cleared ≥min at least once "
                    "this milestone; latched=%s]" % ", ".join(sorted(self._passed_screens)))
                orch._logger.warning(
                    "Visual fidelity PASSED (%s): %s%s",
                    ", ".join(f"{s['name']}={s['similarity']:.2f}" for s in screens),
                    result.get("summary"), _how)
                return
            orch._logger.warning(
                "Visual fidelity attempt %s/3 FAILED — %s",
                self.attempts, result.get("summary"))
            try:
                _vt = orch.hubs.workhub.create_task(
                    title=f"UI does not match reference designs (visual gate, attempt {self.attempts})",
                    description=remediation_text(result, getattr(orch, "output_dir", None),
                                                 latched=self._passed_screens),
                    assignee="frontend",
                    agent="orchestrator",
                    priority="P1",
                )
                # Wake the frontend NOW — milestone work is done at this
                # point and the lane otherwise idles through the deferral.
                try:
                    from tools.communication_tools import _create_message
                    _msg = _create_message(
                        source_agent_id="orchestrator",
                        target_agent_id="frontend",
                        content=(
                            "Visual-fidelity remediation task assigned "
                            f"(task_id={(_vt or {}).get('id')}). Claim it and "
                            "fix the listed per-screen deviations NOW — the "
                            "milestone release is DEFERRED until the UI "
                            "matches the references (or attempts exhaust)."),
                        msg_type="task_ready",
                        priority="urgent",
                        persist=True,
                        tags=["visual_fidelity", "remediation"],
                    )
                    await orch.message_bus.send(_msg)
                except Exception:
                    pass
            except Exception as exc:
                orch._logger.error("visual-fidelity task creation failed: %s", exc)
            # FIX #133: EMPTY-STATE screens are a BACKEND-data problem the frontend
            # cannot style away — the reference's design skeleton (feed cards, video
            # chrome) only renders WITH rows, so the judge can never fairly score the
            # screen (run-47/50: reels "No reels available" pinned 0.0-0.4 all window).
            # Remind the BACKEND lane ONCE per milestone to seed the missing rows
            # (workhub.create_task does NOT dedupe — the guard prevents a task per
            # re-judge round; reset in reset_for_milestone).
            try:
                _empty = sorted({str(r.get("name")) for r in screens
                                 if r.get("empty_state") and not r.get("passed")})
                if _empty and not self._seed_reminder_sent:
                    self._seed_reminder_sent = True
                    _bt = orch.hubs.workhub.create_task(
                        title="Visual gate: screen(s) render an EMPTY state — seed the missing rows",
                        description=(
                            "The visual-fidelity judge flagged these screens as EMPTY-state: "
                            + ", ".join(_empty) + ". Their reference design only renders when "
                            "the backing table has rows (e.g. a reels page needs video posts), "
                            "so the screen can never match the reference no matter what the "
                            "frontend does. Add realistic seed rows (>=3) for each screen's "
                            "backing table(s) to app/backend/seed_data.json — keep FK "
                            "references consistent with the existing seed users/posts."),
                        assignee="backend",
                        agent="orchestrator",
                        priority="P1",
                    )
                    try:
                        from tools.communication_tools import _create_message
                        _bmsg = _create_message(
                            source_agent_id="orchestrator",
                            target_agent_id="backend",
                            content=(
                                "Seed-data task assigned "
                                f"(task_id={(_bt or {}).get('id')}): the visual gate found "
                                f"EMPTY-state screen(s) [{', '.join(_empty)}] whose design "
                                "cannot render without data. Add seed rows for their backing "
                                "tables to app/backend/seed_data.json NOW."),
                            msg_type="task_ready",
                            priority="urgent",
                            persist=True,
                            tags=["visual_fidelity", "seed_data"],
                        )
                        await orch.message_bus.send(_bmsg)
                    except Exception:
                        pass
            except Exception as exc:
                orch._logger.error("empty-state seed reminder failed (non-fatal): %s", exc)
        except Exception as exc:
            orch._logger.error("visual fidelity gate raised (non-fatal): %s", exc)
