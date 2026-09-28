"""#1202wo: when no attendee records anything, write down who was expected and who spoke.

The kickoff driver already detects the condition and says so in the log. Its own comment
establishes the rest: 7 of 151 corpus runs end there having built nothing -- no DDL, no
seed, no frontend, no capture -- the salvage `_derive_missing_essential_sections` exists,
and its precondition (the stall escape's 240s floor) was unreachable in five of those seven
because the run was already over.

The comment also names what blocks the real fix: "tuning the floor without knowing why the
lanes never spawned would be a guess."

Nothing in a finished run answers that. `progress_events.jsonl` records the kickoff
STARTING, with its attendee list and a timestamp, and no artifact records how it went.
`.agent_logs/` is pruned: r135, which DELIVERED, and r136, which is on the silent list, both
show four empty lane directories today -- the two cases are indistinguishable afterwards.

So this records the census at the moment the condition is detected. It does NOT change
kickoff behaviour: a signal that cannot be validated against the corpus is not one to act
on (the same reason #1202wj declined to widen a blocking probe).
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.kickoff_driver import (  # noqa: E402
    _record_kickoff_silence_1202wo,
)


class _Orch:
    def __init__(self, d):
        self.output_dir = d


def _rows(tmp_path):
    p = tmp_path / "logs" / "kickoff_silence_1202wo.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _call(tmp_path, **kw):
    args = {"elapsed": 63.4, "expected": ["backend", "frontend", "verifier"],
            "missing": ["backend", "frontend", "verifier"], "rnd": 1, "polls": 7,
            "lane_activity": "backend: no tool calls"}
    args.update(kw)
    return _record_kickoff_silence_1202wo(
        _Orch(tmp_path), args["elapsed"], args["expected"], args["missing"],
        args["rnd"], args["polls"], args["lane_activity"])


def test_the_census_lands(tmp_path):
    assert _call(tmp_path) is True
    row = _rows(tmp_path)[0]
    assert row["expected_count"] == 3 and row["missing_count"] == 3
    assert row["elapsed_sec"] == 63.4 and row["round"] == 1 and row["polls"] == 7


def test_who_did_speak_is_derived(tmp_path):
    """★ "3 missing of 3" and "3 missing of 5" are different runs; name the difference."""
    _call(tmp_path, expected=["backend", "frontend", "verifier", "debugger"],
          missing=["backend", "frontend"])
    row = _rows(tmp_path)[0]
    assert row["recorded"] == ["debugger", "verifier"], row
    assert row["missing"] == ["backend", "frontend"]


def test_the_lane_activity_line_is_kept(tmp_path):
    """It is the only in-run evidence of whether a lane process did anything at all."""
    _call(tmp_path, lane_activity="backend: 0 calls; frontend: 0 calls")
    assert "0 calls" in _rows(tmp_path)[0]["lane_activity"]


def test_counts_sit_beside_the_capped_lists(tmp_path):
    """#1034: a truncated roster must not look whole."""
    many = ["lane%d" % i for i in range(40)]
    _call(tmp_path, expected=many, missing=many)
    row = _rows(tmp_path)[0]
    assert row["expected_count"] == 40 and len(row["expected"]) == 20
    assert row["missing_count"] == 40 and len(row["missing"]) == 20


def test_each_detection_is_appended(tmp_path):
    _call(tmp_path, elapsed=61.0)
    _call(tmp_path, elapsed=140.0)
    assert [r["elapsed_sec"] for r in _rows(tmp_path)] == [61.0, 140.0]


def test_no_output_dir_writes_nothing(tmp_path):
    class _Bare:
        output_dir = None
    assert _record_kickoff_silence_1202wo(_Bare(), 61.0, [], [], 1, 1, "") is False
    assert not (tmp_path / "logs").exists()


def test_the_recorder_is_called_at_the_detection(tmp_path):
    """★ A recorder nobody calls is the defect #1202wm was about."""
    import ast

    path = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                        "kickoff_driver.py")
    with open(path, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_drive_kickoff_to_completion"), None)
    assert fn is not None, "_drive_kickoff_to_completion is gone"
    guards = [n for n in ast.walk(fn)
              if isinstance(n, ast.If) and "_said_silent_862" in ast.unparse(n.test)]
    assert guards, "the silence detection is gone"
    assert any(isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "_record_kickoff_silence_1202wo"
               for g in guards for c in ast.walk(g)), (
        "the condition is detected and still leaves no evidence behind")
