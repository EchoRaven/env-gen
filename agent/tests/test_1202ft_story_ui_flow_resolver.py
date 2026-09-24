"""#1202ft -- story_hub's ui_flow resolver said nothing at all, and lacked every rule its
two sibling readers carry.

Found by SWEEPING for the pattern this batch kept hitting (#1202fn/#1202fp/#1202fq/#1202fs:
one store, several readers, each implementing a different subset of the rules) rather than
by waiting to hit it again in a run.

Measured on tiktok-r96's ledger before the fix: 23 ui_flow records, 17 passed and 6 failed,
and EVERY flow resolved to "evidence_pending" -- including a flow that was never recorded.
A flow with 17 passing records was indistinguishable from one nobody ever ran.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.story_hub import _resolve_ui_flow  # noqa: E402

BUILD, OLD, NEW = 5000.0, 1000.0, 9000.0
PAGES = {"live": {"name": "live_discover", "route": "/live"}}


def _rec(flow, status, at, url=None):
    meta = {"check": "ui_flow", "flow": flow}
    if url:
        meta["url"] = url
    return {"name": f"validation:ui_flow:{flow}", "status": status,
            "metadata": meta, "recorded_at": at}


def _smoke(at):
    return {"name": "validation:api_smoke", "status": "passed",
            "metadata": {"check": "api_smoke"}, "recorded_at": at}


class _Reg:
    def __init__(self, recs, pages=None):
        self._r = recs
        outer = self

        class _RH:
            def list_ui_pages(self_inner):
                return pages if pages is not None else {}
        self.registryhub = _RH()

    def get_validation_results(self, limit=500):
        return self._r


def test_a_passing_record_resolves_to_pass():
    """The defect in one line: the record's status is 'passed', never 'pass'."""
    assert _resolve_ui_flow(_Reg([_rec("explore_grid", "passed", NEW)]),
                            "ui_flow:explore_grid") == "pass"


def test_the_raw_store_spelling_also_resolves():
    """#752 counted three spellings in the store: success 1198 / passed 310 / failure 252."""
    assert _resolve_ui_flow(_Reg([_rec("explore_grid", "success", NEW)]),
                            "ui_flow:explore_grid") == "pass"
    assert _resolve_ui_flow(_Reg([_rec("explore_grid", "failure", NEW)]),
                            "ui_flow:explore_grid") == "fail"


def test_a_flow_with_no_record_is_still_pending():
    """The resolver must keep the ability to say 'no evidence' -- that is the state it
    used to report for everything."""
    assert _resolve_ui_flow(_Reg([_rec("other", "passed", NEW)]),
                            "ui_flow:absent") == "evidence_pending"


def test_another_flows_record_does_not_answer_for_this_one():
    """The predicate was `check == 'ui_flow' OR ...`, true for every ui_flow row, so the
    first row would have answered for every flow."""
    recs = [_rec("some_other_flow", "failed", NEW), _rec("mine", "passed", NEW)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "pass"


def test_latest_record_wins():
    """The store is a HISTORY -- #357 and #757 both take the newest; this took the first."""
    recs = [_rec("mine", "failed", OLD), _rec("mine", "passed", NEW)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "pass"
    recs = [_rec("mine", "passed", OLD), _rec("mine", "failed", NEW)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "fail"


def test_a_rewalk_under_the_routes_own_name_is_attributed(): 
    """#1202fo: `/live` re-walked and passing as `live_page` is evidence about the page
    registered on /live."""
    recs = [_rec("live_discover", "failed", OLD),
            _rec("live_page", "passed", NEW, "http://localhost:8081/live")]
    assert _resolve_ui_flow(_Reg(recs, PAGES), "ui_flow:live_discover") == "pass"


def test_a_stale_failure_reads_as_needing_reverification():
    """#401: a failure predating the build's validation is a re-verify, not a verdict."""
    recs = [_rec("mine", "failed", OLD), _smoke(BUILD)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "evidence_pending"


def test_a_stale_pass_is_never_aged_out():
    recs = [_rec("mine", "passed", OLD), _smoke(BUILD)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "pass"


def test_a_current_failure_still_fails():
    recs = [_rec("mine", "failed", NEW), _smoke(BUILD)]
    assert _resolve_ui_flow(_Reg(recs), "ui_flow:mine") == "fail"


def test_registry_hiccup_does_not_raise():
    class _Bad(_Reg):
        def __init__(self):
            super().__init__([_rec("mine", "passed", NEW)])
            self.registryhub = None
    assert _resolve_ui_flow(_Bad(), "ui_flow:mine") == "pass"
