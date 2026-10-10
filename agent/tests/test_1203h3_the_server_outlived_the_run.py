"""#1203h3: the MCP server a test-user started kept running after the run ended.

#1203gs let the MCP test-user actually start the server it is sent to test. Nothing stopped it.
r173 ended with TWO still running — etime 5h38m and 2h13m, cwd `mcp_server/app` under its own
output directory — holding ports 8890 and 8891. r174's agent then did exactly what the
briefing said and got `Port 8890 is already in use`, twice, before crashing: a previous run's
leak broke the next run's ability to test MCP at all.

Third instance today of one shape: a fix lets work finish and the resource it takes has no
counterpart (#1202as for worktrees, #1203gw for images, this for processes).

Attribution is by `/proc/<pid>/cwd` resolving UNDER the run's output directory — the same
choice #1203gw made for images: scope by something the run demonstrably owns, not by a name
pattern or a port range. `ProcessManager` records no owner (`start()` takes no agent id,
`ProcessInfo` has no such field), so scoping there would have meant changing a shared singleton.
"""
import ast
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.worktree_reclaim import (
    _own_pid_chain_1203h3 as _chain,
    reclaim_run_processes_1203h3 as _reclaim,
)

MAIN = (Path(__file__).resolve().parents[1] / "env_generator/llm_generator/main.py")


def _sleeper(cwd: Path):
    """A process whose cwd is `cwd`, like the MCP server started under mcp_server/<env>."""
    cwd.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(cwd))
    for _ in range(50):                      # wait until /proc shows its cwd
        try:
            if Path("/proc/%d/cwd" % p.pid).resolve() == cwd.resolve():
                break
        except Exception:
            pass
        time.sleep(0.05)
    return p


def test_a_process_under_the_run_is_stopped(tmp_path):
    run = tmp_path / "generated" / "env-r1"
    p = _sleeper(run / "mcp_server" / "app")
    try:
        out = _reclaim(run)
        assert [r["pid"] for r in out["stopped"]] == [p.pid], out
        p.wait(timeout=10)
        assert p.poll() is not None
    finally:
        if p.poll() is None:
            p.kill()


def test_a_process_OUTSIDE_the_run_is_untouched(tmp_path):
    """The safety property: another run's server, or anyone else's, is not ours to stop."""
    run = tmp_path / "generated" / "env-r1"
    run.mkdir(parents=True)
    other = _sleeper(tmp_path / "generated" / "env-r2" / "mcp_server" / "app")
    try:
        out = _reclaim(run)
        assert out["stopped"] == [], out
        assert other.poll() is None, "a process outside the run was stopped"
    finally:
        other.kill()


def test_this_process_and_its_ancestors_are_never_candidates():
    """A reclaim that can kill the run itself is worse than the leak."""
    chain = _chain()
    assert os.getpid() in chain
    assert len(chain) >= 2, chain          # at least self + parent


def test_the_run_dir_being_the_cwd_of_THIS_process_does_not_kill_it(tmp_path, monkeypatch):
    """The sharpest version of the same guard: reclaim a directory we ourselves sit in."""
    monkeypatch.chdir(tmp_path)
    out = _reclaim(tmp_path)
    assert os.getpid() not in [r["pid"] for r in out["stopped"]], out


def test_a_missing_or_empty_target_is_a_skip(tmp_path):
    assert _reclaim("/nonexistent/%s" % ("x" * 9))["skipped"]
    assert _reclaim(tmp_path)["skipped"]


def test_the_keep_switch_is_honoured(tmp_path, monkeypatch):
    run = tmp_path / "generated" / "env-r1"
    p = _sleeper(run / "mcp_server" / "app")
    try:
        monkeypatch.setenv("ENVGEN_KEEP_RUN_PROCESSES", "1")
        out = _reclaim(run)
        assert out["skipped"] == "ENVGEN_KEEP_RUN_PROCESSES=1", out
        assert p.poll() is None
    finally:
        p.kill()


def test_it_never_raises_on_nonsense():
    assert _reclaim(None) is not None
    assert _reclaim(12345) is not None


def test_the_end_of_run_hook_calls_it_beside_the_worktree_reclaim():
    """AST: it has to run where the run gives back what it took, or the leak persists."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert any("reclaim_run_processes_1203h3" in c for c in calls), (
        "main.py never stops the processes the run left running")
    assert any("reclaim_run_worktrees_1202as" in c for c in calls), "the worktree reclaim went"
