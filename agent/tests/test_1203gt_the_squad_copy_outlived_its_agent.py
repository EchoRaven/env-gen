"""#1203gt: a terminated test-user kept its 394MB checkout until the run ended.

#1202as reclaims per-LANE worktrees when the run is over. A squad spawns twelve agents per
milestone and terminates each as it finishes or times out, so every milestone's copies stayed
alive at once: r171 reached 29 worktrees / 12G and watched /data fall from 13G to 7.5G in 45
minutes, after which Postgres initdb failed on `pg_wal: No space left on device` and the
framework correctly stopped for OPERATOR ACTION.

The reclaim runs right after `terminate`, including for the TIMED-OUT agents -- r171's four
squads timed out 26 of 48, and those are the ones that leave a copy. It never uses --force, so
a worktree with uncommitted work is KEPT rather than destroyed.
"""
import ast
import subprocess
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.worktree_reclaim import (
    reclaim_agent_worktree_1203gt as _reclaim,
)

SQUAD = (Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent/runtime/test_user_squad.py")
RECLAIM = (Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/runtime/worktree_reclaim.py")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, check=True)


def _repo_with_worktree(tmp_path, agent_id="api_test_user_1_x"):
    root = tmp_path / "run"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    wt = root / "worktrees" / agent_id
    _git(root, "worktree", "add", "-q", "-b", f"agent/{agent_id}", str(wt))
    assert wt.is_dir()
    return root, wt


def test_a_clean_worktree_is_handed_back(tmp_path):
    root, wt = _repo_with_worktree(tmp_path)
    out = _reclaim(root, "api_test_user_1_x")
    assert out["removed"] == ["api_test_user_1_x"], out
    assert out["kept"] == [], out
    assert not wt.exists()


def test_a_worktree_with_uncommitted_work_is_KEPT(tmp_path):
    """--force is deliberately not used: a refusal is the correct outcome, not an obstacle."""
    root, wt = _repo_with_worktree(tmp_path)
    (wt / "app" / "main.py").write_text("x = 2  # a lane's unsaved work\n", encoding="utf-8")
    out = _reclaim(root, "api_test_user_1_x")
    assert out["removed"] == [], out
    assert out["kept"] == ["api_test_user_1_x"], out
    assert wt.is_dir(), "the checkout with uncommitted work must survive"


def test_it_touches_only_the_named_agent(tmp_path):
    root, wt = _repo_with_worktree(tmp_path, "api_test_user_1_x")
    _git(root, "worktree", "add", "-q", "-b", "agent/backend", str(root / "worktrees" / "backend"))
    out = _reclaim(root, "api_test_user_1_x")
    assert out["removed"] == ["api_test_user_1_x"], out
    assert (root / "worktrees" / "backend").is_dir(), "a lane's worktree must not be reclaimed"


def test_a_missing_or_unusable_id_is_a_skip_not_a_crash(tmp_path):
    root, _ = _repo_with_worktree(tmp_path)
    for bad in ("", "   ", "..", "a/b", "never_spawned"):
        out = _reclaim(root, bad)
        assert out["removed"] == [] and out["kept"] == [], (bad, out)
        assert out["skipped"], (bad, out)


def test_the_keep_switch_is_honoured(tmp_path, monkeypatch):
    root, wt = _repo_with_worktree(tmp_path)
    monkeypatch.setenv("ENVGEN_KEEP_WORKTREES", "1")
    out = _reclaim(root, "api_test_user_1_x")
    assert out["skipped"] == "ENVGEN_KEEP_WORKTREES=1", out
    assert wt.is_dir()


def test_it_never_raises_on_a_nonsense_root():
    """Cleanup must never become the thing that fails a squad entry."""
    assert _reclaim("/nonexistent/%s" % "x" * 8, "a")["skipped"]
    assert _reclaim(None, "a") is not None


def test_force_is_never_passed():
    """Source-level: the one guarantee this module's docstring makes about data."""
    body = RECLAIM.read_text(encoding="utf-8")
    tree = ast.parse(body)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "reclaim_agent_worktree_1203gt")
    args = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert not any("--force" in a for a in args), args


def test_the_squad_reclaims_AFTER_it_terminates(tmp_path):
    """Position, not presence: reclaiming before termination would race the live agent."""
    tree = ast.parse(SQUAD.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_run_one")
    term = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and "terminate" in ast.unparse(n.func)]
    recl = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and "reclaim_agent_worktree_1203gt" in ast.unparse(n.func)]
    assert term, "the squad no longer terminates its agents"
    assert recl, "the squad does not reclaim the terminated agent's worktree"
    assert min(recl) > max(term), (
        "the reclaim must sit AFTER terminate (%s vs %s)" % (recl, term))


def test_the_reclaim_runs_for_timed_out_agents_too():
    """It sits on the common path, not inside the `completed` branch.

    r171's four squads timed out 26 of 48 agents; a reclaim that only ran for the ones that
    finished would miss the majority of the copies.
    """
    tree = ast.parse(SQUAD.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_run_one")
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.Try, ast.ExceptHandler)) and not isinstance(node, ast.Try):
            inner = [n for n in ast.walk(node)
                     if isinstance(n, ast.Call)
                     and "reclaim_agent_worktree_1203gt" in ast.unparse(n.func)]
            if inner:
                raise AssertionError(
                    "the reclaim sits inside a conditional (%s) — a timed-out agent would keep "
                    "its copy" % ast.unparse(node.test if isinstance(node, ast.If) else node))
