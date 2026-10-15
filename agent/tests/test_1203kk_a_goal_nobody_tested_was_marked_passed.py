"""#1203kk: a squad goal whose own agent timed out was recorded as passed.

The per-goal cycle verdict accepted "ANY agent in this modality finished" as a fallback. The
ledger exists to re-test previously-FAILED flows first (design §3.5), so a goal marked passed
is never an open failure and never gets replayed — a flow that was never tested stayed
permanently recorded as fine.

Measured over the modern era's 35 squad ledgers (407 agent rows): 176 agents did not finish
and EVERY one of them timed out — `spawned 183 = completed 105 + timed_out 78 + failed 0`,
each row reading "did not finish within 300s". Of those, 140 across 34 of the 35 runs sat in a
modality where a sibling DID finish: r181 6, r178 6, r177 6, r185 5, r184 5, r180 5, mostly
`page_*` browser goals.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    goal_agent_finished_1203kk as FINISHED, FailureLedger)

# r174's real shape: one page goal timed out while its siblings finished.
_MATES = [
    {"name": "page_dm_inbox_page", "completed": True},
    {"name": "page_explore_page", "completed": True},
    {"name": "page_post_detail_page", "completed": False,
     "error": "did not finish within 300s"},
]


def test_a_timed_out_goal_is_not_passed_by_its_siblings_1203kk():
    assert FINISHED({"name": "page_post_detail_page"}, _MATES) is False, (
        "this is the whole defect: 140 corpus goals were recorded passed this way")


def test_a_goal_whose_own_agent_finished_still_passes_1203kk():
    for n in ("page_dm_inbox_page", "page_explore_page"):
        assert FINISHED({"name": n}, _MATES) is True, n


def test_the_old_fallback_would_have_disagreed_1203kk():
    """NON-VACUITY: the fixture must be one the old rule got wrong, or the test proves
    nothing. Old rule = any agent in the modality finished."""
    old = any(a.get("completed") for a in _MATES)
    new = FINISHED({"name": "page_post_detail_page"}, _MATES)
    assert old is True and new is False, (old, new)


def test_a_nameless_goal_keeps_the_modality_fallback_1203kk():
    """The one case with no key to match on: the agent row's name is a positional default
    (`goal_3`), so comparing them would falsely fail a goal that actually ran."""
    assert FINISHED({"name": ""}, _MATES) is True
    assert FINISHED({}, _MATES) is True
    assert FINISHED({"name": None}, _MATES) is True


def test_whitespace_does_not_break_the_match_1203kk():
    assert FINISHED({"name": " page_explore_page "}, _MATES) is True
    assert FINISHED({"name": "page_explore_page"},
                    [{"name": " page_explore_page ", "completed": True}]) is True


def test_no_agent_row_for_the_goal_means_not_finished_1203kk():
    """A goal dropped by the cap (#1203go) never ran, so it must land in the ledger as an open
    failure and be replayed first — which is #1203ki's carried-over half."""
    assert FINISHED({"name": "page_never_spawned"}, _MATES) is False


def test_junk_cannot_break_it_1203kk():
    for goal, mates in ((None, None), ({}, None), ({"name": "x"}, [None, 7, "s"]),
                        (7, _MATES), ("x", _MATES)):
        assert FINISHED(goal, mates) in (True, False), (goal, mates)


def test_a_false_pass_would_have_kept_the_goal_out_of_the_replay_set_1203kk(tmp_path):
    """The consequence, end to end through the ledger: a goal recorded passed is not an open
    failure, so `order_replay_first` never prioritises it."""
    import json
    led = tmp_path / "failure_ledger.json"
    led.write_text(json.dumps({"cycle": 0, "goals": {}}), encoding="utf-8")
    L = FailureLedger(led)
    goals = [{"modality": "browser", "name": n}
             for n in ("page_dm_inbox_page", "page_post_detail_page")]
    L.record_cycle([{"modality": g["modality"], "name": g["name"],
                     "passed": FINISHED(g, _MATES), "defects": 0} for g in goals])
    assert L.open_failures() == ["browser::page_post_detail_page"], L.open_failures()
    ordered = [g["name"] for g in L.order_replay_first(goals)]
    assert ordered[0] == "page_post_detail_page", (
        "the untested goal must be re-tested FIRST next cycle (design §3.5)", ordered)


def test_the_cycle_loop_actually_uses_the_helper_1203kk():
    """Found by mutation, for the third time today: every test above drives the helper
    DIRECTLY, so the call site could revert to the modality fallback with the suite green.

    Asked of the AST — the loop that builds `cycle_results` must get `completed` from the
    helper, and must not re-derive it from the modality rows.
    """
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_squad.py").read_text("utf-8")
    tree = ast.parse(src)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and "cycle_results.append" in ast.unparse(n)]
    assert len(loops) == 1, [ast.unparse(l.target) for l in loops]
    body = ast.unparse(loops[0])
    assigns = [n for n in ast.walk(loops[0]) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "completed" for t in n.targets)]
    assert len(assigns) == 1, [ast.unparse(a) for a in assigns]
    value = ast.unparse(assigns[0].value)
    assert value.startswith("goal_agent_finished_1203kk("), (
        "the per-goal verdict must come from the helper, or the modality fallback can return "
        "silently: " + value)
    assert "passed" in body and "mod_p0 == 0" in body, (
        "the P0 half of the verdict must stay — #1203kk narrows COMPLETION, not defects")
