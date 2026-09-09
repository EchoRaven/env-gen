r"""#1202hz: the median is the wrong percentile for a warning.

`_TIME_TO_FIRST_GATE_S_1202GO` gates `_warn_spent_lane_time_1202fw`, whose whole job is
to say "this resume will probably abort before it is ever asked to deliver" BEFORE the
money is spent. Set to the p50 of the measurement in its own comment (p50 8.6 min,
p75 19.6, p90 28.9, max 52.6), it was silent for half the resumes it exists to warn
about — by construction.

tiktok-r106's third resume is the case. It restored to the best snapshot #1202hx could
name, began with 79.6 of its 90 minutes of lane time already spent, and had ~9.45 minutes
left against a 9.00-minute threshold: silent by 27 seconds. It then took 21 minutes to
reach the evaluation and died on NO-CONVERGENCE having spent $70 for nothing.

The loss is asymmetric: a warning that fires needlessly costs a log line; one that stays
silent costs a whole resume.
"""
from __future__ import annotations

import importlib
import os

import pytest

MOD = "env_generator.llm_generator.multi_agent.orchestrator"


def _threshold(env=None):
    """Re-import so the module-level constant is recomputed under `env`."""
    import sys
    old = dict(os.environ)
    try:
        os.environ.pop("ENVGEN_TIME_TO_FIRST_GATE_S", None)
        if env:
            os.environ.update(env)
        sys.modules.pop(MOD, None)
        m = importlib.import_module(MOD)
        return m._TIME_TO_FIRST_GATE_S_1202GO
    finally:
        os.environ.clear()
        os.environ.update(old)
        sys.modules.pop(MOD, None)
        importlib.import_module(MOD)


# The measurement recorded in the constant's own comment, in seconds.
P50, P75, P90, PMAX = 8.6 * 60, 19.6 * 60, 28.9 * 60, 52.6 * 60
# r106 resume 3, measured: 90min cap, 80.5min already spent when the check ran.
R106_LEFT_S = 5400.0 - 4833.0          # 567s = 9.45 min


def test_the_threshold_is_no_longer_the_median():
    assert _threshold() > P50, (
        "at the p50 the warning is silent for half the resumes it exists to warn about")


def test_it_is_at_least_the_p90_of_the_measurement():
    assert _threshold() >= P90


def test_it_does_not_exceed_the_slowest_run_measured():
    """Beyond the max there is no evidence, and a warning that always fires is noise."""
    assert _threshold() <= PMAX


def test_the_r106_resume_would_now_be_warned():
    """The 27 seconds that cost $70."""
    assert R106_LEFT_S <= _threshold(), "this is the resume the fix exists for"


def test_the_r106_resume_was_silent_at_the_old_threshold():
    """Guards the premise: without this, the test above proves nothing."""
    assert R106_LEFT_S > 9 * 60


def test_a_resume_with_ample_budget_is_still_silent():
    """It must stay a targeted warning, not fire on every resume."""
    assert (PMAX + 600) > _threshold()


def test_it_is_tunable():
    assert _threshold({"ENVGEN_TIME_TO_FIRST_GATE_S": "600"}) == 600


def test_a_junk_value_does_not_crash_the_import():
    """A bad env var must not make the orchestrator unimportable."""
    try:
        v = _threshold({"ENVGEN_TIME_TO_FIRST_GATE_S": "nonsense"})
    except ValueError:
        pytest.fail("a junk threshold must not break module import")
    assert isinstance(v, int)


def test_the_comment_still_carries_the_measurement():
    """The percentiles are the evidence for the number; losing them loses the argument."""
    from pathlib import Path
    src = Path(importlib.import_module(MOD).__file__).read_text()
    i = src.index("#1202hz: THE MEDIAN IS THE WRONG PERCENTILE")
    seg = src[:i]
    assert "p50 8.6 min, p75 19.6, p90 28.9, max 52.6" in seg
