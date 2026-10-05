r"""#1203fc / #1203fd: two facts that lived only where a finished run cannot be read.

Both were found by being blocked BY them while verifying the rest of the f-series on r155.

#1203fc -- the clobber census named the actor for refusals and not for declarations.
#1202fc established that a refusal naming every FILE and no ACTOR is unactionable, and
#1203f4 put the actor in the ledger for refusals. `declared` -- the census this ledger
exists for, "the number #1011 measured at ~22,000 and which nothing has been able to see
since" -- still counted paths only. r155 made the cost concrete: 37 declared writes across
9 files, and no way even in principle to tell which projector argued for any of them, so
the live check of #1203f3's new declarations could not be made at all. Asking later whether
a declaration still holds (#1202tb's question, over 407 declared writes in the corpus) needs
the same thing.

#1203fd -- `caps` carried `max_wall_sec`, `max_ticks` and `unlimited`, and not the spend
ceiling, which is the one that actually stops most runs. To confirm r155 was launched at
$300 I had to read `/proc/<pid>/environ` while it was still alive; after it exited that
answer was gone. Same shape as #1203f4, one ledger over.

It records the HARD ceiling too, because the cap alone misstates where a run stops. #1183
multiplies it by 1.25 once the delivery gate has passed, #1202cz by 1.15 while the visual
gate reports the run is still improving -- "a cap that kills a converging run loses
everything it already bought", measured at three runs and ~$1,195 with nothing delivered.
r155 was launched at $300 and stopped at $351.22. Both numbers are correct and neither was
readable from the run's own ledger.
"""
import json
import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import path_routed_workspace as prw   # noqa: E402
from multi_agent.runtime.run_budget import RunBudget           # noqa: E402


def _lane_file(name="TrendingPage.jsx"):
    d = Path(tempfile.mkdtemp())
    f = d / "app" / "frontend" / "src" / "pages" / name
    f.parent.mkdir(parents=True)
    f.write_text("export default function P(){ return null }", encoding="utf-8")
    return f


def _reset():
    for b in prw._LANE_CLOBBERS_1202CW.values():
        b.clear()


class TheCensusNamesTheDeclarer(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_a_declared_write_is_keyed_by_call_site(self):
        def a_projector():
            prw.framework_write_1202cw(_lane_file(), "x", clobber_ok="#1203fc test: declared")
        a_projector()
        by = prw.lane_clobbers_1202cw()["declared_by_1203fc"]
        self.assertEqual(len(by), 1, by)
        site = next(iter(by))
        self.assertIn("a_projector", site, "the site must name the projector: %r" % site)
        self.assertNotIn("path_routed_workspace", site,
                         "the guard named itself instead of the caller: %r" % site)

    def test_two_declaring_sites_on_one_path_are_told_apart(self):
        f = _lane_file()

        def site_a():
            prw.framework_write_1202cw(f, "a", clobber_ok="#1203fc test: a")

        def site_b():
            prw.framework_write_1202cw(f, "b", clobber_ok="#1203fc test: b")

        site_a()
        site_b()
        led = prw.lane_clobbers_1202cw()
        self.assertEqual(len(led["declared"]), 1,
                         "one path, so the path-keyed bucket cannot separate them")
        self.assertEqual(len(led["declared_by_1203fc"]), 2, led["declared_by_1203fc"])

    def test_every_declared_write_is_counted(self):
        f = _lane_file()
        for _ in range(3):
            prw.framework_write_1202cw(f, "x", clobber_ok="#1203fc test: repeat")
        by = prw.lane_clobbers_1202cw()["declared_by_1203fc"]
        self.assertEqual(sum(by.values()), 3, by)

    def test_a_refusal_does_not_appear_as_a_declaration(self):
        prw.framework_write_1202cw(_lane_file(), "x")          # no clobber_ok
        led = prw.lane_clobbers_1202cw()
        self.assertFalse(led["declared_by_1203fc"], led)
        self.assertTrue(led["refused_by_1203f4"], led)

    def test_the_census_reaches_the_run_budget_file(self):
        prw.framework_write_1202cw(_lane_file(), "x", clobber_ok="#1203fc test: persisted")
        out = Path(tempfile.mkdtemp()) / "run"
        out.mkdir()
        RunBudget(out, logging.getLogger("t1203fc")).write(
            {"max_wall_sec": 1e5, "max_ticks": 500}, time.time(), 1.0, 1, "running")
        census = json.loads((out / "run_budget.json").read_text())["lane_clobbers_1202cw"]
        self.assertTrue(census.get("declared_by_1203fc"),
                        "the declarer did not survive into the file a reader gets: %r"
                        % sorted(census))


class TheCapsRecordTheSpendCeiling(unittest.TestCase):
    def _write(self, env, monkeypatch_env):
        out = Path(tempfile.mkdtemp()) / "run"
        out.mkdir()
        import os
        saved = {k: os.environ.get(k) for k in monkeypatch_env}
        try:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            RunBudget(out, logging.getLogger("t1203fd")).write(
                {"max_wall_sec": 7200.0, "max_ticks": 240}, time.time(), 1.0, 1, "running")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return json.loads((out / "run_budget.json").read_text())["caps"]

    _KEYS = ("ENVGEN_MAX_SPEND_USD", "ENVGEN_DELIVERY_OVERSHOOT")

    def test_the_cap_is_recorded(self):
        caps = self._write({"ENVGEN_MAX_SPEND_USD": "300",
                            "ENVGEN_DELIVERY_OVERSHOOT": None}, self._KEYS)
        self.assertEqual(caps.get("max_spend_usd"), 300.0, caps)

    def test_the_hard_ceiling_is_recorded_not_just_the_cap(self):
        """r155 was launched at $300 and stopped at $351.22; the cap alone says $300."""
        caps = self._write({"ENVGEN_MAX_SPEND_USD": "300",
                            "ENVGEN_DELIVERY_OVERSHOOT": None}, self._KEYS)
        self.assertEqual(caps.get("max_spend_hard_ceiling_1203fd"), 375.0, caps)

    def test_an_explicit_overshoot_is_honoured(self):
        caps = self._write({"ENVGEN_MAX_SPEND_USD": "300",
                            "ENVGEN_DELIVERY_OVERSHOOT": "1.0"}, self._KEYS)
        self.assertEqual(caps.get("max_spend_hard_ceiling_1203fd"), 300.0, caps)

    def test_no_cap_records_none_not_zero(self):
        """0.0 is how the enforcement spells "unlimited", so it cannot double as "absent"
        (#1026b)."""
        caps = self._write({"ENVGEN_MAX_SPEND_USD": None,
                            "ENVGEN_DELIVERY_OVERSHOOT": None}, self._KEYS)
        self.assertIsNone(caps.get("max_spend_usd"), caps)
        self.assertNotIn("max_spend_hard_ceiling_1203fd", caps, caps)

    def test_the_wall_clock_caps_are_untouched(self):
        caps = self._write({"ENVGEN_MAX_SPEND_USD": "300",
                            "ENVGEN_DELIVERY_OVERSHOOT": None}, self._KEYS)
        self.assertEqual(caps.get("max_wall_sec"), 7200.0)
        self.assertEqual(caps.get("max_ticks"), 240)
        self.assertIs(caps.get("unlimited"), False)

    def test_a_junk_overshoot_does_not_raise_and_falls_back(self):
        caps = self._write({"ENVGEN_MAX_SPEND_USD": "300",
                            "ENVGEN_DELIVERY_OVERSHOOT": "not-a-number"}, self._KEYS)
        self.assertEqual(caps.get("max_spend_hard_ceiling_1203fd"), 375.0, caps)


if __name__ == "__main__":
    unittest.main()
