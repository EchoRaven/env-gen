r"""#792: a delivery GATE that cannot load must not read as a delivery gate that PASSED.

The consequence sweep, continued past #790 (the delivery gate itself) and #791 (the audit that
feeds it) into the remaining gate/audit modules:

    backend_audit.py  coverage_audit.py  completeness_audit.py
    page_build_gate.py  user_gates.py  test_user_validation.py     -> 0 permissive defaults, clean
    visual_fidelity.py                                             -> 1
    deliverability.py                                              -> 7, on the RELEASE path

`deliverability.py`'s blocker gates are each two `try`s — import the audit, then run it — and both
handlers returned a bare `[]`:

    try:
        from .backend_audit import stub_handler_blockers
    except Exception:
        return []                      # the ENTIRE gate disappears on an ImportError
    try:
        return stub_handler_blockers(...)
    except Exception:
        return []                      # ...or on any fault inside it

So #154's bare-fetch gate, #173's stub-handler gate and #175's invented-field gate can each vanish
without a word, and the release path reads "no blockers". **This is #789's write guard again** — a
whole enforcer lost to an import — now on three delivery gates instead of one write guard.

The permissive default is KEPT (a broken audit must not wedge every release). What changes is that
it stops being indistinguishable from a clean scan. Reuses this module's own say-once memory
(`_SAID_700`, #760/#762) rather than inventing a third mechanism, which also means
`reset_said_700()` already clears it — the module-state-outlives-a-test trap #762 was written for.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dv


@pytest.fixture(autouse=True)
def _clean():
    dv.reset_said_700()
    yield
    dv.reset_said_700()


def test_a_healthy_process_records_nothing():
    """Non-vacuity: silent when everything works, or the signal is noise and gets ignored."""
    assert dv.gates_absent_792() == []


def test_a_missing_gate_is_recorded():
    dv._gate_absent_792("_stub_handler_blockers", ImportError("no module"), "import")
    got = dv.gates_absent_792()
    assert got and "_stub_handler_blockers" in got[0]
    assert "import" in got[0] and "ImportError" in got[0]


def test_the_warning_says_it_is_not_a_clean_result(caplog):
    with caplog.at_level(logging.WARNING):
        dv._gate_absent_792("_bare_fetch_blockers", RuntimeError("boom"), "run")
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "DELIVERY GATE DID NOT RUN" in msg
    assert "NOT" in msg and "evidence the app is clean" in msg


def test_import_and_run_stages_are_distinguished():
    """'the audit is missing' and 'the audit crashed' need different fixes, so they are not
    collapsed into one message."""
    dv._gate_absent_792("_bare_fetch_blockers", ImportError("x"), "import")
    dv._gate_absent_792("_bare_fetch_blockers", RuntimeError("y"), "run")
    assert len(dv.gates_absent_792()) == 2


def test_it_is_said_once_per_gate_per_stage(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            dv._gate_absent_792("_bare_fetch_blockers", RuntimeError("y"), "run")
    assert len(dv.gates_absent_792()) == 1
    assert sum("DELIVERY GATE DID NOT RUN" in r.getMessage() for r in caplog.records) == 1


def test_the_say_once_memory_is_cleared_by_the_existing_reset():
    """#762's whole point: module state outlives a test, so whichever test ran first would
    silence every later one. Reusing `_SAID_700` means the existing reset already covers this."""
    dv._gate_absent_792("_bare_fetch_blockers", RuntimeError("y"), "run")
    assert dv.gates_absent_792()
    dv.reset_said_700()
    assert dv.gates_absent_792() == []


def test_the_reporter_cannot_break_the_release_path():
    class _Unprintable(Exception):
        def __str__(self):
            raise ValueError("even the message explodes")
    dv._gate_absent_792("x", _Unprintable(), "run")          # must not raise


def test_every_vanishing_gate_is_wired():
    import inspect
    src = inspect.getsource(dv)
    for gate in ("_ui_page_wiring_blockers", "_bare_fetch_blockers",
                 "_stub_handler_blockers", "_invented_field_blockers"):
        assert f'_gate_absent_792("{gate}"' in src, gate


def test_the_permissive_default_is_unchanged():
    """The trade is deliberate and must survive: a broken audit cannot wedge every release."""
    import inspect
    src = inspect.getsource(dv._stub_handler_blockers)
    assert src.count("return []") >= 2, "the gate must still fail OPEN"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
