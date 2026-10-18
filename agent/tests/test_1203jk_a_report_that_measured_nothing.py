r"""#1203jk: "a report exists" stopped meaning "a walk happened".

#1203ja skips the final-release walk when `test_user_reports/<tag>.json` exists, so it can
never overwrite the record the #1202nm pre-release gate wrote — tiktok-web-r108 took the
final path and HAS that report, and replacing a gate-relevant record with a post-shutdown
one is the harm. "Exists" was the right proxy while a report always meant a walk.

★ #1203je broke that proxy, and PROJECTING IT OVER THE CORPUS is what shows it: a frontend
that never served now yields `ui_flows.ran == False` with no flows, instead of flow
failures. Over the 263 persisted reports, "no evidence at all" (`api_steps == 0` AND the UI
walk did not run) occurs twice, both July, both from "no frontend port". But of the 52
reports carrying the ERR_CONNECTION_REFUSED records #1203je replaces, 18 already have
`api_steps == 0` — so that shape goes from twice-ever to roughly 18 across 25 runs, and
every one would make the final cut skip its walk on the strength of a report that measured
NOTHING. A frontend that was down earlier is exactly when the final cut — where the visual
gate has just measured the app LIVE — is worth walking.

★★ Found by cross-checking this session's own patches against each other, which is the
fifth time that paid today. `feedback_project_the_patch_over_the_corpus_before_landing_it`
is the rule I should have applied when #1203je landed: #1203je changed the SHAPE that
#1203ja's idempotence check reads, and nothing made the two meet.
"""
import json
import os
import pathlib
import sys
import types

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.orchestrator as ORCH  # noqa: E402


class _Log:
    def debug(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _ask(tmp_path, report, version="1.2.0"):
    if report is not None:
        d = tmp_path / "test_user_reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / ("%s.json" % version)).write_text(
            report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
    o = types.SimpleNamespace(output_dir=pathlib.Path(tmp_path), _logger=_Log())
    return ORCH.Orchestrator._final_report_has_evidence_1203jk(o, version)


_UI_RAN = {"ran": True, "flows": [{"flow": "signup", "ok": True},
                                  {"flow": "login", "ok": True}]}


def test_a_walked_journey_is_never_overwritten(tmp_path):
    """r108's case, which #1203ja exists to protect: the pre-release gate already walked
    this tag.

    #1203na added `verdict` to this fixture, and to the three below, because it was the one
    thing they left out: all 129 version reports in the corpus carry a verdict, so a summary
    without one is a shape that has never existed. Leaving it out would have let these tests
    pass on the verdict gate alone and stop exercising the evidence logic they are named for
    -- the quiet kind of hollowing-out. The shape itself is pinned on purpose by
    `test_a_report_with_no_verdict_at_all_is_walked`."""
    assert _ask(tmp_path, {"summary": {"verdict": "ISSUES", "api_steps": 3},
                           "ui_flows": _UI_RAN}) is True


@pytest.mark.parametrize("verdict", ("ISSUES", "PASS", "PARTIAL"))
def test_a_walked_ui_alone_is_evidence(tmp_path, verdict):
    """The commonest real shape: 119 of the 263 reports have `api_steps == 0` with the UI
    walk having run, because the CRUD journey needs a creatable collection (#1203jc).

    Parametrised over the verdicts that population actually carries -- measured on the 129
    version reports: 31 ISSUES, 9 PASS, 7 PARTIAL."""
    assert _ask(tmp_path, {"summary": {"verdict": verdict, "api_steps": 0},
                           "ui_flows": _UI_RAN}) is True


def test_a_report_that_measured_nothing_is_rewalked(tmp_path):
    """★ THE TICKET. #1203je's new shape: the frontend never served, and the journey had
    nothing to drive. There is no evidence to lose, and the app is live at the final cut."""
    rep = {"summary": {"verdict": "NOT_WALKED", "api_steps": 0},
           "ui_flows": {"ran": False,
                        "reason": "frontend at http://localhost:8033 never served within "
                                  "the readiness budget (#1203je)"}}
    assert _ask(tmp_path, rep) is False


def test_a_ran_true_with_no_flows_is_not_evidence(tmp_path):
    """`ran` alone is not the claim — an empty container is not a fact (#1038's own words,
    in the function this feeds)."""
    assert _ask(tmp_path, {"summary": {"verdict": "NOT_WALKED", "api_steps": 0},
                           "ui_flows": {"ran": True, "flows": []}}) is False


def test_an_absent_report_is_walked(tmp_path):
    assert _ask(tmp_path, None) is False


def test_unreadable_json_fails_closed(tmp_path):
    """WITHOUT THIS IT IS A DATA-LOSS BUG: if we cannot tell what the existing report holds,
    overwriting it is the harm #1203ja named."""
    assert _ask(tmp_path, "{not json at all") is True


def test_a_report_that_is_not_an_object_names_the_right_cause(tmp_path):
    """★ THE VERDICT WAS NEVER THE POINT, and the mutation proved it: delete the non-object
    guard and `_rep.get("summary")` raises AttributeError, the handler fails closed, and the
    bool is still True — so asserting only the bool let that mutation survive.

    What the guard buys is the CAUSE. Without it the run logs "could not read the existing
    report", of a report that read perfectly well and simply is not one. Naming the wrong
    cause is the defect this project removes most often, so this asserts the message.
    """
    msgs = []

    class _Rec:
        """#1202be requires the line at WARNING, not debug — a probe that fails every run
        must leave a trace. So the message assertions watch `warning`."""

        def debug(self, *a, **k):
            pass

        def warning(self, fmt, *a, **k):
            try:
                msgs.append(str(fmt) % a)
            except Exception:
                msgs.append(str(fmt))

    d = tmp_path / "test_user_reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.2.0.json").write_text("[1, 2, 3]", encoding="utf-8")
    o = types.SimpleNamespace(output_dir=pathlib.Path(tmp_path), _logger=_Rec())
    assert ORCH.Orchestrator._final_report_has_evidence_1203jk(o, "1.2.0") is True
    assert not any("could not read" in m for m in msgs), (
        "a report that READ fine was reported as unreadable: %s" % msgs)


def test_a_truly_unreadable_report_does_say_so(tmp_path):
    """The other side of the same distinction — the message must still fire when the read
    really did fail, or the guard above would have silenced a real diagnosis."""
    msgs = []

    class _Rec:
        """#1202be requires the line at WARNING, not debug — a probe that fails every run
        must leave a trace. So the message assertions watch `warning`."""

        def debug(self, *a, **k):
            pass

        def warning(self, fmt, *a, **k):
            try:
                msgs.append(str(fmt) % a)
            except Exception:
                msgs.append(str(fmt))

    d = tmp_path / "test_user_reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.2.0.json").write_text("{not json at all", encoding="utf-8")
    o = types.SimpleNamespace(output_dir=pathlib.Path(tmp_path), _logger=_Rec())
    assert ORCH.Orchestrator._final_report_has_evidence_1203jk(o, "1.2.0") is True
    assert any("could not read" in m for m in msgs), msgs


_CORPUS = pathlib.Path(_AGENT).parent / "generated"


@pytest.mark.skipif(not _CORPUS.exists(), reason="no generated/ corpus in this checkout")
def test_it_agrees_with_the_real_corpus():
    """★ THE SHAPES, NOT A FIXTURE. Every persisted report is classified, and the two the
    corpus already holds with no evidence at all must come out False while everything that
    measured something comes out True. A predicate over a file shape is exactly the kind
    that can match nothing real (#1203d6)."""
    import re
    import tempfile
    seen = {True: 0, False: 0}
    noev = []
    for p in sorted(_CORPUS.glob("*/test_user_reports/*.json")):
        if not re.match(r"^\d+\.\d+\.\d+$", p.stem):
            continue
        try:
            rep = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rep.get("ui_flows"), dict):
            continue
        with tempfile.TemporaryDirectory() as td:
            got = _ask(pathlib.Path(td), rep, version=p.stem)
        seen[got] += 1
        if got is False:
            noev.append("%s/%s" % (p.parent.parent.name, p.name))
    assert seen[True] > 50, seen
    # #1203mk: this was `len(noev) == 2`, naming the two July reports by run. The 2026-10-15
    # corpus prune (229 -> 103 run dirs, to free the disk for r189) removed `run73`, so an
    # exact count asserted the SIZE OF THE CORPUS rather than the property under test, and
    # went red on a deletion that changed nothing about the predicate.
    #
    # What must stay true is the direction that can catch a regression: every report the
    # predicate calls no-evidence is one of the two known ones, and at least one of them is
    # still on disk so the claim is not vacuous. A NEW no-evidence report -- the thing a
    # regression would produce -- still fails here, which the old form also caught; a
    # deleted old one no longer does, which it should never have caught.
    assert noev, "no no-evidence report left on disk -- this half of the test proved nothing"
    assert all("gmrun4" in n or "run73" in n for n in noev), (
        "a report outside the two known July no-evidence ones reads as no-evidence", noev)


# --- #1203na: evidence requires a verdict the ladder actually derived ------------------------
#
# #1203n9 made an ABORTED validation keep the counts its earlier steps had already collected,
# which is right for the delivery line and wrong for this predicate: it reads `api_steps > 0`
# as "already walked, do not overwrite". MEASURED on the 6 ERROR reports in r189/r190/r191,
# with #1203n9's key present: r190's three (7, 7 and 9 steps) flip from "walk it" to "do not",
# which is the outage #1203ja exists to prevent. Across all 129 version reports the fix
# changes 0 of today's decisions, because 0 of them carry `api_steps > 0` without a derived
# verdict -- so the guard is exactly as wide as the evidence (#647).

_DERIVED = ("PASS", "ISSUES", "PARTIAL", "NOT_WALKED")


def test_an_errored_report_that_walked_steps_is_still_walked_again(tmp_path):
    """r190's shape: the journey had done 7 steps when an unrelated ImportError aborted the
    run, so the counts are real and the verdict never happened."""
    assert _ask(tmp_path, {
        "summary": {"verdict": "ERROR", "error": "ImportError: x", "api_steps": 7,
                    "api_passed": 5},
        "api": {"steps": [{"ok": True}] * 7}}) is False


def test_the_verdict_gate_comes_before_the_ui_evidence_test(tmp_path):
    """An abort carries no verdict however much it collected first."""
    assert _ask(tmp_path, {
        "summary": {"verdict": "ERROR", "error": "ImportError: x", "api_steps": 7},
        "ui_flows": _UI_RAN}) is False


def test_env_unavailable_is_not_evidence_either(tmp_path):
    assert _ask(tmp_path, {
        "summary": {"verdict": "ENV_UNAVAILABLE", "error": "backend not reachable",
                    "api_steps": 3}}) is False


@pytest.mark.parametrize("verdict", _DERIVED)
def test_every_derived_verdict_still_counts_as_evidence(tmp_path, verdict):
    assert _ask(tmp_path, {"summary": {"verdict": verdict, "api_steps": 4}}) is True


def test_not_walked_with_ui_evidence_is_still_evidence(tmp_path):
    """The case the whitelist must not break: the ladder DID judge, it judged the journey
    empty, and the UI walk collected flows anyway."""
    assert _ask(tmp_path, {"summary": {"verdict": "NOT_WALKED", "api_steps": 0},
                           "ui_flows": _UI_RAN}) is True


def test_a_report_with_no_verdict_at_all_is_walked(tmp_path):
    """0 of the 129 corpus reports are this shape, so this pins intent rather than a
    population: a report that never says what it concluded has not been judged."""
    assert _ask(tmp_path, {"summary": {"api_steps": 9}, "ui_flows": _UI_RAN}) is False


def test_the_verdict_set_has_one_owner_1203na():
    """#1032: the predicate must not re-list the ladder's verdicts."""
    from multi_agent.runtime.test_user_validation import DERIVED_VERDICTS_1203NA
    assert tuple(DERIVED_VERDICTS_1203NA) == _DERIVED
    import ast
    import inspect
    src = inspect.getsource(ORCH.Orchestrator._final_report_has_evidence_1203jk)
    tree = ast.parse(src.lstrip())
    names = [getattr(c.comparators[0], "id", None) for c in ast.walk(tree)
             if isinstance(c, ast.Compare) and c.comparators
             and isinstance(c.ops[0], ast.NotIn)]
    assert "DERIVED_VERDICTS_1203NA" in names, names


# ★ NULL MUTATION, recorded rather than chased (#1203jr). Dropping the `.upper()` from the
# verdict comparison comes back MISSED, and no test is added for it: every verdict the ladder
# writes is an uppercase literal (`verdict = "ISSUES"` and its three siblings), all 129 corpus
# reports agree, so no real input distinguishes the two versions. Both directions also fail
# safe -- an unrecognised verdict means "walk it", which is the direction #1203ja wants. The
# `str()` is what actually matters there, and `test_a_report_with_no_verdict_at_all_is_walked`
# pins it.
