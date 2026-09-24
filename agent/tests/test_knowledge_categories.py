"""Tests for new structured Knowledge categories (Cutover 15)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.knowledge.types import Knowledge, KnowledgeCategory  # noqa: E402


class KnowledgeCategoriesTests(unittest.TestCase):
    def test_adr_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.ADR.value, "adr")

    def test_runbook_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.RUNBOOK.value, "runbook")

    def test_postmortem_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.POSTMORTEM.value, "postmortem")


class KnowledgeStructuredFieldsTests(unittest.TestCase):
    def test_default_structured_fields_is_empty_dict(self) -> None:
        k = Knowledge(title="x")
        self.assertEqual(k.structured_fields, {})

    def test_can_construct_with_structured_fields(self) -> None:
        k = Knowledge(title="adr-001", category=KnowledgeCategory.ADR,
                      structured_fields={"decision": "use postgres",
                                          "context": "needed ACID",
                                          "alternatives": ["mysql", "sqlite"],
                                          "consequences": "ops overhead",
                                          "status": "accepted"})
        self.assertEqual(k.structured_fields["decision"], "use postgres")
        self.assertEqual(k.structured_fields["status"], "accepted")

    def test_to_dict_includes_structured_fields(self) -> None:
        k = Knowledge(title="r1", category=KnowledgeCategory.RUNBOOK,
                      structured_fields={"trigger": "deploy", "steps": ["a", "b", "c"],
                                          "verification": "v", "rollback": "r"})
        d = k.to_dict()
        self.assertIn("structured_fields", d)
        self.assertEqual(d["structured_fields"]["trigger"], "deploy")
        self.assertEqual(d["category"], "runbook")

    def test_from_dict_roundtrips_structured_fields(self) -> None:
        if not hasattr(Knowledge, "from_dict"):
            self.skipTest("Knowledge.from_dict not present in this version")
        payload = {
            "title": "pm1", "category": "postmortem",
            "structured_fields": {
                "incident_date": "2026-05-23", "impact": "p99 +400ms",
                "timeline": ["t1", "t2", "t3"], "root_cause": "cache miss",
                "action_items": ["a1"],
            },
        }
        k = Knowledge.from_dict(payload)
        self.assertEqual(k.category, KnowledgeCategory.POSTMORTEM)
        self.assertEqual(k.structured_fields["impact"], "p99 +400ms")


if __name__ == "__main__":
    unittest.main()
