"""Phase 0.2 attempt-5 FIX B — R1 round-4 hole B regression coverage.

R1 round-4 finding (HOLE B): ``AgentTooling.set_hubs``
(``multi_agent/agents/runtime/tooling.py``, lines ~116-126 in the
pre-fix tree) was previously a 'best-effort' worktree registration:
when ``hubs.codehub.register_agent_worktree`` raised, OR when (in
legacy / mocked call sites) it returned ``None``, the code only
logged a WARNING and CONTINUED. That left the tool pool bound to
the bare ``Workspace`` that ``_register_env_gen_tools`` builds
when no worktree is available — a ``Workspace`` that does NOT
carry the ``ROUTING_TABLE``-driven per-route write gate of
``PathRoutedWorkspace``.

Net effect of the silent degrade: any registration hiccup
re-opened the arbitrary host-write surface that the Phase 0.2
hardening was supposed to close. ``GenerateSeedSQLTool``'s raw
``open(output_file, "w")`` (data_engine_tools.py:810) skips
``workspace.resolve()`` for absolute paths and depends on the
role-write gate firing against a ``PathRoutedWorkspace`` to deny
out-of-base writes. With the bare ``Workspace`` quietly left in
place, that defence collapsed.

The fix in ``tooling.py``: registration must fail-CLOSED.
  * ``register_agent_worktree`` raising → log ERROR explaining the
    security implication and raise ``RuntimeError``.
  * ``register_agent_worktree`` returning ``None`` → same
    treatment.
  * The downstream tool pool rebuild is also fail-closed: a
    rebuild exception aborts the agent rather than leaving a
    half-replaced registry on a permissive base.

These tests pin that contract end-to-end:

  1. ``register_agent_worktree`` returning ``None`` MUST cause
     ``set_hubs`` to raise ``RuntimeError`` (not log-warning-and-
     continue).
  2. ``register_agent_worktree`` raising MUST propagate as a
     ``RuntimeError`` (or the original exception type wrapped) —
     NOT be swallowed.
  3. Happy path: a successful registration proceeds as before
     and attaches a ``_routed_workspace``. No regression on the
     normal flow.

If a future commit reintroduces the silent-degrade pattern (any
``except Exception: ... self._logger.warning(...)`` around the
registration call without a re-raise), tests (1) and (2) turn
red. If the rebuild-on-PathRoutedWorkspace path stops attaching
``_routed_workspace``, test (3) turns red.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402
from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402
from multi_agent.workspace_manager import WorkspaceManager  # noqa: E402


class _StubAgent(AgentTooling):
    """Minimal ``AgentTooling`` subclass exposing exactly what
    ``set_hubs`` and ``_register_env_gen_tools`` read.

    The historic call shape (real agents): ``__init__`` builds a
    tool pool on the bare ``Workspace``, then later ``set_hubs``
    fires worktree registration + tool-pool rebuild. This stub
    reproduces that sequencing — the stub's ``__init__`` does NOT
    pre-build a routed workspace; ``set_hubs`` is what would do
    that on a real agent.
    """

    allowed_tool_categories = ["file", "reasoning"]
    _include_vision = False

    def __init__(self, agent_id: str, base_dir: Path):
        self.agent_id = agent_id
        self.workspace = WorkspaceManager(base_dir)
        self._logger = MagicMock()
        self._tool_instances: dict = {}
        # Minimal stand-in for ToolRegistry: only the ``_tools``
        # dict attribute is touched by ``set_hubs`` (to clear the
        # registry on rebuild) and ``register``/``to_openai_tools``
        # by ``_register_env_gen_tools`` / ``get_tools_for_llm``.
        self._tools = MagicMock()
        self._tools._tools = {}
        self._allow_tools: list = []
        self._deny_tools: list = []
        self._tool_bundle_ids: list = []
        self._worktree_dir = None
        self.llm = None


def _make_hubs_returning(value):
    """Build a fake hubs object whose ``codehub.register_agent_worktree``
    returns the supplied value (which may be ``None`` to exercise
    the fail-closed-on-None branch)."""
    hubs = MagicMock()
    hubs.codehub.register_agent_worktree = MagicMock(return_value=value)
    return hubs


def _make_hubs_raising(exc: BaseException):
    """Build a fake hubs object whose ``codehub.register_agent_worktree``
    raises ``exc`` — used to exercise the fail-closed-on-raise
    branch."""
    hubs = MagicMock()
    hubs.codehub.register_agent_worktree = MagicMock(side_effect=exc)
    return hubs


class WorktreeRegistrationFailsClosed(unittest.TestCase):
    """R1 round-4 Hole B: registration failure must NOT silently
    fall back to bare Workspace."""

    def test_registration_returning_none_aborts(self):
        """``register_agent_worktree`` → ``None``. ``set_hubs`` must
        raise ``RuntimeError`` (NOT log-warning-and-continue, which
        was the pre-fix behaviour and the exact regression R1 round-4
        hole B flagged)."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", Path(tmp))
            hubs = _make_hubs_returning(None)
            with self.assertRaises(RuntimeError) as ctx:
                agent.set_hubs(hubs)
            self.assertIn("registration failed", str(ctx.exception).lower())
            # Also confirm we did NOT silently install a worktree
            # dir — the fail-closed contract is that the agent never
            # transitions out of the unregistered state on failure.
            self.assertIsNone(agent._worktree_dir)
            # ERROR-level log MUST be emitted (the WARNING-only
            # behaviour was the regression).
            self.assertTrue(
                agent._logger.error.called,
                "fail-closed contract: registration failure must log "
                "at ERROR explaining the security implication, not "
                "WARNING (R1 round-4 hole B).",
            )

    def test_registration_raising_propagates(self):
        """``register_agent_worktree`` raising must propagate (as a
        ``RuntimeError`` or its original type) — NOT be swallowed
        into a warning."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", Path(tmp))
            hubs = _make_hubs_raising(OSError("disk full"))
            with self.assertRaises((OSError, RuntimeError)) as ctx:
                agent.set_hubs(hubs)
            # The fail-closed path wraps the underlying exception in
            # a RuntimeError citing the hole — the original cause is
            # preserved via ``raise ... from`` so debuggers see the
            # OSError on the chain.
            chain_repr = repr(ctx.exception) + " ; cause=" + repr(getattr(ctx.exception, "__cause__", None))
            self.assertIn("disk full", chain_repr)
            self.assertIsNone(agent._worktree_dir)
            self.assertTrue(
                agent._logger.error.called,
                "fail-closed contract: registration exception must "
                "log at ERROR — silent-warning is the regression.",
            )

    def test_successful_registration_proceeds(self):
        """Happy path regression check — a successful registration
        attaches ``_worktree_dir`` and rebuilds the tool pool on a
        ``PathRoutedWorkspace`` (visible via ``_routed_workspace``).
        Ensures the fail-closed wiring did NOT also break the legit
        flow."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True, exist_ok=True)
            agent = _StubAgent("backend", base)
            hubs = _make_hubs_returning(wt)
            # ``set_hubs`` must NOT raise on the happy path.
            agent.set_hubs(hubs)
            self.assertEqual(agent._worktree_dir, wt)
            # The rebuild path wires up the routed workspace — its
            # presence is the discriminator between "live gate" and
            # the silent-degrade regression.
            #
            # attempt-6 HARDENING A (R1 round-5 FIX B residual): tighten
            # from ``assertIsNotNone`` to ``assertIsInstance`` against
            # ``PathRoutedWorkspace``. A truthy-but-wrong-type value
            # (e.g. the bare ``Workspace`` silently re-installed by a
            # future regression, or a stray sentinel) would have
            # satisfied ``assertIsNotNone`` while still bypassing the
            # ROUTING_TABLE-driven per-route write gate. Asserting the
            # actual class pins the security-relevant invariant.
            self.assertTrue(hasattr(agent, "_routed_workspace"))
            self.assertIsInstance(agent._routed_workspace, PathRoutedWorkspace)


class HubsRegistryMissingCodehubFailsClosed(unittest.TestCase):
    """R1 round-5 FIX B residual: a hubs object lacking ``codehub`` must
    abort ``set_hubs`` rather than silently skip registration.

    The attempt-5 fix-closed contract guarded the case where
    ``register_agent_worktree`` raised or returned ``None``, but the
    enclosing ``hasattr(hubs, "codehub")`` gate meant a hubs object
    that simply didn't expose ``codehub`` at all bypassed the contract
    entirely — leaving the agent on the bare permissive ``Workspace``
    (R1 round-4 hole B regression). attempt-6 raises on that path.
    """

    def test_hubs_without_codehub_attribute_aborts(self) -> None:
        """A hubs object without a ``codehub`` attribute must trigger
        ``RuntimeError`` — NOT a silent skip that leaves the bare
        ``Workspace`` in place."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", Path(tmp))

            # Build a hubs object that does NOT expose ``codehub``.
            # MagicMock auto-creates attributes on access, so use a
            # plain object subclass instead to genuinely lack the
            # attribute.
            class _HubsNoCodehub:
                pass

            hubs = _HubsNoCodehub()
            self.assertFalse(hasattr(hubs, "codehub"))

            with self.assertRaises(RuntimeError) as ctx:
                agent.set_hubs(hubs)

            # The error message must cite the residual to make
            # forensic root-cause obvious in operator logs.
            err_msg = str(ctx.exception).lower()
            self.assertIn("codehub", err_msg)
            self.assertIn("bare workspace", err_msg.replace("permissive ", ""))

            # Fail-closed contract: NO worktree dir was installed.
            self.assertIsNone(agent._worktree_dir)

            # ERROR-level diagnostic must have been emitted, not a
            # WARNING (silent-degrade is exactly the regression).
            self.assertTrue(
                agent._logger.error.called,
                "fail-closed contract: missing codehub must log at "
                "ERROR explaining the security implication (R1 "
                "round-5 FIX B residual).",
            )


if __name__ == "__main__":
    unittest.main()
