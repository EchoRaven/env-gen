r"""`BaseAgent(enable_stuck_detection=True)` — the DOCUMENTED default — raised ModuleNotFoundError.

    def _setup_stuck_detector(self) -> None:
        from .stuck_detector import StuckDetector      # utils/stuck_detector.py does not exist

`utils/stuck_detector.py` has never existed — not in the tree, and `git log --all` over
`*stuck_detector*` returns nothing, so it was never deleted either. The hook was written against
a module that was never added. `enable_stuck_detection` defaults to **True**, so constructing a
BaseAgent the documented way blew up in `__init__`; the system only worked because the single
production subclass (multi_agent/agents/base.py:501) passes `False` explicitly.

Every one of the six consumers already guards with `if self._stuck_detector:` — the surface was
written to tolerate the detector's absence and only this one line was not. It now degrades the
same way, and logs once rather than swallowing silently (#634).

Surfaced by the type checker, which could not see it until [tool.pyrefly] gave Pyrefly the two
import roots that main.py puts on sys.path.
"""
import logging

import pytest

from utils.base_agent import BaseAgent


class _Host:
    """Stands in for a half-built BaseAgent: `_logger` is set at line 180, before the call."""

    def __init__(self):
        self._logger = logging.getLogger("test.stuck")
        self._stuck_detector = "sentinel"


# --- the crash ---------------------------------------------------------------------------------

def test_setting_up_the_detector_no_longer_raises():
    host = _Host()
    BaseAgent._setup_stuck_detector(host)      # used to raise ModuleNotFoundError


def test_the_detector_is_left_as_None_not_a_stale_value():
    """The six consumers all test `if self._stuck_detector:` — it must be falsy, not a sentinel."""
    host = _Host()
    BaseAgent._setup_stuck_detector(host)
    assert host._stuck_detector is None


def test_the_default_really_is_True():
    """If this ever flips, the bug above stops being reachable and this file can go."""
    import inspect
    sig = inspect.signature(BaseAgent.__init__)
    assert sig.parameters["enable_stuck_detection"].default is True


def test_the_module_really_is_absent():
    """Pins the premise: if someone adds utils/stuck_detector.py the fallback stops firing."""
    import importlib.util
    assert importlib.util.find_spec("utils.stuck_detector") is None


# --- it degrades loudly, not silently -------------------------------------------------------------

def test_it_says_something_when_the_feature_is_inert(caplog):
    host = _Host()
    with caplog.at_level(logging.DEBUG, logger="test.stuck"):
        BaseAgent._setup_stuck_detector(host)
    assert any("stuck_detector" in r.message for r in caplog.records)


def test_the_message_says_the_watchdogs_are_unaffected(caplog):
    """A reader must not conclude the orchestrator lost its liveness detection too."""
    host = _Host()
    with caplog.at_level(logging.DEBUG, logger="test.stuck"):
        BaseAgent._setup_stuck_detector(host)
    assert any("147/#149" in r.message or "unaffected" in r.message for r in caplog.records)


# --- a real module would still be used ---------------------------------------------------------

def test_only_ImportError_is_absorbed():
    """A detector that exists but throws must NOT be silently swallowed."""
    import inspect
    src = inspect.getsource(BaseAgent._setup_stuck_detector)
    assert "except ImportError:" in src
    assert "except Exception" not in src


def test_the_import_is_still_attempted_first():
    import inspect
    src = inspect.getsource(BaseAgent._setup_stuck_detector)
    assert src.index("from .stuck_detector import StuckDetector") < src.index("except ImportError")
    assert "StuckDetector(" in src, "a present module must still be constructed"


def test_the_history_finding_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(BaseAgent._setup_stuck_detector).replace("#", " ").split())
    assert "NEVER existed" in flat
    assert "DEFAULTS TO TRUE" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
