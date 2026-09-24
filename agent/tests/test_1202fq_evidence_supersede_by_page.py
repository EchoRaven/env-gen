"""#1202fq -- #757 must supersede by the PAGE, not by the record's spelling.

#757 exists to stop `validation_ui_evidence_failed` being a latch: "a failure that a later
pass has answered does not [block]". It keys that by the record NAME, which only works
when both records spell the flow the same way -- and a verifier re-walking a page names
the record after the route it browsed.

tiktok-r96: `/live` was re-walked and PASSED as `ui_flow:live_page`, while
`ui_flow:live_discover` (the page registered on /live) still held a 28-hour-old failure
from before two resumes. Two keys, both kept, the stale one still counted as the newest
word on its flow. Every one of the 8 records then blocking delivery was 28h+ old while
every fresh walk had passed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _ui_evidence_breadth_739, _page_by_route_1202fq)

ROUTES = {"/live": "live_discover", "/explore": "explore_grid"}


def _rec(flow, status, at, url=None):
    meta = {"check": "ui_flow", "flow": flow}
    if url:
        meta["url"] = url
    return {"name": f"validation:ui_flow:{flow}", "status": status,
            "metadata": meta, "recorded_at": at}


def test_fresh_pass_retires_the_stale_failure_for_the_same_page():
    recs = [_rec("live_discover", "failure", 1000.0),
            _rec("live_page", "success", 9000.0, "http://localhost:8081/live")]
    b = _ui_evidence_breadth_739(recs, page_by_route=ROUTES)
    assert b["failed_records"] == 0, (
        f"a re-walk that passed did not retire the stale failure: {b['pages_failed']}")


def test_without_the_map_the_old_behaviour_is_exact():
    recs = [_rec("live_discover", "failure", 1000.0),
            _rec("live_page", "success", 9000.0, "http://localhost:8081/live")]
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 1


def test_a_newer_failure_still_blocks():
    """The gate must keep its teeth in the other direction."""
    recs = [_rec("live_discover", "success", 1000.0),
            _rec("live_page", "failure", 9000.0, "http://localhost:8081/live")]
    b = _ui_evidence_breadth_739(recs, page_by_route=ROUTES)
    assert b["failed_records"] == 1, "a newer failing walk was swallowed"


def test_an_older_pass_does_not_retire_a_newer_failure():
    recs = [_rec("live_discover", "failure", 9000.0),
            _rec("live_page", "success", 1000.0, "http://localhost:8081/live")]
    b = _ui_evidence_breadth_739(recs, page_by_route=ROUTES)
    assert b["failed_records"] == 1, "latest-wins was inverted"


def test_flows_with_no_fresh_walk_are_untouched():
    """The fix must be narrow: it retires the page that was actually re-walked, and
    nothing else. On r96 it moved exactly one of eight."""
    recs = [_rec("live_discover", "failure", 1000.0),
            _rec("profile_own", "failure", 1000.0),
            _rec("settings_more_menu", "failure", 1000.0),
            _rec("live_page", "success", 9000.0, "http://localhost:8081/live")]
    b = _ui_evidence_breadth_739(recs, page_by_route=ROUTES)
    assert sorted(set(b["pages_failed"])) == ["profile_own", "settings_more_menu"], (
        f"blanket-cleared instead of retiring one page: {b['pages_failed']}")


def test_unmapped_route_keeps_its_own_key():
    recs = [_rec("live_discover", "failure", 1000.0),
            _rec("mystery", "success", 9000.0, "http://localhost:8081/nowhere")]
    b = _ui_evidence_breadth_739(recs, page_by_route=ROUTES)
    assert b["failed_records"] == 1


def test_resolver_shares_flow_coverage_implementation():
    """One map, one implementation -- this batch's recurring defect was two consumers of
    one evidence store each implementing half the rules."""
    import inspect
    src = inspect.getsource(_page_by_route_1202fq)
    assert "_page_name_by_route_1202fo" in src, "a second route map was written"


def test_resolver_degrades_to_empty_not_to_an_exception():
    class _Boom:
        registryhub = None

        def __getattr__(self, n):
            raise RuntimeError("hub down")

    assert _page_by_route_1202fq(_Boom()) == {}
