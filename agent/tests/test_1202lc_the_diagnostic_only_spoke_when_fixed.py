"""#1202lc: #1202jx could only speak once the problem had already gone away.

#1202jx reports the contract contradiction that makes a logged-out screen unrenderable: the
design system declares it reachable without a token, its page calls an `auth_required`
endpoint, the capture arrives anonymous, the handler answers 401, and the lane goes looking at
a frontend where nothing is wrong. Its own measurement says the condition is common -- 32 of 98
logged-out screens across 35 recent runs.

It never once said so. `#1202jx` appears in NONE of the 310 run logs on this machine, while
replaying its finder over the real ledgers returns findings in 29 of 150 runs (19%) --
netflix's `landing` at `/`, over and over.

The cause is #1202ka's exactly, and not a guard: TEN earlier `return`s. It sat at the far end
of `_maybe_framework_deliver`, past every "not deliverable yet" exit, so it was reachable only
when the gate was GREEN -- and a screen that can never render is precisely what keeps the gate
RED. The diagnostic could only speak once the thing it diagnoses had been fixed by someone else.

It now runs in the `gate.get("failed_checks")` branch beside #1202kn: 2 returns ahead of it
instead of 10, and both are "already delivered" / "nothing to deliver yet".

WHAT IS VERIFIED: the call sits inside the red-gate branch; far fewer returns precede it; it
says both repairs; it says them once per distinct finding set rather than per tick; it is
silent with no findings and with no design_system.json; and it never raises.

WHAT IS NOT: that it runs before the endpoints are implemented. The `nothing to deliver yet`
return at the top still precedes it, so the first report lands once the contract is built --
far earlier than never, but not at kickoff.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.orchestrator import Orchestrator  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_ORCH = _ROOT / "env_generator/llm_generator/multi_agent/orchestrator.py"


class _Log:
    def __init__(self): self.errors = []
    def error(self, msg, *a): self.errors.append(msg % a if a else msg)
    def warning(self, *a, **k): pass
    def debug(self, *a, **k): pass


class _Hubs:
    def __init__(self, rh): self.registryhub = rh


class TheReportNowRuns(unittest.TestCase):
    """The helper is exercised against a REAL RegistryHub, not a stand-in for it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lc_"))
        (self.root / "design").mkdir(parents=True)
        (self.root / "hubs").mkdir()
        self.rh = RegistryHub(self.root / "hubs")
        self.rh.register_endpoint(method="GET", path="/api/titles",
                                  schema={"auth_required": True, "response_key": "items"},
                                  agent="backend", status="implemented", kind="business")
        self.rh.register_ui_page(name="landing", route="/", agent="frontend",
                                 apis_used=["GET /api/titles"], status="implemented")
        (self.root / "design" / "design_system.json").write_text(json.dumps(
            {"screens": [{"name": "landing", "route": "/", "requires_auth": False}]}),
            encoding="utf-8")
        self.o = Orchestrator.__new__(Orchestrator)
        self.o.hubs = _Hubs(self.rh)
        self.o.output_dir = self.root
        self.o._logger = _Log()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_it_reports_the_netflix_landing_shape(self):
        """★ The shape found in 29 of 150 real runs."""
        self.o._report_logged_out_auth_screens_1202lc()
        said = "\n".join(self.o._logger.errors)
        self.assertIn("#1202jx", said)
        self.assertIn("landing", said)
        self.assertIn("/api/titles", said)

    def test_it_names_both_repairs_and_picks_neither(self):
        self.o._report_logged_out_auth_screens_1202lc()
        said = "\n".join(self.o._logger.errors)
        self.assertIn("public in the CONTRACT", said)
        self.assertIn("stop declaring this screen reachable logged out", said)

    def test_it_says_it_once_not_every_tick(self):
        """A contract fact, not a heartbeat (#845/#1202ad)."""
        for _ in range(5):
            self.o._report_logged_out_auth_screens_1202lc()
        self.assertEqual(len([e for e in self.o._logger.errors if "#1202jx" in e]), 1)

    def test_silent_without_a_design_system(self):
        (self.root / "design" / "design_system.json").unlink()
        self.o._report_logged_out_auth_screens_1202lc()
        self.assertEqual(self.o._logger.errors, [])

    def test_silent_when_the_screen_needs_no_auth_endpoint(self):
        self.rh.register_endpoint(method="GET", path="/api/titles",
                                  schema={"auth_required": False, "response_key": "items"},
                                  agent="backend", status="implemented", kind="business")
        self.o._report_logged_out_auth_screens_1202lc()
        self.assertEqual(self.o._logger.errors, [])

    def test_it_never_raises(self):
        self.o.output_dir = Path("/nonexistent/xyz")
        self.o._report_logged_out_auth_screens_1202lc()   # must not raise


class ItIsReachableNow(unittest.TestCase):
    """#1202ka's rule: an ancestor chain with no `if` is not reachability — count the earlier
    `return`s too."""

    def _fn(self):
        tree = ast.parse(_ORCH.read_text(encoding="utf-8"))
        return next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "_maybe_framework_deliver")

    def _call(self, fn):
        return next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "_report_logged_out_auth_screens_1202lc")

    def test_it_runs_in_the_RED_gate_branch(self):
        """★ The whole point: it must speak while the gate is failing, not after."""
        fn = self._fn()
        call = self._call(fn)
        parents = {}
        for n in ast.walk(fn):
            for c in ast.iter_child_nodes(n):
                parents[id(c)] = n
        cur, tests = call, []
        while id(cur) in parents:
            cur = parents[id(cur)]
            if isinstance(cur, ast.If):
                tests.append(ast.unparse(cur.test))
        self.assertTrue(any("failed_checks" in t for t in tests),
                        "the report is not inside the failing-gate branch: %s" % tests)

    def test_far_fewer_returns_precede_it_than_the_ten_that_killed_it(self):
        fn = self._fn()
        call = self._call(fn)
        rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
                and fn.lineno < n.lineno < call.lineno]
        self.assertLessEqual(len(rets), 3, "it drifted back behind the early exits")

    def test_the_old_green_gate_site_is_gone(self):
        """Leaving the dead copy would mean two sites and one working one."""
        src = _ORCH.read_text(encoding="utf-8")
        self.assertEqual(src.count("logged_out_screens_needing_auth_1202jx("), 1,
                         "more than one call site — the dead one was not removed")


if __name__ == "__main__":
    unittest.main()
