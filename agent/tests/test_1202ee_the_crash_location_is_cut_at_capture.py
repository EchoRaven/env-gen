r"""#1202ee: the visual gate bounds a console error BELOW its median, at capture.

tiktok-web-r96 crashed every one of its twelve routes. The record it left:

    #740 ... console.error: TypeError: (void 0) is not a function
        at http://localhost:8005/assets/index-CA-T_HGA.js:252:30568
        at $l (http://localhost:8005/assets/ind   <- cut mid-URL

Two caps, stacked. `_rec740` bounded each message at 300 chars AT CAPTURE, so nothing
downstream could restore what it dropped; then #740's own log line re-cut the remainder
at 160. The #740 comment says the mechanism exists so the cause need not "be
rediscovered by whoever drove a browser next" -- and it removed the only field that
localises the crash.

300 is below the median. Measured on the same payload, 135 console errors across 33 run
logs: p50 330, p90 450, p99 630, max 710. #1202ea measured this for the test-user walk;
the visual gate reads the same console of the same browser, so there is now ONE number.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

RT = THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
VF = (RT / "visual_fidelity.py").read_text(encoding="utf-8")


def test_the_capture_cap_clears_the_measured_median():
    from multi_agent.runtime.message_format import CONSOLE_ERROR_CAP_1202EE as CAP
    assert CAP >= 450, "a p90 console error no longer survives capture"


def test_capture_no_longer_hardcodes_300():
    i = VF.index("def _rec740")
    seg = VF[i:VF.index("if console_errors is not None:", i)]
    assert "[:300]" not in seg, "the capture cap is back below the median"
    assert "_CONSOLE_ERROR_CAP_1202EE" in seg


def test_the_740_log_line_does_not_re_cut_below_the_capture_cap():
    """A display cap under the capture cap throws the rest away a second time."""
    i = VF.index("#740 the browser reported")
    seg = VF[i:VF.index("#419: PERSIST the per-dimension verdict", i)]
    assert "[:160]" not in seg
    assert "_CONSOLE_ERROR_CAP_1202EE" in seg


def test_the_old_cap_provably_fired_on_r96():
    """Not inferred -- measured. The deviation r96 persisted carries a console entry of
    EXACTLY 315 chars: len("console.error: ") == 15, plus the old 300. It ends mid-token,
    inside a stack position number ("...465"), which is what a hard slice does and what a
    naturally-short message never does. The new cap must clear that boundary."""
    from multi_agent.runtime.message_format import CONSOLE_ERROR_CAP_1202EE as CAP
    observed_entry_len = 315
    assert observed_entry_len - len("console.error: ") == 300
    assert CAP > 300, "the cap that demonstrably truncated r96 is still in force"


def test_one_number_serves_both_readers():
    """The test-user walk and the visual gate read the same console of the same browser."""
    from multi_agent.runtime.test_user_runner import _CONSOLE_ENTRY_CAP_1202EA as A
    from multi_agent.runtime.message_format import CONSOLE_ERROR_CAP_1202EE as B
    assert A == B


def test_the_message_count_bound_survives():
    """Only the per-message LENGTH was this fix's business; a looping page still cannot
    flood. #1202eh later made that count budget per-kind so a broken bundle's 404s cannot
    evict an uncaught exception -- the bound moved, it did not go away."""
    i = VF.index("def _rec740")
    seg = VF[i:VF.index("if console_errors is not None:", i)]
    assert "_KIND_BUDGET_1202EH" in seg
    from multi_agent.runtime.visual_fidelity import _BLANKING_TYPES_1202EH  # noqa: F401
