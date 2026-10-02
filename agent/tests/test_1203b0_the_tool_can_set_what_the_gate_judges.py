r"""#1203b0: the lane's ui_page tool could not express the three fields the gate judges.

`registryhub_register_ui_page` is the only ui_page registration tool a lane holds during
implementation. Its PARAMETERS exposed `name`, `path`, `status`, `components`,
`reference_image`, `notes` — and NOT `apis_used`, `route` or `component`. The plumbing was
already complete: `WorkHub.update_ui_page` forwards all three to
`RegistryHub.register_ui_page`, which keeps the existing value when it receives None.

WHAT THAT COST, on two consecutive runs:

  r143  aborted with NOTHING DELIVERED at $170.89 / 140 gate records / 0 passes.
        `deliverability_page_apis_understated` failed in 131 of them. The frontend called this
        tool 19 times — always `name=` + `path=` only — so every call was a SILENT NO-OP for
        the one field the gate was blocking on. It got success back, marked the remediation
        task complete, and the gate re-failed. Gate records 52..140 are byte-identical.
  r142  the same cause one step earlier: 32 workhub tasks for that single blocker, and its
        lane filed "P0 platform/registry blocker: EXPOSE MUTATION OR PROJECTION PATH FOR
        ui_page apis_used".

★ THE LANE WAS RIGHT AND I WAS WRONG. I dismissed that task by testing
`RegistryHub.register_ui_page(..., apis_used=[...])` against a copy of r142's hub — the PYTHON
METHOD, which does accept the kwarg. The lane does not call the method; it calls the TOOL. That
is the "I tested the helper, not the caller" error, and this time it cost a wrong conclusion
written into memory and a second aborted run to find.

`route`/`component` are the same gap with a larger footprint: 979 of 2798 corpus ui_page records
(35%, 138 runs) have an empty route, 1038 an empty component, and #905 already measured 644 of
those as REAL pages under src/pages/. The only tool that could set them is
`kickoff_declare_ui_page`, which needs a `meeting_id` and is in NO implementation-phase tool set
(verified on r143: frontend's communicate/edit_code/run_checks/deliver/delegate_team all exclude
it, while frontend called the registry tool 19 times and the list tool 18).
"""
import asyncio
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.hub_tools as HT  # noqa: E402

# The class is `WorkHubUpdatePageTool` — the tool NAME is `registryhub_register_ui_page`, which
# is not the class name. Guessing the class cost one red run; resolve it by NAME instead so a
# rename cannot silently turn these tests into AttributeErrors that look like the fix failing.
_TOOL = next(o for o in vars(HT).values()
             if getattr(o, "NAME", "") == "registryhub_register_ui_page")


def _tool():
    """The tool with a workhub stand-in that records what reaches `update_ui_page`."""
    seen = {}

    class _WH:
        def update_ui_page(self, name, data, agent=""):
            seen["name"] = name
            seen["data"] = dict(data)
            seen["agent"] = agent
            return {"id": name, "name": name, **{k: v for k, v in data.items()}}

    t = _TOOL.__new__(_TOOL)
    t._hubs = types.SimpleNamespace(workhub=_WH())
    t._agent_id = "frontend"
    return t, seen


def _run(t, **kw):
    res = asyncio.run(t._run(**kw))
    return res.data if hasattr(res, "data") else res


def test_the_schema_exposes_the_three_fields_the_gate_judges():
    """★ The defect, stated as the schema: a lane can only pass what the schema names."""
    props = _TOOL.PARAMETERS["properties"]
    for field in ("apis_used", "route", "component"):
        assert field in props, "%s is still not expressible: %s" % (field, sorted(props))


def test_apis_used_reaches_the_registry():
    t, seen = _tool()
    _run(t, name="signup", apis_used=["POST /auth/register"])
    assert seen["data"].get("apis_used") == ["POST /auth/register"], seen["data"]


def test_route_and_component_reach_the_registry():
    """35% of corpus ui_page records have an empty route; this is why."""
    t, seen = _tool()
    _run(t, name="feed", route="/feed", component="ForYouFeedPage")
    assert seen["data"].get("route") == "/feed", seen["data"]
    assert seen["data"].get("component") == "ForYouFeedPage", seen["data"]


def test_an_empty_list_is_forwarded_not_dropped():
    """★ `apis_used=[]` must be distinguishable from "not passed": a page that genuinely calls
    nothing has to be able to SAY so, and `if apis_used:` would have silently dropped it."""
    t, seen = _tool()
    _run(t, name="static_page", apis_used=[])
    assert "apis_used" in seen["data"], seen["data"]
    assert seen["data"]["apis_used"] == []


def test_omitting_apis_used_still_preserves_and_says_so():
    """★ The silent no-op that cost r143 the run. Omitting the field keeps the old list — which
    is the right behaviour — but the caller must be TOLD, or it reads the success as a fix."""
    t, seen = _tool()

    class _WHKept:
        def update_ui_page(self, name, data, agent=""):
            return {"id": name, "apis_used": ["POST /auth/signup"], **data}

    t._hubs = types.SimpleNamespace(workhub=_WHKept())
    out = _run(t, name="signup", path="app/frontend/src/pages/SignupPage.jsx")
    assert "apis_used" not in seen.get("data", {}), "it must not invent a list"
    note = str(out.get("_apis_used_unchanged_1203b0") or "")
    assert note, "the no-op is still silent: %s" % sorted(out)
    assert "POST /auth/signup" in note, note
    assert "changed nothing" in note, note


def test_a_call_that_sets_apis_used_carries_no_such_note():
    """The note belongs to the no-op path only."""
    t, _ = _tool()
    out = _run(t, name="signup", apis_used=["POST /auth/register"])
    assert "_apis_used_unchanged_1203b0" not in out, out


def test_no_note_when_there_was_nothing_to_keep():
    """A first registration has no existing list, so there is no no-op to report."""
    t, _ = _tool()
    out = _run(t, name="brand_new", path="x.jsx")
    assert "_apis_used_unchanged_1203b0" not in out, out


def test_the_schema_tells_the_lane_that_omitting_keeps_the_old_list():
    """The description has to carry the rule, because the schema is what the lane reads before
    it calls — the note above only arrives after a wasted call."""
    d = _TOOL.PARAMETERS["properties"]["apis_used"]["description"]
    assert "OMITTING" in d.upper(), d
    assert "full list" in d, d


def test_the_plumbing_below_already_forwarded_all_three():
    """Pinned so the fix is understood as a SCHEMA gap, not a new capability: `update_ui_page`
    has forwarded route/component/apis_used all along."""
    import inspect

    from multi_agent.runtime.hubs.workhub.service import WorkHub
    src = inspect.getsource(WorkHub.update_ui_page)
    for field in ("apis_used", "route", "component"):
        assert '"%s"' % field in src, "%s is not forwarded: %s" % (field, src[:400])


def test_kickoff_remains_the_only_other_writer():
    """Context for the fix, pinned as a fact: the kickoff tool has these fields and the
    implementation-phase tool now does too. If a THIRD writer appears, this is where to look."""
    names = []
    for obj in vars(HT).values():
        p = getattr(obj, "PARAMETERS", None)
        if isinstance(p, dict) and "apis_used" in (p.get("properties") or {}):
            names.append(getattr(obj, "NAME", obj.__name__))
    assert "registryhub_register_ui_page" in names, names
    assert "kickoff_declare_ui_page" in names, names
