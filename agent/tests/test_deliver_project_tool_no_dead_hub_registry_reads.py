"""PR 6 review cleanup (2026-05-30): pin against re-introduction
of the dead ``self.agent.hub_registry`` pattern in
``DeliverProjectTool.execute``.

Background:

  * The reviewer flagged a "secondary retro gate" in
    ``DeliverProjectTool.execute`` as dead — it read
    ``getattr(self.agent, "hub_registry", None)`` but production
    agents expose hubs as ``self._hubs`` (see
    ``multi_agent/agents/runtime/tooling.set_hubs``), never
    ``hub_registry``. ``if registry is not None`` short-circuited
    every call on the production code path.
  * Investigation surfaced that the SAME dead pattern was repeated
    in five gates inside the same method: retro / coverage /
    visual / seed / runhub-since-session. All five were dead.
    Tests exercised them via ``MagicMock(... hub_registry=reg)``
    — testing the gate LOGIC but the production WIRING never
    reached it.
  * The review-cleanup commit deleted all five blocks. This file
    pins that they stay deleted (or, equivalently, that any
    future attempt to read ``self.agent.hub_registry`` from any
    Tool in this module fails the build).

Why an AST-level pin (not just "all 5 gone today"):

  * Hand-deletion repeats the historical mistake of someone
    inadvertently writing the same dead pattern later (e.g.
    porting a similar gate into a new Tool in this file). A scan
    is cheap and catches the class.
  * The intent ("read hubs from an agent") is fine — the bug is
    the attribute name. If a future commit wants to read hubs
    from the agent, use ``self.agent._hubs``. Update this guard
    only if the pattern itself becomes safe (e.g. agents grow a
    ``hub_registry`` alias).
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
TOOL_FILE = LLM_DIR / "tools" / "agent_interaction_tools.py"

if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _find_dead_hub_registry_reads_in_tool_module() -> list:
    """Return list of (lineno, source) for every
    ``...self.agent.hub_registry...`` reference in
    ``agent_interaction_tools.py``. Both attribute access
    (``self.agent.hub_registry``) and ``getattr`` lookups
    (``getattr(self.agent, "hub_registry", ...)``) count.
    Documentation/comment mentions of the attribute don't —
    the scan is AST-level."""
    text = TOOL_FILE.read_text()
    tree = ast.parse(text)
    lines = text.split("\n")
    hits = []
    for node in ast.walk(tree):
        # Match attribute access: self.agent.hub_registry
        if isinstance(node, ast.Attribute) and node.attr == "hub_registry":
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "agent"
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                lineno = node.lineno
                source = lines[lineno - 1].strip() if lineno - 1 < len(lines) else ""
                hits.append((lineno, source))
        # Match getattr(self.agent, "hub_registry", ...)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) < 2:
                continue
            target = node.args[0]
            name_arg = node.args[1]
            is_self_agent = (
                isinstance(target, ast.Attribute)
                and target.attr == "agent"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            )
            is_hub_registry_literal = (
                isinstance(name_arg, ast.Constant)
                and name_arg.value == "hub_registry"
            )
            if is_self_agent and is_hub_registry_literal:
                lineno = node.lineno
                source = lines[lineno - 1].strip() if lineno - 1 < len(lines) else ""
                hits.append((lineno, source))
    return hits


class DeliverProjectToolHasNoDeadHubRegistryReads(unittest.TestCase):
    def test_zero_self_agent_hub_registry_reads_in_module(self):
        """``hub_registry`` is a TOOL-level attribute (set on
        coverage_tools, visual_review_tools, etc.). Agents expose
        hubs as ``self._hubs`` via ``set_hubs``. Reading
        ``self.agent.hub_registry`` is always None on production
        and therefore a guaranteed-dead gate. Pin zero."""
        hits = _find_dead_hub_registry_reads_in_tool_module()
        self.assertFalse(
            hits,
            "Dead ``self.agent.hub_registry`` pattern reappeared "
            "in tools/agent_interaction_tools.py:\n"
            + "\n".join(f"  line {ln}: {src}" for ln, src in hits)
            + "\n\nProduction agents store hubs at ``self._hubs`` "
            "(see ``multi_agent/agents/runtime/tooling.set_hubs``). "
            "If your new code needs the registry, read "
            "``self.agent._hubs`` instead. The historical "
            "``hub_registry`` attribute was only ever set by test "
            "MagicMocks — production never had it.",
        )


class ProductionAgentHasNoHubRegistryAttribute(unittest.TestCase):
    """Defence in depth: pin the agent-class invariant that the
    deleted gates were unknowingly depending on. If a future commit
    adds an ``agent.hub_registry`` instance attribute, the dead-
    pattern guard above stops being meaningful — this test fires so
    the maintainer must explicitly decide whether to ALSO resurrect
    the gates' wiring.

    Granularity matters here: ``set_hubs`` already mentions
    ``hub_registry`` in a textual comment AND injects
    ``tool.hub_registry = hubs`` into TOOL instances (the
    coverage_tools / visual_review_tools etc. that hold the
    registry on themselves). That tool-side attribute is fine —
    the dead gates read ``self.agent.hub_registry``, which is the
    AGENT-side attribute. So this test specifically looks for
    ``self.hub_registry = ...`` assignment on agent classes
    (AgentTooling and its concrete subclasses), not for any
    mention of the string."""

    def test_no_agent_class_assigns_self_hub_registry(self):
        """AST scan of every class in
        ``multi_agent/agents/`` for ``self.hub_registry = …``
        assignments. ``self._hubs`` is the canonical attribute;
        any new ``self.hub_registry`` assignment on an agent is
        a regression."""
        AGENTS_DIR = LLM_DIR / "multi_agent" / "agents"
        offenders = []
        for path in AGENTS_DIR.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text()
                tree = ast.parse(text)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (isinstance(target, ast.Attribute)
                            and target.attr == "hub_registry"
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        offenders.append(
                            f"{path.relative_to(LLM_DIR)}:{node.lineno}"
                        )
        self.assertFalse(
            offenders,
            "An agent class introduced ``self.hub_registry = …`` "
            "assignment(s):\n  " + "\n  ".join(offenders) +
            "\n\nIf this is intentional, also revisit the gates "
            "deleted from ``DeliverProjectTool.execute`` in the "
            "2026-05-30 review-cleanup commit — they may now be "
            "legitimately wireable via the new attribute. Update "
            "this test's allow-list when doing so."
        )


if __name__ == "__main__":
    unittest.main()
