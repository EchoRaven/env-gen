r"""#1202ik: the other half of #1202if.

The no-convergence abort logs a sentence with everything in it —

    FAIL-FAST: aborting the run early — delivery never SUCCEEDED in 243min of lane time
    since the contract built (now failing ['business_chain_failing', ...])

— and then wrote `status: "stuck_abort"` with no reason, which the final ledger write
turned into the generic `status: "failed", terminal_reason: null`. tiktok-r107's fourth
resume looked identical on disk to a run that simply stopped, and the one number that
explained it (243 minutes against a 240-minute cap) lived only in the log.

#1202if fixed the wall-clock/tick path. This one kept the habit, and it also shared that
path's status name: a cap says "raise it or accept it", a no-convergence abort says
"nothing converged in the time you gave it" — opposite advice from one word.
"""
from __future__ import annotations

import ast
import inspect

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator

STUCK = ("delivery never SUCCEEDED in 243min of lane time since the contract built "
         "(now failing ['business_chain_failing'])")
CAP = "wall-clock 10876s exceeded cap 10800s"


class _O:
    _stop_status_1202ik = Orchestrator._stop_status_1202ik

    def __init__(self, reason):
        self._budget_stop_1202if = reason


def test_a_no_convergence_stop_is_named_stuck():
    assert _O(STUCK)._stop_status_1202ik() == "stuck_abort"


def test_a_cap_stop_keeps_its_own_name():
    assert _O(CAP)._stop_status_1202ik() == "budget_exceeded"


def test_a_missing_reason_degrades_to_the_cap_name():
    o = _O("")
    assert o._stop_status_1202ik() == "budget_exceeded"


def test_it_never_raises():
    for junk in (None, 123, [], {}):
        assert _O(junk)._stop_status_1202ik() in ("stuck_abort", "budget_exceeded")


def _generate_src():
    return inspect.getsource(Orchestrator)


def test_the_stuck_site_passes_its_sentence():
    """Found over the AST of the whole class, by the call's own arguments.

    Two landmark attempts failed first: `'"stuck_abort")'` is a spelling this fix removed
    by adding the reason, and slicing from the log line starts mid-f-string, which will not
    parse. The call is identified by what it IS — a `_write_run_budget` whose status
    argument is the constant "stuck_abort" — which no edit to the prose can break.
    """
    import textwrap
    tree = ast.parse(textwrap.dedent(_generate_src()))
    stuck = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_write_run_budget"
             and any(isinstance(a, ast.Constant) and a.value == "stuck_abort"
                     for a in n.args)]
    assert stuck, "the no-convergence abort no longer writes a ledger record"
    assert any(len(c.args) >= 6 for c in stuck), "the stuck write still carries no reason"
    assert "_budget_stop_1202if" in _generate_src(), (
        "the sentence is not stashed for the final write")


def test_the_final_write_distinguishes_the_two_stops():
    src = _generate_src()
    i = src.index("_abort_status_1202hv(_abort_1202eb)")
    seg = src[i:src.index("return GenerationResult(", i)]
    assert "_stop_status_1202ik" in seg, "both stops still share one name"


def test_the_cap_name_is_not_hardcoded_at_the_final_write():
    """A literal there would re-merge the two stops the moment this is edited."""
    src = _generate_src()
    i = src.index("_abort_status_1202hv(_abort_1202eb)")
    seg = src[i:src.index("return GenerationResult(", i)]
    assert '"budget_exceeded"\n' not in seg
