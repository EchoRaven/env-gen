"""#346: every tool name the framework PINS must resolve to a real tool.

`ACTION_STAGE_ALWAYS_INCLUDE` and the TEAM_/KNOWLEDGE_ name sets exist to
GUARANTEE a tool reaches the model's menu regardless of the ranker -- they are
the mechanism that fixed the V25 MALFORMED_FUNCTION_CALL wedge and the
get_skill delivery deadlock. But the force-offer set is applied as
`always_include & candidate_names`, so a name that matches no registered tool
is silently dropped: the framework believes it pinned something and pinned
nothing.

Two such names were shipped:

  * `registryhub_get_table` in _CONTRACT_READ (force-offered into edit_code and
    run_checks). No tool has that NAME -- the real ones are
    registryhub_list_tables (already in the same set, so the capability was
    never actually missing) and registryhub_get_table_breaking_changes.
  * `think` in TEAM_MODE_SUPPORT_TOOLS. Not registered anywhere in tools/, and
    the action stages additionally `candidate_names.discard("think")`.

Unlike a prompt's prose -- where a backticked `app.include_router(...)` is a
legitimate FastAPI code EXAMPLE, not an instruction to call a tool -- these
sets are structured data whose only purpose is to name tools. So an
unresolvable entry here is unambiguously a defect, which is why the assertion
lives at this layer rather than over the templates.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def registered_tool_names() -> set:
    names = set()
    for p in (LLM_DIR / "tools").rglob("*.py"):
        names |= set(re.findall(
            r'NAME(?:\s*:\s*str)?\s*=\s*["\']([a-z_][a-z0-9_]*)["\']',
            p.read_text(errors="ignore")))
    return names


def pinned_name_sets() -> dict:
    from multi_agent.agents.base import EnvGenAgent as E
    sets = {
        "TEAM_TOOL_NAMES": E.TEAM_TOOL_NAMES,
        "TEAM_MODE_SUPPORT_TOOLS": E.TEAM_MODE_SUPPORT_TOOLS,
        "KNOWLEDGE_FETCH_TOOL_NAMES": E.KNOWLEDGE_FETCH_TOOL_NAMES,
        "KNOWLEDGE_STORE_TOOL_NAMES": E.KNOWLEDGE_STORE_TOOL_NAMES,
    }
    for stage, names in (E.ACTION_STAGE_ALWAYS_INCLUDE or {}).items():
        sets[f"ACTION_STAGE_ALWAYS_INCLUDE[{stage}]"] = names
    return sets


class TheHarnessSeesWhatItShould(unittest.TestCase):

    def test_registry_is_populated(self):
        self.assertGreater(len(registered_tool_names()), 200)

    def test_the_pinned_sets_are_found(self):
        sets = pinned_name_sets()
        self.assertGreater(len(sets), 5)
        self.assertTrue(any(v for v in sets.values()))


class EveryPinnedNameResolves(unittest.TestCase):

    def test_no_unresolvable_pin(self):
        tools = registered_tool_names()
        bad = {}
        for label, names in pinned_name_sets().items():
            missing = sorted(n for n in (names or set()) if n not in tools)
            if missing:
                bad[label] = missing
        self.assertEqual(
            bad, {},
            "these pinned names match no registered tool, so the pin is a "
            "silent no-op:\n" + "\n".join(f"  {k} -> {v}" for k, v in sorted(bad.items())))

    def test_the_two_known_phantoms_are_gone(self):
        from multi_agent.agents.base import EnvGenAgent as E
        self.assertNotIn("think", E.TEAM_MODE_SUPPORT_TOOLS)
        for stage, names in (E.ACTION_STAGE_ALWAYS_INCLUDE or {}).items():
            self.assertNotIn("registryhub_get_table", names or set(),
                             f"stage {stage} still pins a nonexistent tool")


class TheCapabilityIsNotLost(unittest.TestCase):
    """Both removals must be pure dead-weight, not a capability cut."""

    def test_table_contract_reads_are_still_pinned(self):
        from multi_agent.agents.base import EnvGenAgent as E
        pinned = set()
        for names in (E.ACTION_STAGE_ALWAYS_INCLUDE or {}).values():
            pinned |= set(names or set())
        self.assertIn("registryhub_list_tables", pinned)

    def test_the_real_table_tools_exist(self):
        tools = registered_tool_names()
        self.assertIn("registryhub_list_tables", tools)
        self.assertIn("registryhub_get_table_breaking_changes", tools)

    def test_team_support_still_pins_its_real_tools(self):
        from multi_agent.agents.base import EnvGenAgent as E
        for real in ("wait", "check_inbox", "send_message", "finish"):
            self.assertIn(real, E.TEAM_MODE_SUPPORT_TOOLS)


if __name__ == "__main__":
    unittest.main()
