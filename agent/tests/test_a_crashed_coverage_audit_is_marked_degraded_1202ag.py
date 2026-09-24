r"""#1202ag: a coverage audit that crashed no longer looks like a clean app.

Both failure paths of `_coverage_summary` returned `{"is_clean": True, "dead_count_by_kind":
{}}`, and the gate reads it as:

    if not coverage.get("is_clean", True) and not functionally_validated:

so a broken audit and a spotless app produced byte-identical gate behaviour, silently. That is
the shape this session has been removing all day — #1201's warn-once exists for it, #1039's
live row count died of it, #1202ae found it in three detectors I wrote and #1202af in two of
the framework's — and here it was in the gate module itself.

★ `is_clean: True` STAYS. Flipping it turns every audit fault into a hard blocker, which is
#566j's false-blocker failure and cost r117/r120 a 75-minute no-deliver abort. What changes is
that the result carries `degraded: True` — the convention this same module already uses for
`_DEGRADED_FLOW_COVERAGE`, whose own docstring says it exists "so operators can distinguish a
broken audit from a clean app" — and that it says so once.
"""

import logging
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import deliverability as D  # noqa: E402
from multi_agent.runtime import message_format as mf  # noqa: E402


def test_a_crashed_audit_is_marked_degraded(caplog):
    mf._WARNED_1201.clear()
    with caplog.at_level(logging.WARNING):
        out = D._coverage_summary(object(), object())
    assert out["degraded"] is True
    assert out["source"] == "degraded"
    assert "1202ag" in caplog.text
    assert "NOT known absent" in caplog.text


def test_it_still_reports_clean_so_no_false_blocker_appears():
    """#566j: a fault must not become a hard blocker. The gate reads is_clean; it stays True."""
    out = D._coverage_summary(object(), object())
    assert out["is_clean"] is True
    assert out["dead_count_by_kind"] == {}


def test_the_gate_still_reads_is_clean_the_same_way():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/deliverability.py"
           ).read_text(encoding="utf-8")
    assert 'if not coverage.get("is_clean", True) and not functionally_validated:' in src


def test_a_healthy_audit_is_not_marked_degraded(tmp_path):
    """The marker is for failure only."""
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    out = D._coverage_summary(reg, tmp_path / "app")
    assert out.get("degraded") is not True
    assert "dead_count_by_kind" in out


def test_each_caller_gets_its_own_dict():
    """A shared constant handed out by reference would let one caller mutate the next one's."""
    a = D._coverage_summary(object(), object())
    b = D._coverage_summary(object(), object())
    a["is_clean"] = False
    assert b["is_clean"] is True
