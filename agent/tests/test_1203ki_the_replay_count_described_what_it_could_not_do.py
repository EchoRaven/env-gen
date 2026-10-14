"""#1203ki: "replaying N prior failure(s) first", where N could exceed the agents spawned.

`open_failures()` is every unpassed key the ledger holds, from every cycle. The squad logged
its LENGTH as the replay count — but `order_replay_first` can only move goals that are IN this
cycle's plan, so the number described something it could not do.

Measured over the corpus's 192 squad-spawn lines: 6 claim to replay MORE failures than there
are agents — "spawning 12 agents across modalities ['browser'] … replaying 14 prior
failure(s) first". The extras are other cycles' modalities still in the ledger (`api::`,
`mcp::`) while this cycle planned browser goals only.

The carried-over half is kept rather than filtered: a goal that failed before and is NOT in
this cycle's plan is a failure nobody will re-test, which is worth saying on its own.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import FailureLedger  # noqa: E402


def _ledger(tmp_path, goals):
    p = tmp_path / "failure_ledger.json"
    p.write_text(json.dumps({"cycle": 2, "goals": goals}), encoding="utf-8")
    return FailureLedger(p)


def _g(mod, name):
    return {"modality": mod, "name": name}


_LEDGER = {
    "browser::page_a": {"passed": False},
    "browser::page_b": {"passed": False},
    "api::api_smoke": {"passed": False},
    "mcp::mcp_surface": {"passed": True},
}


def test_only_the_planned_failures_count_as_replayed_1203ki(tmp_path):
    L = _ledger(tmp_path, _LEDGER)
    replay, carried = L.replay_split_1203ki([_g("browser", "page_a"), _g("browser", "page_c")])
    assert replay == ["browser::page_a"], replay
    assert sorted(carried) == ["api::api_smoke", "browser::page_b"], carried


def test_the_replay_count_can_never_exceed_the_plan_1203ki(tmp_path):
    """The arithmetic the corpus caught: 12 agents, 14 'replayed'."""
    L = _ledger(tmp_path, {"browser::p%d" % i: {"passed": False} for i in range(14)})
    plan = [_g("browser", "p%d" % i) for i in range(12)]
    replay, carried = L.replay_split_1203ki(plan)
    assert len(replay) <= len(plan), (len(replay), len(plan))
    assert len(replay) == 12 and len(carried) == 2


def test_a_passed_goal_is_in_neither_half_1203ki(tmp_path):
    L = _ledger(tmp_path, _LEDGER)
    replay, carried = L.replay_split_1203ki([_g("mcp", "mcp_surface")])
    assert "mcp::mcp_surface" not in replay + carried, (replay, carried)


def test_the_two_halves_partition_the_open_failures_1203ki(tmp_path):
    L = _ledger(tmp_path, _LEDGER)
    replay, carried = L.replay_split_1203ki([_g("browser", "page_a")])
    assert sorted(replay + carried) == sorted(L.open_failures())
    assert not (set(replay) & set(carried)), "a key may not be in both halves"


def test_an_empty_plan_replays_nothing_and_carries_everything_1203ki(tmp_path):
    L = _ledger(tmp_path, _LEDGER)
    for plan in ([], None):
        replay, carried = L.replay_split_1203ki(plan)
        assert replay == [] and len(carried) == 3, (plan, replay, carried)


def test_junk_goals_cannot_break_it_1203ki(tmp_path):
    L = _ledger(tmp_path, _LEDGER)
    replay, carried = L.replay_split_1203ki([None, 7, "x", _g("browser", "page_a")])
    assert replay == ["browser::page_a"], replay


def test_an_empty_ledger_is_silent_1203ki(tmp_path):
    L = _ledger(tmp_path, {})
    assert L.replay_split_1203ki([_g("browser", "page_a")]) == ([], [])


def test_the_log_line_uses_the_split_and_names_what_it_skips_1203ki():
    """#1034: the count beside the list must describe that list, and the carried half must be
    named — a failure nobody re-tests is the half a reader needs."""
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_squad.py").read_text("utf-8")
    tree = ast.parse(src)
    calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    logline = [c for c in calls if "replaying %d prior failure" in c]
    assert len(logline) == 1, logline
    body = logline[0]
    assert "len(_replay1203ki)" in body, (
        "the replayed count must be the PLANNED half, not len(open_failures())", body)
    assert "open_failures()" not in body, body
    assert "_carried1203ki" in body and "NOT in this cycle's plan" in body, body
