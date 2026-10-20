r"""#1203qh: the recorded fidelity averaged two different products' screens, in silence.

`#500` merges `verdict.json` BY SCREEN NAME, keeping the best score per name, so a transient
capture cannot clobber a good verdict. The key carries no product, so screens scored against
ANOTHER product's references survive into the merge -- and `#542a`'s recorded Part-A average
is then taken across both sets. `#542a`'s own comment states the intent this breaks: the
average is over blocking screens only "so a transient/advisory or duplicate-route screen
never drags the persisted fidelity".

MEASURED over the corpus: 78 of 79 verdicts use exactly one product's references. The
exception, `googlemaps-r16`, splits its 17 blocking screens into 9 google_maps (mean 0.4611,
range 0.34-0.56) and 8 netflix (mean 0.1487, range 0.05-0.35) -- the netflix ones carrying
missing-component lists that name "Netflix wordmark" and "Top 10 badge". Recomputing #542a's
formula over all 17 reproduces the recorded `blocking_average` of 0.3141 EXACTLY, which is how
the mechanism was confirmed rather than inferred; over the google_maps screens alone it is
0.4611, so that run's persisted fidelity understates itself by 1.47x.

DETECT AND SAY, NOT ARITHMETIC. n=1, and the likely cause is a reused output directory, so
dropping screens would be a behavioural change argued from one observation -- #1202w6 wants a
live run for that and #647 wants no guard wider than the evidence. These tests therefore pin
that the average is UNCHANGED and only the announcement is new.

AND IT GOES THROUGH #1203os's CHANNEL, NOT #1201's. This is a thing that IS the case about
the record, not a guarded mechanism that failed. Reporting it through `warn_once_1201` would
re-create exactly what #1203os removed: three sites doing that made 599 of 602 `#1201` lines
wrong answers to "which mechanisms were off this run".
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import visual_fidelity as vf          # noqa: E402
from multi_agent.runtime import message_format as mf           # noqa: E402


def _screen(name, sim, product):
    return {"name": name, "route": "/" + name, "similarity": sim, "passed": sim >= 0.65,
            "reference": "/x/design_inputs/%s/references/%s.png" % (product, name),
            "screenshot": "/x/shot/%s.png" % name,
            "dimensions": {"components": {"score": sim, "notes": "n", "fix": "f",
                                          "missing": []}}}


class ThePureReaderIsHonest(unittest.TestCase):
    """`reference_products_1203qh` answers {} for the 78, and names the split for the 1."""

    def test_one_product_is_not_a_finding(self):
        self.assertEqual(vf.reference_products_1203qh(
            [_screen("a", 0.5, "tiktok"), _screen("b", 0.6, "tiktok")]), {})

    def test_two_products_are_named_with_their_screens(self):
        got = vf.reference_products_1203qh(
            [_screen("home_map", 0.56, "google_maps"), _screen("games", 0.05, "netflix")])
        self.assertEqual(sorted(got), ["google_maps", "netflix"])
        self.assertEqual(got["netflix"], ["games"])

    def test_screens_without_a_reference_are_ignored(self):
        self.assertEqual(vf.reference_products_1203qh(
            [{"name": "x", "similarity": 0.4}, {"name": "y", "reference": ""}]), {})

    def test_a_reference_outside_design_inputs_is_ignored(self):
        self.assertEqual(vf.reference_products_1203qh(
            [{"name": "x", "reference": "/tmp/whatever/x.png"},
             _screen("a", 0.5, "tiktok")]), {})

    def test_junk_cannot_raise(self):
        for bad in (None, [], [None], ["string"], [{"reference": 7}], 5):
            self.assertIsInstance(vf.reference_products_1203qh(bad), dict)


class _Driven(unittest.TestCase):
    """Drives the real `_persist_verdict`, so the announcement is shown to ARRIVE."""

    def setUp(self):
        self._said = []
        self._real = mf.announce_once_1203os
        # the production site imports it from the module at call time, so patching the
        # attribute is what the live path will see
        mf.announce_once_1203os = lambda site, message, *a: self._said.append(
            (site, str(message) % a if a else str(message)))
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        mf.announce_once_1203os = self._real
        self._tmp.cleanup()

    def _persist(self, results):
        vf._persist_verdict(self.root, passed=False, min_similarity=0.65,
                            milestone_label="M1", summary="s", coverage=None,
                            results=results)
        p = self.root / "design" / "visual_gate" / "verdict.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


class TheCrossProductAverageIsAnnounced(_Driven):

    _MIXED = None

    def setUp(self):
        super().setUp()
        self._MIXED = [_screen("home_map", 0.56, "google_maps"),
                       _screen("search_results", 0.48, "google_maps"),
                       _screen("browse_home", 0.11, "netflix"),
                       _screen("games", 0.05, "netflix")]

    def test_it_says_so_and_names_both_products(self):
        self._persist(self._MIXED)
        said = [m for _s, m in self._said if "products' references" in m]
        self.assertTrue(said, "nothing was announced: %s" % self._said)
        self.assertIn("google_maps=2", said[0])
        self.assertIn("netflix=2", said[0])

    def test_it_quotes_the_number_that_is_not_about_one_app(self):
        d = self._persist(self._MIXED)
        said = [m for _s, m in self._said if "products' references" in m][0]
        self.assertIn("%.4f" % d["blocking_average"], said)

    def test_the_arithmetic_is_UNCHANGED(self):
        """#647/#1202w6: detect and say; dropping screens on n=1 would be a live-run change."""
        d = self._persist(self._MIXED)
        self.assertEqual(d["blocking_average"], 0.3)      # (0.56+0.48+0.11+0.05)/4
        self.assertEqual(len(d["screens"]), 4)

    def test_a_single_product_run_stays_silent(self):
        d = self._persist([_screen("a", 0.56, "tiktok"), _screen("b", 0.48, "tiktok")])
        self.assertEqual([m for _s, m in self._said if "products' references" in m], [])
        self.assertEqual(d["blocking_average"], 0.52)

    def test_it_uses_the_findings_channel_not_the_mechanism_channel(self):
        """#1203os: `warn_once_1201` answers "which mechanisms were OFF"; this is not that."""
        real_warn = mf.warn_once_1201
        warned = []
        mf.warn_once_1201 = lambda site, what, exc=None: warned.append(site)
        try:
            self._persist(self._MIXED)
        finally:
            mf.warn_once_1201 = real_warn
        self.assertEqual([s for s in warned if "1203qh" in s], [],
                         "a finding must not be reported as a mechanism that failed")
        self.assertTrue([s for s, _m in self._said if "1203qh" in s])


class TheCorpusCaseStillReadsThatWay(unittest.TestCase):
    """Against the artifact the measurement came from, when it is on this machine."""

    _P = (Path(__file__).resolve().parents[2] / "generated" / "googlemaps-r16"
          / "design" / "visual_gate" / "verdict.json")

    def test_googlemaps_r16_spans_two_products_and_the_formula_reproduces(self):
        if not self._P.is_file():
            self.skipTest("googlemaps-r16 is not on this machine")
        d = json.loads(self._P.read_text(encoding="utf-8"))
        screens = d.get("screens") or []
        blocking = [s for s in screens
                    if not s.get("advisory") and s.get("blank") is not True]
        self.assertEqual(sorted(vf.reference_products_1203qh(blocking)),
                         ["google_maps", "netflix"])
        sims = [float(s.get("similarity") or 0) for s in blocking]
        self.assertEqual(round(sum(sims) / len(sims), 4), d["blocking_average"],
                         "#542a's formula no longer reproduces the recorded number")
        gm = [float(s.get("similarity") or 0) for s in blocking
              if re.search(r"design_inputs/google_maps/", str(s.get("reference") or ""))]
        self.assertGreater(round(sum(gm) / len(gm), 4), d["blocking_average"],
                           "the single-product average must be the higher one")


if __name__ == "__main__":
    unittest.main()
