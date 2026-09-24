"""FIX #181 — run-14 showed the test-user SQUAD passing (0 P0) a build the deterministic browser
gate correctly FAILED (auth_ok=False, fake_map=['home_map'], no_real_data) — TWICE, escalating.
The squad's per-page browser goal only said "renders real content (not blank/placeholder)", too
vague to make the LLM agents flag a FAKE map (a colored div vs real draggable tiles), THIN/empty
seed data, or an auth bounce. This sharpens the goal to assert those objective signals explicitly
and FILE a P0, closing the demonstrated squad-coverage gap (the deterministic gate catches these,
but the squad is the user-facing test-user and must too — defense in depth). PURE. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import plan_test_user_goals  # noqa: E402


def _page_goal():
    goals = plan_test_user_goals(
        business_eps=[], ui_pages=[{"name": "Explore", "route": "/explore"}],
        acceptance=[], multi_tenant=False, mcp_present=False)
    pg = [g for g in goals if g.get("kind") == "page"]
    return pg[0]["goal"].lower() if pg else ""


def test_page_goal_still_produced():
    assert _page_goal(), "expected a browser 'page' goal for a declared non-auth page"


def test_page_goal_asserts_real_interactive_map():
    # fake_map=['home_map'] — run-14's squad passed a fake map; the goal must call out a REAL map.
    assert "interactive map" in _page_goal()


def test_page_goal_asserts_real_seeded_data():
    # no_real_data — the squad passed thin/empty data; assert REAL seeded rows explicitly.
    assert "seeded data" in _page_goal()


def test_page_goal_asserts_auth_bounce_and_files_p0():
    # auth_ok=False bounce + must FILE a P0 on any objective-breakage signal it finds.
    g = _page_goal()
    assert "login" in g or "auth" in g
    assert "p0" in g
