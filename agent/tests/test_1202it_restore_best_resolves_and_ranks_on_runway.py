"""#1202it / #1202iu: starting a resume from the BEST state, not the newest one.

Two halves of the same gap. `best_snapshot_1202hx` already computed which snapshot was
worth restarting from -- and it was only ever PRINTED, so the one step that decides whether
a resume starts ahead or behind was the one step left manual (#1202it). And its ranking
left out `budget_left_s`, the field its own call site calls "the quality that decides
whether restoring is ahead or behind" (#1202iu).
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.run_snapshot import (  # noqa: E402
    best_snapshot_1202hx)


def _snap(name, *, epoch, budget=None, screens_pass=0, med=0.36, failed=("business_chain",),
          judgments=2):
    return {"name": name, "epoch": epoch, "budget_left_s": budget,
            "screens_pass": screens_pass, "screens_total": 9, "visual_med": med,
            "fwval_failed": list(failed), "judgments": judgments}


def test_runway_beats_recency_when_the_state_is_the_same():
    """r109's real snapshots, reduced to the two that matter. `135712-interval-gate5` and
    `125512-interval-t14` hold the SAME 0/9 screens, the SAME 0.36 median and the SAME
    single blocking check. One is 30 minutes short of the wall; the other is 32 minutes
    past it and $181 further spent. Ranking on recency picked the dead one."""
    snaps = [_snap("t14", epoch=1000.0, budget=+30 * 60),
             _snap("gate5", epoch=2000.0, budget=-32 * 60)]
    assert best_snapshot_1202hx(snaps) == "t14"


def test_quality_still_outranks_runway():
    """#1202iu inserted budget BELOW the quality terms, not above them. A snapshot with
    more screens over threshold is still the better restore point even with less runway --
    otherwise the fix would trade the thing being optimised for the budget to optimise it
    in."""
    snaps = [_snap("poor_but_fresh", epoch=1000.0, budget=+60 * 60, screens_pass=1),
             _snap("good_but_tight", epoch=1000.0, budget=+1 * 60, screens_pass=4)]
    assert best_snapshot_1202hx(snaps) == "good_but_tight"


def test_an_unmeasured_budget_is_not_read_as_zero_left():
    """`None` means not measured. It must not beat a measured positive, and must not lose
    to a measured negative -- reading a missing value as a meaningful one is the mistake
    #902 (blank route as site root), #907 (empty cache as empty tree) and #566y (empty
    child_meta as True) all were."""
    assert best_snapshot_1202hx(
        [_snap("unknown", epoch=2000.0, budget=None),
         _snap("has_runway", epoch=1000.0, budget=+10 * 60)]) == "has_runway"
    assert best_snapshot_1202hx(
        [_snap("unknown", epoch=1000.0, budget=None),
         _snap("past_the_wall", epoch=2000.0, budget=-10 * 60)]) == "unknown"


def test_recency_is_still_the_final_tiebreaker():
    snaps = [_snap("older", epoch=1000.0, budget=+10 * 60),
             _snap("newer", epoch=2000.0, budget=+10 * 60)]
    assert best_snapshot_1202hx(snaps) == "newer"


def test_a_snapshot_that_scored_nothing_is_never_best():
    """#1202di's trap, unchanged by #1202iu: all the runway in the world is worthless on a
    run that has never photographed a screen."""
    snaps = [_snap("never_scored", epoch=2000.0, budget=+90 * 60, judgments=0),
             _snap("scored", epoch=1000.0, budget=-90 * 60, judgments=3)]
    assert best_snapshot_1202hx(snaps) == "scored"


def test_the_cli_accepts_the_literal_best(tmp_path):
    """#1202it. Asserted against main.py's SOURCE reaching `best_snapshot_1202hx` from the
    restore branch -- the branch itself exits the process, so it cannot be called here, and
    a test that only checked the listing would pass with the restore half never wired."""
    import ast
    src = (_AGENT / "env_generator" / "llm_generator" / "main.py").read_text()
    tree = ast.parse(src)
    # find the comparison against the literal "best" and prove a best_snapshot_1202hx call
    # lives in the same branch, rather than matching either one anywhere in the file.
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.dump(node.test)
        if "'best'" not in test_src and '"best"' not in test_src:
            continue
        calls = [n.func for n in ast.walk(node) if isinstance(n, ast.Call)]
        names = {getattr(c, "id", None) or getattr(c, "attr", None) for c in calls}
        if "best_snapshot_1202hx" in names and "list_snapshots" in names:
            found = True
    assert found, "no `== 'best'` branch resolves through best_snapshot_1202hx"
