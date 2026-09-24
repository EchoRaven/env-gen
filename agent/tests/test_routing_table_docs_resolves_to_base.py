"""Smoke #25 root-cause pin: ``docs/`` must route to ``base_root``.

Background:
    Smoke #25 (post-Fix-#3+#4) reached the kickoff_complete + 8f.2 doc
    authoring milestone. Orchestrator wrote
    ``<base>/docs/milestones/MILESTONE_M1.md`` +
    ``<base>/docs/ROADMAP.md`` +
    ``<base>/docs/briefings/BRIEFING_M1_<lane>.md`` via raw
    ``Path.write_text``. Backend + frontend lanes then tried to read
    those files at relative ``docs/...`` paths (now that Fix #4 plugged
    the absolute-path leak in the system prompt). Every read failed:

        ❌ read FAILED: path not found: docs/milestones/MILESTONE_M1.md
        ❌ read FAILED: path not found: docs/briefings/BRIEFING_M1_backend.md

Root cause:
    ``ROUTING_TABLE`` had NO entry for ``docs/``. Relative paths fell
    through to ``_DEFAULT_TARGET="code"`` (the agent's worktree). The
    orchestrator's authoring writes via raw ``Path.write_text`` to
    ``base/docs/...`` — never inside the worktree. So the briefings
    that lanes need to read landed at ``base/docs/`` but their reads
    were routed to ``worktree/docs/``, which never existed.

Fix: add a routing entry
    ``("docs/", "base", frozenset(), "kickoff-authored ...")``
- ``target="base"`` so reads resolve to ``base/docs/...`` where the
  orchestrator's authoring writes land.
- ``writers=frozenset()`` (read-only) so agents can't write here; the
  orchestrator's writes bypass routing anyway via raw Path.

This test pins:
    1. ``docs/milestones/MILESTONE_M1.md`` resolves under ``base_root``,
       NOT inside the agent's worktree.
    2. The routing table contains the ``docs/`` entry with the
       expected target + read-only writer set.
    3. No agent can write to ``docs/...``.
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

from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    PathRoutedWorkspace,
    ROUTING_TABLE,
)


class RoutingTableDocsResolvesToBase(unittest.TestCase):
    """Smoke #25 follow-on: docs/ must route to base_root."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory(prefix="docs_route_")
        td = Path(self._td.name)
        self.base = td / "base"
        self.base.mkdir(parents=True)
        self.worktrees = self.base / "worktrees"
        self.worktrees.mkdir(parents=True)
        self.code = self.worktrees / "backend"
        self.code.mkdir(parents=True)
        self.ws = PathRoutedWorkspace(base_root=self.base, code_root=self.code)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_milestone_md_resolves_under_base_not_worktree(self):
        """The exact path agents read: orchestrator wrote it under
        ``base/docs/milestones/`` via raw ``Path.write_text``. The
        agent's read MUST resolve to that path, not into its worktree."""
        resolved = self.ws.resolve("docs/milestones/MILESTONE_M1.md")
        self.assertEqual(
            resolved, self.base / "docs/milestones/MILESTONE_M1.md",
            f"docs/ should route to base; got {resolved} (worktree was {self.code})",
        )
        # Negative pin: assert NOT under worktree.
        self.assertFalse(
            str(resolved).startswith(str(self.code) + "/"),
            f"docs/ MUST NOT resolve into worktree {self.code}; got {resolved}",
        )

    def test_briefing_md_resolves_under_base(self):
        """Per-lane briefing the agent reads at implementation start."""
        resolved = self.ws.resolve("docs/briefings/BRIEFING_M1_backend.md")
        self.assertEqual(
            resolved, self.base / "docs/briefings/BRIEFING_M1_backend.md",
        )

    def test_roadmap_md_resolves_under_base(self):
        """ROADMAP.md is also at base/docs/."""
        resolved = self.ws.resolve("docs/ROADMAP.md")
        self.assertEqual(resolved, self.base / "docs/ROADMAP.md")

    def test_no_agent_can_write_under_docs(self):
        """``docs/`` is orchestrator-authored. No agent may write."""
        for agent in ("backend", "frontend", "verifier", "orchestrator", "debugger"):
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed("docs/whatever.md", agent),
                    f"agent {agent} should NOT be allowed to write under docs/",
                )

    def test_routing_table_has_docs_entry(self):
        """Pin the table entry shape so future edits don't silently
        regress the resolution target or open up writers."""
        matches = [r for r in ROUTING_TABLE if r[0] == "docs/"]
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one docs/ routing entry; found {len(matches)}",
        )
        prefix, target, writers, _doc = matches[0]
        self.assertEqual(target, "base", "docs/ must target base_root")
        self.assertEqual(
            writers, frozenset(),
            f"docs/ must be read-only (frozenset()); got writers={writers}",
        )


if __name__ == "__main__":
    unittest.main()
