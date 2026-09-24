r"""#1202af: the framework's own gate detectors say so when they cannot run.

#1202ae applied this rule to three detectors I had written; this extends the audit to the ones
I did not. An AST sweep of `runtime/` for functions that swallow an exception and return an
empty value found 224 sites, 174 of them with no announcement anywhere in the function body.

★ My first pass reported 186 and named `business_chain_blockers` among the offenders. It is
not one: it announces through `_swallowed_790`, a third mechanism my sweep did not know about
alongside `warn_once_1201` and `_gate_absent_792`. Counting all three brings the figure down
and clears that function.

Most of the 174 are fine — a helper returning `[]` on bad input is answering, not measuring.
The ones that matter are detectors whose empty return feeds a DELIVERY BLOCKER, because there
"found nothing" becomes "delivery allowed". Two are now covered:

    unscoped_owner_read_findings      #919, cross-user reads   (#1202af)
    invented_field_fallback_blockers  #175, invented values    (#1202af)

Both keep their existing return value, so no gate behaviour changes; only the silence goes.
"""

import io
import logging
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import message_format as mf  # noqa: E402
from multi_agent.runtime.backend_audit import unscoped_owner_read_findings  # noqa: E402
from multi_agent.runtime.frontend_audit import (  # noqa: E402
    invented_field_fallback_blockers)


def _fresh():
    mf._WARNED_1201.clear()


def test_the_owner_read_scan_announces(caplog):
    _fresh()
    with caplog.at_level(logging.WARNING):
        assert unscoped_owner_read_findings(object()) == []
    assert "NOT known scoped" in caplog.text


def test_the_invented_field_scan_announces(caplog):
    _fresh()
    with caplog.at_level(logging.WARNING):
        assert invented_field_fallback_blockers(object()) == []
    assert "NOT known real" in caplog.text


def test_a_clean_tree_stays_silent(tmp_path, caplog):
    _fresh()
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.jsx").write_text("export default function App(){return null;}\n",
                                 encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        invented_field_fallback_blockers(src)
    assert "NOT known real" not in caplog.text


def test_business_chain_blockers_was_never_an_offender():
    """It announces through `_swallowed_790` — the mechanism my first sweep missed, which is
    why the first count was wrong. Pinned so the correction is not lost."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/delivery_gate.py"
           ).read_text(encoding="utf-8")
    i = src.index("def business_chain_blockers")
    body = src[i:src.index("\ndef ", i + 1)]
    assert "_swallowed_790(" in body


def test_the_returns_are_unchanged():
    """The point is the announcement, not a behaviour change: both still return []."""
    _fresh()
    assert unscoped_owner_read_findings(object()) == []
    assert invented_field_fallback_blockers(object()) == []
