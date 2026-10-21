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
    # #1154 added two keys. This assertion is deliberately key-for-key -- the same
    # contract shape #750 and #558 extended rather than loosened -- so a new key has to
    # be declared here on purpose instead of appearing unnoticed.
    # #1203fx declares its key here on purpose, which is what this assertion is for: the
    # words of each BLOCKING page, so a clean run carries none.
    assert b == {"passed_records": 2, "failed_records": 0,
                 "pages_passed": ["a", "b"], "pages_failed": [],
                 "unreachable_records": 0, "pages_unreachable": [],
                 "words_failed": {}}


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
    recs = [{"name": "validation:ui_smoke:landing", "status": "passed", "recorded_at": t,
             "metadata": {"check": "ui_smoke", "page": "landing"}} for t in (1, 2, 3)]
    b = dg._ui_evidence_breadth_739(recs)
    assert b["passed_records"] == 1 and b["pages_passed"] == ["landing"]


def test_distinct_flows_are_still_counted_separately():
    recs = [{"name": f"validation:ui_smoke:p{i}", "status": "passed", "recorded_at": i,
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

# --- #1203r6: the announcement's DELIVERY, which `caplog` only looked like it checked ---------
#
# `test_a_true_verdict_over_failures_is_announced` takes the `caplog` fixture, opens
# `caplog.at_level(logging.WARNING)` -- and then merely REFERENCES `validate_delivery_gate`
# (the `noqa: B018` on that line admits the statement does nothing) before asserting on
# `inspect.getsource`. So the log-capture machinery is set up and never used, and the test
# reads as a behavioural check of the emission while being purely textual.
#
# mut_739 measured what that costs. Two mutations leave every asserted string in place:
#
#   B1  `if _sc1202ad("ui_smoke_existential_739", ...)` -> `if False and _sc1202ad(...)`
#       the warning is emitted ZERO times                                        MISSED
#   B2  `logger.warning(...)` -> `logger.debug(...)` at that site
#       it vanishes from the operator's log at WARNING level                     MISSED
#   B3  the guarding condition removed (pinned as a whole literal)               CAUGHT
#
# `validate_delivery_gate` needs a populated hub set and an output tree, so it cannot be
# called from here; these assert on the AST instead, and -- per #1203r4 -- on what the code
# MEANS rather than on which identifiers appear in it.

def test_the_739_warning_is_emitted_at_warning_level_1203r6():
    """A diagnostic demoted to debug is invisible where it is meant to be read."""
    import ast
    tree = ast.parse(inspect.getsource(dg.validate_delivery_gate).lstrip())
    sites = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                and first.value.startswith("#739 ui_smoke_pass=True rests on"):
            sites.append(node)
    assert len(sites) == 1, "expected exactly one #739 announcement, found %d" % len(sites)
    fn = sites[0].func
    assert isinstance(fn, ast.Attribute), ast.unparse(fn)
    assert fn.attr == "warning", (
        "the #739 announcement is emitted with logger.%s -- at that level the operator never "
        "sees that a True ui_smoke verdict rests on failing records" % fn.attr)


def test_the_739_announcement_is_not_gated_off_1203r6():
    """The say-once gate decides WHETHER it is ever emitted, so the gate must be the whole
    condition -- not one term of an `and` whose other term can switch it off."""
    import ast
    tree = ast.parse(inspect.getsource(dg.validate_delivery_gate).lstrip())
    guards = [n for n in ast.walk(tree)
              if isinstance(n, ast.If) and "ui_smoke_existential_739" in ast.unparse(n.test)]
    assert len(guards) == 1, [ast.unparse(g.test) for g in guards]
    test = guards[0].test
    assert isinstance(test, ast.Call), (
        "the say-once gate is no longer the whole condition -- something else can suppress "
        "the announcement without touching its text: %s" % ast.unparse(test))
    assert "_sc1202ad" in ast.unparse(test.func), ast.unparse(test)
