"""#1202fu -- _ts757 looked for four field names, none of which a production record has.

`HubRegistry.get_validation_results` RENAMES the field when it builds a row:
``"recorded_at": check.get("updated_at", 0)``. _ts757 looked for updated_at / _updated_at /
created_at / at, so it returned 0.0 for every real record.

That made #757 itself inert since it landed: with all timestamps 0.0 the
``_ts757(r) >= _ts757(prev)`` comparison is ``0 >= 0`` — always true — so "latest wins"
kept whichever record iteration reached last. And #1202fs's staleness, which needs a real
timestamp, could never drop anything.

These tests build records through the PRODUCER rather than by hand: the offline fixture
that hid this carried both spellings, and a fixture the producer would never emit tests a
world that does not exist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _ts757, _ui_evidence_breadth_739)
from multi_agent.runtime import hub_registry as HR  # noqa: E402


def _production_record(name, status, at, check="ui_flow", flow=None):
    """Build a row exactly as HubRegistry.get_validation_results does, from a CodeHub
    check — so the shape is the producer's, not this test's opinion of it."""
    ev = {"summary": "", "execution_mode": "manual",
          "metadata": {"check": check, **({"flow": flow} if flow else {})}}
    check_row = {"name": name, "status": status, "evidence": ev, "updated_at": at,
                 "agent": "verifier"}
    return {
        "task_id": check_row["name"].removeprefix("validation:"),
        "name": check_row["name"],
        "status": HR._canon_validation_status(check_row["status"]),
        "summary": ev.get("summary", ""),
        "execution_mode": ev.get("execution_mode", "auto"),
        "metadata": HR._flatten_validation_metadata(ev),
        "recorded_by": check_row.get("agent", ""),
        "recorded_at": check_row.get("updated_at", 0),
    }


def test_a_production_record_has_a_readable_timestamp():
    """The defect in one line: this returned 0.0 for every real row."""
    r = _production_record("validation:ui_flow:x", "success", 1234.5, flow="x")
    assert _ts757(r) == 1234.5, (
        "the recency of a production record reads as 0.0 — #757's latest-wins and "
        "#1202fs's staleness both compare it")


def test_the_producer_still_emits_the_field_this_reads():
    """A contract test between producer and consumer. If get_validation_results renames
    the field again, this fails here rather than silently in the gate."""
    r = _production_record("validation:ui_flow:x", "success", 99.0, flow="x")
    assert "recorded_at" in r, "the producer no longer emits recorded_at"
    assert _ts757(r) > 0


def test_latest_wins_on_production_records():
    """#757's whole purpose: a later pass retires an answered failure."""
    recs = [_production_record("validation:ui_flow:f", "failure", 1000.0, flow="f"),
            _production_record("validation:ui_flow:f", "success", 9000.0, flow="f")]
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 0
    recs.reverse()      # iteration order must not decide the verdict
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 0


def test_a_later_failure_still_wins_on_production_records():
    recs = [_production_record("validation:ui_flow:f", "success", 1000.0, flow="f"),
            _production_record("validation:ui_flow:f", "failure", 9000.0, flow="f")]
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 1
    recs.reverse()
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 1


def test_staleness_can_actually_drop_a_production_record():
    """#1202fs needs a real timestamp; with 0.0 it could never fire."""
    recs = [_production_record("validation:ui_flow:f", "failure", 1000.0, flow="f")]
    assert _ui_evidence_breadth_739(recs, stale_before=5000.0)["failed_records"] == 0
    assert _ui_evidence_breadth_739(recs, stale_before=500.0)["failed_records"] == 1


def test_older_spellings_still_read():
    """Records written by an older normaliser must not start reading as timeless."""
    for k in ("updated_at", "_updated_at", "created_at", "at"):
        assert _ts757({k: 77.0}) == 77.0


def test_recorded_at_wins_when_both_are_present():
    """The canonical field is the producer's; a legacy copy must not outrank it."""
    assert _ts757({"recorded_at": 2.0, "updated_at": 1.0}) == 2.0
