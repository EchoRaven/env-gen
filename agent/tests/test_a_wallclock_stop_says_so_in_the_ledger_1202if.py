r"""#1202if: the run ran out of clock and the ledger said only "failed".

`RunBudget.write` has carried a `reason` since #1202eb — "WHY a run reached a non-`finished`
status" — and the orchestrator's own wrapper dropped the parameter, so every caller that
HAD the sentence could not pass it on.

tiktok-r107, live. Its log carried:

    Run budget exceeded (wall-clock 10811s exceeded cap 10800s) without delivery; aborted
    after 22 coordination ticks. Adjust via ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS.

and its ledger carried `status: "failed", terminal_reason: null` — so reading the record
meant grepping the log to learn the run had simply run out of clock with $510 of its $900
and 22 of its 200 ticks unspent. #1202hv named the two stops it could see (our own cap vs
the provider); a wall-clock stop is neither, and fell through to the generic "failed".
"""
from __future__ import annotations

import ast
import inspect

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget


def test_the_wrapper_forwards_the_reason():
    """Asserted against the REAL signature: the parameter it forwards into must exist."""
    assert "reason" in inspect.signature(RunBudget.write).parameters
    assert "reason" in inspect.signature(Orchestrator._write_run_budget).parameters
    src = inspect.getsource(Orchestrator._write_run_budget)
    call = [n for n in ast.walk(ast.parse(src.lstrip()))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "write"]
    assert call and len(call[0].args) >= 6, "the reason is still dropped on the floor"


def _generate_src():
    return inspect.getsource(Orchestrator.generate) if hasattr(Orchestrator, "generate") \
        else inspect.getsource(Orchestrator)


def test_the_wallclock_site_passes_its_sentence():
    """Asserted on the CALL, over the AST.

    The first draft matched text near the landmark, and the stash line
    `self._budget_stop_1202if = str(budget_exceeded)` satisfied both of its assertions on
    its own — so deleting the reason from the write left it green. The counter-proof found
    that; the call's arity is what actually carries the sentence.
    """
    import textwrap
    src = _generate_src()
    tree = ast.parse(textwrap.dedent(src))
    writes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "_write_run_budget"]
    assert writes, "the wall-clock stop no longer writes a ledger record at all"
    assert any(len(w.args) >= 6 for w in writes), (
        "no _write_run_budget call carries a reason; the sentence dies here")
    assert "_budget_stop_1202if" in src, "the sentence is not stashed for the final write"


def test_the_final_write_no_longer_erases_it():
    src = _generate_src()
    i = src.index("_abort_status_1202hv")
    seg = src[i:src.index("return GenerationResult(", i)]
    assert "_budget_stop_1202if" in seg, (
        "the generic 'failed' still overwrites the only sentence that explained the run")


def test_the_provider_and_own_cap_names_still_win():
    """#1202hv's two names must keep precedence over the new one."""
    src = _generate_src()
    i = src.index("_abort_status_1202hv")
    seg = src[i:src.index("return GenerationResult(", i)]
    a = seg.index("_abort_status_1202hv")
    b = seg.index("_budget_stop_1202if")
    assert a < b, "a provider/own-cap stop must not be relabelled budget_exceeded"


def test_a_clean_finish_is_untouched():
    src = _generate_src()
    i = src.index("_abort_status_1202hv")
    assert '"finished" if success' in src[i:src.index("return GenerationResult(", i)]


def test_the_status_is_read_defensively():
    """It runs inside the ledger's best-effort block; a missing attribute must not be why
    a run record fails to write.

    Landmark-anchored at the FINAL write, not a byte window around the first mention —
    the first mention is the wall-clock stash site, where a plain assignment is correct.
    """
    src = _generate_src()
    i = src.index("_abort_status_1202hv")
    seg = src[i:src.index("return GenerationResult(", i)]
    assert seg.count("getattr(self, \"_budget_stop_1202if\"") >= 2, (
        "the final write must read it defensively in both the status and the reason")


def test_the_ledger_round_trips_a_reason(tmp_path):
    """End to end on the real writer, not a stand-in."""
    import json
    import logging
    b = RunBudget(tmp_path, logging.getLogger("test_1202if"))
    b.write({"max_wall_sec": 10800.0, "max_ticks": 200, "unlimited": False},
            1.0, 10811.0, 22, "budget_exceeded",
            "wall-clock 10811s exceeded cap 10800s")
    u = json.loads((tmp_path / "run_budget.json").read_text())["usage"]
    assert u["status"] == "budget_exceeded"
    assert "wall-clock 10811s" in u["terminal_reason"]
