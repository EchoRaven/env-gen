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
import asyncio as _asyncio
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Set

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


try:   # #646: one viewport for the whole pipeline (see _bootstrap for why)
    from ...tools.browser._bootstrap import CANONICAL_VIEWPORT_646 as _CV646
except Exception:  # pragma: no cover — import-shape safety only
    _CV646 = {"width": 1380, "height": 900}
_VIEWPORT = dict(_CV646)

# #644 — THE CAPTURE AND THE REFERENCE ARE DIFFERENT SHAPES. MEASURED, NOT ACTED ON.
# `_VIEWPORT` is the one constant in this module carrying no measured rationale. Against the
# corpus (all 900 reference images in the 45 kept runs):
#
#     reference aspect  1.7297-1.7391, median 1.7344   capture 1380x900 = 1.5333   (13.1% apart)
#
# and, measured on 389 screens where a top edge is detectable in BOTH images:
#
#     reference top edge   97px of 1107  -> fraction 0.0876
#     capture   top edge   86px of  900  -> fraction 0.0956
#
# I changed the viewport to 796px (width / median aspect) and then measured the consequence
# instead of assuming it. The two objectives point in OPPOSITE directions:
#
#     make the two IMAGES the same shape (what the judge compares)  -> 796px
#     make CONTENT land at the same FRACTION (what the spec sampler
#     assumes, `_measured_deviations` -> spec_color_deviations)     -> 981px
#
# because web layout is absolute from the top and scales with WIDTH, so a shorter viewport makes
# a fixed-height nav bar occupy a LARGER fraction, not a smaller one. 796px would have taken the
# sampler's error from +9.1% to +23%. The change is therefore REVERTED, and only the measurement
# is kept: I have no offline evidence that the judge scores a same-shaped pair any better, and
# the one half I could measure moved the wrong way.
#
# `capture_viewport_644` is retained as the aspect calculation, unused by the capture path, so
# whichever direction a future run's data supports can be wired without re-deriving this.
_VIEWPORT_FALLBACK_H_644 = 900

# #872: ceiling on ONE judge call including its re-rolls. `utils.llm` caps a completion at 240s
# (FIX #187) and the retry layer is capped at 3 attempts (#890), so one call is ~12 MINUTES
# worst case -- bounded, and large enough to eat a round. Per SCREEN, so a round of ~12 is at
# 12 x this rather than unbounded. Env-overridable. Placed AFTER the constant above, not before
# it: inserting between #644's rationale and its number orphaned that rationale and #647's guard
# caught it — a seam, not a logic error.
# #898: DERIVED from the live per-call watchdog, not hardcoded. r153 measured 6550
# completions with max 588.9s -- 2.45x the 240s I had calibrated against, because 240 is
# `_llm_hard_timeout(None, ...)` (the UNSET default) while config.py sets timeout=1800, so
# the live cap is min(1800, 600) = 600s. The old 300s sat at HALF the real watchdog and
# would have cut that 588.9s call in two.
# ★ imported INSIDE the function: three tests exec this module's source into a synthetic
# package and hand-stub each module-level relative import, so a new one there fails at
# collection with `No module named '<pkg>.stage_contract'` (#853/#889 hit this too).
# Calling it per use also means the ceiling tracks a config change without a restart.
def _spent_verdict_892(screen: Mapping[str, Any]) -> Dict[str, Any]:
    """#892: the verdict a screen gets when the round budget ran out before it was judged.

    ★ Extracted so it can be EXECUTED. Every one of #892's original seven assertions read the
    source text (`assert '"judge_error": True' in block`), and the round budget is
    `max(_judge_timeout_s_872(), env)` — the env var can only RAISE it — so nothing in a test or in
    the field could ever reach this path. A mechanism whose only checks are string matches on code
    that never runs is the exact shape this session has been finding in other people's tickets.

    The shape is load-bearing, which is why it deserves a real test. `judged = {r["name"] for r in
    results}` counts a screen that appears AT ALL, so this record is what keeps a budget-spent
    round RECOVERABLE: skipping the screen leaves it `unjudged`, and an unjudged owned screen fails
    the verdict outright. `judge_error` + `similarity: 0.0` is the state #142 refuses to cache, so
    the screen is re-judged next round rather than frozen at zero.
    """
    return {
        "name": screen["name"], "route": screen["route"],
        "similarity": 0.0, "dimensions": {},
        "deviations": ["not judged this round: the round budget was spent (#892)"],
        "summary": "round budget spent", "judge_error": True,
        "advisory": bool(screen.get("advisory")),
    }


def _judge_timeout_s_872() -> float:
    from .stage_contract import llm_ceiling_898
    return llm_ceiling_898("ENVGEN_JUDGE_TIMEOUT_S")


def _references_dir_644(anywhere: Any) -> Optional[Path]:
    """`design/references` found from any path inside the project tree (the capture helper is
    handed an out_dir, not the project root)."""
    try:
        here = Path(str(anywhere)).resolve()
        for base in (here, *here.parents):
            cand = base / "design" / "references"
            if cand.is_dir():
                return cand
    except Exception:
        pass
    return None


def capture_viewport_644(project_dir: Any) -> Dict[str, int]:
    """The capture viewport, with its height matched to the reference aspect. Never raises."""
    width = int(_VIEWPORT["width"])
    try:
        from PIL import Image
        refs = _references_dir_644(project_dir)
        ratios = []
        for p in sorted(refs.glob("*")) if refs else []:
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            try:
                with Image.open(p) as im:
                    w, h = im.size
                if w > 0 and h > 0:
                    ratios.append(w / h)
            except Exception:
                continue
        if ratios:
            ratios.sort()
            median = ratios[len(ratios) // 2]
            if 0.2 < median < 10:          # a sane aspect; never trust a corrupt read
                return {"width": width, "height": max(320, round(width / median))}
    except Exception:
        pass
    return {"width": width, "height": _VIEWPORT_FALLBACK_H_644}


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
            # #747: KEEP THE REFERENCE THE PAGE DECLARED. This projection dropped `metadata`
            # at the door, and `metadata.reference_image` is where the lane states which
            # reference image the page it just built corresponds to. It is not rare and it is
            # not guesswork: across the corpus **1182** ui_page records carry it, 54 distinct
            # values, and **1119 of them (94.7%) name a file that exists in that run's
            # design/references/**. The misses are almost all an extension mismatch (the lane
            # wrote `landing.png`, the staged file is `landing.jpg`), which is why the match
            # below is on the STEM.
            items = [{"name": v.get("name") or k, "route": v.get("route"),
                      "component": v.get("component"),
                      "reference_image": ((v.get("metadata") or {}).get("reference_image")
                                          if isinstance(v.get("metadata"), Mapping) else None)}
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
            # #747: read from EITHER shape. The dict branch above already lifted it out of
            # `metadata`; the list branch passes raw records straight through, so it is still
            # nested there. My first edit only touched `items` and this projection dropped it
            # again one loop later — the field has to survive the LAST place it is rebuilt.
            _ri747 = v.get("reference_image")
            if not _ri747 and isinstance(v.get("metadata"), Mapping):
                _ri747 = (v.get("metadata") or {}).get("reference_image")
            out.append({"name": str(v.get("name") or ""), "route": route,
                        "component": str(v.get("component") or ""),
                        "reference_image": str(_ri747).strip() if _ri747 else None})
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
        # #542a: a TRANSIENT interaction-STATE name (hover/preview/ad — see
        # _TRANSIENT_STATE_RE) is one a static route capture can NEVER reproduce, so — like a
        # structural overlay token — it never inherits a ui_page route / gets promoted to a
        # blocking page, and it is ALWAYS advisory (the classification branch below).
        _transient_by_name = bool(_TRANSIENT_STATE_RE.search(stem))
        # #747: A DECLARATION BEATS A NAME MATCH. #416 infers the design_screen <-> ui_page
        # link from token overlap because it assumed nothing states it. Something does: the
        # lane writes `metadata.reference_image` on the page it just built — 1182 times across
        # the corpus, 94.7% of them naming a file that really is in that run's references. The
        # framework dropped the field in `load_ui_pages` and went on guessing.
        #
        # This is the user's own proposal ("let the frontend agent that implements it transmit
        # which page maps to which reference"), and the data to honour it has been arriving all
        # along. Matched on the STEM: the 63 non-resolving values are almost entirely an
        # extension mismatch (`landing.png` declared, `landing.jpg` staged), and a declaration
        # that is right about WHICH screen should not be discarded over a file suffix.
        #
        # Placed ahead of #416 and subject to exactly the same two exclusions — an overlay or
        # transient-state name is still never given a page route (#128/#542a own those, and a
        # declaration must not be able to promote a dropdown into a blocking screen).
        _declared_page = None
        if not (_overlay_by_name or _transient_by_name):
            for _pg in pages:
                _ri = str(_pg.get("reference_image") or "").strip()
                if not _ri:
                    continue
                _ri_stem = re.sub(r"[^a-z0-9]+", "_", Path(_ri).stem.lower())
                if _ri_stem and _ri_stem == stem:
                    _rt = str(_pg.get("route") or "").strip()
                    if _rt and (not known or _rt in known):
                        _declared_page = _pg
                        break
        _guessed_page = (None if (_overlay_by_name or _transient_by_name)
                         else _match_ui_page(_screen_name_tokens(p.stem, stem), pages, known))
        # #758: SAY WHEN THE DECLARATION DECIDED, AND WHEN IT OVERRULED THE GUESS. #747 shipped
        # silent, so r149 — which carried 15 declarations and ran with #747 in its build — left
        # no way to tell whether a single binding came from the declaration or from the token
        # heuristic that has always been there. An improvement nobody can see fired is the same
        # shape as #722/#723/#748, and item 67's own open question ("do the two ever disagree?")
        # is unanswerable without this line. DISAGREEMENT is the case worth the WARNING: it
        # means the heuristic has been binding a reference to the wrong page and no artifact
        # ever said so.
        if _declared_page is not None:
            _dr758 = str(_declared_page.get("route") or "")
            _gr758 = str((_guessed_page or {}).get("route") or "")
            if _guessed_page is not None and _gr758 != _dr758:
                _LOG.warning(
                    "#758 declared reference OVERRULES the name guess for screen '%s': the "
                    "page that declared it serves %s, token matching would have bound %s. The "
                    "declaration wins (#747) — and every earlier run took the guess.",
                    p.stem, _dr758 or "(none)", _gr758 or "(none)")
            else:
                _LOG.info(
                    "#758 declared reference bound screen '%s' -> %s (the lane stated it; "
                    "no guess needed).", p.stem, _dr758 or "(none)")
        _matched_page = _declared_page or _guessed_page
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
        # #356: auth follows the RESOLVED route, never a filename token.
        # #73 (netflix r77, 2026-08-05): a framework-public route (login/signup) is
        # PUBLIC BY CONSTRUCTION (framework-injected; a login page MUST be reachable
        # logged-out — see _FRAMEWORK_PUBLIC_ROUTES comment). The old guard let a
        # design_analyst that MIS-MEASURED requires_auth=true for the login screen
        # OVERRIDE this → login captured AUTHED → its `if(isAuthed())nav('/profiles')`
        # redirect fired → the judge scored the WRONG (redirected) page ~0.00 (r77
        # login=0.00, a top Part-A drag). A measured requires_auth on a framework-public
        # route is ALWAYS a measurement error, so the by-construction fact wins: capture
        # these routes logged-out regardless of the (wrong) measured flag. Non-public
        # routes are unaffected (their measured requires_auth still governs, line 345).
        if route in _FRAMEWORK_PUBLIC_ROUTES:
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
            # (and its name is not a structural overlay / transient-state token —
            # enforced when _matched_page was resolved) -> it is a real page, judged
            # BLOCKING even if #132's pixel-only pass mislabeled it kind='overlay' (it
            # can't see that the app built a page for it). This is the ONLY path that
            # overrides the overlay label; a genuine overlay with no dedicated page
            # (account_menu, *_dropdown) never matches a ui_page, so #128 holds and
            # it stays advisory.
            advisory = False
        elif _transient_by_name:
            # #542a: a transient interaction-STATE name (hover/preview/ad) is authoritative —
            # such a screen has no navigable route of its own (it is a popover/card/ad slot
            # layered on a base page), so it is ADVISORY even when the pixel-only analyst
            # mislabeled it kind='page'. #389: the analyst's kind comes back INVERTED for
            # screens that SHARE a route (netflix: card_hover_preview[page] <-> browse_home @
            # /browse), which is exactly how card_hover_preview was scored 0.35 as a blocking
            # screen and dragged the mean. The duplicate-route pass (below) is the complementary
            # signal for a NON-transient-named screen that still duplicates a route.
            advisory = True
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
    remaining cap budget goes to advisory extras.

    #542b: the judged set is DETERMINISTIC run-to-run — the routed screens are sorted by
    name before the blocking/advisory split, so the same measured input yields the same
    judged set AND the same order every run (the analyst's run-to-run screen ORDERING no
    longer changes which advisory extras fill the cap, i.e. the gating denominator). Blocking
    screens are all judged regardless of order, so this never changes the gating verdict —
    only makes the exam reproducible."""
    routed = sorted((s for s in screens if s.get("route")),
                    key=lambda s: str(s.get("name") or ""))
    blocking = [s for s in routed if not s.get("advisory")]
    advisory = [s for s in routed if s.get("advisory")]
    return blocking + advisory[:max(0, max_screens - len(blocking))]


def _norm_screen_stem(name: Any) -> str:
    """Normalized stem of a screen name for the token regexes (matches map_reference_screens)."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _screen_is_transient(screen: Mapping[str, Any]) -> bool:
    """#542a: is this screen a TRANSIENT interaction state (hover/preview/ad or a structural
    overlay: modal/dialog/popover/tooltip/flyout/menu/…) that a static route capture cannot
    reproduce? Pure name-token test over BOTH vocabularies. Generalizable; no product literals."""
    stem = _norm_screen_stem(screen.get("name"))
    return bool(_TRANSIENT_STATE_RE.search(stem) or _OVERLAY_NAME_RE.search(stem))


def _demote_duplicate_route_screens(
        screens: List[Dict[str, Any]],
        owned: Optional[set] = None) -> List[Dict[str, Any]]:
    """#542a: when several judged screens resolve to the SAME concrete capture route, a static
    route-capture navigates to that ONE route and produces the SAME screenshot for all of them
    (netflix: card_hover_preview and browse_home both -> /browse -> BYTE-IDENTICAL PNGs, yet the
    duplicate was scored 0.35 as a blocking screen and mechanically lowered the mean). Only ONE
    screen can be the canonical page for a route; the rest are transient interaction states
    layered on it and cannot be fairly scored as blocking pages.

    Keep exactly ONE blocking screen per route (deterministic canonical: an ``owned`` page wins,
    then a real page — non-advisory AND not transient-named — then the earliest name) and mark
    every OTHER same-route screen ADVISORY. In-place + returns ``screens``. This ONLY ever
    demotes (never promotes), and a route with a single routed screen is untouched, so gating is
    byte-identical when there are no duplicate-route screens."""
    own = {str(n) for n in (owned or set())}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for s in screens:
        r = s.get("route")
        if not r:
            continue
        groups.setdefault(_concrete_capture_route(str(r)), []).append(s)
    for group in groups.values():
        if len(group) < 2:
            continue

        def _canon_key(s: Mapping[str, Any]):
            name = str(s.get("name") or "")
            # smaller sorts first -> canonical: an owned page, then a real (non-advisory,
            # non-transient) page, then the earliest name (stable + deterministic).
            return (0 if name in own else 1,
                    1 if s.get("advisory") else 0,
                    1 if _screen_is_transient(s) else 0,
                    name)

        canonical = min(group, key=_canon_key)
        for s in group:
            if s is not canonical and not s.get("advisory"):
                s["advisory"] = True
    return screens


def _blocking_similarity_average(results: List[Mapping[str, Any]]) -> float:
    """#542a: the gating fidelity average over BLOCKING screens ONLY — advisory
    (overlay/hover/preview/modal/duplicate-route) screens are EXCLUDED so a transient screen a
    static projector cannot render never drags the mean (a driver of the +-0.10 Part-A variance).
    Blank mid-rebuild captures (#75a) are excluded too (a transient env glitch, not a design
    score — mirrors _persist_verdict's _blocking_merged); a REAL capture failure (blank!=True)
    counts as its 0.0 (a canonical page that never rendered is a real miss, NOT silently dropped
    -- #542b). 0.0 over an empty blocking set. Does NOT change the pass/fail bar or any per-screen
    score — it only chooses WHICH screens the average is taken over."""
    def _sim(r: Mapping[str, Any]) -> float:
        try:
            return float(r.get("similarity") or 0.0)
        except Exception:
            return 0.0
    blk = [r for r in (results or [])
           if isinstance(r, dict) and not r.get("advisory") and r.get("blank") is not True]
    return round(sum(_sim(r) for r in blk) / len(blk), 4) if blk else 0.0


# Interaction-STATE name tokens — a reference so named is an overlay reachable only by
# a click/hover, never a URL route, so it can't be fairly scored by route-capture.
_OVERLAY_NAME_RE = re.compile(
    r"(?:^|_)(?:flyout|modal|popup|pop_?over|dropdown|drop_?down|overlay|dialog|"
    r"drawer|tooltip|toast|sheet|menu|context_?menu|lightbox)(?:_|$)")

# #542a: TRANSIENT interaction-STATE tokens a static route capture can NEVER reproduce — a
# hover popover, a preview card, an ad slot. These are DISTINCT from the structural overlay
# tokens above (menu/sheet can also legitimately NAME a real page — a restaurant menu, a
# bottom-sheet page — so they only mark advisory via the classification fallback, preserving
# #416/#132), whereas hover/preview/ad essentially NEVER name a navigable page, so a name
# match here is authoritative and marks the screen ADVISORY even over a kind='page' mislabel.
# Kept SEPARATE from _OVERLAY_NAME_RE so frontend_scaffold's route-owner ranking (which imports
# _OVERLAY_NAME_RE) is unaffected. Word-segment anchored (no 'ad' inside 'add'/'read'); no
# product literals.
# #588 — CONTENT-DOMINATED SCREENS. A full-bleed media surface (the player) is mostly VIDEO:
# holistic similarity against one captured frame scores the CONTENT, not the build. r142's
# reference happened to catch an AD state ("Ad 12", "All American begins after ads"), so the
# judge charged the implementation for missing an ad system nothing asked it to build — copy
# 0.50 was literally 'Ad 12' vs 'Disclosure Day', and even layout/components were compared
# against an ad chrome carrying FEWER controls than the implementation shipped.
#
# What the generator actually controls on such a screen is the CHROME, and the framework
# already defines it exactly: `_player_controls_jsx_449` emits a named control cluster. So the
# honest, content-free test is whether that cluster is PRESENT. Complete chrome -> the residual
# difference is content the app cannot reproduce -> advisory (the same mechanism #128/#542a
# already use), never a silent pass: ANY missing control keeps the screen blocking and the
# missing list is directly actionable.
#
# #589 — THE CHECKLIST HAS TO CUT BOTH WAYS. #588 only DEMOTED, so it could not see the worse
# half of the same defect: a screen ABOVE the bar was skipped before the chrome was ever
# examined. Measured over 31 runs with a player page, holistic similarity is not merely noisy
# there, it is INVERTED — all 26 complete players scored below all 3 passing shells:
#
#     chrome COMPLETE  n=26  mean 0.605  max 0.72   (every one of them BLOCKED)
#     chrome SHELL     r107 0.92 (7 of 8 controls missing)   <- PASSED
#                      r106 0.85 (5 missing)                 <- PASSED
#                      r138 0.80 (2 missing)                 <- PASSED
#
# The mechanism is visible in r107's own verdict: "Player chrome closely matches the reference"
# with fixes "group the flag icon and Ad counter into one dark rounded chip" — the reference is
# an AD frame, so a page that reproduces the AD chrome (Back/Report/Fullscreen and nothing else)
# outscores a working player. Similarity was rewarding the absence of the control cluster.
#
# Blocking cannot key on `missing != []` alone: every non-player page is "missing" all of them
# (that asymmetry is exactly why #588 was demotion-only). The applicability test has to be the
# framework's OWN — `_screen_is_player_449`, the same predicate that decided to EMIT the cluster
# for this screen. If the framework emitted the controls and the delivered page does not carry
# them, some later pass overwrote them (r142: a reprojected 118-line shell); that is a build
# regression and no similarity score should be able to buy it a pass. Recorded as a separate
# blocking reason so `_blocking_average` — reporting-only since #542a — stays untouched.
#595 — TWO OPEN DROPDOWNS IS NOT A STATE ANY APP CAN BE IN. #128/#542a demote a transient
# capture by the screen's NAME (`*_menu`, `*_dropdown`, `hover`, `preview`, `ad`). §5.0t already
# recorded the hole that leaves: on `player.jpg` the transient-ness was in the IMAGE, invisible
# to every name-based guard. `browse_by_languages` — mean 0.424, the WORST screen in the arc and
# a blocker in 27 of 40 scored runs — is the second independent instance, and a worse one: its
# reference was captured with the Original-Language dropdown open, the language list open
# (Arabic→Vietnamese, occluding the whole right column), AND a hover preview card floating over
# row 2. Three overlays at once.
#
# The measurement already says so, per region, machine-readably:
#     original-language-dropdown  state "open, showing options"
#     language-options-menu       state "expanded, long list visible"
#     title-preview-popover       role "hover/preview popover…"  state "open over row 2"
#
# The rule is physical, not aesthetic: opening a second dropdown CLOSES the first, so a frame
# holding two INDEPENDENT open overlays is not a state the implementation can ever be in. A
# dropdown and the list it opens are ONE interaction (adjacent boxes, merged), two different
# dropdowns are two. Measured over the 45 design systems, that separates cleanly:
#     browse_by_languages  1.78 mean, >=2 in 36/45  <- the target
#     account_menu 1.78 (36/45) / shows_genres_menu 1.16 (8/45)
#                                                   <- already advisory via _OVERLAY_NAME_RE
#     my_list 1.44 (21/45)                          <- per-run, and genuinely the same disease:
#         r100's frame carries "third tile hovered → expanded preview overlay", "like button
#         hovered with 'I like this' tooltip visible", and a `status-url-tooltip` that is the
#         BROWSER's own link-hover status bar — not app UI at all.
#     title_episodes 0.89 (3/45)
#     login, games, player, browse_home, movies, shows, landing, genre_category,
#     title_detail, card_preview, card_hover_preview, rate_dialog, player_controls  -> 0/45
#
# `title_detail` is the case a naive AREA threshold gets wrong: its modal occludes 0.504 of the
# frame, more than any other screen, but it is ONE overlay and it IS the subject. Counting
# clusters keeps it blocking (where #584 belongs); area would have excused it.
_OVERLAY_ROLE_RE = re.compile(
    r"dropdown|menu|popover|overlay|modal|tooltip|hover|preview|flyout|dialog", re.I)
_OVERLAY_OPEN_RE = re.compile(r"\bopen\b|expanded|hover|showing options", re.I)
# how close two overlay boxes may sit and still be ONE interaction (normalized frame units) —
# a dropdown and the list it opens share an edge, so pure intersection links nothing
_OVERLAY_GAP = 0.02


def _overlay_box(region: Any) -> Optional[tuple]:
    try:
        x0, y0, x1, y1 = [float(v) for v in (region or [])][:4]
    except Exception:
        return None
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def open_overlay_clusters(screen_design: Any) -> int:
    """#595 — how many INDEPENDENT overlays the reference frame was captured with open.

    A dropdown and the option list it owns overlap, so they count once; two different
    dropdowns do not, so they count twice. 0 when nothing was measured."""
    if not isinstance(screen_design, Mapping):
        return 0
    boxes: List[tuple] = []
    for reg in (screen_design.get("regions") or screen_design.get("components") or []):
        if not isinstance(reg, Mapping):
            continue
        if not _OVERLAY_ROLE_RE.search(f"{reg.get('role') or ''} {reg.get('id') or ''}"):
            continue
        if not _OVERLAY_OPEN_RE.search(str(reg.get("state") or "")):
            continue
        b = _overlay_box(reg.get("region"))
        if b:
            boxes.append(b)

    # A dropdown and the list it opens are ADJACENT, not overlapping — they share an edge and
    # their intersection area is exactly zero. So link by PROXIMITY (each box inflated by
    # _OVERLAY_GAP on every side, then intersected), and merge transitively: dropdown→list→
    # sub-list must collapse to one interaction, not a chain of three.
    n = len(boxes)
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        ax0, ay0, ax1, ay1 = boxes[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = boxes[j]
            if (min(ax1, bx1) + _OVERLAY_GAP >= max(ax0, bx0)
                    and min(ay1, by1) + _OVERLAY_GAP >= max(ay0, by0)):
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[ri] = rj
    return len({_find(i) for i in range(n)})


#601 — THE OTHER UNREPRODUCIBLE FRAME: AN AD WAS PLAYING WHEN THE REFERENCE WAS CAPTURED.
# #595 handles a frame caught mid-INTERACTION. This handles a frame caught mid-INTERSTITIAL, the
# case §5.0t found on `player.jpg` ("Ad 12", "All American begins after ads") and could then only
# answer with #588's bespoke chrome checklist plus a recommendation that a human swap the asset.
# Swapping an image does not generalize — the next product's capture will land on its own ad —
# so the rule has to come from the measurement, exactly as #595's does.
#
# An advertisement is a GENERIC UI concept (like a dropdown or a popover), not a product literal,
# and no generation task ever asks the app to build an ad system. So a reference whose measured
# STATE says an ad is playing is scoring the implementation against something it was never asked
# to produce.
#
# Three refinements, each forced by a false positive in the real corpus (2880 screens):
#   * read `state`, not `role`/`id` — `player_controls`'s role text literally says "No 'Ad NN'
#     chip", and a keyword match on role flagged it;
#   * skip a NEGATED mention, for the same reason;
#   * require a live-playback word within 34 chars — `landing` carries
#     "'The Netflix you love for just $8.99.' with subtitle about ad-supported plan" in its
#     state, which is marketing COPY the app SHOULD reproduce, not an ad on screen.
# With all three: 142 hits, every one `player`, and 2738 of 2880 screens untouched.
_AD_TOKEN_RE = re.compile(
    r"(?:^|[^a-z-])(ad|ads|advert|advertisement|interstitial|commercial|pre-?roll|mid-?roll)"
    r"(?:[^a-z-]|$)", re.I)
_AD_LIVE_RE = re.compile(
    r"\b(play|playing|plays|showing|shown|running|countdown|remaining|break|skip|left|active)\b",
    re.I)
_AD_NEGATED_RE = re.compile(r"\b(no|without|non|not|never|hidden|absent)\b[^.]{0,24}$", re.I)


def reference_shows_an_ad(screen_design: Any) -> bool:
    """#601 — was an advertisement ON SCREEN when this reference frame was captured?"""
    if not isinstance(screen_design, Mapping):
        return False
    for reg in (screen_design.get("regions") or screen_design.get("components") or []):
        if not isinstance(reg, Mapping):
            continue
        st = str(reg.get("state") or "")
        m = _AD_TOKEN_RE.search(st)
        if not m or _AD_NEGATED_RE.search(st[:m.start()]):
            continue
        if _AD_LIVE_RE.search(st[max(0, m.start() - 34):m.end() + 34]):
            return True
    return False


def screens_captured_showing_an_ad(project_dir: Any) -> Set[str]:
    """#601 — screen names whose reference frame was captured with an ad playing."""
    out: Set[str] = set()
    try:
        ds = json.loads((Path(project_dir) / "design" / "design_system.json")
                        .read_text(encoding="utf-8"))
    except Exception:
        return out
    for sc in ((ds or {}).get("screens") or []):
        if not isinstance(sc, Mapping):
            continue
        nm = str(sc.get("name") or sc.get("id") or "").strip()
        if nm and reference_shows_an_ad(sc):
            out.add(nm)
    return out


def screens_captured_mid_interaction(project_dir: Any) -> Dict[str, int]:
    """#595 — ``{screen_name: cluster_count}`` for screens whose reference frame holds TWO or
    more independent open overlays. Empty when there is no measured design to read."""
    out: Dict[str, int] = {}
    try:
        ds = json.loads((Path(project_dir) / "design" / "design_system.json")
                        .read_text(encoding="utf-8"))
    except Exception:
        return out
    for sc in ((ds or {}).get("screens") or []):
        if not isinstance(sc, Mapping):
            continue
        nm = str(sc.get("name") or sc.get("id") or "").strip()
        if not nm:
            continue
        n = open_overlay_clusters(sc)
        if n >= 2:
            out[nm] = n
    return out


def player_chrome_missing(frontend_dir: Any, component: Any) -> Optional[List[str]]:
    """Controls the framework's own player emitter defines that this page does NOT contain.

    ``None`` when the question does not apply (no vocabulary, no readable page source) — the
    caller then leaves the screen exactly as it was. ``[]`` means the chrome is complete."""
    try:
        from .frontend_scaffold import player_control_labels
        required = player_control_labels()
    except Exception:
        return None
    if not required:
        return None
    comp = str(component or "").replace(".jsx", "")
    if not comp:
        return None
    try:
        src = (Path(frontend_dir) / "src" / "pages" / f"{comp}.jsx").read_text(
            encoding="utf-8", errors="ignore")
    except Exception:
        return None
    return sorted(lbl for lbl in required if f'aria-label="{lbl}"' not in src)


_TRANSIENT_STATE_RE = re.compile(r"(?:^|_)(?:hover|preview|ad|ad_?state)(?:_|$)")

# #509 (netflix r84, 2026-08-05): MODAL/OVERLAY INTERACTION CAPTURE. #128 correctly marks
# overlay screens (rate_dialog, account_menu, card_hover_preview, *_dropdown …) ADVISORY
# because route-capture navigates to the PARENT page and never opens the overlay → the judge
# compares the bare page against the modal reference → floor score (r84 rate_dialog=0.12,
# card_hover=0.40). But advisory ≠ un-scorable: the reference_spec gives each overlay a
# `route_hint` (parent route, already the screen's `route`), so after navigating there we can
# DRIVE the interaction — click/hover the trigger — and screenshot the REAL overlay state for
# a FAIR score. Best-effort + fallback (on any miss the caller keeps the plain-route shot →
# never regresses / never worse than today). Generalizes to every app's overlays; no product
# literals (keywords derive from the screen NAME).
_OVERLAY_TOKEN_RE = re.compile(
    r"(?:_?(?:flyout|modal|popup|pop_?over|dropdown|drop_?down|overlay|dialog|drawer|"
    r"tooltip|toast|sheet|menu|context_?menu|lightbox|preview|hover|state|open|active))+$")
_OVERLAY_STOPWORDS = frozenset((
    "the", "and", "for", "with", "page", "screen", "view", "app", "user"))


def _overlay_trigger_keywords(name: str) -> List[str]:
    """Derive TRIGGER keywords from an overlay screen name (pure, testable). Strips the
    trailing interaction token(s) (``rate_dialog`` → ``rate``; ``account_menu`` → ``account``;
    ``card_hover_preview`` → ``card``) and returns the remaining >2-char tokens, plus generic
    menu/account synonyms so a bare avatar trigger is still found. Generalizes; no literals."""
    base = _OVERLAY_TOKEN_RE.sub("", str(name or "").lower()).strip("_")
    kws = [w for w in re.split(r"[_\s]+", base)
           if len(w) > 2 and w not in _OVERLAY_STOPWORDS]
    low = str(name or "").lower()
    if "menu" in low or "account" in low or "profile" in low or "dropdown" in low:
        kws += ["account", "profile", "avatar", "menu", "user"]
    return list(dict.fromkeys(kws))  # de-dup, order-preserving


def _overlay_is_hover(name: str) -> bool:
    """Hover-state overlays (card_hover_preview, *_hover) open on pointer-over, not click."""
    low = str(name or "").lower()
    return "hover" in low or "preview" in low


# JS: find a plausible trigger element (accessible-name / class match, else a nav avatar /
# aria-haspopup control) and click it (or dispatch hover events). Returns whether it fired.
_OVERLAY_OPEN_JS = r"""
([kws, isHover]) => {
  const norm = s => (s||'').toLowerCase();
  const acc = el => norm(el.innerText)+' '+norm(el.getAttribute&&el.getAttribute('aria-label'))
      +' '+norm(el.getAttribute&&el.getAttribute('title'))+' '+norm(el.getAttribute&&el.getAttribute('alt'))
      +' '+norm(el.className&&el.className.baseVal!==undefined?el.className.baseVal:el.className);
  const cand = Array.from(document.querySelectorAll('button,a,[role=button],[aria-haspopup],[onclick]'));
  let el = cand.find(e => { const t = acc(e); return kws.some(k => k && t.includes(k)); });
  if (!el) {
    el = document.querySelector('header [aria-haspopup], nav [aria-haspopup]');
    if (!el) { const img = document.querySelector('header img, nav img');
               if (img) el = img.closest('button,a') || img; }
  }
  if (!el) return false;
  try { el.scrollIntoView({block:'center'}); } catch(e) {}
  try {
    if (isHover) { ['pointerover','mouseover','mouseenter','pointerenter']
        .forEach(t => el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true}))); }
    else { el.click(); }
  } catch(e) { return false; }
  return true;
}
"""

# JS: did an overlay become visible? role=dialog / aria-modal, or a large fixed/absolute
# high-z element (a dropdown/menu/modal panel). Conservative size floor avoids scrims.
_OVERLAY_DETECT_JS = r"""
() => {
  if (document.querySelector('[role=dialog],[aria-modal="true"]')) return true;
  return Array.from(document.querySelectorAll('div,section,ul,nav,aside')).some(el => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return (s.position==='fixed'||s.position==='absolute') && (parseInt(s.zIndex)||0) >= 10
        && r.width >= 120 && r.height >= 70 && s.visibility!=='hidden' && s.display!=='none'
        && (parseFloat(s.opacity)||1) > 0.5;
  });
}
"""


async def _drive_overlay_open(page, name: str) -> bool:
    """#509: best-effort open an overlay/modal so the screenshot captures it, not the bare
    parent page. Returns True iff an overlay became visible. NEVER raises — any failure leaves
    the page on the plain parent route (caller's existing shot), so it can only ever help."""
    try:
        # #509-review (2026-08-05): a trigger click can NAVIGATE (the fallback in _OVERLAY_OPEN_JS
        # may click a header logo/avatar `<a href="/">`). Remember the capture route so that on a
        # MISS (no overlay opened) we restore it — otherwise the caller's unconditional screenshot
        # would capture the wrong route (home) and the screen would be judged against it → floor
        # score → FALSE-BLOCK an otherwise-good app. Guarantees the "a miss leaves the plain-route
        # shot / never regresses" invariant for real navigating triggers.
        try:
            _url_before = page.url
        except Exception:
            _url_before = None
        kws = _overlay_trigger_keywords(name)
        is_hover = _overlay_is_hover(name)
        fired = await page.evaluate(_OVERLAY_OPEN_JS, [kws, is_hover])
        if fired:
            await page.wait_for_timeout(800)
            if bool(await page.evaluate(_OVERLAY_DETECT_JS)):
                return True
        # miss (nothing fired, or fired but no overlay became visible) — undo any navigation.
        try:
            if _url_before and page.url != _url_before:
                await page.goto(_url_before, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(400)
        except Exception:
            pass
        return False
    except Exception:
        return False


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
            "reason": (f"{len(unjudged)} declared screen(s) were not judged in this round: "
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
            # #936: docker when present, podman otherwise — see _runtime_bin_936.
            [_runtime_bin_936(), "compose", "-f", str(compose_file), "up", "-d"],
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
        # #574 (netflix r138, live): the EMAIL came from the row but the PASSWORD was
        # hardcoded to the framework default, so any seed row carrying its OWN plaintext
        # password produced credentials that cannot log in. The loader's rule is
        # ``pw = row.pop('password', None) or 'password'`` (seed_data.py) — mirror it
        # EXACTLY, or the QA tooling authenticates as nobody.
        #
        # r138: seed_data.json's first user is ``demo@netflix.test`` / ``Demo!2345``; the DB
        # therefore holds sha256('Demo!2345'+salt) while the walk sent 'password' → 401. Both
        # the form drive (auth_ok) and #504's direct-API corroboration (api_login_ok) failed,
        # so the browser gate hard-deferred delivery 11 times over 54 minutes on an app whose
        # auth was fine — and, exactly as this function's docstring warns, the walk then
        # browsed as a non-populated user so every data page looked blank.
        if users and isinstance(users[0], dict) and users[0].get("email"):
            _pw = users[0].get("password")
            _pw = str(_pw) if _pw not in (None, "") else "password"  # backend_skeleton._SEED_PASSWORD
            return {"email": str(users[0]["email"]), "password": _pw,
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


# #418: a detail/param route (/title/:id, /browse/genre/:genreId, /watch/:titleId,
# /title/{id}/episodes) navigated with the LITERAL param renders the page's
# empty-state (the app fetches title ":id"/"{id}" → 404 → "not found"/blank), so
# the judge scores a data-less page ~0.00 no matter how good the layout/projection
# is (r13: genre_category 0.00, player 0.10 — the detail screens the projector
# builds hero+rails for). Substitute every :param / {param} segment with a real
# seeded id. "1" is safe + generalizable: Postgres serial PKs start at 1 and the
# seed loader always seeds ≥1 row for each seeded table, so id 1 exists for the
# primary entity of every detail route (the SAME id-1-is-seeded assumption the
# chain-executor's required-FK repair already relies on, #411). A no-op for
# param-less routes → non-detail screens are unaffected.
_ROUTE_PARAM_RE = re.compile(r":[A-Za-z_]\w*|\{[^}/]+\}")


def _concrete_capture_route(route: str) -> str:
    """Fill param segments of an app route with a real seeded id so the captured
    page loads CONTENT, not its empty-state (#418). ``/title/:id`` → ``/title/1``,
    ``/browse/genre/:genreId`` → ``/browse/genre/1``. Param-less routes unchanged."""
    if not route:
        return route
    return _ROUTE_PARAM_RE.sub("1", route)


# ---------------------------------------------------------------------------
# #565 (netflix r111) — NON-FINAL MILESTONE advisory-judge SCOPING.
# On an intermediate milestone the advisory visual judge scored the WHOLE reference
# set (all screens across every milestone) and filed frontend remediation for pages a
# LATER milestone owns — so M1 churned the frontend for ~1h on M2/M3's movies/my_list.
# These helpers let VisualFidelityGate.maybe_run pass THIS milestone's OWNED routes so
# non-owned screens are demoted to advisory (still captured/reported, but out of the
# blocking pass/average/failing/remediation). Final/single-milestone passes None → the
# full set → byte-identical.
# ---------------------------------------------------------------------------
def _norm_route_for_scope(route: Any) -> str:
    """Normalize a route for milestone-scope comparison: drop query/fragment, lowercase,
    ensure a single leading slash, strip a trailing slash, and collapse param segments
    (``:id`` / ``{id}``) to ``*`` so ``/title/:id`` compares equal to ``/title/1``.
    Returns '' for an empty/None route."""
    s = str(route or "").split("?", 1)[0].split("#", 1)[0].strip().lower()
    if not s:
        return ""
    if not s.startswith("/"):
        s = "/" + s
    s = re.sub(r"[:{][^/}]*\}?", "*", s)   # :id / {id} -> * (param-insensitive compare)
    s = re.sub(r"^/\d+$|(?<=/)\d+(?=/|$)", "*", s)  # numeric id segments -> *
    if len(s) > 1:
        s = s.rstrip("/")
    return s or "/"


def _route_resource_token(norm_route: str) -> str:
    """Last non-param ('*'), non-empty segment of a normalized route ('' for '/')."""
    segs = [seg for seg in str(norm_route or "").split("/") if seg and seg != "*"]
    return segs[-1] if segs else ""


def _route_in_scope(screen_route: Any, owned_norm: set) -> bool:
    """INCLUSIVE ownership test, biased to KEEP a screen blocking (under-scoping is the
    safe direction — it degrades toward today's full-set behavior, never hides an owned
    page): a screen is owned iff its normalized route equals an owned route OR shares its
    last resource token with one. An empty route (or a token-less '/' absent from the
    owned set) is never owned."""
    sr = _norm_route_for_scope(screen_route)
    if not sr:
        return False
    if sr in owned_norm:
        return True
    tok = _route_resource_token(sr)
    if not tok:
        return False
    return any(_route_resource_token(o) == tok for o in owned_norm)


def _milestone_declared_routes(milestone: Mapping[str, Any]) -> set:
    """#565: the NORMALIZED frontend routes a milestone declares it OWNS.

    SURPRISE (verified 2026-08-07): a milestone registry record
    (``milestone_registry._norm``) carries NO structural screen/page/route list — only
    prose (``description_slice`` + kickoff-authored ``detail`` + ``acceptance``), and no
    registered ui_page carries a milestone tag. So the owned routes are EXTRACTED from
    that prose: HTTP-method-prefixed paths (``GET /movies``), bare ``/path`` tokens, and
    — since a page route commonly mirrors its resource endpoint — the ``/api``-stripped
    variant of any ``/api/<rest>`` path.

    Returns a NORMALIZED set (via ``_norm_route_for_scope``); the extraction is
    deliberately GENEROUS because an over-large owned set only UNDER-scopes (keeps more
    screens blocking = safe), whereas a too-small one could hide an owned page. Returns an
    EMPTY set when nothing parseable is found, so the caller falls back to NO scoping (the
    full set) rather than hiding everything on a prose miss."""
    if not isinstance(milestone, Mapping):
        return set()
    parts: List[str] = []
    for k in ("description_slice", "detail"):
        v = milestone.get(k)
        if v:
            parts.append(str(v))
    for a in (milestone.get("acceptance") or []):
        parts.append(str(a))
    text = "\n".join(parts)
    if not text.strip():
        return set()
    raw: set = set()
    for m in re.findall(r"(?:GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./:{}\-]+)", text):
        raw.add(m)
    for m in re.findall(r"(?<![\w/])/[A-Za-z0-9_][A-Za-z0-9_./:{}\-]*", text):
        raw.add(m)
    out: set = set()
    for r in raw:
        nr = _norm_route_for_scope(r)
        if not nr:
            continue
        out.add(nr)
        if nr.startswith("/api/"):
            stripped = _norm_route_for_scope("/" + nr[len("/api/"):])
            if stripped:
                out.add(stripped)
    out.discard("")
    return out


# ---------------------------------------------------------------------------
# #491 (netflix r63, confirmed) — POST-LOGIN PROFILE/SELECTION GATE.
# App.jsx routes catalog pages as ``<RequireProfile><XxxPage/></RequireProfile>``;
# RequireProfile redirects to ``/profiles`` when ``getActiveProfileId()`` (=
# ``localStorage.getItem('active_profile_id')``) is empty. The capture logs in
# (sets a token) but NEVER selects a profile → every catalog route bounces to the
# profiles chooser → all catalog screenshots are IDENTICAL (the profiles list) →
# fidelity collapses (~0.06-0.12) instead of scoring the real pages.
#
# Mirror the token block (FIX #103): the profile-selection storage KEY is pure
# lane variance ('active_profile_id' vs camelCase vs 'profile' …), so once we know
# an id we establish it under EVERY common alias in BOTH localStorage AND
# sessionStorage. Best-effort everywhere — apps with no profile gate are
# unaffected (the extra keys are inert to the app).
# ---------------------------------------------------------------------------
_PROFILE_KEY_ALIASES = (
    "active_profile_id", "activeProfileId", "profile_id", "profileId",
    "selected_profile_id", "selectedProfileId", "current_profile_id",
    "currentProfileId", "activeProfile", "selectedProfile", "profile",
)

# Discover the first profile id via the app's OWN origin/session (most robust —
# same fetch the app itself makes). Tries the common list endpoints in order,
# unwraps the common envelopes, reads the first present id field. Returns null on
# any miss so the caller silently proceeds. ``token`` is passed in (may be "").
_PROFILE_DISCOVER_JS = """async (token) => {
  const paths = ['/api/profiles', '/api/profile', '/profiles'];
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  for (const p of paths) {
    try {
      const r = await fetch(p, { headers });
      if (!r.ok) continue;
      const d = await r.json();
      let arr = null;
      if (Array.isArray(d)) arr = d;
      else if (d && Array.isArray(d.profiles)) arr = d.profiles;
      else if (d && Array.isArray(d.items)) arr = d.items;
      else if (d && Array.isArray(d.data)) arr = d.data;
      if (!arr || !arr.length) continue;
      const row = arr[0];
      if (!row || typeof row !== 'object') continue;
      for (const k of ['id', 'profile_id', 'profileId', '_id', 'uuid']) {
        if (row[k] !== undefined && row[k] !== null && row[k] !== '') {
          return String(row[k]);
        }
      }
    } catch (e) {}
  }
  return null;
}"""


def _profile_select_init_js(profile_id: str) -> str:
    """A JS init-script that establishes ``profile_id`` as the ACTIVE profile
    under every alias in ``_PROFILE_KEY_ALIASES`` in BOTH localStorage and
    sessionStorage — the mirror of the token block (FIX #103), because the app's
    profile-selection storage KEY is pure lane variance. Returns "" for a falsy
    id (no gate to satisfy). The value is JSON-encoded so it is always a valid JS
    string literal (no unbalanced quotes for any id)."""
    if not profile_id:
        return ""
    _pid_js = json.dumps(str(profile_id))
    return ";".join(
        f"localStorage.setItem('{k}', {_pid_js});"
        f"sessionStorage.setItem('{k}', {_pid_js})"
        for k in _PROFILE_KEY_ALIASES) + ";"


# ---------------------------------------------------------------------------
# #548 (netflix, r103) — CAPTURE STABILITY across a MID-RUN DB RE-SEED.
# ROOT of the Part-A run-to-run variance: the app's DB is periodically re-seeded
# DURING a run, which momentarily WIPES the ``profiles`` table. The frontend gates
# every protected route on a selected profile (``needProfile`` → renders the
# "Who's watching?" picker when none is selected/persisted OR when the persisted
# id no longer resolves to a live profile). So a screenshot taken while a re-seed
# is in flight captures the tiny profile-picker instead of the real page, and the
# judge scores that real screen ~0.05 — with NO code change (r103: browse_home
# 0.78→0.06 in 13 min). The pre-existing FIX #491 selects a profile ONCE at boot,
# which is defeated by a re-seed that lands mid-capture.
#
# Three additive, structural, best-effort mechanisms (all no-ops for an app with no
# profile gate → byte-identical for such apps):
#   (b) SEED-SETTLED wait: before capturing, poll the app's own /profiles endpoint
#       until it is NON-EMPTY and STABLE (same count twice) so discovery/capture
#       never starts mid-wipe.
#   (a)+(c) INVALID-CAPTURE detect + RE-SELECT + retry: right before each protected
#       screen's shot, probe the loaded DOM; if it is the profile picker (a
#       who's-watching heading, or a /profiles chooser grid) — i.e. a re-seed
#       re-raised the gate — RE-SELECT a profile (re-discover a now-valid id +
#       re-persist under every alias + click the picker's first tile, which makes
#       the app persist under its OWN key) and re-navigate, up to a small bound.
#       A picker never scores a real screen.
# The profiles screen ITSELF (a legitimate reference) is exempt (its picker capture
# is correct). Purely structural signals; no product literals.
# ---------------------------------------------------------------------------

# JS probe: structural signals of a profile-SELECTION gate on the loaded page.
# ``whos`` keys on a HEADING (not arbitrary body copy) matching the universal
# who's-watching prompt; ``profilesRoute`` = the capture bounced to a /profiles
# collection; ``avatars`` counts square selection tiles (excluding an add/new
# affordance). Read-only — never mutates the page.
_PROFILE_PICKER_PROBE = r"""() => {
  const RE = /who[’'`]?s?\s+watch/i;
  const heads = Array.from(document.querySelectorAll('h1,h2,h3,[role=heading]'));
  const whos = heads.some(h => RE.test((h.innerText || '')));
  const path = (location.pathname || '').replace(/\/+$/, '').toLowerCase();
  const profilesRoute = /\/profiles$/.test(path);
  const els = Array.from(document.querySelectorAll('button,a,[role=button],li'));
  let avatars = 0, hasAdd = false;
  for (const el of els) {
    const lab = (((el.getAttribute && el.getAttribute('aria-label')) || '') + ' '
                 + (el.innerText || '')).toLowerCase();
    if (/\b(add|new|create|manage|edit)\b|(^|\s)\+(\s|$)/.test(lab)) { hasAdd = true; continue; }
    const r = el.getBoundingClientRect();
    if (r.width >= 48 && r.height >= 48
        && Math.abs(r.width - r.height) <= Math.max(r.width, r.height) * 0.6) avatars++;
  }
  return { whos: whos, profilesRoute: profilesRoute, avatars: avatars, hasAdd: hasAdd };
}"""

# JS: click the first profile TILE of an on-screen picker (skipping an add/new tile).
# The app's own onClick persists the active profile under its OWN key and navigates
# on — the most robust selection path (defeats storage-key lane variance AND a
# server-validated gate). Returns whether a tile was clicked.
_PROFILE_PICKER_CLICK_JS = r"""() => {
  const els = Array.from(document.querySelectorAll('button,a,[role=button]'));
  const isAdd = el => {
    const s = (((el.getAttribute && el.getAttribute('aria-label')) || '') + ' '
               + (el.innerText || '')).toLowerCase();
    return /\b(add|new|create|manage|edit)\b|(^|\s)\+(\s|$)/.test(s);
  };
  const tiles = els.filter(el => {
    if (isAdd(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 48 && r.height >= 48;
  });
  const el = tiles[0] || els.find(e => !isAdd(e));
  if (!el) return false;
  try { el.scrollIntoView({ block: 'center' }); el.click(); } catch (e) { return false; }
  return true;
}"""

# JS: the size of the app's own profiles collection (for the seed-settled wait).
# Returns -1 when NO profiles endpoint exists → no gate → nothing to wait for.
_PROFILE_COUNT_JS = r"""async (token) => {
  const paths = ['/api/profiles', '/api/profile', '/profiles'];
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  for (const p of paths) {
    try {
      const r = await fetch(p, { headers });
      if (!r.ok) continue;
      const d = await r.json();
      let arr = null;
      if (Array.isArray(d)) arr = d;
      else if (d && Array.isArray(d.profiles)) arr = d.profiles;
      else if (d && Array.isArray(d.items)) arr = d.items;
      else if (d && Array.isArray(d.data)) arr = d.data;
      if (arr) return arr.length;
    } catch (e) {}
  }
  return -1;
}"""

# how many times a still-picker capture is re-selected+re-navigated before we skip
# the shot (rather than feed the judge a picker as a real screen). Small: a genuine
# re-seed settles fast; a persistent picker is a real app defect (correctly unjudged).
_PROFILE_RESELECT_MAX = int(os.environ.get("ENVGEN_VISUAL_PROFILE_RESELECT_MAX", "2") or 2)
_SEED_SETTLE_POLLS = int(os.environ.get("ENVGEN_VISUAL_SEED_SETTLE_POLLS", "6") or 6)
_SEED_SETTLE_INTERVAL_MS = int(os.environ.get("ENVGEN_VISUAL_SEED_SETTLE_MS", "800") or 800)

# who's-watching / plural "profiles" collection — the screen's OWN identity. Plain
# "profiles" (plural) as a substring so underscore forms ('select_profiles') match
# too; singular "profile" (an account page, not a chooser) deliberately does NOT.
_PROFILE_SCREEN_NAME_RE = re.compile(
    r"who[’'`]?s?\s*[-_ ]*watch|profiles|profile[_\s-]*(?:picker|select|chooser)",
    re.I)


def _is_profile_picker_capture(probe: Optional[Mapping[str, Any]]) -> bool:
    """(#548, pure) Decide from a ``_PROFILE_PICKER_PROBE`` result whether the
    captured page is a profile-SELECTION gate ("Who's watching?"), not the real
    screen. True iff:
      * a who…watching HEADING is present (the universal picker prompt), OR
      * the capture bounced to a /profiles collection route AND shows an avatar
        selection grid (>=2 same-shape tiles).
    CONSERVATIVE by design: a real content page (no such heading, not bounced to a
    /profiles chooser) is NEVER flagged, so an app with NO profile gate triggers no
    re-select/retry and its capture is byte-identical."""
    if not isinstance(probe, Mapping):
        return False
    if probe.get("whos"):
        return True
    if probe.get("profilesRoute") and int(probe.get("avatars") or 0) >= 2:
        return True
    return False


def _screen_is_profile_screen(screen: Mapping[str, Any]) -> bool:
    """(#548, pure) Is THIS screen itself the profile-picker ('who's watching' /
    plural /profiles collection) — so a picker capture is the CORRECT capture and
    must NOT be flagged invalid? Keyed on the screen's own name/route naming a
    profile COLLECTION picker. A singular ``/profile`` account page (not a chooser)
    is deliberately NOT matched, so its gate-bounce is still re-selected."""
    if not isinstance(screen, Mapping):
        return False
    name = str(screen.get("name") or "")
    route = str(screen.get("route") or "").rstrip("/").lower()
    if route.endswith("/profiles"):
        return True
    return bool(_PROFILE_SCREEN_NAME_RE.search(name))


async def _wait_seed_settled(page, token: Optional[str]) -> None:
    """(#548b) Best-effort: block until the app's profiles collection is NON-EMPTY
    and STABLE (same count on two consecutive polls) so a capture never starts DURING
    a mid-run re-seed that momentarily wiped the table. Returns immediately when there
    is NO profiles endpoint (count -1 → no gate → byte-identical for such apps) or when
    the poll budget is spent. Never raises."""
    _prev: Optional[int] = None
    for _ in range(max(1, _SEED_SETTLE_POLLS)):
        try:
            _n = await page.evaluate(_PROFILE_COUNT_JS, token or "")
        except Exception:
            return
        try:
            _n = int(_n)
        except Exception:
            return
        if _n < 0:
            return  # no profiles endpoint → no gate to settle
        if _n > 0 and _prev is not None and _n == _prev:
            return  # non-empty and stable
        _prev = _n
        try:
            await page.wait_for_timeout(_SEED_SETTLE_INTERVAL_MS)
        except Exception:
            return


async def _ensure_profile_selected(page, ctx, token: Optional[str]) -> bool:
    """(#548a) (Re-)establish an ACTIVE profile so protected routes render real
    content, robust to a mid-run re-seed that invalidated a previously-persisted id.
    Belt-and-suspenders (each step best-effort; never raises):
      1) RE-DISCOVER the first profile id from the app's own /profiles endpoint (a
         re-seed yields a fresh valid id) and persist it under EVERY alias — via an
         init-script (future page loads) AND on the CURRENT page (immediate);
      2) if a picker is on-screen, CLICK its first tile — the app's own handler
         persists under the app's OWN key, defeating storage-key lane variance and
         satisfying a server-validated gate.
    Returns True iff a profile was (re-)selected by either path."""
    ok = False
    try:
        _pid = await page.evaluate(_PROFILE_DISCOVER_JS, token or "")
    except Exception:
        _pid = None
    _js = _profile_select_init_js(_pid) if _pid else ""
    if _js:
        try:
            await ctx.add_init_script(_js)          # all future page loads
        except Exception:
            pass
        try:
            await page.evaluate("() => { " + _js + " }")  # the current page, immediately
            ok = True
        except Exception:
            pass
    try:
        if await page.evaluate(_PROFILE_PICKER_CLICK_JS):
            await page.wait_for_timeout(600)
            ok = True
    except Exception:
        pass
    return ok


async def capture_route_screenshots(
    base_url: str,
    screens: List[Dict[str, Any]],
    token: Optional[str],
    out_dir: Path,
    auth_redirected: Optional[List[str]] = None,
    blank_screens: Optional[List[str]] = None,
    picker_screens: Optional[List[str]] = None,   # #657
    console_errors: Optional[Dict[str, List[str]]] = None,   # #740
    capture_errors: Optional[Dict[str, str]] = None,         # #935

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
            # #740: KEEP THE UNCAUGHT ERROR. The capture drives a real browser to every
            # declared route, every remediation round, and threw away the single most
            # diagnostic signal on the page — there is no `page.on("console")` or
            # `"pageerror"` anywhere in this module. So a crashed SPA could only ever be
            # described by its SYMPTOM: "route X rendered BLANK — the SPA never hydrated".
            #
            # r148 is what that costs. Its frontend threw `TypeError: (void 0) is not a
            # function` on every authenticated route; the capture saw ten blank shells, the
            # remediation task said "fix the page's mount/data load, not its styling", and the
            # error itself reached the lane only because the VERIFIER separately drove a
            # browser and read the console. Corpus: 14 runs carry a frontend runtime-crash
            # signature in their task store and **all 14 released**, 9 of them with the crash
            # task still open.
            #
            # Collected per screen, bounded (5 distinct messages each, 300 chars) so a page
            # looping an error cannot flood the verdict. Console `error` level and uncaught
            # exceptions only — warnings and logs are noise here. Purely additive: nothing
            # reads this yet except the blank deviation text, and a screen with no errors is
            # byte-identical to before.
            _cur740 = {"name": "(startup)"}

            def _rec740(kind: str, text: Any) -> None:
                if console_errors is None:
                    return
                try:
                    _b = console_errors.setdefault(_cur740["name"], [])
                    _m = f"{kind}: {str(text)[:300]}"
                    if _m not in _b and len(_b) < 5:
                        _b.append(_m)
                except Exception:
                    pass

            if console_errors is not None:
                page.on("pageerror", lambda e: _rec740("uncaught", e))
                page.on("console", lambda m: (
                    _rec740("console.error", m.text) if m.type == "error" else None))
            # #491 (netflix r63) — POST-LOGIN PROFILE GATE. A token alone does not
            # pass <RequireProfile>: catalog routes redirect to /profiles until an
            # ACTIVE profile is selected, collapsing every catalog shot to the
            # identical profiles chooser (fidelity ~0.06-0.12). Mirror FIX #103's
            # token approach: discover the first profile id via the app's OWN
            # origin/session, then establish it under every alias in both storages
            # (ctx.add_init_script) so ALL subsequent page loads pass the gate.
            # Best-effort — ANY failure (no such endpoint, network, parse) silently
            # proceeds exactly as before; apps without a profile gate are unaffected.
            # #548b: FIRST wait for the seed to SETTLE — the DB is periodically
            # re-seeded mid-run, momentarily wiping the profiles table; discovering
            # (and later capturing) mid-wipe reads an EMPTY collection → the profile
            # gate never gets a valid id → every protected shot is the picker. The
            # wait is a no-op for an app with no /profiles endpoint (byte-identical).
            try:
                await page.goto(base_url, wait_until="domcontentloaded",
                                timeout=20000)
                await _wait_seed_settled(page, token)
                _pid = await page.evaluate(_PROFILE_DISCOVER_JS, token or "")
                _profile_js = _profile_select_init_js(_pid) if _pid else ""
                if _profile_js:
                    await ctx.add_init_script(_profile_js)
            except Exception:
                pass  # no profile gate / discovery failed → proceed as before
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
                    _cur740["name"] = str(screen["name"])   # #740: attribute to THIS screen
                    await page.goto(base_url + _concrete_capture_route(screen["route"]),
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
                    # #548a/c: PROFILE-GATE re-assert. A mid-run re-seed can re-raise
                    # the "Who's watching?" gate over a PROTECTED route even though a
                    # profile was selected at boot — the capture would then score a real
                    # screen ~0.05 (the picker), the root of the Part-A variance. If the
                    # loaded DOM IS the picker, RE-SELECT a (now-valid) profile and
                    # re-navigate, up to a small bound; a picker never scores a real
                    # screen. The profiles screen itself is exempt (its picker capture is
                    # correct). No-op for an app with no profile gate → byte-identical.
                    if not _screen_is_profile_screen(screen):
                        _still_picker = False
                        for _attempt in range(_PROFILE_RESELECT_MAX + 1):
                            try:
                                _pk = await page.evaluate(_PROFILE_PICKER_PROBE)
                            except Exception:
                                _pk = None
                            _still_picker = _is_profile_picker_capture(_pk)
                            if not _still_picker or _attempt >= _PROFILE_RESELECT_MAX:
                                break
                            await _ensure_profile_selected(page, ctx, token)
                            try:
                                await page.goto(
                                    base_url + _concrete_capture_route(screen["route"]),
                                    wait_until="networkidle", timeout=20000)
                                await page.wait_for_timeout(1200)
                            except Exception:
                                break
                        if _still_picker:
                            # exhausted retries — do NOT feed a picker to the judge as a
                            # real screen (a false ~0.05). Skip the shot (reported blank).
                            # #657: record WHICH cause this was. Both this branch and the
                            # un-hydrated-shell branch below feed `blank_screens`, and the
                            # deviation built from it names only the shell — so a screen the
                            # capture could not get past the profile picker was reported as
                            # "the SPA never hydrated", sending the lane to fix a mount/data
                            # load that works fine.
                            if picker_screens is not None:
                                picker_screens.append(screen["name"])
                            if blank_screens is not None:
                                blank_screens.append(screen["name"])
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
                    # #509: for an OVERLAY/modal screen the parent route is now loaded but the
                    # overlay is closed — DRIVE the interaction (click/hover its trigger) so the
                    # screenshot captures the real overlay state, not the bare page (r84
                    # rate_dialog=0.12/card_hover=0.40 were bare-page vs modal-reference).
                    # best-effort — a miss leaves the plain parent shot (never regresses).
                    # #509-review (2026-08-05): drive ONLY for ADVISORY screens — advisory IS the
                    # authoritative #128 overlay classification. The old `_OVERLAY_NAME_RE OR ...`
                    # branch also fired on BLOCKING routed pages whose name coincidentally holds an
                    # overlay token (`menu`, `sheet` — e.g. a restaurant 'menu' PAGE): driving a
                    # trigger there could open a dropdown / navigate over a page that must be judged
                    # as-is → floor score → false-block. A blocking page is always judged plain.
                    if screen.get("advisory"):
                        try:
                            if await _drive_overlay_open(page, screen["name"]):
                                await page.wait_for_timeout(300)  # let the overlay settle
                        except Exception:
                            pass  # keep the plain-route shot
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
                except Exception as _cap769:
                    # #769: SAY WHY THE CAPTURE FAILED. This was a bare `continue`, so a screen
                    # that could not be photographed left NO trace — and downstream it becomes a
                    # hard 0.00 that counts against the gate (#542's invariant, deliberately).
                    #
                    # r150 is what that costs. Its final round captured 3 of 12 screens and
                    # scored NINE zeros; the zeros track missing captures exactly, round by
                    # round (4 shots -> 0 zeros; 0 shots -> 7 zeros). The app was fine — its
                    # captures from earlier rounds are a complete Netflix clone. So the gate
                    # reported 0.1727 about the HARNESS and nothing anywhere said so.
                    #
                    # Same shape as #748 one layer up: the reason existed, was caught, and was
                    # discarded at the `except`. Bounded by construction — at most one line per
                    # screen per pass, and the exception type is the useful half (a navigation
                    # timeout, a closed page and a proxy refusal are three different problems).
                    _LOG.warning(
                        "#769 capture FAILED for screen '%s' (%s): %s: %s. No screenshot, so "
                        "this screen scores 0.00 downstream — that zero is about the capture, "
                        "not the page.",
                        screen.get("name"), screen.get("route"),
                        type(_cap769).__name__, str(_cap769)[:200])
                    # #935: and OUT of the logger. #769 rescued the reason from the bare `except`
                    # and put it in a log line; r154's run directory contains no `#769` line
                    # anywhere, because nothing in the run persists this logger. So the reason
                    # existed, was caught, was written — and was still unavailable to anyone
                    # holding only the run's artifacts.
                    #
                    # r154 is what that costs. `title_detail` was photographed ONCE, at 17:19:57
                    # (`history/` holds exactly one entry for it against 118 in total), and scored
                    # 0.00 in every round after. I diagnosed that as judge noise, wrote it into two
                    # tickets, and only found the truth by listing mtimes. This dict is the fourth
                    # out-parameter's shape (#657, #740) and reaches the ledger via #933.
                    if capture_errors is not None:
                        capture_errors[str(screen.get("name"))] = (
                            f"{type(_cap769).__name__}: {str(_cap769)[:200]}")
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
    "counts) and empty states caused by missing data — judge the DESIGN.\n"
    # #781: SCORE THE IMAGE, NOT THE PRODUCT. `player` fails the bar in 46% of runs and the
    # complaint is always the same chrome: `scrub` appears in 39 of 40 judged records, alongside
    # "missing skip-back and skip-forward buttons", "missing next-episode and CC/subtitles
    # icons". Its reference shows an AD playing — back arrow, flag, "Ad 12", pause, volume,
    # "All American begins after ads", fullscreen — and a Netflix ad view HAS no scrubber, no
    # skip, no CC, no next-episode. The framework's own decomposition finds exactly those 8
    # components and no more, in 53 of 53 runs, so the decomposition is right and the judge is
    # scoring against its prior of what a Netflix player looks like.
    #
    # "Weigh component completeness most heavily" invites precisely that, because completeness
    # was never defined. It is defined here.
    "COMPLETENESS IS DEFINED BY THE REFERENCE IMAGE, NOT BY THE PRODUCT. A control the "
    "reference does not show is NOT missing — even when the real product has it, and even when "
    "the screen is instantly recognisable. If the reference is a partial or transient state (an "
    "ad playing, a modal open, a loading view), score the implementation against THAT state. "
    "Never list under `missing` an element you cannot point to in the first image.\n\n"
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
    # #857: #781 restrained `missing` and stopped there, so the same over-claim simply moved to
    # `deviations` — which is the field `remediation_text` turns into the lane's concrete to-do
    # list (see #855). Measured: #652's rail position indicator is emitted (gate fires 7/7) and
    # its markup is verifiably PRESENT in the delivered source of all 7 post-#652 runs, yet 5 of
    # those 7 still carry a "pagination dots missing" deviation. The rate did not move: 74%
    # before the fix, 71% after. A shipped fix whose metric does not move is not always a broken
    # fix — here the instrument was reporting a component it could point to in neither image.
    '  "deviations": ["<WHERE on the screen + WHAT differs, ordered by impact. ANCHOR EVERY '
    'ENTRY IN THE IMAGES: for \'X is missing\' you must be able to point to X in the FIRST '
    'image, and for \'X is wrong/extra\' you must be able to point to X in the SECOND. If you '
    'cannot point to it in either, it is not a deviation — do not infer it from what the real '
    'product usually has. e.g. \'header: implementation centers the logo; reference '
    'left-aligns it next to search\'>", ...],\n'
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
        # #466: a parse failure is a TRANSIENT judge glitch, NOT real 0.0 fidelity —
        # flag judge_error so it is never CACHED as truth (line ~1215) and is re-judged
        # next milestone (with the #466 larger token budget, the retry now succeeds).
        return {"similarity": 0.0, "dimensions": {}, "deviations": ["judge returned no JSON"],
                "summary": str(text)[:200], "judge_error": True,
                "raw_judge_reply": str(text)[:400]}   # #767: same key on every zero path
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"similarity": 0.0, "dimensions": {}, "deviations": ["judge JSON unparseable"],
                "summary": m.group(0)[:200], "judge_error": True,
                "raw_judge_reply": str(text)[:400]}   # #767: same key on every zero path
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
    _empty766 = False
    if sim is None:
        # model omitted the overall judgment — average its dimension scores
        scores = [r["score"] for r in dims.values()]
        sim = round(sum(scores) / len(scores), 3) if scores else 0.0
        # #766: PARSED, BUT EMPTY — A NON-VERDICT, NOT A ZERO. The two sibling paths above
        # (no JSON at all; JSON that will not parse) both set `judge_error`, precisely so #142
        # never caches them and #75a/#466 can treat them as transient. This third shape was
        # missed: valid JSON carrying NEITHER `similarity` NOR a usable `dimensions` block
        # yields 0.0 with no flag, and is then indistinguishable from an honest "this page looks
        # nothing like the reference".
        #
        # A 0.0 the framework believes is expensive. It drags the blocking average, it counts as
        # a real judgment for #138's plateau, and #500's high-water merge then hides it from the
        # persisted record — so nobody reading verdict.json afterwards can even see it happened.
        #
        # NOT claimed as r150's cause. r150 shipped v1.0.0 with 9 of 12 screens at 0.00 on its
        # final round while the gating average sat at 0.6778, and the zeros oscillate across
        # rounds (7 -> 4 -> 6 -> 9) on 1.4MB content-rich captures with no judge error logged —
        # which points at the measurement rather than the app, but the raw judge responses are
        # not kept, so this hole is a defect found while investigating, not a proven diagnosis.
        if not scores:
            _empty766 = True
    # #767: KEEP THE RAW REPLY FOR A ZERO. r150 released with eight screens at 0.00 whose
    # captures are 1.4MB of correctly rendered page — I opened the PNGs and browse_home is a
    # complete Netflix clone (wordmark, full nav, hero with a seeded title, three poster rails).
    # So the zeros are a MEASUREMENT failure, and the question "did the judge actually say 0.0,
    # or did it return an empty JSON that #766 now flags" could not be answered, because the
    # reply is parsed and discarded.
    #
    # A zero is the one score worth keeping the evidence for: it is the only value that can be
    # produced by a NON-answer, it is rare enough that the cost is nothing, and #500's merge
    # will erase it from the persisted record within a round or two. Truncated hard — this is a
    # diagnostic crumb, not a transcript.
    def _stamp767(v: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if float(v.get("similarity") or 0.0) == 0.0:
                v["raw_judge_reply"] = str(text)[:400]
        except Exception:
            pass
        return v

    if _empty766:
        return _stamp767({"similarity": 0.0, "dimensions": {},
                "deviations": ["judge returned JSON with no similarity and no dimensions — "
                               "a NON-VERDICT, not a 0.0 (#766)"],
                "summary": str(text)[:200], "judge_error": True})
    devs = [str(x)[:300] for x in (data.get("deviations") or []) if str(x).strip()][:10]
    fixes = [str(x)[:300] for x in (data.get("fixes") or []) if str(x).strip()][:10]
    # #767: stamped HERE too, and this is the half that matters most. A reply of
    # `{"similarity": 0.0}` about a page that renders correctly is the case #766 cannot explain
    # and the one r150 needs answered — was it a considered verdict with reasons, or a hollow
    # one? Only the raw text can say, and one round from now it will be gone.
    return _stamp767({"similarity": sim, "dimensions": dims, "deviations": devs,
            "fixes": fixes, "summary": str(data.get("summary", ""))[:300],
            # FIX #133: the judge's empty-state observation becomes REPORTABLE (it was
            # told to ignore data-empty states — now it also flags them so the framework
            # can remind the BACKEND lane to seed the missing rows).
            "empty_state": bool(data.get("empty_state"))})


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
        # #466: 3000 tok TRUNCATED the 7-dimension rubric JSON on complex screens
        # (r45 shows=0.00 = 'judge JSON unparseable' — a 1.5MB rendered screen falsely
        # scored 0.0 and dragged the mean). The rubric (7 dims × score+notes+fix +
        # deviations + fixes + summary) needs >3000 tok for a busy screen → give it
        # ample headroom so the JSON never truncates. temp=0 + JSON-only instruction
        # means it emits only what the verdict needs, capped here. Generalizable
        # (every judge call, every app) — measurement integrity.
        # #872: bound the judge call. Same family as #870/#871, on the biggest population.
        #
        # `utils.llm` caps one completion at 240s (FIX #187) and its retry layer re-rolls with no
        # cap on the count, so a single screen is 240s x N. This runs ONCE PER SCREEN — ~12 per
        # round — and the visual gate's escapes (`escape_s` wall-clock, attempt cap, plateau) are
        # evaluated only BETWEEN rounds by `_visual_release_decision`. A round that runs long
        # therefore cannot be escaped from: 70 of the 94 non-completed corpus runs reach the
        # visual gate and never terminate, and r151 sat here for 116 minutes.
        #
        # A timeout needs no new branch: `asyncio.TimeoutError` is an `Exception`, so it lands in
        # the handler three lines below and becomes the existing `judge_error` verdict — which
        # #142 already treats as TRANSIENT and refuses to cache, so the screen is re-judged rather
        # than pinned at 0.0. Timing out lands on a path the code already takes.
        #
        # Calibrated like #870/#871: above one 240s watchdog so an honest slow call still
        # completes, below two so the uncapped re-rolls cannot stack.
        resp = await _asyncio.wait_for(
            client.chat([Message.user_multimodal(parts)],
                        temperature=0.0, max_tokens=8000),
            timeout=_judge_timeout_s_872())
        return _parse_verdict(getattr(resp, "content", "") or "")
    except Exception as exc:
        # judge_error marks a TRANSIENT failure — #142 must never cache it
        # (a frozen 0.0 would pin a healthy screen for the whole milestone).
        return {"similarity": 0.0, "dimensions": {}, "deviations": [f"judge call failed: {exc}"[:200]],
                "summary": "judge error", "judge_error": True}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _group_console_errors_740(console_errors: Any) -> Dict[str, List[str]]:
    """#740: {screen -> [messages]} inverted to {message -> [screens]}.

    One broken import crashes every route, so a per-screen listing reads as N problems when
    it is one. Grouping by MESSAGE makes the fan-out the headline: "this error, on 12 screens".
    Pure and total — any malformed entry is skipped rather than raising inside a capture.
    """
    out: Dict[str, List[str]] = {}
    if not isinstance(console_errors, Mapping):
        return out
    for name, msgs in console_errors.items():
        if not isinstance(msgs, (list, tuple)):
            continue
        for m in msgs:
            _m = str(m)
            if not _m.strip():
                continue
            _seen = out.setdefault(_m, [])
            if str(name) not in _seen:
                _seen.append(str(name))
    return out


def _served_build_is_stale_738(prev: Any, frontend_commit: str, bundle: str) -> bool:
    """#738: did app/frontend move while the SERVED bundle stayed byte-identical?

    Pure predicate so the decision is testable without a container. Both halves must be
    present and both must be known from the PREVIOUS capture — the first round of a run has
    no prior and can never be stale. Reports only; see the call site for the disposition.
    """
    if not (isinstance(prev, Mapping) and frontend_commit and bundle):
        return False
    _pc, _pb = prev.get("frontend_commit"), prev.get("bundle")
    if not (_pc and _pb):
        return False
    return bool(_pb == bundle and _pc != frontend_commit)


def _auth_wipeout_655(judged_screens, auth_bounced) -> bool:
    """#655: did the authenticated session fail WHOLESALE? Judged per ROUTE, not per screen.

    The re-mint retry below exists because a wholesale rejection is usually a race (#105) — a
    parallel validation cycle reset the DB or rotated the JWT keys between the mint and the
    capture. It only fired when EVERY auth screen bounced, but `_auth_bounced` is keyed by
    screen NAME while bouncing is a property of the ROUTE. Several screens routinely share one
    route and the bounce is flaky per capture, so ONE lucky screen vetoed the retry for all the
    rest. r30 is the shape; r49 and r68 are the same:

        scored   sim=0.30   browse_by_languages   /browse
        BOUNCED  sim=0.00   browse_home           /browse     <- same route, same token,
        BOUNCED  sim=0.00   card_hover_preview    /browse     <- same capture pass
        BOUNCED  sim=0.00   ... 8 more, covering every remaining auth route

    10 of 12 screens scored 0.0, `auth_unavailable` stayed False and no re-mint was attempted,
    because one screen on an already-bouncing route happened to come back. Those three runs are
    30 of the 43 auth-bounce records in the corpus.

    Counting by route: a route that bounced for any screen is a bounced route, so a run where
    every auth route bounced somewhere is a wipeout and earns its one retry. A genuinely partial
    failure (r43: 4 routes, the rest fine) still does not — that is a real per-route auth bug,
    and the deviation text already tells the lane exactly that.
    """
    auth_names = {s["name"] for s in judged_screens if s.get("auth")}
    if not auth_names:
        return False
    bounced = set(auth_bounced or ())

    # #916: a screen with NO route can neither prove a route bounced nor be proved bounced by
    # one. It used to do both: `s.get("route")` is `None` for such a screen, so ONE route-less
    # bounced screen put `None` into `bounced_routes`, and then EVERY route-less auth screen
    # matched it and counted as covered — a wholesale auth wipeout inferred from two missing
    # fields. Found by driving this function instead of reading it (item 262's pass): two screens,
    # neither with a route, one bounced → True.
    #
    # ★ Latent, not live: the corpus has 140 route-less design screens across 7 runs and NONE of
    # them is marked `auth`, so no run has taken this path. Fixed anyway because it costs two
    # lines and the failure is expensive and silent — a True here abandons the ENTIRE round
    # (`return {"passed": False, "auth_unavailable": True, "screens": []}`), which is exactly the
    # all-screens-unjudged state #892 exists to prevent.
    #
    # Direction chosen deliberately: missing the wipeout leaves the round to judge those screens
    # (low scores, recoverable); inventing one discards a whole round of real work.
    def _rt_916(s: Mapping[str, Any]) -> str:
        return str(s.get("route") or "").strip()

    bounced_routes = {_rt_916(s) for s in judged_screens
                      if s["name"] in bounced and _rt_916(s)}
    # A screen is covered when its ROUTE is known to have bounced, OR when the screen ITSELF
    # bounced — the latter needs no route at all, which is what keeps #655's own case working
    # (`test_a_screen_with_no_route_is_handled`: both auth screens bounced, one unrouted → still a
    # wipeout). The first version of #916 dropped that and I wrote the loss up as a deliberate
    # trade; #655's existing test said otherwise, and it was right.
    covered = {s["name"] for s in judged_screens
               if s["name"] in auth_names
               and (s["name"] in bounced or (_rt_916(s) and _rt_916(s) in bounced_routes))}
    return covered >= auth_names


def _blank_wipeout_656(results, blank_screens, shots) -> bool:
    """#656: is a blank capture wholesale enough to refund the ATTEMPT rather than the SCORE?

    Same defect shape as #655, in the blank path: `capture_transient` was
    ``bool(_blank_screens) and not shots`` — TOTAL blankness, nothing less. A capture that
    blanked 9 of 13 screens produced one shot, so it was "partial", so the bounded refund never
    applied. Measured over the run logs: 58 blank events across 20 runs, and **18 of them (31%)
    name 8 or more screens** — near-total, never total.

    That mattered because `_blocking_average` (#542a) drops every ``blank is True`` screen from
    its denominator as "a transient env glitch". The drop has no bound and no persistence check,
    so a near-total blackout does not refund the attempt AND does not count — the gate is simply
    decided by whatever few screens survived:

        r60   9 blank -> the average was taken over 4 screens
        r43   7 blank -> over 5
        r121  4 blank -> over 4, giving blocking_average 0.6125

    The rule needs no tuned constant: the gate must not be decided by FEWER screens than it
    refunded. When the blanks are at least as many as the screens that scored, the capture as a
    whole is not credible and it is the same condition #75a already refunds — bounded by the
    same `_TRANSIENT_REFUND_CAP`, so a genuinely blank app still flows to a real verdict after
    three tries.

    A true minority blank is unchanged and still returns False: #75a's reason for that
    ("a partial-blank must not discard a fixable sibling's 0.55 and suppress its remediation")
    holds precisely while the siblings are the majority.
    """
    if not blank_screens:
        return False
    if not shots:
        return True                       # the original total-blackout case, unchanged
    blocking = [r for r in (results or [])
                if isinstance(r, dict) and not r.get("advisory")]
    blanked = [r for r in blocking if r.get("blank") is True]
    return bool(blocking) and len(blanked) * 2 >= len(blocking)


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
    milestone_owned_routes: Optional[set] = None,
    milestone_label: Optional[str] = None,   # #941
) -> Dict[str, Any]:
    """Compare the running app against the reference designs.

    Returns {"passed": bool, "summary": str, "screens": [{name, route,
    similarity, passed, deviations, screenshot}], "skipped": [names]}.
    ``passed`` is True iff every judged screen reaches ``min_similarity``
    (default 0.65, env ENVGEN_VISUAL_MIN). No mappable references → passes
    vacuously with a summary saying so (the gate only binds when references
    exist — that's the user-provided design contract)."""
    # #891: the capture's only real input is the built frontend. r32 captured with
    # `app/frontend/src` EMPTY — the blank-capture class (#75a/#737), where a blank PNG is then
    # scored, refunded, and consumed as evidence of stability. Naming the missing input here
    # separates "the app renders nothing" from "the frontend was never written".
    try:
        from .stage_contract import require_stage_input_891
        _src891 = Path(project_dir) / "app" / "frontend" / "src"
        require_stage_input_891(
            "visual capture", "app/frontend/src/**/*.jsx", "the frontend scaffold",
            present=lambda: list(_src891.rglob("*.jsx")) if _src891.is_dir() else [],
            detail="every capture from here will be blank, and a blank capture is NOT evidence "
                   "that the app is stable (#737).")
    except Exception:
        pass

    project_dir = Path(project_dir).resolve()
    if min_similarity is None:
        try:
            min_similarity = float(os.environ.get("ENVGEN_VISUAL_MIN", "0.65"))
        except Exception:
            min_similarity = 0.65
    known_routes: set = set()
    _stale_serve_715 = None
    try:
        _app = project_dir / "app" / "frontend" / "src" / "App.jsx"
        if _app.exists():
            known_routes = set(re.findall(
                r'<Route\s+path=["\']([^"\']+)["\']',
                _app.read_text(encoding="utf-8", errors="ignore")))
            # #715: IS THE APP WE ARE ABOUT TO PHOTOGRAPH BUILT FROM THIS FILE?
            # #713 settled that the r147 collapse was the SERVE side: the rename landed at
            # 04:02:44, nothing rebuilt, and the 04:03:54 capture hit a bundle that knew only
            # the old paths, so four screens fell to the catch-all and scored 0.03-0.08. The
            # route list above is re-parsed from SOURCE every call and is never stale — the
            # gap is between it and what the container serves, and nothing anywhere checked
            # that. It is not rare: 103 of 127 runs (81%) contain screens scored against a
            # page some older bundle produced.
            #
            # The instrument for this already existed and had never been wired:
            # DockerInspectImageTool ("useful for debugging when containers show stale content")
            # is exported, in no bundle, and absent from all 253 run logs. Rather than grant a
            # tool, the gate does the same two commands itself — it already has project_dir,
            # and this is a framework check, not an agent capability.
            #
            # Reports only. A mismatch does not mean the app is broken; it means THIS
            # MEASUREMENT IS VOID, which is the distinction the framework could not previously
            # make — and the reason a phantom 0.05 was indistinguishable from a real one.
            try:
                import subprocess as _sp715
                _cf715 = None
                for _c715 in ("docker-compose.yml", "compose.yml", "docker-compose.yaml"):
                    if (project_dir / _c715).exists():
                        _cf715 = project_dir / _c715
                        break
                if _cf715 is not None:
                    # #936: was `docker compose ps -q frontend` — no docker binary on a podman
                    # host, and podman-compose has no service positional either, so this returned
                    # "" forever and both probes below never ran.
                    _cid715 = _container_id_936(_cf715, "frontend")
                    if _cid715:
                        # The container is nginx serving the BUILD, not the source: the
                        # Dockerfile is multi-stage and ends
                        # `COPY --from=builder /app/dist /usr/share/nginx/html`, so
                        # `src/App.jsx` does not exist in it. My first draft read that path and
                        # would have silently never fired. What DOES survive the build is the
                        # route strings themselves, as literals inside the bundle — so grep the
                        # served JS for each route the source declares. `src/` is still tried
                        # first for a dev-server layout.
                        _served715 = _sp715.run(
                            [_runtime_bin_936(), "exec", _cid715, "sh", "-c",
                             "cat /app/src/App.jsx 2>/dev/null || "
                             "cat /usr/share/nginx/html/assets/*.js 2>/dev/null"],
                            capture_output=True, text=True, timeout=30).stdout
                        if _served715:
                            # A param route ships as its literal prefix; compare on the static
                            # head so `/browse/genre/:genreId` is not reported missing merely
                            # because the bundle stores the pattern differently.
                            def _head715(_r: str) -> str:
                                return _r.split(":", 1)[0].rstrip("/") or "/"
                            _missing715 = {
                                _r for _r in known_routes
                                if len(_head715(_r)) > 1 and _head715(_r) not in _served715}
                            # UNVERIFIED ASSUMPTION, guarded. That route paths survive into the
                            # bundle as literals is near-certain for Vite but could not be
                            # checked offline — the delivered tree has no `dist/` (it is built
                            # inside the container). If the assumption is wrong this fires on
                            # EVERY route of EVERY run, which is worse than silence. So a
                            # near-total miss is reported as a suspect PROBE, not a stale build:
                            # a real staleness moves a few routes, not all of them.
                            if known_routes and len(_missing715) >= max(3, len(known_routes) - 1):
                                _LOG.warning(
                                    "#715 probe inconclusive: %d of %d source routes are absent "
                                    "from the served bundle. A stale build moves a few routes, "
                                    "not nearly all — this more likely means route literals do "
                                    "not survive the build the way this check assumes. Treating "
                                    "it as no signal.",
                                    len(_missing715), len(known_routes))
                                _missing715 = set()
                            if _missing715:
                                _stale_serve_715 = sorted(_missing715)
                                _LOG.warning(
                                    "#715 the SERVED frontend does not know %d route(s) the "
                                    "source declares: %s. The capture is about to navigate to "
                                    "them and the container will fall through to its catch-all, "
                                    "so those screens will photograph another page and score "
                                    "near zero. That is a STALE BUILD, not a bad page — the "
                                    "scores and deviations from this pass are void for them.",
                                    len(_stale_serve_715), ", ".join(_stale_serve_715[:6]))
                            else:
                                # #722: SAY SO WHEN IT IS CLEAN. Until now #715 had two warning
                                # branches and no third, so silence covered three different
                                # states: the probe ran and found nothing, the probe never ran,
                                # and the probe was skipped by a guard above. r148 is exactly
                                # that ambiguity — neither warning appears, and grepping the log
                                # for "#715" returns six hits that are all timestamp
                                # milliseconds. The one check built to answer item 34's
                                # source-vs-served question told us nothing about r148, which is
                                # the same defect shape as #691's silent skip, #696's invisible
                                # load failure and #712's dead branch.
                                #
                                # INFO, not WARNING: a clean probe is not news, it is provenance.
                                # What matters is that "checked, matched" and "never checked" stop
                                # looking identical in a log.
                                _LOG.info(
                                    "#715 served build matches the source: all %d declared "
                                    "route(s) are present in the bundle.", len(known_routes))
                        # #738: A STALE BUNDLE WHOSE ROUTES DID NOT CHANGE.
                        # #715 compares ROUTE LITERALS, so it only sees staleness that renamed
                        # or added a route — r147's case. r148 died of the other half and #715
                        # would have called it CLEAN: the routes never changed, a frontend bug
                        # fix simply never reached the container, and #722 would have printed
                        # "served build matches the source" over an app that crashed on every
                        # page. A false all-clear is worse than the silence #722 was built to
                        # end.
                        #
                        # The observation already exists — a lane wrote it by hand into the P0
                        # that never got actioned: "PRIOR FIX (task_17fc0b5257) DID NOT LAND.
                        # The deployed bundle hash + error signature are IDENTICAL to before."
                        # Vite content-hashes its asset filenames, so that check is mechanical:
                        # if the frontend source moved and the served asset names did not, the
                        # container is serving a build from before the edit.
                        #
                        # Keyed on the last commit that TOUCHED app/frontend, not on HEAD. Most
                        # commits in a run are backend or docs, and those legitimately leave the
                        # bundle alone — keying on HEAD would fire on nearly every round.
                        #
                        # Same disposition as #715: reports, decides nothing. A stale serve does
                        # not mean the app is broken, it means this measurement is of the wrong
                        # build. Any fault leaves the state file untouched and says nothing.
                        _assets738 = _sp715.run(
                            [_runtime_bin_936(), "exec", _cid715, "sh", "-c",
                             "ls -1 /usr/share/nginx/html/assets/ 2>/dev/null"],
                            capture_output=True, text=True, timeout=20).stdout.split()
                        _bundle738 = " ".join(sorted(_assets738))
                        _fe738 = subprocess.run(
                            ["git", "log", "-1", "--format=%H", "--", "app/frontend"],
                            cwd=str(project_dir), capture_output=True, text=True,
                            timeout=20).stdout.strip()
                        _sf738 = project_dir / "design" / "visual_gate" / "served_build.json"
                        _prev738: Dict[str, Any] = {}
                        try:
                            if _sf738.exists():
                                _prev738 = json.loads(
                                    _sf738.read_text(encoding="utf-8")) or {}
                        except Exception as _sb_exc:
                            # #887: same shape as #884, one function away. `_sf738.exists()`
                            # above already separates "first round, no prior" — which the probe's
                            # docstring calls a legitimate never-stale state — from "the file is
                            # there and will not parse". This handler collapsed them back.
                            #
                            # `_served_build_is_stale_738` returns False on an empty `prev`
                            # (`if not (_pc and _pb): return False`), so an unreadable
                            # served_build.json reads as **NOT STALE** — a false all-clear on the
                            # one probe that exists because, in its own words, "#715 cannot see
                            # this case: the routes are unchanged, so it reports the build clean".
                            # That is the mechanism recorded as letting r148 release v1.0.0 with
                            # the SPA throwing on every route.
                            #
                            # The permissive default stays (a corrupt stamp must not block a
                            # capture); what it must not be is indistinguishable from round one.
                            if not globals().get("_said_sb_887"):
                                globals()["_said_sb_887"] = True
                                _LOG.error(
                                    "SERVED-BUILD STAMP UNREADABLE (%s: %s) — #738's stale-bundle "
                                    "check is DISABLED for this round and will report the build "
                                    "clean, which is exactly the blind spot it was written to "
                                    "cover (#887).",
                                    type(_sb_exc).__name__, _sb_exc)
                            _prev738 = {}
                        if _served_build_is_stale_738(_prev738, _fe738, _bundle738):
                            _LOG.warning(
                                "#738 the SERVED bundle did not change while app/frontend did: "
                                "still %s, but the frontend's last commit moved %s -> %s. The "
                                "container is serving a build from BEFORE that edit, so this "
                                "capture measures the old app and any fix in it is not present. "
                                "Rebuild the frontend image (a source edit alone does not "
                                "restage nginx's /usr/share/nginx/html). #715 cannot see this "
                                "case: the routes are unchanged, so it reports the build clean.",
                                _bundle738[:120], str(_prev738.get("frontend_commit"))[:9],
                                _fe738[:9])
                        if _bundle738 and _fe738:
                            try:
                                _sf738.parent.mkdir(parents=True, exist_ok=True)
                                _sf738.write_text(
                                    json.dumps({"frontend_commit": _fe738,
                                                "bundle": _bundle738}),
                                    encoding="utf-8")
                            except Exception:
                                pass
            except Exception:
                pass
    except Exception:
        pass
    screens = map_reference_screens(
        reference_images, known_routes,
        classifications=load_screen_classifications(project_dir),  # FIX #132
        ui_pages=load_ui_pages(project_dir))                       # FIX #416
    # #542a: a screen that DUPLICATES another's capture route (same route -> same static
    # screenshot) can't be fairly scored as its own blocking page — demote the non-canonical
    # duplicate to ADVISORY so it is still judged/reported but never drags the blocking
    # pass/average. Deterministic + only-demotes, so gating is byte-identical when there are
    # no duplicate-route screens (transient names are already advisory from map_reference_screens).
    screens = _demote_duplicate_route_screens(screens)
    # #565: NON-FINAL milestone advisory scoping. When the caller supplies THIS
    # milestone's OWNED routes (VisualFidelityGate.maybe_run does this ONLY for a
    # non-final milestone — final/single-milestone passes None), demote every BLOCKING
    # screen whose route the milestone does NOT own to ADVISORY: still captured/reported,
    # but excluded from `passed`, the blocking average, `failing`, and remediation_text —
    # so an intermediate milestone stops scoring + filing frontend remediation for pages a
    # LATER milestone owns (M1 churning on M2/M3's movies/my_list). Default None → no
    # demotion → byte-identical. SAFETY: never make the exam vacuous — if scoping would
    # leave ZERO blocking screens, skip it (judge the full set) and log loudly. Same
    # only-demotes mechanism as _demote_duplicate_route_screens, so gating is byte-identical
    # when milestone_owned_routes is None/empty.
    _scope_excluded_names: List[str] = []
    if milestone_owned_routes:
        _owned_norm = {_norm_route_for_scope(r) for r in milestone_owned_routes}
        _owned_norm.discard("")
        if _owned_norm:
            _blk = [s for s in screens if not s.get("advisory")]
            _demote = [s for s in _blk if not _route_in_scope(s.get("route"), _owned_norm)]
            if _demote and len(_demote) < len(_blk):
                for s in _demote:
                    s["advisory"] = True          # out of passed / blocking-avg / failing
                    s["scope_excluded"] = True    # out of remediation_text (this-milestone only)
                _scope_excluded_names = sorted(str(s.get("name")) for s in _demote)
                _LOG.warning(
                    "VISUAL MILESTONE-SCOPE (#565): demoted %d non-owned screen(s) %s to "
                    "advisory for this milestone (owned routes=%s) — %d owned blocking "
                    "screen(s) scored.",
                    len(_demote), _scope_excluded_names,
                    sorted(_owned_norm), len(_blk) - len(_demote))
            elif _demote:
                _LOG.warning(
                    "VISUAL MILESTONE-SCOPE (#565): scoping to owned routes=%s would hide "
                    "ALL %d blocking screen(s) — skipping scope (judging the full set) to "
                    "avoid a vacuous gate.", sorted(_owned_norm), len(_blk))
    judged_screens = _select_judged_screens(screens, max_screens)
    skipped = [s["name"] for s in screens if not s.get("route")]
    if not judged_screens:
        return {"passed": True, "summary": "no mappable reference screens — visual gate vacuous",
                "screens": [], "skipped": skipped}

    capture = capture_fn
    # #934 hoisted this out of the `capture is None` branch below: the no-capture handler needs it,
    # and with an injected `capture_fn` that branch never ran, so the name was unbound (caught by
    # #542's end-to-end test on the first full run). One definition, not two — a value duplicated
    # under one name is a promise that drifts on the first edit to either.
    shots_dir = out_dir or (project_dir / "design" / "visual_gate")
    # #935: same reason as shots_dir above — the no-capture handler reads it whichever branch ran.
    _cap_err935: Dict[str, str] = {}
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
        auth_measured = any(s["auth"] for s in judged_screens)
        # #522b (netflix r93): DO NOT gate token minting on the design-analyst's per-screen
        # `requires_auth` flag — it is lane-NOISY (r92 measured catalog auth → token minted →
        # catalog rendered 0.50; r93 measured it public → token=None → NO token injected →
        # /api/games 401 → every catalog page stuck 0.08). The token injection (add_init_script,
        # both keys, pre-navigation) is INERT on a truly-public app but is the ONLY thing that
        # makes an auth-gated GET return DATA instead of 401. So mint whenever the app HAS an
        # auth system — a DETERMINISTIC signal (a seed user exists OR a /login|/signin route was
        # projected) — independent of the noisy per-screen flag. Generalizable: a no-auth app has
        # neither signal → token stays None → unchanged behavior.
        _demo = _seed_demo_login(project_dir)
        _has_login_route = any(str(r).rstrip("/").lower() in ("/login", "/signin", "/signup")
                               for r in (known_routes or set()))
        has_auth = auth_measured or bool(_demo) or _has_login_route
        # Log in as the SEEDED demo user so authed screens render POPULATED (matching the
        # references), not the empty lists a fresh throwaway user sees under tenant-scoping.
        token = _mint_token(be_port, demo=_demo) if has_auth else None
        if auth_measured and not token:
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

        _auth_bounced: List[str] = []
        _blank_screens: List[str] = []
        _picker_screens: List[str] = []          # #657
        _console740: Dict[str, List[str]] = {}   # #740

        async def capture(scr):  # noqa: F811 — default capture closes over the boot
            return await capture_route_screenshots(
                base_url, scr, token, shots_dir, auth_redirected=_auth_bounced,
                blank_screens=_blank_screens, picker_screens=_picker_screens,
                console_errors=_console740, capture_errors=_cap_err935)

    else:
        _auth_bounced = []
        _blank_screens = []
        _picker_screens = []
        _console740 = {}

    shots = await capture(judged_screens)
    if _auth_wipeout_655(judged_screens, _auth_bounced):        # #655: by ROUTE, not by screen
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
            _picker_screens.clear()
            shots = await capture(judged_screens)
    if _auth_wipeout_655(judged_screens, _auth_bounced):        # #655
        # The minted token was rejected wholesale (e.g. the validation cycle
        # rebuilt the app between mint and capture, rotating the JWT keys).
        return {"passed": False, "auth_unavailable": True,
                "summary": ("authenticated session rejected — every auth route "
                            "redirected to /login despite a freshly minted "
                            "token (incl. one re-mint retry); skipping judgment"),
                "screens": [], "skipped": skipped}
    if judged_screens and not shots and not _blank_screens:
        # #949: say what is KNOWN, not a cause nobody checked.
        #
        # This summary asserted "app not reachable" for every zero-capture round, and it does not
        # know that. `heal_missing_browser` re-raises when a playwright binary is missing and
        # cannot be installed, so a browser-infra failure lands here reading as an app failure —
        # a mis-attribution, which is worse than silence: it sends the reader to the app, and
        # this session already lost a long detour to exactly that shape (#934's stale PNG).
        #
        # #935's `_cap_err935` is in scope and holds the actual exception per screen. Name it when
        # it exists, say plainly that nothing was recorded when it does not, and hand the dict out
        # so the caller can record it rather than re-deriving it from a sentence.
        _why949 = "; ".join(f"{_k}: {_v}" for _k, _v in list(_cap_err935.items())[:3])
        return {"passed": False,
                "summary": ("capture unavailable — 0 of "
                            f"{len(judged_screens)} screen(s) photographed; not judged"
                            + (f" — the capture raised {_why949}" if _why949 else
                               " — no capture exception was recorded, so the app most likely did "
                               "not serve (unverified)")),
                "screens": [], "skipped": skipped,
                "capture_unavailable": True,
                "capture_errors": dict(_cap_err935),
                "min_similarity": min_similarity}
    judge = judge_fn or judge_screen_pair

    # #892: a per-ROUND budget, spent as VERDICTS rather than as skips.
    #
    # #872 bounded ONE judge call at 300s. A round is ~12 screens, so the round itself was still
    # 60 minutes — and the gate's escapes (`escape_s` wall-clock, attempt cap, plateau) are
    # evaluated only BETWEEN rounds by `_visual_release_decision`, so a long round cannot be
    # escaped from while it runs. 70 of the 94 non-completed corpus runs die at this gate.
    #
    # ★ #872 recorded a per-round cap as "actively harmful", and that was right about the version
    # I had in mind: a budget that STOPS STARTING screens leaves them out of `results`, and an
    # absent screen is `unjudged` — "an owned screen that was never judged is a FAILURE, not a
    # skip". It would convert a slow run into a permanently failing one.
    #
    # The harm was in the SKIP, not in the bound. `judged = {r["name"] for r in results}` counts a
    # screen that appears AT ALL, so spending the remaining screens as `judge_error` verdicts
    # (score 0.0, `judge_error: True`) keeps them judged — the exact state #142 refuses to cache
    # and re-judges next round, and the exact state a #872 timeout already produces. Bounded and
    # recoverable, instead of bounded and fatal.
    #
    # Sized off #872's own ceiling: three screens' worth of honest slow judging before the round
    # gives the wall-clock escape a chance to look at it.
    import time as _t892
    _round_budget_892 = max(
        _judge_timeout_s_872(), float(os.environ.get("ENVGEN_JUDGE_ROUND_BUDGET_S") or "900"))
    _round_started_892 = _t892.monotonic()
    _spent_892 = False

    results: List[Dict[str, Any]] = []
    for screen in judged_screens:
        if not _spent_892 and (_t892.monotonic() - _round_started_892) > _round_budget_892:
            _spent_892 = True
            _LOG.error(
                "VISUAL ROUND BUDGET SPENT after %.0fs — the remaining screens are recorded as "
                "judge_error (transient, not cached, re-judged next round) so the round can end "
                "and the gate's escapes can run. They are NOT skipped: an unjudged owned screen "
                "fails the verdict outright (#892).", _round_budget_892)
        if _spent_892:
            results.append(_spent_verdict_892(screen))
            continue
        shot = shots.get(screen["name"])
        if not shot:
            _no_shot_768 = False
            if screen["name"] in _picker_screens:
                # #657: the SPA hydrated perfectly — it rendered the profile picker, and the
                # capture could not get past it within _PROFILE_RESELECT_MAX reselect attempts.
                # Telling the lane to fix the page's mount/data load would send it after a bug
                # that does not exist; the real ask is that profile selection persist.
                _dev = (f"route {screen['route']} never got past the PROFILE PICKER — the SPA "
                        "hydrated and rendered the who's-watching chooser instead of the route, "
                        "through every reselect retry. The page's mount and data load are fine; "
                        "make profile selection persist (store it and honour it on load) so a "
                        "direct navigation to this route renders the route")
                # #657b — AND IT SCORES, WHICH #657 CHANGED WITHOUT SAYING SO.
                # Splitting picker screens out of `_blank_screens` also moved them across the
                # `blank` flag below, and #542a's `_blocking_average` refunds ONLY `blank is
                # True`. So before #657 a picker screen was excluded from the gating average as
                # a transient env glitch; after it, the same screen counts as a hard 0.0.
                #
                # Caught by cross-auditing this session's own fixes against each other — the
                # #645 shape, where one of my fixes silently shadowed another. The suite stayed
                # green through it because no test crossed #657 and #542a.
                #
                # The new behaviour is the RIGHT one and is kept deliberately: #657's own
                # diagnosis is that profile selection does not persist, which is an application
                # defect, not a capture glitch. An app whose every route lands on the
                # who's-watching chooser is unusable, so it must score and block; refunding it
                # would ship exactly that. What was missing is that anyone could see the choice
                # was made — hence this note and the test that pins it.
            elif screen["name"] in _blank_screens:
                _dev = (f"route {screen['route']} rendered BLANK — navigated + reached "
                        "networkidle but the SPA never hydrated after ~5s re-poll (a bare "
                        "<div id=root> shell). If transient (mid-rebuild) it is refunded a "
                        "few times; if it persists it is a real render/data-fetch failure "
                        "on this route — fix the page's mount/data load, not its styling")
                # #740: name the ACTUAL error when the browser gave us one. Without this the
                # lane is told a symptom ("never hydrated") and has to rediscover the cause;
                # r148's remediation tasks said exactly that while the console was repeating
                # `TypeError: (void 0) is not a function` on every route.
                _err740 = _console740.get(screen["name"]) or []
                if _err740:
                    _dev += (". The browser reported: " + " | ".join(_err740[:3])
                             + " — fix THAT, it is the reason the shell is empty")
            elif screen["name"] in _auth_bounced:
                _dev = (f"route {screen['route']} redirected to /login — the auth guard "
                        "rejected the session on THIS route only; fix the route's auth "
                        "handling, not its styling")
            else:
                # #768: NO CAPTURE AT ALL — and this scored a hard 0.00 that COUNTED.
                # r150's final round: 12 screens, 3 captures written, NINE zeros. Exact. The
                # zeros track missing captures round by round (4 shots -> 0 zeros; 0 shots ->
                # 7 zeros), so they are not the judge's opinion of the page — the page was
                # never photographed. And the app is fine: the captures from the 0.65-0.75
                # rounds are a complete Netflix clone (wordmark, nav, hero with a seeded
                # title, poster rails, a working title-detail modal, a full-screen player).
                #
                # `blank` gets refunded (#75a), excluded from the blocking average (#542a) and
                # watched by #737/#750. This branch sets none of that, so a screen the harness
                # failed to photograph drags the gate exactly as if the lane had shipped a
                # broken page — and #500's merge then erases the evidence, which is why
                # `could not be captured` appears in 0 of 116 persisted verdicts.
                _dev = (f"route {screen['route']} produced NO capture this pass — the harness "
                        "did not photograph it, so there is nothing to judge. This is not a "
                        "verdict on the page")
                # #935: name the failure. "produced NO capture" tells a reader the harness
                # missed it; the exception type says WHY, and #769 is explicit that the three
                # common causes are three different problems ("a navigation timeout, a closed
                # page and a proxy refusal"). Only the logger had it.
                _why935 = _cap_err935.get(screen["name"])
                if _why935:
                    _dev += f" — the capture raised {_why935}"
                _no_shot_768 = True
                # #934: and the PREVIOUS round's photograph is still sitting at
                # `visual_gate/<name>.png`, looking healthy.
                #
                # The record says the truth (`screenshot: None`, `capture_missing: True`); the
                # DIRECTORY does not. r154 ran seven rounds with `title_detail` at 0.00 while
                # `title_detail.png` held a complete, correct detail page whose mtime never moved
                # off 17:19:57 — round 1's capture. I opened that file, reasoned from it, and
                # wrote two tickets around "the judge scored a working page 0.00" before checking
                # the mtime. It is also the reading a lane gets, and the reading #713 gets: a
                # stale file is a real image that can duplicate-match another screen.
                #
                # Renamed, never deleted — the pixels stay available under a name that cannot be
                # mistaken for this round's capture, and #930 has already archived it under its
                # own code_state if it ever earned a score.
                _retire_stale_capture_934(shots_dir, screen["name"])
            results.append({"name": screen["name"], "route": screen["route"],
                            "similarity": 0.0, "passed": False, "dimensions": {},
                            "deviations": [_dev],
                            "blank": screen["name"] in _blank_screens,
                            # #768: a separate flag, NOT folded into `blank` — #657 deliberately
                            # split the picker OUT of blank and #657b records what that cost, so
                            # overloading it again would repeat exactly that mistake.
                            "capture_missing": _no_shot_768,
                            # #935: the exception, on the record and therefore in #933's ledger
                            # entry — None for every path that is not a raised capture failure.
                            "capture_error": _cap_err935.get(screen["name"]),
                            "advisory": bool(screen.get("advisory")),
                            "console_errors": _console740.get(screen["name"]) or [],  # #740
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
                        # #767b: carry the raw reply through. This append PROJECTS a fixed key
                        # set, so #767's crumb was being dropped exactly here — the fix would
                        # have shipped and recorded nothing. Only ever present on a 0.00, so
                        # every other record is byte-identical.
                        **({"raw_judge_reply": verdict["raw_judge_reply"]}
                           if verdict.get("raw_judge_reply") else {}),
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
    # #542a: the gating fidelity average over BLOCKING screens ONLY (advisory/transient
    # screens excluded). Reported alongside the pass/fail so the recorded Part-A metric
    # stops being dragged by transient interaction-state screens a static projector cannot
    # render. Purely additive — the pass/fail verdict + the 0.65 bar are unchanged.
    _blk_avg = _blocking_similarity_average(results)
    failing = [f"{r['name']}({r['similarity']:.2f})" for r in _blocking if not r["passed"]]
    _adv_note = [f"{r['name']}({r['similarity']:.2f})" for r in results
                 if r.get("advisory")]
    summary = ("all %d screens ≥ %.2f" % (len(_blocking), min_similarity) if passed
               else "below %.2f: %s" % (min_similarity, ", ".join(failing)))
    summary += " (blocking avg %.2f)" % _blk_avg
    if _adv_note:
        summary += " [advisory (overlay, non-blocking): %s]" % ", ".join(_adv_note)
    if _blank_screens:
        summary += " [blank capture: %s]" % ", ".join(_blank_screens)
    # #740: SAY THE ERROR OUT LOUD, ONCE PER PASS. Grouped by message rather than by screen —
    # one broken import crashes every route, and 12 identical lines read as 12 problems.
    _by740 = _group_console_errors_740(_console740)
    if _by740:
        _LOG.warning(
            "#740 the browser reported %d distinct uncaught/console error(s) during this "
            "capture: %s. Nothing in this module used to read the console, so a crashed SPA "
            "could only be described as 'rendered BLANK' and the cause had to be rediscovered "
            "by whoever drove a browser next. These are now in each screen's deviations.",
            len(_by740),
            "; ".join(f"{_m740[:160]} (on {len(_ns740)} screen(s): "
                      f"{', '.join(sorted(_ns740)[:4])})"
                      for _m740, _ns740 in sorted(
                          _by740.items(), key=lambda kv: -len(kv[1]))[:4]))
    # #419: PERSIST the per-dimension verdict to disk so fidelity iteration is
    # TARGETED, not guessed (see _persist_verdict). Best-effort + write-only.
    _persist_verdict(project_dir, passed=passed, min_similarity=min_similarity,
                     milestone_label=milestone_label,
                     summary=summary, coverage=_coverage, results=results)
    # FIX #75a: a REFUNDABLE transient ONLY when EVERY judged screen was a blank shell
    # (no real verdict obtained). If SOME screens produced real shots, do NOT refund —
    # their verdicts + remediation must flow this tick (a partial-blank must not discard
    # a fixable sibling's 0.55 and suppress its remediation).
    return {"passed": passed, "summary": summary, "screens": results, "skipped": skipped,
            # #901: scope-labelled, because `screens` and `coverage` describe DIFFERENT SETS and
            # the document did not say so. `screens` is #500's MERGE (this round plus anything a
            # prior round scored); `coverage` is computed from THIS round's `results`. r153's
            # verdict therefore lists `browse_home_rows` (0.40) and `card_hover_preview` (0.30)
            # with scores while `coverage.unjudged` calls them never-judged.
            #
            # ★ Both halves are individually right — the gate evaluates the current round on
            # purpose (`visual_gate_verdict(results=results, ...)`, and #351 means this block does
            # not gate) — but as a DOCUMENT it contradicts itself, and it misled me into filing a
            # gate defect that does not exist. The artifact a human opens should not need the
            # source to disambiguate it.
            "coverage": {**(_coverage if isinstance(_coverage, dict) else {}),
                         "scope": "this round's captures; `screens` above is #500's merge across "
                                  "rounds, so a screen may carry a score here and still appear "
                                  "under `unjudged` (#901)"},
            "blocking_average": _blk_avg,  # #542a: gating avg over BLOCKING screens only
            # #656: a NEAR-total blackout is the same condition as a total one.
            "capture_transient": _blank_wipeout_656(results, _blank_screens, shots),
            # #565: screens demoted for THIS (non-final) milestone — excluded from
            # remediation_text so an intermediate milestone never files frontend work for a
            # later milestone's pages. Empty on the final/single-milestone path.
            "scope_excluded_screens": _scope_excluded_names,
            "min_similarity": min_similarity}


def _runtime_bin_936() -> str:
    """``docker`` when it exists, else ``podman`` — see `container_runtime` for the whole story.

    #936: this module shelled out to a literal ``"docker"`` in four places and there is no docker
    binary on a podman-backed gen host, so #715 and #738 had never run. Kept as a thin local name
    because four call sites and a test suite refer to it; the logic lives in one place.
    """
    from .container_runtime import runtime_bin
    return runtime_bin()


def _container_id_936(compose_file: Any, service: str, *, timeout: int = 20) -> str:
    """The running container id for a compose service, on either runtime (#936)."""
    from .container_runtime import container_id
    return container_id(compose_file, service, timeout=timeout)


def _retire_stale_capture_934(shots_dir: Any, name: str) -> bool:
    """The harness did not photograph this screen — take the PREVIOUS round's picture out of the
    way. Returns True if a stale file was retired.

    The record already tells the truth (`screenshot: None`, `capture_missing: True`); the
    directory does not. r154 ran seven rounds with `title_detail` at 0.00 while
    `visual_gate/title_detail.png` held a complete, correct detail page whose mtime never moved off
    round 1. I opened that file, reasoned from it, and wrote two tickets around "the judge scored a
    working page 0.00" before checking the mtime. A lane reads the same directory, and so does
    #713, for which a stale file is a real image that can duplicate-match another screen.

    Renamed, never deleted: the pixels stay under a name that cannot be mistaken for this round,
    and #930 has already archived the image under its own code_state if it ever earned a score.
    """
    try:
        p = Path(shots_dir) / f"{name}.png"
        if not p.is_file():
            return False
        p.replace(p.with_name(f"{name}.NOT-CAPTURED.png"))
        return True
    except Exception:
        return False


def _archive_capture_930(rec: Dict[str, Any], vdir: Any, code_state: Any) -> Dict[str, Any]:
    """Copy the image that earned THIS score aside, and point the record at the copy.

    #771 put the capture's path in the record so "look at the image" is a lookup rather than an
    inference. The path is stable — ``visual_gate/<name>.png``, rewritten every round — so as soon
    as #500's merge keeps an older record, that lookup returns a DIFFERENT picture than the one
    scored. r154: the title_detail record reads 0.6 and its `screenshot` is the file that scored
    0.00, twice.

    Called only for a record that just WON the merge, so the archive grows once per genuine
    improvement rather than once per round. `screenshot_live` keeps the moving path, so a reader
    can still find the current capture. Best-effort; any failure returns the record untouched.
    """
    try:
        src = rec.get("screenshot")
        if not src:
            return rec
        p = Path(str(src))
        if not p.is_file():
            return rec
        stamp = str(code_state or "").strip()[:8] or "nocommit"
        dst = Path(vdir) / "captures" / f"{p.stem}@{stamp}{p.suffix}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.is_file() or dst.stat().st_size != p.stat().st_size:
            import shutil as _sh930
            _sh930.copyfile(p, dst)
        return {**rec, "screenshot": str(dst), "screenshot_live": str(p)}
    except Exception:
        return rec


def _persist_verdict(project_dir: Any, *, passed: bool, min_similarity: float,
                     milestone_label: Optional[str] = None,
                     summary: str, coverage: Any, results: List[Mapping[str, Any]]) -> None:
    """#419/#500: write design/visual_gate/verdict.json — the BEST per-screen result MERGED
    across the milestone's captures — with each screen's per-dimension detail, so fidelity
    iteration is TARGETED and the recorded Part-A metric reflects the app's real fidelity.

    The judge scores 7 rich dimensions (layout / components / style / color / typography /
    iconography / copy) per screen; this dumps dimensions/deviations/fixes/measured color diffs
    to disk so the next lever fixes the ACTUAL weak dimension instead of guessing.

    #500 (netflix r68, live): it used to persist the LATEST attempt (overwrite). A TRANSIENT
    capture — the env mid-rebuild (a lane rebuilding a shared component → restart →
    ERR_CONNECTION_REFUSED → auth-bounce → every catalog page 0.00) — then CLOBBERED a prior good
    capture: r68's catalog pages measured 0.35–0.65 at one tick, 0.00 at the next (during a
    top_nav_bar rebuild), and the 0.00 persisted → recorded Part-A 0.00 while the app truly renders
    ~0.51 (delivery-time test-user: auth_ok, 14 pages, real data, no login wall). Now MERGE with the
    prior verdict.json, keeping the MAX per-screen similarity (+ that capture's full detail).
    Max-latch is correct for MEASUREMENT: a screen that never renders keeps 0.00 (still fails); one
    that rendered once keeps its real score — it can never FALSELY pass a broken screen. VERDICT.JSON
    IS DIAGNOSTIC-ONLY (nothing reads it back to gate delivery — the gate uses in-memory results +
    the #129/#138 latch), so this never changes gate/delivery behavior. Best-effort; never raises.
    Env/app-agnostic."""
    try:
        vdir = Path(project_dir) / "design" / "visual_gate"
        vdir.mkdir(parents=True, exist_ok=True)
        screens = [{
            "name": r.get("name"), "route": r.get("route"),
            "similarity": r.get("similarity"), "passed": r.get("passed"),
            "advisory": r.get("advisory"), "empty_state": r.get("empty_state"),
            "blank": r.get("blank"),
            # #768b: the THIRD fixed-key projection on this path, and the one that writes
            # verdict.json. Without these two lines `capture_missing` never reaches the gating
            # average (only the live one, which reads `results` directly) and #767's
            # `raw_judge_reply` never reaches disk at all — so #767 would still have recorded
            # nothing after #767b fixed its first projection. Found because a test asserted the
            # gating number and it disagreed with the live one; the same miss as #767b, one
            # function later.
            "capture_missing": r.get("capture_missing"),
            # #935: and the WHY. #771b's end-to-end key guard caught this on its first full run —
            # `capture_error` would have been the FOURTH field produced at capture and dropped by
            # this fixed-key projection, after #767's raw_judge_reply, #768's capture_missing and
            # #771's screenshot. The guard is doing exactly the job it was written for.
            "capture_error": r.get("capture_error"),
            # #771: WHICH IMAGE PRODUCED THIS SCORE. The record could not say. Both paths carry
            # `screenshot` and `reference` from the capture, and both projections dropped them,
            # so `verdict.json` gave a number with no way back to the pixels.
            #
            # That cost this session its single most decisive step. r150 scored nine screens
            # 0.00 and I spent three passes on scores, logs and stores before opening a PNG —
            # which showed a complete Netflix clone and reversed the conclusion, the
            # recommendation and the sign of the result. Finding the right file took matching
            # mtimes against round timestamps, and I got it WRONG once: the images I first read
            # were from the 0.75 rounds, not the 0.00 one.
            #
            # A path is 60 bytes. It turns "look at the image" from an inference into a lookup.
            "screenshot": r.get("screenshot"),
            "reference": r.get("reference"),
            # #771b: `console_errors` too — found by the end-to-end key guard below on its FIRST
            # run, which is the best validation that guard could have had. #740 collects the
            # browser's own errors and they are what made #753 findable, yet they lived only in
            # a log line: the third field lost on this one path, after #767's raw_judge_reply
            # and #768's capture_missing. Empty list rather than None so a reader can tell
            # "checked, none" from "not recorded".
            "console_errors": r.get("console_errors") or [],
            **({"raw_judge_reply": r["raw_judge_reply"]} if r.get("raw_judge_reply") else {}),
            "dimensions": r.get("dimensions") or {},
            "deviations": r.get("deviations") or [],
            "fixes": r.get("fixes") or [],
            "measured_deviations": r.get("measured_deviations") or [],
            "summary": r.get("summary") or "",
        } for r in results]

        def _sim(rec: Mapping[str, Any]) -> float:
            try:
                return float(rec.get("similarity") or 0.0)
            except Exception:
                return 0.0

        # #500: merge with the prior persisted verdict, keeping the BEST per-screen capture.
        prior_by_name: Dict[str, Any] = {}
        _prior_code_state_893 = None
        try:
            _pp = vdir / "verdict.json"
            if _pp.is_file():
                _pj = json.loads(_pp.read_text(encoding="utf-8"))
                _prior_code_state_893 = _pj.get("code_state")
                for s in (_pj.get("screens") or []):
                    if isinstance(s, dict) and s.get("name") is not None:
                        prior_by_name[s["name"]] = s
        except Exception as _pv_exc:
            # #884: an UNREADABLE prior verdict is not "there is no prior verdict".
            #
            # `if _pp.is_file()` above already separates the two, so reaching this handler means
            # the file EXISTS and could not be parsed — and `{}` then does two things silently:
            #
            #   1. #500's high-water merge stops merging, so every screen takes THIS round's live
            #      score and a previously-passing screen can regress.
            #   2. the carry-over loop below ("prior screens absent from this possibly-partial
            #      capture") carries nothing — so a screen this round did not capture simply
            #      VANISHES from the verdict.
            #
            # ★ (2) is the dangerous one. #872 established that `visual_gate_verdict` FAILS any
            # owned screen left unjudged — "an owned screen that was never judged is a FAILURE,
            # not a skip" — and it is not recoverable within the round. So a corrupt verdict.json
            # silently converts a partial capture into a gate FAILURE, in the file where 70 of the
            # 94 non-completed corpus runs die.
            #
            # This is the direction the usual analysis misses: the empty default is not a
            # permissive pass here, it is a silent fail. Announced once; the data cannot be
            # recovered from an unparseable file, so the fix available is to stop it being silent.
            if not globals().get("_said_prior_884"):
                globals()["_said_prior_884"] = True
                _LOG.error(
                    "PRIOR VERDICT UNREADABLE (%s: %s) — #500's high-water merge is disabled for "
                    "this round and any screen not captured now will be MISSING from the verdict, "
                    "which #872 shows the gate scores as a failure rather than a skip (#884).",
                    type(_pv_exc).__name__, _pv_exc)
            prior_by_name = {}

        # #621's HEAD stamp, hoisted here by #930 because the merge below now names the archive
        # after it. Its own rationale is unchanged and still written out at its old site; this is
        # a pure `git rev-parse` read, so computing it earlier decides nothing differently.
        _head_sha = None
        try:
            import subprocess as _sp
            _head_sha = _sp.run(["git", "-C", str(project_dir), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip() or None
        except Exception:
            _head_sha = None

        merged: List[Dict[str, Any]] = []
        _names_now = set()
        _below_928: List[str] = []
        for s in screens:
            _names_now.add(s.get("name"))
            p = prior_by_name.get(s.get("name"))
            if p is not None and _sim(p) > _sim(s):
                # #928: keep the high-water number — that IS #500's point, and the docstring
                # above defends it as the right MEASUREMENT — but stop the record implying the
                # app renders that way NOW. The aggregate already says so
                # (`blocking_average_live` + #711's `record_exceeds_live_by`); per screen it
                # said nothing, so the eight numbers a reader actually looks at were all
                # high-water with one aggregate caveat beside them.
                #
                # Measured over the runs holding both files: 8 of 10 carry at least one screen
                # whose recorded score exceeds the last live capture (46 screens, median gap
                # 0.54), and 24 of those recorded >=0.40 while the live capture was <=0.05 —
                # a collapsed screen presented as a good one. r148 is five of the 24
                # (browse_home 0.80/0.00, new_and_popular 0.75/0.00, my_list 0.72/0.00,
                # movies 0.70/0.00, games 0.62/0.00), which is how a run whose SPA crashed on
                # every route recorded ~0.7 fidelity.
                _below_928.append(str(s.get("name")))
                merged.append({**p, "similarity_live": _sim(s),
                               "similarity_live_note": (
                                   "this capture scored lower; `similarity` is the best-of-"
                                   "captures merge (#500), `similarity_live` is what the "
                                   "delivered frontend rendered at this code_state (#928). "
                                   # #931: and say whose evidence this is. Every other field on
                                   # this record — dimensions, deviations, fixes, screenshot —
                                   # describes the RECORDED capture, so a reader who sees
                                   # `similarity_live: 0.00` beside a deviations list about title
                                   # placement would take that list as the reason for the 0.00.
                                   # It is not; it is why the BETTER capture fell short of 1.0.
                                   # (Checked before writing it: `remediation_text` reads the
                                   # live results, not this file, so no lane is dispatched
                                   # against the stale list — the harm is to a human reader.)
                                   "dimensions/deviations/fixes/screenshot on this record "
                                   "describe the RECORDED capture, not the live one")})
            else:
                # #930: this capture won, so ARCHIVE the image that earned the score before the
                # next round overwrites it. `screenshot` is a stable path
                # (`visual_gate/<name>.png`) rewritten every round, so a record kept by #500's
                # merge points at the LATEST image rather than its own — r154's title_detail
                # record reads 0.6 and points at the file that scored 0.00. #771 added the path
                # so "look at the image" is a lookup instead of an inference; for every merged
                # screen that lookup silently returned the wrong picture.
                #
                # Only the winner is copied, only when it wins, so the archive grows once per
                # genuine improvement (a handful per screen per run) rather than once per round.
                merged.append(_archive_capture_930(s, vdir, _head_sha))
        # carry over prior screens absent from this (possibly partial) capture
        for name, p in prior_by_name.items():
            if name not in _names_now:
                # #928: and a screen this round never photographed must not keep a
                # `similarity_live` earned in some earlier round — that is the same lie one
                # level down. Say it was not captured instead.
                merged.append({**p, "similarity_live": None,
                               "similarity_live_note": (
                                   "not captured in this round; `similarity` is a previous "
                                   "capture's score (#500/#928)")})

        # #595: a reference frame captured with TWO OR MORE independent overlays open is not a
        # state the app can be in — demote before the chrome checks, same as #128/#542a do by
        # name. Runs BEFORE #588/#589 so a screen already excused here is not re-examined.
        try:
            _midint = screens_captured_mid_interaction(project_dir)
            _admid = screens_captured_showing_an_ad(project_dir)
            for _s in merged:
                if _s.get("advisory"):
                    continue
                _nm595 = str(_s.get("name") or "")
                if _nm595 in _admid:
                    _s["advisory"] = True
                    _s["advisory_reason"] = (
                        "#601 reference frame was captured with an ADVERTISEMENT playing — "
                        "no generation task asks the app to build an ad system, so the "
                        "difference is not the build")
                    continue
                _n = _midint.get(_nm595)
                if _n:
                    _s["advisory"] = True
                    _s["advisory_reason"] = (
                        f"#595 reference frame was captured with {_n} independent overlays open "
                        "at once — opening one closes another, so no implementation can render "
                        "this state")
        except Exception:
            pass

        # #588: a CONTENT-DOMINATED screen whose framework-defined chrome is provably COMPLETE
        # is demoted to advisory — the residual difference is content the app cannot reproduce.
        # Self-gating: the test is "every control the framework's own player emitter defines is
        # present", so a non-player page (which has none of them) can never qualify. Measured on
        # real trees: r139's PlayerPage carries all of them and scored 0.55, r142's carries only
        # `Back` and scored 0.50 — holistic similarity could not tell those apart, this can, and
        # r142 correctly keeps blocking with an actionable missing list.
        try:
            from .frontend_scaffold import _screen_is_player_449
            _fe = Path(project_dir) / "app" / "frontend"
            for _s in merged:
                if _s.get("advisory"):
                    continue
                # #589: above the bar, only a screen the framework itself treats as a player is
                # still worth inspecting — for everyone else the checklist does not apply.
                _is_player = bool(_screen_is_player_449(_s))
                # #942: judge the skip on the WORSE of the recorded and the live score.
                #
                # `_sim(_s)` is #500's high-water, so a screen at recorded 0.70 / live 0.00 cleared
                # this bar and was never inspected — the same merged-record read that #928 and #929
                # were about, one detector further on. I left it in place when I found it, on the
                # grounds that `chrome_incomplete` feeds `_merged_passed`; following that to its
                # end shows `_merged_passed` writes only `verdict["passed"]`, and verdict.json has
                # exactly ONE programmatic reader in the whole repo (its own prior-read here). So
                # the blast radius is the diagnostic file, and the deferral was over-cautious.
                #
                # `similarity_live` is absent when nothing diverged and None when the screen was
                # not captured this round; neither means zero (#907).
                _lv942 = _s.get("similarity_live")
                _worst942 = _sim(_s)
                if isinstance(_lv942, (int, float)):
                    _worst942 = min(_worst942, float(_lv942))
                if _worst942 >= min_similarity and not _is_player:
                    continue
                _nm = str(_s.get("name") or "")
                _cands = [_s.get("component"),
                          "".join(w.capitalize() for w in _nm.split("_")) + "Page",
                          "".join(w.capitalize() for w in _nm.split("_"))]
                for _c in _cands:
                    if not _c:
                        continue
                    _missing = player_chrome_missing(_fe, _c)
                    if _missing == []:
                        if _sim(_s) < min_similarity:
                            _s["advisory"] = True
                            _s["advisory_reason"] = (
                                "#588 content-dominated screen with complete "
                                "framework chrome — scored on content, not build")
                        break
                    if _missing:
                        _s["chrome_missing"] = _missing
                        # #589: the framework emitted this cluster for this screen and the
                        # delivered page lost it — a build regression similarity cannot excuse.
                        if _is_player:
                            _s["chrome_incomplete"] = True
                        break
        except Exception:
            pass

        # recompute pass from the merged max scores (blocking, non-advisory, non-blank screens)
        # #768r — THE EXCLUSION IS WITHDRAWN, and the reason is worth more than the fix was.
        # I excluded `capture_missing` here on #542a's grounds ("a transient screen never drags
        # the persisted fidelity"), which would have moved r150's final round from 0.1727 to
        # 0.6400. #542's own test refused it, correctly: "a canonical page that fails capture is
        # NOT silently dropped — its 0.0 counts in the blocking average."
        #
        # Both positions are right about different causes, and the branch cannot tell them
        # apart. A page that never LOADS is the app's failure and must count, or the gate passes
        # a partial exam and ships an app with a dead page — the exact hole this whole session
        # has been closing. A page the HARNESS failed to photograph is not evidence of anything.
        # The `else` branch is "no shot, for any reason not otherwise classified", so excluding
        # it would have bought r150 a better number by reopening #542's hole for everyone.
        #
        # So: the flag and the honest deviation text STAY (they cost nothing and they are how
        # the next reader sees the difference), and the arithmetic does not change.
        _blocking_merged = [s for s in merged
                            if not s.get("advisory") and s.get("blank") is not True]
        # #589: a player screen that lost its framework-emitted control cluster fails the gate
        # regardless of its similarity score — see the inversion measured above the helper.
        _merged_passed = (all(_sim(s) >= min_similarity and not s.get("chrome_incomplete")
                              for s in _blocking_merged)
                          if _blocking_merged else bool(passed))
        # #542a: the recorded Part-A metric — the average over BLOCKING screens ONLY, so a
        # transient/advisory or duplicate-route screen never drags the persisted fidelity.
        _blocking_average = (round(sum(_sim(s) for s in _blocking_merged) / len(_blocking_merged), 4)
                             if _blocking_merged else 0.0)

        # #618 — THE RECORD CAN BE BETTER THAN THE CODE. #500 merges the BEST per-screen score
        # across captures, to stop a transient capture (env mid-rebuild → every page 0.00) from
        # clobbering a good verdict. That guard is right, but it does not distinguish a
        # transient zero from a REAL regression, so a lane that makes the frontend worse keeps
        # its historical best on the record.
        #
        # Measured over the arc, comparing `blocking_average` against the LAST live judgement
        # in the run log: the record is better than the live code in **24 of 39 runs**, mean
        # +0.056 and up to **+0.44** (r103: recorded 0.58, last live 0.14). Related: across the
        # 29 runs with two or more scored rounds, 19 improved but **10 ended WORSE than they
        # started** — the regressions are real, and this merge is what hides them.
        #
        # Deliberately NOT changing the merge or the gate: keeping the best is still the right
        # defence against a transient, and flipping it would newly fail runs on a capture
        # artefact. Record the live number ALONGSIDE it so the divergence stops being invisible.
        _live_blocking = [s for s in (results or []) if isinstance(s, Mapping)
                          and not s.get("advisory") and s.get("blank") is not True]  # #768r
        _live_average = (round(sum(_sim(s) for s in _live_blocking) / len(_live_blocking), 4)
                         if _live_blocking else None)
        # #621 — RECORD WHICH CODE STATE THIS SCORE BELONGS TO. #618 showed the persisted
        # number can beat the live one in 24 of 39 runs (up to +0.44), and that delivery almost
        # never comes from a PASS — only 1 of 40 verdicts ever passed, the rest release through
        # the bounded escape at whatever the last round left behind. Shipping the run's own BEST
        # state instead would need one thing the artifacts do not have: a join key. The commits
        # exist (codehub records 36 in r142, with sha/branch/author) and the scores exist; only
        # the link between a capture and the tree it scored is missing.
        #
        # Stamping HEAD costs a `rev-parse` and makes that selection possible later — the same
        # move as #611 (record what a future question will need). It changes no decision here.
        # (#930 hoisted the `rev-parse` above the merge, which needs it to name the archive.
        # Nothing else moved.)
        # #893: the judge contradicting ITSELF on identical input.
        #
        # #781 and #857 tell the judge not to report what it cannot point to in the reference.
        # Both are PROMPT rules — the "claim with no enforcer" shape this session has been mining,
        # and I fixed a prompt problem with a prompt. A content-matching enforcer is not the
        # answer either: the careful version of one reported 5 of 6 controls "present" by matching
        # word tokens across a 300 KB concatenation, and it is recorded as do-not-build.
        #
        # ★ What CAN be checked without vision is self-consistency. `code_state` (#621) stamps the
        # tree each capture scored, so two rounds at the SAME sha are the same input — and a
        # different `missing` list or a materially different score across them is the judge being
        # non-deterministic, not the app changing. That is exactly the over-claim signature:
        # an element "missing" in one round and not the next, with no code in between.
        #
        # Honest limit: only 7 of 119 corpus verdicts carry a `code_state`, so this cannot be
        # validated against history — #621 is recent. Every verdict from here on carries one, so
        # its first real signal is run 152. It is recorded in the verdict rather than acted on.
        _unstable_893 = []
        try:
            if _head_sha and _prior_code_state_893 == _head_sha:
                # ★ #929: over `screens` (THIS capture), not `merged`. #500's merge replaces a
                # collapsed screen's record with the prior one, so when the live capture scored
                # LOWER `_s` *is* `_pn` and `_delta` is 0 by construction — the detector could
                # only ever see instability in the direction where the judge grew kinder.
                # Executed control, same tree both ways:
                #     0.60 -> 0.00   judge_unstable_893: null      (silent)
                #     0.00 -> 0.60   judge_unstable_893: delta 0.6 (reported)
                # r154 is the live case: title_detail scored 0.60, then 0.00 twice on a capture
                # that is byte-identical between the two rounds and shows a complete, working
                # detail page (hero art, Play/+/like, meta row, synopsis, Episodes with a season
                # selector). A judge that scores that 0.00 is the noise this ticket exists to
                # name, and it was the one shape #893 could not report.
                for _s in screens:
                    _pn = prior_by_name.get(_s.get("name"))
                    if not isinstance(_pn, dict):
                        continue

                    def _miss(rec):
                        out = set()
                        for _dv in (rec.get("dimensions") or {}).values():
                            if isinstance(_dv, dict):
                                out |= {str(m) for m in (_dv.get("missing") or [])}
                        return out

                    _a, _b = _miss(_s), _miss(_pn)
                    _delta = abs(float(_s.get("similarity") or 0)
                                 - float(_pn.get("similarity") or 0))
                    if (_a != _b and (_a - _b or _b - _a)) or _delta >= 0.10:
                        _unstable_893.append({
                            "screen": _s.get("name"),
                            "appeared": sorted(_a - _b)[:5],
                            "vanished": sorted(_b - _a)[:5],
                            "score_delta": round(_delta, 3)})
            if _unstable_893:
                _LOG.warning(
                    "JUDGE UNSTABLE at an unchanged tree (%s): %d screen(s) got a different "
                    "verdict for the SAME code_state — %s. An item that appears and vanishes "
                    "with no code between rounds is judge noise, not a defect; weigh `missing` "
                    "accordingly (#893).",
                    str(_head_sha)[:8], len(_unstable_893),
                    ", ".join(str(u["screen"]) for u in _unstable_893[:4]))
        except Exception:
            _unstable_893 = []

        _verdict = {
            "passed": bool(passed) or _merged_passed, "min_similarity": min_similarity,
            "code_state": _head_sha,   # #621: the tree `blocking_average_live` scored
            "blocking_average": _blocking_average,  # #542a: Part-A over BLOCKING screens only
            # #618: what THIS capture scored, before the best-of merge
            "blocking_average_live": _live_average,
            # ★ #921: the scope label belongs on the DOCUMENT, which is this dict.
            #
            # #901 added it — to the dict `run_visual_fidelity` RETURNS, while
            # `_persist_verdict(..., coverage=_coverage, ...)` receives the unlabelled original.
            # Its own stated purpose was *"the artifact a human opens should not need the source
            # to disambiguate it"*, and `verdict.json` IS that artifact: **121 of 121 delivered
            # verdicts carry a coverage block and NONE carries the label.** r153's still reads
            # `"unjudged": ["browse_home_rows", "card_hover_preview", …]` directly above a
            # `screens` list where both of those carry scores — the exact contradiction #901 was
            # written to explain, unexplained.
            #
            # #903's shape, in my own ticket: a value computed correctly and handed to the wrong
            # object. Every one of #901's six assertions read the SOURCE, where the string does
            # exist, so nothing caught it until the file was driven (#920's sweep).
            "summary": summary,
            "coverage": {**(coverage if isinstance(coverage, dict) else {}),
                         "scope": "this round's captures; `screens` above is #500's merge across "
                                  "rounds, so a screen may carry a score here and still appear "
                                  "in `unjudged` — the two fields describe different sets"},
            "screens": merged,
        }
        if _unstable_893:
            _verdict["judge_unstable_893"] = _unstable_893
        if (_live_average is not None
                and _blocking_average - _live_average > 0.01):
            _verdict["record_exceeds_live_by"] = round(_blocking_average - _live_average, 4)
            _verdict["record_exceeds_live_note"] = (
                "the persisted score is the best-of-captures merge (#500); THIS capture scored "
                "lower, so the delivered frontend is currently worse than the recorded number")
        # #928: name them. The aggregate caveat above says the delivered app is worse than the
        # record without saying WHERE, and "worse by 0.20" reads like eight screens each a
        # little dimmer when the corpus shape is two screens collapsing to zero while the rest
        # hold. r154 is exactly that: title_detail 0.60 -> 0.00 and movies 0.62 -> 0.05, with
        # landing IMPROVING 0.40 -> 0.72 in the same round.
        if _below_928:
            _verdict["screens_below_record_928"] = sorted(_below_928)
        # #941: WHICH MILESTONE earned these numbers.
        #
        # `verdict.json` is a run-wide, best-of-captures merge (#500) and nothing resets it at a
        # milestone boundary — I checked: no unlink, no rmtree, no reset anywhere on this path. So
        # on a compound app the recorded fidelity can have been earned by a version of a page that
        # a later milestone replaced, and the document said nothing at all: the string "milestone"
        # appears ZERO times in r154's verdict, which spans M1 and M2.
        if milestone_label:
            _verdict["milestone"] = milestone_label
        # #641: computed BEFORE this round joins the ledger, so the comparison is against
        # earlier rounds only. Recommendation only — it changes no decision taken here.
        _better = better_state_available_641(vdir, _verdict.get("blocking_average_live"))
        if _better:
            # #698: SAY IT OUT LOUD. #641 computes this correctly — r146 validated it end to
            # end, picking round 5's commit with delta 0.0246 against a 0.02 margin — and then
            # wrote it into verdict.json, which NOTHING reads. Grepping the tree for
            # `better_state_available` / `better_state_note` finds only the three lines that
            # produce them, and the single reader of verdict.json is #500's best-of merge two
            # hundred lines above, which takes per-screen similarities and never looks at these
            # keys. So the recommendation reached no agent, no gate, no log and no human.
            #
            # Same shape as #691's silent skip and #696's invisible load failure: a correct
            # detector whose output is not observable is indistinguishable from one that never
            # ran. A WARNING costs nothing and changes no decision — the release policy question
            # (ship the best recorded round rather than the last) stays open on purpose, because
            # an earlier commit can score better VISUALLY while being functionally worse, and
            # that trade is not this function's to make.
            try:
                _LOG.warning(
                    "#641 better state available: an earlier capture of this run scored %.3f "
                    "(+%.3f) at commit %s, and the bounded escape ships the LAST round. "
                    "#618: 24 of 39 runs deliver worse than their own best.",
                    _better["score"], _better["delta"], str(_better["code_state"])[:12])
            except Exception:
                pass
            _verdict["better_state_available"] = _better
            _verdict["better_state_note"] = (
                "an earlier capture of this run scored %.3f (+%.3f) at commit %s — the bounded "
                "escape ships the LAST round, not the best one (#618: 24 of 39 runs deliver "
                "worse than their own best)" % (_better["score"], _better["delta"],
                                                str(_better["code_state"])[:12]))
        # #711: SAY WHEN THE GATING NUMBER HAS LEFT THE APP BEHIND.
        # Both numbers are already computed and written side by side; nothing compares them.
        # `blocking_average` is taken over `merged`, and #500 defines merged as the BEST
        # per-screen capture ever persisted ("keep prior when its similarity beats the current
        # one", ~200 lines above). verdict.json is rewritten every round, so the prior
        # accumulates a high-water mark and the gating number is monotonically non-decreasing
        # BY CONSTRUCTION. Both kept runs confirm it, and neither ever falls:
        #
        #   r146  gating 0.5809 0.5809 0.5855 0.6027 0.67 0.67 0.67 0.67 0.67
        #         live   0.5783 0.5450 0.5627 0.5982 0.6655 0.6409 0.6409 0.6409 0.6409
        #   r147  gating 0.655 0.655 0.655 0.668 0.688 0.700
        #         live   0.6333 0.5975 0.5558 0.5858 0.6400 0.3817
        #
        # #711r — RETRACTION OF THE CONSEQUENCE, kept above because the divergence itself is
        # real and worth warning about. What is WRONG is the sentence "A release authorised on
        # the former ships the latter", and the r146/r147 delivery claims built on it.
        #
        # The merged, monotonically non-decreasing number lives in the PERSISTED record —
        # verdict.json and rounds.jsonl, written by _persist_verdict. The DECISION path does not
        # read it. `_visual_fast_release_args` takes `gate.last_result`, which is the dict
        # RETURNED by run_visual_fidelity at its final `return`, and that dict carries
        # `blocking_average` = `_blocking_similarity_average(results)` — the CURRENT capture,
        # never merged — and `passed` un-merged as well. `_persist_verdict` receives `results`
        # and writes to disk; it does not mutate the returned dict.
        #
        # So: the RECORD is a high-water mark that diverges from the live capture, which matters
        # for anyone reading verdict.json to judge quality (I did, all session, and it is why
        # this warning is worth keeping). It is NOT what authorises a release.
        #
        # And the value that DOES authorise one is persisted nowhere — the current blocking-only
        # average appears in no artifact — so "what number released r146" cannot be recovered
        # from disk at all. That is the honest state, and it is why the delivery claims are
        # withdrawn rather than re-measured.
        #
        # ~~r146 DELIVERED at gating 0.67 while its screens sat at 0.6409 — under the 0.65 bar.~~
        # r147 is the extreme case and it ALSO delivered: its sixth and final round reads 0.700
        # against a live 0.3817 — though that live figure is itself DEPRESSED by #713, since four
        # of its twelve screens (browse_by_languages, genre_category, new_and_popular, player)
        # captured the landing page rather than their own and scored 0.05/0.08/0.05/0.03 for it.
        # Over the eight screens that were actually photographed the mean is 0.5463. The gap is
        # therefore 0.700 vs 0.5463 rather than vs 0.3817, still 0.15 and still under the 0.65
        # bar — the finding holds, but #711 and #713 COMPOUND here and must not be added up as
        # if they were independent. And
        # `codehub_releases.json` carries `1.0.0` — "Final delivery: delivery gate fully clear."
        # The release branch is cut at 93d1a3d, exactly ONE commit past round 6's 9e606251d and
        # differing only by four one-line frontend edits, so 0.3817 is what shipped. No round
        # ever judged the released commit itself. This is also the mechanism behind #618's unexplained corpus pattern
        # (24 of 39 runs deliver worse than their own best round): the gate's number IS the best
        # round, per screen, so release happens when the high-water mark crosses the bar.
        #
        # #500's max is deliberate and defensible — one flaky blank capture should not tank a
        # screen for the rest of the run — so it is NOT removed, and whether the gate should
        # read the live mean instead is a calibration decision of the same class as the 0.65 bar.
        # What was never defensible is that the divergence was SILENT while both numbers already
        # existed. Same disposition as #641 above: warn, change no decision.
        try:
            _g711, _l711 = _verdict.get("blocking_average"), _verdict.get("blocking_average_live")
            # #736: COMPARE LIKE WITH LIKE. #711's only condition was a >=0.05 gap between the
            # two averages; it never checked they cover the SAME screens, and often they do
            # not. Both averages correctly drop `blank is True`, so a blank capture shrinks the
            # LIVE denominator while the gating one keeps every screen's best-ever score — and
            # a near-total blackout then leaves a 2-screen mean facing a 12-screen mean. That
            # difference is COMPOSITION, not divergence. r148 round 4: gating 0.6190 over 12
            # screens vs live 0.4250 over the only two that captured (landing 0.45 + login 0.40
            # -- exactly their mean), on a round the framework had ALREADY labelled
            # `[blank capture: ...] - attempt refunded`. Across every log in the corpus #711 has
            # fired 2 times and BOTH are this artefact: a 100% false-positive firing history.
            #
            # No tuned constant is needed (same disposition as #656): restrict the gating mean
            # to the screens this capture actually scored. A real divergence still fires —
            # #713's r147 case is four routes falling THROUGH to the landing page, which are
            # captured and scored, so they stay in both populations.
            _names736 = {s.get("name") for s in _live_blocking}
            _cmp736 = [s for s in _blocking_merged if s.get("name") in _names736]
            _g736 = (round(sum(_sim(s) for s in _cmp736) / len(_cmp736), 4)
                     if _cmp736 else None)
            if (isinstance(_g736, (int, float)) and isinstance(_l711, (int, float))
                    and _g736 - _l711 >= 0.05):
                _LOG.warning(
                    "#711 the gating average has left the app behind: over the %d screen(s) "
                    "THIS capture scored, best-ever %.4f vs live %.4f (gap %.4f). The gating "
                    "number is #500's best-ever-per-screen and never falls; the live one is "
                    "this capture, so the RECORD on disk overstates the app. #711r: that is "
                    "NOT what authorises a release — the release path reads the returned "
                    "dict, i.e. the current capture — and the emitted text used to say it "
                    "did, which was measured false and is why this sentence now says this. "
                    "(#736: run-wide the two are %.4f vs %.4f over %d screen(s); compared "
                    "like-for-like above, because a blank capture shrinks the live population "
                    "and the rest of the gap would be composition, not divergence.)",
                    len(_cmp736), _g736, _l711, _g736 - _l711,
                    _g711, _l711, len(_blocking_merged))
            # ★ #917: and say something when there is NOTHING to compare.
            #
            # #736 restricted the comparison to the screens THIS capture scored, which was right
            # — both its firings were composition artefacts. But a TOTAL blackout empties that
            # population, so `_cmp736` is `[]`, `_g736` is None, and the guard that exists to say
            # "the record on disk overstates the app" says nothing at all. Measured as a clean
            # gradient on a planted prior of four screens at 0.80:
            #
            #     blank 0/4 → warns (over 4)    blank 2/4 → warns (over 2)
            #     blank 1/4 → warns (over 3)    blank 3/4 → warns (over 1)
            #     ★ blank 4/4 → SILENT, and the persisted verdict still reads passed=True
            #
            # The guard degraded exactly as the situation got worse, and went quiet at its worst.
            # That is r148's fourth mechanism in the REPORTING path — #500's high-water merge
            # keeps every screen's best-ever score, so a totally blacked-out round leaves a
            # verdict.json that still passes and no line anywhere saying the capture was empty.
            #
            # An empty population is not "nothing to compare": it is "everything is gone", which
            # is the loudest reading available. Fifth appearance this session of an empty
            # container answered as a fact (#902, #907, #908, #916).
            #
            # Reports only, like #711/#736 — the release path reads the returned dict, not this
            # file, and #737/#750 already handle the escape side.
            if not _cmp736 and _blocking_merged and (results or []):
                _LOG.error(
                    "TOTAL BLACKOUT AGAINST A RECORD THAT STILL PASSES: this capture scored NO "
                    "blocking screen, so #736's like-for-like comparison has an empty population "
                    "and #711 above is silent. The persisted verdict still shows %d screen(s) "
                    "averaging %.4f with passed=%s — #500's best-ever-per-screen merge never "
                    "falls, so the record on disk cannot show this round at all. Read the LIVE "
                    "per-screen scores, not verdict.json (#917).",
                    len(_blocking_merged), _blocking_average, bool(_verdict.get("passed")))
        except Exception:
            pass
        # #713: TWO SCREENS THAT CAPTURED THE SAME IMAGE DID NOT BOTH RENDER.
        # r147 is the worked example and it cost 0.26 of live fidelity in one round. Its final
        # round renamed four routes in App.jsx (/new-and-popular -> /new, /genre/:id ->
        # /browse/genre/:genreId, /browse-by-languages -> /browse/languages, plus a new
        # /watch/:titleId). The capture still navigated to the OLD paths, React Router matched
        # nothing, and all four fell through to the landing page:
        #
        #     browse_by_languages.png, genre_category.png, new_and_popular.png, player.png
        #     and landing.png are ONE file, md5 02a3e3577bf5
        #
        #     browse_by_languages 0.45 -> 0.05    new_and_popular  -> 0.05
        #     genre_category      0.60 -> 0.08    player      0.55 -> 0.03
        #     blocking_average_live 0.6400 -> 0.3817, and #500's merge ROSE 0.688 -> 0.70
        #
        # so the run shipped its worst capture while the recorded number climbed. #641/#698
        # flagged the symptom (delta 0.2583, the largest in the corpus) but nothing named the
        # CAUSE, and a near-zero score is indistinguishable from a page that is merely bad.
        #
        # The trigger, stated only as far as it is proven. ~~routes renamed after the capture
        # list was built~~ is WRONG and was checked: `known_routes` is re-parsed out of
        # App.jsx on every call (`re.findall(r'<Route\s+path=...')` in run_visual_fidelity),
        # so the list is never stale. What IS true is that the route list comes from SOURCE
        # while the browser hits the SERVED app, so any lag between the two — a bundle not
        # rebuilt since the rename — makes the new paths miss and fall to the catch-all.
        # Which of those it was in r147 is not decided here; the detector does not need to
        # know, and guessing it is how the first version of this comment got it wrong.
        #
        # Byte-identical captures are the cheap tell: distinct screens cannot legitimately
        # produce the same PNG. Hashing what is already on disk costs one read per screen and
        # turns an invisible cliff into "these routes did not resolve".
        # Every similarity computed from a shared capture measures that page, not those
        # screens.
        #
        # Corpus scale, and NOT solved history: 103 of the 127 runs with gate screenshots
        # contain a byte-identical group — 71 of 84 before r100, 32 of 43 after. The
        # extremes are total: r37 captured ONE image for 12 of its 13 screens, r48 11 of
        # 13, r6 11 of 12.
        #
        # Ruled out first: `_concrete_capture_route` DOES substitute params
        # (`/browse/genre/:genreId` -> `/browse/genre/1`), so this is not a
        # literal-placeholder navigation. Checked and refuted before this was written.
        try:
            import hashlib as _hl713
            _by713: Dict[str, List[str]] = {}
            for _r713 in (results or []):
                _n713 = str((_r713 or {}).get("name") or "")
                _f713 = vdir / f"{_n713}.png"
                if not _n713 or not _f713.is_file():
                    continue
                _h713 = _hl713.md5(_f713.read_bytes()).hexdigest()
                _by713.setdefault(_h713, []).append(_n713)
            # #718: SPLIT THE EXPECTED SHARING FROM THE DEFECT, using the route already in hand.
            # #713's message says "their routes did not resolve", and for the most common group
            # in the corpus that is simply false. Four reference screens map to ONE route:
            #
            #     browse_home  browse_home_rows  card_hover_preview  account_menu   -> /browse
            #
            # so identical captures are EXPECTED there — it is one page — and the sharing rate
            # shows it: browse_home_rows 53 of 53 runs, card_hover_preview 53 of 57,
            # account_menu 19 of 23. They are INTERACTION STATES (a scrolled view, a hovered
            # card, an opened menu), reachable only by acting on /browse, and the capture only
            # navigates. So the gate photographs the base page and scores it against a reference
            # showing the overlay: card_hover_preview's median is 0.300 and its MAXIMUM across 54
            # appearances is 0.55, never once reaching the 0.65 bar, and it structurally cannot.
            #
            # #595 already demotes reference frames with TWO OR MORE open overlays ("not a state
            # the app can be in"); a single overlay falls under that threshold, which is why
            # these were never caught. Removing all three from the average is worth +0.0208 on
            # the mean run and +0.1785 at the extreme.
            #
            # AND IT BLOCKS. `card_hover_preview` is a BLOCKING screen in 36 of its 54
            # appearances, and across those 36 its maximum similarity is 0.40, its median 0.30,
            # and it clears the 0.65 bar exactly ZERO times. So in 36 runs a screen the gate
            # cannot photograph was gating the release. (`account_menu` is advisory in all 22 of
            # its appearances — handled correctly — and `browse_home_rows` blocks in 22 of 52.)
            #
            # That reframes #711 and #712 rather than merely adding to them. #500's high-water
            # merge, #558's fast-release and the plateau escapes are not only leniency: they are
            # what lets a run finish at all when part of the measurement is structurally broken.
            # Remove every escape and those 36 runs could never release on the gate's own terms.
            # Which means the calibration question — should the gate read the live mean — cannot
            # be answered without also deciding what to do about screens that can never pass.
            #
            # Not demoted here — an overlay screen is real product and dropping it loses
            # coverage, the same trade #713 declined to make. What changes is that the two cases
            # stop sharing one wrong sentence.
            _routes713 = {}
            for _r713 in (results or []):
                _rn = str((_r713 or {}).get("name") or "")
                if _rn:
                    _routes713[_rn] = str((_r713 or {}).get("route") or "")
            # #723: SAY WHEN THE CAPTURES ARE ALL DISTINCT. Fourth instance of the same shape
            # (#691 silent skip, #696 invisible failure, #712 dead branch, #715 two warnings and
            # no third), and this one bit while I was reading r148: I concluded "no duplicate
            # groups" from #713's SILENCE, which also covers "the hashing raised" and "results
            # was empty". The conclusion happened to be right only because I hashed the PNGs
            # myself as well. A detector guarding the validity of 26% of all fidelity scores
            # must not require a second opinion to be believed.
            if not [g for g in _by713.values() if len(g) > 1]:
                _LOG.info("#713 all %d screen captures are distinct — no shared-page scoring "
                          "this pass.", len(_by713))
            for _h713, _names713 in _by713.items():
                if len(_names713) < 2:
                    continue
                _rs713 = {_routes713.get(n, "") for n in _names713}
                if len(_rs713) == 1 and next(iter(_rs713)):
                    _LOG.warning(
                        "#713b %d screens share ONE route (%s) and therefore one capture: %s. "
                        "This is expected — they are interaction states of a single page (a "
                        "scroll, a hover, an opened menu), reachable only by acting on it, and "
                        "the capture only navigates. Their scores measure the base page against "
                        "a reference showing the interaction, so a low number here is the "
                        "GATE's limitation, not the app's.",
                        len(_names713), next(iter(_rs713)), ", ".join(sorted(_names713)))
                    continue
                _LOG.warning(
                    "#713 %d screens captured the SAME image (md5 %s): %s. Distinct screens "
                    "cannot render identically — their routes did not resolve and the browser "
                    "fell through to a common page. Their similarity scores measure that page, "
                    "not those screens; check whether a route was renamed after the capture "
                    "list was built.",
                    len(_names713), _h713[:12], ", ".join(sorted(_names713)))
                _verdict.setdefault("identical_captures_713", []).append(
                    {"md5": _h713, "screens": sorted(_names713)})
                # #714: and STOP THE PHANTOM REMEDIATION. Detection alone still leaves the
                # lane a to-do list about a page that was never photographed. Measured over the
                # corpus: screens inside a duplicate group carry 17.5 deviations each against
                # 15.3 for real ones — scored against someone else's page, nearly everything
                # looks wrong — so 5835 of 21550 deviations (27%) describe an uncaptured screen.
                #
                # `remediation_text` already honours `scope_excluded_screens` (#565 uses it to
                # drop out-of-milestone pages), and it reads the list from the verdict at
                # CONSUMPTION time. Appending here therefore suppresses exactly the phantom
                # entries and touches no score: the averages, the pass/fail and the 0.65 bar are
                # computed earlier and are byte-identical. Deliberately NOT demoting to advisory
                # — that would change gating arithmetic, and the evidence does not yet say what
                # the right gate behaviour is when a quarter of the exam did not render.
                #
                # One canonical screen per group is KEPT scorable, as #542a does: the group did
                # photograph SOMETHING, and dropping every member would hide that too.
                try:
                    _grp713 = sorted(_names713)
                    _ex713 = _verdict.setdefault("scope_excluded_screens", [])
                    for _nm713 in _grp713[1:]:          # keep _grp713[0] scorable
                        if _nm713 not in _ex713:
                            _ex713.append(_nm713)
                except Exception:
                    pass
        except Exception:
            pass
        (vdir / "verdict.json").write_text(json.dumps(_verdict, indent=2, default=str),
                                           encoding="utf-8")
        _append_round_record_640(vdir, _verdict, results)
    except Exception:
        pass


def best_recorded_round_641(vdir: Any) -> Optional[Dict[str, Any]]:
    """#641 — the round that scored best, from #640's ledger. None until one exists.

    #640 started recording (code_state, live score) per round; this is the SELECTION on top of
    it, and it is a pure function over the ledger, so it is written and tested now rather than
    deferred with the data. Only the data needs a run — the logic does not, and saying "this
    needs a run" about a pure function was the last hiding place of a deferral I have now been
    wrong about four times (#630, #638, #639, #640).

    Rules, all of them consequences of what the ledger means:
      * rank on `blocking_average_live` — THIS capture's score. `blocking_average` is #500's
        best-of-captures merge across rounds, so ranking rounds by it compares each round to a
        mixture that includes the others.
      * a round with no `code_state` is unusable: there is no tree to go back to.
      * ties go to the EARLIER round — it has survived longer and later rounds may carry
        unrelated regressions.
    """
    try:
        p = Path(vdir) / "rounds.jsonl"
        if not p.is_file():
            return None
        best = None
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict) or not row.get("code_state"):
                continue
            score = row.get("blocking_average_live")
            if not isinstance(score, (int, float)):
                continue
            if best is None or score > best.get("blocking_average_live", float("-inf")):
                best = row
        return best
    except Exception:
        return None


def better_state_available_641(vdir: Any, this_live: Any,
                               margin: float = 0.02) -> Optional[Dict[str, Any]]:
    """The recommendation: a recorded round beat what is about to ship, by more than `margin`.

    #618 measured that **24 of 39 runs deliver a state worse than their own best**, by up to
    +0.44 — the bounded escape releases whatever the last round happened to leave. Returns
    ``{code_state, score, delta}`` when going back is justified, else None.

    `margin` exists because the judge is not exactly repeatable: a hair's-breadth difference is
    noise, and reverting on noise would churn the tree for nothing. It is a RECOMMENDATION —
    computing it changes no decision here; whether the release acts on it is a separate call
    that wants one run's ledger behind it.
    """
    try:
        if not isinstance(this_live, (int, float)):
            return None
        best = best_recorded_round_641(vdir)
        if not best:
            return None
        score = best.get("blocking_average_live")
        if not isinstance(score, (int, float)) or score - this_live <= margin:
            return None
        return {"code_state": best.get("code_state"), "score": score,
                "delta": round(score - this_live, 4)}
    except Exception:
        return None


# #932: every finding `_persist_verdict` can add to the verdict, carried into the append-only
# ledger. Kept as one declared set so a finding added later is either listed here or caught by
# `test_every_verdict_finding_is_carried_932`, which walks the function's AST for the keys it can
# grow — a hand-written line per finding is how #900 ended up carrying exactly one of eight.
_ROUND_FINDINGS_932 = (
    "judge_unstable_893",         # the judge contradicting itself on an unchanged tree
    "identical_captures_713",     # distinct screens that photographed the same page
    "screens_below_record_928",   # screens whose live capture fell under their recorded score
    "record_exceeds_live_by",     # #711's aggregate divergence
    "record_exceeds_live_note",
    "better_state_available",     # #641: an earlier round of this run scored higher
    "better_state_note",
    "scope_excluded_screens",     # #714/#565: screens whose remediation is suppressed
)


def _append_round_record_640(vdir: Any, verdict: Dict[str, Any],
                             results: List[Dict[str, Any]]) -> None:
    """#640 — one line per capture round, so "which tree scored best" becomes answerable.

    #618 measured that **24 of 39 runs ship a state worse than their own best** (up to +0.44),
    and #621 stamped `code_state` on the verdict so a score could be tied to a commit. Neither
    is enough, and testing the claim rather than restating it is what showed why:

      * `round -> commit` IS recoverable for past runs — the capture history is written as
        `design/visual_gate/history/HHMMSS_<screen>.png`, and codehub records every commit with
        `created_at`. That join was never the missing piece.
      * `round -> score` is recorded NOWHERE. `verdict.json` is a single file OVERWRITTEN each
        round and it holds the #500 best-of merge, not this capture; the history holds images
        only; the run log prints coverage and milestone-scope but no similarity. So of 40 kept
        verdicts, the per-round series exists for zero of them.

    `code_state` alone therefore could not have made the selection decidable on the next run
    either — the score it needs to be compared against would still be gone by the time the run
    ended. This appends the pair, plus the per-screen live scores, before anything overwrites it.

    Append-only JSONL, best-effort, never raises: a corrupt or unwritable record must not fail
    the gate that produced it.
    """
    try:
        row = {
            "at": time.time(),
            "code_state": verdict.get("code_state"),
            "blocking_average": verdict.get("blocking_average"),
            "blocking_average_live": verdict.get("blocking_average_live"),
            "passed": verdict.get("passed"),
            "min_similarity": verdict.get("min_similarity"),
            "live": {str(s.get("name")): s.get("similarity")
                     for s in (results or []) if isinstance(s, dict) and s.get("name")},
            # #941: and on every ROUND — the half that matters more. rounds.jsonl is the only
            # append-only record of the run, it spans every milestone, and without this a reader
            # cannot tell M1's rounds from M2's. r154's ledger has 12 rounds across two
            # milestones and no way to split them.
            **({"milestone": verdict["milestone"]} if verdict.get("milestone") else {}),
        }
        # #900: carry #893's instability finding into the APPEND-ONLY record.
        #
        # ★ #893 wrote `judge_unstable_893` only into verdict.json, which `_persist_verdict`
        # OVERWRITES every round — so a detection could be erased by the very next round. That is
        # #500's evidence-erasure shape, committed by the detector built to expose the judge's
        # inconsistency. r153 makes the cost concrete: 12 rounds happened and exactly ONE verdict
        # file survives, so any instability found in rounds 1-11 would be unrecoverable.
        #
        # `rounds.jsonl` is already appended here, one line per round, and r153 proves it retains
        # what verdict.json loses: 11 distinct code_states over 12 rounds, including the repeat
        # (41b11425e7 x2) that gave #893 its only real opportunity — where it correctly stayed
        # silent, because both rounds scored identically (merged 0.6771, live 0.627, delta 0.0000).
        # #932: #900's remedy applied to EVERY finding on the document, not one of them.
        #
        # Its reasoning above is general — "a detection could be erased by the very next round" —
        # and every other finding sits on the same overwritten file. r154 proved it while this was
        # being written: `identical_captures_713` recorded `login` and `movies` capturing the same
        # image in round 2, `movies` recovered in round 3, and the finding vanished from the only
        # surviving verdict. The run's history now says it never happened.
        #
        # Carried as a declared set rather than a hand-written line each, because the failure mode
        # here is a NEW finding quietly not being carried; the test asserts every key the verdict
        # can grow is either in this set or explicitly not a finding.
        for _k932 in _ROUND_FINDINGS_932:
            if verdict.get(_k932):
                row[_k932] = verdict[_k932]
        # #933: WHY a screen scored zero, in the record that survives the round.
        #
        # Every 0.0 this module produces is a JUDGE failure and each one writes its cause as a
        # deviation — "judge returned no JSON", "judge JSON unparseable", "judge call failed: …",
        # #766's non-verdict. #767 stamped `raw_judge_reply` onto the record for exactly this
        # question, and said why: *"Only the raw text can say, and one round from now it will be
        # gone."* It goes into the screen record — which #500's merge discards whenever the screen
        # COLLAPSED, i.e. precisely when the question is asked.
        #
        # r154: `title_detail` scored 0.00 for four consecutive rounds across three code states,
        # on a capture showing a complete working detail page (hero art, Play/+/like, meta row,
        # synopsis, Episodes with a season selector) against a reference that is unmistakably the
        # same screen. Round 1 scored the same page 0.60. Nothing on disk can say what the judge
        # replied in rounds 2-5.
        #
        # `results` is the LIVE list and is already in hand here. Only exact zeros are carried —
        # that is the value every judge-failure path returns, so the rule needs no threshold.
        _zero933: Dict[str, Any] = {}
        for _s933 in (results or []):
            if not isinstance(_s933, dict):
                continue
            _n933 = str(_s933.get("name") or "")
            try:
                _sim933 = float(_s933.get("similarity") or 0.0)
            except Exception:
                continue
            if not _n933 or _sim933 != 0.0:
                continue
            _devs933 = [str(d) for d in (_s933.get("deviations") or []) if str(d).strip()]
            _zero933[_n933] = {
                "why": _devs933[0][:200] if _devs933 else None,
                "judge_error": bool(_s933.get("judge_error")),
                "blank": _s933.get("blank"),
                "capture_missing": _s933.get("capture_missing"),
                "capture_error": _s933.get("capture_error"),      # #935
                "raw_judge_reply": str(_s933.get("raw_judge_reply") or "")[:200] or None,
            }
        if _zero933:
            row["zero_reasons_933"] = _zero933
        # #937: the CAPTURE FINGERPRINT per screen, so "did anything actually change?" is a query.
        #
        # r154 spent 12 rounds at a flat 0.5655 across five distinct code_states. Answering why
        # took: md5-ing `history/` (which only exists because #141b caps it at 500 files),
        # counting build events in `podman images` to refute a stale bundle, and finally
        # `git log` on the component App.jsx actually routes to — which had been edited TWICE in
        # 148 minutes, the second time by 24 bytes. The one number that would have started that
        # investigation is the one #142 already computes to key its verdict cache and then drops.
        #
        #     login 1 distinct image across 12 captures · landing 2 · games 2 · browse_home 3
        #
        # A plateau where the pixels are IDENTICAL is a different defect from one where they
        # change and the score does not, and the ledger could not tell them apart.
        try:
            import hashlib as _hl937
            _fp937: Dict[str, str] = {}
            for _s937 in (results or []):
                if not isinstance(_s937, dict):
                    continue
                _n937 = str(_s937.get("name") or "")
                _p937 = _s937.get("screenshot")
                if not _n937 or not _p937:
                    continue
                _f937 = Path(str(_p937))
                if _f937.is_file():
                    _fp937[_n937] = _hl937.md5(_f937.read_bytes()).hexdigest()[:12]
            if _fp937:
                row["capture_md5_937"] = _fp937
        except Exception:
            pass
        with open(Path(vdir) / "rounds.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


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
        # #662: ORDER BEFORE THE CAP. The 10-line window was filled in list order, and
        # `accent_missing` is ~34% of all measurements — so it crowded out the deviations that
        # carry an actual measured `distance`, which is what this section promises ("facts").
        # Measured: 498 of 1248 screens (40%) had at least one background deviation hidden by
        # the cap; 1881 of 9132 (21%) never reached the lane. Background-first, then widest gap
        # first, recovers 1012 of them (+14%) — a REORDER, so nothing is dropped that the cap
        # was not already dropping, and no tuned constant is introduced.
        _ordered = sorted(devs, key=lambda m: (m.get("kind") != "background",
                                               -(m.get("distance") or 0)))
        for d in _ordered[:10]:
            if d.get("kind") == "accent_missing":
                # #662: this one is NOT the same grade of fact as a background diff, and saying
                # so costs a clause. Its `expected` is sampled from a region of the REFERENCE
                # IMAGE, and on a nav or hero that region often shows photographic content
                # through transparent chrome. Across the corpus 64% of these accents (2959 of
                # 4618) are not attributable to the design's own measured palette, their median
                # saturation is 0.56 against the brand accent's 0.96, and the hue split is
                # green 32% / gold 27% / purple 23% / blue 15% / red 4% — for a product whose
                # accent is red. Filtering them on colour was tried and rejected: the cleanest
                # cut still lost 27% of the genuine red ones.
                lines.append(
                    f"  · {d.get('component')}: {d.get('hue')} accent MISSING — the "
                    f"reference measures {d.get('expected')} in this region; restore it IF it "
                    "is chrome (semantic color loss: unread-dots/badges/buttons going gray). "
                    "This sample can pick up artwork showing through transparent chrome — "
                    "ignore it when the region is a poster/backdrop rather than a control")
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


# #660: a judge "fix" that says nothing to do.
#
# Three conditions, and the last two exist because the first one alone was WRONG. Anchoring on
# "none|no" and allowing word characters to the end matched 309 strings — but 14 of them carry
# a real instruction after a continuation word, and dropping those would have silenced actual
# remediation:
#
#     'No changes needed BEYOND adding missing labels.'
#     'No change needed BEYOND removing the amber hero image dominating the top.'
#     'No major change needed ONCE hero image renders correctly.'
#     'None major BEYOND adding Kids gradient tile.'
#
# So: starts with none/no, carries no continuation marker, and is short. Verified by listing
# every string the filter drops across the corpus and reading all 27 distinct shapes — 295
# instructions, none of them actionable.
_NOOP_FIX_CONT_660 = re.compile(r"\b(beyond|once|except|apart|aside|besides|other than|but)\b",
                                re.I)
_NOOP_FIX_HEAD_660 = re.compile(r"^(none|no)\b[\w\s,]*\.?$", re.I)


_DEMANDS_INTERACTION_855 = re.compile(r"\bhover\b|\bon mouse|mouseover|:hover")


def _unsatisfiable_by_static_capture_855(text: Any, screen_name: Any) -> bool:
    """#855: does this deviation demand an interaction state the capture can never show?

    #542a already excludes TRANSIENT screens by NAME (`card_hover_preview` and friends) from
    scoring, because a static route capture cannot open an overlay. It does not help when the
    screen is an ordinary catalog page whose REFERENCE IMAGE happens to depict a card mid-hover:
    the judge writes "Missing hover preview card with play/add/like actions" against `my_list`,
    `remediation_text` hands that to the lane as a concrete instruction, the lane builds a hover
    card, the next static capture still shows no hover state, and the deviation recurs. That is
    #566z's unsatisfiable-expectation engine at the visual gate instead of the chain gate.

    Measured over the corpus: **188 of 7763 deviation lines (2.4%)**, concentrated on `my_list`
    (99) and `browse_by_languages` (80) — 112 run-screens, and the largest semantic deviation
    class by run count.

    Dropping is safe by the same test #660 used for no-op fixes: **0 screens have ALL of their
    deviations in this shape, and 0 BLOCKING screens do** — so no screen is ever left without an
    actionable line. It is dropped from the INSTRUCTIONS only; the verdict record keeps it, and
    the caller says how many it dropped (an erased finding is #791's defect).

    A deviation on a screen that IS transient/overlay is kept: there the overlay genuinely should
    render (#509 gives those screens an interaction capture), and 39 of the hover entries are on
    `card_hover_preview` itself."""
    t = str(text or "").lower()
    if not _DEMANDS_INTERACTION_855.search(t):
        return False
    return not _screen_is_transient({"name": screen_name})


def _is_noop_fix_660(text: str) -> bool:
    t = (text or "").strip()
    return (bool(_NOOP_FIX_HEAD_660.match(t))
            and not _NOOP_FIX_CONT_660.search(t)
            and len(t) <= 40)


def _component_file_938(project_dir: Any, route: Any) -> Optional[str]:
    """The source file that renders ``route``, as a repo-relative path, or None.

    Two hops, both already owned by the framework: `frontend_audit._route_element` reads App.jsx's
    routing table for the component IDENTIFIER (#597 calls that wiring "the source of truth for
    what renders this page"), and App.jsx's own import line maps that identifier to a file.

    Returns None rather than a guess. A remediation task that names the WRONG file is worse than
    one that names none — the lane would edit it, see no score change, and conclude the judge is
    broken, which is the reasoning error #934 caught me making from the other end.
    """
    try:
        if not project_dir or not route:
            return None
        src = Path(str(project_dir)) / "app" / "frontend" / "src"
        app = src / "App.jsx"
        if not app.is_file():
            return None
        text = app.read_text(encoding="utf-8", errors="replace")
        from .frontend_audit import _route_element
        ident = _route_element(text, str(route))
        if not ident:
            return None
        m = re.search(r"import\s+(?:\{[^}]*\b" + re.escape(ident) + r"\b[^}]*\}|"
                      + re.escape(ident) + r")\s+from\s+['\"]([^'\"]+)['\"]", text)
        if not m:
            return None
        rel = m.group(1)
        if not rel.startswith("."):
            return None                      # a package import renders nothing the lane can edit
        base = (src / rel).resolve()
        for cand in (base, base.with_suffix(".jsx"), base.with_suffix(".tsx"),
                     base / "index.jsx", base / "index.tsx"):
            if cand.is_file():
                return str(cand.relative_to(Path(str(project_dir)).resolve()))
        return None
    except Exception:
        return None


def remediation_text(result: Mapping[str, Any], output_dir: Any = None,
                     latched: Optional[set] = None,
                     prev_live: Optional[float] = None,
                     this_live: Optional[float] = None,
                     round_no: Optional[int] = None) -> str:
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
    # #619 — TELL THE LANE WHETHER ITS LAST CHANGE HELPED. #617 showed every round is labelled
    # "attempt 1"; #618 showed the persisted score keeps the best-of-captures merge, so a
    # regression never reaches the record. Between them the lane had no way to learn from its
    # own previous round — and it shows: across the 29 runs with two or more scored rounds,
    # 19 improved but **10 ended WORSE than they started** (r103 -0.40 over 12 rounds), at a
    # mean of only +0.003 per round.
    #
    # The gate already knows both numbers by the time it writes this task. Leading with the
    # delta costs nothing and is the one piece of feedback a blind retry loop lacks.
    # #620 — NAME THE SCREENS THE LAST ROUND BROKE. #129 keeps a latched (already-passed)
    # screen OUT of the fix list so the lane is not told to re-work it — but that cannot stop
    # the lane BREAKING it while fixing another screen, because they share components (a nav
    # bar, a card). Tracking every screen that left the below-bar list and later came back:
    # **113 real fall-backs across 12 runs** (scores like 0.03 / 0.05 / 0.42), against only 32
    # that are the 0.00 env-down captures #500's merge exists to absorb. #619 tells the lane
    # the average moved; it never said WHICH screen it lost, and a latched screen is exactly
    # the one nothing else in the task body mentions.
    _broken = sorted(
        f"{r.get('name')} ({float(r.get('similarity') or 0.0):.2f})"
        for r in (result.get("screens") or [])
        if isinstance(r, Mapping) and r.get("name") in latched
        and isinstance(r.get("similarity"), (int, float))
        and float(r["similarity"]) < float(result.get("min_similarity") or 0.65))
    _regressed = ""
    if _broken:
        _regressed = ("⚠ COLLATERAL DAMAGE — these screens had already cleared the bar and are "
                      "below it again: " + ", ".join(_broken) + ". They are NOT in the fix list "
                      "below (#129 keeps a passed screen out of it), so whatever broke them was "
                      "a side effect — most often a shared component. Check that first.\n\n")

    _head = ""
    if isinstance(prev_live, (int, float)) and isinstance(this_live, (int, float)):
        _d = this_live - prev_live
        _r = f"Round {round_no}. " if round_no else ""
        if _d < -0.01:
            _head = (f"{_r}⚠ YOUR LAST ROUND MADE THIS WORSE: the blocking average went "
                     f"{prev_live:.2f} → {this_live:.2f} ({_d:+.2f}). Before changing anything "
                     f"else, look at what that round touched and consider reverting it — the "
                     f"screens listed below are scored on the CURRENT code.\n\n")
        elif _d > 0.01:
            _head = (f"{_r}Your last round helped: blocking average {prev_live:.2f} → "
                     f"{this_live:.2f} ({_d:+.2f}). Keep going in the same direction.\n\n")
        else:
            _head = (f"{_r}Your last round moved the blocking average by {_d:+.2f} — "
                     f"effectively nothing. Repeating the same kind of change is unlikely to "
                     f"help; try a different dimension from the list below.\n\n")
    # #565: screens the caller (a NON-FINAL milestone) demoted as out-of-milestone-scope —
    # never file frontend remediation for a LATER milestone's pages. Empty on the
    # final/single-milestone path, so that remediation body is byte-identical to before.
    _scope_excluded = {str(n) for n in (result.get("scope_excluded_screens") or [])}
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
    # #680: ORDER WORST-FIRST, THEN CAP — the #662 shape, one level up.
    # This loop walked `result["screens"]` in judge order and emitted EVERY blocking screen in
    # full. The resulting task description is the largest single object the system produces:
    #
    #     447 visual remediation tasks, median 8 screens and 57,815 chars, max 15 and 126,047
    #     432 of 447 exceed 20 KB and hold 99% of their 28.2M chars
    #     `description` is 77.8% of ALL task bytes (31.6M of 41M across 12836 tasks)
    #
    # That description is what #679 traced check_inbox back to — 187.3M chars, 46.7% of the
    # 401M the per-run tool_io_rollup tables account for — and it is delivered
    # whole to the lane. #649 already measured the dilution inside one screen (mean 6.4 fix
    # instructions, and the holistic score tracks only the WEAKEST dimension); a median task
    # stacks eight of those.
    #
    # Capping loses nothing because remediation is RE-ISSUED every round — 447 tasks over ~100
    # runs, ~4.5 per run — so a screen that does not fit this round leads the next one. What
    # would lose work is capping WITHOUT ordering, which is why the sort comes first: the
    # screens furthest below the bar are the ones the gate is waiting on.
    #
    # Four is half the median screen count and halves the payload (51% of bytes, measured over
    # the same 447), and the remainder is named with its scores rather than silently dropped.
    _REMEDIATION_SCREEN_CAP_680 = 4
    _eligible = [r for r in (result.get("screens") or [])
                 if not (r.get("passed") or r.get("name") in latched
                         or r.get("name") in _scope_excluded)]
    _eligible.sort(key=lambda r: float(r.get("similarity") or 0.0))
    _deferred = _eligible[_REMEDIATION_SCREEN_CAP_680:]
    for r in _eligible[:_REMEDIATION_SCREEN_CAP_680]:
        lines.append(f"\n## {r['name']}  (route {r['route']}, similarity {r['similarity']:.2f})")
        # #938: NAME THE FILE. The header gave a screen name and a route, and left resolving that
        # to a component up to the lane.
        #
        # r154 is what that costs. Twenty frontend rebuilds, fifty commits touching twelve
        # frontend source files, twelve capture rounds — and `components/LoginPage.jsx`, the file
        # `App.jsx` actually routes `/login` to, was edited TWICE in 148 minutes, the second time
        # by 24 bytes. `login` produced ONE distinct image across all twelve captures and sat at
        # 0.50 the whole run. The loop was working hard somewhere else.
        #
        # App.jsx is the source of truth for what renders a route (#597's own words, in
        # `_route_element`), and the framework has parsed it since #566e. Printing the path costs
        # a file read and removes an inference the lane was silently getting wrong. Omitted, never
        # guessed, when it cannot be resolved — a wrong path is worse than none.
        _f938 = _component_file_938(output_dir, r.get("route"))
        if _f938:
            lines.append(f"   edit: {_f938}   ← what App.jsx routes {r['route']} to")
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
            # #797: the other two measured axes the repair round never saw.
            lines.extend(_style_lines_797(_ds, str(r.get("name") or "")))
            lines.extend(_copy_lines_797(_ds, str(r.get("name") or "")))
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
        # #649 — SAY WHICH DIMENSION THE SCORE IS ACTUALLY FOLLOWING.
        # Measured over 412 judged screens, the holistic `similarity` tracks the MINIMUM
        # dimension at r=0.942 — higher than any single dimension (components 0.924, layout
        # 0.910) and higher than the unweighted mean (0.927) — with an offset of only +0.047.
        # The score is "the weakest dimension plus a small allowance", not an average. So on a
        # screen whose weakest dimension is clearly alone, raising any OTHER dimension cannot
        # move the number.
        #
        # The lane was never told this. It receives a mean of **6.4** FIX instructions per
        # screen (median 7, one per dimension), all formatted identically, and the weakest is
        # clearly alone — a gap of >=0.05 to the second-worst — on **211 of 299** blocking
        # screens (71%). Naming it costs one line and turns seven equal-looking asks into one
        # ask plus six that are worth doing but will not lift the gate.
        _ranked = sorted(((v.get("score"), k) for k, v in dims.items()
                          if isinstance(v, dict) and isinstance(v.get("score"), (int, float))))
        if len(_ranked) >= 2:
            _lo, _lokey = _ranked[0]
            _title = dim_titles.get(_lokey, _lokey)
            if _ranked[1][0] - _lo >= 0.05:
                lines.append(
                    f"This screen's score follows its WEAKEST dimension — {_title} ({_lo:.2f}). "
                    f"Raising any other dimension will not move it until {_title} comes up.")
            else:
                _tied = ", ".join(dim_titles.get(k, k) for sc, k in _ranked
                                  if sc - _lo < 0.05)
                lines.append(
                    f"This screen's score follows its weakest dimensions — {_tied} "
                    f"({_lo:.2f}) — which are tied; all of them have to come up.")
        # #649b: a non-numeric score used to raise TypeError here and take the WHOLE
        # remediation body down — a malformed judge field must never cost the lane its
        # instructions. Coerce for ordering only; the printed value is untouched.
        def _score_key(kv):
            _s = kv[1].get("score") if isinstance(kv[1], dict) else None
            return _s if isinstance(_s, (int, float)) else 0.0
        for key, rec in sorted(dims.items(), key=_score_key):
            if rec.get("notes"):
                lines.append(f"- [{dim_titles.get(key, key)} {rec.get('score', 0):.2f}] {rec['notes']}")
            # #660: the judge writes "None.", "No change needed.", "None significant." into
            # `fix` when a dimension needs nothing — 309 of 8094 fix instructions across the
            # corpus, 295 after excluding the 14 that hide a real instruction behind
            # "beyond"/"once". Emitted verbatim they read as instructions ("FIX: None
            # significant.") and dilute the real ones; #649 measured the lane already receiving
            # a mean of 6.4 per blocking screen. Dropping them is safe rather than blinding: no
            # screen has ALL of its fixes in this shape, and no BLOCKING screen does either
            # (0 of 299) — so nothing is ever left without an actionable line.
            if rec.get("fix") and not _is_noop_fix_660(str(rec["fix"])):
                lines.append(f"  FIX: {rec['fix']}")
        devs = r.get("deviations") or []
        if devs:
            # #855: drop the ones a static route capture can never satisfy, and SAY SO.
            _sname = r.get("screen") or r.get("name")
            _keep = [d for d in devs if not _unsatisfiable_by_static_capture_855(d, _sname)]
            _dropped = len(devs) - len(_keep)
            if _keep:
                lines.append("Differences (where + what):")
                for d in _keep:
                    lines.append(f"- {d}")
            if _dropped:
                lines.append(
                    f"  ({_dropped} further note(s) ask for a HOVER/interaction state. This screen "
                    "is captured statically, so no change can make them appear — they are recorded "
                    "in the verdict but are not work. Do not chase them.)")
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
    # #680: name what did not fit, with its scores, so the omission is visible and the lane
    # knows it is a sequencing decision rather than a claim that these screens are fine.
    if _deferred:
        lines.append(
            "\n## Not in this round ({} more below the bar)\n".format(len(_deferred))
            + ", ".join(f"{r.get('name')} ({float(r.get('similarity') or 0.0):.2f})"
                        for r in _deferred)
            + "\n These are ordered behind the screens above, which are further from the bar. "
              "Remediation is re-issued every round, so they lead the next one — fix the ones "
              "above first rather than spreading effort across all of them.")
    return _regressed + _head + "\n".join(lines)   # #619/#620


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


def _style_lines_797(ds: Optional[Mapping[str, Any]], screen_name: str) -> List[str]:
    """#797: the measured SURFACE TREATMENT for one failing screen.

    `style` is the lowest-mean judged dimension (0.615) and `flat` appears in 79% of its notes.
    #779 found why: `design_system.shadow_scale` (ready-to-paste CSS per role) and
    `design_system.material` (the surface treatment in words) are measured from the reference,
    written to the file, and were named nowhere the lane reads — fixed for the KICKOFF prompt.
    But #796 showed the kickoff prompt is read once at design time while THIS text is read on
    every repair round, so the measurement was still absent from the round that moves the score.
    Empty when nothing is measured."""
    if ds is None:
        return []
    try:
        out: List[str] = []
        mat = str(ds.get("material") or (ds.get("design_system") or {}).get("material") or "").strip()
        if mat:
            out.append("  · MATERIAL (measured): " + mat[:400])
        scale = (ds.get("shadow_scale")
                 or (ds.get("design_system") or {}).get("shadow_scale") or [])
        seen = set()
        for ent in scale if isinstance(scale, (list, tuple)) else []:
            if not isinstance(ent, Mapping):
                continue
            role, css = str(ent.get("role") or ""), str(ent.get("css") or "")
            if not css or css in seen:
                continue
            # the screen's own roles first; a generic scale entry still applies to any surface
            if role and screen_name and role not in screen_name and screen_name not in role \
                    and len(seen) >= 3:
                continue
            seen.add(css)
            out.append(f"  · ELEVATION {role or 'default'}: box-shadow: {css};")
        if not out:
            return []
        return (["MEASURED DEPTH (paste these, do not default to flat — `style` is the weakest "
                 "dimension at 0.615 mean and `flat` appears in 79% of its notes):"] + out)
    except Exception:
        return []


def _copy_lines_797(ds: Optional[Mapping[str, Any]], screen_name: str) -> List[str]:
    """#797: the VERBATIM reference text for this screen's components.

    #778 measured 9152 text components across the corpus and 84% of their notes DESCRIBED the
    text rather than quoting it, which is why `ui_copy` keeps scoring as a floor; #786 added the
    transcription to the design-prep schema and named it in the kickoff prompt. Same #796 gap:
    the repair round never saw it. Empty when no component carries `copy`."""
    if ds is None:
        return []
    try:
        screen = next((x for x in (ds.get("screens") or [])
                       if isinstance(x, Mapping) and str(x.get("name") or "") == screen_name), None)
        if screen is None:
            return []
        rows = []
        for c in (screen.get("components") or [])[:12]:
            if not isinstance(c, Mapping):
                continue
            txt = str(c.get("copy") or "").strip()
            if txt:
                rows.append(f"  · {c.get('id') or c.get('name')}: \"{txt[:120]}\"")
        if not rows:
            return []
        return (["REFERENCE COPY (verbatim — render these strings character for character; do "
                 "not paraphrase, translate or substitute a synonym):"] + rows)
    except Exception:
        return []


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
        # #796: lead with the screen's measured CONTENT BOX. #787 named `layout_metrics` to the
        # lane in the kickoff prompt, but the lane reads THIS text on every repair round — so the
        # measurement was present when designing and absent when fixing, which is the round that
        # matters for a layout deviation. Per-component regions below only imply the container;
        # the full-bleed case (left 0, width 100%) is the one an implied container gets wrong,
        # and r151 carries 15 distinct boxes across its 20 screens, so it is not one global value.
        _lm796 = screen.get("layout_metrics")
        if isinstance(_lm796, Mapping):
            try:
                _l = float(_lm796.get("left")); _w = float(_lm796.get("width"))
                rows.append(
                    "  · CONTENT BOX (measured): x %.0f-%.0f%% (width %.0f%%)%s — set THIS "
                    "screen's container/gutters to match; it is measured per screen and the "
                    "screens differ." % (
                        _l * 100, (_l + _w) * 100, _w * 100,
                        " = FULL-BLEED, no max-width container" if _w >= 0.99 and _l <= 0.01
                        else ""))
            except Exception:
                pass
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
            # #812: the measured VERTICAL RHYTHM of a list-like component. design_prep records
            # `rows` (detected item bands) and `row_gap_px` (the gap between them) per component
            # — e.g. r151's profile flyout is 7 rows at 57px. Written, never read, and `layout`
            # is a floor dimension with a repair text that carried no spacing at all.
            #
            # Its siblings `columns`/`pitch_px` are DELIBERATELY not emitted: they are a
            # low-level stripe measure (25 "columns" at 7px pitch across a top nav), not a
            # layout grid. Handing that to a lane as "columns" would be #782's mistake in
            # reverse — a plausible NAME whose meaning does not match it.
            _geo812 = comp.get("geometry") if isinstance(comp.get("geometry"), Mapping) else {}
            _rhythm = ""
            try:
                _n, _gap = _geo812.get("rows"), _geo812.get("row_gap_px")
                if isinstance(_n, int) and _n > 1 and isinstance(_gap, (int, float)) and _gap > 0:
                    _rhythm = f", {_n} rows {_gap:.0f}px apart (measured)"
            except Exception:
                _rhythm = ""
            rows.append(
                f"  · {comp.get('id')}: x {x1 * 100:.0f}-{x2 * 100:.0f}% "
                f"(width {(x2 - x1) * 100:.0f}%), y {y1 * 100:.0f}-{y2 * 100:.0f}% "
                f"(height {(y2 - y1) * 100:.0f}%)"
                + (f", bg {bg}" if bg else "") + _rhythm)
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
        # #811: state the denominator. An advisory that silently shows 20 of 40 reads as "these
        # are the ones", and the lane fixes the visible half.
        _hdr = ("\n## Real assets not used (advisory — use the STAGED asset, do not draw it)"
                + (" — showing 20 of %d:" % len(rows) if len(rows) > 20 else ":"))
        out = [_hdr]
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
        self.unreachable_refunds = 0   # #655b: same bound for capture/auth-unavailable
        self.last_result = None
        self.last_judged_sig = None
        self._passed_screens: set = set()  # #129: milestone-anchored sticky per-screen pass latch
        self._seed_reminder_sent = False   # #133: one backend seed reminder per milestone
        self._best_by_screen: Dict[str, float] = {}  # #138: best similarity per blocking screen
        self.plateau_rounds = 0            # #138: consecutive judgments with no new best
        self.app_dead_750 = False          # #750: blackout past the cap WITH console errors
        self.avg_pass_rounds = 0           # #558: consecutive judged rounds whose gating
        #                                    blocking_average cleared the min bar (the STABLE
        #                                    precondition for the avg fast-release; a single
        #                                    lucky pass never fires it). Reset when a round drops
        #                                    below the bar; per-milestone (not reset by churn).
        self._verdict_cache: Dict[str, Dict[str, Any]] = {}  # #142: (screen, shot-md5) → verdict
        self.last_judgment_at = None       # #145: wall-clock of the last real judgment
        self.released = False              # #521: STICKY escape latch — once the deferral
        #                                    escapes (below-threshold delivery earned), the
        #                                    milestone stays released; a later >0.02 per-screen
        #                                    improvement must NOT reset plateau_rounds and re-
        #                                    defer (r91/r92: escape fired then re-deferred, so
        #                                    the deliver_project loop only terminated at the
        #                                    3600s wall-clock — 44/88 narrations, ~75min tails).

    def reset_for_milestone(self) -> None:
        """Anchor the deferral clock + total-judgment backstop to a NEW milestone
        (PIPE-C3: within a milestone neither is reset by lane churn)."""
        self.deferred_since = None
        self.total_judgments = 0
        self.transient_refunds = 0     # #75a: milestone-anchored, not reset by sig churn
        self.unreachable_refunds = 0   # #655b: milestone-anchored, same reason
        self._passed_screens = set()   # #129: latch cleared per milestone, not by sig churn
        self._seed_reminder_sent = False  # #133: re-armed per milestone
        self._best_by_screen = {}      # #138: plateau tracking is per milestone
        self.plateau_rounds = 0
        self.avg_pass_rounds = 0       # #558: avg-stable round tracking is per milestone
        self._verdict_cache = {}       # #142: pixel-keyed verdicts are per milestone
        self.last_judgment_at = None   # #145: idle-source stamp is per milestone
        self.released = False          # #521: sticky escape latch is per milestone

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
            # #565: on a NON-FINAL milestone, scope this advisory judge to THIS
            # milestone's OWNED routes so it stops scoring + filing frontend remediation
            # for pages a later milestone owns (M1 churning on M2/M3). Final/single-
            # milestone — or an orchestrator with no _current_milestone — leaves _scope
            # None → the full set → byte-identical to the r107-r109 path. An empty extracted
            # set also stays None (never hide everything on a prose miss).
            _scope = None
            if not getattr(orch, "_is_final_milestone", True):
                _ms = getattr(orch, "_current_milestone", None) or {}
                _routes = _milestone_declared_routes(_ms)
                if _routes:
                    _scope = _routes
            # #941: the milestone's identity, built from whatever the plan actually carries
            # (`id` / `index` / `name` — verified against r154's milestones.json, not guessed).
            _mlabel941 = None
            try:
                _msd = getattr(orch, "_current_milestone", None) or {}
                if isinstance(_msd, dict) and _msd:
                    _bits = [str(_msd.get("index") or "").strip(),
                             str(_msd.get("name") or "").strip(),
                             str(_msd.get("id") or "").strip()]
                    _mlabel941 = " ".join(b for b in _bits if b) or None
            except Exception:
                _mlabel941 = None
            result = await run_visual_fidelity(orch.output_dir, refs, _judge_llm,
                                               verdict_cache=self._verdict_cache,
                                               milestone_owned_routes=_scope,
                                               milestone_label=_mlabel941)
            if result.get("capture_unavailable") or result.get("auth_unavailable"):
                # Not a judgment — the app wasn't reachable (mid-rebuild) or
                # the authed session was rejected wholesale (token mint failed
                # / every auth route bounced to /login — round 31 judged the
                # LOGIN PAGE against feed/profile references, 0.2s across the
                # board). Refund so the budget only counts REAL verdicts.
                #
                # #655b — BOUNDED, for the same reason #75a bounds the blank refund three lines
                # below: "a GENUINELY blank app can't defer forever". This branch was the one
                # asymmetry — unbounded — and #655 widened its entry by relaxing the auth
                # wipeout from "every auth SCREEN bounced" to "every auth ROUTE bounced". A
                # transient race clears on the re-mint and never reaches the cap; an app whose
                # auth guard is actually broken satisfies the condition EVERY round, so without
                # a bound it refunds every round, the fidelity gate never counts an attempt, and
                # the run spins to wall-clock. Past the cap the result flows to a real verdict
                # and its remediation, exactly as the blank path does.
                #
                # Found by cross-auditing this session's fixes against each other (the #645
                # method); the asymmetry predates #655, which only made it easier to reach.
                if self.unreachable_refunds < _TRANSIENT_REFUND_CAP:
                    self.unreachable_refunds += 1
                    self.attempts = max(0, self.attempts - 1)
                    orch._logger.warning(
                        "Visual fidelity: %s — attempt refunded, will retry next tick "
                        "(unreachable %s/%s).",
                        result.get("summary") or "capture/auth unavailable",
                        self.unreachable_refunds, _TRANSIENT_REFUND_CAP)
                else:
                    orch._logger.warning(
                        "Visual fidelity: %s — refund cap reached (%s), NOT refunding; the "
                        "condition is persistent, not transient.",
                        result.get("summary") or "capture/auth unavailable",
                        _TRANSIENT_REFUND_CAP)
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
            # #737: A BLACKOUT CANNOT IMPROVE, SO IT MANUFACTURES ITS OWN PLATEAU.
            # #75a refunds a wholesale blank capture, BOUNDED by _TRANSIENT_REFUND_CAP so a
            # genuinely blank app cannot defer forever — correct. What follows the cap was not:
            # `capture_transient` stays True, the branch above stops returning, and every screen
            # arrives at 0.00. A 0.00 never beats its best-so-far, so `_improved` is False by
            # construction and `plateau_rounds` climbs once per blackout round. The plateau
            # escape then reads that as "the scores have flatlined" and ships.
            #
            # r148 is the worked example end to end:
            #
            #   11:13:19  10 of 12 screens blank -> refunded (transient 1/3)
            #   11:14:49  same 10 blank          -> refunded (transient 2/3)
            #   11:18:16  same 10 blank          -> refunded (transient 3/3)   cap exhausted
            #   ...five more blackout rounds, each incrementing plateau_rounds...
            #   11:36:46  deferral RELEASED (... PLATEAU 5 no-improvement rounds - #138 escape)
            #   11:36:47  FINAL DELIVERY: gate clear -> cut release v1.0.0
            #
            # The app was genuinely broken, not the capture: the verifier independently filed
            # `TypeError: (void 0) is not a function` at 11:22:16, and four P0 tasks were still
            # OPEN at the cut, one of them titled "P0 REMEDIATION: SPA crashes on ALL routes"
            # whose description reads "DELIVERY IS BLOCKED BY THIS ONE BUG". So the blackout was
            # the truest signal in the run, and it was consumed as evidence of stability.
            #
            # Corpus: 8 of 116 runs with a verdict.json end with blank>=2 or half their screens
            # at 0.00. r148 is NOT among them — #500's high-water merge had already erased its
            # blackout from the persisted record — so that 7% is a floor, not an estimate.
            #
            # A blackout round carries NO information about whether the app has plateaued, so it
            # neither increments nor resets. Deliberately narrow: `total_judgments` and
            # `last_judgment_at` above still advance (a blank capture still costs a vision call),
            # and the wall-clock/total-judgment escapes still bound the run — this removes a
            # false accelerant, it does not add a way to hang.
            if result.get("capture_transient"):
                orch._logger.warning(
                    "#737 blackout round does NOT count toward the plateau: the capture "
                    "produced no rendered page, so its 0.00s are not evidence the app has "
                    "flatlined (plateau still %s). Past #75a's refund cap this round is "
                    "judged and remediated as before — only the escape counter is held.",
                    self.plateau_rounds)
                # #750 (user-approved): LATCH "the app does not render" and veto every release
                # escape. Narrow by construction, and only measurable since #740 started
                # keeping the console: a blank capture alone is #75a's business and can be the
                # harness rather than the app — which is precisely why this decision sat open.
                # A blank capture PAST the refund cap whose routes ALSO raised an uncaught
                # error is not ambiguous. r148 is the case: 10 of 12 screens blank for nine
                # rounds while the console repeated `TypeError: (void 0) is not a function`,
                # and it released v1.0.0 through the plateau escape.
                _errs750 = sorted({m for _s in (screens or [])
                                   for m in (_s.get("console_errors") or [])})
                if self.transient_refunds >= _TRANSIENT_REFUND_CAP and _errs750:
                    if not self.app_dead_750:
                        orch._logger.warning(
                            "#750 DELIVERY VETOED — the app does not render. The capture has "
                            "blanked past #75a's refund cap (%s/%s) and the browser raised: "
                            "%s. Every release escape (wall-clock, attempts, plateau, idle, "
                            "#558 fast path) is refused while this holds; it clears as soon as "
                            "one capture renders. Fix the crash — no release is better than a "
                            "release that renders nothing.",
                            self.transient_refunds, _TRANSIENT_REFUND_CAP,
                            "; ".join(_errs750[:3]))
                    self.app_dead_750 = True
            else:
                # #750: a capture that RENDERED clears the veto. The latch must never outlive
                # the condition — a lane that fixes the crash has to be able to ship, and a
                # sticky veto would turn one bad round into a run that can never deliver.
                if self.app_dead_750:
                    orch._logger.warning(
                        "#750 veto CLEARED — this capture rendered, so the app is no longer "
                        "demonstrably dead and the release escapes apply again.")
                    self.app_dead_750 = False
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
            # FIX #558: track consecutive REAL judgments whose gating blocking_average (#542,
            # over BLOCKING screens only) cleared the min bar — the STABLE precondition for the
            # avg fast-release (a single lucky pass never triggers a release; a round below the
            # bar resets the count — TRUE as written; #712's strike-through is withdrawn, see
            # #712r below). Per-milestone, NOT reset by source churn
            # (mirrors plateau_rounds). Best-effort: a result missing either field never advances.
            #
            # #712r — THIS WHOLE BLOCK IS WITHDRAWN. The original #558 sentence was RIGHT and I
            # struck it out on a false premise. The counter reads `result["blocking_average"]`,
            # and `result` is what run_visual_fidelity RETURNS — `_blocking_similarity_average(
            # results)`, the CURRENT capture's blocking-only mean. It is not the merged
            # high-water value; that one exists only in the persisted record, written by
            # _persist_verdict, which never touches the returned dict. So the current average
            # CAN fall, the `else` reset below IS reachable, and "a round below the bar resets
            # the count" is true as originally written.
            #
            # Caught by r148: round 6 recorded gating 0.656 against live 0.61 with the bar at
            # 0.65 — the exact latch condition #712 described — and the warning below fired ZERO
            # times. It cannot fire at all: `result` carries no `blocking_average_live` key
            # (run_visual_fidelity's body never mentions it), so `_lv712` is always None. A dead
            # branch guarding a claim that was false anyway, which is the defect class this
            # session has been finding all along, written by me.
            #
            # Left in place, struck through rather than deleted, because the reasoning is the
            # useful part: I verified monotonicity from rounds.jsonl — the PERSISTED number —
            # and then assumed the counter read the same one. Two numbers with the same name in
            # two dicts, and I checked the wrong dict.
            #
            # ~~#712: THE STRUCK-OUT SENTENCE IS FALSE, AND THE PROTECTION IT DESCRIBES DOES NOT
            # EXIST. `blocking_average` is #711's high-water mark — computed over #500's merged
            # BEST-per-screen captures, so it is monotonically non-decreasing by construction and
            # never falls in either kept run. Once `_ba >= _mn` holds it holds forever, which
            # makes the `else` reset below UNREACHABLE after the first crossing. "N consecutive
            # rounds above the bar" therefore means "one round above the bar, then wait N-1
            # rounds", and with the default N=2 that is one lucky round plus one more judgment.
            #
            # r146 is the worked example, and it DELIVERED this way:
            #
            #     round   gating   live     avg_pass_rounds
            #     1-4     0.58-0.60 …       0
            #     5       0.67     0.6655   1     <- the only real crossing
            #     6       0.67     0.6409   2 = N -> fast_release fires
            #
            # The app that shipped scored 0.6409, under the 0.65 bar it was judged against, on
            # the strength of round 5's number latched into the mark. That is precisely the
            # "single lucky pass" the original sentence promised could not happen.
            #
            # Not changed here: whether the counter should read `blocking_average_live` instead
            # is the same calibration decision as #711 and the 0.65 bar, and flipping it would
            # make every flaky capture reset the count — the thing #500 exists to prevent. What
            # is fixed is the comment, plus a warning below when a release is authorised on a
            # latched average whose live capture is under the bar.
            try:
                _ba = result.get("blocking_average")
                _mn = result.get("min_similarity")
                if _ba is not None and _mn is not None and float(_ba) >= float(_mn):
                    self.avg_pass_rounds = self.avg_pass_rounds + 1
                    # #712: the count advanced. Say so when the LIVE capture is under the bar,
                    # because then the advance came from the latch and not from the app.
                    _lv712 = result.get("blocking_average_live")
                    if _lv712 is not None and float(_lv712) < float(_mn):
                        _LOG.warning(
                            "#712 avg_pass_rounds -> %d on a LATCHED average: gating %.4f >= bar "
                            "%.4f but this capture scored %.4f. blocking_average never falls "
                            "(#711), so the 'consecutive rounds' precondition cannot reset and "
                            "a release may be authorised on a round the app did not earn.",
                            self.avg_pass_rounds, float(_ba), float(_mn), float(_lv712))
                else:
                    self.avg_pass_rounds = 0
            except Exception:
                self.avg_pass_rounds = 0
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
            # #617 — THE TASK TITLE BORROWED THE WRONG COUNTER. `self.attempts` is the JUDGING
            # budget for the CURRENT source (reset to 0 on line ~3038 whenever the frontend
            # changes, cap 3) — and a remediation always changes the frontend, so it is 1 again
            # on every re-dispatch. Measured across the arc: **280 visual-gate remediation tasks
            # in 40 runs, every single one titled "attempt 1"**, median 6 per run and up to 21.
            #
            # The loop itself is healthy — 7 capture rounds per run (max 26), 6 dispatches, 182
            # completions — so the failure is not that nothing re-measures. It is that every
            # iteration is AMNESIC: the lane cannot tell it is being asked the 21st time, and
            # any escalation keyed on the round can never fire. Count the dispatches separately;
            # `self.attempts` keeps its own meaning untouched.
            self._remediation_round = getattr(self, "_remediation_round", 0) + 1
            # #619: what THIS capture scored, and what the previous round scored, so the task
            # can lead with whether the lane's last change helped.
            _this_live = None
            try:
                _lb = [x for x in (screens or []) if isinstance(x, Mapping)
                       and not x.get("advisory") and x.get("blank") is not True]
                _this_live = (round(sum(float(x.get("similarity") or 0.0) for x in _lb)
                                    / len(_lb), 4) if _lb else None)
            except Exception:
                _this_live = None
            _prev_live = getattr(self, "_prev_live_average", None)
            self._prev_live_average = _this_live
            try:
                _vt = orch.hubs.workhub.create_task(
                    title=(f"UI does not match reference designs (visual gate, "
                           f"round {self._remediation_round}; judge attempt "
                           f"{self.attempts}/3 on this source)"),
                    description=remediation_text(result, getattr(orch, "output_dir", None),
                                                 latched=self._passed_screens,
                                                 prev_live=_prev_live, this_live=_this_live,
                                                 round_no=self._remediation_round),
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
                    # #661: NAME THE TABLES, AND DO NOT ASSERT A CAUSE THE FRAMEWORK CAN CHECK.
                    # This task told the backend "add seed rows" unconditionally and listed only
                    # SCREEN names, leaving the lane to map screen -> table itself — information
                    # the framework already holds. Worse, when the tables are in fact seeded the
                    # advice is simply wrong: a page that renders empty over a populated table is
                    # a QUERY/filter/owner-scoping bug (the #566y/#598 family), and sending the
                    # backend to add rows burns a round on the wrong lane.
                    # `audit_seed_data` is the existing checker that tells the two apart, and it
                    # is reachable here (`orch.hubs.schema_hub` is the registryhub).
                    # Measured: 99 empty-state screens across 48 runs, 19 of them blocking, and
                    # NOT ONE ever cleared the bar — similarity min 0.03, median 0.35, max 0.60.
                    # Best-effort: a diagnosis that fails must never cost the reminder.
                    _thin: List[str] = []
                    _seed_checked = False
                    try:
                        from .seed_audit import audit_seed_data as _asd
                        _rep = _asd(orch.hubs)
                        _seed_checked = True
                        _thin = sorted({str(t.get("table")) for t in _rep.flagged_tables
                                        if isinstance(t, dict) and t.get("table")})
                    except Exception:
                        pass
                    if not _seed_checked:
                        _diag = ("Add realistic seed rows (>=3) for each screen's backing "
                                 "table(s) to app/backend/seed_data.json.")
                    elif _thin:
                        _diag = ("The seed audit flags these registered tables as under-seeded: "
                                 + ", ".join(_thin) + ". Seed them first — that is very likely "
                                 "the whole cause. Add realistic rows to "
                                 "app/backend/seed_data.json.")
                    else:
                        _diag = ("NOTE: the seed audit flags NO table as under-seeded, so this "
                                 "is probably NOT a seeding problem. A page that renders empty "
                                 "over a populated table is a read-path bug — check the query's "
                                 "filters and owner-scoping (does the browsing user own the "
                                 "rows?), the route's handler precedence, and whether the "
                                 "endpoint returns [] for a valid session. Only add seed rows "
                                 "if you first confirm the backing table is genuinely empty.")
                    _bt = orch.hubs.workhub.create_task(
                        title="Visual gate: screen(s) render an EMPTY state — seed the missing rows",
                        description=(
                            "The visual-fidelity judge flagged these screens as EMPTY-state: "
                            + ", ".join(_empty) + ". Their reference design only renders when "
                            "the backing table has rows (e.g. a reels page needs video posts), "
                            "so the screen can never match the reference no matter what the "
                            "frontend does. " + _diag + " Keep FK references consistent with "
                            "the existing seed users/posts."),
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
                                "cannot render without data. " + _diag),
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
