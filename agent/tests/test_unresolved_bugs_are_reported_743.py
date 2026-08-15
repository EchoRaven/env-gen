r"""#743: bug tasks are excluded from the delivery gate, delegated to a gate that isn't.

`incomplete_required_tasks` counts only structural kickoff kinds and states the reason: ad-hoc
`task_*` "are governed by their own gates (visual deferral, deliverability) and are deliberately
excluded here so this gate never double-blocks them". The exclusion is right in shape — a bug
should not double-block — but for `kind='bug'` the delegation goes nowhere: **neither
`deliverability.py` nor `delivery_gate.py` references `kind='bug'` or a bug severity anywhere.**

This also corrects a looser claim I made earlier in the session: "the delivery gate reads no task
status or priority at all". It DOES read task status — `incomplete_required_tasks` calls
`wh.list_tasks()` and filters on `pending`/`in_progress`. What is true is narrower and worse: it
reads structural tasks and deliberately skips bugs, citing a consumer that does not exist.

Corpus, restricted to `metadata.kind == 'bug'` (1477 bug tasks across 129 runs):

    completed 818   pending 363   cancelled 140   in_progress 139   failed 17
    P0 only:  completed 443, genuinely open 317, cancelled 99
    runs ending with an unresolved P0 bug     86
    of those, runs that RELEASED              15      (of 29 real releases in the whole corpus)

#755 CORRECTION: this first read "90 ... 90 ... 100%". The release test was
`r.get("tag") or r.get("version")` and every codehub_releases.json carries a bootstrap
`{"version": 1}` document, so every run scored as released. Only 29 of 149 ever cut a real tag.

A hard block on "any open P0 bug" would stop 86 of 129 runs. That is a halt, not a gate, and it
is the same conclusion reached from the other direction in item 56 (124 of 148 on all-kinds P0).

**`failed` is the narrow signal.** `fail_task` is authorised (creator/claimer/orchestrator),
requires a `reason`, and means an attempt was MADE and did not work — `pending` can just mean
nobody reached it. Only 20 of 148 runs end with one, and 4 of those released (#755 corrects an
earlier "all 20": a bootstrap `{"version": 1}` document was being read as a release tag).
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


class _WH:
    def __init__(self, tasks):
        self._t = tasks

    def list_tasks(self):
        return self._t


class _Hubs:
    def __init__(self, tasks):
        self.workhub = _WH(tasks)


def _task(tid, status, kind=None, severity=None, title="t", reason=None):
    return {"id": tid, "status": status, "title": title, "fail_reason": reason,
            "assignee": "frontend",
            "metadata": {k: v for k, v in (("kind", kind), ("severity", severity)) if v}}


# --- what it reports ---------------------------------------------------------------------------

def test_a_failed_task_is_named_with_its_reason():
    out = dg.unresolved_bug_tasks_743(_Hubs([
        _task("t1", "failed", "bug", "P0", "Dockerfile uses blocked base images",
              reason="registry 403")]))
    assert out["failed_count"] == 1
    assert out["failed"][0]["reason"] == "registry 403"
    assert out["failed"][0]["severity"] == "P0"


def test_a_failed_task_is_reported_whatever_its_kind():
    """20 of 148 runs end with one and half carry no severity — the structural
    `validate.api_smoke...` and `impl.component...` failures are exactly as interesting."""
    out = dg.unresolved_bug_tasks_743(_Hubs([_task("t1", "failed")]))
    assert out["failed_count"] == 1


def test_open_p0_bugs_are_counted_separately():
    out = dg.unresolved_bug_tasks_743(_Hubs([
        _task("b1", "pending", "bug", "P0"), _task("b2", "in_progress", "bug", "P0")]))
    assert out["open_p0_bug_count"] == 2
    assert out["failed_count"] == 0


def test_a_completed_or_cancelled_bug_is_not_open():
    out = dg.unresolved_bug_tasks_743(_Hubs([
        _task("b1", "completed", "bug", "P0"), _task("b2", "cancelled", "bug", "P0")]))
    assert out["open_p0_bug_count"] == 0


def test_a_non_bug_pending_task_is_not_counted_as_a_bug():
    """The structural gate already owns those; double-counting them would recreate the
    83%-blast-radius number that made the P0 idea unusable."""
    out = dg.unresolved_bug_tasks_743(_Hubs([_task("s1", "pending", None, "P0")]))
    assert out["open_p0_bug_count"] == 0


def test_lower_severities_are_not_counted_as_p0():
    out = dg.unresolved_bug_tasks_743(_Hubs([_task("b1", "pending", "bug", "P1")]))
    assert out["open_p0_bug_count"] == 0


def test_the_lists_are_bounded_but_the_counts_are_not():
    out = dg.unresolved_bug_tasks_743(_Hubs(
        [_task(f"f{i}", "failed") for i in range(25)]
        + [_task(f"b{i}", "pending", "bug", "P0") for i in range(25)]))
    assert out["failed_count"] == 25 and len(out["failed"]) == 10
    assert out["open_p0_bug_count"] == 25 and len(out["open_p0_bugs"]) == 10


# --- it can never break the gate ------------------------------------------------------------------

@pytest.mark.parametrize("hubs", [None, object(), _Hubs([None, "x", 3])])
def test_junk_never_raises(hubs):
    assert isinstance(dg.unresolved_bug_tasks_743(hubs), dict)


def test_a_raising_workhub_is_tolerated():
    class _Boom:
        def list_tasks(self):
            raise RuntimeError("hub down")

    class _H:
        workhub = _Boom()
    assert dg.unresolved_bug_tasks_743(_H()) == {}


def test_it_decides_nothing():
    src = inspect.getsource(dg.unresolved_bug_tasks_743)
    assert "failed_checks" not in src
    assert "raise" not in src


# --- it is wired into the gate --------------------------------------------------------------------

def _gate_src() -> str:
    return inspect.getsource(dg.validate_delivery_gate)


def test_the_gate_calls_it_and_publishes_it():
    g = _gate_src()
    assert "_bugs743 = unresolved_bug_tasks_743(hubs)" in g
    assert '"unresolved_bugs": _bugs743' in g


def test_both_findings_are_logged_separately():
    g = _gate_src()
    assert "are in status FAILED at the delivery cut" in g
    assert "P0 BUG task(s) are still open at the delivery cut" in g


def test_the_warnings_say_they_do_not_enforce():
    g = _gate_src()
    assert "Reported, not enforced" in g
    assert "reported rather than blocking" in g


def test_it_runs_before_the_verdict_is_assembled():
    g = _gate_src()
    assert g.index("_bugs743 = unresolved_bug_tasks_743") < g.index("incomplete_tasks =")


# --- provenance --------------------------------------------------------------------------------------

def test_the_delegation_gap_is_recorded():
    d = " ".join((dg.unresolved_bug_tasks_743.__doc__ or "").split())
    assert "the delegation goes nowhere for this kind" in d
    assert "Nothing consumes them." in d


def test_the_blast_radius_of_both_options_is_recorded():
    d = " ".join((dg.unresolved_bug_tasks_743.__doc__ or "").split())
    assert "86 of 129 runs" in d and "is not a gate, it is a halt" in d
    assert "15 of the 29 runs that actually released" in d, "#755: the corrected release count"
    assert "20 of 148 runs (13%)" in d


def test_why_failed_beats_pending_is_recorded():
    d = " ".join((dg.unresolved_bug_tasks_743.__doc__ or "").split())
    assert "an attempt was MADE and did not work" in d
    assert "nobody reached it" in d


def test_the_exclusion_it_documents_is_really_there():
    """Non-vacuity: the finding rests on a docstring in another function. If that text ever
    changes, this must fail rather than keep citing it."""
    d = " ".join((dg.incomplete_required_tasks.__doc__ or "").split())
    assert "governed by their own gates" in d
    assert "deliberately excluded here" in d


def test_deliverability_does_not_consume_bug_tasks():
    """Half of the claim, checked rather than asserted from memory. `deliverability` is one of
    the two gates the exclusion names, and it does not mention a bug kind at all."""
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dl
    src = inspect.getsource(dl)
    assert '"bug"' not in src and "'bug'" not in src


def test_the_gate_never_CONSUMES_a_tasks_bugness_outside_743():
    """The other half. The first version of this asserted the WORD `bug` never appears outside
    #743, and it failed on prompt prose — "…file a bug via `bug_create(...)`" — which is an
    instruction to an agent, not a gate reading a task. The claim is about CONSUMPTION, so
    that is what is checked: nothing outside #743 tests a task's kind for bug-ness or branches
    on a bug severity. If a real bug gate is ever added this fails, and the finding must be
    re-stated rather than silently kept."""
    import re
    src = inspect.getsource(dg)
    rest = src.replace(inspect.getsource(dg.unresolved_bug_tasks_743), "")
    consumption = re.compile(r"""kind[^\n]{0,20}==[^\n]{0,10}["']bug["']"""
                             r"""|["']bug["'][^\n]{0,10}==[^\n]{0,20}kind"""
                             r"""|severity[^\n]{0,20}==[^\n]{0,10}["']P[0-3]["']"""
                             r"""|severity[^\n]{0,30}\bin\b[^\n]{0,30}P0""")
    hits = [rest[rest.rfind("\n", 0, m.start()) + 1:rest.find("\n", m.start())].strip()
            for m in consumption.finditer(rest)]
    assert not hits, hits


def test_that_consumption_pattern_is_not_vacuous():
    """The regex above must actually match the shape it claims to look for."""
    import re
    probe = ('if (t.get("metadata") or {}).get("kind") == "bug":\n'
             'if meta.get("severity") == "P0":\n')
    consumption = re.compile(r"""kind[^\n]{0,20}==[^\n]{0,10}["']bug["']"""
                             r"""|severity[^\n]{0,20}==[^\n]{0,10}["']P[0-3]["']""")
    assert len(consumption.findall(probe)) == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
