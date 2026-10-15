"""#1203km: a goal the cap removed was never recorded, so the cap removed it again.

#1203kl made a previously-FAILED goal survive the cap. A goal the cap DROPPED never entered
the ledger at all — neither passed nor failed, just absent — so nothing prioritised it and the
cap's stable order dropped it again next cycle.

Measured over the modern era: 29 goals dropped across 10 of 35 runs, 24 never spawned in their
run. In the multi-cycle runs the stable order is what makes it permanent: 12 goals across 4
runs were dropped on EVERY cycle of their run — r179 seven of them, r183 two, r170 two, r177
one — so those flows were never tested at all.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    FailureLedger, goal_ledger_key_1203kl as KEY, plan_test_user_goals as PLAN,
    _dropped_goals_1203go as DROPPED)


def _ledger(tmp_path, goals, cycle=1):
    p = tmp_path / "failure_ledger.json"
    p.write_text(json.dumps({"cycle": cycle, "goals": goals}), encoding="utf-8")
    return FailureLedger(p)


def _g(name, mod="browser"):
    return {"name": name, "kind": "page", "modality": mod}


def test_a_first_sighting_becomes_an_open_failure_1203km(tmp_path):
    L = _ledger(tmp_path, {})
    assert L.note_never_run_1203km([_g("page_z")]) == ["browser::page_z"]
    assert L.open_failures() == ["browser::page_z"]


def test_an_earned_pass_is_never_overwritten_1203km(tmp_path):
    """The churn this guard prevents: a goal that PASSED in cycle 2 and is dropped in cycle 3
    would go back to being an open failure, undoing the pass and oscillating forever."""
    L = _ledger(tmp_path, {"browser::page_a": {"passed": True, "pass_count": 1}})
    assert L.note_never_run_1203km([_g("page_a")]) == []
    assert L.data["goals"]["browser::page_a"]["passed"] is True
    assert L.open_failures() == []


def test_a_recorded_failure_is_also_left_alone_1203km(tmp_path):
    L = _ledger(tmp_path, {"browser::page_a": {"passed": False, "fail_streak": 3}})
    assert L.note_never_run_1203km([_g("page_a")]) == []
    assert L.data["goals"]["browser::page_a"]["fail_streak"] == 3, "history is not reset"


def test_it_says_the_entry_was_never_run_1203km(tmp_path):
    """`passed: False` alone would read as a verdict. The marker keeps the two apart for any
    later reader (#771b's distinction between 'checked, no' and 'not checked')."""
    L = _ledger(tmp_path, {})
    L.note_never_run_1203km([_g("page_z")])
    assert L.data["goals"]["browser::page_z"]["never_run_1203km"] is True


def test_it_persists_1203km(tmp_path):
    L = _ledger(tmp_path, {})
    L.note_never_run_1203km([_g("page_z")])
    again = FailureLedger(tmp_path / "failure_ledger.json")
    assert again.open_failures() == ["browser::page_z"], "the next cycle reads a FILE"


def test_nothing_dropped_writes_nothing_1203km(tmp_path):
    p = tmp_path / "failure_ledger.json"
    L = _ledger(tmp_path, {})
    before = p.read_text(encoding="utf-8")
    for d in ([], None, [None, 7, "x"]):
        assert L.note_never_run_1203km(d) == [], d
    assert p.read_text(encoding="utf-8") == before, "no write when there is nothing to add"


def test_the_modality_survives_the_drop_projection_1203km():
    """The key needs `modality`, and `_dropped_goals_1203go` used to project it away."""
    eps = [{"method": "GET", "path": "/api/a", "status": "implemented"}]
    pages = [{"name": "p%d" % i, "route": "/p%d" % i} for i in range(20)]
    kept = PLAN(business_eps=eps, ui_pages=pages, max_goals=5)
    full = PLAN(business_eps=eps, ui_pages=pages, max_goals=99)
    dropped = DROPPED(full, kept)
    assert dropped, "the fixture must actually drop something"
    assert all(d.get("modality") for d in dropped), dropped[:2]
    assert all("::" in KEY(d) and not KEY(d).startswith("None::") for d in dropped), dropped[:2]


def test_the_round_trip_puts_a_dropped_goal_back_in_the_plan_1203km(tmp_path):
    """End to end with #1203kl: drop -> record -> next cycle's plan contains it."""
    eps = [{"method": "GET", "path": "/api/a", "status": "implemented"}]
    pages = [{"name": "p%d" % i, "route": "/p%d" % i} for i in range(20)]
    kept = PLAN(business_eps=eps, ui_pages=pages, max_goals=5)
    dropped = DROPPED(PLAN(business_eps=eps, ui_pages=pages, max_goals=99), kept)
    L = _ledger(tmp_path, {})
    L.note_never_run_1203km(dropped)
    nxt = PLAN(business_eps=eps, ui_pages=pages, max_goals=5,
               replay_first=L.open_failures())
    assert KEY(dropped[0]) in {KEY(g) for g in nxt}, (
        "a goal nobody ran must reach the next plan", [g["name"] for g in nxt])
    assert len(nxt) == len(kept), "the cap is still the cap"


def test_the_caller_records_the_drops_on_the_same_ledger_1203km():
    """The call site, by AST. Four times today a mutation showed the caller can stop using a
    helper while every direct test of it stays green."""
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_squad.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              and f.name == "_run_squad_for_delivery_impl")
    calls = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    note = [c for c in calls if "note_never_run_1203km" in c]
    assert len(note) == 1, note
    assert note[0] == "ledger.note_never_run_1203km(_dropped1203go)", (
        "it must record the CAP's own drop list on the same ledger object #1203kl read from, "
        "or the two halves disagree about what was never run: " + note[0])
    body = ast.unparse(fn)
    i_drop = body.index("_dropped_goals_1203go(")
    i_note = body.index("note_never_run_1203km(")
    assert i_drop < i_note, "the drop list has to exist before it can be recorded"
