r"""#1022b: the delivery gate printed four of N and gave no sign the rest existed.

`#743`'s two gate lines format an UNCAPPED count against a `[:4]` list:

    "#743 %d P0 BUG task(s) are still open at the delivery cut: %s"
        _bugs743["open_p0_bug_count"],                      # 5
        "; ".join(... for b in ...["open_p0_bugs"][:4])     # four titles

netflix r172, 16:03:16, verbatim: *"#743 5 P0 BUG task(s) are still open at the delivery
cut: Canonical runtime port 3000 …; Clean validation backend health check …; Docker database
initialization fails …; Docker validation cannot start …"* — five claimed, four listed, no
marker. Reading the gate across ticks means diffing those lists, and a silent cap makes the
diff wrong: a task that was merely pushed past position four reads as resolved.

Bounding the list is right — the fix is to say so, not to print everything.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import _join_capped_1022


def test_a_truncated_list_declares_the_remainder():
    assert _join_capped_1022(list("abcde"), 5) == "a; b; c; d (+1 more not shown)"


def test_an_untruncated_list_gains_no_noise():
    assert _join_capped_1022(list("abc"), 3) == "a; b; c"


def test_exactly_at_the_cap_is_not_annotated():
    assert _join_capped_1022(list("abcd"), 4) == "a; b; c; d"


def test_an_empty_list_is_empty():
    assert _join_capped_1022([], 0) == ""


@pytest.mark.parametrize("total", [None, "bad", -1])
def test_a_junk_total_never_raises(total):
    """This runs inside the delivery gate's logging path — it must not be able to break a cut."""
    assert isinstance(_join_capped_1022(["a", "b"], total), str)


def _join_calls():
    """Every `_join_capped_1022(...)` call, located by AST position rather than by a byte
    window — a window sized in characters moves the moment a comment above it grows."""
    tree = ast.parse(inspect.getsource(dg))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_join_capped_1022"]


def test_every_bug_list_gate_line_uses_the_capped_join():
    """The FAILED list, the open-P0 list, #1023's stale-P0 list and #1033's contradicted-claim
    list, and #1050's framework-owned-failure list. Growing this number is expected when a gate
    line is added; what must not happen is a NEW list printed with a bare `[:4]`."""
    assert len(_join_calls()) == 5, "a gate line printing a bug list without the capped join"


def test_the_count_and_the_list_come_from_the_same_number():
    """The defect was that they did not: the printed count was uncapped and the list was
    `[:4]`. Each call must be capped by an expression the caller actually reports."""
    # ast.unparse normalises string quotes, so compare against its own spelling.
    totals = {ast.unparse(c.args[1]) for c in _join_calls()}
    assert totals == {"_bugs743['failed_count']", "_bugs743['open_p0_bug_count']",
                      "_bugs743['stale_open_p0_count']",
                      "len(_bugs743['contradicted_tool_claims'])",
                      # #1050's sibling line: a FAILED task whose reason is TRUE.
                      "len(_bugs743['framework_owned_failed'])"}, totals


def test_each_warning_prints_the_count_it_capped_by():
    """Stronger: within each `logger.warning(...)`, the number that bounded the list is one the
    message itself prints. #1023's line prints TWO counts (stale of total), so 'the argument
    immediately before' is too strict — the requirement is that the cap is not a number the
    reader never sees."""
    tree = ast.parse(inspect.getsource(dg))
    checked = 0
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        for k, a in enumerate(call.args):
            if not (isinstance(a, ast.Call)
                    and getattr(a.func, "id", None) == "_join_capped_1022"):
                continue
            cap = ast.unparse(a.args[1])
            printed = {ast.unparse(x) for j, x in enumerate(call.args) if j != k}
            assert cap in printed, (
                f"the list is capped by {cap}, which this message never prints")
            checked += 1
    assert checked == 5, f"expected 5 gate lines, checked {checked}"


def test_no_bare_slice_remains_on_those_lists():
    src = inspect.getsource(dg)
    assert '["failed", [])[:4]' not in src
    assert '["open_p0_bugs", [])[:4]' not in src


def test_the_control_is_the_pre_fix_expression():
    """Planted control: five items, the old formatting, no marker — the exact r172 line."""
    pre_fix = "; ".join(list("abcde")[:4])
    assert pre_fix == "a; b; c; d"
    assert "more" not in pre_fix, "the control was supposed to be silently truncated"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
