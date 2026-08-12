r"""#628: `bug_found` waited to be subscribed to, and mostly wasn't.

`bug_create` published the event with no `recipients`, so delivery depended entirely on a matching
subscription existing at that instant. Across 45 runs:

    555 bug_found events
    443 (80%) reached NOBODY

The model is exact. Of the 16 runs that ever record a bug_found subscription:

    144 undelivered events were filed BEFORE the subscription existed
      0 after it

The other 29 runs never subscribe at all, so every bug is broadcast into the void.

The code's older note blamed a `source_hub` mismatch with the debugger's
`('verifier','bug_found')` subscription. That hypothesis was tested and REJECTED: verifier-sourced
events go undelivered 312 of 408 times, and browser_test_user ones do get through 15 times. It is
timing, not source.

`_record_breaking_change` already shows the right shape — name the recipients rather than hoping a
subscription exists. `publish_event` unions explicit recipients with subscription matches, so this
can only add.
"""
import pytest

from env_generator.llm_generator.tools import bug_tools


class _EventHub:
    def __init__(self):
        self.published = []

    def publish_event(self, **kw):
        self.published.append(kw)
        return {"id": "evt_1"}


class _WorkHub:
    def __init__(self):
        self.created = []

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "task_1", **kw}


class _Hubs:
    def __init__(self):
        self.eventhub = _EventHub()
        self.workhub = _WorkHub()


@pytest.fixture()
def tool():
    t = bug_tools.BugCreateTool.__new__(bug_tools.BugCreateTool)
    t._hubs = _Hubs()
    t._agent_id = "verifier"
    return t


async def _file(tool, **over):
    kw = dict(source="verifier", severity="P0", title="Landing page renders blank",
              bug_artifacts={"actual": "blank"}, description="")
    kw.update(over)
    return await tool._run(**kw)


def _event(tool):
    return next(e for e in tool._hubs.eventhub.published if e["event_type"] == "bug_found")


# --- the recipient ------------------------------------------------------------------------------

def test_the_event_names_a_recipient(tool):
    """A bug owned by a lane must still tell the triage role it happened."""
    import asyncio
    asyncio.run(_file(tool, bug_artifacts={"affected_files": ["app/frontend/src/pages/X.jsx"]}))
    assert _event(tool)["recipients"] == ["debugger"]


def test_it_no_longer_depends_on_a_subscription(tool):
    """The whole defect: `recipients` was absent, so an unsubscribed run delivered nothing."""
    import asyncio
    asyncio.run(_file(tool))
    assert "recipients" in _event(tool)


def test_the_assignee_is_not_double_woken(tool):
    """create_task(assignee=...) already wakes the fixer; naming them again is noise."""
    import asyncio
    # a title+artifact that routes to the frontend lane
    asyncio.run(_file(tool, bug_artifacts={"affected_files": ["app/frontend/src/pages/X.jsx"]}))
    task = tool._hubs.workhub.created[0]
    assert task["assignee"] == "frontend"
    assert "frontend" not in _event(tool)["recipients"]


def test_a_bug_the_triage_owner_already_owns_notifies_nobody_extra(tool):
    """When the #626 fallback assigns the debugger, the event must not wake it twice."""
    import asyncio
    asyncio.run(_file(tool, title="something with no routable words", bug_artifacts={"actual": "x"}))
    assert tool._hubs.workhub.created[0]["assignee"] == "debugger"
    assert _event(tool)["recipients"] == []


# --- it must not change anything else -------------------------------------------------------------

def test_the_payload_and_priority_are_unchanged(tool):
    import asyncio
    asyncio.run(_file(tool))
    e = _event(tool)
    assert e["priority"] == "high"
    assert set(e["payload"]) == {"task_id", "severity", "title"}


def test_a_low_severity_bug_still_publishes(tool):
    import asyncio
    asyncio.run(_file(tool, severity="P3"))
    assert _event(tool)["priority"] == "normal"


def test_the_bug_task_is_still_the_source_of_truth(tool):
    """Event publication stays best-effort — a broken eventhub must not lose the bug."""
    import asyncio

    def boom(**kw):
        raise RuntimeError("eventhub down")

    tool._hubs.eventhub.publish_event = boom
    res = asyncio.run(_file(tool))
    assert res.data["id"] == "task_1"


def test_the_rejected_hypothesis_is_recorded():
    """A future reader must not re-derive the source_hub theory the data refutes."""
    import inspect
    flat = " ".join(inspect.getsource(bug_tools.BugCreateTool).replace("#", " ").split())
    assert "It is timing, not source" in flat
    assert "312 of 408" in flat


def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(bug_tools.BugCreateTool).replace("#", " ").split())
    assert "443 of 555" in flat
    assert "144 undelivered events were filed BEFORE" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
