r"""#1202v: "EXAMINED 0 OF N TABLES" is said when the state changes, not once per evaluation.

The audit's fallback filter inspects only tables with `status == "defined"`, and the corpus has
1729 implemented against 16 defined — so on a normal run it examines nothing and says so, every
single gate evaluation:

    r22 123   r23 132   r24 130   r25 40   r26 156   r30 213

One unchanging fact, restated up to 213 times. #1202n removed exactly this noise from the heal
declines; the rule is the same here — a state that MOVES is reported again, standing still is
quiet, and the verdict is untouched.

The underlying gap is separately fixed: #1202r moved the real check into the seeder, which runs
at boot with the session open, so it no longer depends on this audit reaching a live database.
"""

import logging
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

import multi_agent.runtime.seed_audit as sa  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reg(n_tables):
    reg = HubRegistry(Path(tempfile.mkdtemp()) / "proj")
    for i in range(n_tables):
        t = "t%d" % i
        reg.schema_hub.register_table(t, schema={"columns": []},
                                      provider="backend", agent="backend")
        # the state the corpus is actually in: implemented, so the filter skips it
        rec = dict(reg.schema_hub.list_tables()[t])
        rec["status"] = "implemented"
        reg.schema_hub._tables.update(
            lambda m, _k=t, _v=rec: m.set(_k, _v, "test"), change_info={"agent": "test"})
    return reg


def test_an_unchanged_state_is_said_once(caplog):
    sa._SAID_0_OF_1202V = None
    reg = _reg(3)
    with caplog.at_level(logging.WARNING, logger=sa.__name__):
        for _ in range(8):
            sa.audit_seed_data(reg, None)
    assert caplog.text.count("EXAMINED 0 OF") == 1


def test_a_changed_table_count_is_reported_again(caplog):
    sa._SAID_0_OF_1202V = None
    with caplog.at_level(logging.WARNING, logger=sa.__name__):
        sa.audit_seed_data(_reg(3), None)
        sa.audit_seed_data(_reg(5), None)
    assert caplog.text.count("EXAMINED 0 OF") == 2


def test_the_verdict_is_unchanged(caplog):
    """Deduping the line must not change what the audit reports."""
    sa._SAID_0_OF_1202V = None
    reg = _reg(3)
    first = sa.audit_seed_data(reg, None).to_dict()
    second = sa.audit_seed_data(reg, None).to_dict()
    assert first == second
    assert first.get("flagged_tables") == []
