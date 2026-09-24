"""Tests that backend + orchestrator prompts teach seed sufficiency discipline.

Backend owns seed data post-roster-reduction (2026-06-02); the legacy
database lane is folded into backend.
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


def _render(tpl_name: str, macros: list) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    tpl = env.get_template(tpl_name)
    mod = tpl.make_module()
    for name in macros:
        if hasattr(mod, name):
            try:
                return getattr(mod, name)()
            except TypeError:
                return getattr(mod, name)(".", "")
    raise RuntimeError(f"no macro found in {tpl_name}")


class BackendSeedAuthoringPromptTests(unittest.TestCase):
    """The backend agent now OWNS the seed VALUES (agent-only seed decision, 2026-06-29):
    the prompt must teach the concrete mechanism (author app/backend/seed_data.json) and
    the rules that make a populated, consistent preview (owner attribution, derived
    counters match the rows, password handling)."""

    def setUp(self) -> None:
        self.prompt = _render("backend_agent.j2", ["backend_system_prompt"])

    def test_teaches_seed_data_json_artifact(self) -> None:
        self.assertIn("seed_data.json", self.prompt)

    def test_teaches_owner_attribution_and_first_user(self) -> None:
        up = self.prompt.upper()
        self.assertIn("OWNER", up)
        # the first user must have data so the test-user/preview is not empty
        self.assertTrue("USER #1" in up or "FIRST USER" in up)

    def test_teaches_derived_counters_match_rows(self) -> None:
        # the user's Q1: a denormalized count (unread_count) must follow the real rows
        self.assertIn("unread_count", self.prompt)
        up = self.prompt.upper()
        self.assertTrue("DERIVED" in up or "MUST MATCH" in up or "MUST EQUAL" in up)

    def test_does_not_tell_agent_to_write_password_hash(self) -> None:
        # the loader hashes; the agent supplies plaintext "password"
        self.assertIn('"password": "password"', self.prompt)


class OrchestratorSeedPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        # Use the v3 lead_system_prompt — the seed-audit discipline is
        # embedded in the inlined lead_specifics macro (round 4 inlined
        # the former v2 imports into v3).
        self.system = _render("orchestrator_agent.j2", ["lead_system_prompt"])

    def test_mentions_seed_audit(self) -> None:
        upper = self.system.upper()
        self.assertTrue("SEED_AUDIT_CHECK" in upper or "SEED AUDIT" in upper)

    def test_mentions_seed_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("SEED", upper)
        self.assertIn("DELIVER", upper)


# Note: the DatabaseSeedPromptTests class was retired with the database
# resident lane (2026-06-02 roster reduction). Backend now owns seed data;
# the seed-discipline content (MIN_SEED_ROWS, placeholder warnings,
# register_seed_data) will be reintroduced in the Phase C contract
# documents (`contract/data_model.md`) rather than in a single agent
# prompt. The schema_hub gate enforces backend authorship at runtime.


if __name__ == "__main__":
    unittest.main()
