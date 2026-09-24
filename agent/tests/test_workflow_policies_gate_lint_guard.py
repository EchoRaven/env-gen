"""PR 3 of the hub-responsibility-split plan (rank 3) retired 13
gate methods from ``WorkHub`` into ``GateRegistry`` plus 2 dead
predicates (``is_design_approved``, ``is_visual_approved``)
removed entirely. Q2 of the plan (reviewer-confirmed) replaced the
"30-day deprecation window" with a **condition-based** retirement:
the delegate stays only until every in-tree caller migrates, then
it's deleted in the same PR — plus a **lint guard** that fails the
build if any future change adds a call to a retired name.

This file is that lint guard. It walks every Python file in the
generator runtime + the test tree using AST and fails the test if
any expression of the shape ``<chain>.workhub.<retired_name>(...)``
or ``<chain>.workhub.<deleted_dead_predicate>(...)`` appears. The
matching is on the call site, not text, so doc strings / comments
don't trigger false positives.

Allow-listed sites:
  * ``env_generator/llm_generator/multi_agent/runtime/gate_registry.py``
    — the new owner; it stores the page-store handle but never
    calls anything on a ``workhub`` chain.
  * This test file itself — to allow this very rule.

If a future PR genuinely needs to add a WorkHub method with one of
these retired names (e.g. someone re-introduces "is_visual_approved"
for a separate reason), the maintainer must explicitly:
  1. Update the RETIRED list below with a comment naming the new
     semantics; AND
  2. Justify in the PR description why the retired name is being
     resurrected — the lint guard's failure message includes a
     pointer back to this docstring.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
TESTS_DIR = ROOT / "tests"

if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


# Methods retired from WorkHub into GateRegistry in PR 3. Calling
# ``<any>.workhub.<NAME>(...)`` is forbidden anywhere in the tree;
# the call must go through ``<any>.gate_registry.<NAME>(...)``.
RETIRED_TO_GATE_REGISTRY = frozenset({
    "get_design_page",
    "register_visual_review_task", "get_visual_review",
    "list_pending_visual_reviews", "list_critical_visual_reviews",
    "submit_visual_review",
    "list_retros", "get_latest_retro_for_generation",
    "list_coverage_allowlist", "mark_path_intentionally_dead",
})

# Predicates deleted entirely in PR 3 (re-audit §7.3 dead-helper
# inventory). Any call to ``<any>.workhub.<NAME>(...)`` OR a free
# reference to ``<NAME>(`` anywhere is forbidden.
DELETED_DEAD_PREDICATES = frozenset({
    "is_design_approved",
    "is_visual_approved",
})

# Methods retired from RegistryHub into MCPRegistry in PR 4 (rank 4).
# Calling ``<any>.registryhub.<NAME>(...)`` is forbidden — the call must
# go through ``<any>.mcp_registry.<NAME>(...)``. The on-disk store
# stays on RegistryHub (path ``registryhub_mcp_registry.json`` unchanged for
# snapshot compatibility), but the method surface is gone.
RETIRED_TO_MCP_REGISTRY = frozenset({
    "register_mcp_server", "get_mcp_servers",
    "register_mcp_tool", "get_mcp_tools",
    "register_mcp_consumer", "get_mcp_consumers",
})

# Methods retired from RegistryHub into SchemaHub in PR 5 (rank 5).
# Calling ``<any>.registryhub.<NAME>(...)`` is forbidden — the call must
# go through ``<any>.schema_hub.<NAME>(...)``. The on-disk stores
# (``registryhub_tables.json``, ``registryhub_table_consumers.json``,
# ``registryhub_seed_registrations.json``,
# ``registryhub_table_breaking_changes.json``) stay on RegistryHub for
# snapshot compatibility.
# PR 5's SchemaHub split was reverted: table/schema methods live on
# RegistryHub directly again. The lint guard set is now empty (kept for
# future re-extraction).
RETIRED_TO_SCHEMA_HUB = frozenset()

# Files that are allowed to mention the names. The guard scans these
# but doesn't fire on hits.
ALLOWED_FILES = frozenset({
    # New owners — they don't actually call workhub.X /
    # registryhub.<retired> but might mention method names in comments.
    str(LLM_DIR / "multi_agent" / "runtime" / "gate_registry.py"),
    str(LLM_DIR / "multi_agent" / "runtime" / "mcp_registry.py"),
    # This lint guard itself + the dead-helper inventory test.
    str(Path(__file__).resolve()),
    str(TESTS_DIR / "test_design_visual_gate_wiring_inventory.py"),
})


def _iter_py_files():
    """Walk both the generator source and the test tree. Skip
    caches, agent logs, and the lint guard's own allow-list."""
    skip_parts = {"__pycache__", ".git", "node_modules", ".pytest_cache",
                    ".agent_logs"}
    for base in (LLM_DIR, TESTS_DIR):
        for path in base.rglob("*.py"):
            if any(part in skip_parts for part in path.parts):
                continue
            if str(path.resolve()) in ALLOWED_FILES:
                continue
            yield path


def _scan_calls(path: Path, forbidden_attrs: frozenset, receiver_attr: str):
    """For ``path``, return a list of (lineno, source-line, attr) for
    every ``<expr>.<receiver_attr>.<attr>(...)`` call where ``attr``
    is in ``forbidden_attrs``."""
    try:
        text = path.read_text()
        tree = ast.parse(text)
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    lines = text.split("\n")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in forbidden_attrs:
            continue
        recv = func.value
        if not (isinstance(recv, ast.Attribute) and recv.attr == receiver_attr):
            continue
        lineno = node.lineno
        source_line = lines[lineno - 1].strip() if lineno - 1 < len(lines) else ""
        hits.append((lineno, source_line, func.attr))
    return hits


def _scan_workhub_calls(path: Path):
    """Legacy alias retained for PR 3 backwards compatibility — scans
    for ``<expr>.workhub.<retired-or-deleted>(...)`` calls."""
    return _scan_calls(
        path,
        RETIRED_TO_GATE_REGISTRY | DELETED_DEAD_PREDICATES,
        "workhub",
    )


class NoCallerUsesRetiredWorkHubGateMethods(unittest.TestCase):
    """The Q2 enforcement: zero ``<expr>.workhub.<retired_name>(...)``
    call sites in the entire tree (modulo the explicit allow-list).
    If a future commit accidentally adds one, this test fails with a
    pointer to the new owner."""

    def test_no_retired_workhub_gate_call_sites_in_tree(self):
        offenders = []
        for path in _iter_py_files():
            for lineno, source, attr in _scan_workhub_calls(path):
                # Build a structured offender record.
                rel = path.relative_to(ROOT)
                if attr in DELETED_DEAD_PREDICATES:
                    suggestion = (
                        f"{attr} was DELETED in PR 3 (re-audit §7.3 "
                        f"dead helper). If you genuinely need an "
                        f"approval check, read "
                        f"``page.get('status') == 'approved'`` from "
                        f"``GateRegistry.get_{('design' if 'design' in attr else 'visual_review')}_page``."
                    )
                else:
                    suggestion = (
                        f"{attr} was retired to GateRegistry. "
                        f"Replace ``<expr>.workhub.{attr}(...)`` with "
                        f"``<expr>.gate_registry.{attr}(...)``."
                    )
                offenders.append(f"{rel}:{lineno}  {source}\n    → {suggestion}")
        self.assertFalse(
            offenders,
            "PR 3 retired these gate methods to GateRegistry. The "
            "following call sites still use the old workhub.X "
            "interface:\n\n" + "\n\n".join(offenders) + "\n\n"
            "See ``tests/test_workflow_policies_gate_lint_guard.py`` "
            "for the full list of retired names and the migration "
            "pattern. If a method genuinely needs to be resurrected "
            "on WorkHub, update RETIRED_TO_GATE_REGISTRY / "
            "DELETED_DEAD_PREDICATES with a justification."
        )


class NoCallerUsesRetiredRegistryHubMCPMethods(unittest.TestCase):
    """PR 4 Q2 enforcement: zero ``<expr>.registryhub.<retired_name>(...)``
    call sites in the entire tree. If a future commit accidentally
    adds one, this test fails with a pointer to MCPRegistry."""

    def test_no_retired_registryhub_mcp_call_sites_in_tree(self):
        offenders = []
        for path in _iter_py_files():
            for lineno, source, attr in _scan_calls(
                path, RETIRED_TO_MCP_REGISTRY, "registryhub",
            ):
                rel = path.relative_to(ROOT)
                offenders.append(
                    f"{rel}:{lineno}  {source}\n"
                    f"    → {attr} was retired to MCPRegistry in PR 4. "
                    f"Replace ``<expr>.registryhub.{attr}(...)`` with "
                    f"``<expr>.mcp_registry.{attr}(...)``."
                )
        self.assertFalse(
            offenders,
            "PR 4 retired these MCP methods to MCPRegistry. The "
            "following call sites still use the old registryhub.X "
            "interface:\n\n" + "\n\n".join(offenders),
        )


class NoCallerUsesRetiredRegistryHubSchemaMethods(unittest.TestCase):
    """PR 5 Q2 enforcement: zero ``<expr>.registryhub.<retired_name>(...)``
    call sites for table-class methods."""

    def test_no_retired_registryhub_schema_call_sites_in_tree(self):
        offenders = []
        for path in _iter_py_files():
            for lineno, source, attr in _scan_calls(
                path, RETIRED_TO_SCHEMA_HUB, "registryhub",
            ):
                rel = path.relative_to(ROOT)
                offenders.append(
                    f"{rel}:{lineno}  {source}\n"
                    f"    → {attr} was retired to SchemaHub in PR 5. "
                    f"Replace ``<expr>.registryhub.{attr}(...)`` with "
                    f"``<expr>.schema_hub.{attr}(...)``."
                )
        self.assertFalse(
            offenders,
            "PR 5 retired these table/seed methods to SchemaHub. "
            "The following call sites still use the old registryhub.X "
            "interface:\n\n" + "\n\n".join(offenders),
        )


class GetTableConsumersSignatureParity(unittest.TestCase):
    """``RegistryHub.get_table_consumers(table_name)`` and
    ``RegistryHub.get_consumers(endpoint_id)`` must share signature shape so
    coverage audits iterate over both uniformly."""

    def test_get_table_consumers_signature_parity_with_get_consumers(self):
        import inspect
        from multi_agent.runtime.registryhub import RegistryHub
        endpoint_sig = inspect.signature(RegistryHub.get_consumers)
        table_sig = inspect.signature(RegistryHub.get_table_consumers)
        endpoint_params = [
            p for p in endpoint_sig.parameters.values() if p.name != "self"
        ]
        table_params = [
            p for p in table_sig.parameters.values() if p.name != "self"
        ]
        self.assertEqual(len(endpoint_params), 1)
        self.assertEqual(len(table_params), 1)
        for ep, tp in zip(endpoint_params, table_params):
            self.assertEqual(ep.kind, tp.kind)
            self.assertEqual(ep.default, tp.default)

    def test_get_table_consumers_returns_list_shape(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            reg.registryhub.register_table(
                "users", schema={"id": "int"},
                provider="backend", agent="backend",
            )
            reg.registryhub.register_table_consumer(
                "users", "src/users.py", "backend",
            )
            result = reg.registryhub.get_table_consumers("users")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], dict)
            self.assertEqual(result[0]["table_name"], "users")
            # Empty list for unknown table — same posture as
            # RegistryHub.get_consumers for unknown endpoint.
            self.assertEqual(reg.schema_hub.get_table_consumers("nope"), [])


class RetiredListMatchesGateRegistry(unittest.TestCase):
    """Sanity: every name in ``RETIRED_TO_GATE_REGISTRY`` must actually
    exist on ``GateRegistry``. If a typo lands in this test file, the
    guard would silently pass — pin the contract here."""

    def test_every_retired_name_is_in_gate_registry(self):
        from multi_agent.runtime.gate_registry import GateRegistry
        missing = [
            n for n in RETIRED_TO_GATE_REGISTRY
            if not hasattr(GateRegistry, n)
        ]
        self.assertFalse(
            missing,
            f"RETIRED_TO_GATE_REGISTRY lists method(s) {sorted(missing)} "
            "that are NOT on GateRegistry. Either rename the entry or "
            "add the method to GateRegistry.",
        )

    def test_every_deleted_predicate_has_no_workhub_attr(self):
        """The dead predicates should be GONE from WorkHub."""
        from multi_agent.runtime.hubs.workhub.service import WorkHub
        for name in DELETED_DEAD_PREDICATES:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(WorkHub, name),
                    f"WorkHub still has ``{name}`` — PR 3 was supposed "
                    f"to delete it (re-audit §7.3 dead-helper). "
                    "Either remove the method or remove the entry "
                    "from DELETED_DEAD_PREDICATES (and explain why).",
                )

    def test_every_retired_mcp_name_is_in_mcp_registry(self):
        """PR 4: every name in ``RETIRED_TO_MCP_REGISTRY`` must exist
        on MCPRegistry. Pins the contract so a typo here doesn't
        silently make the guard pass."""
        from multi_agent.runtime.mcp_registry import MCPRegistry
        missing = [
            n for n in RETIRED_TO_MCP_REGISTRY
            if not hasattr(MCPRegistry, n)
        ]
        self.assertFalse(
            missing,
            f"RETIRED_TO_MCP_REGISTRY lists method(s) {sorted(missing)} "
            "that are NOT on MCPRegistry.",
        )

    def test_retired_mcp_methods_are_gone_from_registryhub(self):
        from multi_agent.runtime.registryhub import RegistryHub
        for name in RETIRED_TO_MCP_REGISTRY:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(RegistryHub, name),
                    f"RegistryHub still has ``{name}`` — PR 4 was supposed "
                    "to retire it. Either drop the delegate or remove "
                    "the entry from RETIRED_TO_MCP_REGISTRY (and "
                    "explain why).",
                )

    def test_no_dead_attach_scaffolding_on_workhub_or_registryhub(self):
        """PR 3 review cleanup: ``WorkHub.attach_gate_registry`` /
        ``RegistryHub.attach_mcp_registry`` / ``RegistryHub.attach_schema_hub``
        were thin-delegate scaffolding from the migration window.
        After PRs 3-5 deleted the delegates entirely (single
        source of truth: each new registry owns the methods),
        those setters had no readers — keeping them invites a
        future maintainer to "fix" a bug by storing a registry
        they think the hub will forward to.

        ``RunHub.attach_mcp_registry`` IS live (RunHub reads
        ``self.mcp_registry`` in its MCP probe). Don't touch it."""
        from multi_agent.runtime.hubs.workhub.service import WorkHub
        from multi_agent.runtime.registryhub import RegistryHub
        dead = [
            (WorkHub, "attach_gate_registry"),
            (WorkHub, "_gate_registry"),
            (RegistryHub, "attach_mcp_registry"),
            (RegistryHub, "_mcp_registry_ref"),
            (RegistryHub, "attach_schema_hub"),
            (RegistryHub, "_schema_hub_ref"),
        ]
        offenders = []
        for cls, attr in dead:
            if hasattr(cls, attr):
                offenders.append(f"{cls.__name__}.{attr}")
        # Class-level inspection won't catch instance-only attrs
        # set in __init__. Walk the source to be sure.
        import inspect
        for cls, attr in dead:
            src = inspect.getsource(cls)
            if f"self.{attr} = " in src or f"def {attr}" in src:
                offenders.append(
                    f"{cls.__name__}.{attr} (referenced in source)"
                )
        self.assertFalse(
            offenders,
            "Dead-scaffolding attribute/setter resurfaced on "
            "WorkHub/RegistryHub:\n  " + "\n  ".join(offenders) +
            "\nIf you legitimately need a back-ref to a registry "
            "from a hub, justify in the PR description and remove "
            "from this list. RunHub.attach_mcp_registry is "
            "deliberately excluded — RunHub DOES read mcp_registry.",
        )

    def test_orphan_valid_review_states_constant_not_on_workhub(self):
        """``_VALID_DESIGN_REVIEW_STATES`` was deleted from GateRegistry
        on 2026-06-02 (the design submit-for-review surface retired in
        favor of the orchestrator-hosted kickoff meeting). PR 3 review
        previously found a stale copy still on ``WorkHub`` — orphan
        after the original PR 3 retirement. Pin that the WorkHub copy
        stays gone — and would-be re-introduction on EITHER class is
        caught here."""
        from multi_agent.runtime.hubs.workhub.service import WorkHub
        from multi_agent.runtime.gate_registry import GateRegistry
        self.assertFalse(
            hasattr(WorkHub, "_VALID_DESIGN_REVIEW_STATES"),
            "WorkHub regained ``_VALID_DESIGN_REVIEW_STATES`` — the "
            "constant was retired entirely on 2026-06-02. If you "
            "brought it back, justify the use site (design approval "
            "is now decided in the orchestrator-hosted kickoff "
            "meeting).",
        )
        self.assertFalse(
            hasattr(GateRegistry, "_VALID_DESIGN_REVIEW_STATES"),
            "GateRegistry regained ``_VALID_DESIGN_REVIEW_STATES`` — "
            "the constant was retired entirely on 2026-06-02 (kickoff "
            "meeting replaces the per-draft review handshake).",
        )


if __name__ == "__main__":
    unittest.main()
