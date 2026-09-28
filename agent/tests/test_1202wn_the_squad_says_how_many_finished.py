"""#1202wn: the squad's own completion count must survive the run.

`run_test_user_squad` builds a report -- spawned / completed / timed_out / failed plus a
per-agent row -- logs "N completed / M spawned" once per wave, returns it, and nothing
persisted it. So the number that says what the test-user squad actually did lived only in a
run log, and run logs are not kept.

That number is not incidental. MEASURED over 30 squad verdicts in 21 runs: completion is
0-6 of 12 agents, median ~2, never above 6. #1202ur corrected the VERDICT (a squad where
nobody finished no longer passes for having filed no P0) and deliberately left the
completion rate alone, because "raise the timeout" is the wrong move while the 900s escape
sits above the squad block. Deciding where the agents actually die needs this breakdown from
a finished run.

Appended per squad pass, so a run that ran several waves keeps each.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    record_squad_outcome_1202wn,
)


class _Orch:
    def __init__(self, d):
        self.output_dir = d


def _rows(tmp_path):
    p = tmp_path / "logs" / "test_user_squad_1202wn.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _report(**kw):
    base = {"spawned": 12, "completed": 2, "timed_out": 9, "failed": 1, "agents": []}
    base.update(kw)
    return base


def test_the_counts_land(tmp_path):
    assert record_squad_outcome_1202wn(_Orch(tmp_path), _report()) is True
    row = _rows(tmp_path)[0]
    assert (row["spawned"], row["completed"], row["timed_out"], row["failed"]) == (12, 2, 9, 1)


def test_each_agents_outcome_is_named(tmp_path):
    """"2 of 12 finished" does not say WHICH, and the next fix needs which."""
    agents = [{"goal": "browse the feed", "kind": "browser", "completed": False,
               "error": "TimeoutError: 900s"},
              {"goal": "post a comment", "kind": "api", "completed": True}]
    record_squad_outcome_1202wn(_Orch(tmp_path), _report(agents=agents))
    got = _rows(tmp_path)[0]["agents"]
    assert [a["goal"] for a in got] == ["browse the feed", "post a comment"]
    assert [a["completed"] for a in got] == [False, True]
    assert "Timeout" in got[0]["error"]


def test_a_long_roster_keeps_its_count_beside_the_cut(tmp_path):
    """#1034: a truncated list must not sit next to a number that implies it is whole."""
    agents = [{"goal": "g%d" % i, "completed": False} for i in range(40)]
    record_squad_outcome_1202wn(_Orch(tmp_path), _report(agents=agents))
    row = _rows(tmp_path)[0]
    assert row["agent_count"] == 40
    assert len(row["agents"]) == 20, "the roster is capped"


def test_each_wave_is_kept(tmp_path):
    record_squad_outcome_1202wn(_Orch(tmp_path), _report(completed=0))
    record_squad_outcome_1202wn(_Orch(tmp_path), _report(completed=3))
    assert [r["completed"] for r in _rows(tmp_path)] == [0, 3], (
        "appended, not overwritten -- a run's later wave must not erase its first")


def test_no_output_dir_writes_nothing(tmp_path):
    class _Bare:
        output_dir = None
    assert record_squad_outcome_1202wn(_Bare(), _report()) is False
    assert not (tmp_path / "logs").exists()


def test_a_non_report_is_refused(tmp_path):
    assert record_squad_outcome_1202wn(_Orch(tmp_path), None) is False
    assert record_squad_outcome_1202wn(_Orch(tmp_path), ["not", "a", "report"]) is False
    assert not (tmp_path / "logs").exists()


def test_the_recorder_is_called_where_the_report_is_finished():
    """★ A recorder nobody calls is the defect this ticket is about (#1202wm)."""
    import ast

    path = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                        "test_user_squad.py")
    with open(path, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "run_test_user_squad"), None)
    assert fn is not None, "run_test_user_squad is gone"
    assert any(isinstance(c, ast.Call) and getattr(c.func, "id", "") ==
               "record_squad_outcome_1202wn" for c in ast.walk(fn)), (
        "the squad finishes without writing down what it did")
