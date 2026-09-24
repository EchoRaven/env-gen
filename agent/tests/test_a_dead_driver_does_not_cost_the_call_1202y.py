r"""#1202y: the call that DISCOVERS a dead driver is retried, not lost.

#1198 made a dead driver recoverable and r30 proved it — the driver died twice, was rebuilt
twice, zero permanent failures. What it does not do is save the call that trips over the death:
`ensure_browser` runs at the START of a tool, so the in-flight goto/click still fails and the
lane still writes a FAIL record about it. r32 measured the residue — two rebuilds, and two
failures that reached the verifier anyway:

    21:39  browser_click FAILED ... Connection closed while reading from the driver
    00:24  browser_navigate FAILED (113778ms) ... Connection closed while reading from the driver

Both are the probe, not the product. Both became prose in a check record that a human then has
to triage — and triaging those is exactly the 45% of netflix-era UI failures that turned out to
be probe artifacts rather than defects. One retry after the rebuild makes the death invisible
where it belongs.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from tools.browser._manager import is_dead_driver_error_1202y  # noqa: E402


def test_it_recognises_the_shapes_the_corpus_produced():
    for msg in ("Page.goto: Connection closed while reading from the driver",
                "Page.click: Connection closed while reading from the driver",
                "Target page, context or browser has been closed",
                "Browser has been closed",
                "Target closed"):
        assert is_dead_driver_error_1202y(Exception(msg)), msg


def test_it_does_not_claim_ordinary_failures():
    """A dead driver is not a missing element, a timeout, or a refused origin — those must
    keep their own handling."""
    for msg in ("Timeout 30000ms exceeded",
                "net::ERR_CONNECTION_REFUSED at http://localhost:8033/",
                "strict mode violation: locator resolved to 3 elements",
                "Element is not visible",
                "net::ERR_ABORTED"):
        assert not is_dead_driver_error_1202y(Exception(msg)), msg


def test_it_never_raises_on_a_hostile_exception():
    class _Bad(Exception):
        def __str__(self): raise RuntimeError("no string for you")
    assert is_dead_driver_error_1202y(_Bad()) is False
    assert is_dead_driver_error_1202y(None) is False


def test_navigate_retries_once_after_rebuilding():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/tools/browser/core.py").read_text(encoding="utf-8")
    body = src[src.index("#1202y"):]
    body = body[:body.index("raise _last_exc")]
    assert "recover_for_retry_1202y" in body
    assert "page.goto(" in body                     # the retry itself


def test_click_rebuilds_before_spending_its_remaining_attempts():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/tools/browser/interaction.py").read_text(
               encoding="utf-8")
    body = src[src.index("#1202y"):]
    body = body[:body.index("if attempt < retry - 1:")]
    assert "recover_for_retry_1202y" in body
    assert "page = self.browser.state.page" in body   # retry against the NEW page


def test_the_recovery_only_fires_for_a_dead_driver():
    """It must not swallow an ordinary error into a browser rebuild."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/tools/browser/_manager.py").read_text(
               encoding="utf-8")
    body = src[src.index("async def recover_for_retry_1202y"):]
    body = body[:body.index("\n    async def ")]
    assert "if not is_dead_driver_error_1202y(exc):" in body
    assert "return False" in body
