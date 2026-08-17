r"""#891: a stage says so when its input never arrived.

The last of the four generalisable fixes. This pipeline is ~10 stages where each stage's output is
the next stage's only input, and **no stage validated its input** — so one empty output propagates
and surfaces far from the cause.

Measured across 151 runs, a later stage ran while an earlier one produced nothing:

    backend  ran, DDL empty      12 runs   <- 8%; the app has no tables, so every query fails at
    seed     ran, DDL empty       5 runs      RUNTIME, five links from the cause
    frontend ran, DDL empty       4 runs
    capture  ran, DDL empty       2 runs
    capture  ran, frontend empty  1 run    <- r32, the blank-capture class (#75a/#737)

#864 added this check at one boundary and is the only reason that failure is legible. This
generalises the shape instead of hand-writing it again.

★ **It reports; it does not abort** — the fifth time this session that decision came out the same
way, for the reason #876 finally made precise: the run is usually already lost, and what was
missing was never the abort, it was the sentence naming which stage did not deliver.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import stage_contract as sc


@pytest.fixture(autouse=True)
def _reset():
    sc.reset_said_891()
    yield
    sc.reset_said_891()


def test_a_present_input_is_silent(caplog):
    with caplog.at_level(logging.ERROR):
        assert sc.require_stage_input_891("backend", "DDL", "db", present=["01_init.sql"]) is True
    assert not caplog.records


@pytest.mark.parametrize("absent", [None, False, 0, [], {}, "", (), set()])
def test_every_empty_shape_is_absent(absent):
    assert sc.require_stage_input_891("backend", "DDL", "db", present=absent) is False


def test_a_callable_is_evaluated():
    assert sc.require_stage_input_891("s", "n", "p", present=lambda: ["x"]) is True
    sc.reset_said_891()
    assert sc.require_stage_input_891("s", "n", "p", present=lambda: []) is False


def test_a_check_that_raises_is_absent_and_says_so(caplog):
    """★ #873's rule: 'cannot confirm' and 'confirmed empty' must not collapse. #877 is what
    happens when they do — so the raise is named in the message rather than swallowed into a
    plain absence."""
    with caplog.at_level(logging.ERROR):
        ok = sc.require_stage_input_891(
            "s", "n", "p", present=lambda: (_ for _ in ()).throw(OSError("boom")))
    assert ok is False
    assert "the check itself failed" in caplog.text and "OSError" in caplog.text


def test_the_message_names_the_producer_and_the_consequence(caplog):
    """'DDL missing' is a symptom; 'the database scaffold should have produced it, and what
    follows is a consequence' is what stops the next reader chasing the wrong stage."""
    with caplog.at_level(logging.ERROR):
        sc.require_stage_input_891("backend skeleton", "app/database/init/*.sql",
                                   "the database scaffold", present=[])
    assert "the database scaffold should have produced" in caplog.text
    assert "CONSEQUENCE, not the cause" in caplog.text


def test_it_says_once_per_boundary(caplog):
    """These fire on a broken run and a broken run ticks many times (#845)."""
    with caplog.at_level(logging.ERROR):
        for _ in range(4):
            sc.require_stage_input_891("backend", "DDL", "db", present=[])
        sc.require_stage_input_891("capture", "jsx", "frontend", present=[])
    assert sum("STAGE INPUT MISSING" in r.getMessage() for r in caplog.records) == 2


def test_it_never_raises():
    """An observability call that takes down the stage it observes manufactures the failure it
    reports. A progress sink that throws must not escape either."""
    class _Boom:
        def emit(self, *a, **k):
            raise RuntimeError("sink down")
    assert sc.require_stage_input_891("s", "n", "p", present=[],
                                      progress=_Boom(), event_type="x") is False


def test_the_output_mirror_reports_its_own_stage(caplog):
    with caplog.at_level(logging.ERROR):
        sc.require_stage_output_891("database scaffold", "any registered table", present=False)
    assert "database scaffold" in caplog.text


# --- the three boundaries it is wired at -------------------------------------------------------

def test_the_ddl_producer_reports_a_zero_table_schema():
    """`write_database_scaffold` writes 01_init.sql either way, so nothing downstream could tell
    'the contract had no tables' from 'the contract had tables'."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import database_scaffold as ds
    src = inspect.getsource(ds.write_database_scaffold)
    assert "require_stage_output_891" in src
    assert "ZERO tables" in src


def test_the_backend_requires_the_ddl():
    """The first consumer, and the 12-run boundary."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    src = inspect.getsource(scaffolder)
    assert "require_stage_input_891" in src
    assert "app/database/init/*.sql" in src


def test_the_capture_requires_the_frontend():
    """r32's boundary — a capture with no frontend source produces a blank PNG, and #737 records
    a blank capture being consumed as evidence of stability."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "require_stage_input_891" in src
    assert "the frontend scaffold" in src


def test_none_of_the_three_abort():
    """★ Reported, not fatal — pinned so a later change to that is deliberate."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import (
        database_scaffold as ds, scaffolder, visual_fidelity as vf)
    for src in (inspect.getsource(ds.write_database_scaffold),
                inspect.getsource(vf.run_visual_fidelity)):
        i = src.index("891")
        assert "raise" not in src[max(0, i - 400):i + 400]
    assert "require_stage_input_891" in inspect.getsource(scaffolder)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
