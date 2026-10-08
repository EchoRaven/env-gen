"""#1203ge -- seven of the eight agents' per-tool wall clock was overwritten every run.

`_flush_tool_ms_1202wl` wrote `logs/tool_timings_1202wl.json` — ONE path, for every agent in the
run. The agents run concurrently and flush every 50 tool calls, so the file was both a race and
an overwrite, and what survived was whichever agent happened to flush last. The record even
carried `"agent": <id>`: it knew whose numbers it held and discarded the other seven anyway.

Measured on the two most recent runs:
    r164  logs/tool_timings_1202wl.json  ->  agent = "backend"   (has lint, grep)
    r165  logs/tool_timings_1202wl.json  ->  agent = "verifier"  (has neither)
So the only per-tool timing a run leaves behind is a different agent each time, and no
cross-run comparison is possible. That is not a reporting nicety: #1203g5 (lint content-hash
cache), #1203g6 (grep skipping binary files) and #1203g7 (container label cache) are all
wall-clock fixes, and all three landed with r165 verification criteria THIS ARTIFACT CANNOT
ANSWER. A performance patch needs its measurement to survive the run that would prove it.

Fix: one file per agent under `logs/tool_timings_1202wl/<agent>.json`, plus
`read_tool_timings_1203ge(run_dir)` so a reader does not have to rediscover the layout — having
to go looking for it is what surfaced the overwrite.

Not a read-modify-write on one shared file: the agents are concurrent, so that trades the
overwrite for a lost update.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.runtime.tooling import (  # noqa: E402
    _agent_slug_1203ge,
    read_tool_timings_1203ge,
)
from multi_agent.agents.runtime import tooling as T  # noqa: E402


class _Host(T.AgentTooling):
    """The flush path's world: a hubs base_dir and an agent id. Mirrors #1202wl's fixture —
    subclassing the real class, so this exercises the shipped recorder, not a copy."""

    def __init__(self, base, agent):
        class _Hubs:
            base_dir = base
        self._hubs = _Hubs()
        self.agent_id = agent


def _flush(base, agent, tool, ms, n=None):
    """Drive the REAL recorder until it flushes at least once."""
    h = _Host(base, agent)
    for _ in range(n if n is not None else h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl(tool, ms)
    return h


def _dir(base):
    return Path(base) / "logs" / "tool_timings_1202wl"


# --- the defect itself -------------------------------------------------------------------------

def test_two_agents_do_not_overwrite_each_other(tmp_path):
    """THE HARM, reproduced. Before the fix the second flush replaced the first."""
    _flush(tmp_path, "backend", "lint", 120)
    _flush(tmp_path, "verifier", "run_validation", 400000)
    both = read_tool_timings_1203ge(tmp_path)
    assert set(both) == {"backend", "verifier"}, both
    assert "lint" in both["backend"], both["backend"]
    assert "run_validation" in both["verifier"], both["verifier"]


def test_every_agent_in_a_run_keeps_its_own_numbers(tmp_path):
    """Eight agents is the real shape; the artifact must hold eight rows, not one."""
    agents = ["orchestrator", "backend", "frontend", "verifier",
              "debugger", "analyst", "designer", "api_test_user"]
    for i, a in enumerate(agents):
        _flush(tmp_path, a, "read", 10 + i)
    got = read_tool_timings_1203ge(tmp_path)
    assert len(got) == len(agents), sorted(got)
    # each agent's own average survived, so the rows are not a merged blur
    for i, a in enumerate(agents):
        assert got[a]["read"]["max_ms"] == 10 + i, (a, got[a])


def test_the_run_directory_still_wins_over_the_workspace(tmp_path):
    """#1202wl's rule, carried over: a lane worktree is not the run directory."""
    run, worktree = tmp_path / "run", tmp_path / "worktree"
    h = _Host(run, "frontend")
    h.workspace = worktree
    for _ in range(h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl("grep", 3)
    assert read_tool_timings_1203ge(run), "nothing landed in the run directory"
    assert not (worktree / "logs").exists()


# --- the slug cannot collapse two agents into one file -----------------------------------------

def test_agent_ids_that_differ_get_different_files():
    """A slug that collapsed two ids would put the overwrite straight back."""
    ids = ["backend", "Backend Engineer Agent", "frontend", "Frontend Engineer Agent",
           "api_test_user", "API Test-User (api_test_user)", "orchestrator", "verifier"]
    slugs = [_agent_slug_1203ge(i) for i in ids]
    assert len(set(slugs)) == len(ids), dict(zip(ids, slugs))
    for s in slugs:
        assert s and "/" not in s and s == s.strip(". -"), s


def test_an_empty_or_hostile_agent_id_still_names_a_file():
    for bad in ("", "   ", None, "///", "..", "-"):
        s = _agent_slug_1203ge(bad)
        assert s and "/" not in s and s not in (".", ".."), (bad, s)


# --- the reader ---------------------------------------------------------------------------------

def test_the_reader_tolerates_a_pre_fix_run_directory(tmp_path):
    """203 corpus run directories carry the old single file; reading one must still work."""
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    (logs / "tool_timings_1202wl.json").write_text(json.dumps({
        "at": 1.0, "agent": "backend", "calls": 50,
        "tools": {"lint": {"count": 3, "total_ms": 30.0, "max_ms": 20.0}}}), encoding="utf-8")
    got = read_tool_timings_1203ge(tmp_path)
    assert got == {"backend": {"lint": {"count": 3, "total_ms": 30.0, "max_ms": 20.0}}}, got


def test_the_reader_is_empty_not_angry_on_a_run_with_no_timings(tmp_path):
    assert read_tool_timings_1203ge(tmp_path) == {}
    assert read_tool_timings_1203ge(tmp_path / "nope") == {}


def test_the_reader_skips_a_corrupt_file_without_losing_the_others(tmp_path):
    d = _dir(tmp_path)
    d.mkdir(parents=True)
    (d / "backend.json").write_text(json.dumps({
        "agent": "backend", "tools": {"lint": {"count": 1, "total_ms": 1.0, "max_ms": 1.0}}}),
        encoding="utf-8")
    (d / "truncated.json").write_text('{"agent": "verifier", "tools": {', encoding="utf-8")
    got = read_tool_timings_1203ge(tmp_path)
    assert list(got) == ["backend"], got


# --- the shape that caused it must not come back ------------------------------------------------

def test_the_flush_path_is_not_a_single_shared_filename():
    """Structural: the written path must depend on the agent, or eight agents share a file again."""
    src = Path(T.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_flush_tool_ms_1202wl")
    assigns = [n for n in ast.walk(fn)
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "out" for t in n.targets)]
    assert len(assigns) == 1, "expected exactly one `out = ...` in the flush"
    expr = ast.unparse(assigns[0].value)
    assert "_agent_slug_1203ge" in expr, (
        "the output path no longer depends on the agent — eight agents share one file again: %s"
        % expr)
    assert '"tool_timings_1202wl.json"' not in expr and "'tool_timings_1202wl.json'" not in expr, expr
