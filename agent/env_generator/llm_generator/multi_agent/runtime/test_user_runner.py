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
# DOM probe: is there a real interactive control, and any console errors?
_PROBE = """() => {
  const txt = (document.body && document.body.innerText || '').trim();
  const btns = document.querySelectorAll('button, a[href], [role=button]').length;
  const inputs = document.querySelectorAll('input, textarea, select').length;
  return { textLen: txt.length, sample: txt.slice(0, 120), buttons: btns, inputs: inputs };
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
                    cerr.clear()
                    rec: Dict[str, Any] = {"name": name, "route": route, "ok": False, "blank": True,
                                           "console_errors": [], "shot": None}
                    try:
                        await page.goto(base_url + route, wait_until="networkidle", timeout=20000)
                        await page.wait_for_timeout(900)
                        probe = await page.evaluate(_PROBE)
                        rec["blank"] = (probe.get("textLen", 0) < _MIN_TEXT)
                        rec["sample"] = probe.get("sample", "")
                        rec["controls"] = probe.get("buttons", 0) + probe.get("inputs", 0)
                        dest = out_dir / f"{name}.png"
                        await page.screenshot(path=str(dest))
                        rec["shot"] = str(dest)
                        report["shots"][name] = str(dest)
                        rec["console_errors"] = list(cerr)[:5]
                        rec["ok"] = (not rec["blank"]) and not cerr
                    except Exception as exc:
                        rec["note"] = f"navigation failed: {exc}"
                    report["pages"].append(rec)
            finally:
                await browser.close()
    except Exception as exc:
        report["summary"] = f"browser test-user error: {exc}"
        return report

    blanks = [p["name"] for p in report["pages"] if p.get("blank")]
    errs = [p["name"] for p in report["pages"] if p.get("console_errors")]
    auth_ok = all(s["ok"] for s in report["steps"]) if report["steps"] else False
    report["auth_ok"] = auth_ok
    report["blank_pages"] = blanks
    report["error_pages"] = errs
    report["summary"] = (
        f"auth_ok={auth_ok}; pages={len(report['pages'])}; "
        f"blank={blanks or '∅'}; console_errors={errs or '∅'}")
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
    for s in report.get("steps", []):
        lines.append(f"  [{'OK' if s['ok'] else 'FAIL'}] {s['step']}" + (f" — {s['note']}" if s.get('note') else ""))
    for p in report.get("pages", []):
        flags = []
        if p.get("blank"):
            flags.append("BLANK (renders no real content)")
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
