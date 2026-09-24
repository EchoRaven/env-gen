"""#1202fp -- coverage/deliverability audits must read the SHARED project tree, not the
calling agent's worktree.

tiktok-r96, measured on disk:

    worktrees/orchestrator/app/frontend/src/pages   0 files
    worktrees/{backend,frontend,verifier,debugger}  21 files each
    the shipped tree (root, on integration)         21 files

`coverage_audit_check` is orchestrator-only and resolved its root to
``workspace.root`` -- the orchestrator's own worktree -- so it reported all 19 declared
pages as missing. A real count of the wrong tree, published by deliverability as a
delivery blocker the frontend lane could never satisfy: the files were already present in
the tree docker-compose actually builds.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent import tool_bundles as TB  # noqa: E402


class _WS:
    """Mirrors PathRoutedWorkspace: .root is the agent's CODE root, .base_root shared."""

    def __init__(self, base, code):
        self.base_root = Path(base)
        self.root = Path(code)
        self.code_root = Path(code)


class _Ctx:
    def __init__(self, workspace=None, app_root=None, workspace_path=None):
        if workspace is not None:
            self.workspace = workspace
        if app_root is not None:
            self.app_root = app_root
        if workspace_path is not None:
            self.workspace_path = workspace_path


def test_prefers_the_shared_tree_over_the_lane_worktree(tmp_path):
    out = tmp_path / "generated" / "env-r1"
    wt = out / "worktrees" / "orchestrator"
    assert TB._audit_root_1202fp(_Ctx(_WS(out, wt))) == out


def test_never_returns_a_worktree_when_a_base_exists(tmp_path):
    """The defect in one line: the audit must not read a path under worktrees/."""
    out = tmp_path / "out"
    wt = out / "worktrees" / "orchestrator"
    got = Path(str(TB._audit_root_1202fp(_Ctx(_WS(out, wt)))))
    assert "worktrees" not in got.parts, f"audit still points into a worktree: {got}"


def test_explicit_app_root_still_wins(tmp_path):
    out, wt = tmp_path / "out", tmp_path / "out" / "worktrees" / "x"
    ctx = _Ctx(_WS(out, wt), app_root=str(tmp_path / "explicit"))
    assert getattr(ctx, "app_root") == str(tmp_path / "explicit")


def test_workspace_without_base_root_falls_back_to_root(tmp_path):
    """Older/plain workspaces expose only .root -- behave exactly as before."""
    class _Plain:
        def __init__(self, root):
            self.root = Path(root)

    d = tmp_path / "plain"
    assert TB._audit_root_1202fp(_Ctx(_Plain(d))) == d


def test_no_workspace_falls_back_to_workspace_path(tmp_path):
    d = str(tmp_path / "wp")
    assert TB._audit_root_1202fp(_Ctx(workspace_path=d)) == d


def test_nothing_available_returns_none():
    assert TB._audit_root_1202fp(_Ctx()) is None


def test_both_bundles_use_the_same_resolver():
    """The two audits must not drift apart again -- that split is what #1202fn fixed
    one level down."""
    import inspect
    for fn in (TB._bundle_coverage_tools, TB._bundle_deliverability_tools):
        src = inspect.getsource(fn)
        assert "_audit_root_1202fp" in src, f"{fn.__name__} resolves its root separately"
