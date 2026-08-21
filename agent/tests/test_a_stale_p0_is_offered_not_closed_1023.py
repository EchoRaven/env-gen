r"""#1023: nothing retires a P0 whose condition stopped being true, so the count random-walks.

netflix r172, measured LIVE at 16:12 against the running system rather than the ledger — all
three containers `Up (healthy)` at the time:

    "PostgreSQL container exits during clean Docker startup"        docker_database_1 Up (healthy)
    "Docker validation cannot start because frontend container      docker_frontend_1 Up
     is missing"
    "Clean database initialization fails on my_list.profile_id      the DDL on disk was already
     foreign-key type mismatch"                                     SERIAL/integer throughout
    "Canonical runtime port 3000 serves backend 404"                STILL TRUE under curl

Three of four open P0s described a world that no longer existed. The verifier files one task
per SYMPTOM (one unbootable DDL produced five), so the count rises automatically; it falls only
when somebody happens to close one. Hence r172's sawtooth: 1 -> 2 -> 1 -> 3 -> 2 -> 5 -> 3 -> 4.

★ **This does not close, cancel, or age anything out, by design.** A task-lifecycle timeout
would passively cancel work that is merely slow — and that is backwards here: the stale tasks
are the FAST ones (a symptom whose cause was fixed minutes later), while a slow task is exactly
the one that must survive. So the gate reports EVIDENCE and the owning agent decides.

The signal is deliberately conservative — every file the bug itself named in
`bug_artifacts.affected_files` has been modified since the bug's own evidence was taken
(`claimed_at` / `created_at` / latest `triage_history[].at`). That is grounds to re-verify, not
proof of a fix. One unchanged file, one missing file, no named files, or no timestamp all
return "" rather than guess.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _bug_reference_time_1023, _stale_open_p0_evidence_1023, unresolved_bug_tasks_743)


def _task(files, ref=1000.0, status="in_progress", **kw):
    t = {"id": "task_x", "title": "PostgreSQL container exits during clean Docker startup",
         "status": status, "assignee": "backend", "claimed_at": ref,
         "metadata": {"kind": "bug", "severity": "P0",
                      "bug_artifacts": {"affected_files": list(files)}}}
    t.update(kw)
    return t


def _tree(tmp_path, files, mtime):
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        import os
        os.utime(p, (mtime, mtime))
    return tmp_path


# --- the signal ---------------------------------------------------------------------------

def test_every_affected_file_changed_since_the_evidence(tmp_path):
    _tree(tmp_path, ["docker/docker-compose.yml"], mtime=2000.0)
    out = _stale_open_p0_evidence_1023(_task(["docker/docker-compose.yml"], ref=1000.0), tmp_path)
    assert out and "docker/docker-compose.yml" in out
    assert "+16m" in out, out          # (2000-1000)/60 -> 16


def test_one_unchanged_file_means_the_evidence_still_stands(tmp_path):
    """Conservative on purpose: a partial fix is not grounds to re-verify the whole bug."""
    _tree(tmp_path, ["a.py"], mtime=2000.0)
    _tree(tmp_path, ["b.py"], mtime=500.0)
    assert _stale_open_p0_evidence_1023(_task(["a.py", "b.py"], ref=1000.0), tmp_path) == ""


def test_a_file_modified_exactly_at_the_reference_is_not_stale(tmp_path):
    _tree(tmp_path, ["a.py"], mtime=1000.0)
    assert _stale_open_p0_evidence_1023(_task(["a.py"], ref=1000.0), tmp_path) == ""


def test_no_named_files_stays_quiet(tmp_path):
    assert _stale_open_p0_evidence_1023(_task([], ref=1000.0), tmp_path) == ""


def test_a_named_file_we_cannot_see_is_not_a_guess(tmp_path):
    assert _stale_open_p0_evidence_1023(_task(["gone.py"], ref=1000.0), tmp_path) == ""


def test_no_timestamp_means_no_verdict(tmp_path):
    _tree(tmp_path, ["a.py"], mtime=2000.0)
    t = _task(["a.py"])
    t.pop("claimed_at")
    assert _stale_open_p0_evidence_1023(t, tmp_path) == ""


def test_it_never_raises_on_junk(tmp_path):
    for junk in ({}, {"metadata": None}, {"metadata": {"bug_artifacts": {"affected_files": 3}}}):
        assert _stale_open_p0_evidence_1023(junk, tmp_path) == ""
    assert _stale_open_p0_evidence_1023(_task(["a.py"]), None) == ""


def test_the_reference_time_is_the_LATEST_evidence(tmp_path):
    """A bug re-triaged after a fix landed must not read as stale off its original claim."""
    t = _task(["a.py"], ref=1000.0)
    t["metadata"]["triage_history"] = [{"at": 900.0}, {"at": 3000.0}]
    assert _bug_reference_time_1023(t) == 3000.0
    _tree(tmp_path, ["a.py"], mtime=2000.0)
    assert _stale_open_p0_evidence_1023(t, tmp_path) == "", (
        "the file predates the latest triage — the evidence is current")


# --- the collector -----------------------------------------------------------------------

class _WH:
    def __init__(self, tasks):
        self._t = tasks

    def list_tasks(self):
        return self._t


class _Hubs:
    def __init__(self, tasks):
        self.workhub = _WH(tasks)


def test_the_gate_reports_stale_separately_from_open(tmp_path):
    _tree(tmp_path, ["docker/docker-compose.yml"], mtime=2000.0)
    stale = _task(["docker/docker-compose.yml"], ref=1000.0)
    fresh = dict(_task(["docker/docker-compose.yml"], ref=9000.0), id="task_y",
                 title="Canonical runtime port 3000 serves backend 404")
    out = unresolved_bug_tasks_743(_Hubs([stale, fresh]), tmp_path)
    assert out["open_p0_bug_count"] == 2, out
    assert out["stale_open_p0_count"] == 1, out
    assert out["stale_open_p0"][0]["id"] == "task_x"


def test_nothing_is_closed_or_cancelled(tmp_path):
    """★ The design constraint. The task's status must be untouched — the agent decides."""
    _tree(tmp_path, ["a.py"], mtime=2000.0)
    t = _task(["a.py"], ref=1000.0)
    before = dict(t)
    out = unresolved_bug_tasks_743(_Hubs([t]), tmp_path)
    assert out["stale_open_p0_count"] == 1
    assert t["status"] == before["status"] == "in_progress"
    assert t["metadata"]["severity"] == "P0"
    assert "cancelled" not in str(out).lower()


def test_no_age_based_cancellation_anywhere(tmp_path):
    """A task open for a very long time, whose files never changed, is NOT flagged — slowness
    alone must never be grounds. This is the failure mode a lifecycle timeout would have."""
    _tree(tmp_path, ["a.py"], mtime=10.0)
    old = _task(["a.py"], ref=1_000_000.0)
    out = unresolved_bug_tasks_743(_Hubs([old]), tmp_path)
    assert out["open_p0_bug_count"] == 1
    assert out["stale_open_p0_count"] == 0, "age must not make a task stale"


def test_the_collector_still_works_without_an_output_dir(tmp_path):
    """Back-compat: the pre-#1023 one-argument call must keep working and simply not judge."""
    out = unresolved_bug_tasks_743(_Hubs([_task(["a.py"], ref=1000.0)]))
    assert out["open_p0_bug_count"] == 1 and out["stale_open_p0_count"] == 0


def test_a_completed_bug_is_not_considered(tmp_path):
    _tree(tmp_path, ["a.py"], mtime=2000.0)
    out = unresolved_bug_tasks_743(
        _Hubs([_task(["a.py"], ref=1000.0, status="completed")]), tmp_path)
    assert out["open_p0_bug_count"] == 0 and out["stale_open_p0_count"] == 0


def test_the_planted_r172_case_is_detected(tmp_path):
    """The three r172 tasks that no longer reproduced, against a tree touched after triage."""
    files = ["docker/docker-compose.yml", "app/database/init/01_init.sql"]
    _tree(tmp_path, files, mtime=5000.0)
    tasks = [dict(_task([f], ref=1000.0), id=f"task_{i}", title=t) for i, (f, t) in enumerate([
        (files[0], "Docker validation cannot start because frontend container is missing"),
        (files[1], "Clean database initialization fails on my_list.profile_id FK type mismatch"),
    ])]
    out = unresolved_bug_tasks_743(_Hubs(tasks), tmp_path)
    assert out["stale_open_p0_count"] == 2, out
    assert all(b["stale_evidence"] for b in out["stale_open_p0"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
