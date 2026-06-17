"""Guard: the frontend must not declare done while declared pages are unbuilt.

youtube run #13 false-completion: the framework created one impl.page.<name> task
per declared ui_page; the lane built 1 page, left 15 of 16 page tasks in_progress,
then messaged "All tasks claimed and completed. Ready to proceed with Phase A/B" —
a hallucinated done that ships a blank shell (frontend_navigable delivery gate = 0).
frontend_pages_implemented blocks finish while any impl.page.* task is non-terminal,
and (anti-gaming) when all are "complete" but ZERO page files exist.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    frontend_pages_implemented,
)


class _Workhub:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self, assignee=None, status=None, **kw):
        out = self._tasks
        if assignee is not None:
            out = [t for t in out if t.get("assignee") == assignee]
        if status is not None:
            out = [t for t in out if t.get("status") == status]
        return list(out)


class _Hubs:
    def __init__(self, tasks):
        self.workhub = _Workhub(tasks)


class _Agent:
    def __init__(self, tasks, worktree=None, lane="frontend"):
        self._config_key = lane
        self._hubs = _Hubs(tasks)
        self._worktree_dir = worktree
        self.workspace = None  # frontend_canonical_root: base_dir None → passes


def _page(name, status):
    return {"id": f"impl.page.{name}", "assignee": "frontend", "status": status}


class FrontendPagesImplementedTests(unittest.TestCase):
    def test_blocks_when_page_tasks_in_progress(self):
        tasks = [_page("youtube_home", "in_progress"),
                 _page("youtube_watch", "completed"),
                 {"id": "impl.component.top_bar", "assignee": "frontend",
                  "status": "in_progress"}]  # not a page → ignored
        msg = frontend_pages_implemented(_Agent(tasks), "finish", {})
        self.assertIsNotNone(msg)
        self.assertIn("not complete", msg.lower())
        self.assertIn("youtube_home", msg)
        self.assertNotIn("youtube_watch", msg)  # completed → not listed

    def test_passes_when_all_pages_complete_and_built(self):
        with tempfile.TemporaryDirectory() as wt:
            pages = Path(wt) / "app" / "frontend" / "src" / "pages"
            pages.mkdir(parents=True)
            (pages / "Home.jsx").write_text("export default function Home(){}")
            tasks = [_page("youtube_home", "completed"),
                     _page("youtube_watch", "completed")]
            self.assertIsNone(
                frontend_pages_implemented(_Agent(tasks, worktree=wt), "finish", {}))

    def test_blocks_when_all_complete_but_zero_pages_built(self):
        with tempfile.TemporaryDirectory() as wt:
            # all page tasks "completed" but no pages dir / no .jsx → gamed
            tasks = [_page("youtube_home", "completed"),
                     _page("youtube_watch", "completed")]
            msg = frontend_pages_implemented(_Agent(tasks, worktree=wt), "finish", {})
            self.assertIsNotNone(msg)
            self.assertIn("ZERO page", msg)

    def test_non_frontend_lane_passes(self):
        tasks = [_page("youtube_home", "in_progress")]
        self.assertIsNone(
            frontend_pages_implemented(_Agent(tasks, lane="backend"), "finish", {}))

    def test_no_page_tasks_passes(self):
        tasks = [{"id": "task_misc", "assignee": "frontend", "status": "in_progress"}]
        self.assertIsNone(frontend_pages_implemented(_Agent(tasks), "finish", {}))

    def test_cancelled_page_task_counts_as_terminal(self):
        with tempfile.TemporaryDirectory() as wt:
            pages = Path(wt) / "app" / "frontend" / "src" / "pages"
            pages.mkdir(parents=True)
            (pages / "Home.jsx").write_text("x")
            tasks = [_page("youtube_home", "completed"),
                     _page("youtube_deprecated", "cancelled")]
            self.assertIsNone(
                frontend_pages_implemented(_Agent(tasks, worktree=wt), "finish", {}))


if __name__ == "__main__":
    unittest.main()
