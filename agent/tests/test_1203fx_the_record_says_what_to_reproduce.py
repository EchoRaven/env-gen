"""#1203fx — the remediation body told the lane to reproduce a report it never quoted.

`_ui_evidence_failed_extra` closes with "open each page, reproduce what the record reports,
repair it, then re-run the walk so the record flips". The report is on the record the gate
blocked on, and `_ui_evidence_breadth_739` had it in hand: it joins error/detail/message/
reason/evidence/output into a `_blob` to run #1154's reachability match, then returns page
NAMES only.

Measured over every run directory: 291 failing `validation:ui_{flow,smoke}:*` records across
89 runs, of which 285 carry readable words (54 of the 291 are `ui_smoke`, a shape #1203ft's
codehub reader structurally cannot see). They read like "origin/destination fields could be
filled but route submit control was not interactable" — the whole repair, already written.

`validation_ui_evidence_failed` is the instrument for the most common live blocker (#1040:
7 of the last 10 declining runs), so this is the richest evidence line in the dispatcher.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


def _rec(flow, status, summary=None, kind="ui_flow", **ev):
    e = dict(ev)
    if summary is not None:
        e["summary"] = summary
    return {"name": f"validation:{kind}:{flow}", "status": status,
            "metadata": {"check": kind, "flow": flow}, "evidence": e}


class _Orch:
    """Only the external world is a stand-in: the real `_ui_evidence_breadth_739` runs."""

    def __init__(self, records):
        self._records = list(records)

    def _get_validation_results(self, limit=200):
        return self._records[: max(1, int(limit))]


# --------------------------------------------------------------------------- the gate half

def test_the_gate_returns_the_words_beside_the_names():
    rep = dg._ui_evidence_breadth_739([
        _rec("checkout", "failed", "POST /api/orders returned 401 with a valid token"),
        _rec("landing", "success", "fine"),
    ])
    assert rep["pages_failed"] == ["checkout"]
    assert rep["words_failed"] == {
        "checkout": "POST /api/orders returned 401 with a valid token"}


def test_the_words_are_keyed_by_the_same_label_as_the_verdict():
    """Not a second labelling scheme: every key must be a page the gate itself blocked on."""
    rep = dg._ui_evidence_breadth_739([
        _rec("a", "failed", "one"), _rec("b", "failure", "two"),
        _rec("c", "error", "three"), _rec("d", "success", "passing"),
    ])
    assert set(rep["words_failed"]) <= set(rep["pages_failed"])
    assert set(rep["words_failed"]) == {"a", "b", "c"}, rep["words_failed"]


def test_a_passing_page_never_contributes_words():
    rep = dg._ui_evidence_breadth_739([_rec("landing", "success", "all good here")])
    assert rep["words_failed"] == {}
    assert "landing" not in rep["words_failed"]


def test_ui_smoke_records_carry_words_too():
    """54 of the 291 measured failures are ui_smoke — the shape #1203ft cannot read."""
    rep = dg._ui_evidence_breadth_739(
        [_rec("home", "failed", "the SPA threw TypeError: (void 0) is not a function",
              kind="ui_smoke")])
    assert rep["words_failed"] == {
        "home": "the SPA threw TypeError: (void 0) is not a function"}


def test_a_record_with_no_words_is_simply_absent():
    """6 of 291 carry nothing readable; the caller then prints the name alone, as before."""
    rep = dg._ui_evidence_breadth_739(
        [_rec("home", "failed", kind="ui_smoke", verdict="fail",
              screenshot="screenshot_20260714_194222.png")])
    assert rep["pages_failed"] == ["home"]
    assert rep["words_failed"] == {}


def test_a_record_folded_back_by_1154_keeps_its_words():
    """#1154 discounts a connection-level failure only while something else passed. With
    nothing passing it folds back into `pages_failed` — and must bring its words."""
    rep = dg._ui_evidence_breadth_739(
        [_rec("login", "failed", "POST /auth/register ERR_CONNECTION_REFUSED")])
    assert rep["pages_failed"] == ["login"], rep
    assert rep["words_failed"] == {
        "login": "POST /auth/register ERR_CONNECTION_REFUSED"}, rep


def test_a_discounted_unreachable_record_is_not_reported_as_blocking():
    """The other side of the same rule: with a passing record present the unreachable one is
    discounted, so it is not in `pages_failed` and its words must not be quoted as a blocker."""
    rep = dg._ui_evidence_breadth_739([
        _rec("login", "failed", "POST /auth/register ERR_CONNECTION_REFUSED"),
        _rec("landing", "success", "fine"),
    ])
    assert rep["pages_unreachable"] == ["login"], rep
    assert rep["pages_failed"] == [], rep
    assert rep["words_failed"] == {}, rep


# ------------------------------------------------------- where the words come off the record

@pytest.mark.parametrize("record,expected", [
    ({"summary": "top-level"}, "top-level"),
    ({"evidence": {"summary": "nested"}}, "nested"),
    ({"evidence": {"reason": "a reason"}}, "a reason"),
    ({"reason": "top reason"}, "top reason"),
    ({"error": "an error"}, "an error"),
    ({"detail": "a detail"}, "a detail"),
    ({"message": "a message"}, "a message"),
    ({"evidence": {"verdict": "fail", "screenshot": "x.png"}}, ""),
    ({}, ""),
    ("not a dict", ""),
    (None, ""),
])
def test_the_words_come_off_either_record_shape(record, expected):
    """`_get_validation_results` lifts `evidence.summary` to the top level while
    `hub_registry.get_validation_results` need not — both spellings must resolve."""
    assert dg._record_own_words_1203fx(record) == expected


def test_summary_wins_over_the_narrower_error_fields():
    assert dg._record_own_words_1203fx(
        {"summary": "the walk's sentence", "error": "KeyError"}) == "the walk's sentence"


# --------------------------------------------------------------------- the dispatcher half

def test_the_diagnosis_quotes_the_record_for_each_named_page():
    orch = _Orch([
        _rec("directions", "failed",
             "origin/destination fields could be filled but route submit control was not "
             "interactable"),
        _rec("login", "failed", "POST /auth/login returned 401 with valid credentials"),
    ])
    pages = rd._ui_evidence_failed_pages(orch)
    assert sorted(pages) == ["directions", "login"], pages
    out = rd.ui_evidence_failed_evidence_1203fx(orch, pages)
    assert "route submit control was not interactable" in out
    assert "401 with valid credentials" in out
    assert "directions" in out and "login" in out


def test_the_diagnosis_is_silent_when_the_writer_left_no_words():
    orch = _Orch([_rec("home", "failed", kind="ui_smoke", verdict="fail")])
    assert rd._ui_evidence_failed_pages(orch) == ["home"]
    assert rd.ui_evidence_failed_evidence_1203fx(orch, ["home"]) == ""


def test_the_diagnosis_only_quotes_pages_it_was_asked_about():
    orch = _Orch([_rec("a", "failed", "about a"), _rec("b", "failed", "about b")])
    out = rd.ui_evidence_failed_evidence_1203fx(orch, ["a"])
    assert "about a" in out and "about b" not in out


def test_the_body_the_lane_receives_both_instructs_and_quotes():
    """The #982 paragraph says 'reproduce what the record reports'. Both halves must be in
    the same body — the instruction is what makes the quote actionable, and vice versa."""
    orch = _Orch([_rec("checkout", "failed", "POST /api/orders returned 401")])
    pages = rd._ui_evidence_failed_pages(orch)
    body = (rd._ui_evidence_failed_extra(pages)
            + rd.ui_evidence_failed_evidence_1203fx(orch, pages))
    assert "reproduce what the record reports" in body
    assert "POST /api/orders returned 401" in body


def test_a_long_record_is_capped_but_not_emptied():
    orch = _Orch([_rec("checkout", "failed", "x" * 5000)])
    out = rd.ui_evidence_failed_evidence_1203fx(orch, ["checkout"])
    assert "x" * 400 in out
    assert "x" * 401 not in out


def test_the_diagnosis_never_raises():
    for bad in (None, object(), _Orch(["not a dict", None, 7])):
        assert rd.ui_evidence_failed_evidence_1203fx(bad, ["anything"]) == ""
        assert rd.ui_evidence_failed_evidence_1203fx(bad, []) == ""


# ------------------------------------------------------------------- structure, not substring

def test_the_diagnosis_is_composed_into_the_blocking_branch():
    """Structural, over the dispatch source: #1178 is the standing lesson that a helper can
    be perfect and never reached. Anchored on the `_extra` assignment, not on the ticket
    string (which also appears inside the comment beside it)."""
    src = inspect.getsource(rd)
    i = src.index('if name == "validation_ui_evidence_failed":')
    j = src.index('if name == "deliverability_ui_flow_failed":', i)
    branch = src[i:j]
    assert "_extra = (_ui_evidence_failed_extra(_fp)" in branch
    assert "ui_evidence_failed_evidence_1203fx(orch, _fp)" in branch


def test_the_producer_and_the_diagnosis_share_one_fetch():
    """#1178 was a duplicated reader that drifted. Two consumers, one fetch — asserted by
    the absence of a second `_get_validation_results` reach outside the shared function."""
    reaches = [n for n in ("_ui_evidence_failed_pages", "ui_evidence_failed_evidence_1203fx")
               if "_get_validation_results" in inspect.getsource(getattr(rd, n))]
    assert reaches == [], f"{reaches} fetch validation results themselves"
    assert "_get_validation_results" in inspect.getsource(rd._ui_evidence_report_1203fx)


def test_the_gate_collects_words_before_the_reachability_test_decides():
    """The words must be taken off the record independently of which list the page lands in;
    collecting them inside the `else` would lose every #1154 fold-back. Asserted over the
    AST: the collection must sit in the failure branch but NOT inside the `if`/`else` that
    splits unreachable from failed."""
    import ast
    tree = ast.parse(inspect.getsource(dg._ui_evidence_breadth_739))
    fn = tree.body[0]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_record_own_words_1203fx"]
    assert len(calls) == 1, "exactly one collection point"
    target = calls[0]
    # the innermost `if` whose body (not orelse) contains the call must be the status test,
    # i.e. the call must NOT be nested inside the unreachable-vs-failed split
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            for branch in (node.body, node.orelse):
                if any(target is c for b in branch for c in ast.walk(b)
                       if isinstance(c, ast.Call)):
                    src = ast.unparse(node.test)
                    assert "_UNREACHABLE_1154" not in src and "unreachable" not in src, (
                        f"the collection sits inside the reachability split ({src})")


def test_a_long_list_is_cut_and_says_so():
    """#1034: declare the cut. googlemaps-r16 reports one global defect on 12 pages."""
    orch = _Orch([_rec(f"p{i}", "failed", f"sentence {i}") for i in range(12)])
    pages = rd._ui_evidence_failed_pages(orch)
    assert len(pages) == 12
    out = rd.ui_evidence_failed_evidence_1203fx(orch, pages)
    assert out.count("\n- ") == 8, out
    assert "4 more failing page(s) carry a recorded sentence too" in out


def test_a_list_at_the_cap_says_nothing_about_a_cut():
    orch = _Orch([_rec(f"p{i}", "failed", f"sentence {i}") for i in range(8)])
    out = rd.ui_evidence_failed_evidence_1203fx(orch, rd._ui_evidence_failed_pages(orch))
    assert out.count("\n- ") == 8
    assert "more failing page(s)" not in out


# ------------------------------------------- the writers' own spellings of the same sentence

@pytest.mark.parametrize("evidence,expected", [
    ({"failure_reason": "ui_fyp_feed loads with 401 on GET /api/feed/for-you"},
     "ui_fyp_feed loads with 401 on GET /api/feed/for-you"),
    ({"note": "Every route renders empty <div id=root/> with React crash"},
     "Every route renders empty <div id=root/> with React crash"),
    ({"notes": "Anon GETs on /api/videos/1 return 401"},
     "Anon GETs on /api/videos/1 return 401"),
    ({"root_cause_hypothesis": "frontend regressed to fallback shell across all routes"},
     "frontend regressed to fallback shell across all routes"),
    ({"failing_request": "GET /api/feed/foryou -> 401 (spec says public per M1 §3.5)"},
     "GET /api/feed/foryou -> 401 (spec says public per M1 §3.5)"),
    ({"console_error": "TypeError: Cannot destructure property 'user' of useContext(...)"},
     "TypeError: Cannot destructure property 'user' of useContext(...)"),
])
def test_a_writers_own_spelling_still_yields_the_sentence(evidence, expected):
    """29 of the 69 records `summary`/`reason` missed carry the sentence under another name.
    Every key here was taken from a real failing record on disk."""
    assert dg._record_own_words_1203fx({"evidence": evidence}) == expected


def test_an_expected_actual_pair_is_composed_into_one_sentence():
    """10 records split it in two; neither half alone says what happened."""
    out = dg._record_own_words_1203fx({"evidence": {
        "expected": "FYP feed renders with >=3 <video> elements",
        "actual": "Fallback login form rendered at /"}})
    assert out == ("expected FYP feed renders with >=3 <video> elements; "
                   "actual Fallback login form rendered at /")


def test_half_an_expected_actual_pair_is_not_a_sentence():
    assert dg._record_own_words_1203fx({"evidence": {"expected": "three videos"}}) == ""
    assert dg._record_own_words_1203fx({"evidence": {"actual": "a login form"}}) == ""


def test_a_bug_pointer_is_reported_as_a_pointer():
    """6 records name only the bug task. Useful, but it must not read as the report itself."""
    out = dg._record_own_words_1203fx({"evidence": {"root_cause_bug": "task_bd2852ab93"}})
    assert out == "root cause filed as task_bd2852ab93 — open that task for the detail"


def test_prose_always_wins_over_the_bug_pointer():
    out = dg._record_own_words_1203fx({"evidence": {
        "root_cause_bug": "task_bd2852ab93",
        "failure_reason": "POST /api/comments returned 401"}})
    assert out == "POST /api/comments returned 401"


@pytest.mark.parametrize("evidence", [
    {"screenshot": "shot.png"}, {"run_id": "r164"}, {"flow": "checkout"},
    {"screenshot": "s.png", "url": "http://x/", "verdict": "fail"},
    {"console_errors": 2}, {"network_errors": [{"status": 401}]},
    {"observed_dom": "<div id='root'></div>"},
])
def test_a_field_that_is_not_prose_is_never_quoted(evidence):
    """The 40 records that genuinely say nothing must stay silent — quoting a filename or a
    count under "its own words" would be worse than printing the page name alone."""
    assert dg._record_own_words_1203fx({"evidence": evidence}) == ""


def test_the_field_list_excludes_the_shape_shifting_keys():
    """`console_errors`/`network_errors` are an int in some records and a list of dicts in
    others; a str-only read would be silently inconsistent, so they are excluded by name."""
    for k in ("console_errors", "network_errors", "observed_dom", "screenshot", "url",
              "run_id", "verdict", "flow", "steps", "steps_completed"):
        assert k not in dg._WORD_FIELDS_1203FX, k
