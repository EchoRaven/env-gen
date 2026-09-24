"""#1202fy -- `updated_at` does not exist on a WorkHub task.

Found by extending #1202fx's sweep from validation records to the OTHER shared record
types, reading each store's real key set off a live ledger rather than off the source.

WorkHub writes the last-modification stamp as `_updated_at`; `updated_at` appears on 0 of
542 tasks in tiktok-r96's ledger. `_bug_reference_time_1023` read the latter, and because
its max() also sees claimed_at/created_at (present on all 542) the dead read failed
silently instead of returning nothing.

The cost is real: 76 of those 542 tasks have `_updated_at` NEWER than what the function
computed, 24 by over five minutes and one by 26.5 hours. #1114/#1023 use this to decide
whether a bug's evidence predates a content change, so evidence read as staler than it was.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import _bug_reference_time_1023  # noqa: E402


def test_the_field_workhub_actually_writes_is_read():
    """The defect in one line: this stamp was invisible."""
    assert _bug_reference_time_1023({"_updated_at": 900.0}) == 900.0


def test_the_newest_stamp_wins():
    task = {"created_at": 100.0, "claimed_at": 200.0, "_updated_at": 900.0}
    assert _bug_reference_time_1023(task) == 900.0


def test_an_older_underscore_stamp_does_not_drag_the_answer_back():
    task = {"created_at": 100.0, "claimed_at": 900.0, "_updated_at": 200.0}
    assert _bug_reference_time_1023(task) == 900.0


def test_triage_history_still_counts():
    task = {"created_at": 100.0, "_updated_at": 200.0,
            "metadata": {"triage_history": [{"at": 900.0}]}}
    assert _bug_reference_time_1023(task) == 900.0


def test_the_legacy_spelling_still_reads_if_a_store_ever_emits_it():
    assert _bug_reference_time_1023({"updated_at": 900.0}) == 900.0


def test_a_task_with_no_stamps_is_zero_not_a_raise():
    assert _bug_reference_time_1023({}) == 0.0
    assert _bug_reference_time_1023({"created_at": "not-a-number"}) == 0.0


def test_never_raises_on_a_malformed_task():
    for bad in (None, [], "task", {"metadata": "not-a-dict"}):
        assert isinstance(_bug_reference_time_1023(bad), float)
