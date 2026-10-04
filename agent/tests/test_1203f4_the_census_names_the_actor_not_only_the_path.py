r"""#1203f4: the clobber census must name the CALL SITE, not only the path.

#1202fc established that a refusal naming every FILE and no ACTOR is unactionable -- "acting
on the alarm meant reading 52 call sites in frontend_scaffold alone and guessing which one it
was" -- and put the actor in the WARNING. Two things keep that out of reach of anyone reading
a finished run:

  * the warning fires only on the FIRST refusal per path (`refused[key] == 1`), so r154's 25
    refusals of one file produced one line;
  * the warning lives in that run's stderr. `run_budget.json` is what survives, and its
    `lane_clobbers_1202cw` census carried paths only.

So tracing 1172 undeclared clobbers across 30 runs back to the 8 functions responsible meant
grepping run logs and mapping line numbers that had since moved -- which is the work #1202fc
set out to remove, arriving from one step further out.

The by-site bucket counts EVERY refusal, not the first, because the repetition is the signal:
a site refused 25 times is not retrying through a transient condition, it is one that can
never succeed (the target is lane-owned by definition and the site declares nothing).
"""
import logging
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import path_routed_workspace as prw  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def _lane_file(name="TrendingPage.jsx"):
    d = Path(tempfile.mkdtemp())
    f = d / "app" / "frontend" / "src" / "pages" / name
    f.parent.mkdir(parents=True)
    f.write_text("export default function P(){ return null }", encoding="utf-8")
    return f


def _reset():
    for b in prw._LANE_CLOBBERS_1202CW.values():
        b.clear()


class TheCensusNamesTheActor(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_a_refusal_is_keyed_by_call_site(self):
        prw.framework_write_1202cw(_lane_file(), "x")
        by = prw.lane_clobbers_1202cw()["refused_by_1203f4"]
        self.assertEqual(len(by), 1, by)
        site = next(iter(by))
        self.assertIn(":", site, "a site must be module:function:line, got %r" % site)
        self.assertNotIn("path_routed_workspace", site,
                         "the guard named itself instead of the projector: %r" % site)

    def test_every_refusal_is_counted_not_only_the_announced_one(self):
        """The repetition is the signal, and the warning cannot carry it."""
        cap = _Capture()
        log = logging.getLogger("multi_agent.runtime.path_routed_workspace")
        log.addHandler(cap)
        try:
            f = _lane_file()
            for _ in range(3):
                prw.framework_write_1202cw(f, "x")
        finally:
            log.removeHandler(cap)
        announced = [m for m in cap.msgs if "#1202cw refused" in m]
        self.assertEqual(len(announced), 1,
                         "the warning is per-path-first-hit by design: %r" % announced)
        by = prw.lane_clobbers_1202cw()["refused_by_1203f4"]
        self.assertEqual(sum(by.values()), 3,
                         "the census must count the refusals the warning did not: %r" % by)

    def test_two_sites_hitting_one_path_are_told_apart(self):
        f = _lane_file()

        def site_a():
            prw.framework_write_1202cw(f, "a")

        def site_b():
            prw.framework_write_1202cw(f, "b")

        site_a()
        site_b()
        led = prw.lane_clobbers_1202cw()
        self.assertEqual(len(led["refused"]), 1,
                         "one path, so the path-keyed bucket cannot separate them")
        self.assertEqual(len(led["refused_by_1203f4"]), 2,
                         "two actors must be two entries: %r" % led["refused_by_1203f4"])

    def test_a_declared_write_is_not_an_actor(self):
        prw.framework_write_1202cw(_lane_file(), "x", clobber_ok="#1203f4 test: declared")
        led = prw.lane_clobbers_1202cw()
        self.assertFalse(led["refused_by_1203f4"], led)
        self.assertTrue(led["declared"], led)

    def test_the_census_reaches_the_run_budget_file(self):
        import json
        import time
        from multi_agent.runtime.run_budget import RunBudget
        prw.framework_write_1202cw(_lane_file(), "x")
        out = Path(tempfile.mkdtemp()) / "run"
        out.mkdir()
        RunBudget(out, logging.getLogger("t1203f4")).write(
            {"max_wall_sec": 1e5, "max_ticks": 500}, time.time(), 1.0, 1, "running")
        census = json.loads((out / "run_budget.json").read_text())["lane_clobbers_1202cw"]
        self.assertTrue(census.get("refused_by_1203f4"),
                        "the actor did not survive into the file anyone can read later: %r"
                        % sorted(census))


if __name__ == "__main__":
    unittest.main()
