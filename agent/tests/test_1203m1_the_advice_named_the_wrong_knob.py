r"""#1203m1: the budget abort told the dev to adjust a limit that had not fired.

The suffix was unconditional:

    Run budget exceeded ({budget_exceeded}) without delivery; aborted after {n}
    coordination ticks. Adjust via ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS.

Measured over all 83 occurrences in the 29 root logs that carry one, classified by the
cause string inside the parentheses: 57 spend ceiling, 20 wall-clock, 6 provider credits
exhausted, and **0** coordination ticks -- so `ENVGEN_MAX_TICKS`, printed every single
time, has never once been the limit that bound, and 63/83 ended on advice that omits or
contradicts the real one. r135's cause says "raising ENVGEN_MAX_* will NOT help" and the
same sentence then says "Adjust via ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS".

The decision is executed here, not re-implemented: the if/elif chain is lifted out of
`Orchestrator.run` by AST and run against the four cause shapes the corpus produced.
"""
from __future__ import annotations

import ast
import inspect

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator

# verbatim from the logs named beside each one
CAUSE_SPEND = (
    "this run's OWN spend ceiling stopped it — the provider is fine. Raise "
    "ENVGEN_MAX_SPEND_USD (or unset it) to let a run go further: [BudgetExceeded] run "
    "spend $420.01 reached ENVGEN_MAX_SPEND_USD=$420.00 after 7880 calls")      # r176
CAUSE_PROVIDER = (
    "LLM provider budget/auth exhausted — get a budget increase or a fresh key "
    "(raising ENVGEN_MAX_* will NOT help): [RateLimitError] Error code: 429")     # r135
CAUSE_WALL = "wall-clock 7242s exceeded cap 7200s"                               # r121
CAUSE_TICKS = "coordination ticks 200 reached cap 200"                           # never seen


def _advice_chain() -> ast.If:
    """The real `if/elif` that decides the advice, lifted from the real method."""
    tree = ast.parse(inspect.cleandoc(inspect.getsource(Orchestrator.run)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {t.id for s in node.body if isinstance(s, ast.Assign)
                 for t in s.targets if isinstance(t, ast.Name)}
        if "_advice_1203m1" in names:
            return node
    raise AssertionError("the advice is no longer chosen by a branch at all")


def _advice_for(cause: str) -> str:
    ns = {"_cause_1203m1": cause}
    exec(compile(ast.Module(body=[_advice_chain()], type_ignores=[]),
                 "<chain>", "exec"), ns)
    return ns["_advice_1203m1"]


def test_a_cause_that_names_its_own_knob_gets_no_second_opinion():
    """Spend and provider causes are self-explaining (#1203jt); appending fights them."""
    assert _advice_for(CAUSE_SPEND) == ""
    assert _advice_for(CAUSE_PROVIDER) == ""
    # the specific contradiction that motivated this: the cause SAYS they will not help
    assert "ENVGEN_MAX_" not in _advice_for(CAUSE_PROVIDER)


def test_each_real_limit_is_named_alone():
    assert _advice_for(CAUSE_WALL) == " Adjust via ENVGEN_MAX_WALLCLOCK_SEC."
    assert "TICKS" not in _advice_for(CAUSE_WALL)
    assert _advice_for(CAUSE_TICKS) == " Adjust via ENVGEN_MAX_TICKS."
    assert "WALLCLOCK" not in _advice_for(CAUSE_TICKS)


def test_an_unknown_cause_keeps_both_knobs():
    """#647: no evidence to narrow on, so behaviour is unchanged."""
    got = _advice_for("something nobody has produced yet")
    assert got == " Adjust via ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS."


def test_the_raise_interpolates_the_choice_rather_than_a_literal():
    """#1202w1: the name has to be USED in the message, not merely assigned nearby."""
    tree = ast.parse(inspect.cleandoc(inspect.getsource(Orchestrator.run)))
    raises = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            continue
        for arg in node.exc.args:
            if isinstance(arg, ast.JoinedStr) and any(
                    isinstance(v, ast.Constant) and "Run budget exceeded (" in str(v.value)
                    for v in arg.values):
                raises.append(arg)
    assert len(raises) == 1, "the budget abort message moved or was duplicated"
    msg = raises[0]
    used = {v.value.id for v in msg.values
            if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)}
    assert "_advice_1203m1" in used, "the chosen advice never reaches the message"
    literals = "".join(str(v.value) for v in msg.values if isinstance(v, ast.Constant))
    assert "ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS" not in literals, \
        "both knobs are still hard-coded into every abort"
