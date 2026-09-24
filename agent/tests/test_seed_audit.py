"""Tests for runtime/seed_audit.py (Cutover 21)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.seed_audit import (  # noqa: E402
    SeedReport, audit_seed_data, detect_placeholder_score,
)


_GOOD_USERS = [
    {"id": 1, "name": "Alex Chen", "email": "alex.chen@gmail.com", "is_active": True},
    {"id": 2, "name": "Maria Rodriguez", "email": "maria.r@gmail.com", "is_active": False},
    {"id": 3, "name": "Yuki Tanaka", "email": "yuki@gmail.com", "is_active": True},
]

_PLACEHOLDER_USERS = [
    {"id": 1, "name": "user1", "email": "test@example.com", "is_active": True},
    {"id": 2, "name": "user2", "email": "foo@example.com", "is_active": True},
    {"id": 3, "name": "user3", "email": "bar@example.com", "is_active": True},
]


class DetectPlaceholderScoreTests(unittest.TestCase):
    def test_empty_excerpt_returns_zero(self) -> None:
        self.assertEqual(detect_placeholder_score([]), 0.0)

    def test_realistic_data_returns_low_score(self) -> None:
        score = detect_placeholder_score(_GOOD_USERS)
        self.assertLess(score, 0.5,
                          f"good data scored too high: {score}")

    def test_placeholder_data_returns_high_score(self) -> None:
        score = detect_placeholder_score(_PLACEHOLDER_USERS)
        self.assertGreaterEqual(score, 0.5,
                                  f"placeholder data scored too low: {score}")

    def test_sequential_names_flagged(self) -> None:
        rows = [{"name": f"item{i}"} for i in range(3)]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.5)

    def test_lorem_ipsum_flagged(self) -> None:
        rows = [{"body": "Lorem ipsum dolor sit amet, consectetur adipiscing"}]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.3)

    def test_all_same_bool_flagged(self) -> None:
        rows = [{"name": "A", "active": True},
                {"name": "B", "active": True},
                {"name": "C", "active": True}]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.2)

    def test_score_capped_at_1(self) -> None:
        rows = [{"name": f"user{i}", "title": f"item{i}",
                 "body": f"lorem ipsum {i}"} for i in range(5)]
        self.assertLessEqual(detect_placeholder_score(rows), 1.0)


class AuditSeedDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seed_aud_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tables_returns_clean(self) -> None:
        report = audit_seed_data(self.reg)
        self.assertIsInstance(report, SeedReport)
        self.assertEqual(report.flagged_tables, [])
        self.assertTrue(report.is_clean)

    def test_unregistered_table_flagged_missing_seed(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["table"], "users")
        self.assertEqual(report.flagged_tables[0]["reason"], "missing_seed")

    def test_low_row_count_flagged(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        self.reg.schema_hub.register_seed_data(
            "users", row_count=3, sample_excerpt=_GOOD_USERS, agent="backend")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "low_row_count")

    def test_high_row_count_passes(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        self.reg.schema_hub.register_seed_data(
            "users", row_count=42, sample_excerpt=_GOOD_USERS, agent="backend")
        report = audit_seed_data(self.reg)
        self.assertEqual(report.flagged_tables, [])

    def test_placeholder_content_flagged(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        self.reg.schema_hub.register_seed_data(
            "users", row_count=20, sample_excerpt=_PLACEHOLDER_USERS, agent="backend")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "placeholder_content")

    def test_custom_min_seed_rows_respected(self) -> None:
        # Table declares it needs at least 20 rows
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend",
            min_seed_rows=20)
        self.reg.schema_hub.register_seed_data(
            "users", row_count=10, sample_excerpt=_GOOD_USERS, agent="backend")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "low_row_count")
        self.assertEqual(report.flagged_tables[0]["detail"]["min_seed_rows"], 20)

    def test_min_seed_rows_zero_skips_table(self) -> None:
        # Table opts out via min_seed_rows=0 (e.g., empty lookup table)
        self.reg.schema_hub.register_table(
            "config", schema={"columns": []}, provider="backend", agent="backend",
            min_seed_rows=0)
        report = audit_seed_data(self.reg)
        self.assertEqual(report.flagged_tables, [])

    def test_all_dead_paths_property(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        self.reg.schema_hub.register_table(
            "posts", schema={"columns": []}, provider="backend", agent="backend")
        report = audit_seed_data(self.reg)
        paths = report.all_flagged_paths
        self.assertIn("seed:users", paths)
        self.assertIn("seed:posts", paths)


if __name__ == "__main__":
    unittest.main()
