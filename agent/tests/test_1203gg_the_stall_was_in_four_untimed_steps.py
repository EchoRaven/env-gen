"""#1203gg -- the stall inside docker_up happened in four untimed steps.

`#1203gf` split docker_up into `down_v` / `build` / `up` and the first two runs with it answered
immediately -- and said the split was still incomplete:

    r165   29 calls   docker_up 5998s   8 calls >=200s = 4412s = 74% of docker_up
    r166   30 calls   docker_up 4582s   5 calls >=200s = 2295s = 50% of docker_up
           stall values: 208 / 219 / 270 / 728 / 870 seconds

In the 13-of-16 normal case the three timed sub-steps account for the whole phase (preamble 4-8s)
and `build` dominates at a stable median 66s. In the stalls, the timed sub-steps account for
almost NOTHING -- 870s total with `down_v` 2.1s and `build` 0.6s. docker_up is 94% of
run_validation, which is the biggest single wall-clock item in the pipeline, so ~110 minutes
across two runs sat in code that is neither timed nor logged.

Four candidates share that window, all untimed:

    lock_wait       `while True: flock(LOCK_NB) / sleep(2)`, up to 600s. ITS ONLY LOG LINE
                    FIRES WHEN IT GIVES UP, and that line appears 0 times in r165 and r166 --
                    so a wait of several hundred seconds leaves no trace at all.
    stage_assets    FIX #113, re-stages design assets before the build
    repair_params   FIX #125, rewrites lane param types against the projection
    localize_seed   downloads external seed images locally -- the other prime suspect

This times all four rather than only the lock: the measurement that distinguishes them is the
whole point, and guessing which one it is would be the same mistake as reading the phase total.

The lock uses the `_wait_start` the code already keeps, instead of wrapping the polling loop --
the elapsed value is already exact there, and wrapping a `while True` in a lambda would not be.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import validation_runner as VR  # noqa: E402

SRC = Path(VR.__file__).read_text(encoding="utf-8")


def _smoke_fn():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and "_du_steps_1203gf" in ast.unparse(n):
            return n
    raise AssertionError("the docker_up sub-step collector is gone")


def _timed_labels(fn):
    out = set()
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_timed_1203gf" \
           and call.args and isinstance(call.args[0], ast.Constant):
            out.add(call.args[0].value)
    return out


def _appended_labels(fn):
    """Labels pushed straight onto the collector (the lock does this, using _wait_start)."""
    out = set()
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        if getattr(call.func, "attr", None) != "append":
            continue
        if getattr(getattr(call.func, "value", None), "id", None) != "_du_steps_1203gf":
            continue
        for a in call.args:
            if isinstance(a, ast.Tuple) and a.elts and isinstance(a.elts[0], ast.Constant):
                out.add(a.elts[0].value)
    return out


def test_all_seven_steps_in_the_window_are_timed():
    fn = _smoke_fn()
    labels = _timed_labels(fn) | _appended_labels(fn)
    expected = {"down_v", "build", "up",                      # #1203gf
                "lock_wait", "stage_assets", "repair_params", "localize_seed"}  # #1203gg
    missing = expected - labels
    assert not missing, (
        "untimed steps inside docker_up's phase window: %s -- their seconds land on the phase "
        "total with no label, which is the defect being fixed" % sorted(missing))


def test_the_lock_wait_uses_the_elapsed_the_code_already_keeps():
    """Wrapping the `while True` poll in a lambda would measure the wrong thing; `_wait_start`
    is already exact. Pin that it is what gets recorded."""
    fn = _smoke_fn()
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        if getattr(call.func, "attr", None) != "append":
            continue
        if getattr(getattr(call.func, "value", None), "id", None) != "_du_steps_1203gf":
            continue
        for a in call.args:
            if isinstance(a, ast.Tuple) and a.elts and getattr(a.elts[0], "value", None) == "lock_wait":
                assert "_wait_start" in ast.unparse(a), ast.unparse(a)
                return
    raise AssertionError("lock_wait is not appended to the collector")


def test_each_timed_step_still_runs_its_original_call():
    """A timer that swallowed the call would make every stall vanish AND break the step."""
    body = ast.unparse(_smoke_fn())
    for fragment in ("ensure_assets_staged_for_build(compose_file)",
                     "repair_custom_routes_param_types_vs_projection(_be)",
                     "localize_seed_external_images(_be_seed, _fe_dir)"):
        assert fragment in body, fragment


def test_none_of_the_new_steps_became_a_check():
    """Sub-steps must not enter `checks` — a phantom verdict reads as a real gate check."""
    fn = _smoke_fn()
    added = {c.args[0].value for c in ast.walk(fn)
             if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_add"
             and c.args and isinstance(c.args[0], ast.Constant)}
    for step in ("lock_wait", "stage_assets", "repair_params", "localize_seed"):
        assert step not in added, "%s became a check, not a sub-step" % step
