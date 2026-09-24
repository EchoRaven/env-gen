"""#1202fo -- a ui_flow record is attributed to the page registered on the URL it
validated, so re-validation reaches the key the delivery gate counts.

tiktok-r96: the verifier walked http://localhost:8081/live six minutes before the run
ended and it PASSED, but recorded `validation:ui_flow:live_page`. The page registered
for /live is `live_discover`, still holding a 27-hour-old failure from before two
resumes. The fresh evidence landed on a key nothing reads, so the flow stayed uncleared
however many walks ran -- r96 ran three. #237's suffix aliasing cannot bridge
`live_page` -> `live_discover`: they share no stem, only the route.

The point is NOT that flows start passing. On r96's real ledger the fix moves exactly two
flows, one in each direction -- `live_discover` missing->passed, and `login_modal`
passed->missing because the newest evidence about /login is a failure and its green was 27
hours stale. Both tests below pin that symmetry.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime import flow_coverage as FC  # noqa: E402

PAGES = {
    "live_discover": {"name": "live_discover", "route": "/live"},
    "explore_grid": {"name": "explore_grid", "route": "/explore"},
    "login_modal": {"name": "login_modal", "route": "/login"},
}


class _Reg:
    def __init__(self, pages=None):
        self._p = PAGES if pages is None else pages

    def list_ui_pages(self):
        return self._p


class _Hubs:
    def __init__(self, records, pages=None):
        self._r = records
        self.registryhub = _Reg(pages)

    def get_validation_results(self, limit=1000):
        return self._r


def _rec(flow, status, at, url=None):
    meta = {"check": "ui_flow", "flow": flow}
    if url:
        meta["url"] = url
    return {"name": f"validation:ui_flow:{flow}", "status": status,
            "metadata": meta, "recorded_at": at}


def test_fresh_walk_reaches_the_registered_page(): 
    """r96's exact shape: an old failure under the registered name, a fresh pass under
    a name the walker invented from the route."""
    hubs = _Hubs([_rec("live_discover", "failed", 1000.0),
                  _rec("live_page", "passed", 9000.0,
                       "http://localhost:8081/live")])
    idx = FC._index_ui_flow_records(hubs)
    assert idx.get("live_discover") == "passed", (
        f"fresh evidence for /live never reached live_discover: {idx}")


def test_newer_failure_supersedes_a_stale_pass_through_the_alias():
    """The fix must work in the unhelpful direction too -- otherwise it is just a way
    of making the gate green."""
    hubs = _Hubs([_rec("login_modal", "passed", 1000.0),
                  _rec("login_page", "failed", 9000.0,
                       "http://localhost:8081/login")])
    idx = FC._index_ui_flow_records(hubs)
    assert idx.get("login_modal") == "failed", (
        f"a stale pass survived newer failing evidence for the same route: {idx}")


def test_older_alias_does_not_override_a_newer_direct_record():
    hubs = _Hubs([_rec("live_discover", "failed", 9000.0),
                  _rec("live_page", "passed", 1000.0,
                       "http://localhost:8081/live")])
    idx = FC._index_ui_flow_records(hubs)
    assert idx.get("live_discover") == "failed", "latest-wins was not preserved"


def test_record_keeps_its_own_key_as_well():
    hubs = _Hubs([_rec("live_page", "passed", 9000.0,
                       "http://localhost:8081/live")])
    idx = FC._index_ui_flow_records(hubs)
    assert idx.get("live_page") == "passed"
    assert idx.get("live_discover") == "passed"


def test_unknown_route_is_left_alone():
    hubs = _Hubs([_rec("some_flow", "failed", 9000.0,
                       "http://localhost:8081/nowhere")])
    idx = FC._index_ui_flow_records(hubs)
    assert set(idx) == {"some_flow"}, f"invented an attribution: {idx}"


def test_two_pages_on_one_route_are_never_guessed():
    pages = {"a": {"name": "a", "route": "/live"}, "b": {"name": "b", "route": "/live"}}
    hubs = _Hubs([_rec("live_page", "passed", 9000.0,
                       "http://localhost:8081/live")], pages=pages)
    idx = FC._index_ui_flow_records(hubs)
    assert set(idx) == {"live_page"}, f"guessed between ambiguous pages: {idx}"


def test_records_without_a_url_behave_exactly_as_before():
    hubs = _Hubs([_rec("live_discover", "failed", 1000.0),
                  _rec("live_page", "passed", 9000.0)])
    idx = FC._index_ui_flow_records(hubs)
    assert idx.get("live_discover") == "failed"


def test_route_parsing():
    f = FC._route_of_url_1202fo
    assert f("http://localhost:8081/live") == "/live"
    assert f("http://h/live/?a=1#x") == "/live"
    assert f("/explore") == "/explore"
    assert f("http://localhost:8081") == "/"
    assert f("") == ""
    assert f("mailto:x@y") == ""


def test_registry_hiccup_is_not_fatal():
    class _Bad:
        def list_ui_pages(self):
            raise RuntimeError("hub down")

    hubs = _Hubs([_rec("live_page", "passed", 9000.0, "http://h/live")])
    hubs.registryhub = _Bad()
    assert FC._index_ui_flow_records(hubs).get("live_page") == "passed"
