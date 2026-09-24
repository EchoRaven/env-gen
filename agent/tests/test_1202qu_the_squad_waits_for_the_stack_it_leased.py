r"""#1202qu: the squad waits for a booting stack, and a browser goal needs the API too.

tiktok-r128, 17:25-17:34. The orchestrator launched the test-user squad right after a validation
cycle had recreated the stack. The squad took the compose lease (#1202nx logged "api_smoke
validation (fresh boot) waits to tear the stack down: in use by test-user squad"), then ran
#625's reachability probe. The probe's budget is 60s; a `down -v` + build + migrate + seed takes
longer, so at 17:26:39 it reported `api=http://localhost:8008 DOWN`.

Two things then went wrong, and they are the two halves of this fix:

1. Because the probe gave up early, the 3 api/mcp goals were never dispatched -- on a stack
   nothing could take down, because this squad held the lease. Waiting was free.

2. The 7 BROWSER goals were dispatched anyway: `need` mapped `browser` to `ui` alone. They ran
   for nine minutes against a frontend whose backend refused every connection -- their own
   `test_api` lines read `NOTHING IS LISTENING at localhost:8008` -- and then the
   `skipped_env_unavailable` early return threw the whole report away. A browser test-user
   drives the UI to exercise the APP; with the API down every page it can reach is the stack's
   state, which is the one thing #625 exists to keep out of the bug queue.
"""
import asyncio

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_squad as sq


_UI, _API = "http://localhost:8081", "http://localhost:3000"
_GOALS = [{"name": "a", "modality": "browser"}, {"name": "b", "modality": "api"},
          {"name": "c", "modality": "mcp"}]


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


@pytest.fixture()
def instant(monkeypatch):
    """No real waiting in either budget."""
    monkeypatch.setattr(sq, "_PROBE_DEADLINE_625", 0.0)
    monkeypatch.setattr(sq, "_PROBE_INTERVAL_625", 0.0)
    monkeypatch.setattr(sq, "_BOOT_DEADLINE_1202QU", 0.0)


def test_a_browser_goal_is_not_runnable_without_the_api():
    """The r128 case: ui up, api down. Nothing may be dispatched."""
    assert sq._runnable_goals_625(_GOALS, {"ui": True, "api": False}) == []


def test_a_dead_ui_still_leaves_the_api_side_runnable():
    """The half-up principle survives in the direction that still makes sense."""
    kept = sq._runnable_goals_625(_GOALS, {"ui": False, "api": True})
    assert [g["name"] for g in kept] == ["b", "c"]


def test_a_healthy_stack_runs_everything():
    kept = sq._runnable_goals_625(_GOALS, {"ui": True, "api": True})
    assert [g["name"] for g in kept] == ["a", "b", "c"]


def test_no_browser_agent_is_spawned_against_a_dead_api(monkeypatch, instant):
    """Counter-proof for (2): before this fix, `a` was dispatched here."""
    monkeypatch.setattr(sq, "_probe_http_625",
                        lambda url, timeout=4.0: None if "/health" in url else 200)
    orch = _Orch()
    rep = asyncio.run(sq.run_test_user_squad(orch, _GOALS, ui_base=_UI, api_base=_API))
    assert orch.spawn_service.requests == []
    assert rep["skipped_env_unavailable"] == 3


def test_the_squad_waits_out_a_cold_boot(monkeypatch):
    """Counter-proof for (1): the stack answers only after the #625 budget would have expired,
    and every goal still runs."""
    calls = {"n": 0}

    def _late(url, timeout=4.0):
        calls["n"] += 1
        return 200 if calls["n"] > 4 else None

    monkeypatch.setattr(sq, "_probe_http_625", _late)
    monkeypatch.setattr(sq, "_PROBE_DEADLINE_625", 0.0)   # the old budget: gives up at once
    monkeypatch.setattr(sq, "_PROBE_INTERVAL_625", 0.0)
    monkeypatch.setattr(sq, "_BOOT_DEADLINE_1202QU", 30.0)
    rep = asyncio.run(sq.run_test_user_squad(_Orch(), _GOALS, ui_base=_UI, api_base=_API))
    assert "skipped_env_unavailable" not in rep
    assert rep["reachable"] == {"ui": True, "api": True}


def test_the_boot_budget_is_longer_than_the_probe_budget():
    """The constant exists to be longer; a regression that equalises them is the r128 bug."""
    assert sq._BOOT_DEADLINE_1202QU > sq._PROBE_DEADLINE_625
