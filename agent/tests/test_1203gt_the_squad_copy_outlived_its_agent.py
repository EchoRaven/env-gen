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


def test_force_is_only_reachable_behind_the_untracked_only_gate():
    """The guarantee, in its #1203gz shape: `--force` exists, and ONLY under that predicate.

    This test used to assert `--force` is never passed at all. #1203gz narrowed the guarantee
    rather than dropping it -- a copy holding only untracked build output is discarded, a copy
    holding any tracked change is still KEPT -- so the assertion has to pin the narrower
    property: every `--force` call site sits inside an `if` that consults
    `_only_untracked_1203gz`. A mutation that forces unconditionally turns this red, which the
    old "never force" version could not distinguish from the fix.
    """
    tree = ast.parse(RECLAIM.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "reclaim_agent_worktree_1203gt")

    def _forces(node):
        return [c for c in ast.walk(node)
                if isinstance(c, ast.Call) and "--force" in ast.unparse(c)]

    all_forces = _forces(fn)
    assert all_forces, "the #1203gz path is gone; if that is intended, restore the old test"
    guarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "_only_untracked_1203gz" in ast.unparse(node.test):
            guarded.extend(_forces(node))
    unguarded = len(all_forces) - len(guarded)
    assert unguarded == 0, (
        "%d `--force` call(s) are not behind the untracked-only predicate" % unguarded)


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


# --- #1203gz: git also refuses on untracked files, and that is what actually happened ---
#
# #1203gt predicted `kept` would stay empty (46 observed reclaims kept nothing). r172 refuted
# it on the first run, for a reason that is #1203gs working: the MCP test-user now really
# starts the server it is sent to test, `start.sh` runs `uv`, and the copy is left holding
# `?? mcp_server/app/uv.lock` -- 393MB held until the end-of-run reclaim, for a build artifact.

from env_generator.llm_generator.multi_agent.runtime.worktree_reclaim import (  # noqa: E402
    _only_untracked_1203gz as _untracked_only,
)


def test_a_copy_holding_only_untracked_build_output_is_reclaimed(tmp_path):
    """r172's exact case, reproduced: `?? mcp_server/app/uv.lock` and nothing else."""
    root, wt = _repo_with_worktree(tmp_path, "mcp_test_user_2_mcp_surface")
    (wt / "mcp_server" / "app").mkdir(parents=True)
    (wt / "mcp_server" / "app" / "uv.lock").write_text("# generated\n", encoding="utf-8")
    assert _untracked_only(wt, root), "an untracked-only copy must read as holding no work"
    out = _reclaim(root, "mcp_test_user_2_mcp_surface")
    assert out["removed"] == ["mcp_test_user_2_mcp_surface"], out
    assert out.get("untracked_only_1203gz") is True, out
    assert not wt.exists()


def test_a_tracked_modification_is_still_KEPT(tmp_path):
    """The no-force guarantee is unchanged for anything that could be real work."""
    root, wt = _repo_with_worktree(tmp_path, "browser_test_user_1_x")
    (wt / "app" / "main.py").write_text("x = 2  # a real edit\n", encoding="utf-8")
    assert not _untracked_only(wt, root)
    out = _reclaim(root, "browser_test_user_1_x")
    assert out["kept"] == ["browser_test_user_1_x"], out
    assert wt.is_dir()


def test_a_MIXED_state_is_KEPT(tmp_path):
    """One tracked edit beside any amount of build output means the copy holds work."""
    root, wt = _repo_with_worktree(tmp_path, "api_test_user_3_x")
    (wt / "app" / "main.py").write_text("x = 3\n", encoding="utf-8")
    (wt / "uv.lock").write_text("# generated\n", encoding="utf-8")
    assert not _untracked_only(wt, root)
    out = _reclaim(root, "api_test_user_3_x")
    assert out["kept"] == ["api_test_user_3_x"], out
    assert wt.is_dir()


def test_a_clean_copy_does_not_take_the_force_path(tmp_path):
    """A clean copy is removed by the plain remove; `_only_untracked` must say False for it,
    so an empty status can never be read as licence to force."""
    root, wt = _repo_with_worktree(tmp_path, "clean_agent")
    assert not _untracked_only(wt, root), "an empty status must not unlock --force"
    out = _reclaim(root, "clean_agent")
    assert out["removed"] == ["clean_agent"] and not out.get("untracked_only_1203gz")


def test_an_unreadable_status_is_KEPT(tmp_path):
    """Not a git worktree at all: the predicate must refuse, not guess."""
    d = tmp_path / "not_a_repo"
    d.mkdir()
    assert not _untracked_only(d, tmp_path)
