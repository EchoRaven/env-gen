"""PR 6 of the hub-responsibility-split plan
(``docs/hub_responsibility_split_plan.md``, rank 6): profile
rewiring + ghost-tool sweep.

The reviewer's framing was "update agents_config.yaml profiles to
include the new module tool bundles where appropriate". After
PRs 3-5, several tool wrappers retain their historical
``registryhub_*`` / ``workhub_*`` NAMEs (these are LLM-facing contracts;
renaming would cost prompt churn) even though they now route
through ``GateRegistry`` / ``MCPRegistry`` / ``SchemaHub``. That's
intentional, but it creates a drift surface: a future commit could
accidentally rewire a tool's body back to the old hub and the
mismatch wouldn't surface anywhere visible.

This regression test pins the inventory. For each retired-method
name (from the PR 3 / 4 / 5 sets the lint guard already tracks),
it walks ``tools/hub_tools.py`` AST and finds the tool class that
calls that method, then asserts the call routes through the NEW
hub (gate_registry / mcp_registry / schema_hub), NOT the legacy
``registryhub`` / ``workhub`` receiver. A future commit that quietly
flips a tool back to ``self._hubs.registryhub.register_table(...)``
fails this test with a pointer at the call site.

Ghost-tool sweep: ``test_no_ghost_tool_references.py`` already
fences "tool name in prompt must exist in registry". This file
complements it with "tool's implementation must route through the
hub its docstring claims".
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
HUB_TOOLS_PATH = LLM_DIR / "tools" / "hub_tools.py"

if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


# Method names retired during PR 3 / 4 / 5. The same lists live in
# ``test_workflow_policies_gate_lint_guard.py`` — keep both in sync.
# (Importing from there would create a test-to-test dependency; the
# lint guard tests this list matches the runtime classes, so a typo
# here surfaces via THIS test's parallel check.)
RETIRED_TO_GATE_REGISTRY = frozenset({
    "get_design_page",
    "register_visual_review_task", "get_visual_review",
    "list_pending_visual_reviews", "list_critical_visual_reviews",
    "submit_visual_review",
    "list_retros", "get_latest_retro_for_generation",
    "list_coverage_allowlist", "mark_path_intentionally_dead",
})
RETIRED_TO_MCP_REGISTRY = frozenset({
    "register_mcp_server", "get_mcp_servers",
    "register_mcp_tool", "get_mcp_tools",
    "register_mcp_consumer", "get_mcp_consumers",
})
# PR 5's SchemaHub split was reverted — methods live on RegistryHub again.
RETIRED_TO_SCHEMA_HUB = frozenset()

NAME_TO_HUB = {
    **{n: "gate_registry" for n in RETIRED_TO_GATE_REGISTRY},
    **{n: "mcp_registry" for n in RETIRED_TO_MCP_REGISTRY},
    **{n: "schema_hub" for n in RETIRED_TO_SCHEMA_HUB},
}


def _find_method_call_receivers_in_hub_tools(method_name: str) -> list:
    """Walk ``tools/hub_tools.py`` AST and return every receiver-source
    used for ``<expr>.<method_name>(...)`` calls. The receiver is
    serialised via ``ast.unparse`` so e.g.
    ``self._hubs.gate_registry`` shows up as the literal string."""
    text = HUB_TOOLS_PATH.read_text()
    tree = ast.parse(text)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != method_name:
            continue
        try:
            recv = ast.unparse(func.value)
        except Exception:
            continue
        out.append((node.lineno, recv))
    return out


class HubToolImplementationsRouteThroughNewHubs(unittest.TestCase):
    """For each retired method name, every call site inside
    ``tools/hub_tools.py`` must route through the NEW hub
    (``gate_registry`` / ``mcp_registry`` / ``schema_hub``), not the
    legacy ``registryhub`` / ``workhub`` receiver. The lint guard
    (``test_workflow_policies_gate_lint_guard.py``) checks the
    rest of the tree; this test focuses on the tool wrappers
    specifically because their tool NAMEs (registryhub_X / workhub_X)
    still suggest the old hub — drift is hardest to spot there."""

    def test_every_retired_call_in_hub_tools_routes_to_new_hub(self):
        offenders = []
        for method, expected_hub in NAME_TO_HUB.items():
            for lineno, recv in _find_method_call_receivers_in_hub_tools(method):
                # Acceptable receivers: any chain ending with the new
                # hub attribute (e.g. self._hubs.schema_hub,
                # registry.gate_registry).
                if recv.endswith(f".{expected_hub}"):
                    continue
                offenders.append(
                    f"hub_tools.py:{lineno}  "
                    f"{recv}.{method}(...)  → should route through "
                    f"``{expected_hub}.{method}(...)``"
                )
        self.assertFalse(
            offenders,
            "Tool wrappers in ``tools/hub_tools.py`` are calling "
            "retired methods through the OLD hub receiver. Either "
            "fix the call site to use the new hub OR remove the "
            "entry from the retired-method set in PR 3/4/5's "
            "lint guard if the retirement was rolled back:\n\n"
            + "\n\n".join(offenders),
        )


class ToolNamesRemainStableAcrossRetirement(unittest.TestCase):
    """The reviewer's PR 6 framing was "rewire profiles where
    appropriate". Tool NAMEs (e.g. ``registryhub_register_table``)
    stay stable because they are LLM-facing contracts — renaming
    would force a prompt+test sweep across every agent profile.
    Pin a few historically-stable names so a future PR that
    *does* rename them does so consciously."""

    def test_critical_tool_names_remain_registryhub_prefixed(self):
        """These tool names appear in prompt templates and the LLM
        is trained against them. If a future commit renames them
        to ``schemahub_*``, this test fails — the maintainer must
        either roll back the rename OR coordinate the prompt sweep
        + this assertion update in the same PR."""
        text = HUB_TOOLS_PATH.read_text()
        for stable_name in (
            "registryhub_register_table",
            "registryhub_list_tables",
            "registryhub_register_table_consumer",
            "registryhub_get_table_breaking_changes",
        ):
            with self.subTest(name=stable_name):
                self.assertIn(
                    f'NAME = "{stable_name}"', text,
                    f"Tool name {stable_name!r} no longer present "
                    f"in tools/hub_tools.py. If you renamed it as "
                    f"part of a deliberate PR-6-followup, also "
                    f"sweep the prompts and update this test.",
                )

    def test_critical_workhub_tool_names_remain_stable(self):
        text = HUB_TOOLS_PATH.read_text()
        for stable_name in (
            "workhub_create_document",
            "registryhub_register_ui_page",
            "workhub_task",
        ):
            with self.subTest(name=stable_name):
                self.assertIn(
                    f'NAME = "{stable_name}"', text,
                    f"Tool name {stable_name!r} no longer present; "
                    f"prompts reference it.",
                )


class RetiredMethodSetsMatchTheLintGuard(unittest.TestCase):
    """Drift check: if PR 3/4/5 retired sets in
    ``test_workflow_policies_gate_lint_guard.py`` ever change, this
    file's sets MUST match. Otherwise the inventory and the lint
    guard report different "retired" surfaces."""

    def test_gate_registry_set_matches(self):
        from test_workflow_policies_gate_lint_guard import (
            RETIRED_TO_GATE_REGISTRY as canonical,
        )
        self.assertEqual(RETIRED_TO_GATE_REGISTRY, canonical)

    def test_mcp_registry_set_matches(self):
        from test_workflow_policies_gate_lint_guard import (
            RETIRED_TO_MCP_REGISTRY as canonical,
        )
        self.assertEqual(RETIRED_TO_MCP_REGISTRY, canonical)

    def test_schema_hub_set_matches(self):
        from test_workflow_policies_gate_lint_guard import (
            RETIRED_TO_SCHEMA_HUB as canonical,
        )
        self.assertEqual(RETIRED_TO_SCHEMA_HUB, canonical)


if __name__ == "__main__":
    unittest.main()
