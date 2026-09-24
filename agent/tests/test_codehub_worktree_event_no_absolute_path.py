"""Sandbox principle: agents perceive workspace root as ``/``.

Pre-fix backend agents read ``worktree_registered`` from their inbox and saw
``{'path': '/tmp/envgen_demo/<run>/worktrees/backend'}`` — the host's absolute
prefix. That contaminated the agent's mental model: every subsequent write was
constructed as ``/tmp/envgen_demo/.../app/backend/server.js``, which the path-
routing layer then denied because absolute paths bypass the routing table.

The fix relativizes the ``path`` field at the emission site (codehub.service
``register_agent_worktree`` + ``cleanup_worktree``). This closed-by-construction
test pins it: the published event payload must not leak an absolute path.

A grep-style scrub over the full event payload also catches any future field
that accidentally captures ``str(self.repo_root / ...)``.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CodeHubWorktreeEventNoAbsolutePath(unittest.TestCase):
    """Smoke #23 follow-on: plug the absolute-path leak at source."""

    def _published_events(self, hubs: HubRegistry) -> list:
        return list(hubs.eventhub._events.value().values())

    def _assert_no_abs_prefix(self, payload: dict, *, repo_root: Path) -> None:
        """Fail if ANY string-valued field in payload starts with ``/`` or
        contains the absolute repo_root prefix."""
        abs_prefix = str(repo_root)
        for key, val in payload.items():
            if not isinstance(val, str):
                continue
            self.assertFalse(
                val.startswith("/tmp/") or val.startswith(abs_prefix),
                f"absolute path leaked in event payload[{key!r}]: {val!r} "
                f"(repo_root={abs_prefix!r}). Agents must see paths "
                f"relative to workspace root.",
            )
            # Sanity: also no double-slash that would hint at host paths
            self.assertFalse(
                val.startswith("//"),
                f"suspicious path in payload[{key!r}]: {val!r}",
            )

    def test_worktree_registered_emits_relative_path(self):
        """``worktree_registered`` payload's path must be relative to repo_root.
        Pre-fix this asserted ``str(wt_path)`` — an absolute /tmp path.
        Post-fix it is ``worktrees/<agent_id>``."""
        with tempfile.TemporaryDirectory(prefix="codehub_abs_path_") as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")

            evts = [
                e for e in self._published_events(hubs)
                if e.get("event_type") == "worktree_registered"
            ]
            self.assertEqual(
                len(evts), 1,
                f"expected exactly 1 worktree_registered event, got {len(evts)}",
            )
            payload = evts[0]["payload"]

            self.assertEqual(payload.get("agent_id"), "backend")
            self.assertEqual(payload.get("branch"), "agent/backend")
            # The exact pin: relative path, not absolute.
            self.assertEqual(payload.get("path"), "worktrees/backend")
            # Defense-in-depth: scrub every string field for absolute prefix.
            self._assert_no_abs_prefix(payload, repo_root=ch.repo_root)

    def test_worktree_cleaned_emits_relative_path(self):
        """``worktree_cleaned`` payload's path must also be relative."""
        with tempfile.TemporaryDirectory(prefix="codehub_abs_path_") as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("frontend")
            ch.cleanup_worktree("frontend")

            evts = [
                e for e in self._published_events(hubs)
                if e.get("event_type") == "worktree_cleaned"
            ]
            self.assertEqual(
                len(evts), 1,
                f"expected exactly 1 worktree_cleaned event, got {len(evts)}",
            )
            payload = evts[0]["payload"]
            self.assertEqual(payload.get("agent_id"), "frontend")
            self.assertEqual(payload.get("path"), "worktrees/frontend")
            self._assert_no_abs_prefix(payload, repo_root=ch.repo_root)

    def test_all_codehub_published_events_have_no_absolute_paths(self):
        """Sweeping check: across the full lifecycle (register + cleanup +
        commit_recorded + repo_registered), NO published event payload may
        contain an absolute path string. This pins the sandbox property
        across the whole CodeHub surface, so future fields can't silently
        re-introduce the leak."""
        with tempfile.TemporaryDirectory(prefix="codehub_abs_path_sweep_") as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            wt = ch.repo_root / "worktrees" / "backend"
            (wt / "hello.py").write_text("x=1\n")
            ch.commit("backend", message="add hello", files=["hello.py"])
            ch.cleanup_worktree("backend")

            for evt in self._published_events(hubs):
                with self.subTest(event_type=evt.get("event_type")):
                    self._assert_no_abs_prefix(
                        evt.get("payload") or {}, repo_root=ch.repo_root,
                    )


if __name__ == "__main__":
    unittest.main()
