"""Bounded frontend-page BUILD gate (2026-06-21).

youtube ground truth: the frontend lane DECLARES ui_pages but writes ~0 page bodies
(it burns its action budget on registry/workhub bookkeeping), so the framework's
generic fallback (now a card grid, _PAGE_MARKER + data-fallback) is what ships — a
declared-but-unbuilt page passes the STATIC audit and is marked `implemented`.

This gate detects business pages the lane never built (still the framework fallback)
and lets the deliver flow DEFER (re-dispatching the lane to build them) for a bounded
number of attempts / wall-clock, then ESCAPE to the card-floor fallback. Mirrors the
visual-deferral bounded escape (_visual_release_decision) — it NEVER deadlocks:
block+dispatch for N rounds → release with the usable card fallback.

Pure + deterministic + domain-agnostic; the deliver-flow wiring lives in the
orchestrator (mirrors the visual deferral block).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

# Auth pages are framework-OWNED (the intended login/signup), never "unbuilt".
_AUTH_ROUTES = {"/login", "/signup", "/signin", "/register"}

PAGES_DEFERRAL_ESCAPE_S = 900.0  # max wall-clock a milestone may defer on unbuilt pages
PAGES_ATTEMPT_CAP = 3            # per-milestone re-dispatch attempts before escape


def _unbuilt_with_routes(workhub: Any, app_root: Any) -> List[tuple]:
    """Core walk: (component_name, normalized_route) for each registered BUSINESS ui_page the
    lane never built (file missing OR still the framework fallback marker). Auth pages
    excluded. Best-effort; never raises."""
    out: List[tuple] = []
    try:
        from .frontend_page_projector import _PAGE_MARKER
        from .frontend_scaffold import _page_component_name
    except Exception:
        return out
    # ui_pages are a RegistryHub first-class contract (``list_ui_pages``); older
    # callers passed a workhub with ``get_ui_pages``. Accept either source.
    pages = {}
    if workhub is not None:
        for _meth in ("list_ui_pages", "get_ui_pages"):
            _fn = getattr(workhub, _meth, None)
            if callable(_fn):
                try:
                    pages = _fn() or {}
                except Exception:
                    pages = {}
                break
    if not pages:
        return out
    src = Path(app_root) / "app" / "frontend" / "src" / "pages"
    if not src.is_dir():
        return out
    for name, page in pages.items():
        if not isinstance(page, dict):
            continue
        route = str(page.get("route") or "").strip().lower().rstrip("/")
        if route in _AUTH_ROUTES:
            continue
        comp = _page_component_name(page) or str(name)
        f = src / f"{comp}.jsx"
        try:
            if not f.exists() or _PAGE_MARKER in f.read_text(encoding="utf-8", errors="ignore"):
                out.append((comp, route))
        except Exception:
            continue
    return out


def frontend_unbuilt_pages(workhub: Any, app_root: Any) -> List[str]:
    """Component names of registered BUSINESS ui_pages the lane never built (file missing OR
    still the framework fallback marker). Auth pages excluded. Best-effort, never raises."""
    return [comp for comp, _route in _unbuilt_with_routes(workhub, app_root)]


def referenced_unbuilt_pages(workhub: Any, app_root: Any, reference_routes: Any) -> List[str]:
    """§2 gate-hardening: of the unbuilt pages, those whose route MATCHES a provided reference
    image route. A page the references DEPICT must ship as the REAL page, not the framework
    fallback — so the gate blocks harder on these (see pages_release_decision)."""
    if not reference_routes:
        return []
    refset = {str(r).strip().lower().rstrip("/") for r in reference_routes}
    return [comp for comp, route in _unbuilt_with_routes(workhub, app_root)
            if route and route in refset]


def pages_release_decision(deferred_since: Optional[float], attempts: int, now: float,
                           *, attempt_cap: int = PAGES_ATTEMPT_CAP,
                           escape_s: float = PAGES_DEFERRAL_ESCAPE_S,
                           has_referenced_unbuilt: bool = False) -> str:
    """Bounded decision for the unbuilt-pages deferral. Returns:
      * ``"defer"``   — keep blocking the release; re-dispatch the lane to build.
      * ``"release"`` — escape: deliver with the card-floor fallback (no deadlock).
    Escapes (so the deferral ALWAYS terminates): wall-clock since the FIRST defer
    exceeds escape_s (anchored, not reset by lane churn), OR the attempt budget is
    spent. §2 gate-hardening: when an unbuilt page is one the REFERENCES depict
    (``has_referenced_unbuilt``), block HARDER — double the attempt + wall-clock budget
    so the lane gets more chances to ship the REAL page before falling back (still bounded;
    never a hard deadlock)."""
    if has_referenced_unbuilt:
        attempt_cap *= 2
        escape_s *= 2
    if deferred_since is not None and (now - deferred_since) > escape_s:
        return "release"
    if attempts >= attempt_cap:
        return "release"
    return "defer"
