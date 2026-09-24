"""#1202hj — reuse the measured design system across RUNS, not just across resumes.

`#1202bv` made a `--resume` inherit the enriched `design_system.json` already in ITS OWN
output dir, which is why r103's resume spent 13 seconds on design-prep (14:50:35 -> 14:50:48,
"skipping the skeleton rewrite and the design_analyst spawn") instead of the usual 10-15
minutes plus a spawned analyst bounded at 1800s.

A FRESH run of the same environment gets a brand-new output dir, so there is nothing on disk
to inherit and the analyst is paid for again -- for references that have not changed. Today
alone that is r102 and r103 measuring the identical `design_inputs/tiktok` from scratch.

The guard is the one #1202bv already defined and this must not weaken it: the donor's doc has
to pass `design_system_is_enriched` AND its recorded fingerprint has to match the design input
resolved NOW. So the donor scan calls `design_prep_reusable_1202bv` itself, once per candidate
-- one predicate, both paths, no second copy of the rule to drift.
"""
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.design_prep import (design_prep_donor_1202hj,
                                             design_prep_reusable_1202bv,
                                             design_system_is_enriched,
                                             record_design_prep_input_1202bv)

_INPUT = "/some/design_inputs/tiktok"
_RESOLVED = {"design_input": _INPUT, "references": ["a.png", "b.png"]}


def _enriched_doc():
    """Built to satisfy the REAL predicate, and asserted against it below -- a fixture the
    production reader rejects would make every test here vacuous."""
    return {"design_system": {"palette": {"bg": "#000000"},
                              "type_scale": [{"role": "body", "size_px": 14, "weight": 400}],
                              "radius_scale": [8], "iconography": {"set": "measured"}},
            "screens": [{"name": "fyp_feed", "route": "/", "components": [
                {"name": "VideoCard",
                 "build_notes": "measured: 12px gutter, 48px avatar, caption 14/400",
                 "typography": {"caption": {"size_px": 14, "weight": 400}}}]}]}


def _make_run(root, name, doc=None, fingerprint_input=_INPUT):
    d = root / name
    (d / "design").mkdir(parents=True)
    if doc is not None:
        (d / "design" / "design_system.json").write_text(json.dumps(doc), encoding="utf-8")
        record_design_prep_input_1202bv(d, fingerprint_input,
                                        {"design_input": fingerprint_input,
                                         "references": _RESOLVED["references"]})
    return d


class DonorScan(unittest.TestCase):
    def test_the_fixture_satisfies_the_production_predicate(self):
        self.assertTrue(design_system_is_enriched(_enriched_doc()))

    def test_a_prior_run_with_the_same_references_is_reused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            donor = _make_run(root, "tiktok-r102", _enriched_doc())
            self.assertTrue(design_prep_reusable_1202bv(donor, _INPUT, _RESOLVED),
                            "the donor must pass #1202bv's own bar")
            fresh = _make_run(root, "tiktok-r104")
            self.assertEqual(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED), donor)

    def test_a_run_measured_from_other_references_is_not_reused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _make_run(root, "netflix-r1", _enriched_doc(), fingerprint_input="/other/netflix")
            fresh = _make_run(root, "tiktok-r104")
            self.assertIsNone(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED))

    def test_a_hollow_doc_is_not_reused(self):
        """#85a's whole point: a parseable but unmeasured doc must not travel further than a
        fresh run would carry it."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _make_run(root, "tiktok-r102", {"design_system": {}, "screens": []})
            fresh = _make_run(root, "tiktok-r104")
            self.assertIsNone(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED))

    def test_the_run_never_donates_to_itself(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            fresh = _make_run(root, "tiktok-r104", _enriched_doc())
            self.assertIsNone(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED))

    def test_the_newest_matching_run_wins(self):
        import os
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            old = _make_run(root, "tiktok-r101", _enriched_doc())
            new = _make_run(root, "tiktok-r103", _enriched_doc())
            past = time.time() - 8000
            os.utime(old / "design" / "design_system.json", (past, past))
            self.assertEqual(design_prep_donor_1202hj(root / "tiktok-r104x", _INPUT, _RESOLVED)
                             if (root / "tiktok-r104x").exists() else
                             design_prep_donor_1202hj(_make_run(root, "tiktok-r104"),
                                                      _INPUT, _RESOLVED), new)


if __name__ == "__main__":
    unittest.main()


class Switch(unittest.TestCase):
    def test_the_opt_out_re_measures(self):
        """An operator who changed the references in place (same path, new pixels) needs a
        way to force a fresh measurement; the fingerprint keys on the input, not its bytes."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _make_run(root, "tiktok-r102", _enriched_doc())
            fresh = _make_run(root, "tiktok-r104")
            prior = os.environ.get("ENVGEN_DESIGN_PREP_REUSE")
            os.environ["ENVGEN_DESIGN_PREP_REUSE"] = "0"
            try:
                self.assertIsNone(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED))
            finally:
                if prior is None:
                    os.environ.pop("ENVGEN_DESIGN_PREP_REUSE", None)
                else:
                    os.environ["ENVGEN_DESIGN_PREP_REUSE"] = prior
            self.assertIsNotNone(design_prep_donor_1202hj(fresh, _INPUT, _RESOLVED))

    def test_adoption_copies_the_doc_and_records_the_fingerprint(self):
        """After adopting, this run must itself pass #1202bv — otherwise its own --resume
        would throw the doc away and respawn the analyst, which is the bug #1202bv fixed."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            donor = _make_run(root, "tiktok-r102", _enriched_doc())
            fresh = _make_run(root, "tiktok-r104")
            from multi_agent.runtime.design_prep import adopt_design_prep_1202hj
            self.assertTrue(adopt_design_prep_1202hj(donor, fresh, _INPUT, _RESOLVED))
            self.assertTrue(design_prep_reusable_1202bv(fresh, _INPUT, _RESOLVED))
