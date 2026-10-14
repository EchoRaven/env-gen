"""#1203kj: "verdict=PASS: 0 open P0" read the same over 12 of 12 goals as over 3 of 10.

The squad verdict line reported defects, by-modality and by-source and never how many agents
actually finished. The number was already in hand — `squad_gate_outcome` consumes
`report["completed"]` (that is #1202ur's point, after a PASS with ZERO completions) and every
wave line prints it; only the verdict omitted it.

Measured over the corpus's squad runs, completion has improved a lot since #1202ur wrote
"0-6 of 12, median ~2, never above 6": modern runs are median 7/12 with none at zero, and
r187 finished 12/12. But r180 passed on 3/10 and r184/r181/r176 on 4/12, and none of those
lines said so.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import squad_coverage_1203kj as COV  # noqa: E402

_UNKNOWN = "coverage unknown (no spawn/completion count in this report)"


def test_it_names_both_numbers_1203kj():
    assert COV({"completed": 3, "spawned": 10}) == "3/10 agents finished"
    assert COV({"completed": 12, "spawned": 12}) == "12/12 agents finished"


def test_zero_completions_is_reported_not_hidden_1203kj():
    """#1202ur routes that case to `retry`; the line must still be able to say it."""
    assert COV({"completed": 0, "spawned": 12}) == "0/12 agents finished"


def test_a_missing_count_says_unknown_rather_than_guessing_zero_1203kj():
    """#1202tn: a fault-tolerant helper's zero may not be used as a fact, and an older or
    restored report shape carries no counts at all."""
    for r in ({}, {"completed": 3}, {"spawned": 10}, {"completed": None, "spawned": None}):
        assert COV(r) == _UNKNOWN, r


def test_a_zero_spawn_is_unknown_not_a_division_1203kj():
    assert COV({"completed": 0, "spawned": 0}) == _UNKNOWN


def test_a_bool_is_not_a_count_1203kj():
    """`True` is an int in Python, and "True/10 agents finished" would be a sentence nobody
    could act on."""
    assert COV({"completed": True, "spawned": 10}) == _UNKNOWN
    assert COV({"completed": 3, "spawned": True}) == _UNKNOWN


def test_junk_cannot_break_it_1203kj():
    for r in (None, [], "x", 7, {"completed": "3", "spawned": "10"}):
        assert COV(r) == _UNKNOWN, r


def test_the_verdict_line_actually_carries_it_1203kj():
    """#1139/#1148 and today's #1203kc: a value nobody emits changes nothing. Asked of the
    AST, because a source-text assertion gets fed by the comment that quotes the code."""
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_squad.py").read_text("utf-8")
    tree = ast.parse(src)
    calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    verdicts = [c for c in calls if "TEST-USER SQUAD" in c and "verdict=" in c]
    assert len(verdicts) == 1, verdicts
    line = verdicts[0]
    assert "squad_coverage_1203kj" in line or "_cov1203kj" in line, line
    assert "open P0" in line, "the defect counts must stay — coverage is added, not swapped in"
