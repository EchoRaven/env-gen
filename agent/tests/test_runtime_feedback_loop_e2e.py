"""End-to-end integration test for the runtime feedback loop (Cutover 12).

Proves: RunHub probe failure -> EventHub fan-out (via Cutover-12 subscriptions)
        -> BugTriageOrch inbox -> triage creates WorkHub bug task
        -> owning agent's hub_pulse shows the assigned bug.

No LLM involved. All IO mocked. This test is the canonical proof that the
post-Cutover-11 architecture closes the loop without manual intervention.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.bug_triage import resolve_owning_agent  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402


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


def _probe_runner_returning(status_code):
    def _runner(plan):
        return {"status_code": status_code, "body_excerpt": "boom",
                "transport_error": None, "latency_ms": 10}
    return _runner


class RuntimeFeedbackLoopE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="loop_e2e_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runhub_failure_reaches_bug_triage_orchestrator_inbox(self) -> None:
        # 1. Register endpoint with backend as owner
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")

        # 2. Pulse for debugger -> installs subscriptions
        collect_hub_pulse(self.reg, "debugger")
        subs = self.reg.eventhub.get_subscriptions("debugger")
        self.assertEqual(len(subs), 4)

        # 3. Trigger a failing RunHub run
        run = self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(500))
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["fail_count"], 1)

        # 4. The run_failed event must be in debugger's inbox
        inbox = self.reg.eventhub.list_inbox("debugger", unread_only=False)
        self.assertIsNotNone(inbox)
        run_failed_items = [ev for ev in inbox if ev.get("event_type") == "run_failed"]
        self.assertEqual(len(run_failed_items), 1,
                          "BugTriageOrch inbox should contain exactly one run_failed event")

    def test_triage_creates_bug_task_and_backend_pulse_sees_it(self) -> None:
        # 1. Wire endpoint owned by backend
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")

        # 2. Install subs and trigger failure
        collect_hub_pulse(self.reg, "debugger")
        self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(500))

        # 3. BugTriageOrch reads the inbox and triages (simulating what the LLM would do)
        inbox = self.reg.eventhub.list_inbox("debugger", unread_only=False)
        failure_event = next(e for e in inbox if e and e.get("event_type") == "run_failed")
        payload = failure_event["payload"]
        artifacts = payload["bug_artifacts"]
        owner = resolve_owning_agent(self.reg, artifacts)
        self.assertEqual(owner, "backend")

        bug = self.reg.workhub.create_task(
            title=payload["title"],
            description=f"From RunHub failure: {payload['title']}",
            assignee=owner, agent="debugger",
            kind="bug", severity=payload["severity"], bug_state="assigned",
            source="runhub", bug_artifacts=artifacts)

        # 4. Backend's pulse must now show the assigned bug
        backend_report = collect_hub_pulse(self.reg, "backend")
        assigned = backend_report.get("assigned_bugs") or []
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]["id"], bug["id"])
        self.assertEqual(assigned[0]["title"], payload["title"])

    def test_passing_run_does_not_create_inbox_noise_for_bug_orch(self) -> None:
        # When a run passes, only run_completed fires (priority=normal); run_failed must not.
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")
        collect_hub_pulse(self.reg, "debugger")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(200))
        self.assertEqual(run["status"], "completed")
        inbox = self.reg.eventhub.list_inbox("debugger", unread_only=False)
        types = [ev.get("event_type") for ev in inbox if ev]
        self.assertNotIn("run_failed", types)
        # run_completed should reach (its priority is "normal" >= the "normal" floor)
        self.assertIn("run_completed", types)


if __name__ == "__main__":
    unittest.main()
