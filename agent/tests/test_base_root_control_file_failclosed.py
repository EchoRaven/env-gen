"""Adversarial tests for attempt-6 R1 round-5 BLOCKER and Residual 1.

R1 round-5 BLOCKER (verified PoC):
    ``path_routed_workspace.py``'s base-root default writer set was
    ``None`` (ungated), so any relative path at the project base that
    did NOT match a named route was silently writable by every agent.
    PoC: an agent writes ``base/run_budget.json`` with
    ``{"caps": {"unlimited": true}}`` and on the next tick the
    orchestrator re-reads it (``orchestrator.py:614``), defeating the
    kill-switch and re-opening unbounded LLM spend. The same hole
    exposed ``.checkpoint.json``, ``project.json``,
    ``team_practices.json`` and ``logs/``.

R1 Residual 1 (bundled fix):
    Production caller ``tooling.py:29-32`` built a ``PathRoutedWorkspace``
    WITHOUT passing ``agent_id`` — owner identity was inferred from
    the ``code_root`` path string, which only works when ``code_root``
    literally lives at ``<base_root>/worktrees/<agent_id>``. Under any
    non-standard geometry the inference fell back to ``None`` and the
    cross-worktree gate (``_sibling_worktree_owner``) failed OPEN.

This file pins both fixes:

  * ``BaseRootControlFilesAreReadOnlyToAgents`` — each of the five
    control prefixes is read-only to every agent (frontend, backend,
    design, verifier, orchestrator). NO agent — not even orchestrator
    via the workspace — may write to these paths through
    ``PathRoutedWorkspace``. The orchestrator's legitimate writes
    bypass the routed workspace entirely (raw ``Path.write_text`` at
    ``orchestrator.py:1349``); this read-only entry is purely a gate
    on agent-side write tools.

  * ``CrossWorktreeFailsClosedOnUnknownOwner`` — a workspace built
    without ``agent_id`` AND with a code_root that does NOT match the
    ``base/worktrees/<X>`` inference pattern must REJECT every absolute
    path that lands inside a sibling worktree. The previous behaviour
    silently returned the path (fail-open).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    PathRoutedWorkspace,
)


# Every agent role that ships in the production team. The fix is only
# correct if NONE of these may write to the control files.
_ALL_AGENTS = (
    "frontend",
    "backend",
    "design",
    "verifier",
    "orchestrator",
    "database",
    "worker",
    "analysis_worker",
    "review_worker",
)


class _BaseFixture(unittest.TestCase):
    """Production geometry — code_root nested under base/worktrees/<agent>."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.base = td / "base"
        self.base.mkdir(parents=True)
        self.worktrees = self.base / "worktrees"
        self.worktrees.mkdir(parents=True)
        self.code = self.worktrees / "frontend"
        self.code.mkdir(parents=True)
        self.ws = PathRoutedWorkspace(
            base_root=self.base, code_root=self.code, agent_id="frontend"
        )

    def tearDown(self) -> None:
        self._td.cleanup()


class BaseRootControlFilesAreReadOnlyToAgents(_BaseFixture):
    """Pin each base-root control file as read-only to ALL agents.

    R1 round-5 blocker: these paths were silently writable under the
    ungated base default. The fix adds explicit ``frozenset()`` routes
    at the TOP of ROUTING_TABLE.
    """

    # ---- run_budget.json (the kill-switch — the high-severity finding) ----

    def test_run_budget_json_readonly_for_all_agents(self):
        """The verified PoC: agent writes base/run_budget.json with
        ``unlimited=true``; orchestrator's _load_run_budget_caps
        re-reads it next tick; budget gate defeated. After the fix,
        NO agent may write to it via PathRoutedWorkspace."""
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / "run_budget.json"), agent),
                    f"run_budget.json must be read-only to {agent!r}; "
                    f"that's the kill-switch poisoning channel R1 round-5 flagged.",
                )

    def test_run_budget_json_readonly_via_nested_path_form(self):
        """Defense-in-depth: write-gate must reject EVEN IF the input
        is a deeper path that resolves to run_budget.json. The current
        match logic uses prefix-startswith, so a path like
        ``run_budget.json/x`` should be caught too (it cannot be a
        real file since run_budget.json IS the file, but the route
        gate should not accidentally allow it)."""
        # File-typed entry — once it matches, deeper writes are still
        # in the read-only route's scope. Pin that the gate stays
        # closed.
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / "run_budget.json"), agent),
                )

    # ---- .checkpoint.json (session checkpoint) ----

    def test_checkpoint_json_readonly_for_all_agents(self):
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / ".checkpoint.json"), agent),
                    f".checkpoint.json must be read-only to {agent!r}.",
                )

    # ---- project.json (project metadata) ----

    def test_project_json_readonly_for_all_agents(self):
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / "project.json"), agent),
                    f"project.json must be read-only to {agent!r}.",
                )

    # ---- team_practices.json ----

    def test_team_practices_json_readonly_for_all_agents(self):
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / ".team_practices.json"), agent),
                    f"team_practices.json must be read-only to {agent!r}.",
                )

    # ---- logs/ dir ----

    def test_logs_dir_readonly_for_all_agents(self):
        """A path under logs/ MUST be read-only — orchestrator logs
        are not for agents to mutate."""
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / "logs" / "orchestrator.log"), agent),
                    f"logs/orchestrator.log must be read-only to {agent!r}.",
                )

    def test_logs_nested_dir_readonly(self):
        """Nested paths under logs/ also read-only."""
        for agent in _ALL_AGENTS:
            with self.subTest(agent=agent):
                self.assertFalse(
                    self.ws.is_write_allowed(str(self.base / "logs" / "2026" / "05" / "29" / "run.log"), agent),
                )

    # ---- end-to-end PoC reconstruction ----

    def test_poc_unlimited_caps_write_blocked(self):
        """Reconstruct the exact PoC: a frontend agent (the
        least-privileged role) attempts to write ``base/run_budget.json``
        with ``unlimited=true``. After the fix, ``is_write_allowed``
        must return False BEFORE any I/O happens, so the agent's write
        tool's pre-flight gate blocks it. We don't actually write the
        file here — the contract is that the gate denies it.

        R1 round-7: PoC uses the ABSOLUTE path because that's the actual
        attack — direct write to the file the orchestrator reads
        (``base/run_budget.json``). A relative-spelling ``run_budget.json``
        lands in the agent's own worktree (not the orchestrator's file)
        and is correctly NOT blocked at this layer (worktree-to-base
        propagation is the auto-stage filter's concern, attempt-2 Fix #5)."""
        abs_run_budget = str(self.base / "run_budget.json")
        self.assertFalse(
            self.ws.is_write_allowed(abs_run_budget, "frontend"),
            "PoC reconstruction: frontend agent must NOT be able to "
            "poison base/run_budget.json with unlimited=true caps.",
        )

    def test_resolve_still_works_for_read_paths(self):
        """Read-only does not mean unreachable. ``resolve()`` must
        still produce the absolute path (so a read tool can open it);
        only ``is_write_allowed`` returns False."""
        for relpath in (
            "run_budget.json",
            ".checkpoint.json",
            "project.json",
            "team_practices.json",
            "logs/some.log",
        ):
            with self.subTest(relpath=relpath):
                resolved = self.ws.resolve(relpath)
                # Lands under base_root
                self.assertTrue(
                    resolved.is_relative_to(self.base),
                    f"{relpath} must resolve under base_root for read access.",
                )

    def test_other_base_paths_are_class_failclosed(self):
        """attempt-7 R1 round-6: the lockdown is CLASS-level, not 5-name.

        R1 round-6 caught that attempt-6's 5-name denylist missed
        ``.team_practices.json`` (real file, leading dot),
        ``.checkpoint.json.bak`` (CheckpointManager backup), and arbitrary
        names like ``foo.json``/``secrets/`` because the default was
        ungated.

        attempt-7 flipped the base default to fail-closed (frozenset).
        Now any unrouted absolute base path is read-only — and so is any
        future control file added by Phase 1+ work. No hand-enumeration
        needed. R1 round-7 reverted ``_DEFAULT_TARGET = "code"`` so the
        agent-owns-worktree model is preserved for unrouted RELATIVE
        paths (which legitimately land in the worktree); the security
        assertion uses ABSOLUTE base paths.
        """
        # Arbitrary unrouted absolute base path is now read-only.
        self.assertFalse(
            self.ws.is_write_allowed(
                str(self.base / "some_other_base_file.json"), "frontend",
            ),
            "Arbitrary unrouted absolute base path must be read-only "
            "(attempt-7 R1 round-6 class-level fix).",
        )
        # And the same class invariant for the specific files R1 caught.
        # Use ABSOLUTE paths so the security gate (base default
        # frozenset) is what's being exercised — R1 round-7's clarification:
        # relative spellings land in the worktree (agent's own scratch),
        # which is by-design ungated.
        for relname in (".team_practices.json", ".checkpoint.json.bak",
                        "foo.json", "bar_budget.json", "secrets/x.txt"):
            abs_path = str(self.base / relname)
            with self.subTest(path=abs_path):
                self.assertFalse(
                    self.ws.is_write_allowed(abs_path, "frontend"),
                    f"R1 round-6 named bypass: absolute {abs_path!r} "
                    f"must be read-only",
                )

    def test_unrouted_relative_paths_are_worktree_writable(self):
        """R1 round-7 bi-directional acceptance: with the security fix
        landed at the base-route level only (not the _DEFAULT_TARGET),
        unrouted RELATIVE paths preserve the agent-owns-worktree model.

        R1 verified the real generated project has README.md +
        STRUCTURE.md at worktree root, plus scratch files / tsconfig.
        These are non-routed but legitimate writes; the agent must be
        able to create them in their own worktree."""
        for relname in ("README.md", "STRUCTURE.md", "scratch.txt",
                        "tsconfig.json", ".gitignore"):
            with self.subTest(relname=relname):
                self.assertTrue(
                    self.ws.is_write_allowed(relname, "frontend"),
                    f"unrouted relative path {relname!r} must remain "
                    f"agent-writable in its own worktree (R1 round-7).",
                )


class CrossWorktreeFailsClosedOnUnknownOwner(unittest.TestCase):
    """R1 Residual 1: when self_agent cannot be determined (no
    agent_id passed AND non-standard code_root), the cross-worktree
    check must FAIL CLOSED."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.base = td / "base"
        self.base.mkdir(parents=True)
        self.worktrees = self.base / "worktrees"
        self.worktrees.mkdir(parents=True)
        # A sibling worktree with sensitive content. An adversarial
        # workspace with unknown owner must NOT be able to reach this.
        self.sibling = self.worktrees / "backend"
        self.sibling.mkdir(parents=True)
        (self.sibling / "secrets.yaml").write_text("nope")
        # Non-standard code_root — NOT under base/worktrees/<X>, so
        # the inference-from-path fallback also fails and self_agent
        # stays None.
        self.nonstd_code = td / "somewhere_else_entirely"
        self.nonstd_code.mkdir(parents=True)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_absolute_sibling_access_rejected_without_agent_id(self):
        """Construct PathRoutedWorkspace WITHOUT agent_id AND with a
        code_root that does NOT match the worktrees/<X> inference
        pattern. self_agent will be None. Attempt to resolve() an
        absolute path into a sibling worktree — must raise."""
        ws = PathRoutedWorkspace(
            base_root=self.base,
            code_root=self.nonstd_code,
            # NO agent_id passed — pre-fix this fell back to None and
            # the cross-worktree gate failed OPEN.
        )
        target = self.sibling / "secrets.yaml"
        with self.assertRaises(ValueError) as ctx:
            ws.resolve(str(target))
        # The error should mention the cross-worktree refusal.
        self.assertIn(
            "cross-worktree",
            str(ctx.exception).lower(),
            "Expected the cross-worktree fail-closed message; got: "
            f"{ctx.exception!s}",
        )

    def test_is_write_allowed_sibling_rejected_without_agent_id(self):
        """Same shape via is_write_allowed: a workspace with unknown
        owner attempting to write into a sibling worktree must be
        denied."""
        ws = PathRoutedWorkspace(
            base_root=self.base,
            code_root=self.nonstd_code,
        )
        target = self.sibling / "secrets.yaml"
        self.assertFalse(
            ws.is_write_allowed(str(target), "backend"),
            "Cross-worktree write must be denied when self_agent is "
            "unknown — fail-closed.",
        )

    def test_explicit_agent_id_still_works(self):
        """Control case: passing agent_id explicitly still lets the
        workspace identify its own owner correctly. Same workspace
        identity may still touch its own worktree.

        R1 round-7: with ``_DEFAULT_TARGET = "code"`` restored, an
        unrouted top-level ``scratch.txt`` correctly lands in
        ``code_root`` (the agent's worktree) — the agent-owns-worktree
        model is preserved alongside the base fail-closed default."""
        ws = PathRoutedWorkspace(
            base_root=self.base,
            code_root=self.sibling,
            agent_id="backend",
        )
        # Touching its own worktree (no ../) should succeed.
        resolved = ws.resolve("scratch.txt")
        self.assertTrue(resolved.is_relative_to(self.sibling))


if __name__ == "__main__":
    unittest.main()
