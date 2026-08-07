"""Runtime control-exercise pass for the browser test-user (2026-06-22, design §3.2).

The browser test-user historically only COUNTED controls per page (blank-vs-not) and
clicked nothing but the auth form, so a button that renders but does the WRONG thing —
posts to the wrong endpoint, shows a success toast on a failed call, or navigates
nowhere — passed every check (static audit sees a bound handler, the walkthrough never
clicks it, the visual judge only sees its pixels).

This module ENUMERATES every interactive control on a page, clicks each from a freshly
reset page state, captures the OBSERVED EFFECT (navigation, the /api calls it fired +
their statuses, DOM mutation, console errors), classifies that effect, and cross-checks
the fired calls against the contract. A control whose intent implies a write (save /
send / create / delete / submit) but fires no call, fires an OFF-CONTRACT call, or draws
a 5xx is flagged deterministically; the remainder can be judged by an LLM against the
control's declared intent.

Design: PURE helpers (canonicalisation, contract matching, effect classification, verdict
aggregation — unit-tested without a browser) + a thin async Playwright driver that never
raises into the validation loop.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Verbs in a control's accessible label that imply it MUTATES server state. Used to flag a
# write-looking control that fires no network call (a dead/inert button) deterministically,
# without needing the LLM. Kept domain-neutral (no app-specific vocab).
# R3(b): the original UI-action vocabulary (save/send/submit/…) UNIONED with the #557
# mutation-verb set (play/start/resume/watch/rate/like/mark/toggle/track/progress/…) so a
# STATE-BEARING control — a play/resume/rate/toggle button — that fires NO persisting call is
# flagged as a dead control too (the class the old set missed). Matched by WORD-PART in
# ``implies_write`` (not substring) so 'display'/'playlist'/'address' do NOT false-hit.
_UI_ACTION_WORDS = frozenset({
    "save", "send", "create", "add", "new", "submit", "post", "publish", "update",
    "edit", "delete", "remove", "archive", "upload", "confirm", "apply", "invite",
})
try:  # reuse #557's mutation vocabulary + splitter (single source; no product literals)
    from .completeness_audit import (
        _MUTATION_VERBS as _CA_MUTATION_VERBS, _split_ident as _split_label)
    _WRITE_INTENT_WORDS = frozenset(_UI_ACTION_WORDS | set(_CA_MUTATION_VERBS))
except Exception:  # keep the pure helpers self-contained if the classifier is unavailable
    _WRITE_INTENT_WORDS = frozenset(_UI_ACTION_WORDS | {
        "play", "start", "resume", "watch", "rate", "like", "mark", "toggle",
        "progress", "track",
    })

    def _split_label(name: Any) -> List[str]:  # minimal fallback (mirrors _split_ident)
        s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or "").strip())
        return [p.lower() for p in re.split(r"[^A-Za-z0-9]+", s) if p]
# Labels we must NOT click during an exercise pass — they end the session or leave the app,
# poisoning every subsequent probe. (Logout/sign-out + external links.)
_SKIP_INTENT_WORDS = ("log out", "logout", "sign out", "signout")


def norm_method_path(method: str, path: str) -> Tuple[str, str]:
    """Canonical (METHOD, path) for contract matching — param-name agnostic.

    Mirrors route_projector._norm_route / registryhub.endpoint_id: upper method,
    strip query/trailing slash, collapse every ``{param}``/``:id``/``${x}`` segment to
    ``{}`` so ``/api/notes/{id}`` ≡ ``/api/notes/{note_id}`` ≡ ``/api/notes/:id``.
    """
    m = (method or "GET").strip().upper()
    p = (path or "").split("?", 1)[0].split("#", 1)[0]
    # express :id and ${x} → {}
    p = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "{}", p)
    p = re.sub(r"\$\{[^}]+\}", "{}", p)
    p = re.sub(r"\{[^}]+\}", "{}", p)
    if len(p) > 1:
        p = p.rstrip("/")
    return m, p or "/"


def path_from_url(url: str) -> str:
    """Extract the path component from an absolute or relative URL (no host, no query)."""
    if not url:
        return ""
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/]+", "", url)  # strip scheme://host
    return s.split("?", 1)[0].split("#", 1)[0] or "/"


def build_contract_index(business_eps: Sequence[Mapping[str, Any]]) -> set:
    """Set of canonical (METHOD, normpath) for every registered business endpoint."""
    idx = set()
    for ep in business_eps or []:
        if not isinstance(ep, Mapping):
            continue
        path = str(ep.get("path") or "")
        if not path:
            continue
        idx.add(norm_method_path(str(ep.get("method") or "GET"), path))
    return idx


def is_api_call(url: str) -> bool:
    """A network request we care about: an /api (or /auth) call, not a static asset."""
    p = path_from_url(url)
    return p.startswith("/api") or p.startswith("/auth")


def _path_matches_template(concrete: str, template: str) -> bool:
    """A CONCRETE path (``/api/notes/42``) matches a contract TEMPLATE (``/api/notes/{}``) iff
    same segment count and every template segment is ``{}`` (wildcard) or equals the concrete one.
    """
    cs = [s for s in concrete.strip("/").split("/") if s]
    ts = [s for s in template.strip("/").split("/") if s]
    if len(cs) != len(ts):
        return False
    return all(t == "{}" or t == c for c, t in zip(cs, ts))


def matches_contract(method: str, concrete_path: str, contract_index: set) -> bool:
    """True if a concrete (method, path) the app actually called matches ANY declared endpoint
    template — matched structurally so a real id segment lines up with a ``{}`` param."""
    m = (method or "GET").strip().upper()
    return any(cm == m and _path_matches_template(concrete_path, ct)
               for (cm, ct) in contract_index)


def off_contract_calls(
    calls: Sequence[Mapping[str, Any]], contract_index: set
) -> List[Dict[str, Any]]:
    """API calls a control fired that match NO declared endpoint (structural, param-aware).

    A frontend that calls ``/api/videos/{id}`` when the contract only declares ``/api/videos``
    or ``/watch`` (the YouTube WatchPage bug) surfaces here; a call to a declared item route
    like ``/api/notes/42`` (contract ``/api/notes/{id}``) does NOT (its id lines up with ``{}``).
    Reports the CONCRETE path the app actually called.
    """
    out: List[Dict[str, Any]] = []
    for c in calls or []:
        if not isinstance(c, Mapping):
            continue
        url = str(c.get("url") or c.get("path") or "")
        if not is_api_call(url):
            continue
        method = str(c.get("method") or "GET").upper()
        concrete = path_from_url(url)
        if not matches_contract(method, concrete, contract_index):
            out.append({"method": method, "path": concrete, "status": c.get("status")})
    return out


def implies_write(label: str) -> bool:
    """A control whose accessible label implies it MUTATES server state. Word-part matched
    (exact for short verbs, prefix for len>=4 — reusing the #557 splitter) so 'Resume',
    'Rate', 'Mark read', 'Save' hit while 'display'/'playlist'/'address' do NOT. Domain-
    neutral (UI-action + #557 mutation vocabulary), no product literals."""
    for p in _split_label(label):
        for w in _WRITE_INTENT_WORDS:
            if p == w or (len(w) >= 4 and p.startswith(w)):
                return True
    return False


def should_skip(label: str) -> bool:
    low = (label or "").strip().lower()
    return any(w in low for w in _SKIP_INTENT_WORDS)


def classify_effect(record: Mapping[str, Any]) -> str:
    """Bucket a click's observed effect.

    Precedence: server_error > off_contract > navigation > network_write >
    network_read > dom_mutation > console_error > no_effect.
    """
    calls = list(record.get("network") or [])
    statuses = [c.get("status") for c in calls if isinstance(c, Mapping)]
    if any(isinstance(s, int) and s >= 500 for s in statuses):
        return "server_error"
    if record.get("off_contract"):
        return "off_contract"
    if record.get("navigated"):
        return "navigation"
    writes = [c for c in calls
              if isinstance(c, Mapping) and str(c.get("method") or "GET").upper()
              in ("POST", "PUT", "PATCH", "DELETE")]
    if writes:
        return "network_write"
    if calls:
        return "network_read"
    if record.get("dom_changed"):
        return "dom_mutation"
    if record.get("console_errors"):
        return "console_error"
    return "no_effect"


def evaluate_control(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Deterministic verdict for one exercised control (no LLM).

    Returns ``{effect, dead, error, off_contract, reason}``. ``dead``/``error`` are the
    high-confidence "this button is broken" signals; ``off_contract`` flags a wrong-target
    call. Whether a SOUND-looking control truly matches its meaning is left to the LLM judge.
    """
    effect = classify_effect(record)
    label = str(record.get("label") or "")
    dead = False
    error = effect == "server_error"
    reason = ""
    if effect == "server_error":
        reason = "click triggered a 5xx server error"
    elif effect == "off_contract":
        oc = record.get("off_contract") or []
        reason = "fired an off-contract API call: " + ", ".join(
            f"{c.get('method')} {c.get('path')}" for c in oc[:3])
    elif effect in ("no_effect", "console_error") and implies_write(label):
        # A "Save/Send/Create/Delete" control that did nothing observable is the classic
        # dead-on-click button — present, visually plausible, but not wired.
        dead = True
        reason = (f"'{label}' looks like a write action but produced no effect"
                  + (" (console error only)" if effect == "console_error" else ""))
    return {
        "effect": effect,
        "dead": dead,
        "error": error,
        "off_contract": list(record.get("off_contract") or []),
        "reason": reason,
    }


def aggregate_control_report(
    page_name: str, route: str, evaluations: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Roll per-control verdicts into a page-level control report."""
    evals = list(evaluations or [])
    dead = [e for e in evals if e.get("dead")]
    errored = [e for e in evals if e.get("error")]
    off = [e for e in evals if e.get("off_contract")]
    return {
        "page": page_name,
        "route": route,
        "controls_exercised": len(evals),
        "dead_controls": [e.get("label") or e.get("reason") for e in dead],
        "error_controls": [e.get("label") or e.get("reason") for e in errored],
        "off_contract_controls": [e.get("reason") for e in off],
        "ok": not (dead or errored or off),
    }


# --------------------------------------------------------------------------------------
# Async Playwright driver (impure; never raises into the loop). Not unit-tested directly —
# the pure helpers above carry the logic; this just drives the browser and records facts.
# --------------------------------------------------------------------------------------

_DESCRIBE_CONTROLS_JS = r"""() => {
  const sel = 'button, a[href], [role=button], input[type=submit], input[type=button], [onclick]';
  const els = Array.from(document.querySelectorAll(sel));
  const out = [];
  for (const el of els) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const label = (el.getAttribute('aria-label') || el.innerText || el.value ||
                   el.getAttribute('title') || '').trim().slice(0, 80);
    out.push({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || ''),
              href: (el.getAttribute('href') || ''), label});
  }
  return out;
}"""

_DOM_SIG_JS = ("() => { const b = document.body; return b ? "
               "(b.innerText.length + ':' + b.querySelectorAll('*').length) : '0:0'; }")


async def _dom_sig(page: Any) -> str:
    try:
        return str(await page.evaluate(_DOM_SIG_JS))
    except Exception:
        return ""


async def exercise_controls(
    page: Any,
    page_url: str,
    contract_index: set,
    *,
    max_controls: int = 25,
    settle_ms: int = 700,
) -> List[Dict[str, Any]]:
    """Enumerate, click, and observe every interactive control on ``page_url``.

    Each control is clicked from a freshly re-navigated page state so clicks are isolated.
    Captures per click: navigation (URL change), the /api|/auth calls fired + statuses,
    DOM-signature change, and console errors; computes off-contract calls vs ``contract_index``.
    Returns a list of raw records (one per control); pass each through ``evaluate_control``.
    Best-effort: any failure yields a partial list, never raises.
    """
    records: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    console_errs: List[str] = []

    def _on_response(resp: Any) -> None:
        try:
            req = resp.request
            url = req.url
            if is_api_call(url):
                calls.append({"method": req.method, "url": url, "status": resp.status})
        except Exception:
            pass

    def _on_console(msg: Any) -> None:
        try:
            if msg.type == "error":
                console_errs.append(str(msg.text)[:200])
        except Exception:
            pass

    page.on("response", _on_response)
    page.on("console", _on_console)
    try:
        try:
            await page.goto(page_url, wait_until="networkidle", timeout=20000)
        except Exception:
            return records
        try:
            descriptors = await page.evaluate(_DESCRIBE_CONTROLS_JS)
        except Exception:
            descriptors = []
        n = min(len(descriptors or []), max_controls)
        for i in range(n):
            desc = descriptors[i] if i < len(descriptors) else {}
            label = str((desc or {}).get("label") or "")
            if should_skip(label):
                continue
            # Reset to a clean page state so each click is observed in isolation.
            try:
                await page.goto(page_url, wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(200)
            except Exception:
                continue
            calls.clear()
            console_errs.clear()
            before_url = page.url
            before_sig = await _dom_sig(page)
            clicked = False
            try:
                loc = page.locator(
                    "button, a[href], [role=button], input[type=submit], "
                    "input[type=button], [onclick]"
                ).nth(i)
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2500, no_wait_after=True)
                    clicked = True
            except Exception:
                clicked = False
            if not clicked:
                continue
            try:
                await page.wait_for_timeout(settle_ms)
            except Exception:
                pass
            after_url = page.url
            after_sig = await _dom_sig(page)
            captured = list(calls)
            rec = {
                "index": i,
                "label": label,
                "tag": (desc or {}).get("tag"),
                "type": (desc or {}).get("type"),
                "route": path_from_url(page_url),
                "navigated": path_from_url(after_url) != path_from_url(before_url),
                "navigated_to": path_from_url(after_url),
                "network": [{"method": c["method"], "path": path_from_url(c["url"]),
                             "status": c.get("status")} for c in captured],
                "dom_changed": bool(after_sig and before_sig and after_sig != before_sig),
                "console_errors": list(console_errs)[:3],
            }
            rec["off_contract"] = off_contract_calls(
                [{"method": c["method"], "url": c["url"], "status": c.get("status")}
                 for c in captured],
                contract_index,
            )
            records.append(rec)
    finally:
        try:
            page.remove_listener("response", _on_response)
            page.remove_listener("console", _on_console)
        except Exception:
            pass
    return records


def build_intent_judge_prompt(
    route: str, records: Sequence[Mapping[str, Any]], page_meta: Optional[Mapping[str, Any]] = None
) -> str:
    """Prompt for the LLM to judge whether each SOUND control's effect matches its intent.

    Only controls that passed the deterministic checks (not dead/error/off-contract) need a
    judgment — does 'Reply' actually open a compose view, does 'Mark read' flip the state.
    """
    meta = page_meta or {}
    lines = [
        f"You are auditing the controls on the '{meta.get('name') or route}' screen (route {route}).",
        "For each control below you are given its label and the OBSERVED EFFECT of clicking it",
        "(navigation target, API calls fired with status, whether the DOM changed).",
        "Decide if the effect MATCHES what the label promises a user.",
        "Return JSON: {\"controls\": [{\"label\": ..., \"matches_intent\": true|false, \"reason\": ...}]}.",
        "",
    ]
    for r in records:
        net = ", ".join(f"{c.get('method')} {c.get('path')}→{c.get('status')}"
                        for c in (r.get("network") or [])) or "no API call"
        lines.append(
            f"- label={r.get('label')!r} tag={r.get('tag')} effect={classify_effect(r)} "
            f"navigated_to={r.get('navigated_to') if r.get('navigated') else 'none'} "
            f"api=[{net}] dom_changed={bool(r.get('dom_changed'))}")
    return "\n".join(lines)
