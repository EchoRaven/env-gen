"""Framework-driven BROWSER test-user (2026-06-22).

The post-milestone test-user the orchestrator recruits: it does not trust the lane's
self-report — it drives a REAL headless browser against the running app and reports
what a person would find. Four jobs, mirroring the intended milestone-end flow:

  1. AUTH FLOW (universal, app-agnostic): register a fresh user (or demo-login), submit
     the real form, and assert a token was stored AND the app navigated away from the
     login page. This is what catches "login does nothing" / a dead auth form — the
     #1 way a generated app ships unusable (outlook run #8).
  2. INTERACT: for each declared page route, navigate as the logged-in user, screenshot
     it, and check it rendered REAL content (not a blank/stub heading), has no dead
     controls (a <button>/<form> with a bound handler), and logged no console errors.
  3. KEY-NODE SCREENSHOTS vs REFERENCE: the captured key pages (login, landing, inbox,
     calendar, …) are matched to the reference images by route (see visual_fidelity.
     map_reference_screens) so the caller can LLM-compare each pair.
  4. FEEDBACK: returns a structured report (per-flow ok + per-page findings + shots) the
     orchestrator routes back to the lane as remediation, then re-tests next cycle.

Pure + defensive: any browser/launch failure returns a report with ``ran=False`` and the
error, never raising into the validation loop. Chromium is the Playwright-bundled build
(no system 'chrome' channel — that path is often absent).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

_VIEWPORT = {"width": 1280, "height": 800}
# A page that rendered almost nothing (a stub heading) — used to flag "blank page".
_MIN_TEXT = 12
# DOM probe: real interactive control? console errors? AND does the page actually look
# like the LOGIN form (a password field + sign-in copy) — so a protected route that
# rendered the auth form IN PLACE (without a URL change) is still caught as hollow.
_PROBE = """() => {
  const txt = (document.body && document.body.innerText || '').trim();
  const btns = document.querySelectorAll('button, a[href], [role=button]').length;
  const inputs = document.querySelectorAll('input, textarea, select').length;
  const pw = document.querySelectorAll('input[type=password]').length;
  const signin = /\\b(sign ?in|log ?in|sign ?up|create account)\\b/i.test(txt);
  return { textLen: txt.length, sample: txt.slice(0, 120), buttons: btns,
           inputs: inputs, pw: pw, signin: signin };
}"""


_TOKEN_JS = "() => localStorage.getItem('access_token') || localStorage.getItem('token')"
# A URL still on an auth route means the flow did not get the user into the app.
_AUTH_ROUTE_SEGS = ("/login", "/signup", "/signin", "/register")


def _api_register(api_base: str, creds: Mapping[str, str]) -> bool:
    """Best-effort: ensure the test-user account EXISTS via the backend auth API so the
    LOGIN ui can be tested in isolation. Driving a multi-step SIGNUP ui is flaky and
    app-specific; the question the auth check answers — 'is the login form wired to the
    API' — only needs a user that already exists. 4xx (incl. 409 already-exists) counts
    as present; only a dead socket / 5xx is a miss. Never raises."""
    import urllib.request
    body = json.dumps({
        "email": creds["email"], "password": creds["password"], "name": creds["name"],
        "full_name": creds["name"].title(), "username": creds.get("username") or creds["name"],
    }).encode()
    for path in ("/auth/register", "/auth/signup"):
        try:
            req = urllib.request.Request(api_base.rstrip("/") + path, data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                if 200 <= r.status < 500:
                    return True
        except urllib.error.HTTPError as he:  # 409 already-exists etc. — the user is present
            if he.code < 500:
                return True
        except Exception:
            pass
    return False


def _is_param_seg(seg: str) -> bool:
    return seg.startswith(":") or (seg.startswith("{") and seg.endswith("}"))


def _http_get_json(url: str, token: Optional[str] = None, timeout: int = 5):
    """(status, parsed-json) for an authed GET; (0, {}) on any failure."""
    import urllib.request
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return 0, {}


def _rows_of(data: Any) -> list:
    """Rows out of a collection response: canonical {items:[...]} first, then a
    bare list, then the first list value of any envelope key — excluding
    error/diagnostic keys, whose entries can carry an 'id' field and would
    otherwise masquerade as rows ({'errors':[{'id':'AUTH_REQUIRED'}]})."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
        for k, v in data.items():
            if str(k).lower() in ("errors", "error", "warnings", "failures", "detail"):
                continue
            if isinstance(v, list):
                return v
    return []


def resolve_param_route(route: str, api_base: Optional[str], token: Optional[str],
                        http_get: Optional[Callable] = None) -> Optional[str]:
    """Fix #35 (complete form) — turn a PARAM route (``/inbox/message/:id``,
    ``/calendar/event/{eventId}``) into a CONCRETE walkable one by fetching a
    REAL row id from the backend.

    The walker used to navigate the LITERAL ``:id`` → the page fetched resource
    ":id" → rendered empty → a FALSE blank that burned the M1 deferral budget
    (outlook run-30). Skipping param routes (the interim fix) silences the false
    signal but leaves every DETAIL page (read-email, event-detail) with zero
    walk coverage. So: resolve first, skip only when unresolvable.

    ONLY id-shaped params are resolved (name ends in id/pk — :id, {eventId},
    :message_id, :uuid): substituting a ROW ID where a :slug/:tab/:handle
    belongs would fabricate a wrong-but-plausible route whose detail page
    misses → a false blank behind the BLOCKING gate (adversarial review
    a7f59d24: /posts/:slug → /posts/7 — the exact class this fix exists to
    kill). Non-id params → None → the caller's interim skip stands.

    Resource guess per id param, in order: the param NAME minus its Id suffix
    (``{eventId}`` → events), then the PRECEDING path segment (``message`` →
    messages) — each tried as-is/pluralised against GET {api_base}/api/<cand>
    with the caller's token (the seeded demo user, so owner-scoped lists are
    POPULATED). First row's id (id/<stem>_id/uuid/_id) substitutes the param,
    URL-encoded. Returns the concrete route, the original route when it has no
    params, or None when any param can't be resolved (caller falls back to
    skipping). Residual risk (accepted): a lane-custom UNSCOPED list beside a
    scoped by-id GET can hand out a non-owner id → 403 detail render — needs
    list/detail scoping to diverge, which by-construction scoping prevents for
    projected tables. Never raises; ``http_get`` injectable."""
    get = http_get or _http_get_json
    path = str(route or "").split("?", 1)[0]
    segs = path.split("/")
    if not any(_is_param_seg(s) for s in segs):
        return route
    if not api_base:
        return None

    def _cands(stem: str) -> List[str]:
        out: List[str] = []
        for c in ((stem + "s") if not stem.endswith("s") else stem,
                  stem, stem.rstrip("s") + "s"):
            if c and c not in out:
                out.append(c)
        return out

    resolved = list(segs)
    for i, seg in enumerate(segs):
        if not _is_param_seg(seg):
            continue
        pname = seg.lstrip(":").strip("{}")
        if not pname.lower().endswith(("id", "pk")):
            return None      # :slug / :tab / :handle — a row id would be WRONG
        stems: List[str] = []
        if len(pname) > 2 and pname.lower().endswith("id"):
            stems.append(pname[:-2].rstrip("_-").lower())
        prev = next((s for s in reversed(segs[:i]) if s and not _is_param_seg(s)), "")
        if prev:
            stems.append(prev.lower())
        rid = None
        seen: set = set()
        for stem in stems:
            if not stem:
                continue
            for cand in _cands(stem):
                if cand in seen:
                    continue
                seen.add(cand)
                try:
                    status, data = get(f"{api_base.rstrip('/')}/api/{cand}", token)
                except Exception:
                    continue
                if status != 200:
                    continue
                rows = _rows_of(data)
                if not rows or not isinstance(rows[0], dict):
                    continue
                row = rows[0]
                for k in ("id", f"{stem.rstrip('s')}_id", "uuid", "_id"):
                    v = row.get(k)
                    if v not in (None, ""):
                        import urllib.parse
                        rid = urllib.parse.quote(str(v), safe="")
                        break
                if rid:
                    break
            if rid:
                break
        if not rid:
            return None
        resolved[i] = rid
    return "/".join(resolved)


async def _fill_visible_inputs(page: Any, creds: Mapping[str, str]) -> int:
    """Fill every visible, empty input on the current step by detected role
    (email / password / name / generic). Returns how many it filled — staged forms
    expose one step at a time, so this is called once per step."""
    filled = 0
    try:
        inputs = await page.locator("input:visible").all()
    except Exception:
        return 0
    for inp in inputs:
        try:
            typ = ((await inp.get_attribute("type")) or "").lower()
            if typ in ("hidden", "checkbox", "radio", "submit", "button"):
                continue
            if (await inp.input_value()):  # already filled (don't clobber a prior step)
                continue
            blob = (((await inp.get_attribute("placeholder")) or "") + " "
                    + ((await inp.get_attribute("name")) or "")).lower()
            if typ == "email" or "email" in blob or "mail" in blob:
                await inp.fill(creds["email"])
            elif typ == "password" or "pass" in blob:
                await inp.fill(creds["password"])
            elif "name" in blob:
                await inp.fill(creds["name"])
            else:
                await inp.fill(creds["email"])  # username-style first field
            filled += 1
        except Exception:
            pass
    return filled


async def _click_primary(page: Any) -> bool:
    """Click the form's primary advance/submit control (Next / Sign in / Continue)."""
    for sel in ("button[type=submit]", "form button", "button[type=button]", "button"):
        try:
            b = page.locator(sel).first
            if await b.count() > 0 and await b.is_visible():
                await b.click(timeout=2500)
                return True
        except Exception:
            pass
    return False


async def _drive_auth_form(page: Any, creds: Mapping[str, str], *, max_steps: int = 4) -> Optional[str]:
    """Drive a login/signup form to completion, single- OR multi-step. Each step: fill the
    visible inputs, check for a stored token, else click the primary button and advance.
    Handles the Microsoft/Google staged flow (email -> Next -> password -> Sign in) without
    hardcoding any label. Returns the stored token (or None)."""
    for _ in range(max_steps):
        await _fill_visible_inputs(page, creds)
        token = await page.evaluate(_TOKEN_JS)
        if token:
            return token
        if not await _click_primary(page):
            break
        await page.wait_for_timeout(1800)
        token = await page.evaluate(_TOKEN_JS)
        if token:
            return token
    return await page.evaluate(_TOKEN_JS)


async def _wait_frontend_ready(page, base_url: str, attempts: int = 15,
                               gap_ms: int = 2000, timeout_ms: int = 4000) -> bool:
    """Poll ``base_url`` until the frontend SERVES (any response < 500). Returns True once
    reachable, False if it never comes up within ~attempts*gap.

    The delivery flow restarts the compose stack per milestone, so the browser walk can fire
    while the FRONTEND container is DOWN / rebuilding → every ``goto`` raises
    net::ERR_CONNECTION_REFUSED → auth_ok=False + all pages 'blank' → a FALSE 'unusable' that
    escape-ships a HEALTHY app (outlook run-28 v1.2.0, live: the final walk hit ERR_CONNECTION_
    REFUSED at /login mid container-restart). Waiting for readiness (and reporting ran=False
    when it never comes up → the gate treats it as 'could not run' / skip, never 'unusable')
    makes the verdict reflect the SETTLED app. Bounded + best-effort. ENV-AGNOSTIC."""
    for _ in range(max(1, attempts)):
        try:
            r = await page.goto(base_url + "/", wait_until="commit", timeout=timeout_ms)
            if r is None or (getattr(r, "status", None) or 200) < 500:
                return True
        except Exception:
            pass
        try:
            await page.wait_for_timeout(gap_ms)
        except Exception:
            pass
    return False


def _api_probe_once(api_base_url: str, timeout: int = 4) -> bool:
    """One HTTP probe of the API base; True when it answers anything < 500."""
    import urllib.request
    try:
        req = urllib.request.Request(api_base_url + "/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (getattr(r, "status", 200) or 200) < 500
    except Exception as exc:
        code = getattr(exc, "code", None)          # HTTPError: server answered
        return code is not None and code < 500


async def _wait_api_ready(page, api_base_url: str, attempts: int = 15,
                          gap_ms: int = 2000, probe=None) -> bool:
    """Poll the BACKEND base until it serves. The frontend readiness gate above closed the
    frontend-down race — but the compose restart staggers services, so the walk can run in
    the FRONTEND-UP/BACKEND-DOWN window: the SPA serves, every API call fails silently →
    login does nothing (auth_ok=False) + data pages render EMPTY shells with ZERO console
    errors (outlook run-35 M1+M2, live: exactly this signature escape-shipped twice).
    Bounded; False → caller reports ran=False (skip, never a false 'unusable')."""
    _probe = probe or _api_probe_once
    for _ in range(max(1, attempts)):
        if _probe(api_base_url):
            return True
        try:
            await page.wait_for_timeout(gap_ms)
        except Exception:
            pass
    return False


async def run_browser_test_user(
    base_url: str,
    pages: List[Mapping[str, Any]],
    out_dir: Path,
    *,
    register: bool = True,
    demo_login: Optional[Mapping[str, str]] = None,
    chrome_path: Optional[str] = None,
    api_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a real browser through the app. ``pages`` is [{name, route, auth}].
    Returns {ran, steps:[{step,ok,note}], pages:[{name,route,ok,blank,console_errors,
    shot}], shots:{name->path}, summary}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"ran": False, "steps": [], "pages": [], "shots": {}, "summary": ""}
    try:
        from playwright.async_api import async_playwright  # lazy heavy dep
    except Exception as exc:  # pragma: no cover
        report["summary"] = f"playwright unavailable: {exc}"
        return report

    def step(name: str, ok: bool, note: str = "") -> None:
        report["steps"].append({"step": name, "ok": bool(ok), "note": note[:200]})

    launch_kw: Dict[str, Any] = {"args": ["--no-sandbox"]}
    if chrome_path:
        launch_kw["executable_path"] = chrome_path
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(**launch_kw)
            try:
                ctx = await browser.new_context(viewport=_VIEWPORT)
                page = await ctx.new_page()
                cerr: List[str] = []
                page.on("console", lambda m: cerr.append(m.text) if m.type == "error" else None)
                report["ran"] = True

                # READINESS GATE (#27): don't test a frontend that's mid container-restart —
                # poll until it serves; if it never comes up, mark ran=False so the gate
                # SKIPS (could-not-run) rather than false-flagging 'unusable' + escape-shipping.
                if not await _wait_frontend_ready(page, base_url):
                    report["ran"] = False
                    report["summary"] = ("frontend not reachable after readiness wait (likely "
                                          "mid container-restart) — browser walk skipped")
                    return report
                # API-BASE READINESS (#46): the compose restart staggers services — in the
                # frontend-up/backend-down window the SPA serves but every API call fails
                # silently → auth_ok=False + blank-but-error-free data pages (run-35 M1+M2
                # escape-shipped on exactly this). Skip instead of false-flagging.
                if api_base_url and not await _wait_api_ready(page, api_base_url):
                    report["ran"] = False
                    report["summary"] = ("backend API not reachable after readiness wait "
                                          "(likely mid container-restart) — browser walk skipped")
                    return report

                # ---- 1. AUTH FLOW (staged-form aware, real submit) ----
                token = None
                creds = dict(demo_login) if demo_login else {
                    "email": "testuser_probe@example.com", "password": "Probe123!x", "name": "Test User"}
                # Ensure the account exists (deterministic), then test the LOGIN ui in
                # isolation — driving a multi-step SIGNUP ui is flaky; the real question is
                # whether the login form is wired to the API (Microsoft/Google staged logins
                # were false-flagged 'broken' when the engine fell through to logging in as a
                # never-registered user). With no api_base we still drive the form best-effort.
                if register and api_base_url:
                    _api_register(api_base_url, creds)
                try:
                    await page.goto(base_url + "/login", wait_until="networkidle", timeout=20000)
                    has_submit = await page.locator(
                        "button[type=submit], form button, button").count() > 0
                    step("login form has a submit control", has_submit,
                         "" if has_submit else "no clickable submit — the auth form is not usable")
                    token = await _drive_auth_form(page, creds)
                    url = page.url
                    path = url.split("?", 1)[0]
                    navigated = not any(seg in path for seg in _AUTH_ROUTE_SEGS)
                    ok_auth = bool(token) and navigated
                    step("auth flow stores a token + navigates into the app", ok_auth,
                         "" if ok_auth else f"login did nothing: token={bool(token)} url={url} — the form is not wired to the API")
                except Exception as exc:
                    step("auth flow", False, f"exception: {exc}")

                # ---- 2 + 3. visit each page, screenshot, blank/console checks ----
                for pg in pages or []:
                    route = str((pg or {}).get("route") or "").strip()
                    name = str((pg or {}).get("name") or route or "page")
                    if not route:
                        continue
                    route_is_auth = any(seg in route for seg in _AUTH_ROUTE_SEGS)
                    cerr.clear()
                    rec: Dict[str, Any] = {"name": name, "route": route, "ok": False, "blank": True,
                                           "console_errors": [], "shot": None,
                                           "redirected_to_login": False}
                    try:
                        await page.goto(base_url + route, wait_until="networkidle", timeout=20000)
                        await page.wait_for_timeout(900)
                        probe = await page.evaluate(_PROBE)
                        # #68 (outlook run-56, live): RETRY a would-be-blank read
                        # before flagging it. A React page under nested routing +
                        # a data fetch can still be mounting at 900ms — run-56 saw
                        # 9 FALSE 'blank' pages (inconsistent between two walks —
                        # the tell of a race) while a manual 1500ms capture of the
                        # SAME routes rendered full content (inbox rows, calendar
                        # grid). A false blank wastes the whole deferral budget
                        # (30min) + escapes + files bogus P0s. Re-poll up to ~3.6s
                        # more; the page only stays 'blank' if it genuinely never
                        # renders content.
                        _tl = probe.get("textLen", 0)
                        if _tl < _MIN_TEXT:
                            for _ in range(3):
                                await page.wait_for_timeout(1200)
                                probe = await page.evaluate(_PROBE)
                                _tl = probe.get("textLen", 0)
                                if _tl >= _MIN_TEXT:
                                    break
                        rec["blank"] = (_tl < _MIN_TEXT)
                        rec["sample"] = probe.get("sample", "")
                        rec["controls"] = probe.get("buttons", 0) + probe.get("inputs", 0)
                        # HOLLOW-PAGE detection: the test-user is logged in (token stored
                        # above), so a PROTECTED route that bounces to the auth URL OR
                        # renders the login form in place (password field + sign-in copy)
                        # means the app could not restore the session — every protected
                        # page is unusable even though it builds/serves. This is the wall
                        # of identical Sign-in captures a hollow frontend ships (outlook MM
                        # 2026-06-29: a hardcoded absolute API origin made every call fail).
                        final_path = (page.url or "").split("?", 1)[0]
                        landed_on_auth = any(seg in final_path for seg in _AUTH_ROUTE_SEGS)
                        looks_like_login = bool(probe.get("pw")) and bool(probe.get("signin"))
                        if not route_is_auth and (landed_on_auth or looks_like_login):
                            rec["redirected_to_login"] = True
                            rec["note"] = ("protected page is the LOGIN form (session not "
                                           f"restored): url={page.url}")
                        dest = out_dir / f"{name}.png"
                        await page.screenshot(path=str(dest))
                        rec["shot"] = str(dest)
                        report["shots"][name] = str(dest)
                        rec["console_errors"] = list(cerr)[:5]
                        rec["ok"] = (not rec["blank"]) and not cerr and not rec["redirected_to_login"]
                    except Exception as exc:
                        rec["note"] = f"navigation failed: {exc}"
                    report["pages"].append(rec)
            finally:
                await browser.close()
    except Exception as exc:
        report["summary"] = f"browser test-user error: {exc}"
        return report

    return _finalize_walkthrough(report)


def _finalize_walkthrough(report: Dict[str, Any]) -> Dict[str, Any]:
    """Roll the per-page records + auth steps into the verdict fields the consumers read
    (auth_ok / blank_pages / error_pages / auth_redirect_pages / hollow_frontend). Pure —
    extracted from the async walkthrough so the HOLLOW verdict is unit-testable with a
    synthetic report (the browser path can't run in the test suite)."""
    pages = report.get("pages") or []
    steps = report.get("steps") or []
    blanks = [p["name"] for p in pages if p.get("blank")]
    errs = [p["name"] for p in pages if p.get("console_errors")]
    redirected = [p["name"] for p in pages if p.get("redirected_to_login")]
    auth_ok = all(s["ok"] for s in steps) if steps else False
    report["auth_ok"] = auth_ok
    report["blank_pages"] = blanks
    report["error_pages"] = errs
    report["auth_redirect_pages"] = redirected
    # HOLLOW FRONTEND: the app builds + serves, the login form is present, but a logged-in
    # user cannot actually reach the app — at least half the PROTECTED pages bounce to the
    # login form. A milestone in this state must NOT ship (the gate reads this flag); it is
    # the definitive "shipped a login wall / empty shell" signal, independent of the root
    # cause (failed API origin, fragile auth-restore, missing route guard).
    protected = [p for p in pages
                 if not any(seg in str(p.get("route") or "") for seg in _AUTH_ROUTE_SEGS)]
    report["hollow_frontend"] = bool(protected) and len(redirected) >= max(1, (len(protected) + 1) // 2)
    report["summary"] = (
        f"auth_ok={auth_ok}; pages={len(pages)}; "
        f"blank={blanks or '∅'}; console_errors={errs or '∅'}; "
        f"login_wall={redirected or '∅'}; hollow={report['hollow_frontend']}")
    return report


async def judge_against_references(
    report: Dict[str, Any],
    reference_images: List[Any],
    llm: Any,
    *,
    judge_fn: Optional[Callable] = None,
    min_similarity: Optional[float] = None,
) -> Dict[str, Any]:
    """Wire the visual-fidelity judge into the browser test-user (PIPELINE_HANDOFF §5/§8.1).

    The browser walkthrough already captured a screenshot per route; here we LLM-compare
    each captured page to the reference image that depicts that route (matched by route via
    ``visual_fidelity.map_reference_screens``) so the feedback the lane gets is not just
    "blank/console-error" but "inbox doesn't match outlook_inbox.png — missing folder rail".

    Mutates + returns ``report``: each judged page gets ``page['visual'] =
    {similarity, passed, deviations, summary}``; a rolled-up ``report['visual_mismatches']``
    lists the page names that fell below threshold. Best-effort: no references, no captured
    shots, or a judge that errors → the page is left unjudged, never raises into the loop."""
    if min_similarity is None:
        try:
            min_similarity = float(os.environ.get("ENVGEN_VISUAL_MIN", "0.65"))
        except Exception:
            min_similarity = 0.65
    report.setdefault("visual_mismatches", [])
    refs = list(reference_images or [])
    pages = report.get("pages") or []
    if not refs or not pages:
        return report
    try:
        from .visual_fidelity import map_reference_screens, judge_screen_pair
    except Exception:  # pragma: no cover - import guard
        return report
    judge = judge_fn or judge_screen_pair
    # Routes we actually walked are the only ones that can have a screenshot to judge.
    walked = {str(p.get("route") or "").strip() for p in pages if p.get("route")}
    by_route = {str(p.get("route") or "").strip(): p for p in pages if p.get("shot")}
    screens = map_reference_screens(refs, walked)
    mismatches: List[str] = []
    for screen in screens:
        route = str(screen.get("route") or "").strip()
        if not route:
            continue
        page = by_route.get(route)
        if not page or not page.get("shot"):
            continue
        try:
            verdict = await judge(llm, screen, page["shot"])
        except Exception as exc:  # a broken judge must not crash the loop
            verdict = {"similarity": 0.0, "deviations": [f"judge error: {exc}"[:160]], "summary": ""}
        sim = float(verdict.get("similarity") or 0.0)
        passed = sim >= min_similarity
        page["visual"] = {
            "reference": Path(str(screen.get("path") or "")).name,
            "similarity": sim,
            "passed": passed,
            "deviations": [str(x)[:200] for x in (verdict.get("deviations") or [])][:8],
            "summary": str(verdict.get("summary", ""))[:200],
        }
        if not passed:
            mismatches.append(str(page.get("name") or route))
    report["visual_mismatches"] = mismatches
    return report


def format_feedback(report: Mapping[str, Any]) -> str:
    """Render the test-user report as a remediation message the orchestrator routes
    back to the frontend lane (the 'give feedback, keep fixing' step)."""
    if not report.get("ran"):
        return f"Test-user could not run: {report.get('summary', 'unknown')}"
    lines = [f"TEST-USER report — {report.get('summary', '')}"]
    if report.get("hollow_frontend"):
        lines.append(
            "  ‼ HOLLOW FRONTEND: logged in, but the PROTECTED pages "
            f"{report.get('auth_redirect_pages')} render the LOGIN form — the app is "
            "unusable. The session is not restored on a fresh page load. Most common cause: "
            "the api client targets an ABSOLUTE/wrong origin instead of a same-origin "
            "RELATIVE path (so it bypasses the nginx proxy / hits the wrong port and every "
            "call incl. login fails). Use relative '/api', '/auth' URLs and restore auth on "
            "load via the canonical /api/auth/me. Fix this FIRST — it blocks delivery.")
    for s in report.get("steps", []):
        lines.append(f"  [{'OK' if s['ok'] else 'FAIL'}] {s['step']}" + (f" — {s['note']}" if s.get('note') else ""))
    for p in report.get("pages", []):
        flags = []
        if p.get("blank"):
            flags.append("BLANK (renders no real content)")
        if p.get("redirected_to_login"):
            flags.append("REDIRECTED TO LOGIN (session not restored — protected page shows the auth form)")
        if p.get("console_errors"):
            flags.append("console errors: " + "; ".join(p["console_errors"])[:120])
        if flags:
            lines.append(f"  [{p['route']}] " + " · ".join(flags))
        vis = p.get("visual")
        if vis and not vis.get("passed"):
            ref = vis.get("reference") or "the reference"
            lines.append(f"  [{p['route']}] VISUAL {vis.get('similarity', 0):.2f} — does NOT "
                         f"match reference {ref}:")
            for d in (vis.get("deviations") or [])[:6]:
                lines.append(f"      - {d}")
    return "\n".join(lines)


def browser_report_unusable(report: Optional[Mapping[str, Any]]) -> bool:
    """PRE-RELEASE GATE predicate (2026-06-30): True iff the browser walk RAN and found an
    OBJECTIVE "a real user cannot use this app" signal — login broken (``auth_ok`` False),
    protected pages rendering BLANK (``blank_pages``), or bounced to a LOGIN WALL
    (``auth_redirect_pages`` / ``hollow_frontend``). The delivery flow uses this to HOLD a
    release so a non-functional UI never ships as "delivered".

    Deliberately EXCLUDES the SOFT signals ``visual_mismatches`` and ``error_pages`` (console
    errors): those stay ADVISORY — the walk still dispatches them as a P0 remediation task,
    but a minor visual deviation or a benign console warning must NOT block delivery. A report
    that could not run (None / ``ran`` False) is NOT "unusable" — infra must never block a
    release, and a one-off flake auto-clears on the next cycle's re-test. Pure + env-agnostic
    so the gate criteria are unit-testable in isolation."""
    if not isinstance(report, dict) or not report.get("ran"):
        return False
    return bool((not report.get("auth_ok")) or report.get("blank_pages")
                or report.get("auth_redirect_pages") or report.get("hollow_frontend"))


def browser_gate_decision(report: Mapping[str, Any], squad_decision: str) -> str:
    """FIX #152 — 'defer' | 'release'. Given the app is UNUSABLE (browser_report_unusable
    already True) and the bounded escape's verdict (``squad_decision`` from
    squad_release_decision), decide whether to actually release.

    A HARD-unusable app — login itself is broken (``auth_ok`` False) or a logged-in user is
    bounced to a LOGIN WALL on the app's own pages (``hollow_frontend``) — must NEVER
    escape-release: a milestone nobody can even log into is worthless, so hold it (→ the
    75-min FAIL-FAST STUCK is the honest outcome, not shipping a dead app). googlemaps run-4:
    a bare-fetch/no-token UI 401'd every core page to /login, the test-user caught it, yet
    the 900s/3-attempt escape shipped it after 9614s/7 attempts. SOFT-unusable (auth works,
    only a secondary page blank or a benign console error) keeps the bounded escape so a
    minor defect never deadlocks the run. ENVGEN_TESTUSER_HARD_GATE=0 restores the old
    always-escape (safety valve if the hard gate ever false-STUCKs). Pure + env-agnostic."""
    import os as _os
    if str(_os.environ.get("ENVGEN_TESTUSER_HARD_GATE", "1")).strip().lower() in (
            "0", "false", "no", "off"):
        return squad_decision
    if not report.get("auth_ok") or report.get("hollow_frontend"):
        return "defer"  # hard-unusable: never escape a dead app
    return squad_decision  # soft-unusable: honor the bounded escape
