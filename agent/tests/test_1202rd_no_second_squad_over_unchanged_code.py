r"""#1202rd: twelve more agents are not spent rediscovering what nobody has fixed.

`squad_gate_tick_action`'s docstring already stated the rule: consume clears the handle "so the
next 'launch' may re-arm AFTER THE FIX LANDS". Nothing checked that it had. Consume clears the
handle, the next delivery tick sees `task_exists=False`, and twelve agents go out again.

tiktok-r130:

    23:42:53  TEST-USER SQUAD (v1.0.0) verdict=DEFECTS: 19 open P0 (18 from test-users) / 3 P1
    23:44:29  TEST-USER SQUAD launched in BACKGROUND (single-flight, 648s deferred)
    23:44:30  TEST-USER SQUAD (v1.0.0): spawning 12 agents

Ninety-six seconds apart. In that gap the two lanes read files and claimed WorkHub tasks and
wrote nothing -- so the second squad was paid to rediscover the same nineteen defects.

The condition is "the app changed", not "the P0s are closed": a lane may fix code without
closing a ticket, and a squad re-running over changed code is doing its job. An unknown
signature never blocks -- refusing to test on ignorance would be worse than testing twice.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.test_user_squad import squad_relaunch_blocked_1202rd  # noqa: E402

SIG_A, SIG_B = "sha:aaa", "sha:bbb"


def test_the_r130_case_is_held():
    """Same code, 19 open P0 -> do not spend another twelve agents."""
    why = squad_relaunch_blocked_1202rd(SIG_A, SIG_A, 19)
    assert why and "19 open P0" in why


def test_changed_code_launches():
    """A lane edited something; re-testing is exactly the point of the gate."""
    assert squad_relaunch_blocked_1202rd(SIG_B, SIG_A, 19) == ""


def test_no_open_p0_launches():
    """Nothing to wait for."""
    assert squad_relaunch_blocked_1202rd(SIG_A, SIG_A, 0) == ""


def test_an_unknown_signature_never_blocks():
    """Refusing to test because the signature could not be read is worse than testing twice."""
    assert squad_relaunch_blocked_1202rd(None, SIG_A, 19) == ""
    assert squad_relaunch_blocked_1202rd(SIG_A, None, 19) == ""


def test_a_junk_p0_count_never_blocks():
    assert squad_relaunch_blocked_1202rd(SIG_A, SIG_A, None) == ""
    assert squad_relaunch_blocked_1202rd(SIG_A, SIG_A, "many") == ""


def test_it_says_why_rather_than_only_refusing():
    why = squad_relaunch_blocked_1202rd(SIG_A, SIG_A, 3)
    assert "has not changed" in why and "rediscover" in why


# --- reachable from the delivery tick, and fed by the consume branch ----------------------

SRC = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
       / "orchestrator.py").read_text(encoding="utf-8")


def _launch_branch() -> str:
    i = SRC.index('if _tu_action == "launch":')
    return SRC[i:SRC.index("self._tu_squad_task = asyncio.create_task(", i)]


def test_the_guard_runs_before_the_squad_is_armed():
    branch = _launch_branch()
    assert "squad_relaunch_blocked_1202rd(" in branch
    assert "return" in branch


def test_the_consume_branch_records_the_signature():
    """Without the stamp the guard can never fire -- the #1202 dead-mechanism shape."""
    i = SRC.index("_tu_result = self._tu_squad_task.result()")
    j = SRC.index("_tu_outcome = squad_gate_outcome(", i)
    assert "_tu_squad_verdict_sig_1202rd" in SRC[i:j]
    assert "_compute_app_source_signature()" in SRC[i:j]


def test_the_stamp_and_the_guard_use_the_same_attribute():
    assert SRC.count("_tu_squad_verdict_sig_1202rd") >= 2
