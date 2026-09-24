r"""#1201: a best-effort safety mechanism that does not run says so, once.

Three times in one session a mechanism was wired and never reached:

  * the api-module scan hidden behind its own `[:200]` bound (#1199c),
  * `_payload_chars_1199`, reported as landed while it sat outside the directory every
    commit staged — HEAD had zero occurrences while the working tree had three,
  * #1200's leak signal, written inside the try whose opening statement imports
    `_isolation_scoped_tables_from_chains` — an import wrapped in a try precisely because
    it can fail, whose `except Exception: pass` would have taken the new signal with it.

Each was invisible for the same reason: the guard around it ends in `pass`. The guards are
right — a repair must never break the run it repairs — but silence means a mechanism can be
off for a whole run, a cross-user leak reopened, with a clean log. #1102 named it: "a notice
nobody sees is the silence this fix exists to end."

Once per process per site, because these run per tick. Never raises: a reporter that can break
its caller is worse than the silence it replaces.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

import logging  # noqa: E402

from multi_agent.runtime import message_format as mf  # noqa: E402


def _reset():
    mf._WARNED_1201.clear()


def test_it_says_which_mechanism_is_off(caplog):
    _reset()
    with caplog.at_level(logging.WARNING, logger=mf.__name__):
        mf.warn_once_1201("site_a", "the lane-read owner-scoping signal (#1200)",
                          RuntimeError("hub is gone"))
    text = caplog.text
    assert "#1201" in text
    assert "owner-scoping signal (#1200)" in text
    assert "RuntimeError" in text and "hub is gone" in text
    # It must read as "OFF", not as a transient someone can ignore.
    assert "OFF" in text


def test_it_says_it_once_per_site(caplog):
    _reset()
    with caplog.at_level(logging.WARNING, logger=mf.__name__):
        for _ in range(5):
            mf.warn_once_1201("site_b", "a mechanism", ValueError("x"))
    assert caplog.text.count("#1201") == 1


def test_separate_sites_are_reported_separately(caplog):
    _reset()
    with caplog.at_level(logging.WARNING, logger=mf.__name__):
        mf.warn_once_1201("site_c", "mechanism one", ValueError("x"))
        mf.warn_once_1201("site_d", "mechanism two", ValueError("y"))
    assert caplog.text.count("#1201") == 2


def test_the_reporter_cannot_break_its_caller():
    """It runs inside `except` blocks that exist to keep the run alive."""
    _reset()

    class _Hostile:
        def __str__(self):
            raise RuntimeError("even my repr is broken")

    mf.warn_once_1201("site_e", "a mechanism", _Hostile())      # must not raise


def test_the_safety_relevant_guards_are_wired():
    """The three that matter: if either owner-scoping signal or the apis_used reconciliation
    goes quiet, the run must say so — those are the ones whose silence reopens a leak."""
    root = THIS_DIR.parent / "env_generator/llm_generator/multi_agent/runtime"
    for name, needle in (
            ("backend_skeleton.py", "lane_owner_scoped_read_1200"),
            ("frontend_scaffold.py", "reconcile_ui_page_apis_1199"),
            ("scaffolder.py", "lane_read_signal_wiring"),
            ("scaffolder.py", "isolation_scoped_tables"),
            ("scaffolder.py", "reconcile_wiring_1199"),
    ):
        src = (root / name).read_text(encoding="utf-8")
        assert "warn_once_1201" in src, name
        assert needle in src, f"{name}: {needle}"
