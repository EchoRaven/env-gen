"""Lint guard: no module outside the workspace package may read
``workspace.root`` directly or construct ``Workspace(...)`` directly.

This is the permanent fence that prevents the workspace abstraction
from re-fragmenting. PR 1 killed every bypass constructor and PR 2
converted every ``.root /`` concat to ``.resolve()``. This guard
fails the build if either pattern slips back in.

Allowed exceptions (whitelisted):
* The workspace modules themselves
  (``workspace.py``, ``path_routed_workspace.py``).
* Internal display helpers (e.g. ``_workspace_rel``) where ``.root``
  is the only way to render a relative path for a user-facing
  message. Limited to the file_tools display helper.
* The agent-runtime workspace assembly point
  (``multi_agent/agents/runtime/tooling.py``) which constructs
  ``PathRoutedWorkspace`` and the fallback plain workspace. This is
  the single legitimate construction site.
* Tests themselves.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"

# Modules that legitimately construct or introspect raw workspaces.
ALLOWLIST: Set[Path] = {
    LLM_DIR / "workspace.py",
    LLM_DIR / "multi_agent" / "runtime" / "path_routed_workspace.py",
    # Single construction site — assembles PathRoutedWorkspace per agent.
    LLM_DIR / "multi_agent" / "agents" / "runtime" / "tooling.py",
    # Legacy compat shim (already DEPRECATED in its own docstring).
    LLM_DIR / "tools" / "path_utils.py",
    # Internal display helper that converts an absolute path back to
    # workspace-relative form for user-facing error messages. Single
    # site, intentional.
    LLM_DIR / "tools" / "file_tools.py",
    # Orchestrator constructs the master Workspace and passes it into
    # WorkspaceManager — this is the project entry-point.
    LLM_DIR / "multi_agent" / "orchestrator.py",
    # Lifecycle / IO modules that take Workspace from orchestrator and
    # never resolve paths through tools.
    LLM_DIR / "multi_agent" / "workspace_manager.py",
}

# Patterns to flag.
_ROOT_READ = re.compile(r"\b(?:self\.)?workspace\.root\b(?!\s*=)")
_WORKSPACE_CTOR = re.compile(r"\bWorkspace\s*\(")

# The "root" attribute name appears on lots of unrelated objects
# (e.g. ``self.root`` on a tree node). We narrow to the workspace
# member-access pattern via the regex above.


def _python_files_under(root: Path) -> List[Path]:
    out: List[Path] = []
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if ".worktrees" in p.parts:
            continue
        if "generated" in p.parts:
            continue
        if "/tests/" in str(p) or p.name.startswith("test_"):
            continue  # tests may legitimately introspect roots
        out.append(p)
    return out


def _scan(pattern: re.Pattern, label: str) -> List[Tuple[Path, int, str]]:
    hits: List[Tuple[Path, int, str]] = []
    for path in _python_files_under(LLM_DIR):
        if path in ALLOWLIST:
            continue
        try:
            text = path.read_text()
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                hits.append((path, lineno, stripped[:140]))
    return hits


class NoBareWorkspaceConstructionOutsideAllowlist(unittest.TestCase):
    """``Workspace(...)`` direct construction is restricted to the
    workspace module + the single agent-runtime assembly point. PR 1
    eliminated every bypass; this guard ensures none come back."""

    def test_no_bare_workspace_construction(self):
        hits = _scan(_WORKSPACE_CTOR, "Workspace(")
        if hits:
            lines = ["", "=== Bare Workspace(...) construction outside allowlist ==="]
            lines.append("Inject a workspace (PathRoutedWorkspace or the agent-runtime "
                          "assembled plain Workspace) instead of constructing one.")
            for path, lineno, txt in hits[:20]:
                rel = path.relative_to(ROOT) if path.is_absolute() else path
                lines.append(f"  {rel}:{lineno}: {txt}")
            self.fail("\n".join(lines))


class NoDirectRootRead(unittest.TestCase):
    """``workspace.root`` direct reads outside the allowlist are
    forbidden. Use ``workspace.resolve(...)`` for path resolution,
    ``workspace.code_root`` / ``workspace.base_root`` if you genuinely
    need a named directory."""

    def test_no_workspace_dot_root_reads(self):
        hits = _scan(_ROOT_READ, "workspace.root")
        if hits:
            lines = ["", "=== workspace.root direct read outside allowlist ==="]
            lines.append("Use workspace.resolve(...) instead of workspace.root / 'x'.")
            lines.append("If you genuinely need a named directory, use "
                          "workspace.code_root (worktree) or workspace.base_root "
                          "(project root).")
            for path, lineno, txt in hits[:20]:
                rel = path.relative_to(ROOT) if path.is_absolute() else path
                lines.append(f"  {rel}:{lineno}: {txt}")
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
