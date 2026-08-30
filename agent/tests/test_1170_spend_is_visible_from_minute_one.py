"""#1170: the spend counter had no carrier during the phase that burns money.

#1163 counts every call, but its carrier -- `run_budget.json` -- was first
written at the top of the delivery loop, which starts AFTER design-prep and
kickoff. Those are a run's first ~15 minutes, and they are exactly where a run
can burn money invisibly: r15 spent 2h50m there against a dead account.

Observed live on r16: 50 calls and 961,227 prompt tokens in, and no
run_budget.json existed yet. Same structural gap #1161 fixed for the abort
poll, one file over.
"""
import re
from pathlib import Path

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.multi_agent.runtime import run_budget as rb

SRC = Path(orch.__file__).read_text(encoding="utf-8")


def _early_block():
    i = SRC.index("# #1170: PUBLISH SPEND FROM MINUTE ONE")
    return SRC[i:SRC.index("#1170 early run_budget write skipped", i)]


def test_the_record_is_written_before_the_delivery_loop():
    early = SRC.index("# #1170: PUBLISH SPEND FROM MINUTE ONE")
    loop = SRC.index("while not orchestrator_lane._project_delivered_event.is_set():")
    assert early < loop


def test_it_is_written_inside_run_not_inside_the_loop():
    """`run()` starts before design-prep; the loop starts after kickoff."""
    run_def = SRC.index("    async def run(")
    early = SRC.index("# #1170: PUBLISH SPEND FROM MINUTE ONE")
    assert run_def < early
    assert early < SRC.index("await run_design_prep(")


def test_it_uses_the_same_env_caps_as_the_loop():
    """Two different cap sources would make the early record disagree with the
    later ones for the whole first phase."""
    b = _early_block()
    for k in ("ENVGEN_MAX_WALLCLOCK_SEC", "ENVGEN_MAX_TICKS", "ENVGEN_BUDGET_UNLIMITED"):
        assert k in b, k
    assert "_load_run_budget_caps(" in b


def test_it_marks_the_phase_distinctly():
    """`starting` must not read as `running`, or a stalled design-prep looks like a
    live loop."""
    assert '"starting"' in _early_block()


def test_accounting_can_never_stop_a_run_from_starting():
    b = _early_block()
    assert "try:" in b
    i = SRC.index("#1170 early run_budget write skipped")
    assert "_logger.debug" in SRC[SRC.rindex("except", 0, i):i + 60]


def test_the_carrier_still_carries_the_llm_usage():
    """#1163's field must survive: writing earlier is pointless if the numbers
    are not in the record."""
    src = Path(rb.__file__).read_text(encoding="utf-8")
    assert "llm_usage" in src and '"llm"' in src
