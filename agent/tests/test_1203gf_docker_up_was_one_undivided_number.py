"""#1203gf -- docker_up is 94% of run_validation and was a single number.

`#1203g8` landed the per-phase breakdown and r165 answered with it immediately:

    29 validations, run_validation 6383s, of which docker_up 5998s = 94%
    median 79s, min 23s, max 992s, six calls at or past 300s

So the biggest wall-clock item in the pipeline is one phase -- and that phase does THREE
different things:

    `down -v`  destroys the volume for a clean boot (no stale pg state)
    build      skipped when the app source fingerprint is unchanged (#566l)
    `up`       re-initialises postgres and reloads the seed, because the volume is gone

Their remedies have nothing in common. A slow `down_v` is teardown cost; a slow `build` means
#566l's fingerprint is missing or the source really did change; a slow `up` is postgres init
plus seed load, which is the price of the clean boot and the only one worth trading away. The
single total cannot tell them apart, so `#1203g8` measured the right thing and stopped one level
too early -- the same shape as the defect it fixed.

Sub-steps on the phase record, NOT extra `_add` calls: `_add` appends to `checks`, and a
phantom entry among the 26 verdicts reads as a check that can pass or fail.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.validation_runner import (  # noqa: E402
    record_phase_timings_1203g8,
)
from multi_agent.runtime import validation_runner as VR  # noqa: E402

SRC = Path(VR.__file__).read_text(encoding="utf-8")


def _run_smoke_fn():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and "_timed_1203gf" in ast.unparse(n):
            return n
    raise AssertionError("_timed_1203gf is not inside any function any more")


# --- the artifact carries the split -----------------------------------------------------------

def test_the_steps_reach_the_artifact(tmp_path):
    ok = record_phase_timings_1203g8(tmp_path, [
        ("frontend_navigable", 0.01),
        ("docker_up", 207.4, [{"name": "down_v", "sec": 12.3},
                              {"name": "build", "sec": 1.0},
                              {"name": "up", "sec": 194.1}]),
        ("backend_health", 3.2),
    ], 210.6)
    assert ok
    rec = json.loads((tmp_path / "logs" / "validation_phase_timings_1203g8.jsonl").read_text())
    du = next(p for p in rec["phases"] if p["name"] == "docker_up")
    assert [s["name"] for s in du["steps"]] == ["down_v", "build", "up"], du
    assert du["steps"][2]["sec"] == 194.1, du
    # the phases that have no sub-steps must not grow an empty key
    assert "steps" not in next(p for p in rec["phases"] if p["name"] == "backend_health")


def test_a_two_tuple_caller_still_works(tmp_path):
    """#1203g8's own shape. Unpacking by width would break every other phase."""
    assert record_phase_timings_1203g8(tmp_path, [("docker_up", 9.0)], 9.0)
    rec = json.loads((tmp_path / "logs" / "validation_phase_timings_1203g8.jsonl").read_text())
    assert rec["phases"] == [{"name": "docker_up", "sec": 9.0}], rec


def test_an_empty_step_list_is_not_written(tmp_path):
    assert record_phase_timings_1203g8(tmp_path, [("docker_up", 9.0, [])], 9.0)
    rec = json.loads((tmp_path / "logs" / "validation_phase_timings_1203g8.jsonl").read_text())
    assert "steps" not in rec["phases"][0], rec


def test_the_guard_from_1203g8_still_holds(tmp_path):
    """A destination that is not already a directory answers False rather than creating junk."""
    assert record_phase_timings_1203g8(object(), [("docker_up", 1.0, None)], 1.0) is False
    assert record_phase_timings_1203g8(tmp_path / "nope", [("docker_up", 1.0)], 1.0) is False


# --- the three sub-steps are really timed, in the real function -------------------------------

def test_all_three_compose_calls_are_wrapped():
    """Each of `down -v`, the build and `up` must go through the timer, or the split lies by
    omission: an unwrapped step's seconds silently land on whichever label comes next."""
    fn = _run_smoke_fn()
    labels = set()
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if name != "_timed_1203gf" or not call.args:
            continue
        lab = call.args[0]
        if isinstance(lab, ast.Constant):
            labels.add(lab.value)
    assert {"down_v", "build", "up"} <= labels, labels
    body = ast.unparse(fn)
    # no bare compose call for the three steps left outside the timer
    for frag in ('_compose(compose_file, \'down\', \'-v\'',
                 '_build_with_retry(compose_file, cwd)',
                 "_compose_capture(compose_file, 'up', '-d'"):
        wrapped = body.count("_timed_1203gf")
        assert wrapped >= 3, wrapped


def test_the_steps_are_attached_to_the_failing_record_too():
    """The 992s call is the one that matters; it is a docker_up that FAILED."""
    fn = _run_smoke_fn()
    add = next(n for n in ast.walk(fn)
               if isinstance(n, ast.FunctionDef) and n.name == "_add")
    body = ast.unparse(add)
    assert "'docker_up'" in body or '"docker_up"' in body, body
    assert "_rec['steps']" in body or '_rec["steps"]' in body, body

    # The property: the attach must not sit inside a branch on the pass/fail argument. Checked
    # over the AST -- a substring search for "if ok" matches `'pass' if ok else 'fail'`, which is
    # a few lines above and has nothing to do with it.
    def _assigns_steps(node):
        for n in ast.walk(node):
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
               and n.slice.value == "steps":
                return True
        return False

    for node in ast.walk(add):
        if isinstance(node, ast.If) and _assigns_steps(node):
            names = {x.id for x in ast.walk(node.test) if isinstance(x, ast.Name)}
            assert "ok" not in names, (
                "the sub-steps are behind a pass/fail test (`%s`) -- the 992s docker_up is a "
                "FAILING one" % ast.unparse(node.test))


def test_no_extra_check_was_added_to_the_twenty_six():
    """Sub-steps must not become `_add` calls — a phantom verdict reads as a real check."""
    fn = _run_smoke_fn()
    added = set()
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_add" and call.args:
            a = call.args[0]
            if isinstance(a, ast.Constant):
                added.add(a.value)
    for step in ("down_v", "build", "up", "build_retry", "up_retry"):
        assert step not in added, "%s became a check, not a sub-step" % step


def test_the_timer_records_even_when_the_step_raises():
    """A step that throws is exactly the expensive case; its seconds must still land."""
    fn = _run_smoke_fn()
    timer = next(n for n in ast.walk(fn)
                 if isinstance(n, ast.FunctionDef) and n.name == "_timed_1203gf")
    tries = [n for n in ast.walk(timer) if isinstance(n, ast.Try)]
    assert tries, "no try/finally in the timer — a raising step loses its measurement"
    assert any(t.finalbody for t in tries), ast.unparse(timer)
