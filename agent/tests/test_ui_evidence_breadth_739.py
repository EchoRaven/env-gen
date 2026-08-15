r"""#739: `ui_smoke_pass` is existential, so one working page certifies the whole UI.

`_ui_smoke_pass` (#287) returns True if ANY validation record is a passed UI-evidence check,
and it never consults a FAILING one. r148 read `ui_smoke_pass=True` off "ui_smoke on landing +
login PASS" while the SPA threw `TypeError: (void 0) is not a function` on 12 of 14 pages, and
the run released v1.0.0.

What makes this worth recording rather than just fixing is a decision already pending. #671
measured that the UI-smoke requirement has NEVER been evaluated: it sits behind
`task_suite_exists`, and `tasks/tasks.yaml` exists in 0 of 144 runs. Its recorded next step is
"enforcing it needs a live run". **r148 shows enforcement alone would not have caught it** —
landing and login passed, so `ui_smoke_pass` is True either way, and switching the matrix on
changes nothing for exactly the failure that motivates switching it on. The predicate has to
stop being existential too, and that is not a change to make blind.

So: counts beside the verdict, and a warning when a True verdict sits on top of failing UI
records. No decision changes — same disposition as #711, #715 and #738.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _rec(check, status, page=None, **meta):
    m = {"check": check}
    if page:
        m["page"] = page
    m.update(meta)
    return {"status": status, "metadata": m}


_R148 = [
    _rec("ui_smoke", "passed", "landing"),
    _rec("ui_smoke", "passed", "login"),
    _rec("ui_flow", "failed", "browse_home_page"),
    _rec("ui_flow", "failed", "games_page"),
    _rec("ui_flow", "failed", "movies_page"),
    _rec("ui_flow", "failed", "my_list_page"),
    _rec("ui_flow", "failed", "new_and_popular_page"),
    _rec("ui_flow", "failed", "shows_page"),
]


# --- the r148 shape ---------------------------------------------------------------------------

def test_the_verdict_is_still_true_which_is_the_point():
    """#739 must not change the decision. If this ever flips, it became a gate."""
    assert dg._ui_smoke_pass(_R148) is True


def test_the_breadth_shows_what_it_rests_on():
    b = dg._ui_evidence_breadth_739(_R148)
    assert b["passed_records"] == 2
    assert b["failed_records"] == 6
    assert b["pages_passed"] == ["landing", "login"]
    assert "browse_home_page" in b["pages_failed"]


def test_a_true_verdict_over_failures_is_announced(caplog):
    with caplog.at_level(logging.WARNING):
        dg.validate_delivery_gate  # noqa: B018 - referenced so the import is meaningful
    src = inspect.getsource(dg.validate_delivery_gate)
    assert "#739 ui_smoke_pass=True rests on" in src
    assert 'if ui_smoke_pass and _breadth739["failed_records"]:' in src


# --- it counts honestly -------------------------------------------------------------------------

def test_a_clean_run_reports_no_failures():
    b = dg._ui_evidence_breadth_739([_rec("ui_smoke", "passed", "a"),
                                     _rec("ui_flow", "passed", "b")])
    assert b == {"passed_records": 2, "failed_records": 0,
                 "pages_passed": ["a", "b"], "pages_failed": []}


def test_non_ui_records_are_ignored():
    b = dg._ui_evidence_breadth_739([_rec("api_smoke", "passed", "x"),
                                     _rec("api_health", "failed", "y")])
    assert b["passed_records"] == 0 and b["failed_records"] == 0


def test_error_counts_as_a_failure():
    b = dg._ui_evidence_breadth_739([_rec("ui_flow", "error", "p")])
    assert b["failed_records"] == 1


def test_every_accepted_check_kind_is_counted():
    """It must track _UI_SMOKE_EVIDENCE_CHECKS, not a hand-copied subset."""
    for c in dg._UI_SMOKE_EVIDENCE_CHECKS:
        assert dg._ui_evidence_breadth_739([_rec(c, "passed", "p")])["passed_records"] == 1, c


def test_the_page_name_falls_back_across_the_shapes_records_use():
    for key in ("page", "route", "name"):
        b = dg._ui_evidence_breadth_739([{"status": "passed",
                                          "metadata": {"check": "ui_smoke", key: "/browse"}}])
        assert b["pages_passed"] == ["/browse"], key


def test_an_unnamed_record_is_counted_not_dropped():
    """Under-counting evidence would understate the problem, which is the wrong direction."""
    b = dg._ui_evidence_breadth_739([_rec("ui_smoke", "passed")])
    assert b["passed_records"] == 1 and b["pages_passed"] == ["?"]


def test_repeats_of_ONE_flow_collapse_to_its_latest():
    """#757 changed this, and the old fixture hid why. It was `[_rec(...)] * 3` — three
    REFERENCES to one object — and the old code counted them as three records. Real records
    carry a `name` (`validation:ui_flow:landing`) and three writes of one flow are one flow's
    history, not three flows. Distinct pages still count distinctly, below."""
    recs = [{"name": "validation:ui_smoke:landing", "status": "passed", "updated_at": t,
             "metadata": {"check": "ui_smoke", "page": "landing"}} for t in (1, 2, 3)]
    b = dg._ui_evidence_breadth_739(recs)
    assert b["passed_records"] == 1 and b["pages_passed"] == ["landing"]


def test_distinct_flows_are_still_counted_separately():
    recs = [{"name": f"validation:ui_smoke:p{i}", "status": "passed", "updated_at": i,
             "metadata": {"check": "ui_smoke"}} for i in range(3)]
    assert dg._ui_evidence_breadth_739(recs)["passed_records"] == 3


@pytest.mark.parametrize("junk", [None, [], [None], ["x"], [{"status": "passed"}]])
def test_junk_input_is_tolerated(junk):
    b = dg._ui_evidence_breadth_739(junk)
    assert b["passed_records"] == 0 and b["failed_records"] == 0


# --- provenance -----------------------------------------------------------------------------------

def test_it_records_that_enforcement_alone_would_not_have_caught_r148():
    """The whole reason this is a finding and not a tidy-up."""
    d = " ".join((dg._ui_evidence_breadth_739.__doc__ or "").split())
    assert "enforcement alone would not have caught it" in d
    assert "0 of 144 runs" in d


def test_it_records_the_existential_defect_itself():
    d = " ".join((dg._ui_evidence_breadth_739.__doc__ or "").split())
    assert "existential" in d
    assert "FAILING UI record is not consulted at all" in d
    assert "12 of 14 pages" in d      # `d` is whitespace-collapsed, so the wrap is harmless


def test_it_records_that_it_decides_nothing():
    d = " ".join((dg._ui_evidence_breadth_739.__doc__ or "").split())
    assert "changes no decision" in d


def test_the_287_rationale_is_not_overwritten():
    """#287 accepted ui_flow for a real reason — a passing flow IS strong evidence. #739
    narrows nothing; it only says how much of the app the evidence covers."""
    # Matched WITHIN one line: the sentence wraps in the source after "A passing", and an
    # assertion spanning the break is the quotation trap, not a finding.
    src = inspect.getsource(dg)
    assert "ui_flow is STRICTLY STRONGER UI evidence than ui_smoke" in src
    assert dg._UI_SMOKE_EVIDENCE_CHECKS == {"ui_smoke", "ui_page_reachable", "ui_flow"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
