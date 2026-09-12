"""#1202lb: the failing-chain list is not one problem per name.

`business_chain_failing` needs every authored chain green, so a tail of three blocks delivery
as hard as a tail of thirty -- and the blocker lists chain NAMES. Those names are not
one-per-problem: the verifier re-authors the same surface under new names round after round.
Measured across the corpus: tiktok-r107 has SEVEN chains over the same two endpoints, r96 has
five over one, r117 has 82 chains covering 71 distinct endpoint-sets.

r117 died here with these failing chains -- `notifications_activity_page`,
`activity_notifications_auth_isolation`, `discovery_notifications_messages_tenant_flow`,
`tiktok_feed_engagement_and_auth_coverage` (plus `_framework_coverage`). The first three are
ONE problem: every failing step in all three is `GET /api/notifications`. The blocker named
four things where there were two.

This also explains a number that looked impossible. `flips_1202fa` reads 0 across all 1808
chains in the corpus, while its own comment records "business_chain_failing flips verdict 115
times over 18 runs, the largest oscillator". Both are true: the counter is per-chain and
increments on a status CHANGE, but each round's re-authored chain is a NEW record starting at
zero. The oscillation happens BETWEEN renamed chains, where nothing was counting.

Verified against the real ledgers, which is also where the silence was checked:
    r117 -> "4 endpoint(s): GET /api/notifications (3 chains); ..."
    r99  -> "4 endpoint(s): GET /api/users/coachmike (2 chains); POST /api/notifications (2)"
    r115, r118, netflix-local-r41 -> silent (one endpoint per chain — the names already say it)

WHAT IS VERIFIED: it collapses when chains share an endpoint; it is SILENT when they do not;
passing and framework_blocked chains are ignored; only steps with ok=False count; and it is
wired into the business_chain_failing detail rather than merely defined.

WHAT IS NOT: that it changes any verdict, or merges any row. The gate still needs every chain
green. It reports the shape of the tail; it does not shorten it.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import delivery_gate as dg  # noqa: E402


def _chain(name, *steps, status="failing"):
    return {"name": name, "status": status,
            "last_result": {"steps": [{"method": m, "path": p, "ok": False} for m, p in steps]}}


class ItCollapsesOntoEndpoints(unittest.TestCase):

    def test_r117s_three_notification_chains_read_as_one_endpoint(self):
        """★ The case it was written for."""
        said = dg._failing_surface_1202lb([
            _chain("notifications_activity_page", ("GET", "/api/notifications")),
            _chain("activity_notifications_auth_isolation", ("GET", "/api/notifications")),
            _chain("discovery_notifications_messages_tenant_flow", ("GET", "/api/notifications")),
        ])
        self.assertIn("#1202lb", said)
        self.assertIn("GET /api/notifications (3 chains)", said)

    def test_it_says_fixing_one_endpoint_clears_several_rows(self):
        said = dg._failing_surface_1202lb([
            _chain("a", ("GET", "/api/notifications")),
            _chain("b", ("GET", "/api/notifications")),
        ])
        self.assertIn("fewer problems than rows", said)

    def test_silent_when_no_endpoint_is_shared(self):
        """★ Narrowness: 59 of the 65 corpus runs with a failing chain are this shape, and the
        name list already says everything. A line that fires on every blocker stops being
        read (#845)."""
        self.assertEqual(dg._failing_surface_1202lb([
            _chain("a", ("GET", "/api/one")),
            _chain("b", ("GET", "/api/two")),
            _chain("c", ("GET", "/api/three")),
        ]), "")

    def test_passing_and_framework_blocked_chains_are_ignored(self):
        self.assertEqual(dg._failing_surface_1202lb([
            _chain("a", ("GET", "/api/notifications"), status="passing"),
            _chain("b", ("GET", "/api/notifications"), status="framework_blocked"),
        ]), "")

    def test_only_failed_steps_count(self):
        """A chain fails on ONE step; its passing steps are not the surface."""
        rec_a = {"name": "a", "status": "failing", "last_result": {"steps": [
            {"method": "POST", "path": "/auth/register", "ok": True},
            {"method": "GET", "path": "/api/notifications", "ok": False}]}}
        rec_b = {"name": "b", "status": "failing", "last_result": {"steps": [
            {"method": "POST", "path": "/auth/register", "ok": True},
            {"method": "GET", "path": "/api/notifications", "ok": False}]}}
        said = dg._failing_surface_1202lb([rec_a, rec_b])
        self.assertIn("GET /api/notifications (2 chains)", said)
        self.assertNotIn("/auth/register", said)

    def test_r102_an_expansion_is_not_reported_as_a_saving(self):
        """Regression: comparing endpoints against the SUM of per-endpoint chain counts made
        tiktok-r102's 16 failing chains over 27 endpoints announce "ONLY 27 ENDPOINT(S)".
        Only endpoints that are genuinely SHARED may be reported."""
        said = dg._failing_surface_1202lb([
            _chain("a", ("GET", "/api/one"), ("GET", "/api/two")),
            _chain("b", ("GET", "/api/three"), ("GET", "/api/four")),
        ])
        self.assertEqual(said, "")

    def test_r96_chains_with_no_attributable_step_are_not_counted(self):
        """Regression: `_framework_coverage` and never-run chains carry no steps, so they can
        never be part of a surface. Counting them claimed r96 collapsed 7 chains onto 2."""
        said = dg._failing_surface_1202lb([
            _chain("real_a", ("GET", "/api/videos")),
            {"name": "_framework_coverage", "status": "failing", "last_result": {"steps": []}},
            {"name": "never_run", "status": "failing"},
        ])
        self.assertEqual(said, "")

    def test_r117_one_wide_chain_does_not_mask_a_shared_endpoint(self):
        """Regression: comparing total endpoints against contributing chains went silent on
        r117 -- one oauth chain contributing 3 endpoints outweighed three notification chains
        sharing 1. Sharing is true or false PER ENDPOINT."""
        said = dg._failing_surface_1202lb([
            _chain("n1", ("GET", "/api/notifications")),
            _chain("n2", ("GET", "/api/notifications")),
            _chain("n3", ("GET", "/api/notifications")),
            _chain("oauth", ("GET", "/oauth/authorize"), ("POST", "/oauth/authorize"),
                   ("POST", "/oauth/token")),
        ])
        self.assertIn("GET /api/notifications (3 chains)", said)
        self.assertNotIn("/oauth/", said)

    def test_junk_never_raises(self):
        self.assertEqual(dg._failing_surface_1202lb(None), "")
        self.assertEqual(dg._failing_surface_1202lb([None, 3, "x"]), "")


class ItIsActuallyWired(unittest.TestCase):
    """Reachability, not presence (#1202ka)."""

    def test_it_is_appended_to_the_business_chain_failing_detail(self):
        tree = ast.parse(Path(dg.__file__).read_text(encoding="utf-8"))
        wired = False
        for d in ast.walk(tree):
            if isinstance(d, ast.Dict):
                src = ast.dump(d)
                if "business_chain_failing" in src and "_failing_surface_1202lb" in src:
                    wired = True
        self.assertTrue(wired, "not wired into the business_chain_failing blocker detail")


if __name__ == "__main__":
    unittest.main()
