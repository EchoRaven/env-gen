"""Tests for project_info / project_phase / share_implementation WorkHub helpers.

Covers Phase D Tasks 17 and 18 of Cutover 3.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _hub() -> WorkHub:
    tmp = tempfile.mkdtemp()
    return WorkHub(Path(tmp))


# ---------------------------------------------------------------------------
# Task 16: update_ui_page / get_ui_pages
# ---------------------------------------------------------------------------

class TestUiPages(unittest.TestCase):
    """A3 (2026-06-12): WorkHub.update_ui_page/get_ui_pages are thin delegates
    to the RegistryHub (the sole owner), which raise without an attached
    registryhub — so these tests build a full HubRegistry and exercise
    ``hubs.workhub`` (the registryhub handle is wired at construction)."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory(prefix="workhub_ui_pages_")
        self.hubs = HubRegistry(Path(self._td.name))
        self.workhub = self.hubs.workhub

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_update_and_get_ui_page(self):
        """update_ui_page creates a ui_page and get_ui_pages returns it by name."""
        hub = self.workhub
        hub.update_ui_page("home", {"status": "defined"}, agent="frontend")
        pages = hub.get_ui_pages()
        self.assertIn("home", pages)
        self.assertEqual(pages["home"]["status"], "defined")
        self.assertEqual(pages["home"]["kind"], "ui_page")

    def test_update_ui_page_is_idempotent(self):
        """Twice-updated entry keeps the latest data; 'implemented' is the
        FRAMEWORK's verdict (mechanism #54) — agent self-claims downgrade,
        the orchestrator-audit write sticks."""
        hub = self.workhub
        hub.update_ui_page("home", {"status": "defined"}, agent="frontend")
        hub.update_ui_page("home", {"status": "implemented"}, agent="frontend")
        self.assertEqual(hub.get_ui_pages()["home"]["status"], "defined")
        hub.update_ui_page("home", {"status": "implemented"}, agent="orchestrator")
        self.assertEqual(hub.get_ui_pages()["home"]["status"], "implemented")

    def test_stale_ui_page(self):
        """Setting status=stale is reflected in get_ui_pages. ``agent`` must be
        in register_ui_page's allowed_set (A3 thin-delegate hits the role gate);
        ``frontend`` owns ui_page registration."""
        hub = self.workhub
        hub.update_ui_page("dashboard", {"status": "stale"}, agent="frontend")
        pages = hub.get_ui_pages()
        self.assertEqual(pages["dashboard"]["status"], "stale")


# ---------------------------------------------------------------------------
# Task 17: set_project_info / set_project_phase / get_project_status
# ---------------------------------------------------------------------------

class TestProjectInfo(unittest.TestCase):
    def test_set_and_get_project_info(self):
        """set_project_info creates a project page retrievable by get_project_status."""
        hub = _hub()
        result = hub.set_project_info("myapp", description="My generated app", agent="orchestrator")
        self.assertEqual(result["title"], "myapp")
        self.assertEqual(result["kind"], "project")
        status = hub.get_project_status("myapp")
        self.assertEqual(status["title"], "myapp")
        self.assertEqual(status["description"], "My generated app")

    def test_set_project_phase_appends_block(self):
        """set_project_phase appends a project_phase block."""
        hub = _hub()
        hub.set_project_info("myapp", agent="orchestrator")
        hub.set_project_phase("myapp", "design", agent="orchestrator", reason="started planning")
        status = hub.get_project_status("myapp")
        self.assertEqual(status["phase"], "design")
        self.assertEqual(status["phase_reason"], "started planning")

    def test_set_project_phase_auto_creates_project(self):
        """set_project_phase auto-creates the project page if absent."""
        hub = _hub()
        hub.set_project_phase("newproj", "init", agent="orchestrator")
        status = hub.get_project_status("newproj")
        self.assertEqual(status["phase"], "init")

    def test_get_project_status_without_name_returns_latest(self):
        """get_project_status() with no name returns the most recently updated project."""
        hub = _hub()
        hub.set_project_info("alpha", agent="orchestrator")
        # beta is created after alpha so it has a later _updated_at
        hub.set_project_info("beta", agent="orchestrator")
        status = hub.get_project_status()
        # beta was updated most recently
        self.assertEqual(status["title"], "beta")

    def test_get_project_status_no_projects_returns_empty(self):
        """get_project_status() returns {} if no project pages exist."""
        hub = _hub()
        self.assertEqual(hub.get_project_status(), {})

    def test_multiple_phases_returns_latest(self):
        """Only the most recent phase block is returned."""
        hub = _hub()
        hub.set_project_info("myapp", agent="orchestrator")
        hub.set_project_phase("myapp", "init", agent="orchestrator")
        hub.set_project_phase("myapp", "design", agent="orchestrator")
        hub.set_project_phase("myapp", "implement", agent="orchestrator")
        status = hub.get_project_status("myapp")
        self.assertEqual(status["phase"], "implement")


# ---------------------------------------------------------------------------
# Task 18: share_implementation / get_shared_implementations
# ---------------------------------------------------------------------------

class TestShareImplementation(unittest.TestCase):
    def test_share_creates_knowledge_block(self):
        """share_implementation appends a block to page:knowledge."""
        hub = _hub()
        block = hub.share_implementation(
            title="Cursor pagination",
            content="SELECT * FROM items WHERE id > ? LIMIT 20",
            agent="backend",
            category="sql_pattern",
        )
        self.assertEqual(block["type"], "knowledge")
        self.assertEqual(block["page_id"], "page:knowledge")
        self.assertEqual(block["content"]["title"], "Cursor pagination")

    def test_get_shared_implementations_returns_list(self):
        """get_shared_implementations returns all knowledge blocks."""
        hub = _hub()
        hub.share_implementation("Pattern A", "code A", agent="backend")
        hub.share_implementation("Pattern B", "code B", agent="frontend")
        impls = hub.get_shared_implementations()
        self.assertEqual(len(impls), 2)

    def test_get_shared_implementations_since_ts(self):
        """since_ts filter excludes older blocks."""
        import time
        hub = _hub()
        hub.share_implementation("Old pattern", "old code", agent="backend")
        mid = time.time()
        hub.share_implementation("New pattern", "new code", agent="backend")
        impls = hub.get_shared_implementations(since_ts=mid)
        self.assertEqual(len(impls), 1)
        self.assertEqual(impls[0]["content"]["title"], "New pattern")

    def test_share_auto_creates_knowledge_page(self):
        """share_implementation auto-creates page:knowledge if it doesn't exist."""
        hub = _hub()
        hub.share_implementation("X", "code", agent="backend")
        pages = hub.stores.pages.value()
        self.assertIn("page:knowledge", pages)
        self.assertEqual(pages["page:knowledge"]["kind"], "knowledge")

    def test_get_shared_implementations_sorted_newest_first(self):
        """Results are sorted newest-first by _updated_at."""
        hub = _hub()
        hub.share_implementation("First", "code1", agent="backend")
        hub.share_implementation("Second", "code2", agent="backend")
        hub.share_implementation("Third", "code3", agent="backend")
        impls = hub.get_shared_implementations()
        titles = [b["content"]["title"] for b in impls]
        self.assertEqual(titles[0], "Third")


if __name__ == "__main__":
    unittest.main()
