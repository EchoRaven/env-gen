r"""#1202ec: kickoff polls for 1200s while every LLM call returns 429.

`terminal_llm_error()` says of itself: "A run loop should poll this and abort instead of
spinning." The orchestrator's coordination loop does (#326). Kickoff runs BEFORE that
loop, and kickoff_driver.py had ZERO references to it -- the one phase ahead of the
poller was the one phase without a poller.

googlemaps-r15, measured from its log:

    03:32:12 [E] LLM.openai: TERMINAL provider error -- not retrying, run should abort
    03:38:41 [E] Kickoff timed out after 1200s ... Missing=[] last_status='validation_failed'

389 seconds waiting on a meeting whose every participant was getting HTTP 429, ending in
a diagnostic that names nothing missing -- because nothing was missing except a provider.
An outage at second 10 would have burned the full 1200s.

Aborting early loses nothing: the return path's deterministic reconcile-and-finalize
needs no LLM.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

SRC_PATH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "runtime" / "kickoff_driver.py")
SRC = SRC_PATH.read_text(encoding="utf-8")


def test_the_wait_loop_polls_the_latched_provider_error():
    """The regression this fixes is literally 'zero references in this file'."""
    assert SRC.count("terminal_llm_error") >= 1
    assert "_provider_terminal_1202ec()" in SRC


def test_the_check_lives_inside_the_poll_loop():
    """Outside the loop it would run once, before the provider had a chance to die."""
    i = SRC.index("while True:")
    j = SRC.index("# Round-8g: derive the meeting's current phase", i)
    assert "_provider_terminal_1202ec()" in SRC[i:j]


def test_the_timeout_check_still_comes_first():
    """8c contract: the timeout overrides any other state-machine decision."""
    loop = SRC[SRC.index("while True:"):]
    assert loop.index("KICKOFF_TIMEOUT_SEC") < loop.index("_provider_terminal_1202ec()")


def test_the_abort_reports_the_provider_reason():
    """`Missing=[] last_status='validation_failed'` named nothing actionable."""
    i = SRC.index("_provider_terminal_1202ec()\n")
    seg = SRC[i:i + SRC[i:].index("provider_terminal\",")]
    assert "_term_1202ec" in seg, "the latched reason must reach the operator"
    assert "terminally unavailable" in seg


def test_it_returns_down_the_reconcile_path():
    """The deterministic reconcile needs no LLM, so early abort loses no work."""
    i = SRC.index("_provider_terminal_1202ec()\n")
    seg = SRC[i:SRC.index("# Round-8g: derive the meeting's current phase", i)]
    assert "_kickoff_fallback_or_reconcile" in seg


def test_the_helper_never_raises():
    i = SRC.index("def _provider_terminal_1202ec")
    seg = SRC[i:SRC.index("\n\n", SRC.index("return \"\"", i))]
    assert "except Exception" in seg
    assert "warn_once_1201" in seg, "a silent guard here disables the check invisibly (#1201)"


def test_a_transient_blip_cannot_trip_it():
    """#1174's grace window is inherited: the reason only latches once quota failure
    has PERSISTED. r16's 57-second outage killed a run at $262 with one gate left."""
    llm = (THIS_DIR.parent / "utils" / "llm.py").read_text(encoding="utf-8")
    i = llm.index("def _is_terminal_llm_error")
    seg = llm[i:llm.index("def terminal_llm_error", i)]
    assert "_QUOTA_FIRST_SEEN_1174" in seg
    assert "return False" in seg, "the first sighting must not latch"


def test_the_helper_reads_through_the_public_accessor():
    """Not the private latch dict -- the grace logic lives behind the accessor."""
    i = SRC.index("def _provider_terminal_1202ec")
    seg = SRC[i:SRC.index("return \"\"", i)]
    assert "terminal_llm_error" in seg
    assert "_TERMINAL_LLM_ERROR" not in seg
