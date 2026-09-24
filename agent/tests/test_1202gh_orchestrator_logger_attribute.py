"""#1202gh — the Orchestrator's logger is `_logger`, and a fix that misses it ships dead.

#1202fw exists to say, at resume time, that a run has already spent its whole
no-convergence budget and this attempt can only abort at tick 1. It never printed once. It
called `self.logger`, and the attribute is `self._logger` — 144 uses to that one typo — so
every call raised AttributeError.

tiktok-r97's sixth resume is what that cost: $17.84 to learn at tick 1 exactly what the
warning was written to say beforehand.

The one thing that worked was the audible guard. #1202fw's except routes through
warn_once_1201, so the log carried "the resume-cost warning (#1202fw) ... did NOT run this
process: AttributeError". Written as `except: pass` — the shape this batch has been removing
— a fix broken on its first line would have stayed silent for the life of the file.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

ORCH = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")


def test_nothing_calls_the_attribute_that_does_not_exist():
    hits = [m.start() for m in re.finditer(r"\bself\.logger\b", ORCH)]
    if hits:
        lines = sorted({ORCH[:h].count(chr(10)) + 1 for h in hits})
        raise AssertionError(
            "orchestrator.py has no `logger` attribute — it is `_logger` (144 uses). "
            f"self.logger at line(s) {lines} raises AttributeError at runtime, and a "
            "guarded caller turns that into a mechanism that silently never runs (#1202fw).")


def test_the_attribute_really_is_underscored():
    """Pin the premise rather than trusting the count in this docstring."""
    assert len(re.findall(r"\bself\._logger\b", ORCH)) > 50


def test_the_resume_cost_warning_uses_it():
    i = ORCH.index("#1202fw this run has ALREADY spent")
    call = ORCH.rindex("self.", 0, i)
    assert ORCH[call:call + len("self._logger")] == "self._logger", ORCH[call:i][:120]


def test_its_guard_is_still_audible():
    """The only reason this bug was findable at all."""
    i = ORCH.index("orchestrator.spent_lane_time_1202fw")
    assert "warn_once_1201" in ORCH[ORCH.rindex("except", 0, i):i]
