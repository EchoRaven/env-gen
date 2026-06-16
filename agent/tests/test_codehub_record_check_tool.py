"""Round 8h smoke #18 follow-up — closed-by-construction pin for the
``codehub_record_check`` LLM-callable tool.

Smoke #18 surfaced that the orchestrator delivery gate
(orchestrator.py:1414-1473) requires ``build:sql_syntax``,
``build:docker_build``, ``build:npm_install``, ``build:backend_start``
and ``validation:api_smoke`` / ``validation:ui_smoke`` checks recorded
against CodeHub, but pre-fix the only callers were Python-internal
(step_pipeline.helpers, hub_registry) — no LLM-callable tool existed.

This test pins that:
  1. ``codehub_record_check`` is registered in HUB_TOOL_CLASSES and
     listed in the ``codehub_tools`` bundle for orchestrator, backend,
     frontend, and verifier profiles.
  2. The tool forwards (pr_id, name, status, evidence) to
     ``codehub.record_check`` with the calling agent's id as the actor.
  3. Verifier-authored ``build:sql_syntax`` ``success`` checks land in
     the PR's checks list and are queryable via ``codehub_list_checks``.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402

from tools.hub_tools import (  # noqa: E402
    HUB_TOOL_CLASSES,
    create_hub_tools as _create_hub_tools,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _find_record_check_tool(reg, agent_id="verifier"):
    for tool in _create_hub_tools(agent_id=agent_id, hub_workspace=reg):
        if getattr(tool, "NAME", "") == "codehub_record_check":
            return tool
    raise AssertionError("codehub_record_check tool not found")


class CodeHubRecordCheckToolRegistrationTests(unittest.TestCase):
    """The tool must be discoverable from HUB_TOOL_CLASSES + the
    codehub_tools bundle. A regression here means the orchestrator's
    delivery gate can't be satisfied even if the LLM tries."""

    def test_tool_class_registered_in_hub_tool_classes(self):
        names = {getattr(cls, "NAME", "") for cls in HUB_TOOL_CLASSES}
        self.assertIn("codehub_record_check", names)

    def test_tool_listed_in_codehub_tools_bundle(self):
        from multi_agent.tool_bundles import _bundle_codehub_tools
        from multi_agent.tool_runtime import (
            ToolAssemblyContext,
            ToolPermissionContext,
            ToolPoolBuilder,
        )

        # Spin up the bundle with the verifier as the carrying agent —
        # the bundle is profile-agnostic; we just need an agent_id
        # for the tool factory.
        with tempfile.TemporaryDirectory(prefix="rct_") as tmp:
            ctx = ToolAssemblyContext(
                agent_id="verifier",
                agent_type="verifier",
                hub_workspace=HubRegistry(Path(tmp)),
                workspace=Path(tmp),
                # Empty allowed_categories=None means "all categories
                # enabled" per category_enabled's contract — keeps the
                # bundle from being filtered out at add() time.
                permission_context=ToolPermissionContext(),
            )
            builder = ToolPoolBuilder(ctx)
            _bundle_codehub_tools(builder, ctx)
            tool_names = {
                getattr(t, "NAME", "") for t in builder.build()
            }
            self.assertIn("codehub_record_check", tool_names)


class CodeHubRecordCheckToolForwardingTests(unittest.TestCase):
    """The tool's ``_run`` must forward all four fields to
    ``codehub.record_check`` and stamp the calling agent id as actor."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rct_"))
        self.reg = HubRegistry(self.tmp)
        task = self.reg.workhub.create_task(
            title="t", assignee="backend", agent="orchestrator",
        )
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend",
            target="main",
            # Verifier needs to be in checks_authorized OR reviewers to
            # write checks under the record_check role gate. We use
            # the reviewers path for parity with how visual_review
            # tasks land verifier in the allowlist.
            reviewers=["frontend", "orchestrator", "verifier"],
            linked_tasks=[task["id"]],
            title="t",
            author="backend",
        )
        self.tool = _find_record_check_tool(self.reg, agent_id="verifier")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_verifier_can_record_build_sql_syntax_success(self):
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"],
            name="build:sql_syntax",
            status="success",
            evidence={"checked_files": ["schema.sql"], "tool": "psql --syntax-check"},
        ))
        self.assertTrue(result.success, f"tool failed: {result.error_message}")
        data = result.data
        self.assertEqual(data["name"], "build:sql_syntax")
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["pr_id"], self.pr["id"])

        # The check is queryable via codehub.list_checks(pr_id=...).
        checks = self.reg.codehub.list_checks(pr_id=self.pr["id"])
        names = {c["name"] for c in checks}
        self.assertIn("build:sql_syntax", names)

    def test_evidence_defaults_to_empty_mapping(self):
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"],
            name="validation:api_smoke",
            status="success",
        ))
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.data["evidence"], {})

    def test_role_denial_returns_error_result(self):
        """An agent not in {orchestrator, checks_authorized, reviewers}
        must get a structured error back (not silent success)."""
        unauthorized = _find_record_check_tool(self.reg, agent_id="frontend")
        # Open a separate PR whose reviewers don't include frontend
        # so the role gate fires for frontend.
        task = self.reg.workhub.create_task(
            title="t2", assignee="backend", agent="orchestrator",
        )
        denial_pr = self.reg.codehub.open_pull_request(
            branch="agent/backend2",
            target="main",
            reviewers=["verifier", "orchestrator"],
            linked_tasks=[task["id"]],
            title="t2",
            author="backend",
        )
        result = _run_async(unauthorized._run(
            pr_id=denial_pr["id"],
            name="build:docker_build",
            status="success",
        ))
        self.assertFalse(result.success)
        self.assertIn("role_denied", result.error_message)
        self.assertEqual(
            result.data.get("error"), "record_check_role_denied",
        )


if __name__ == "__main__":
    unittest.main()
