r"""#745: the retrospective told 102 runs that nobody ever fixed anything.

`_bug_stats` counted `closed` only when `metadata.bug_state == "closed"`. That field is set at
creation and advanced only by `update_bug_state`/`close_bug`, which almost nobody calls. Across
the whole 148-run corpus:

    bugs that ever reached bug_state == "closed"        6
    bug tasks whose STATUS is completed               818
    runs whose retrospective reports `closed: 0`   127 / 129
    ... of those, runs that DID fix bugs              102     ← reported as zero

The retrospective is the framework's own self-assessment and an input to what the next run
learns from. It was telling 102 runs that their entire remediation effort produced nothing.

Same root as #744 — two fields encode one bug lifecycle and only the task status is maintained —
and the same fix: derive from the field that is kept current rather than duplicating it. A
completed task IS a closed bug. `cancelled` stays excluded: #672 measured 55% of cancellations
as duplicates, and a deduped bug was never fixed.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import retro_aggregator as ra


class _Store:
    def __init__(self, tasks):
        self._t = tasks

    def value(self):
        return self._t


class _Stores:
    def __init__(self, tasks):
        self.tasks = _Store(tasks)


class _WH:
    def __init__(self, tasks):
        self.stores = _Stores(tasks)


def _bug(tid, status, bug_state="open", severity="P0"):
    return {"id": tid, "status": status,
            "metadata": {"kind": "bug", "bug_state": bug_state, "severity": severity}}


def _stats(*tasks):
    return ra._bug_stats(_WH({t["id"]: t for t in tasks}))


# --- the defect ---------------------------------------------------------------------------------

def test_a_completed_bug_counts_as_closed():
    assert _stats(_bug("a", "completed"))["closed"] == 1


def test_the_corpus_shape_is_covered():
    """status=completed with bug_state left at `open` — 616 of them, previously counted as 0."""
    s = _stats(_bug("a", "completed", "open"), _bug("b", "completed", "assigned"),
               _bug("c", "pending", "open"))
    assert s["closed"] == 2
    assert s["total_bugs"] == 3


def test_the_original_signal_still_works():
    """The 6 bugs that really did reach bug_state=closed must not be lost."""
    assert _stats(_bug("a", "pending", "closed"))["closed"] == 1


def test_a_bug_is_not_double_counted():
    assert _stats(_bug("a", "completed", "closed"))["closed"] == 1


# --- what must NOT count ---------------------------------------------------------------------------

def test_a_cancelled_bug_is_not_closed():
    """#672: 55% of cancellations are duplicates. A deduped bug was never fixed."""
    assert _stats(_bug("a", "cancelled"))["closed"] == 0


@pytest.mark.parametrize("status", ["pending", "in_progress", "failed"])
def test_an_outstanding_bug_is_not_closed(status):
    assert _stats(_bug("a", status))["closed"] == 0


def test_escalated_still_counts_separately():
    s = _stats(_bug("a", "pending", "escalated"))
    assert s["escalated"] == 1 and s["closed"] == 0


def test_a_completed_ESCALATED_bug_counts_as_closed_not_escalated():
    """`elif` ordering: a bug that was escalated and then fixed is fixed. Pinned because the
    branch order is what decides it, and a later edit could silently flip the meaning."""
    s = _stats(_bug("a", "completed", "escalated"))
    assert s["closed"] == 1 and s["escalated"] == 0


# --- everything else is untouched ---------------------------------------------------------------------

def test_severity_and_total_are_unchanged():
    s = _stats(_bug("a", "completed", severity="P0"), _bug("b", "pending", severity="P1"))
    assert s["total_bugs"] == 2
    assert s["by_severity"] == {"P0": 1, "P1": 1}


def test_a_non_bug_task_is_ignored():
    wh = _WH({"x": {"id": "x", "status": "completed", "metadata": {"kind": "impl"}}})
    assert ra._bug_stats(wh)["total_bugs"] == 0


@pytest.mark.parametrize("wh", [None, object()])
def test_a_missing_hub_is_tolerated(wh):
    assert ra._bug_stats(wh) == {"total_bugs": 0, "by_severity": {}, "closed": 0, "escalated": 0}


# --- non-vacuity ----------------------------------------------------------------------------------------

def test_the_old_rule_alone_would_have_reported_zero():
    """Guards against passing because the harness never reaches the branch."""
    t = _bug("a", "completed", "open")
    assert t["metadata"]["bug_state"] != "closed", "the old condition is genuinely unmet here"
    assert _stats(t)["closed"] == 1, "so the count can only come from the status half"


# --- provenance -------------------------------------------------------------------------------------------

def _prov() -> str:
    """Comment prose with the leading `#` and line wrapping removed. Matching raw source means
    every assertion silently depends on where a sentence happens to wrap — the quotation trap
    that has bitten this suite repeatedly, including twice in this very file."""
    src = inspect.getsource(ra._bug_stats)
    return " ".join(l.strip().lstrip("#").strip() for l in src.split("\n")).replace("  ", " ")


def test_the_measurement_is_recorded():
    p = _prov()
    assert "**6** bugs that ever reached it" in p
    assert "**818** whose TASK was completed" in p
    assert "127 of 129 runs report `closed: 0`" in p


def test_the_consequence_is_recorded():
    p = _prov()
    assert "in 102 of them that is false" in p
    assert "an input to what the next run learns" in p


def test_the_shared_root_with_744_is_named():
    p = _prov()
    assert "Same root as #744" in p
    assert "DERIVE from the field that is kept current" in p


def test_the_cancelled_carve_out_is_justified_in_place():
    p = _prov()
    assert "#672 measured 55% of cancellations as duplicates" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
