"""Frontend module — INFRA ONLY (user decision 2026-06-11).

The framework no longer authors ANY frontend UI content. The page projector,
the catalog of fallback pages, the generic list/detail/form templates, the
auth-page templates, the router-shell rewrite, the placeholder pages and the
theme maps are all REMOVED: framework-authored UI inevitably encodes one
product's shape (the audit found an Instagram catalog, a /feed landing, a
dark-zinc aesthetic) and caps the diversity of what the pipeline can build.

The lane authors the whole UI. What enforces quality instead of templates:
  * ``frontend_navigable`` — a release must ship >=1 page and >=1 route;
  * ``frontend_dead_controls`` — interactive markup must be bound to handlers;
  * ``business_chain`` — verifier-authored API chains must pass;
  * the visual-fidelity gate — screens must match the references;
  * the test-user browser flows — a human-like signup/login must work.
A failure feeds back to the frontend lane as remediation (the agent retries);
the framework never "fills in" UI for it.

What REMAINS here is pure infrastructure, not product content:
  * ``_PAGE_MARKER`` — legacy marker constant; validation still counts marked
    files in old trees (new trees simply have none);
  * ``_ensure_api_helpers`` — build-integrity repair of the api.js surface
    (apiGet/apiPost glue + the fixed 401→/login auth contract).
"""

from __future__ import annotations

from pathlib import Path

_PAGE_MARKER = "// framework-generated page (frontend_page_projector) — edits are overwritten"


def _ensure_api_helpers(api_js: Path) -> bool:
    """Guarantee ``apiGet``/``apiPost`` exports exist — the projected pages import
    them, so their absence is a hard build error. When the lane's service module
    has a ``request()`` helper, delegate to it; otherwise append SELF-CONTAINED
    fetch-based helpers (the old "unknown shape → don't risk it" bail shipped a
    final tree that did not build: pages imported apiGet from an api.js that only
    exported a bare ``api`` object — instagram 2026-06-10 08:29)."""
    if not api_js.exists():
        return False
    src = api_js.read_text(encoding="utf-8")
    # SELF-HEAL: FIX#37 used to stub projector-owned names with throwing
    # placeholders; strip those so the real helpers install below.
    if "not implemented (auto-stub)" in src:
        src = "\n".join(
            ln for ln in src.splitlines()
            if not (("apiGet" in ln or "apiPost" in ln)
                    and "not implemented (auto-stub)" in ln))
        api_js.write_text(src + ("\n" if not src.endswith("\n") else ""),
                          encoding="utf-8")
        src = api_js.read_text(encoding="utf-8")
    if "export async function apiGet" in src or "export const apiGet" in src:
        if "_bcAuthRedirect" in src or "// === BY-CONSTRUCTION" not in src:
            return False  # lane's own helpers, or already the current version
        # UPGRADE an older BY-CONSTRUCTION block (no 401→/login redirect): cut the
        # appended block and fall through to re-append the current version.
        src = src[: src.index("\n\n// === BY-CONSTRUCTION")]
    # On 401, redirect to /login (an unauthenticated visit to a protected page
    # otherwise renders an empty screen with a console full of 401s).
    _redirect = (
        "function _bcAuthRedirect() {\n"
        "  if (window.location.pathname !== '/login') {\n"
        "    localStorage.removeItem('token');\n"
        "    window.location.assign('/login');\n"
        "  }\n"
        "}\n\n"
    )
    if "function request(" in src:
        helpers = (
            "\n\n// === BY-CONSTRUCTION: generic helpers for projected pages.\n"
            + _redirect +
            "export async function apiGet(path) {\n"
            "  try { return await request(path); }\n"
            "  catch (e) { if (String(e).includes('401')) _bcAuthRedirect(); throw e; }\n"
            "}\n\n"
            "export async function apiPost(path, body) {\n"
            "  try { return await request(path, { method: 'POST', body }); }\n"
            "  catch (e) { if (String(e).includes('401')) _bcAuthRedirect(); throw e; }\n"
            "}\n"
        )
    else:
        helpers = (
            "\n\n// === BY-CONSTRUCTION: self-contained helpers for projected pages.\n"
            + _redirect +
            "async function _bcFetch(path, opts = {}) {\n"
            "  const token = localStorage.getItem('token') || localStorage.getItem('access_token');\n"
            "  const res = await fetch(path, {\n"
            "    ...opts,\n"
            "    headers: {\n"
            "      'Content-Type': 'application/json',\n"
            "      ...(token ? { Authorization: `Bearer ${token}` } : {}),\n"
            "      ...(opts.headers || {}),\n"
            "    },\n"
            "  });\n"
            "  if (res.status === 401) { _bcAuthRedirect(); throw new Error('HTTP 401'); }\n"
            "  if (!res.ok) throw new Error(`HTTP ${res.status}`);\n"
            "  return res.json();\n"
            "}\n\n"
            "export async function apiGet(path) {\n  return _bcFetch(path);\n}\n\n"
            "export async function apiPost(path, body) {\n"
            "  return _bcFetch(path, { method: 'POST', body: JSON.stringify(body) });\n}\n"
        )
    api_js.write_text(src.rstrip() + helpers, encoding="utf-8")
    return True
