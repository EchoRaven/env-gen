"""Sandbox principle pin #2: agent system-prompt's ``workspace_dir``
context variable must never carry the host's absolute base_dir prefix.

Background (smoke #24, post-Fix-#3):
    Fix #3 plugged the absolute-path leak in the codehub ``worktree_registered``
    event payload (the FIRST surface backend's inbox saw). Smoke #24 confirmed
    that fix live — orchestrator/backend/frontend all read ``path:
    "worktrees/<id>"`` from check_inbox. But backend STILL constructed every
    write as ``/tmp/envgen_demo/.../app/backend/...`` and path_routed_workspace
    denied them all.

Root cause:
    ``ConfigurableAgent._get_context_vars`` rendered
    ``workspace_dir = str(self.workspace.base_dir)`` — the host's absolute
    ``/tmp/envgen_demo/<project>/`` prefix — and the shared prompt template
    ``agents/shared/agent_definition_v3.j2:136`` embedded it as
    ``Workspace scope: `{{ workspace }}` `` in every agent's system prompt.
    Backend learned the host prefix at startup and joined it onto every
    relative path the kickoff briefing referenced.

Fix: hardcode ``"."`` (matches the macro's default; tool surface routes
relative paths through the routing table, so the agent never needs the
host prefix).

This test pins:
  - ``_get_context_vars()`` returns ``workspace_dir`` that does NOT start
    with ``/tmp/`` and does NOT equal the workspace's absolute base_dir.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.configurable_agent import ConfigurableAgent  # noqa: E402


class _StubWorkspace:
    """Minimal stand-in for ``self.workspace`` — only needs ``base_dir``."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir


def _make_bare_agent(base_dir: Path) -> ConfigurableAgent:
    """Bypass ConfigurableAgent.__init__ (heavy) and inject only the
    fields ``_get_context_vars`` reads: ``workspace``, ``_spawn_role``,
    ``_requested_agent_type``, ``gen_context``, ``_prompt_cfg``."""
    agent = object.__new__(ConfigurableAgent)
    agent.workspace = _StubWorkspace(base_dir)
    agent._spawn_role = None
    agent._requested_agent_type = None
    agent.gen_context = None
    agent._prompt_cfg = {}
    return agent


class ConfigurableAgentWorkspaceDirNoAbsPath(unittest.TestCase):
    """Smoke #24 follow-on: plug the prompt-template leak at source."""

    def test_workspace_dir_does_not_leak_abs_base_dir(self):
        """``_get_context_vars()['workspace_dir']`` must NOT carry the
        host's absolute base_dir prefix. Pre-fix this returned
        ``str(self.workspace.base_dir)``. Post-fix it is ``"."``."""
        with tempfile.TemporaryDirectory(prefix="envgen_ctx_var_") as td:
            base = Path(td)
            agent = _make_bare_agent(base)
            ctx = agent._get_context_vars()

            ws_dir = ctx["workspace_dir"]
            self.assertFalse(
                ws_dir.startswith("/tmp/"),
                f"workspace_dir leaks host /tmp/ prefix: {ws_dir!r}. "
                f"Agent system prompt would render 'Workspace scope: "
                f"`{ws_dir}`' and the agent would join the prefix onto "
                f"every relative path in its briefing.",
            )
            self.assertNotEqual(
                ws_dir, str(base),
                f"workspace_dir equals absolute base_dir ({base!r}) — "
                f"the sandbox principle is broken. From the agent's POV "
                f"workspace root must be `/` (or `.`), not the host's "
                f"absolute prefix.",
            )

    def test_workspace_dir_falls_back_when_no_workspace(self):
        """If ``self.workspace`` is None (rare, e.g. test stubs),
        the fallback should still be a safe sentinel, not raise."""
        agent = object.__new__(ConfigurableAgent)
        agent.workspace = None
        agent._spawn_role = None
        agent._requested_agent_type = None
        agent.gen_context = None
        agent._prompt_cfg = {}
        ctx = agent._get_context_vars()
        ws_dir = ctx["workspace_dir"]
        self.assertFalse(
            ws_dir.startswith("/tmp/") or ws_dir.startswith("/"),
            f"workspace_dir fallback should not be absolute: {ws_dir!r}",
        )

    def test_workspace_dir_exact_value_pin(self):
        """Exact pin: the value is ``"."`` — matches the j2 macro's
        default (``workspace_dir="."``)."""
        with tempfile.TemporaryDirectory(prefix="envgen_ctx_var_") as td:
            agent = _make_bare_agent(Path(td))
            ctx = agent._get_context_vars()
            self.assertEqual(ctx["workspace_dir"], ".")


if __name__ == "__main__":
    unittest.main()
