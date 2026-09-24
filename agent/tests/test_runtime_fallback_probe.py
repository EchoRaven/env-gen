"""FIX #224 — runtime per-route verification of the DELIVERED DOM.

Source-level gates (#222/#223) can in principle be gamed by rewriting files;
the browser walkthrough asserts what a real user's DOM actually shows per
route (IRON-LAW #172: runtime-verify the DELIVERED app):

- any walked page whose live DOM carries [data-fallback] → fallback_dom_pages
  → HARD hold (never escape-released);
- per-route seed rendering: a data page whose own text shows NO salient seed
  value → dataless_pages (SOFT/advisory — pages that populate only under a
  query must not deadlock a run).
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _PROBE, _finalize_walkthrough, browser_report_unusable,
    browser_gate_decision, format_feedback,
)


def _report(pages):
    return {"ran": True, "pages": pages,
            "steps": [{"step": "login", "ok": True}],
            "real_data": {"checked": True, "rendered": True, "matched": ["x"]}}


def test_probe_counts_fallback_dom():
    assert "[data-fallback]" in _PROBE
    assert "fbEls" in _PROBE


def test_fallback_dom_pages_hard_hold():
    rep = _finalize_walkthrough(_report([
        {"name": "feed", "route": "/", "blank": False, "fallback_dom": True},
        {"name": "explore", "route": "/explore", "blank": False,
         "fallback_dom": False},
    ]))
    assert rep["fallback_dom_pages"] == ["feed"]
    assert browser_report_unusable(rep)
    # HARD: never escape-released, even when the bounded squad says release
    assert browser_gate_decision(rep, "release") == "defer"


def test_blank_fallback_not_double_counted():
    rep = _finalize_walkthrough(_report([
        {"name": "feed", "route": "/", "blank": True, "fallback_dom": True},
    ]))
    assert rep["fallback_dom_pages"] == []          # blank already holds it


def test_dataless_pages_soft_advisory():
    """Non-primary routes: dataless stays advisory (#231d hardens only '/')."""
    rep = _finalize_walkthrough(_report([
        {"name": "feed", "route": "/feed", "blank": False,
         "route_seed_hit": False},
        {"name": "messages", "route": "/messages", "blank": False,
         "route_seed_hit": True},
        {"name": "login", "route": "/login", "blank": False,
         "route_seed_hit": False},
    ]))
    assert rep["dataless_pages"] == ["feed"]        # auth routes excluded
    assert not browser_report_unusable(rep)         # SOFT — never a hold alone
    assert browser_gate_decision(rep, "release") == "release"


def test_feedback_mentions_fallback_and_dataless():
    rep = _finalize_walkthrough(_report([
        {"name": "feed", "route": "/", "blank": False, "fallback_dom": True,
         "route_seed_hit": False},
    ]))
    fb = format_feedback(rep)
    assert "FALLBACK PAGE" in fb
    assert "NO SEED DATA" in fb


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_primary_route_dataless_hard_hold():
    """#231d (r21): the DELIVERED home feed rendered 'No videos found' while
    the API served 39 items — global real_data cleared on 2 category labels in
    tab chrome, and dataless stayed advisory. The app's PRIMARY route ('/')
    rendering zero seed data is a hard hold; other routes stay advisory."""
    rep = _finalize_walkthrough(_report([
        {"name": "home", "route": "/", "blank": False, "route_seed_hit": False},
        {"name": "explore", "route": "/explore", "blank": False,
         "route_seed_hit": True},
    ]))
    assert rep["primary_dataless"] is True
    assert browser_report_unusable(rep)
    assert browser_gate_decision(rep, "release") == "defer"
    # a populated primary route holds nothing
    rep2 = _finalize_walkthrough(_report([
        {"name": "home", "route": "/", "blank": False, "route_seed_hit": True},
        {"name": "settings", "route": "/settings", "blank": False,
         "route_seed_hit": False},
    ]))
    assert rep2["primary_dataless"] is False
    assert not browser_report_unusable(rep2)
