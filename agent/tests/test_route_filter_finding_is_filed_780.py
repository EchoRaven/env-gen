r"""#780: the framework computed the fix and wrote it to a log nobody reads.

r151 printed both halves, once, in a 116-minute run:

    #615 6 routes render identical content: /browse, /browse/languages, /games, /movies,
         /new, /shows — all fetch only /api/titles
    #615 the shared endpoint(s) already accept filters the contract declares: /api/titles takes
         genre, kind, language — a route-derived filter is available, the pages just do not
         pass one.

136 tasks existed in that run. **None of them was this.** The route list, the endpoint and the
exact parameter names were all computed and then discarded into a log line.

This is #748/#740/#769/#770's family with the stakes raised: those discarded a CAUSE, this
discards a FIX.

**Gated on the filters existing, deliberately.** Without them the finding is "these pages look
alike", and #615's own comment refuses to act on that — *"at 32/45 it would wedge nearly every
run"*. With them it is a one-line change per page, and naming the parameter is what turns an
observation into a task.

It also closes the loop on the row-title duplication the judge reports in 39% of runs: different
rows, one repeated heading, because a page that passes no filter has no grouping to name them
from. That is item 54's question — the oldest open thread in the document — reaching the lane in
an actionable form for the first time.
"""
import inspect
import tempfile
import types
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa1203pg


@pytest.fixture(autouse=True)
def _reset():
    for _m in list(__import__("sys").modules.values()):
        r = getattr(_m, "reset_said_700", None)
        if callable(r) and getattr(_m, "__name__", "").endswith("deliverability"):
            r()
    yield


def _src() -> str:
    return inspect.getsource(dl)


# --- it files, and only when there is a fix to file ------------------------------------------------

def test_a_task_is_created():
    s = _src()
    assert "workhub.create_task(" in s
    assert "Pass a route-derived filter on:" in s


def test_it_only_files_when_the_filters_are_declared():
    """Without them #615 is an observation its own comment refuses to act on."""
    s = _src()
    i = s.index("_f708 = _filters_708b")
    j = s.index("#780: FILE IT")
    k = s.index("workhub.create_task(")
    assert i < j < k, "the create_task must sit inside the `if _f708:` branch"


def test_the_description_names_the_parameters():
    """A task that says 'these look alike' is the version #615 already rejected."""
    s = _src()
    assert "The contract already declares the filters:" in s
    assert "accepts" in s


def test_it_names_the_routes():
    s = _src()
    assert "_routes780" in s and "render IDENTICAL" in s


def test_it_tells_the_lane_what_to_do():
    s = _src()
    assert "give each page the parameter its own route implies" in s
    assert "label its rows from that grouping" in s


def test_it_is_assigned_to_the_lane_that_can_fix_it():
    s = _src()
    i = s.index("workhub.create_task(")
    blk = s[i:s.index("except Exception as _t780", i)]
    assert 'assignee="frontend"' in blk


# --- it cannot spam, and it cannot break the gate ----------------------------------------------------

def test_it_is_behind_760s_dedupe():
    """One task per distinct group per process; #672's twin-check covers repeats across runs."""
    s = _src()
    assert s.index("_SAID_700.add(_key760)") < s.index("workhub.create_task(")


def test_a_failure_to_file_is_announced():
    """#769's rule applied to my own code: an except that neither raises nor logs is a decision
    to never find out — and here the failure mode is silently reverting to log-only."""
    s = _src()
    assert "#780 could not file the route-filter task" in s
    assert "log-only again, which is the defect #780 exists to fix" in s


def test_it_never_raises():
    # Anchored on a unique substring of the NEXT statement, not a hand-typed literal with
    # guessed indentation — my first version invented the whitespace and failed on it.
    s = _src()
    i = s.index("#780: FILE IT")
    blk = s[i:s.index('"#615 %d routes render identical content', i)]
    assert "except Exception as _t780" in blk
    # STATEMENT level, not substring: the comment above says "with the stakes raised", and a
    # bare `"raise" not in blk` matches that. Same trap as #706's, and the third over-loose
    # substring of this session after #765 and #774.
    stmts = [l.strip() for l in blk.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l == "raise" or l.startswith("raise ")]


# --- provenance ---------------------------------------------------------------------------------------

def test_the_r151_evidence_is_recorded():
    s = " ".join(_src().replace("#", " ").split())
    assert "136 tasks existed; none was this" in s
    assert "116-minute run" in s


def test_it_names_the_family_and_the_escalation():
    s = " ".join(_src().replace("#", " ").split())
    assert "those discarded a CAUSE, and this discards a FIX" in s


def test_the_gating_choice_is_justified():
    s = " ".join(_src().replace("#", " ").split())
    assert "at 32/45 it would wedge nearly every run" in s


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the task is really filed, and it names the routes ---------------------------------
#
# Every assertion above reads the SOURCE, and both mutations went through:
#
#   * `None and workhub.create_task(...)` -- the substring `workhub.create_task(` is still
#     there, which is all `test_a_task_is_created` checks, while nothing is filed and the fix
#     goes back to the log nobody reads. That is the state #780 exists to end: r151 printed both
#     halves once in a 116-minute run and filed nothing.
#   * `_routes780 = ""` -- the task IS filed, naming no routes at all, so the lane cannot tell
#     which pages are affected.
#
# A first version of the first mutation expressed "never files" as a `raise` and was CAUGHT --
# by this file's own statement-level anti-raise assertion, which says nothing about whether the
# filing is driven. A mutation that is caught for the wrong reason is worse than one that is
# missed, because it reads as coverage.
#
# `duplicate_route_content_groups` is a module-level function, so the group can be injected and
# the property under test is just the filing.

_GROUP_1203PG = {"routes": ["/browse", "/movies"], "endpoints": ["/api/titles"]}


def _filed(monkeypatch, group=None, endpoints=None):
    """Run the reporter over one duplicate-content group; return the tasks it filed."""
    created = []
    d = Path(tempfile.mkdtemp())
    (d / "frontend" / "src").mkdir(parents=True)
    eps = endpoints if endpoints is not None else {
        "e1": {"path": "/api/titles",
               "schema": {"request": {"genre": "str?", "kind": "str?", "limit": "int?"}}}}
    pages = {"p1": {"route": "/browse", "apis_used": ["/api/titles"]},
             "p2": {"route": "/movies", "apis_used": ["/api/titles"]}}
    # `get_ui_pages` is read off the WORKHUB here, not the registryhub. The first fixture put it
    # on the registryhub and filed nothing -- diagnosed in one read because #1067 announces the
    # skip with the AttributeError in it, which is the whole point of that ticket.
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(
            list_tasks=lambda: [],
            get_ui_pages=lambda: pages,
            create_task=lambda **kw: (created.append(kw), {"id": "t1"})[1]),
        registryhub=types.SimpleNamespace(
            get_endpoints=lambda: eps,
            get_ui_pages=lambda: pages))
    # the reporter imports it INSIDE the function (`from .frontend_audit import ...`), so the
    # patch has to land on the defining module, not on `deliverability`.
    monkeypatch.setattr(
        fa1203pg, "duplicate_route_content_groups",
        lambda *a, **k: [group if group is not None else dict(_GROUP_1203PG)])
    dl._ui_page_wiring_blockers(hub, d)
    return created


def test_the_fixture_actually_reaches_the_filing(monkeypatch):
    """Non-vacuity, pinned: without this the assertions below would pass on an empty list."""
    created = _filed(monkeypatch)
    assert len(created) == 1, "the fixture never reached create_task -- fix the fixture"


def test_the_task_names_the_routes(monkeypatch):
    task = _filed(monkeypatch)[0]
    assert "/browse" in task["title"] and "/movies" in task["title"], task["title"]
    assert "/browse" in task["description"] and "/movies" in task["description"]


def test_the_task_names_the_filters_the_contract_declares(monkeypatch):
    task = _filed(monkeypatch)[0]
    assert "genre" in task["description"] and "kind" in task["description"]
    assert "/api/titles" in task["description"]


def test_pagination_parameters_are_not_offered_as_a_filter(monkeypatch):
    """`limit` is in the fixture and must not be proposed: paging every page the same way does
    not make two routes render different content."""
    task = _filed(monkeypatch)[0]
    assert "limit" not in task["description"], task["description"]


def test_it_goes_to_the_lane_that_can_fix_it(monkeypatch):
    task = _filed(monkeypatch)[0]
    assert task.get("assignee") == "frontend", task.get("assignee")


def test_nothing_is_filed_when_the_contract_declares_no_filters(monkeypatch):
    """The other side of #708b: with no optional parameter there is no fix to propose, and
    filing one would be a task the lane cannot act on."""
    created = _filed(monkeypatch, endpoints={
        "e1": {"path": "/api/titles", "schema": {"request": {"id": "int"}}}})
    assert created == [], created
