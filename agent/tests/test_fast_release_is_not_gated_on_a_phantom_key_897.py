r"""#897: #861 is reverted — it gated a release path on a key production never emits.

#861 added a second condition to `_visual_release_decision`'s fast path, fed by
`res.get("blocking_average_live")` where `res` is `gate.last_result` — the dict **returned** by
`run_visual_fidelity`. That function emits `blocking_average`; it does **not** emit
`blocking_average_live`. So the value was always `None`, `_live_ok` was always `False`, and
**`fast_release` could never fire**. Not stricter — disabled. Cost per run, by #861's own estimate:
the ~40–60 minutes and ~40 re-judgements the fast path exists to save.

★ **The premise was refuted 200 lines from where I was reading.** #711r: *"The DECISION path does
not read [the merged number]. `_visual_fast_release_args` takes `gate.last_result` … and that dict
carries `blocking_average` = the CURRENT capture, never merged."* **On this path
`blocking_average` already IS the live average.** The merged/live divergence I measured — merged
≥0.65 while live <0.65 in 5 of 7 — was measured in `verdict.json`, the *persisted* record, which
this path never reads.

★★ **Why #861's own test passed:** it called the pure `_visual_release_decision` with
`blocking_average_live` supplied as a kwarg, and never drove `_visual_fast_release_args` against a
real `gate.last_result`. **It pinned the function's logic given an input production cannot
produce.** That is the hazard named one item earlier, with me as the author — so the central case
here drives the whole path, args helper included.

Reverted rather than repaired: emitting the key would make the gate real, and a real gate re-checks
the number `blocking_average` already carries.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


_BASE = dict(avg_release=True, coverage_ok=True, avg_release_rounds=2, avg_stable_rounds=2,
             avg_min=0.65, deferred_since=None, now=0.0, escape_s=1e9,
             total_judgments=0, total_cap=99, attempts=0, attempt_cap=99,
             plateau_cap=0, plateau_rounds=0, plateau_min_s=0)


class _Gate:
    avg_pass_rounds = 2
    app_dead_750 = False
    last_result = {"blocking_average": 0.72, "min_similarity": 0.65,
                   "coverage": {"blocking_judged": 3}}


def test_the_whole_path_fires_not_just_the_pure_function():
    """★ The case #861 needed and did not have: args helper → decision, on a REAL `last_result`."""
    args = orch._visual_fast_release_args(_Gate())
    got = orch._visual_release_decision(
        deferred_since=None, attempts=0, total_judgments=0, now=0.0, escape_s=1e9,
        total_cap=99, attempt_cap=99, plateau_cap=0, plateau_rounds=0, plateau_min_s=0, **args)
    assert got == "fast_release", (got, args)


def test_the_phantom_key_is_gone_from_both_sides():
    """★ Checked by AST, not by substring. The revert note names `_live_ok` and
    `blocking_average_live` in prose — a text match flags the explanation of the fix as the fix's
    absence, which is the self-match this session has hit fifteen times. Names in CODE are what
    matter."""
    import ast
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(orch)))
              if isinstance(n, ast.FunctionDef) and n.name == "_visual_release_decision")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_live_ok" not in names
    assert "blocking_average_live" not in {a.arg for a in fn.args.kwonlyargs + fn.args.args}
    helper = next(n for n in ast.walk(ast.parse(inspect.getsource(orch)))
                  if isinstance(n, ast.FunctionDef) and n.name == "_visual_fast_release_args")
    keys = {k.value for d in ast.walk(helper) if isinstance(d, ast.Dict)
            for k in d.keys if isinstance(k, ast.Constant)}
    assert "blocking_average_live" not in keys
    assert "blocking_average" in keys, "non-vacuity"


def test_run_visual_fidelity_really_does_not_emit_it():
    """★ Non-vacuity for the whole finding: if the key is ever emitted, the revert's premise
    changes and #861 becomes revivable — which is the only condition under which it should be."""
    import ast
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(vf)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "run_visual_fidelity")
    keys = {k.value for d in ast.walk(fn) if isinstance(d, ast.Dict)
            for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert "blocking_average" in keys, "non-vacuity: the emitted key must still be there"
    assert "blocking_average_live" not in keys


@pytest.mark.parametrize("kw,want", [
    ({"blocking_average": 0.72}, "fast_release"),
    ({"blocking_average": 0.50}, "defer"),
    ({"blocking_average": 0.72, "avg_stable_rounds": 1}, "defer"),
    ({"blocking_average": 0.72, "coverage_ok": False}, "defer"),
    ({"blocking_average": 0.72, "avg_release": False}, "defer"),
])
def test_the_original_558_conditions_are_intact(kw, want):
    """The revert must restore #558 exactly, not approximately."""
    assert orch._visual_release_decision(**{**_BASE, **kw}) == want


def test_the_app_dead_veto_still_dominates():
    """#750 is placed first and must keep beating a fast release."""
    assert orch._visual_release_decision(
        **{**_BASE, "blocking_average": 0.72, "app_dead": True}) == "defer"


def test_declining_the_fast_path_never_blocked_a_release():
    """Why this was a throughput regression and not a safety one: every other escape still fires.
    That is also why #861 survived a run without being noticed."""
    # ★ `avg_release=False` disables the fast path, which is what "declining it" means here.
    # The first version of this case left the fast path ENABLED and above the bar, so it fired
    # first and the assertion read as a regression — the test was wrong, the ordering is correct.
    off = {"blocking_average": 0.90, "avg_release": False}
    assert orch._visual_release_decision(
        **{**_BASE, **off, "deferred_since": 0.0, "now": 1e6, "escape_s": 2400}) == "release"
    assert orch._visual_release_decision(
        **{**_BASE, **off, "total_judgments": 99, "total_cap": 10}) == "release"
    assert orch._visual_release_decision(
        **{**_BASE, **off, "attempts": 99, "attempt_cap": 3}) == "release"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
