"""Reviewer re-audit (2026-05-29) HIGH #3:
HubConsistencyPolicy's workhub_pages gap message tells the agent
to call ``workhub_update_page(name=..., ...)`` to satisfy the
gate. But the ``workhub_tools`` bundle only included
``workhub_create_page`` — not ``workhub_update_page``. Worse:
``_count_owned_pages`` specifically requires ``kind=="ui_page"``,
and only ``workhub_update_page`` writes that kind, so the agent
couldn't satisfy the gate even by aggressively calling
``workhub_create_page``. Result: soft-lock for frontend/design at
``finish()`` — gate fires, suggests a tool the agent doesn't have,
infinite loop until tier-3 (or now the claim-gate retry cap).

This regression test pins the alignment: every tool name the gap
messages reference MUST be in the corresponding bundle. A future
"clean up unused bundle entry" commit silently breaks the gate
otherwise.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

POLICIES_PATH = LLM_DIR / "multi_agent" / "workflow_policies.py"
BUNDLES_PATH = LLM_DIR / "multi_agent" / "tool_bundles.py"
AGENTS_YAML = LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"


def _extract_check_hub_kind_tool_refs() -> dict:
    """Walk ``HubConsistencyPolicy._check_hub_kind`` and pull out
    the (hub-kind, suggested-tool-name) pairs from each branch's
    gap-message return value.

    Returns a dict mapping ``hub_kind`` -> set of tool names mentioned
    in that branch's prose. Driven by regex on the source text rather
    than AST execution because the branches build the message via
    f-string assembly and the tool-name token is a backtick-quoted
    identifier inside the prose."""
    text = POLICIES_PATH.read_text()
    # Find the _check_hub_kind method's source span.
    start = text.find("def _check_hub_kind")
    if start < 0:
        raise RuntimeError("_check_hub_kind not found in workflow_policies.py")
    # The method ends at the next def at the same indentation level.
    end = text.find("\n    @staticmethod", start)
    if end < 0:
        end = text.find("\n    def ", start + 1)
    if end < 0:
        end = len(text)
    body = text[start:end]

    # Each branch is `if kind == "<hub_kind>":` followed by some
    # logic and a `return (f"... call `<tool_name>(...)` ...")`.
    branches: dict = {}
    branch_pat = re.compile(
        r'if\s+kind\s*==\s*"([a-z_]+)":(.*?)(?=\n\s*if\s+kind\s*==|\n\s*#\s*Unknown\s+kind|\Z)',
        re.DOTALL,
    )
    tool_pat = re.compile(r"`([a-z_]+)\(")  # backtick-quoted call
    for m in branch_pat.finditer(body):
        kind = m.group(1)
        branch_body = m.group(2)
        tools = set(tool_pat.findall(branch_body))
        # Strip stdlib/helper-ish tokens that appear in prose but
        # aren't actual tool calls. None known today; placeholder.
        ignore = {"open", "len", "print"}
        tools -= ignore
        if tools:
            branches[kind] = tools
    return branches


def _extract_bundle_tool_names(bundle_func: str) -> set:
    """Parse ``tool_bundles.py``, locate the named bundle function,
    walk its body for the ``include_names={...}`` literal set, and
    return the contained tool-name strings."""
    text = BUNDLES_PATH.read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != bundle_func:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.keyword) and sub.arg == "include_names":
                # Expect a set literal of constant strings.
                value = sub.value
                if isinstance(value, ast.Set):
                    return {
                        elt.value for elt in value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)
                    }
    raise RuntimeError(
        f"bundle function {bundle_func!r} or its include_names set "
        "not found in tool_bundles.py"
    )


# The mapping the policy embeds: hub kind -> bundle whose
# include_names set must contain the tool the gap message names.
# This is the test's load-bearing contract. If the policy starts
# referencing a new hub kind, add it here.
HUB_KIND_TO_BUNDLE = {
    "registryhub_endpoints": "_bundle_registryhub_tools",
    "registryhub_tables":    "_bundle_registryhub_tools",
    "workhub_pages":    "_bundle_workhub_tools",
    "codehub_commits":  "_bundle_codehub_tools",
}


class HubConsistencyGapToolsAreInBundles(unittest.TestCase):
    """For every hub kind ``HubConsistencyPolicy`` knows about that
    suggests a tool call in its gap message, that tool MUST be in
    the corresponding bundle. Otherwise the gate fires telling the
    agent to call something it can't reach."""

    @classmethod
    def setUpClass(cls):
        cls.gap_tools_by_kind = _extract_check_hub_kind_tool_refs()

    def test_workhub_pages_gate_tool_is_in_workhub_bundle(self):
        """The exact reviewer finding: workhub_pages gate's gap
        message references a tool not present in the bundle."""
        tools = self.gap_tools_by_kind.get("workhub_pages") or set()
        self.assertTrue(
            tools,
            "no tool calls found in the workhub_pages branch — "
            "extractor regex broken; update the test.",
        )
        bundle_tools = _extract_bundle_tool_names("_bundle_workhub_tools")
        missing = tools - bundle_tools
        self.assertFalse(
            missing,
            f"workhub_pages gate references tool(s) {sorted(missing)} "
            f"that are NOT in workhub_tools bundle. Either add them "
            f"to ``_bundle_workhub_tools.include_names`` or change "
            f"the gate's gap message to use a tool that IS in the "
            f"bundle. Current bundle: {sorted(bundle_tools)}.",
        )

    def test_registryhub_endpoints_gate_tool_is_in_registryhub_bundle(self):
        tools = self.gap_tools_by_kind.get("registryhub_endpoints") or set()
        if not tools:
            self.skipTest("registryhub_endpoints branch has no tool call "
                          "in its gap message (likely uses prose)")
        bundle_tools = _extract_bundle_tool_names("_bundle_registryhub_tools")
        missing = tools - bundle_tools
        self.assertFalse(
            missing,
            f"registryhub_endpoints gate references tool(s) {sorted(missing)} "
            f"not in registryhub_tools bundle.",
        )

    def test_registryhub_tables_gate_tool_is_in_registryhub_bundle(self):
        tools = self.gap_tools_by_kind.get("registryhub_tables") or set()
        if not tools:
            self.skipTest("registryhub_tables branch has no tool call")
        bundle_tools = _extract_bundle_tool_names("_bundle_registryhub_tools")
        missing = tools - bundle_tools
        self.assertFalse(
            missing,
            f"registryhub_tables gate references tool(s) {sorted(missing)} "
            f"not in registryhub_tools bundle.",
        )

    def test_codehub_commits_gate_tool_is_in_codehub_bundle(self):
        tools = self.gap_tools_by_kind.get("codehub_commits") or set()
        if not tools:
            self.skipTest("codehub_commits branch has no tool call")
        bundle_tools = _extract_bundle_tool_names("_bundle_codehub_tools")
        missing = tools - bundle_tools
        self.assertFalse(
            missing,
            f"codehub_commits gate references tool(s) {sorted(missing)} "
            f"not in codehub_tools bundle.",
        )


def _profile_effective_tool_surface(profile: dict) -> set:
    """Compute the union of tool names a profile actually surfaces
    to its agent. Walks ``tool_bundles`` and for each bundle that
    instantiates ``create_hub_tools(include_names={...})``, unions
    the literal name set. Bundles that build tools differently
    (e.g. ``create_seed_tools``, ``create_mcp_registry_tools``) are
    NOT in this scan — they ship a fixed set without an
    include_names parameter. For the purposes of the
    hub-consistency-gate invariant (which only references
    ``registryhub_*``/``workhub_*``/``codehub_*`` tools that live in
    ``create_hub_tools``-built bundles), that's exactly the right
    scope."""
    surface: set = set()
    for bundle_id in (profile.get("tool_bundles") or []):
        bundle_func = f"_bundle_{bundle_id}"
        try:
            names = _extract_bundle_tool_names(bundle_func)
        except RuntimeError:
            # Bundle doesn't use create_hub_tools(include_names=…) —
            # skip; not relevant for the gap-message invariant.
            continue
        surface |= names
    return surface


def _gate_demanded_tools_for_profile(
    profile: dict, gap_tools_by_kind: dict,
) -> set:
    """For a profile that uses ``hub_consistency_gate``, return the
    union of every gap-message tool name across the kinds it lists
    in ``expect_hub_kinds``. The result is the set of tools the
    gate WILL demand the agent call when it fires."""
    demanded: set = set()
    for entry in (profile.get("workflow_policies") or []):
        if (entry or {}).get("kind") != "hub_consistency_gate":
            continue
        for kind in (entry.get("expect_hub_kinds") or []):
            demanded |= gap_tools_by_kind.get(kind) or set()
    return demanded


class GateDemandedToolsAreInEveryDemandingProfile(unittest.TestCase):
    """**Global invariant** (PR 6 review HIGH, 2026-05-30): for
    EVERY profile in agents_config.yaml that wires
    ``hub_consistency_gate``, every tool the gate's gap message
    references for each of that profile's ``expect_hub_kinds`` must
    be present in the profile's effective tool surface (union of
    its bundles' ``include_names``).

    History of why this test exists:
      * Earlier round caught ``frontend`` was wired to
        ``workhub_pages`` but its bundle only had
        ``workhub_create_page`` — gate demanded
        ``workhub_update_page``, agent couldn't call it. Fix:
        added ``workhub_update_page`` to the bundle.
      * PR 6 review caught the SAME shape on ``database``: gate
        wired to ``registryhub_tables`` but the profile had no registryhub
        bundle and couldn't call ``registryhub_register_table``.
      * Two instances → it's a class of bug, not a one-off. This
        invariant test pins ALL profiles × ALL their gate kinds in
        one place, so a third repeat is impossible.
    """

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.config = yaml.safe_load(AGENTS_YAML.read_text())
        cls.gap_tools_by_kind = _extract_check_hub_kind_tool_refs()

    def test_every_profile_can_satisfy_its_hub_consistency_gate(self):
        offenders = []
        profiles = (self.config or {}).get("profiles") or {}
        for profile_name, profile in profiles.items():
            demanded = _gate_demanded_tools_for_profile(
                profile, self.gap_tools_by_kind,
            )
            if not demanded:
                continue
            surface = _profile_effective_tool_surface(profile)
            missing = demanded - surface
            if missing:
                # Surface the kinds that triggered the demand so the
                # operator can target the right bundle / category.
                kinds = []
                for entry in (profile.get("workflow_policies") or []):
                    if (entry or {}).get("kind") == "hub_consistency_gate":
                        kinds = list(entry.get("expect_hub_kinds") or [])
                offenders.append(
                    f"profile {profile_name!r}: "
                    f"hub_consistency_gate expects {kinds}; "
                    f"gate-demanded tools {sorted(missing)} are NOT "
                    f"in the profile's effective tool surface. "
                    f"Either add a bundle that exposes them (e.g. "
                    f"``schemahub_tools`` exposes the table-registration "
                    f"subset) OR remove the offending kind from "
                    f"``expect_hub_kinds``."
                )
        self.assertFalse(
            offenders,
            "hub_consistency_gate demands tools that the gated profile "
            "can't reach. Soft-wedge until the run budget — there is "
            "NO retry cap on this gate. Findings:\n\n"
            + "\n\n".join(offenders),
        )

    def test_invariant_covers_every_profile_using_the_gate(self):
        """Pin that we actually scan every profile that uses the
        gate — a regex bug that misses profiles would silently
        make the assertion above vacuous."""
        profiles = (self.config or {}).get("profiles") or {}
        gated_profiles = [
            name for name, p in profiles.items()
            if any((e or {}).get("kind") == "hub_consistency_gate"
                   for e in (p.get("workflow_policies") or []))
        ]
        # The two implementation lanes use the gate today (design was
        # retired in the 2026-06-02 kickoff-refactor).
        for required in ("backend", "frontend"):
            self.assertIn(
                required, gated_profiles,
                f"profile {required!r} no longer uses "
                "hub_consistency_gate — either the gate is being "
                "phased out (update this test) or the profile lost "
                "the policy and downstream protection is gone.",
            )


class ExtractedBranchesAreReasonable(unittest.TestCase):
    """Defence in depth: pin that the regex actually found ALL the
    branches in the policy, so a regex regression that silently
    drops a branch doesn't make every assertion above vacuous."""

    def test_all_expected_kinds_were_parsed(self):
        gap_tools = _extract_check_hub_kind_tool_refs()
        # Every kind the policy's docstring says it handles should
        # appear in the extracted set (even if its gap message
        # didn't mention a tool — empty value is fine).
        expected_kinds = {
            "registryhub_endpoints", "registryhub_tables", "workhub_pages",
            "codehub_commits",
        }
        found_kinds = set(gap_tools.keys())
        # Allow ``found_kinds`` to be a subset (some branches may
        # not have tool refs). But every kind that mentions a tool
        # must be in HUB_KIND_TO_BUNDLE or the test won't enforce it.
        unmapped = found_kinds - set(HUB_KIND_TO_BUNDLE.keys())
        self.assertFalse(
            unmapped,
            f"HubConsistencyPolicy gained new branches {sorted(unmapped)} "
            "that mention a tool but have no bundle mapping in this "
            "test. Update HUB_KIND_TO_BUNDLE.",
        )


if __name__ == "__main__":
    unittest.main()
