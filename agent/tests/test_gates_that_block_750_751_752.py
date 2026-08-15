r"""#750/#751/#752: three delivery gates go from REPORTING to BLOCKING. User-approved.

Everything found this session (#736-#749) reported and decided nothing, and the corpus says what
that costs (#755-CORRECTED figures): of 149 runs only **29 ever cut a real release**; 14 carry a
frontend runtime-crash signature and **3 released**; 86 carry an unresolved P0 bug and **15
released**. An earlier reading said 14/14 and 90/90 — inflated by counting a bootstrap
`{"version": 1}` document in codehub_releases as a release tag. r148 is the concrete case and is
unaffected: it cut v1.0.0 with the SPA throwing `TypeError: (void 0) is not a function` on every
authenticated route.

Each blast radius was measured before the switch, and one of the three was deliberately split:

    #750  blackout past the refund cap AND console errors   -> would have caught r148
    #751  a task in status `failed`                          20 of 148 runs   (13%)
    #752  UI evidence that both passes and fails              6 of 148 runs   ( 4%)
    ---- NOT enabled -----------------------------------------------------------------
          any open P0 bug (#743)                             90 of 129 runs   -> a halt
          UI evidence MISSING entirely (#671's matrix)       67 of 148 runs   -> a halt

#750 is a VETO rather than another escape condition: every branch of
`_visual_release_decision` returns "release", and an escape answers "have we waited long
enough", which is not a question a blank page has a good answer to. It is also narrow in a way
that was impossible before this session — "the capture blanked" alone is #75a's business and can
be the harness rather than the app, which is exactly why the decision sat open; "blanked past the
refund cap AND the browser raised an uncaught error" is not ambiguous, and only #740 made the
second half observable.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_D = orch._visual_release_decision


# --- #750: no escape may ship an app that does not render ---------------------------------------

def _live_escape_kwargs(now=10_000.0):
    """Inputs that DO release today, one per escape, so the veto is tested against each."""
    return [
        ("wall-clock", dict(deferred_since=0.0, attempts=0, total_judgments=0, now=now)),
        ("attempt cap", dict(deferred_since=now, attempts=3, total_judgments=0, now=now)),
        ("total cap", dict(deferred_since=now, attempts=0, total_judgments=999, now=now)),
        ("plateau", dict(deferred_since=0.0, attempts=0, total_judgments=0, now=now,
                         plateau_rounds=99)),
        ("hard plateau", dict(deferred_since=now, attempts=0, total_judgments=0, now=now,
                              plateau_rounds=99)),
    ]


@pytest.mark.parametrize("label,kw", _live_escape_kwargs())
def test_every_escape_releases_without_the_veto(label, kw):
    """Non-vacuity: each of these really does release today, so the veto below means something."""
    assert _D(**kw) == "release", label


@pytest.mark.parametrize("label,kw", _live_escape_kwargs())
def test_the_veto_dominates_every_escape(label, kw):
    assert _D(app_dead=True, **kw) == "defer", label


def test_the_veto_dominates_the_fast_release_path_too():
    """#558's fast path fires before every time floor, so it is the one that must be checked
    explicitly rather than assumed to be covered by the others."""
    fast = dict(deferred_since=None, attempts=0, total_judgments=0, now=1.0,
                blocking_average=0.9, avg_min=0.65, avg_stable_rounds=99, coverage_ok=True)
    assert _D(**fast) == "fast_release", "non-vacuity: this really does fast-release"
    assert _D(app_dead=True, **fast) == "defer"


def test_the_default_is_off():
    """Every existing caller and test must be byte-identical without the new argument."""
    assert "app_dead: bool = False" in inspect.getsource(_D)


def test_the_veto_is_the_first_branch():
    src = inspect.getsource(_D)
    assert src.index("if app_dead:") < src.index("return \"fast_release\"")


def test_the_args_helper_carries_it_to_both_call_sites():
    src = inspect.getsource(orch._visual_fast_release_args)
    assert '"app_dead": bool(getattr(gate, "app_dead_750", False))' in src


def test_a_fresh_gate_is_not_dead():
    assert vf.VisualFidelityGate(None).app_dead_750 is False


def test_the_latch_is_set_only_with_BOTH_conditions():
    """A blackout alone must not veto — that is #75a's business and can be the harness."""
    src = inspect.getsource(vf.VisualFidelityGate.maybe_run)
    i = src.index("#750 (user-approved)")
    blk = src[i:src.index("_improved = False", i)]
    assert "self.transient_refunds >= _TRANSIENT_REFUND_CAP and _errs750" in blk


def test_the_latch_clears_when_a_capture_renders():
    src = inspect.getsource(vf.VisualFidelityGate.maybe_run)
    assert "#750 veto CLEARED" in src
    assert "self.app_dead_750 = False" in src


def test_the_veto_explains_the_trade_in_place():
    d = " ".join(inspect.getsource(_D).replace("#", " ").split())
    assert "no app is better than an app that renders nothing" in d
    assert "3 of them\n    # released" in d or "3 of them" in d


# --- #751: a task explicitly marked failed blocks -------------------------------------------------

def _gate_src() -> str:
    return inspect.getsource(dg.validate_delivery_gate)


def test_a_failed_task_blocks():
    g = _gate_src()
    assert 'if _bugs743.get("failed_count"):' in g
    assert 'failed_checks.append("unresolved_failed_tasks")' in g


def test_open_p0_bugs_still_only_report():
    """#743 measured 90 of 129 — a halt. It must NOT have been switched on by association."""
    g = _gate_src()
    assert 'failed_checks.append("unresolved_p0_bugs")' not in g
    # Anchored on the statement that ends #751's block, not a character count.
    blk = g[g.index("#751 (user-approved)"):g.index("incomplete_tasks = incomplete_required_tasks")]
    assert "stays REPORTED" in blk


def test_751_records_both_numbers_it_chose_between():
    g = " ".join(_gate_src().replace("#", " ").split())
    assert "90 of 129 runs would block" in g
    assert "20 of 148 runs would block" in g


def test_751_records_how_a_lane_clears_it():
    g = " ".join(_gate_src().replace("#", " ").split())
    assert "complete the task, or cancel it if it was wrong" in g


# --- #752: contradicted UI evidence blocks, missing UI evidence does not ---------------------------

def _rec(check, status):
    return {"status": status, "metadata": {"check": check}}


def test_contradicted_evidence_blocks():
    g = _gate_src()
    assert 'if _breadth739["failed_records"]:' in g
    assert 'failed_checks.append("validation_ui_evidence_failed")' in g


def test_missing_evidence_stays_behind_671s_condition():
    """67 of 148 runs have no UI evidence at all. Blocking those is a stop, not a gate."""
    g = _gate_src()
    i = g.index('failed_checks.append("validation_ui_smoke_missing")')
    before = g[:i]
    assert "if task_suite_exists:" in before, "the missing case must stay gated on the matrix"


def test_the_two_cases_are_distinguished_in_the_record():
    g = " ".join(_gate_src().replace("#", " ").split())
    assert "6 of 148 runs -> 4%, a gate" in g
    assert "67 of 148 runs -> 45%, a halt" in g


@pytest.mark.parametrize("spelling", ["failed", "failure", "error"])
def test_every_failure_spelling_counts(spelling):
    """The raw store carries `failure` 252 times and `failed` never; a record that skipped
    #193/#236's normaliser must not read as neither now that this blocks."""
    b = dg._ui_evidence_breadth_739([_rec("ui_flow", spelling)])
    assert b["failed_records"] == 1


@pytest.mark.parametrize("spelling", ["passed", "success", "pass"])
def test_every_pass_spelling_counts(spelling):
    b = dg._ui_evidence_breadth_739([_rec("ui_smoke", spelling)])
    assert b["passed_records"] == 1


def test_an_unknown_status_counts_as_neither():
    b = dg._ui_evidence_breadth_739([_rec("ui_smoke", "pending")])
    assert b["passed_records"] == 0 and b["failed_records"] == 0


def test_the_r148_shape_now_blocks():
    """Two passing (landing, login) against six failing ui_flow records."""
    recs = [_rec("ui_smoke", "passed")] * 2 + [_rec("ui_flow", "failed")] * 6
    b = dg._ui_evidence_breadth_739(recs)
    assert dg._ui_smoke_pass(recs) is True, "the existential verdict is deliberately unchanged"
    assert b["failed_records"] == 6, "and this is what now blocks alongside it"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
