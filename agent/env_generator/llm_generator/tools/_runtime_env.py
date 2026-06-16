"""Runtime subprocess env helpers — used by ``runtime_tools.py``'s
``ExecuteBashTool`` and ``RunBackgroundTool`` (and by ``ProcessManager``
defaults when no explicit env is supplied).

These helpers are infrastructure, not tools — they create the agent's
sandbox HOME directory and compute the minimal-passthrough env. The
writes happen at env-setup time, not in response to LLM tool calls,
so they intentionally do NOT route through the role-write gate
(``workspace.is_write_allowed``). Lives in its own module so the
write-gate scanner (``test_write_gate_invariant.py``) does not follow
the call chain back into a tool class and misattribute the writes.

PR2.1 (Loop B ①⑦): host-identity vars (HOME/USER/SUDO_USER/LOGNAME)
were dropped from the passthrough so agent commands cannot read host
credentials.

PR2.3 (Loop B ⑪): HOME is restored, but pointed at a workspace-local
sandbox (``<workspace_root>/.agent_home``) — preserves containment
while keeping ``~``-dependent tools (npm/pip/git) functional.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


# Vars allowed to pass through from the host into agent subprocesses.
# PR2.1 (Loop B ⑦): hoisted to module scope so both ExecuteBashTool
# and RunBackgroundTool reference the same set.
_SUBPROCESS_ENV_PASSTHROUGH = {
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "TERM", "TMPDIR",
    "DOCKER_HOST",
    "PIP_CACHE_DIR", "NPM_CONFIG_CACHE", "NODE_PATH", "VIRTUAL_ENV",
}


def DEFAULT_SUBPROCESS_ENV() -> dict:
    """Minimal env: PATH/locale/cache vars only, no host identity."""
    env = {k: v for k, v in os.environ.items() if k in _SUBPROCESS_ENV_PASSTHROUGH}
    env.update({
        "PYTHONUNBUFFERED": "1",
        "DOCKER_BUILDKIT": "0",
        "COMPOSE_DOCKER_CLI_BUILD": "0",
    })
    return env


def ensure_workspace_home(workspace: Any) -> Optional[Path]:
    """Create a sandbox ``HOME`` for this agent's subprocesses.

    Layout: ``<base_root>/.agent_homes/<agent_id>/`` — INTENTIONALLY
    above each agent's git worktree, not inside it. Smoke #29
    (2026-06-04) showed the prior layout (``<code_root>/.agent_home/``)
    dirtied the worktree on first subprocess call: ``git status`` in
    the worktree reported ``.agent_home/`` as an untracked directory,
    the step-end commit_gate scan turned that into
    ``loose.dirty_worktree=True``, the system urgent ``integrity_check``
    flagged it, and the orchestrator's LLM (already running the
    kickoff facilitate handler) chased the cleanup objective in
    ``memory-bank/`` and ``.agent_home/`` instead of writing the
    ``section='facilitator_note'`` decision the meeting required.
    The kickoff hung at facilitator phase across the full smoke.

    Putting the sandbox above the worktrees keeps the worktree clean
    (its ``git status --porcelain`` ignores siblings of ``worktrees/``)
    AND keeps the existing PR2.3 / Loop B ⑪ containment intact —
    sandbox HOME is still inside the project's ``base_root``, never
    the host's real HOME.

    Returns the sandbox home path, or ``None`` if no
    ``base_root``/``agent_id`` is available. The fallback (no
    ``agent_id``) keeps test-stub callers working without forcing them
    to pass one.
    """
    if workspace is None:
        return None
    base = getattr(workspace, "base_root", None)
    agent_id = getattr(workspace, "agent_id", None)
    if base and agent_id:
        # Production layout: per-agent home above any worktree, so
        # ``git status`` inside any worktree never sees it.
        home = Path(base) / ".agent_homes" / str(agent_id)
    else:
        # Test/fallback path — no agent_id pinned (e.g. SimpleNamespace
        # workspaces in unit tests). Keep the legacy layout so the
        # tests stay simple.
        root = getattr(workspace, "code_root", None) or getattr(
            workspace, "base_root", None
        )
        if not root:
            return None
        home = Path(root) / ".agent_home"
    try:
        home.mkdir(parents=True, exist_ok=True)
        gitconfig = home / ".gitconfig"
        if not gitconfig.exists():
            gitconfig.write_text(
                "[user]\n"
                "\tname = env-gen agent\n"
                "\temail = agent@env-gen.local\n",
                encoding="utf-8",
            )
    except Exception:
        return None
    return home


def workspace_env(workspace: Any) -> dict:
    """``DEFAULT_SUBPROCESS_ENV()`` plus a workspace-local ``HOME``.
    Containment + functionality both preserved.
    """
    env = DEFAULT_SUBPROCESS_ENV()
    home = ensure_workspace_home(workspace)
    if home is not None:
        env["HOME"] = str(home)
        env["USER"] = "agent"
    return env
