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
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .validation_runner import _service_host_port

# ---------------------------------------------------------------------------
# Reference-image → route mapping. Reference screenshots are conventionally
# named after the screen they depict; keyword order matters (create_account
# must win over create). A name that maps to no route is skipped (reported).
# ---------------------------------------------------------------------------
_ROUTE_KEYWORDS: tuple = (
    (("create_account", "signup", "sign_up", "register"), "/signup", False),
    (("login", "sign_in", "signin"), "/login", False),
    (("home", "feed", "timeline"), "/feed", True),
    (("search", "explore", "discover"), "/explore", True),
    (("video", "reel", "watch"), "/reels", True),
    (("create", "new_post", "upload", "compose"), "/create", True),
    (("profile", "account"), "/profile", True),
    (("message", "inbox", "direct", "dm"), "/messages", True),
    (("saved", "bookmark", "collection"), "/saved", True),
    (("people", "suggested", "friends"), "/people", True),
)

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


def map_reference_screens(
    reference_images: List[Any],
    known_routes: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """[{name, path, route, auth}] for every reference image whose filename maps
    to a route. Two layers: the common-screen keyword table, then a GENERIC
    fallback matching the filename against the app's actual routes (so an
    arbitrary app's "boards.png" maps to its /boards screen without any
    catalog). Unmappable images get route=None (skipped, not failed)."""
    known = {str(r) for r in (known_routes or set())}
    screens: List[Dict[str, Any]] = []
    for ref in reference_images or []:
        p = Path(ref)
        if not p.is_file():
            continue
        stem = re.sub(r"[^a-z0-9]+", "_", p.stem.lower())
        segs = [s for s in stem.split("_") if s]
        route, auth = None, True
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
        if segs:
            _add(segs[-1])             # the trailing screen token alone
        # GENERIC FIRST (domain-agnostic): match the screenshot filename to a
        # declared route, or "/" for a home/landing screen — so an arbitrary app's
        # screens map without the social catalog biasing ambiguous names.
        if known:
            route = next((c for c in cands if c in known), None)
            if route is None and (stem in _HOME_STEMS or (segs and segs[-1] in _HOME_STEMS)) and "/" in known:
                route = "/"
        # The keyword catalog still supplies the public/auth flag (a login/landing
        # screen is public) and fills the ROUTE only as a LAST resort (never
        # overriding a generic match, and only when the app serves it) — so a
        # non-social app whose screen name contains a social token isn't mis-routed.
        for keys, r, a in _ROUTE_KEYWORDS:
            if any(k in stem for k in keys):
                auth = a
                if route is None and ((not known) or r in known):
                    route = r
                break
        screens.append({"name": p.stem, "path": str(p), "route": route, "auth": auth})
    return screens


# ---------------------------------------------------------------------------
# App boot + auth (the smoke validation tears the env down with ``down -v``,
# so the gate boots the already-built images itself).
# ---------------------------------------------------------------------------
def _compose_up(project_dir: Path, timeout: int = 180) -> Optional[str]:
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
    """Credentials of the SEEDED demo user (the first user in the generated seed_data.py,
    whose password is the framework's fixed seed password). The QA tooling logs in AS this
    user so it validates the POPULATED app — the references depict screens WITH data, and a
    fresh throwaway user sees empty lists (multi-tenant read-scoping), making every page look
    blank/mismatched. Domain-agnostic: reads whatever the seed generated. None if no seed."""
    try:
        import ast
        sd = Path(project_dir) / "app" / "backend" / "seed_data.py"
        if not sd.is_file():
            return None
        m = re.search(r"_SEED\s*=\s*(\{.*\})", sd.read_text(encoding="utf-8", errors="ignore"))
        if not m:
            return None
        seed = ast.literal_eval(m.group(1))
        users = (seed or {}).get("users") or []
        email = users[0].get("email") if users and isinstance(users[0], dict) else None
        if not email:
            return None
        return {"email": str(email), "password": "password",  # backend_skeleton._SEED_PASSWORD
                "name": str((users[0].get("name") or "Demo"))}
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


async def capture_route_screenshots(
    base_url: str,
    screens: List[Dict[str, Any]],
    token: Optional[str],
    out_dir: Path,
    auth_redirected: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Screenshot each screen's route; returns {screen name → png path}. A
    failed navigation skips that screen (reported upstream as missing). An
    AUTH screen whose final URL bounced to /login|/signup is NOT shot — the
    judge must never compare the login page against a feed reference (round
    31: every auth screen scored 0.2 against the wrong pixels). Bounced
    names are appended to ``auth_redirected`` when the caller passes one."""
    from playwright.async_api import async_playwright  # lazy: heavy dep

    out_dir.mkdir(parents=True, exist_ok=True)
    shots: Dict[str, str] = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            ctx = await browser.new_context(viewport=_VIEWPORT)
            if token:
                await ctx.add_init_script(
                    f"localStorage.setItem('token', {json.dumps(token)});")
            page = await ctx.new_page()
            for screen in screens:
                if not screen.get("route"):
                    continue
                try:
                    await page.goto(base_url + screen["route"],
                                    wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(1200)
                    if screen.get("auth"):
                        final = (page.url or "").split("?", 1)[0].rstrip("/")
                        if final.endswith("/login") or final.endswith("/signup"):
                            if auth_redirected is not None:
                                auth_redirected.append(screen["name"])
                            continue
                    dest = out_dir / f"{screen['name']}.png"
                    await page.screenshot(path=str(dest))
                    shots[screen["name"]] = str(dest)
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
            "fixes": fixes, "summary": str(data.get("summary", ""))[:300]}


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
        return {"similarity": 0.0, "dimensions": {}, "deviations": [f"judge call failed: {exc}"[:200]],
                "summary": "judge error"}


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
    screens = map_reference_screens(reference_images, known_routes)
    judged_screens = [s for s in screens if s.get("route")][:max_screens]
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
        fe_port = (_service_host_port(compose_file, cwd, "frontend")
                   or _service_host_port(compose_file, cwd, "ui") or 8080)
        be_port = (_service_host_port(compose_file, cwd, "backend")
                   or _service_host_port(compose_file, cwd, "api") or 3001)
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
        base_url = f"http://localhost:{fe_port}"
        # The validation cycle tears the env down (down -v) and rebuilds —
        # capture must wait for the frontend to actually serve, or every
        # screenshot fails and the gate "judges" a dead app (round 29: all
        # screens 0.00 "could not be captured", burning the attempt budget;
        # round 32 M5: same at 60s — a legacy-builder rebuild takes minutes,
        # so wait up to 240s).
        _deadline = time.time() + 240
        while time.time() < _deadline:
            try:
                req = urllib.request.Request(base_url, method="GET")
                with urllib.request.urlopen(req, timeout=4) as r:
                    if 200 <= r.status < 500:
                        break
            except Exception:
                pass
            time.sleep(3)
        shots_dir = out_dir or (project_dir / "design" / "visual_gate")

        _auth_bounced: List[str] = []

        async def capture(scr):  # noqa: F811 — default capture closes over the boot
            return await capture_route_screenshots(
                base_url, scr, token, shots_dir, auth_redirected=_auth_bounced)

    else:
        _auth_bounced = []

    shots = await capture(judged_screens)
    _auth_routes = [s["name"] for s in judged_screens if s.get("auth")]
    if _auth_routes and set(_auth_bounced) >= set(_auth_routes):
        # The minted token was rejected wholesale (e.g. the validation cycle
        # rebuilt the app between mint and capture, rotating the JWT keys).
        return {"passed": False, "auth_unavailable": True,
                "summary": ("authenticated session rejected — every auth route "
                            "redirected to /login despite a freshly minted "
                            "token; skipping judgment"),
                "screens": [], "skipped": skipped}
    if judged_screens and not shots:
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
            results.append({"name": screen["name"], "route": screen["route"],
                            "similarity": 0.0, "passed": False, "dimensions": {},
                            "deviations": [
                                (f"route {screen['route']} redirected to /login — the "
                                 "auth guard rejected the session on THIS route only; "
                                 "fix the route's auth handling, not its styling")
                                if screen["name"] in _auth_bounced
                                else f"route {screen['route']} could not be captured"],
                            "screenshot": None})
            continue
        verdict = await judge(llm, screen, shot)
        results.append({"name": screen["name"], "route": screen["route"],
                        "similarity": verdict["similarity"],
                        "passed": verdict["similarity"] >= min_similarity,
                        "dimensions": verdict.get("dimensions", {}),
                        "deviations": verdict["deviations"],
                        "fixes": verdict.get("fixes", []),
                        "screenshot": shot,
                        "summary": verdict.get("summary", "")})

    passed = all(r["passed"] for r in results)
    failing = [f"{r['name']}({r['similarity']:.2f})" for r in results if not r["passed"]]
    summary = ("all %d screens ≥ %.2f" % (len(results), min_similarity) if passed
               else "below %.2f: %s" % (min_similarity, ", ".join(failing)))
    return {"passed": passed, "summary": summary, "screens": results, "skipped": skipped,
            "min_similarity": min_similarity}


def remediation_text(result: Mapping[str, Any]) -> str:
    """Actionable task body for the frontend lane from a failed gate result —
    per screen: missing components first, then the judge's per-dimension notes
    (weakest dimension first), then the ordered deviations."""
    lines = ["Visual fidelity below threshold vs the reference designs. "
             "Fix the implemented screens to match the references:"]
    dim_titles = {d["key"]: d["title"] for d in _DIMENSIONS}
    for r in result.get("screens", []):
        if r.get("passed"):
            continue
        lines.append(f"\n## {r['name']}  (route {r['route']}, similarity {r['similarity']:.2f})")
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
    lines.append("\nReference images: use list_reference_images / view_image. "
                 "Your screenshots from the last gate run are in design/visual_gate/.")
    return "\n".join(lines)


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
        self.last_result = None
        self.last_judged_sig = None

    def reset_for_milestone(self) -> None:
        """Anchor the deferral clock + total-judgment backstop to a NEW milestone
        (PIPE-C3: within a milestone neither is reset by lane churn)."""
        self.deferred_since = None
        self.total_judgments = 0

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
            self.attempts = self.attempts + 1
            result = await run_visual_fidelity(orch.output_dir, refs, orch.llm)
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
            screens = result.get("screens") or []
            self.last_result = result
            self.last_judged_sig = sig
            # PIPE-C3: per-milestone real-judgment counter (NOT reset on sig
            # change — only at milestone start). A vision-cost backstop escape so a
            # churning lane that keeps flipping the source signature can't drive
            # unbounded judging even before the 900s wall-clock escape fires.
            self.total_judgments = self.total_judgments + 1
            if result.get("passed"):
                self.passed = True
                orch._logger.warning(
                    "Visual fidelity PASSED (%s): %s",
                    ", ".join(f"{s['name']}={s['similarity']:.2f}" for s in screens),
                    result.get("summary"))
                return
            orch._logger.warning(
                "Visual fidelity attempt %s/3 FAILED — %s",
                self.attempts, result.get("summary"))
            try:
                _vt = orch.hubs.workhub.create_task(
                    title=f"UI does not match reference designs (visual gate, attempt {self.attempts})",
                    description=remediation_text(result),
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
        except Exception as exc:
            orch._logger.error("visual fidelity gate raised (non-fatal): %s", exc)
