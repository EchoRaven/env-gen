"""E2E: register MCP -> probe failure routes to bug -> dead tool blocks deliver."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402


class _FakeCompose:
    def __init__(self):
        self.up_called = False
        self.down_called = False
    def up(self, timeout=180.0):
        self.up_called = True
        return ComposeResult(returncode=0, stdout="up ok")
    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _FakeHealthyHC:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.05)


def _passing_http_probe(plan):
    return {"status_code": 200, "body_excerpt": "ok",
            "transport_error": None, "latency_ms": 5.0}


def _agent(reg, gen_id=7000.0, agent_type="orchestrator", app_root=None):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = str(app_root) if app_root else None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


def _insert_passing_run(reg, started_at):
    """Satisfy the Cutover 24 RunHub-since-session gate."""
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class MCPE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp_e2e_"))
        self.reg = HubRegistry(self.tmp / "hub")
        _add_retro(self.reg, 7000.0)
        # Cutover 24: satisfy RunHub-since-session gate (gen_id=7000.0)
        _insert_passing_run(self.reg, started_at=7001.0)
        # Subscriptions
        collect_hub_pulse(self.reg, "debugger")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_mcp_probe_lands_in_bug_orch_inbox(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        crashing_probe = lambda s: {"healthy": False, "detail": "exited rc=1"}
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=crashing_probe)
        # run_failed event should reach BugTriageOrch via subscription
        events = self.reg.eventhub.list_inbox("debugger", unread_only=False)
        mcp_failures = []
        for ev in events:
            if ev.get("event_type") == "run_failed":
                payload = ev.get("payload") or {}
                if (payload.get("bug_artifacts") or {}).get("affected_mcp_server"):
                    mcp_failures.append(ev)
        self.assertGreaterEqual(len(mcp_failures), 1)

    # ``test_dead_mcp_tool_blocks_deliver`` /
    # ``test_dead_mcp_tool_unblocked_after_consumer_registered``
    # used to live here. They exercised the coverage gate inside
    # ``DeliverProjectTool.execute`` via a MagicMock that injected
    # ``hub_registry`` — but production agents store hubs as
    # ``self._hubs``, never ``hub_registry``. The gate was dead-on-
    # production (see the 2026-05-30 review-cleanup commit + the
    # pin ``test_deliver_project_tool_no_dead_hub_registry_reads``).
    # The MCP dead-tool detection logic itself is tested directly
    # against ``coverage_audit.scan_dead_mcp_tools`` in
    # ``test_coverage_audit_mcp.py``.


if __name__ == "__main__":
    unittest.main()
