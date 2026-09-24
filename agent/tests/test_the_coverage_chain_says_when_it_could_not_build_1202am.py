r"""#1202am: the coverage-by-construction chain says so when it cannot build.

Its call site carries a #701 handler whose comment is emphatic: this call is the fix for "the
#1 recurring stuck-blocker — run-12/run-19 wedged 78min here", and #701 exists because the call
had been swallowed whole. But #701 only fires when `complete_coverage_chain` RAISES, and the
function swallowed its own failures and returned `{}` — so the announcement never fired, no
kind="coverage" chain got registered, `business_chain_api_coverage` found the gap this exists to
close, and the run wedged on exactly the blocker being prevented.

Same structural gap #1202ae found in three of my detectors and #1202ag found in
`_coverage_summary`: the inner function swallows, the outer announcement watches for a raise
that never comes. Both of this function's swallows now announce, with different text, because
they mean different things:

    read   the existing chains could not be READ from the hub
    write  the chain could not be REGISTERED — the consequential one

Both still return {}, so no gate behaviour changes; only the silence goes.
"""

import logging
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import message_format as mf  # noqa: E402
from multi_agent.runtime.delivery_gate import complete_coverage_chain  # noqa: E402


class _HubThatCannotRead:
    class registryhub:
        @staticmethod
        def get_verification_chains():
            raise RuntimeError("hub down")


def test_a_hub_that_cannot_be_read_announces(caplog):
    mf._WARNED_1201.clear()
    with caplog.at_level(logging.WARNING):
        assert complete_coverage_chain(_HubThatCannotRead()) == {}
    assert "#701" in caplog.text
    assert "could NOT be read" in caplog.text
    assert "wedge delivery" in caplog.text


def test_the_two_paths_have_different_messages():
    """Reading and writing fail for different reasons and need different next steps."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/delivery_gate.py"
           ).read_text(encoding="utf-8")
    body = src[src.index("def complete_coverage_chain"):]
    body = body[:body.index("\ndef ")]
    assert "complete_coverage_chain.read" in body
    assert "complete_coverage_chain.write" in body
    assert "could NOT be registered" in body


def test_no_hub_at_all_is_still_a_quiet_answer():
    """`hubs` without a registryhub is not a failure — it is 'nothing to do', and answering
    that quietly is correct."""
    mf._WARNED_1201.clear()

    class _Bare:
        pass
    assert complete_coverage_chain(_Bare()) == {}


def test_the_return_value_is_unchanged():
    """The point is the announcement; the gate still receives {}."""
    mf._WARNED_1201.clear()
    assert complete_coverage_chain(_HubThatCannotRead()) == {}
