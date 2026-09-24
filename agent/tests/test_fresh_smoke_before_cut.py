"""FIX #155 (§6-2) — fresh api_smoke before cut when the backend drifted post-smoke.

gmrun3 timeline (precise, from the archive logs): last api_smoke PASSED @05:15 → visual
window escaped @05:33 → backend lane EDITED custom_routes.py @05:34-35 (a broken
middleware that ``await None()``s at import) → cut release @05:37. The delivery gate
reuses the mid-milestone smoke; the cut-time ``_merge_committed_agent_work()`` imports the
late commit into the release snapshot with NO re-validation → the delivered archive
crashes cold-start (every request 500). The window is STRUCTURAL: the merge sits after
every gate check and before create_release.

Fix: stamp a backend source signature when the framework smoke PASSES; at cut time, if
the (merged, committed) backend signature differs, run ONE fresh RunValidationTool pass
(clean docker boot + probes) and HOLD the cut on failure. Signature covers
app/backend/**/*.py ONLY — the code that executes at boot (custom_routes.py included);
.sql/.json are excluded because the heal pipeline's ORM introspection is not byte-stable
(01_init.sql churn would false-drift every cut). Same-sig failures are cached (no docker
churn); a lane fix changes the sig and re-arms the fresh smoke.
LOCAL-ONLY (agent/tests/ is gitignored).
"""
import asyncio
import logging
import os
import shutil
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from multi_agent.runtime.framework_validation import (  # noqa: E402
    backend_source_signature, ensure_fresh_smoke_before_cut, fresh_smoke_decision)


def _app(tmp_path, backend=None, frontend=None, sql=None):
    root = tmp_path / "app"
    (root / "backend").mkdir(parents=True, exist_ok=True)
    (root / "frontend" / "src").mkdir(parents=True, exist_ok=True)
    (root / "database" / "init").mkdir(parents=True, exist_ok=True)
    for name, txt in (backend or {}).items():
        (root / "backend" / name).write_text(txt)
    for name, txt in (frontend or {}).items():
        (root / "frontend" / "src" / name).write_text(txt)
    for name, txt in (sql or {}).items():
        (root / "database" / "init" / name).write_text(txt)
    return root


# ------------------------- backend_source_signature -------------------------

def test_signature_stable_and_flips_on_backend_py_edit(tmp_path):
    root = _app(tmp_path, backend={"main.py": "app = 1\n", "custom_routes.py": "x = 1\n"})
    s1 = backend_source_signature(root)
    s2 = backend_source_signature(root)
    assert s1 and s1 == s2
    (root / "backend" / "custom_routes.py").write_text("x = 2  # late edit\n")
    assert backend_source_signature(root) != s1


def test_signature_ignores_frontend_and_nonpy_churn(tmp_path):
    root = _app(tmp_path, backend={"main.py": "app = 1\n"},
                frontend={"App.jsx": "v1"}, sql={"01_init.sql": "CREATE TABLE a;"})
    s1 = backend_source_signature(root)
    # frontend edit + the heal pipeline's non-byte-stable DDL/json churn must not drift
    (root / "frontend" / "src" / "App.jsx").write_text("v2")
    (root / "database" / "init" / "01_init.sql").write_text("CREATE TABLE a;  -- reordered")
    (root / "backend" / "seed_dataset.json").write_text('{"places": []}')
    assert backend_source_signature(root) == s1


def test_signature_ignores_pycache(tmp_path):
    root = _app(tmp_path, backend={"main.py": "app = 1\n"})
    s1 = backend_source_signature(root)
    pc = root / "backend" / "__pycache__"
    pc.mkdir()
    (pc / "main.cpython-311.pyc").write_text("junk")
    (pc / "stray.py").write_text("junk = 1")
    assert backend_source_signature(root) == s1


def test_signature_none_when_backend_missing(tmp_path):
    assert backend_source_signature(tmp_path / "app") is None


# ---------------------------- fresh_smoke_decision ----------------------------

def test_decision_matrix():
    # cannot judge our own fault → never block delivery on it
    assert fresh_smoke_decision(None, "v", "p", "f") == "cut"
    # current tree already validated by the last passing smoke → cut
    assert fresh_smoke_decision("s", "s", None, None) == "cut"
    # current tree already freshly validated at a previous cut attempt → cut
    assert fresh_smoke_decision("s", "old", "s", None) == "cut"
    # this exact tree already FAILED a fresh smoke → hold, do not churn docker
    assert fresh_smoke_decision("s", "old", None, "s") == "hold"
    # drifted (or never framework-validated) → run a fresh smoke
    assert fresh_smoke_decision("s", "old", "older", "other") == "smoke"
    assert fresh_smoke_decision("s", None, None, None) == "smoke"


# ------------------------- ensure_fresh_smoke_before_cut -------------------------

class _FakeTool:
    """Stands in for RunValidationTool; records instantiations + executes."""
    instances = []

    def __init__(self, workspace=None):
        type(self).instances.append(self)
        self.executed = False

    async def execute(self):
        self.executed = True
        data = {"runhub_run_id": "run_1"} if getattr(type(self), "passes", True) else {}
        return types.SimpleNamespace(data=data, error_message="")


@pytest.fixture(autouse=True)
def _reset_fake_tool():
    _FakeTool.instances = []
    _FakeTool.passes = True
    yield


def _orch_for_cutcheck(tmp_path, validated_sig=None):
    orch = types.SimpleNamespace(
        output_dir=tmp_path,
        _logger=logging.getLogger("test_fresh_smoke"),
        hubs=types.SimpleNamespace(),
    )
    if validated_sig is not None:
        orch._smoke_backend_sig = validated_sig
    return orch


def _patch_tool(monkeypatch):
    import tools.validation_tools as vt
    monkeypatch.setattr(vt, "RunValidationTool", _FakeTool)


def test_no_drift_cuts_without_smoke(tmp_path, monkeypatch):
    _patch_tool(monkeypatch)
    root = _app(tmp_path, backend={"main.py": "app = 1\n"})
    orch = _orch_for_cutcheck(tmp_path, validated_sig=backend_source_signature(root))
    ok = asyncio.run(ensure_fresh_smoke_before_cut(orch))
    assert ok is True
    assert _FakeTool.instances == []  # cheap path: no docker boot when nothing drifted


def test_drift_runs_fresh_smoke_and_cuts_on_pass(tmp_path, monkeypatch):
    _patch_tool(monkeypatch)
    root = _app(tmp_path, backend={"main.py": "app = 1\n"})
    orch = _orch_for_cutcheck(tmp_path, validated_sig="stale-sig")
    ok = asyncio.run(ensure_fresh_smoke_before_cut(orch))
    assert ok is True
    assert len(_FakeTool.instances) == 1 and _FakeTool.instances[0].executed
    # the fresh pass re-stamps: the next cut attempt on the same tree is cheap
    assert orch._smoke_backend_sig == backend_source_signature(root)
    assert _FakeTool.instances and asyncio.run(ensure_fresh_smoke_before_cut(orch)) is True
    assert len(_FakeTool.instances) == 1  # no second boot


def test_drift_holds_cut_on_fresh_smoke_failure_without_churn(tmp_path, monkeypatch):
    _patch_tool(monkeypatch)
    _FakeTool.passes = False
    _app(tmp_path, backend={"main.py": "await None()  # cold-start crash\n"})
    orch = _orch_for_cutcheck(tmp_path, validated_sig="stale-sig")
    assert asyncio.run(ensure_fresh_smoke_before_cut(orch)) is False
    assert len(_FakeTool.instances) == 1
    # same failed tree on the next tick: still held, but NO second docker boot
    assert asyncio.run(ensure_fresh_smoke_before_cut(orch)) is False
    assert len(_FakeTool.instances) == 1
    # the lane lands a fix → sig changes → fresh smoke re-arms and passes → cut
    _FakeTool.passes = True
    (tmp_path / "app" / "backend" / "main.py").write_text("app = 1  # fixed\n")
    assert asyncio.run(ensure_fresh_smoke_before_cut(orch)) is True
    assert len(_FakeTool.instances) == 2


def test_kill_switch_disables(tmp_path, monkeypatch):
    _patch_tool(monkeypatch)
    monkeypatch.setenv("ENVGEN_FRESH_SMOKE_GATE", "0")
    _app(tmp_path, backend={"main.py": "app = 1\n"})
    orch = _orch_for_cutcheck(tmp_path, validated_sig="stale-sig")
    assert asyncio.run(ensure_fresh_smoke_before_cut(orch)) is True
    assert _FakeTool.instances == []


def test_best_effort_on_broken_orch(monkeypatch):
    _patch_tool(monkeypatch)
    orch = types.SimpleNamespace(_logger=logging.getLogger("t"))  # no output_dir
    assert asyncio.run(ensure_fresh_smoke_before_cut(orch)) is True
    assert _FakeTool.instances == []


# ----------------------------- cut-site wiring -----------------------------

def _deliver_orch(tmp_path):
    """The test_framework_deliver_trigger harness, extended with output_dir."""
    from multi_agent.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch._logger = logging.getLogger("t155")
    orch._project_delivered_event = threading.Event()
    orch.output_dir = tmp_path
    releases = []

    class _Api:
        def get_endpoints(self):
            return {"GET:/api/x": {"id": "GET:/api/x", "method": "GET", "path": "/api/x",
                                   "kind": None, "status": "implemented"}}

    class _Code:
        def create_release(self, tag, source="main", notes="", agent="codehub"):
            releases.append({"tag": tag})
            return {"id": tag, "tag": tag}

    orch.hubs = types.SimpleNamespace(registryhub=_Api(), codehub=_Code())
    orch._validate_delivery_gate = lambda: {"failed_checks": []}
    return orch, releases


def test_cut_held_when_fresh_smoke_gate_says_no(tmp_path, monkeypatch):
    import multi_agent.runtime.framework_validation as fv

    # Isolate the fresh-smoke gate: neutralize the orthogonal pre-release gates
    # (test-user squad #179 + page-build) that also sit on the cut path and would
    # otherwise defer this minimal harness before the fresh-smoke gate is reached.
    monkeypatch.setenv("ENVGEN_TESTUSER_SQUAD", "0")
    monkeypatch.setenv("ENVGEN_PAGES_BLOCKING", "0")

    async def _deny(orch):
        return False

    monkeypatch.setattr(fv, "ensure_fresh_smoke_before_cut", _deny)
    orch, releases = _deliver_orch(tmp_path)
    asyncio.run(orch._maybe_framework_deliver())
    assert releases == [] and getattr(orch, "_project_delivered", False) is False


def test_cut_proceeds_when_fresh_smoke_gate_clears(tmp_path, monkeypatch):
    import multi_agent.runtime.framework_validation as fv

    # Isolate the fresh-smoke gate: neutralize the orthogonal pre-release gates
    # (test-user squad #179 + page-build) that also sit on the cut path and would
    # otherwise defer this minimal harness before the release is cut.
    monkeypatch.setenv("ENVGEN_TESTUSER_SQUAD", "0")
    monkeypatch.setenv("ENVGEN_PAGES_BLOCKING", "0")

    async def _allow(orch):
        return True

    monkeypatch.setattr(fv, "ensure_fresh_smoke_before_cut", _allow)
    orch, releases = _deliver_orch(tmp_path)
    asyncio.run(orch._maybe_framework_deliver())
    assert len(releases) == 1 and orch._project_delivered is True


# ----------------------------- stamp-site wiring -----------------------------

def test_maybe_run_stamps_signature_on_pass_source_contract():
    """maybe_run must compute the backend sig BEFORE tool.execute() (the integration
    tree can be merged-into during the await) and stamp it in the PASSED branch."""
    import inspect
    from multi_agent.runtime.framework_validation import FrameworkValidation
    src = inspect.getsource(FrameworkValidation.maybe_run)
    pre = src.index("backend_source_signature")
    execute_at = src.index("await tool.execute()")
    assert pre < execute_at, "sig must be computed BEFORE the smoke boots"
    stamp_at = src.index("_smoke_backend_sig")
    assert stamp_at > execute_at, "stamp lands in the post-execute PASSED branch"
    # the stamp must sit inside the runhub_run_id (passed) conditional
    passed_branch = src.index('data.get("runhub_run_id")')
    assert stamp_at > passed_branch


# --------------------------- real-archive empiricism ---------------------------

_GM3_APP = (ROOT.parent / "generated" /
            "googlemaps-core-di.SUCCESS-gmrun3-3milestones-realdata" / "app")


@pytest.mark.skipif(not (_GM3_APP / "backend").is_dir(),
                    reason="gmrun3 archive not on this host")
def test_gmrun3_archive_custom_routes_edit_flips_signature(tmp_path):
    """The exact run-3 killer file (custom_routes.py, broken middleware landed 05:34,
    2min before the cut) is inside the signature surface: an edit to the ARCHIVE's real
    backend flips the sig → the cut would have demanded a fresh smoke, which the
    import-time-crashing backend fails → held instead of shipped."""
    work = tmp_path / "app"
    shutil.copytree(_GM3_APP / "backend", work / "backend")
    s1 = backend_source_signature(work)
    assert s1
    cr = work / "backend" / "custom_routes.py"
    assert cr.exists(), "gmrun3 backend has the lane-owned custom_routes.py"
    cr.write_text(cr.read_text(encoding="utf-8", errors="ignore")
                  + "\n# late middleware edit\n", encoding="utf-8")
    assert backend_source_signature(work) != s1
