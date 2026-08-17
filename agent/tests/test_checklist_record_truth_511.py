"""#511 (netflix r80+r84+r85, 2026-08-05) — record-the-truth for stale build:* checklist.

GROUND TRUTH: r80/r84/r85 all died on verification_checklist_not_ready with build:* +
validation:api_smoke recorded = failure DESPITE a gate-passing api_smoke run (r85: 34 api_smoke
passes, visual passed, app provably built+booted+served). #492's reset-and-rerun demonstrably
doesn't land. FIX #511: when a gate-passing api_smoke RunHub run exists this session, directly
re-record the stale build:*/validation:{api_smoke,frontend_build} checks = success with
deterministic_runtime_evidence (outranks the stale opinion). SOUND: gated on a real passing run.

These tests lock _record_build_truth_from_passing_run: (1) re-records stale build checks when a
passing run exists, (2) no-op when NO passing run (never fabricates success), (3) skips
already-success checks, (4) ignores unrelated checks, (5) records with deterministic evidence."""
from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _record_build_truth_from_passing_run)


class _FakeRunHub:
    def __init__(self, has_pass):
        self._has = has_pass

    def last_successful_run_since(self, ts):
        return self._has


class _FakeCodeHub:
    def __init__(self, checks):
        # checks: list of {name, status}
        self._checks = [dict(c, pr_id="main", id=f"check_main_{c['name']}") for c in checks]
        self.recorded = []  # (name, status, evidence)

    def list_checks(self, pr_id=None):
        return [c for c in self._checks if pr_id is None or c["pr_id"] == pr_id]

    def record_check(self, pr_id, name, status, evidence=None, agent=""):
        self.recorded.append((name, status, evidence or {}))
        return {"ok": True}


class _FakeHubs:
    def __init__(self, runhub, codehub):
        self.runhub, self.codehub = runhub, codehub


class _FakeOrch:
    def __init__(self, has_pass, checks):
        self.hubs = _FakeHubs(_FakeRunHub(has_pass), _FakeCodeHub(checks))
        self._session_start_ts = 0.0
    # no _logger → helper's logging is best-effort/guarded


_STALE6 = [{"name": "build:docker", "status": "failure"},
           {"name": "build:backend", "status": "failure"},
           {"name": "build:frontend", "status": "failure"},
           {"name": "build:database", "status": "failure"},
           {"name": "validation:api_smoke", "status": "failure"},
           {"name": "validation:frontend_build", "status": "failure"}]


def test_records_stale_build_checks_when_passing_run_exists():
    orch = _FakeOrch(has_pass=True, checks=_STALE6)
    n = _record_build_truth_from_passing_run(orch)
    assert n == 6
    names = {r[0] for r in orch.hubs.codehub.recorded}
    assert names == {c["name"] for c in _STALE6}
    assert all(r[1] == "success" for r in orch.hubs.codehub.recorded)


def test_noop_when_no_passing_run():
    # NO gate-passing api_smoke run → must NOT fabricate success (soundness).
    orch = _FakeOrch(has_pass=False, checks=_STALE6)
    assert _record_build_truth_from_passing_run(orch) == 0
    assert orch.hubs.codehub.recorded == []


def test_skips_already_success_checks():
    checks = [{"name": "build:docker", "status": "success"},
              {"name": "build:backend", "status": "failure"}]
    orch = _FakeOrch(has_pass=True, checks=checks)
    n = _record_build_truth_from_passing_run(orch)
    assert n == 1
    assert orch.hubs.codehub.recorded[0][0] == "build:backend"


def test_ignores_unrelated_checks():
    checks = [{"name": "artifact:app/backend/main.py", "status": "failure"},
              {"name": "ui_flow:landing", "status": "failure"},
              {"name": "business_chain:foo", "status": "failure"}]
    orch = _FakeOrch(has_pass=True, checks=checks)
    assert _record_build_truth_from_passing_run(orch) == 0
    assert orch.hubs.codehub.recorded == []


def test_records_with_deterministic_evidence():
    orch = _FakeOrch(has_pass=True, checks=[{"name": "build:docker", "status": "failure"}])
    _record_build_truth_from_passing_run(orch)
    _, status, ev = orch.hubs.codehub.recorded[0]
    assert status == "success"
    assert ev.get("deterministic_runtime_evidence") is True  # outranks the stale opinion (#258)


# --- #511-review (2026-08-05): the passing run must reflect the CURRENT code. A gate-passing
# api_smoke EARLIER this session must NOT mask a LATER build regression (a fresh run that FAILED
# after it) — else a broken frontend ships. Enforced only when RunHub exposes list_runs + a
# comparable started_at; degrades to the prior trust-the-pass behavior otherwise (the fakes above).


class _FakeRunHubWithRuns:
    def __init__(self, passing_run, runs):
        self._passing, self._runs = passing_run, runs

    def last_successful_run_since(self, ts):
        return self._passing

    def list_runs(self, limit=1000):
        return list(self._runs)


class _FakeOrchRuns:
    def __init__(self, passing_run, runs, checks):
        self.hubs = _FakeHubs(_FakeRunHubWithRuns(passing_run, runs), _FakeCodeHub(checks))
        self._session_start_ts = 0.0


def test_later_failed_run_blocks_recording():
    # passing at t=100, but a fresh run FAILED at t=200 → the earlier pass is STALE → record NOTHING
    # (recording success would OUTRANK the real failure and ship a non-building app).
    passing = {"id": "r1", "started_at": 100.0, "status": "completed", "fail_count": 0}
    runs = [{"id": "r2", "started_at": 200.0, "status": "failed"}, passing]
    orch = _FakeOrchRuns(passing, runs, _STALE6)
    assert _record_build_truth_from_passing_run(orch) == 0
    assert orch.hubs.codehub.recorded == []


def test_no_later_failure_records():
    # passing is the MOST-RECENT completed run (the failure was BEFORE it) → record the truth.
    passing = {"id": "r2", "started_at": 200.0, "status": "completed", "fail_count": 0}
    runs = [passing, {"id": "r1", "started_at": 100.0, "status": "failed"}]
    orch = _FakeOrchRuns(passing, runs, _STALE6)
    assert _record_build_truth_from_passing_run(orch) == 6


def test_later_aborted_run_blocks_recording():
    # an ABORTED later run is also a regression signal → do not record.
    passing = {"id": "r1", "started_at": 100.0, "status": "completed", "fail_count": 0}
    runs = [{"id": "r2", "started_at": 300.0, "status": "aborted"}, passing]
    orch = _FakeOrchRuns(passing, runs, _STALE6)
    assert _record_build_truth_from_passing_run(orch) == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
