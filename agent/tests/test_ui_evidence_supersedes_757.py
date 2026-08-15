r"""#757: #752 counted a validation HISTORY, so an answered failure would have latched forever.

#752 blocks delivery when any UI-evidence record is `failed`. Validation records are a history,
and nothing retires one — so a flow that failed early and passed later kept blocking, because
the old entry is still in the stream. A gate that cannot be cleared is a latch, not a gate, and
the other two gates this session were explicitly rejected at 45% and 70% for being exactly that.

Superseding by NAME is the store's own rule (`validation:<task_id>` is last-write-wins), so this
reads the history the way the store means it: a failure that is still the newest word on its flow
blocks; one a later pass has answered does not.

**r149 is not this case, and checking that is the point.** I found the gate had blocked r149 for
85 minutes as the only failing check and assumed a stale latch. Its records say otherwise:

    33 of 34 validation records are `success`
    the one failure is `validation:ui_flow:login_to_browse`, updated 1786758171 —
    the NEWEST record in the entire run

So the block was correct: the last word on login→browse was "failed", which is exactly what an
`isAuthenticated` stub throwing on 9 screens (#753) produces. #757 is a real hardening found
while checking a hypothesis that turned out to be false.

The second half is the page name. r149's warning read `passed ? / failed ?` — the fallback for
every one of 19 records, because none of `page`/`route`/`name` is set in metadata. A gate that
cannot say WHICH page failed cannot be acted on; the record's own `name` carries it.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _rec(name, status, ts, check="ui_flow", **meta):
    m = {"check": check}
    m.update(meta)
    return {"name": name, "status": status, "updated_at": ts, "metadata": m}


# --- superseding -------------------------------------------------------------------------------

def test_a_later_pass_on_the_same_flow_clears_the_failure():
    b = dg._ui_evidence_breadth_739([
        _rec("validation:ui_flow:browse_home", "failed", 1),
        _rec("validation:ui_flow:browse_home", "success", 2)])
    assert b["failed_records"] == 0
    assert b["pages_passed"] == ["browse_home"]


def test_a_later_FAILURE_on_the_same_flow_still_blocks():
    b = dg._ui_evidence_breadth_739([
        _rec("validation:ui_flow:browse_home", "success", 1),
        _rec("validation:ui_flow:browse_home", "failed", 2)])
    assert b["failed_records"] == 1


def test_an_unanswered_failure_on_another_flow_still_blocks():
    """The r149 shape: 18 passes elsewhere do not answer a failure on `login_to_browse`."""
    recs = [_rec(f"validation:ui_flow:p{i}", "success", i) for i in range(18)]
    recs.append(_rec("validation:ui_flow:login_to_browse", "failed", 99))
    b = dg._ui_evidence_breadth_739(recs)
    assert b["failed_records"] == 1
    assert b["pages_failed"] == ["login_to_browse"]


def test_the_r149_record_set_blocks_for_the_right_reason():
    """Reconstructed from the run: 33 successes and one failure that is the NEWEST record."""
    recs = [_rec(f"validation:ui_flow:s{i}", "success", 1000 + i) for i in range(33)]
    recs.append(_rec("validation:ui_flow:login_to_browse", "failure", 9999))
    b = dg._ui_evidence_breadth_739(recs)
    assert b["passed_records"] == 33 and b["failed_records"] == 1
    assert b["pages_failed"] == ["login_to_browse"]


def test_records_without_timestamps_do_not_crash_the_ordering():
    b = dg._ui_evidence_breadth_739([
        {"name": "validation:ui_flow:x", "status": "failed", "metadata": {"check": "ui_flow"}},
        {"name": "validation:ui_flow:x", "status": "success", "metadata": {"check": "ui_flow"}}])
    assert b["passed_records"] + b["failed_records"] == 1, "one survivor, not two"


@pytest.mark.parametrize("field", ["updated_at", "_updated_at", "created_at", "at"])
def test_every_timestamp_field_the_stores_use_is_read(field):
    a = {"name": "n", "status": "failed", "metadata": {"check": "ui_flow"}, field: 1}
    b = {"name": "n", "status": "success", "metadata": {"check": "ui_flow"}, field: 2}
    assert dg._ui_evidence_breadth_739([a, b])["failed_records"] == 0, field


def test_the_recency_helper_is_total():
    for junk in (None, {}, "x", 5, {"updated_at": "not-a-number"}):
        assert dg._ts757(junk) == 0.0


# --- the page name ---------------------------------------------------------------------------------

def test_the_page_comes_from_the_record_name_when_metadata_is_bare():
    """r149 printed `passed ? / failed ?` for all 19 records."""
    b = dg._ui_evidence_breadth_739([_rec("validation:ui_flow:genre_category", "failed", 1)])
    assert b["pages_failed"] == ["genre_category"]


def test_explicit_metadata_still_wins():
    b = dg._ui_evidence_breadth_739(
        [_rec("validation:ui_flow:ignored", "failed", 1, page="/real/route")])
    assert b["pages_failed"] == ["/real/route"]


def test_a_nameless_record_is_still_counted():
    b = dg._ui_evidence_breadth_739([{"status": "failed", "metadata": {"check": "ui_flow"}}])
    assert b["failed_records"] == 1, "under-counting a failure is the wrong direction"


# --- nothing else changed ------------------------------------------------------------------------------

def test_non_ui_records_are_still_ignored():
    b = dg._ui_evidence_breadth_739([_rec("validation:api_smoke", "failed", 1, check="api_smoke")])
    assert b["failed_records"] == 0


def test_the_gate_still_blocks_on_a_surviving_failure():
    g = inspect.getsource(dg.validate_delivery_gate)
    assert 'failed_checks.append("validation_ui_evidence_failed")' in g


# --- provenance -------------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(dg._ui_evidence_breadth_739)
    i = src.index("#757: KEEP ONLY THE LATEST")
    return " ".join(l.strip().lstrip("#").strip() for l in src[i:].split("\n"))


def test_the_latch_risk_is_recorded():
    p = _prov()
    assert "That is not a gate, it is a latch." in p
    assert "nothing retires it" in p


def test_r149s_cost_is_recorded():
    p = _prov()
    assert "18 passing UI record(s) while 1 FAILED" in p
    assert "the ONLY failing check for 85 minutes" in p


def test_the_supersede_rule_is_justified_by_the_store():
    p = _prov()
    assert "last-write-wins" in p


def test_the_unprintable_page_name_is_recorded():
    p = _prov()
    assert "passed ? / failed" in p
    assert "cannot say WHICH page failed cannot be acted on" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
