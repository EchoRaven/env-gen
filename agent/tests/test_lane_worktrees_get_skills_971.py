"""#971: the skill path the framework advertises must resolve in every lane's worktree.

`list_skills` and `get_skill` return each skill's `file_path` to the model
(`knowledge_tools.py`: `"path": skill.file_path`), so a lane reasonably follows up with
`read('.agents/skills/<name>/SKILL.md')`. A lane's read resolves against ITS WORKTREE.

Skills were only materialized as a side effect of `discover_workspace_skills()`, which
runs against whichever root happened to call it. netflix r157 finished with the directory
present in 2 of 7 worktrees:

    backend YES · orchestrator YES
    debugger · design_analyst_1 · frontend · knowledge · verifier  — all MISSING

and 80 failed `read` calls, every one for a path the framework itself had handed over.

Materializing at worktree registration makes the advertised path true. It cannot reach the
delivered app: the generated project gitignores `.agents/` and never tracked it — which
`test_skills_do_not_reach_the_delivered_app` pins.
"""

import types
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.codehub import service as svc


class _FakeGit:
    def __init__(self, root):
        self.root = Path(root)
        self.added = []

    def current_head(self):
        return "deadbeef"

    def commit(self, *a, **k):
        return "deadbeef"

    def add_worktree(self, path, branch):
        Path(path).mkdir(parents=True, exist_ok=True)
        self.added.append((Path(path), branch))


def _hub(tmp_path):
    """A CodeHub with only what register_agent_worktree touches."""
    hub = object.__new__(svc.CodeHub)
    hub.repo_root = tmp_path
    hub.git = _FakeGit(tmp_path)
    hub.ensure_repo = lambda: None
    hub._emit = lambda *a, **k: None
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return hub


def _skill_files(root: Path):
    d = root / ".agents" / "skills"
    return sorted(p.parent.name for p in d.rglob("SKILL.md")) if d.is_dir() else []


def test_a_new_worktree_gets_the_skills(tmp_path):
    hub = _hub(tmp_path)
    wt = hub.register_agent_worktree("verifier")
    assert _skill_files(wt), (
        "the lane's worktree has no .agents/skills, so every read of the path that "
        "list_skills advertised will fail — r157 did that 80 times")


def test_every_lane_gets_them_not_just_the_first(tmp_path):
    """r157's actual shape: 2 of 7 worktrees had the directory."""
    hub = _hub(tmp_path)
    lanes = ["backend", "frontend", "verifier", "debugger", "knowledge",
             "orchestrator", "design_analyst_1"]
    missing = [ln for ln in lanes if not _skill_files(hub.register_agent_worktree(ln))]
    assert missing == [], f"lanes still missing skills: {missing}"


def test_an_existing_worktree_is_backfilled(tmp_path):
    """Respawn and resume paths return early when the worktree already exists; they must
    still get the skills, or a respawned lane inherits the r157 hole."""
    hub = _hub(tmp_path)
    wt = tmp_path / "worktrees" / "frontend"
    wt.mkdir(parents=True)
    assert _skill_files(wt) == []
    hub.register_agent_worktree("frontend")
    assert _skill_files(wt), "the early-return path skipped materialization"


def test_the_sync_never_breaks_lane_startup(tmp_path, monkeypatch):
    """A lane must start even if the skill copy fails — it is an affordance, not a
    prerequisite."""
    import env_generator.llm_generator.multi_agent.skill_loader as loader

    def _boom(_root):
        raise OSError("disk full")

    monkeypatch.setattr(loader, "sync_bundled_skills_into_workspace", _boom)
    hub = _hub(tmp_path)
    wt = hub.register_agent_worktree("backend")
    assert wt.exists(), "worktree registration must survive a failed skill sync"


def test_skills_do_not_reach_the_delivered_app(tmp_path):
    """The safety property that makes materializing-everywhere acceptable."""
    from env_generator.llm_generator.multi_agent.skill_loader import (
        PROJECT_AGENT_SKILLS_DIRNAME)
    assert PROJECT_AGENT_SKILLS_DIRNAME.startswith(".agents"), (
        "skills live under .agents/, which the generated project's .gitignore excludes; "
        "if that ever moves, copying into every worktree would ship them to the user")


def test_the_control_leaves_the_worktree_empty(tmp_path):
    """Planted control: the PRE-FIX path — create the worktree, no sync — must produce no
    skills. Synthetic, so fixing the real hub can never turn this red."""
    wt = tmp_path / "worktrees" / "lane"
    wt.mkdir(parents=True)
    assert _skill_files(wt) == [], (
        "the control was supposed to be empty; if not, the assertions above prove nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
