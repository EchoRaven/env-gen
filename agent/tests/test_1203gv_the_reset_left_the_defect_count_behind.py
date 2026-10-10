"""#1203gv: the per-milestone squad reset left two of fj's fields behind.

The reset block clears `_tu_squad_passed`, `_tu_squad_deferred_since` and `_tu_squad_attempts`
-- the three fields that existed when it was written. #1203fj later added two more at the
escape (`_tu_squad_last_p0_1202ut`, read into `delivery_hold.jsonl`'s `defects=`, and
`_tu_squad_verdict_sig_1202rd`, which gates the relaunch guard) and nothing added them here.

r171 stamped `squad_launched_background ... defects=4` at 14:13:45 and again at 16:35:44, each
the instant a NEW milestone's squad launched -- both 4s are the previous milestone's verdict.
8 of the 49 milestone-first launch records on disk carry a count that cannot be theirs.

The last test is the one that matters: it is an invariant, so the NEXT squad field added to
the delivery path turns this file red instead of leaking across milestones in silence.
"""
import ast
from pathlib import Path

ORCH = (Path(__file__).resolve().parents[1]
        / "env_generator/llm_generator/multi_agent/orchestrator.py")

# `_tu_squad_task` is deliberately not in the reset block: the milestone-start code cancels any
# in-flight squad and drops the handle a few lines below it (#532). Naming it here, with that
# reason, is what keeps the invariant below honest instead of merely passing.
_HANDLED_ELSEWHERE = {"_tu_squad_task"}


def _tree():
    return ast.parse(ORCH.read_text(encoding="utf-8"))


def _reset_block_fields():
    """`self._tu_squad_*` names cleared under the `if not _restored_1202ce:` guard."""
    found = set()
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.If):
            continue
        if "_restored_1202ce" not in ast.unparse(node.test):
            continue
        for st in ast.walk(node):
            if isinstance(st, ast.Assign):
                for tg in st.targets:
                    if isinstance(tg, ast.Attribute) and tg.attr.startswith("_tu_squad"):
                        found.add(tg.attr)
    return found


def _delivery_path_fields():
    """Every `self._tu_squad_*` written inside `_maybe_framework_deliver`."""
    fn = next(n for n in ast.walk(_tree())
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
              and n.name == "_maybe_framework_deliver")
    out = set()
    for st in ast.walk(fn):
        if isinstance(st, ast.Assign):
            for tg in st.targets:
                if isinstance(tg, ast.Attribute) and tg.attr.startswith("_tu_squad"):
                    out.add(tg.attr)
    return out


def test_the_milestone_reset_clears_the_defect_count():
    assert "_tu_squad_last_p0_1202ut" in _reset_block_fields()


def test_the_milestone_reset_clears_the_verdict_signature():
    assert "_tu_squad_verdict_sig_1202rd" in _reset_block_fields()


def test_the_three_original_fields_are_still_cleared():
    reset = _reset_block_fields()
    for f in ("_tu_squad_passed", "_tu_squad_deferred_since", "_tu_squad_attempts"):
        assert f in reset, f


def test_the_reset_lives_behind_the_restore_guard():
    """A restored run must keep its persisted squad state, so the clears stay inside the guard."""
    src = ORCH.read_text(encoding="utf-8")
    for node in ast.walk(_tree()):
        if isinstance(node, ast.If) and "_restored_1202ce" in ast.unparse(node.test):
            cleared = {tg.attr for st in ast.walk(node) if isinstance(st, ast.Assign)
                       for tg in st.targets
                       if isinstance(tg, ast.Attribute) and tg.attr.startswith("_tu_squad")}
            if "_tu_squad_last_p0_1202ut" in cleared:
                assert "not _restored_1202ce" in ast.unparse(node.test)
                return
    raise AssertionError("the reset block was not found behind the restore guard")


def test_every_squad_field_the_delivery_path_sets_is_accounted_for():
    """INVARIANT: a new `_tu_squad_*` field must be reset per milestone or named above.

    This is the test the ticket exists for. #1203fj added two fields to the delivery path and
    nothing carried them into the reset; the leak was invisible until a hold ledger was read
    two weeks later.
    """
    leaked = _delivery_path_fields() - _reset_block_fields() - _HANDLED_ELSEWHERE
    assert not leaked, (
        "these squad fields are written during delivery but never cleared at a milestone "
        "boundary, so they carry the previous milestone's value: %s. Either clear them in the "
        "reset block or add them to _HANDLED_ELSEWHERE with the reason." % sorted(leaked))
