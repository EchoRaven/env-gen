r"""#1202aa: a stopped lane is reported as stopped, not nudged as if it were slow.

`nudge_silent_resident_lanes` classifies a lane by heartbeat FRESHNESS alone, so a lane whose
run loop has exited looks exactly like one that is merely busy. r32 ended on that confusion:

    00:31:38  Stopping agent: Frontend Engineer Agent
    ...       Stall escalation (elapsed=5560s ... 5778s) — dispatched urgent task_ready to
              silent resident lanes ['frontend'], repeatedly
    Status: FAIL — cannot complete task

95 minutes of urgent dispatch at a lane whose queue had no reader, and the run finished with
one milestone instead of three. #1202z is the other half of the same event: the resident
wakeup that reported itself "scheduled" onto that same dead queue.

The agent object is in `_orch._agents` and knows whether it is running. Saying which it is
turns an unbounded nudge loop into one actionable line. It deliberately does NOT restart the
lane — that decision belongs to whoever owns lane lifecycle, and inventing it here would be a
second guess on top of a first one.

Unknown state is treated as running: `getattr(..., "is_running", True)`, so a lane object that
does not expose the attribute is nudged exactly as before.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_SRC = (THIS_DIR.parent
        / "env_generator/llm_generator/multi_agent/runtime/coordination.py"
        ).read_text(encoding="utf-8")


def _guard():
    """The #1202aa block, located by landmark (#943 — no fixed byte windows)."""
    start = _SRC.index("# #1202aa:")
    end = _SRC.index("# Don't nudge a lane that has NO actionable work", start)
    return _SRC[start:end]


def test_the_guard_reads_the_agent_object_not_the_heartbeat():
    g = _guard()
    assert "_orch._agents" in g
    assert "is_running" in g


def test_unknown_state_is_treated_as_running():
    """A lane object without the attribute must be nudged exactly as before."""
    assert 'getattr(_agent_obj, "is_running", True) is False' in _guard()


def test_it_skips_rather_than_nudging():
    """The guard's last statement is `continue`, so the dispatch below is never reached."""
    g = _guard()
    stmts = [ln.strip() for ln in g.rstrip().splitlines() if ln.strip()]
    assert stmts[-1] == "continue"


def test_it_says_what_the_consequence_is():
    g = _guard()
    assert "STOPPED, not slow" in g
    assert "needs restarting" in g


def test_it_does_not_restart_the_lane():
    """Lane lifecycle is not this function's call; inventing a restart here would be a second
    guess on top of the first."""
    g = _guard()
    for verb in ("start(", "restart(", "spawn(", "respawn("):
        assert verb not in g


def test_the_freshness_path_still_wins_first():
    """A lane with a recent heartbeat must never reach the stopped check."""
    i_fresh = _SRC.index("_silent_lane_nudges.pop(lane_id, None)")
    i_guard = _SRC.index("# #1202aa:")
    assert i_fresh < i_guard
