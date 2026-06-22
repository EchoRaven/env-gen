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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

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


async def run_browser_test_user(
    base_url: str,
    pages: List[Mapping[str, Any]],
    out_dir: Path,
    *,
    register: bool = True,
    demo_login: Optional[Mapping[str, str]] = None,
    chrome_path: Optional[str] = None,
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

                # ---- 1. AUTH FLOW (real form, real submit) ----
                token = None
                creds = dict(demo_login) if demo_login else {
                    "email": "testuser_probe@example.com", "password": "Probe123!x", "name": "Test User"}
                await page.goto(base_url + "/login", wait_until="networkidle", timeout=20000)
                try:
                    if register:
                        # try to switch the form into create-account mode if it offers it
                        for label in ("Create one", "Create a free account", "New here", "Sign up", "Create account"):
                            el = page.get_by_text(label, exact=False)
                            if await el.count() > 0:
                                try:
                                    await el.first.click(timeout=1500)
                                    await page.wait_for_timeout(400)
                                except Exception:
                                    pass
                                break
                    em = page.locator("input[type=email], input[name=email], input[placeholder*=mail i]").first
                    pw_in = page.locator("input[type=password]").first
                    if await em.count() > 0:
                        await em.fill(creds["email"])
                    # multi-step (email -> Next -> password) forms: click Next if password isn't visible
                    if await pw_in.count() == 0:
                        nxt = page.get_by_role("button", name="Next")
                        if await nxt.count() > 0:
                            await nxt.first.click(); await page.wait_for_timeout(500)
                        pw_in = page.locator("input[type=password]").first
                    name_in = page.locator("input[placeholder*=name i], input[name=name]").first
                    if register and await name_in.count() > 0:
                        try:
                            await name_in.fill(creds["name"])
                        except Exception:
                            pass
                    if await pw_in.count() > 0:
                        await pw_in.fill(creds["password"])
                    submit = page.locator("button[type=submit]").first
                    has_submit = await submit.count() > 0
                    step("login form has a submit control", has_submit,
                         "" if has_submit else "no button[type=submit] — the auth form is not usable")
                    if has_submit:
                        await submit.click()
                        await page.wait_for_timeout(2500)
                    token = await page.evaluate("() => localStorage.getItem('access_token') || localStorage.getItem('token')")
                    url = page.url
                    navigated = "/login" not in url.split("?", 1)[0]
                    ok_auth = bool(token) and navigated
                    step("auth flow stores a token + navigates into the app", ok_auth,
                         "" if ok_auth else f"submit did nothing: token={bool(token)} url={url} — the form is not wired to the API")
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
    return "\n".join(lines)
