"""Invariant: every TOOL_BUNDLE_REGISTRY entry must have a TOOL_BUNDLE_REQUIREMENTS
entry, and vice versa. Catches the bug pattern where a new bundle is
added to TOOL_BUNDLES + granted in agents_config.yaml but the validator
doesn't know about it (load_config raises at startup).

Found 2026-06-01 when the v3 re-pilot launch
(launch_facebook_v3_repilot.sh) failed at
orchestrator._spawn_core_agents with:

  ValueError: Invalid tool surface config:
  - profile 'verifier' references unknown tool bundle: verifier_contract_tools

Root cause: the Phase 4.4 Path A bundle-trim (commit 7272a2fc) added
`_bundle_verifier_contract_tools` + registered it in TOOL_BUNDLE_REGISTRY at
tool_bundles.py:617 AND granted it to the verifier profile in
agents_config.yaml:582, but never added a TOOL_BUNDLE_REQUIREMENTS
entry. The config validator (tool_surface.py:122-126) checks
TOOL_BUNDLE_REQUIREMENTS, so the bundle reads as "unknown" and
startup fails — even though every other test (which doesn't load
the full agent config end-to-end) passes clean.

This test scans both dicts and asserts they have the same keyset.
Also asserts every key in agents_config.yaml's profile.tool_bundles
lists is covered by TOOL_BUNDLE_REQUIREMENTS — closes the gap from
the OTHER side too (if someone adds to yaml but not to TOOL_BUNDLE_REGISTRY,
that side is already caught by the runtime; if someone adds to yaml
but not to TOOL_BUNDLE_REQUIREMENTS, this test catches it).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class ToolBundleRegistryParity(unittest.TestCase):
    """TOOL_BUNDLES and TOOL_BUNDLE_REQUIREMENTS must have identical keysets."""

    def test_every_tool_bundle_has_requirements_entry(self) -> None:
        from multi_agent.tool_bundles import (
            TOOL_BUNDLE_REGISTRY,
            TOOL_BUNDLE_REQUIREMENTS,
        )
        missing = sorted(set(TOOL_BUNDLE_REGISTRY.keys()) - set(TOOL_BUNDLE_REQUIREMENTS.keys()))
        self.assertEqual(
            missing, [],
            msg=(
                f"TOOL_BUNDLE_REGISTRY has {len(missing)} entries without a "
                f"matching TOOL_BUNDLE_REQUIREMENTS entry: {missing}. "
                f"Every bundle must declare its required tool_categories "
                f"so the config validator can verify profile grants. "
                f"Add `'<bundle_name>': {{'<category>'}}` to "
                f"TOOL_BUNDLE_REQUIREMENTS in tool_bundles.py. "
                f"This catches the v3 re-pilot startup failure of "
                f"2026-06-01 (commit 7272a2fc added the bundle to "
                f"TOOL_BUNDLE_REGISTRY but not to TOOL_BUNDLE_REQUIREMENTS)."
            ),
        )

    def test_every_requirements_entry_has_a_bundle(self) -> None:
        from multi_agent.tool_bundles import (
            TOOL_BUNDLE_REGISTRY,
            TOOL_BUNDLE_REQUIREMENTS,
        )
        orphan = sorted(set(TOOL_BUNDLE_REQUIREMENTS.keys()) - set(TOOL_BUNDLE_REGISTRY.keys()))
        self.assertEqual(
            orphan, [],
            msg=(
                f"TOOL_BUNDLE_REQUIREMENTS has {len(orphan)} entries "
                f"without a matching TOOL_BUNDLE_REGISTRY entry: {orphan}. "
                f"The requirement is dead — either restore the bundle "
                f"function in TOOL_BUNDLES or drop the requirement."
            ),
        )


class ProfileGrantsResolveToKnownBundles(unittest.TestCase):
    """Every bundle id in agents_config.yaml's profile.tool_bundles
    lists must be a known bundle. This is what load_config() validates
    at startup — this test brings the same check into the offline
    suite so it catches the regression before launch instead of at run."""

    def test_all_profile_bundle_grants_are_known(self) -> None:
        import yaml
        from multi_agent.tool_bundles import TOOL_BUNDLE_REQUIREMENTS

        cfg_path = (
            AGENT_DIR / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        self.assertTrue(cfg_path.exists(), msg=f"agents_config.yaml not found at {cfg_path}")

        with open(cfg_path, "r") as f:
            cfg = yaml.safe_load(f)
        profiles = cfg.get("profiles") or {}
        self.assertGreater(len(profiles), 0, msg="no profiles in config")

        known_bundles = set(TOOL_BUNDLE_REQUIREMENTS.keys())
        unknown_per_profile: dict = {}
        for profile_id, profile_cfg in profiles.items():
            granted = [str(b) for b in (profile_cfg.get("tool_bundles") or [])]
            unknown = [b for b in granted if b not in known_bundles]
            if unknown:
                unknown_per_profile[profile_id] = unknown
        self.assertEqual(
            unknown_per_profile, {},
            msg=(
                f"profiles grant unknown tool_bundles: "
                f"{unknown_per_profile}. Either add the missing bundle "
                f"to TOOL_BUNDLE_REQUIREMENTS in tool_bundles.py OR "
                f"remove the grant from agents_config.yaml. This is the "
                f"check load_config() runs at startup — having it here "
                f"surfaces the bug before the run launches."
            ),
        )

    def test_load_config_does_not_raise(self) -> None:
        """End-to-end sanity: the real load_config() that runs at
        orchestrator startup must not raise. This was the function that
        threw on 2026-06-01 v3 re-pilot launch."""
        from multi_agent.agents.configurable_agent import load_config, _config_cache
        # Reset the cache so we exercise the real validation path.
        import multi_agent.agents.configurable_agent as cc
        cc._config_cache = None
        try:
            cfg = load_config()
            self.assertIn("profiles", cfg)
        except ValueError as e:
            self.fail(
                f"load_config() raised — orchestrator startup would "
                f"fail with the same error: {e}"
            )


if __name__ == "__main__":
    unittest.main()
