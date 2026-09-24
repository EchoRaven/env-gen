"""#1202ez: `usage.started_at` must mean the same thing in every writer.

#1196 made the field mean "the origin the wall-clock cap is measured from" --
which excludes design-prep and kickoff -- and set that on the periodic ticker
only. The terminal writer kept passing process start, and it "runs LAST and
overwrites everything", so a finished run's ledger reported one clock while every
live reading during it reported another. That is verbatim the "One field, two
meanings, whichever writer touched it last" #1196 was written to remove.

The precedent sits one argument below the same call: #1192 fixed `ticks` on the
ticker, left this site, and #1192b had to come back for it.
"""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.run_budget import RunBudget  # noqa: E402

ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def _budget_write_calls():
    """Every `self._budget.write(...)` in the orchestrator, as AST nodes."""
    out = []
    for node in ast.walk(ast.parse(ORCH)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == "write"
                and isinstance(f.value, ast.Attribute) and f.value.attr == "_budget"):
            out.append(node)
    return out


class TestOneClock(unittest.TestCase):

    def test_every_direct_ledger_writer_uses_the_cap_origin(self):
        """The two writers #1196 and #1192b are about. The wrapper forwards a parameter,
        so it is judged at its CALL sites instead (below)."""
        tree = ast.parse(ORCH)
        wrapper = next(n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == "_write_run_budget")
        inside = set(range(wrapper.lineno, (wrapper.end_lineno or wrapper.lineno) + 1))
        checked = 0
        for call in _budget_write_calls():
            if call.lineno in inside:
                continue
            origin = ast.unparse(call.args[1])
            self.assertTrue("_loop_start_1196" in origin or "_origin_1202ez" in origin,
                            "a writer passes a different clock: " + origin)
            elapsed = ast.unparse(call.args[2])
            self.assertTrue("_loop_start_1196" in elapsed or "_origin_1202ez" in elapsed,
                            "elapsed measured from a different clock: " + elapsed)
            checked += 1
        self.assertGreaterEqual(checked, 2, "expected the periodic and terminal writers")

    def test_the_only_process_clock_writer_is_the_one_before_the_loop_exists(self):
        """#1196: "Before the loop exists there is no loop origin, so it falls back to
        process start, which is the honest answer for that window." Exactly one caller may
        be in that window, and it must come before the loop origin is ever assigned."""
        tree = ast.parse(ORCH)
        first_loop_start = min(
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            for t in ast.walk(n)
            if isinstance(t, ast.Name) and t.id == "loop_start" and isinstance(t.ctx, ast.Store))
        pre_loop = []
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_write_run_budget"):
                continue
            origin = ast.unparse(call.args[1])
            if origin == "loop_start":
                continue
            pre_loop.append((call.lineno, origin))
        self.assertEqual(len(pre_loop), 1,
                         "every wrapper call but the pre-loop one must pass loop_start: "
                         + repr(pre_loop))
        line, origin = pre_loop[0]
        self.assertIn("start_time", origin)
        self.assertLess(line, first_loop_start,
                        "a process-clock write after the loop origin exists is the #1196 bug")

    def test_the_total_wall_clock_is_still_recorded(self):
        """Making the field consistent must not delete the other question."""
        d = Path(tempfile.mkdtemp())
        b = RunBudget(d, None)
        b.write_process_wall_1202ez(3600.0)
        b.write({"max_wall_sec": 1.0, "max_ticks": 1}, 0.0, 120.0, 1, "finished")
        usage = json.loads((d / "run_budget.json").read_text(encoding="utf-8"))["usage"]
        self.assertEqual(usage["process_wall_sec_1202ez"], 3600.0)
        self.assertEqual(usage["elapsed_sec"], 120.0, "the capped window is unchanged")

    def test_the_field_is_absent_when_nobody_measured_it(self):
        """Never claim a measurement that was not taken."""
        d = Path(tempfile.mkdtemp())
        RunBudget(d, None).write({"max_wall_sec": 1.0, "max_ticks": 1}, 0.0, 1.0, 1, "running")
        usage = json.loads((d / "run_budget.json").read_text(encoding="utf-8"))["usage"]
        self.assertNotIn("process_wall_sec_1202ez", usage)

    def test_a_bad_measurement_never_breaks_the_ledger(self):
        d = Path(tempfile.mkdtemp())
        b = RunBudget(d, None)
        b.write_process_wall_1202ez("not a number")
        b.write({"max_wall_sec": 1.0, "max_ticks": 1}, 0.0, 1.0, 1, "running")
        self.assertTrue((d / "run_budget.json").is_file())


if __name__ == "__main__":
    unittest.main()
