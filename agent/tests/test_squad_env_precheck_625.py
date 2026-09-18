r"""#625: the test-user squad drove a target that was not listening.

The squad spawns one agent per goal and each files its own bugs. When the stack is down, every
agent independently discovers "connection refused" and files it as a product defect:

    555 bugs across 40 runs
     47 connectivity-shaped — 46 of them P0     (r121: 19, r137: 15, r125: 8)

One environment event, reported N times, at the top severity. The lanes then burn real turns
triaging it — the recorded cancel reasons are "False-positive: test-user targeted wrong ports",
"Root cause resolved: docker stack was not up when test-users ran", "Duplicate: same stack-down
root cause".

`test_user_validation` already got this guard in Round 32: it waits for /health and reports
ENV_UNAVAILABLE "instead of misdiagnosing the app". The SQUAD — which is what actually files the
bugs — never did.

The check is a SOCKET probe, deliberately not a filter on bug text: "unreachable" appears in
genuine product bugs too (r119's P2 "POST /api/continue-watching returns 404 — endpoint
unreachable / route not mounted"), so classifying findings after the fact would suppress real
ones.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_squad as sq


@pytest.fixture()
def probe(monkeypatch):
    """Control which URLs 'answer'. Keys are substrings; value None means the socket is dead."""
    state = {"ui": 200, "api": 200}

    def fake(url, timeout=4.0):
        return state["api"] if "/health" in url else state["ui"]

    monkeypatch.setattr(sq, "_probe_http_625", fake)
    monkeypatch.setattr(sq, "_PROBE_DEADLINE_625", 0.0)
    # #1202qu gave the squad's own probe a cold-boot budget; these tests want neither wait.
    monkeypatch.setattr(sq, "_BOOT_DEADLINE_1202QU", 0.0)
    return state


_UI, _API = "http://localhost:8081", "http://localhost:3000"


# --- the probe --------------------------------------------------------------------------------

def test_both_up_is_reported_up(probe):
    assert sq.targets_reachable_625(_UI, _API, deadline=0) == {"ui": True, "api": True}


def test_a_dead_socket_is_reported_down(probe):
    probe["api"] = None
    assert sq.targets_reachable_625(_UI, _API, deadline=0) == {"ui": True, "api": False}


def test_any_status_counts_as_up(probe):
    """A bare root often 404s; the socket still serves."""
    probe["ui"] = 404
    assert sq.targets_reachable_625(_UI, _API, deadline=0)["ui"] is True


def test_it_retries_until_the_deadline(monkeypatch):
    """A slow-starting stack must not be called down on the first probe."""
    calls = {"n": 0}

    def fake(url, timeout=4.0):
        calls["n"] += 1
        return 200 if calls["n"] > 2 else None

    monkeypatch.setattr(sq, "_probe_http_625", fake)
    monkeypatch.setattr(sq, "_PROBE_INTERVAL_625", 0.0)
    assert sq.targets_reachable_625(_UI, _API, deadline=5)["api"] or calls["n"] > 2


# --- which goals survive -----------------------------------------------------------------------

_GOALS = [{"name": "a", "modality": "browser"}, {"name": "b", "modality": "api"},
          {"name": "c", "modality": "mcp"}]


def test_a_dead_ui_drops_only_the_browser_goals():
    kept = sq._runnable_goals_625(_GOALS, {"ui": False, "api": True})
    assert [g["name"] for g in kept] == ["b", "c"]


def test_a_dead_api_drops_every_goal():
    """mcp talks to the API, and so does browser -- #1202qu. A browser test-user drives the
    UI to exercise the APP; with the API down every page it opens is the stack's state."""
    assert sq._runnable_goals_625(_GOALS, {"ui": True, "api": False}) == []


def test_everything_down_drops_everything():
    assert sq._runnable_goals_625(_GOALS, {"ui": False, "api": False}) == []


def test_everything_up_changes_nothing():
    kept = sq._runnable_goals_625(_GOALS, {"ui": True, "api": True})
    assert [g["name"] for g in kept] == ["a", "b", "c"]


# --- the runner --------------------------------------------------------------------------------

class _Spawn:
    def __init__(self):
        self.requests = []

    async def spawn(self, req):
        self.requests.append(req)
        raise RuntimeError("should not be reached in these tests")


class _Orch:
    def __init__(self):
        self.spawn_service = _Spawn()
        self._logger = None


def test_nothing_is_spawned_when_the_target_is_down(probe):
    import asyncio
    probe["ui"] = probe["api"] = None
    orch = _Orch()
    rep = asyncio.run(sq.run_test_user_squad(orch, _GOALS, ui_base=_UI, api_base=_API))
    assert orch.spawn_service.requests == []
    assert rep["spawned"] == 0
    assert rep["skipped_env_unavailable"] == 3


def test_the_report_says_which_side_was_down(probe):
    import asyncio
    probe["api"] = None
    rep = asyncio.run(sq.run_test_user_squad(_Orch(), _GOALS, ui_base=_UI, api_base=_API))
    assert "api=" in rep["error"] and "DOWN" in rep["error"]
    assert rep["reachable"] == {"ui": True, "api": False}
    assert rep["skipped_env_unavailable"] == 3      # #1202qu: browser needs the API too


def test_a_healthy_stack_still_dispatches(probe):
    """The guard must be invisible when the app is up."""
    import asyncio
    rep = asyncio.run(sq.run_test_user_squad(_Orch(), _GOALS, ui_base=_UI, api_base=_API))
    assert "skipped_env_unavailable" not in rep
    assert rep["reachable"] == {"ui": True, "api": True}


# --- the hazard this fix introduces, closed ------------------------------------------------------

def test_a_skipped_squad_is_RETRY_not_PASS():
    """With no agent dispatched no P0 is filed, and `ran=True, p0=0` is exactly the input that
    sets _tu_squad_passed and releases the milestone UNTESTED. Not running must stay `retry`."""
    assert sq.squad_gate_outcome(ran=False, p0=0) == "retry"
    assert sq.squad_gate_outcome(ran=True, p0=0) == "pass"


def test_the_delivery_wrapper_reports_it_as_not_ran():
    import inspect
    src = inspect.getsource(sq._run_squad_for_delivery_impl)  # #1202nx: body behind the lease
    i = src.index("#625: if the target was down")
    block = src[i:src.index("bugs = collect_test_user_bugs", i)]
    assert '"ran": False' in block
    assert "skipped_env_unavailable" in block


def test_it_returns_before_the_ledger_records_false_failures():
    """A stack-down cycle must not mark every goal as a fresh regression."""
    import inspect
    src = inspect.getsource(sq._run_squad_for_delivery_impl)  # #1202nx: body behind the lease
    assert src.index("skipped_env_unavailable") < src.index("ledger.record_cycle")


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(sq).replace("#", " ").split())
    assert "47 of the" in flat and "555 bugs across 40 runs" in flat
    assert "19 in r121" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
