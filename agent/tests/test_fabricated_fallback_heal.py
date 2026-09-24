"""Guard: FIX #191 — deterministic heal for #175 fabricated-field fallbacks.

tiktok-r3 died on deliverability_fabricated_field_fallback NO-CONVERGENCE: the
HARD gate (correctly) flagged invented-data fallbacks, the frontend lane
thrashed 75 minutes without landing the edit, and the run aborted. The gate
stays HARD (the user's no-mock bar); the fix is a DETERMINISTIC rewrite of the
exact flagged sites — `place.rating || '4.5'` → `place.rating ?? '—'` (honest
empty state), ternary fakes likewise — using the SAME regexes + literal
classifier as the gate, so the heal clears precisely what the gate blocks, by
construction. Field-name drift then surfaces as honest '—' cells (and the
no_real_data browser gate still owns 'the page must show REAL data').
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    invented_field_fallback_blockers, repair_fabricated_fallbacks,
)


def _mk_src(text, name="SearchResultsPage.jsx"):
    d = Path(tempfile.mkdtemp())
    (d / name).write_text(text)
    return d


class FabricatedFallbackHealTests(unittest.TestCase):
    def test_or_fallback_rewritten_to_honest_empty(self):
        d = _mk_src("<span>{place.rating || '4.5'}</span>\n")
        rep = repair_fabricated_fallbacks(d)
        self.assertTrue(rep["repaired"])
        out = (d / "SearchResultsPage.jsx").read_text()
        self.assertIn("place.rating ?? '—'", out)
        self.assertNotIn("4.5", out)

    def test_ternary_fake_rewritten(self):
        d = _mk_src("{sel ? selectedPlace.name : 'HI Point Montara Lighthouse'}\n")
        rep = repair_fabricated_fallbacks(d)
        self.assertTrue(rep["repaired"])
        out = (d / "SearchResultsPage.jsx").read_text()
        self.assertIn(": '—'", out)
        self.assertNotIn("Montara", out)

    def test_honest_fallbacks_untouched(self):
        src = ("<i>{user.status || 'active'}</i>\n"
               "<i>{user.name || 'Unknown'}</i>\n"
               "<i>{list.length || 0}</i>\n")
        d = _mk_src(src)
        rep = repair_fabricated_fallbacks(d)
        self.assertFalse(rep.get("repaired"))
        self.assertEqual((d / "SearchResultsPage.jsx").read_text(), src)

    def test_heal_clears_the_gate_by_construction(self):
        d = _mk_src(
            "<span>{place.rating || '4.5'}</span>\n"
            "<b>{place.reviews || '1,234'}</b>\n"
            "<i>{place.address || 'San Francisco, CA'}</i>\n"
            "<i>{user.status || 'pending'}</i>\n")
        self.assertTrue(invented_field_fallback_blockers(d))
        repair_fabricated_fallbacks(d)
        self.assertEqual(invented_field_fallback_blockers(d), [])

    def test_idempotent(self):
        d = _mk_src("<span>{place.rating || '4.5'}</span>\n")
        repair_fabricated_fallbacks(d)
        rep2 = repair_fabricated_fallbacks(d)
        self.assertFalse(rep2.get("repaired"))

    def test_sites_reported_with_location(self):
        d = _mk_src("<span>{place.rating || '4.5'}</span>\n")
        rep = repair_fabricated_fallbacks(d)
        self.assertTrue(any("SearchResultsPage.jsx:1" in s for s in rep["sites"]))


if __name__ == "__main__":
    unittest.main()
