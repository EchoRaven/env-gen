r"""#1203jm: eight new checks that could have been uniformly silent, and nobody would know.

`scripts/verify_shipped_fixes.py` turns the 2026-10-14 batch's predictions into a command,
and every one of its new checks is gated on `_has_1014_1203ja` so a pre-fix run answers NOT
MEASURED instead of confirming on an artifact it happens to share. `--self-test` proves
that half: 25 checks, none confirms on r140.

★ IT PROVES ONLY THAT HALF. A bug in the gate — a typo in the marker field, a glob that
matches nothing — makes every check answer NOT MEASURED on EVERY run, forever, and the
self-test would still pass because NOT MEASURED is what it wants there. That is this
script's own doctrine turned on itself: "a check that cannot distinguish 'looked and found
nothing' from 'never looked' reports a silence as a pass."

So these build a run directory with the POST-fix shape and require each check to reach a
verdict. Both directions: the shape the fix predicts must CONFIRM, and the shape it forbids
must FALSIFY.
"""
import importlib.util
import json
import os
import pathlib

import pytest

_AGENT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOL = _AGENT.parent / "scripts" / "verify_shipped_fixes.py"


@pytest.fixture(scope="module")
def vsf():
    assert _TOOL.exists(), "scripts/verify_shipped_fixes.py is gone"
    spec = importlib.util.spec_from_file_location("_vsf_1203jm", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, *, reports, releases=("1.0.0", "1.1.0"), gate=None, holds=(),
         terminal=None, checks=None):
    """A run directory with the 2026-10-14 shape. `reports` maps version -> summary/ui."""
    r = tmp_path / "run"
    (r / "test_user_reports").mkdir(parents=True, exist_ok=True)
    (r / "shared" / "hubs").mkdir(parents=True, exist_ok=True)
    (r / "logs").mkdir(parents=True, exist_ok=True)
    for v, rep in reports.items():
        (r / "test_user_reports" / ("%s.json" % v)).write_text(
            json.dumps(rep), encoding="utf-8")
    (r / "shared" / "hubs" / "codehub_releases.json").write_text(
        json.dumps({v: {"tag": v} for v in releases} | {"_meta": {}}), encoding="utf-8")
    if checks is not None:
        (r / "shared" / "hubs" / "codehub_checks.json").write_text(
            json.dumps(checks), encoding="utf-8")
    if gate is not None:
        (r / "logs" / "delivery_gate.jsonl").write_text(
            json.dumps(gate) + "\n", encoding="utf-8")
    if holds:
        (r / "logs" / "delivery_hold.jsonl").write_text(
            "\n".join(json.dumps(h) for h in holds) + "\n", encoding="utf-8")
    if terminal is not None:
        (r / "run_budget.json").write_text(
            json.dumps({"usage": {"terminal_reason": terminal}}), encoding="utf-8")
    return r


def _ok(v, ui_ran=True, steps=1, verdict="PASS"):
    """A report in the post-fix shape. The marker field is what the gate looks for."""
    return {"version": v,
            "summary": {"api_steps": steps, "verdict": verdict,
                        "ui_walk_ran_1203je": ui_ran},
            "ui_flows": {"ran": ui_ran,
                         "flows": ([{"flow": "signup", "ok": True}] if ui_ran else [])}}


def test_the_gate_recognises_the_post_fix_shape(vsf, tmp_path):
    """★ THE TICKET. If this is red, every check below is permanently NOT MEASURED and the
    command answers nothing on every run."""
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")})
    assert vsf._has_1014_1203ja(r) is True
    # ...and does NOT recognise the pre-fix shape, or the self-test's guarantee is empty
    pre = _run(tmp_path / "pre", reports={"1.0.0": {"summary": {"api_steps": 1,
                                                               "verdict": "PASS"}}})
    assert vsf._has_1014_1203ja(pre) is False


def test_1203ja_confirms_when_the_final_tag_was_walked(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0"), "1.1.0": _ok("1.1.0")})
    assert vsf.check_1203ja(r) == vsf.CONFIRMED


def test_1203ja_falsifies_when_the_final_tag_was_not(vsf, tmp_path):
    """The defect itself: releases up to 1.1.0, a report only for 1.0.0."""
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")})
    assert vsf.check_1203ja(r) == vsf.FALSIFIED


def test_1203jc_falsifies_a_pass_with_nothing_walked(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0", steps=0, ui_ran=False)})
    assert vsf.check_1203jc(r) == vsf.FALSIFIED


def test_1203jc_confirms_when_the_verdict_is_not_walked(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0", steps=0, ui_ran=False,
                                             verdict="NOT_WALKED")})
    assert vsf.check_1203jc(r) == vsf.CONFIRMED


def test_1203je_falsifies_a_surviving_connection_refused(vsf, tmp_path):
    rep = _ok("1.0.0")
    rep["ui_flows"]["flows"] = [{"flow": "login", "ok": False,
                                 "note": "Error: Page.goto: net::ERR_CONNECTION_REFUSED"}]
    r = _run(tmp_path, reports={"1.0.0": rep})
    assert vsf.check_1203je(r) == vsf.FALSIFIED


def test_1203je_confirms_a_readiness_skip(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0", ui_ran=False, verdict="NOT_WALKED")})
    assert vsf.check_1203je(r) == vsf.CONFIRMED


def test_1203jd_reports_a_hold_without_scoring_it(vsf, tmp_path):
    """A hold is the guard working; whether the tree was really broken is a judgement, so
    it must be surfaced as NOT MEASURED rather than scored either way."""
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             holds=[{"hold": "fresh_smoke_final_1203jd", "detail": "2 failing check(s)"}])
    assert vsf.check_1203jd(r) == vsf.UNMEASURED
    r2 = _run(tmp_path / "quiet", reports={"1.0.0": _ok("1.0.0")})
    assert vsf.check_1203jd(r2) == vsf.CONFIRMED


def test_1203jg_falsifies_a_blocker_with_no_prose(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             gate={"failed_checks": ["validation_ui_evidence_failed"], "blocker_prose": {}})
    assert vsf.check_1203jg(r) == vsf.FALSIFIED


def test_1203jg_confirms_prose_with_a_reason(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             gate={"failed_checks": ["validation_ui_evidence_failed"],
                   "blocker_prose": {"validation_ui_evidence_failed":
                                     ["2 failed UI record(s); login_page: /api/auth/me 401"]}})
    assert vsf.check_1203jg(r) == vsf.CONFIRMED


def test_1203jg_flags_prose_that_matched_nothing(vsf, tmp_path):
    """The landed-but-inert case: prose present, every page 'no summary recorded'."""
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             gate={"failed_checks": ["validation_ui_evidence_failed"],
                   "blocker_prose": {"validation_ui_evidence_failed":
                                     ["2 failed UI record(s); login_page: no summary recorded"]}})
    assert vsf.check_1203jg(r) == vsf.UNMEASURED


def test_1203jf_counts_the_anonymous_401_class(vsf, tmp_path):
    checks = {"c1": {"name": "validation:ui_flow:login_page", "status": "failure",
                     "evidence": {"summary": "/api/auth/me returned 401 while logged out"}},
              "c2": {"name": "validation:ui_flow:feed", "status": "failure",
                     "evidence": {"summary": "TypeError .map is not a function"}}}
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")}, checks=checks)
    assert vsf.check_1203jf(r) == vsf.UNMEASURED      # 1 of 2 → not yet zero
    r2 = _run(tmp_path / "clean", reports={"1.0.0": _ok("1.0.0")},
              checks={"c2": checks["c2"]})
    assert vsf.check_1203jf(r2) == vsf.CONFIRMED      # 0 of 1


def test_1203jh_falsifies_a_lost_shipped_clause(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             terminal="no abort and no cap -- the loop exited with the app not delivered. "
                      "last framework-validation failure set: business_chain")
    assert vsf.check_1203jh(r) == vsf.FALSIFIED


def test_1203jh_confirms_the_clause_with_its_tags(vsf, tmp_path):
    r = _run(tmp_path, reports={"1.0.0": _ok("1.0.0")},
             terminal="no abort and no cap -- the loop exited with the app not delivered."
                      " SHIPPED: 1.0.0, 1.1.0 (#1202jg: `status`=delivered means this)."
                      " last framework-validation failure set: business_chain")
    assert vsf.check_1203jh(r) == vsf.CONFIRMED


def test_1203jk_falsifies_a_final_report_that_measured_nothing(vsf, tmp_path):
    r = _run(tmp_path, releases=("1.0.0",),
             reports={"1.0.0": _ok("1.0.0", steps=0, ui_ran=False, verdict="NOT_WALKED")})
    assert vsf.check_1203jk(r) == vsf.FALSIFIED


def test_1203jk_confirms_a_final_report_with_evidence(vsf, tmp_path):
    r = _run(tmp_path, releases=("1.0.0",), reports={"1.0.0": _ok("1.0.0")})
    assert vsf.check_1203jk(r) == vsf.CONFIRMED


def test_every_new_check_is_registered(vsf):
    """A check nobody runs is prose with extra steps."""
    names = {getattr(c, "__name__", "") for c in vsf.CHECKS}
    for t in ("ja", "jc", "je", "jd", "jg", "jf", "jh", "jk"):
        assert "check_1203%s" % t in names, (t, sorted(names))
