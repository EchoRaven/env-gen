r"""#1203rk: a test-user goal whose agent never spawned was dropped in total silence.

`run_test_user_squad` catches a spawn refusal per goal rather than failing the whole squad,
which is right -- one unlucky worktree should not cost the other eleven goals. But the
handler only wrote the reason into the per-agent record and returned. Nothing was logged.

WHAT THAT COSTS. Returning before the agent is counted as spawned is correct, since it never
ran; the effect is that every counter in the report stays silent too. `spawned` does not
include it, `completed` does not, and `timed_out` does not -- so an operator reading the run
log sees a squad that spawned N and finished N, with no hint that a goal was never exercised
at all. The only record was the per-agent error inside `test_user_squad_1202wn.jsonl`.

MEASURED on 2026-10-21 over the 36 corpus squad ledgers:
  * 8 agents carry `spawn failed: RuntimeError: agent worktree registration failed`
    -- 6 in tiktok-web-r170, 2 in tiktok-web-r169, across page / ui_crud / isolation /
    mcp_parity
  * the raise's own wording appears in 0 of the 213 run logs
  * the report's `failed` count is 8 corpus-wide -- EXACTLY these agents, because the
    gather classifies a record as timed out only when its error carries the timeout
    wording. So `failed` has never meant "ran and failed"; it has only ever meant
    "never started", and the claim it supports elsewhere reads differently once you know
    that.

#1203hf is the same failure, half handled: it records the briefing BEFORE the spawn so that
"what was this agent told" survives an agent that dies, reasoning that the briefing is most
needed exactly then. It preserved the evidence and did not announce the event. Copying a
precedent means copying both halves.

The announcement is what this ticket adds. The classification is only PINNED here, not
changed -- `failed` vs `timed_out` is load-bearing for readers of the ledger.
"""
import asyncio
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_squad as sq

_UI, _API = "http://localhost:8081", "http://localhost:3000"
_GOALS = [{"name": "page_login", "modality": "browser", "kind": "page"},
          {"name": "api_posts", "modality": "api", "kind": "api_crud"}]


class _Log:
    """Captures what an operator would have seen in the run log, WITH THE LEVEL.

    The level is not a detail here. `[D]` lines appear in 4 of the 213 corpus run logs and
    `[I]` lines in essentially all of them, so an announcement demoted to debug is gone from
    209 runs out of 213 while every level-blind test stays green. The first version of this
    fake collapsed all four levels into one list and could not have seen that.
    """

    def __init__(self):
        self.records = []          # (level, rendered message)

    def _at(self, level):
        def _add(msg, *a):
            try:
                self.records.append((level, str(msg) % a if a else str(msg)))
            except Exception:
                self.records.append((level, "%s %r" % (msg, a)))
        return _add

    def __getattr__(self, name):
        if name in ("warning", "info", "debug", "error", "critical"):
            return self._at(name)
        raise AttributeError(name)

    @property
    def lines(self):
        return [m for _lvl, m in self.records]


class _Spawn:
    """`raises` is the exception the spawn refuses with, or None to accept."""

    def __init__(self, raises=None):
        self.raises = raises
        self.requests = []

    async def spawn(self, req):
        self.requests.append(req)
        if self.raises is not None:
            raise self.raises
        ev = asyncio.Event()
        ev.set()
        return type("R", (), {"task_done_event": ev})()

    async def terminate(self, agent_id, wait=False):
        return None


class _Orch:
    def __init__(self, raises=None):
        self.spawn_service = _Spawn(raises)
        self._logger = _Log()
        self.output_dir = None


@pytest.fixture(autouse=True)
def reachable(monkeypatch, tmp_path):
    """The stack answers, so goals are dispatched; no real waiting anywhere."""
    monkeypatch.setattr(sq, "_probe_http_625", lambda url, timeout=4.0: 200)
    monkeypatch.setattr(sq, "_PROBE_DEADLINE_625", 0.0)
    monkeypatch.setattr(sq, "_PROBE_INTERVAL_625", 0.0)
    monkeypatch.setattr(sq, "_BOOT_DEADLINE_1202QU", 0.0)


def _run(orch):
    return asyncio.run(sq.run_test_user_squad(orch, _GOALS, ui_base=_UI, api_base=_API))


def _rk(orch):
    return [l for l in orch._logger.lines if "#1203rk" in l]


# ------------------------------------------------------------------ the ticket

def test_a_refused_spawn_is_announced():
    """★ THE TICKET. The event reached no reader at all; now it reaches the run log."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    _run(orch)
    said = _rk(orch)
    assert said, ("a refused spawn produced no #1203rk line; the operator still cannot see "
                  "that a goal went unexercised. Logged: %r" % orch._logger.lines)


def test_the_announcement_names_the_goal_and_its_kind():
    """A count would not be actionable -- WHICH goal was skipped is the whole point."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    _run(orch)
    said = " ".join(_rk(orch))
    assert "page_login" in said, said
    assert "page" in said, said


def test_the_announcement_carries_the_cause():
    """#1201's rule: say WHY, or the reader cannot tell a bug from an environment hiccup."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    _run(orch)
    said = " ".join(_rk(orch))
    assert "worktree registration failed" in said, said
    assert "RuntimeError" in said, said


def test_it_says_the_goal_was_never_exercised():
    """The CONSEQUENCE, not just the error. A reader who sees only a stack trace concludes
    'one agent had a bad start'; the thing that matters is that nothing was checked."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    _run(orch)
    said = " ".join(_rk(orch))
    assert "NEVER EXERCISED" in said, said


def test_a_successful_spawn_says_nothing():
    """COUNTER-PROOF: the line must not fire on the ordinary path, or it is noise and the
    next reader learns to skip it."""
    orch = _Orch(raises=None)
    _run(orch)
    assert _rk(orch) == [], orch._logger.lines


def test_a_missing_logger_is_not_a_crash():
    """The squad runs with `_logger` unset in several harnesses, and losing the whole squad
    over an announcement would be a far worse trade than losing the announcement."""
    orch = _Orch(raises=RuntimeError("boom"))
    orch._logger = None
    rep = _run(orch)
    assert int(rep.get("failed") or 0) == 2, rep


def test_the_announcement_is_at_a_level_the_run_log_keeps():
    """`[D]` is in 4 of 213 run logs and `[I]` in essentially all, so a demotion to debug
    deletes this line from 209 runs while saying nothing. Warning or above."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    _run(orch)
    levels = {lvl for lvl, m in orch._logger.records if "#1203rk" in m}
    assert levels, orch._logger.records
    assert levels <= {"warning", "error", "critical"}, (
        "the #1203rk line is emitted at %r, which does not survive into a normal run log"
        % sorted(levels))

# ------------------------------------------------------- the classification this pins

def test_a_refused_spawn_counts_as_failed_and_not_as_timed_out():
    """PINNED, not changed. Corpus-wide `failed` is 8 and every one of them is a refused
    spawn, so a reader who takes `failed` to mean 'ran and failed' is reading it wrong."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    rep = _run(orch)
    assert int(rep.get("failed") or 0) == 2, rep
    assert int(rep.get("timed_out") or 0) == 0, rep


def test_a_refused_spawn_is_not_counted_as_spawned():
    """It never ran, so counting it would overstate how much of the app was exercised."""
    orch = _Orch(raises=RuntimeError("agent worktree registration failed for browser_x"))
    rep = _run(orch)
    assert int(rep.get("spawned") or 0) == 0, rep
    assert int(rep.get("completed") or 0) == 0, rep
