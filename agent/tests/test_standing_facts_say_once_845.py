r"""#845: I shipped two warnings that fire on essentially every run — the failure I corrected in #793.

Measured across the corpus after shipping #842 and #844:

    #842 unstaged asset class    150/150  (100%)
    #844 unseeded entity kind    141/150  ( 94%)
    #823 imageless unreachable    22/150  ( 14%)
    -> 141 of 150 runs trip at least two; 22 trip all three

★ Two of the three fire on **essentially every run**, because the gaps they name — no avatar
staged, no game data — are properties of how this app is STAGED, not per-run defects.
`validate_delivery_gate` runs at every tick, so each would emit dozens of identical warnings per
run.

That is precisely #793's correction, which I wrote: *"a line that fires on healthy runs gets
filtered out, which is how a signal becomes decoration."* I then shipped two of them three items
later. The standing fact belongs in the record (EXPERIMENTS items 164/165) and in **one** warning
per process.

Reused shape rather than a new mechanism (#792's lesson): a module-level set with the reset
#762 requires, because module state outlives a test and whichever test runs first would otherwise
silence every later one.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


@pytest.fixture(autouse=True)
def _clean():
    dg.reset_said_845()
    yield
    dg.reset_said_845()


def test_a_standing_fact_is_logged_once_across_ticks(caplog):
    """The gate runs at every tick; the fact does not change between them."""
    log = logging.getLogger("gate")
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            dg._say_once_845("842", log, "avatar not staged")
    assert sum("avatar not staged" in r.getMessage() for r in caplog.records) == 1


def test_distinct_facts_each_get_their_own_line(caplog):
    """Say-once must not collapse two different findings into one."""
    log = logging.getLogger("gate")
    with caplog.at_level(logging.WARNING):
        dg._say_once_845("842", log, "asset gap")
        dg._say_once_845("844", log, "kind gap")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "asset gap" in msgs and "kind gap" in msgs


def test_the_reset_restores_it_for_a_new_run(caplog):
    log = logging.getLogger("gate")
    with caplog.at_level(logging.WARNING):
        dg._say_once_845("842", log, "x")
        dg.reset_said_845()
        dg._say_once_845("842", log, "x")
    assert sum("x" == r.getMessage() for r in caplog.records) == 2


def test_it_never_raises():
    """It runs on the release path, inside the reporting of another finding."""
    class _Bad:
        def warning(self, *a, **k):
            raise RuntimeError("logger exploded")
    dg._say_once_845("k", _Bad(), "m")


def test_all_three_standing_reports_are_routed_through_it():
    import inspect
    src = inspect.getsource(dg.validate_delivery_gate)
    for tag in ("842", "844", "823"):
        assert f'_say_once_845("{tag}", logger,' in src, tag


def test_the_per_tick_reporters_were_not_touched():
    """#790's DELIVERY CHECK DID NOT RUN is per-tick by design — it reports a transient event, not
    a standing fact, and collapsing it would hide a check that failed on one tick only."""
    import inspect
    src = inspect.getsource(dg)
    i = src.index("DELIVERY CHECK DID NOT RUN")
    assert "_say_once_845" not in src[max(0, i - 400):i]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
