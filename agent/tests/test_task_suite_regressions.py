import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from workspace import Workspace  # noqa: E402
from tools.task_suite_executor import ExecuteTaskSuiteTool  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.orchestrator import Orchestrator  # noqa: E402


def _prepare_min_delivery_layout(out: Path):
    required_files = {
        "docker/docker-compose.yml": "services: {}",
        "design/README.md": "# Design",
        "design/spec.database.json": "{}",
        "design/spec.api.json": "{}",
        "design/spec.ui.json": "{}",
    }
    for rel, content in required_files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    for rel in ["app/backend/main.py", "app/frontend/main.js", "app/database/schema.sql", "tasks/tasks.yaml"]:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


class TaskSuiteRegressionTests(unittest.TestCase):
    def test_execute_task_suite_validate_only_reports_schema_issues(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = Workspace(root)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            (tasks_dir / "tasks.yaml").write_text(
                yaml.safe_dump(
                    {
                        "tasks": [
                            {
                                "id": "bad_task",
                                "execution_mode": "invalid_mode",
                                "actions": [{"type": "api_call", "params": {"method": "GET"}}],
                            }
                        ]
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            tool = ExecuteTaskSuiteTool(workspace=ws, agent_id="task_runner", include_browser=False)
            res = asyncio.run(tool.execute(validate_only=True))
            self.assertTrue(res.success)
            self.assertFalse(res.data["validation"]["valid"])
            codes = {issue["code"] for issue in res.data["validation"]["issues"]}
            self.assertIn("E_TASK_INVALID_MODE", codes)
            self.assertIn("E_API_INVALID_INPUT", codes)

    def test_execute_action_retries_retryable_failure(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(Path(td))
            tool = ExecuteTaskSuiteTool(workspace=ws, agent_id="task_runner", include_browser=False)
            calls = {"n": 0}

            async def flaky(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"success": False, "error": "connection refused", "error_code": "E_API_CONNECTION"}
                return {"success": True, "status": 200, "error_code": "OK"}

            tool._execute_action_once = flaky  # type: ignore[attr-defined]
            result = asyncio.run(
                tool._execute_action(  # type: ignore[attr-defined]
                    task_id="t1",
                    action={"type": "api_call", "params": {"url": "http://localhost:1"}},
                    idx=1,
                    execution_mode="api",
                    action_timeout_seconds=1,
                    action_retry_count=2,
                    action_retry_backoff_ms=0,
                )
            )
            self.assertTrue(result["success"])
            self.assertEqual(calls["n"], 2)

    def test_retry_to_remediate_and_dedupe_and_delivery_gate_soft_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _prepare_min_delivery_layout(root)
            crdt = HubRegistry(root)
            crdt.hubs.registryhub.register_endpoint("GET", "/health", schema={}, provider="backend", agent="backend", status="implemented")
            crdt.update_table("users", {"status": "implemented"}, agent="backend")
            crdt.hubs.workhub.update_ui_page("home", {"status": "implemented"}, agent="frontend")
            # PR 6 review follow-up (2026-05-30): the autonomous
            # delivery gate now folds in ``compute_deliverability``
            # (orchestrator.py:_validate_delivery_gate). The
            # soft-fail-only state is only reachable when no
            # deliverability dimension is failing. Satisfy each:
            #   * insert a passing RunHub run since session_start_ts
            #   * mark the minimal-layout entries intentionally dead
            #     so coverage_audit doesn't flag them (the layout
            #     has 1-byte stub files, not real consumers)
            run = crdt.hubs.runhub.record_run(
                branch="x", generated_dir="/g", agent="orchestrator",
            )
            raw = crdt.hubs.runhub.stores.runs.get(run["id"])
            raw["started_at"] = 2000.0
            raw["status"] = "completed"
            raw["fail_count"] = 0
            raw["probes"] = []
            raw["mcp_probes"] = []
            crdt.hubs.runhub.stores.runs.update(
                lambda m: m.set(run["id"], raw, "runhub"),
                change_info={"agent": "runhub"},
            )
            # Register a consumer for each table — the minimal
            # layout's 1-byte stub files don't reference the
            # topology, so ``coverage_audit`` would otherwise
            # mark the ``users`` table as a dead artifact.
            # (Endpoints/pages live by being attached to a file
            # path on the filesystem; tables live by having a
            # registered consumer.) NB: compute_deliverability
            # doesn't subtract the gate's coverage_allowlist —
            # only the deleted DeliverProjectTool path did. So
            # marking-intentionally-dead doesn't help here; a
            # real consumer is what satisfies coverage_audit.
            for name in (crdt.hubs.schema_hub.list_tables() or {}):
                crdt.hubs.schema_hub.register_table_consumer(
                    name, "app/backend/main.py", agent="backend",
                )

            crdt.record_validation_result(
                task_id="api_smoke_health",
                status="failed",
                agent="task_runner",
                summary="HTTP Error: 500",
                execution_mode="api",
                metadata={"check": "api_smoke"},
            )
            retry = crdt.handle_validation_failure(
                validation_task_id="api_smoke_health",
                publisher="user",
                max_auto_retries=1,
            )
            self.assertEqual(retry["action"], "retry")

            orch = Orchestrator.__new__(Orchestrator)
            orch.output_dir = root
            orch.crdt_workspace = crdt
            orch.hubs = crdt.hubs  # HubRegistry-compatible handle
            # Anchor session_start_ts BEFORE the run was inserted
            # so the runhub-since-session check passes.
            orch._session_start_ts = 1000.0
            gate = orch._validate_delivery_gate()
            self.assertEqual(gate["state"], "waiting_for_retry",
                              f"expected soft-fail-only, "
                              f"failed_checks={gate.get('failed_checks')}")
            self.assertTrue(gate["soft_fail_only"])

            remediate = crdt.handle_validation_failure(
                validation_task_id="api_smoke_health",
                publisher="user",
                max_auto_retries=1,
            )
            self.assertEqual(remediate["action"], "remediate")
            remediation_id = remediate["dev_task"]["id"]

            deduped = crdt.create_dev_task_from_validation_failure(
                validation_task_id="api_smoke_health",
                publisher="user",
            )
            self.assertEqual(deduped["id"], remediation_id)
            self.assertTrue(deduped.get("_deduped"))


if __name__ == "__main__":
    unittest.main()
