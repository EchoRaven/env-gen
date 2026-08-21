r"""#1024: the three checks behind `task_suite_exists` have never fired — audited, not activated.

Sweeping every check token the gate can emit against all 298 run logs, 12 of 21 have never
fired. Nine are fine (empty-hub safety nets that correctly never trigger, plus two documented
vestigial `semantic_*`). Three are structurally dead:

    validation_api_smoke_missing
    validation_ui_smoke_missing
    validation_retry_pending

all inside `if task_suite_exists:`, and `tasks/tasks.yaml` exists in **0 of 172 runs**.

★ WHAT IS *NOT* TRUE, because it misled the last two readers of this code (#671 partially, and
a full re-derivation of it): the measurements are NOT dead. `api_smoke_pass` and
`ui_smoke_pass` are computed unconditionally and published in `validation_runtime` every run.
Only the ENFORCEMENT is gated. The old `matrix_skipped_reason` said "the API-smoke and UI-smoke
requirements were NOT evaluated" and then, in the same sentence, "api_smoke_pass/ui_smoke_pass
below are REPORTED" — a self-contradiction that reads as a dead validation layer. #1024 fixes
the wording; the class is #694/#682/#690, where the text costs the rounds, not the detection.

Root cause, past where #671 stopped: `tasks/tasks.yaml` HAS a producer — `save_task_suite`,
one of the five `task_definition_tools` — the verifier IS granted them (agents_config
`tool_categories` includes `task_definition`) and the verifier does spawn. None of the five
tool names appears in ANY of the 298 logs, while `agent_definition.j2` instructs every agent
to use them. Dead by agent choice, not by a missing grant.

★ DELIBERATELY NOT ACTIVATED. #671 measured the consequence: "no UI evidence at all — 67 of
148 runs, 45%, a halt". #752 already blocks the case that catches a genuinely dead app —
CONTRADICTED evidence (passing and failing UI records together, 6 of 148 runs, 4%) — and does
it unconditionally, regardless of `task_suite_exists`. So the failure mode r148 shipped
(`ui_smoke_pass=True` while the SPA crashed on 12 of 14 pages) is already covered, and turning
these on would add a 45% halt for ABSENT evidence without adding that coverage.

★ DELIBERATELY NOT DELETED. The measurement behind them is live, published and useful; the
enforcement is a switch someone may want once evidence coverage improves.

So: audited. This test exists so the next reader spends one `ls agent/tests | grep -i
task_suite` instead of a session.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg

_DEAD = ("validation_api_smoke_missing", "validation_ui_smoke_missing",
         "validation_retry_pending")


def _gate_src():
    return inspect.getsource(dg.validate_delivery_gate)


def test_all_three_sit_behind_task_suite_exists():
    """If one is ever moved out of the branch it becomes live, and this file's premise dies."""
    src = _gate_src()
    i = src.index("if task_suite_exists:")
    # the branch runs until the next dedented statement at the same level
    tail = src[i:]
    end = re.search(r"\n    [^\s#]", tail)
    block = tail[:end.start()] if end else tail
    for tok in _DEAD:
        assert tok in block, f"{tok} is no longer behind task_suite_exists — re-measure it"


def test_they_are_appended_nowhere_else():
    """Count APPENDS, not mentions — the skip message now names all three in prose, and a bare
    substring count would read those as emission sites."""
    src = _gate_src()
    for tok in _DEAD:
        n = len(re.findall(r'failed_checks\.append\(\s*["\']' + re.escape(tok) + r'["\']', src))
        assert n == 1, (
            f"{tok} has {n} emission sites; the dead-branch claim needs re-checking")


def test_the_measurements_are_NOT_gated():
    """★ The correction. Both values are computed unconditionally — it is only the blocking
    that is off. Reading this the other way is what cost two sessions."""
    src = _gate_src()
    for name in ("api_smoke_pass =", "ui_smoke_pass ="):
        i = src.index(name)
        assert i < src.index("if task_suite_exists:"), (
            f"{name} must be computed before, and independently of, the gate branch")


def test_both_values_are_published_every_run():
    src = _gate_src()
    i = src.index('"validation_runtime"')
    block = src[i:]
    for key in ('"api_smoke_pass"', '"ui_smoke_pass"', '"task_suite_exists"',
                '"matrix_skipped_reason"'):
        assert key in block, f"{key} must travel with the verdict"


# --- the wording defect this fixes -----------------------------------------------------------

def _skip_reason():
    src = _gate_src()
    i = src.index("matrix_skipped_reason = ")
    return src[i:src.index("if task_suite_exists:", i)]


def test_the_message_no_longer_contradicts_itself():
    """It said the requirements "were NOT evaluated" and, in the same sentence, that the two
    values are "REPORTED". Both cannot be true, and the first is the false one."""
    r = _skip_reason()
    assert "were NOT evaluated" not in r
    assert "ARE evaluated" in r and "NOT ENFORCED" in r


def test_the_message_says_the_deadness_is_STRUCTURAL():
    """"no tasks/tasks.yaml" alone reads as 'not this run'. It has never happened in any run,
    and a reader needs to know which."""
    r = _skip_reason()
    assert "0 of 172 runs" in r
    assert "never fired" in r or "never been called" in r


def test_the_message_names_the_three_checks():
    r = _skip_reason()
    for tok in _DEAD:
        assert tok in r, f"{tok} is gated by this flag but the skip message does not name it"


# --- the decision, recorded so it is not silently reversed -------------------------------------

def test_the_reason_for_not_activating_is_recorded():
    """A future reader must find the measurement, not just the disposition."""
    d = " ".join((__doc__ or "").split())
    assert "67 of 148" in d and "45%" in d, "the halt measurement must travel with the decision"
    assert "6 of 148" in d and "#752" in d, (
        "the reason activation adds no coverage — #752 already blocks the contradicted case")


def test_the_root_cause_is_recorded_not_just_the_symptom():
    """#671 recorded 'tasks.yaml has never existed'. The re-derivation cost was the chain
    below it: a granted producer that no agent ever calls."""
    d = " ".join((__doc__ or "").split())
    assert "save_task_suite" in d
    assert "298 logs" in d
    assert "not by a missing grant" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
