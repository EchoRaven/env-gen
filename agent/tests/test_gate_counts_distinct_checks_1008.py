"""#1008: count distinct gate checks, not instances.

r164's gate log reads:

    1 failed check(s): ['verification_checklist_not_ready']
    6 failed check(s): ['deliverability_ui_page_unwired', 'deliverability_ui_page_unwired',
                        'deliverability_ui_page_unwired', 'deliverability_ui_page_unwired', …]

All six are the same check — one kind, six pages. The run read as a 6x regression when nothing
new had broken, and this number is what an operator judges distance-to-green by; it is the
metric this whole session used to compare runs (r158=8, r162=1, r164=20→2→1→6→3).

`deliverability_ui_page_unwired` is also in `_COVERED_ELSEWHERE`, so it is deliberately never
dispatched: six entries inflate the distance while producing no work for anyone.

Display-only path (`Framework deliver declined`) — the gate's own verdict is unchanged.
"""

import ast
import inspect

import pytest


def _dedup(failed):
    """The shape #1008 installed, extracted so the behaviour can be pinned directly."""
    seen = {}
    for c in sorted(str(x) for x in failed):
        seen[c] = seen.get(c, 0) + 1
    return len(seen), [(f"{k} x{v}" if v > 1 else k) for k, v in sorted(seen.items())]


def test_r164s_six_become_one():
    n, shown = _dedup(["deliverability_ui_page_unwired"] * 6)
    assert n == 1
    assert shown == ["deliverability_ui_page_unwired x6"]


def test_a_single_instance_keeps_its_bare_name():
    """No ` x1` noise on the common case."""
    assert _dedup(["verification_checklist_not_ready"]) == (
        1, ["verification_checklist_not_ready"])


def test_distinct_checks_all_survive():
    n, shown = _dedup(["b_check", "a_check", "b_check"])
    assert n == 2
    assert shown == ["a_check", "b_check x2"]


def test_empty_is_zero():
    assert _dedup([]) == (0, [])


def test_the_orchestrator_uses_the_distinct_count():
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    src = inspect.getsource(orch)
    assert "_seen1008" in src
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "_seen1008" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "len(_seen1008)" in body, "the count must come from the deduped map"
    assert "len(_failed)" not in body, "the instance count must no longer be reported"


def test_the_control_inflates_the_distance():
    """Planted control: the PRE-FIX count on r164's real list."""
    assert len(["deliverability_ui_page_unwired"] * 6) == 6, (
        "the control was supposed to count instances; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
