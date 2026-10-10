r"""#1203hf: the briefing that decides what every test-user does was written nowhere.

`build_briefing(goal, ui_base, api_base)` decides which MCP server a test-user reaches,
which tool it gets a port with, what counts as a defect and what does not. It rode into
`spawn_service.spawn(... metadata={"description": briefing})` and was then unrecoverable.

MEASURED three ways on 2026-10-10:
  * the run log: `Get a port FIRST`, `Completeness, then parity`, `ls mcp_server/`,
    `NEVER hand-edit`, `auth_token` — 0 occurrences each
  * `logs/test_user_squad_1202wn.jsonl`: keys are agent_count / agents / at / completed /
    dropped_goals_1203go / failed / spawned / timed_out. No briefing, no task text
  * every artifact in the corpus: 0 files under `generated/*/logs/` or
    `generated/*/shared/hubs/` contain any briefing phrase

So no question of the form "did this copy reach the agent / did changing it help" could
be answered after the fact — and #1203h6, `_hint_1202z6` (landed three times while the P0
kept being filed) and #1203gq (copy naming a tool absent from that turn's list) are all
exactly that question.

★ IT COST A WRONG CONCLUSION THE SAME DAY. On r176 I searched the log for #1203h6's text,
found `auth_token` 0 times while `find_free_port` appeared 5 times, and wrote down "the
copy did not reach the briefing". Wrong: those 5 were all tool PLUMBING (`tools_delta=+`,
the tool list, the invocation, token accounting), and the positive control — phrases that
have been in the briefing for weeks — was 0 as well. "Absent from the log" is evidence
only when something present would show up.

SCOPE: a SEPARATE file from `test_user_squad_1202wn.jsonl`, whose docstring calls itself
"the single writer of the file" and whose entries are deliberately small; folding ~3 KB of
prose per agent into it would destroy what it is for. Size is not a concern either way:
measured 4474 characters for a 3-goal plan (the mcp_parity briefing alone is 2937), so the
12-goal cap is ~12-18 KB against run directories of 380 MB to 2 GB.
"""
import inspect
import json
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    build_briefing, plan_test_user_goals, record_briefing_1203hf)


def _orch(tmp_path):
    return types.SimpleNamespace(output_dir=str(tmp_path))


def _lines(tmp_path):
    p = tmp_path / "logs" / "test_user_briefings_1203hf.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_the_briefing_reaches_an_artifact(tmp_path):
    """★ The whole ticket: the text an agent was given survives the run."""
    rec = {"agent_id": "mcp_test_user_2_mcp_surface", "kind": "mcp_parity",
           "name": "mcp_surface", "modality": "api", "tenant": "tu_2_api"}
    assert record_briefing_1203hf(_orch(tmp_path), rec, "GO AND DO THE THING") is True
    rows = _lines(tmp_path)
    assert len(rows) == 1, rows
    assert rows[0]["briefing"] == "GO AND DO THE THING"
    assert rows[0]["agent_id"] == "mcp_test_user_2_mcp_surface"
    assert rows[0]["goal_kind"] == "mcp_parity"


def test_it_appends_one_line_per_agent(tmp_path):
    """One line per test-user, so the count can be compared with `spawned`."""
    for i in range(3):
        record_briefing_1203hf(_orch(tmp_path), {"agent_id": f"a{i}"}, f"brief {i}")
    rows = _lines(tmp_path)
    assert [r["briefing"] for r in rows] == ["brief 0", "brief 1", "brief 2"]


def test_the_real_mcp_briefing_round_trips(tmp_path):
    """★ THE CASE THAT MOTIVATED IT: #1203h6's copy must be recoverable from the artifact,
    which is the online criterion h6 did not have."""
    goals = plan_test_user_goals(
        business_eps=[{"method": "GET", "path": "/api/feed", "response_key": "items"}],
        tables={"posts": {"schema": {"columns": ["id", "caption"]}}},
        ui_pages=[], feature_inventory={}, mcp_present=True, max_goals=24)
    mcp = next(g for g in goals if g.get("kind") == "mcp_parity")
    briefing = build_briefing(mcp, ui_base="http://localhost:3000",
                              api_base="http://localhost:8000")
    record_briefing_1203hf(_orch(tmp_path), {"agent_id": "mcp_1", "kind": "mcp_parity"},
                           briefing)
    stored = _lines(tmp_path)[0]["briefing"]
    assert "find_free_port" in stored, stored[:200]
    assert "auth_token" in stored, stored[:200]
    assert "hand-edit" in stored, stored[:200]


def test_a_pathological_briefing_is_bounded_and_declares_the_cut(tmp_path):
    """A cap only so one goal cannot write an unbounded line — and it says what it dropped
    (#1034) rather than ending in a bare ellipsis (#1203he)."""
    record_briefing_1203hf(_orch(tmp_path), {"agent_id": "big"}, "z" * 30000)
    stored = _lines(tmp_path)[0]["briefing"]
    assert len(stored) < 21000, len(stored)
    assert "chars]" in stored, stored[-60:]


def test_a_missing_output_dir_is_reported_not_raised(tmp_path):
    """The early exits: no orch, no `output_dir`. These return False WITHOUT reaching the
    except block, which is why they cannot stand in for the test below."""
    assert record_briefing_1203hf(None, {"agent_id": "x"}, "b") is False
    assert record_briefing_1203hf(types.SimpleNamespace(), {"agent_id": "x"}, "b") is False


def test_odd_arguments_are_tolerated(tmp_path):
    assert record_briefing_1203hf(_orch(tmp_path), None, "b") is True
    assert record_briefing_1203hf(_orch(tmp_path), {"agent_id": "x"}, None) is True


def test_a_write_that_cannot_happen_is_swallowed(tmp_path):
    """★ THE TEST THE FIRST VERSION DID NOT HAVE. `test_it_never_raises_into_the_squad`
    passed four shapes that all returned False or True from the EARLY paths, so mutating
    `except Exception: return False` into `raise` stayed green — the guard it named was
    never reached. A squad agent must not be lost because a log line could not be written,
    so make the write itself impossible: `output_dir` under a plain FILE, which makes
    `mkdir(parents=True)` raise."""
    blocker = tmp_path / "a_file"
    blocker.write_text("not a directory\n")
    orch = types.SimpleNamespace(output_dir=str(blocker / "run"))
    assert record_briefing_1203hf(orch, {"agent_id": "x"}, "b") is False


def _code_only(fn):
    """The function's statements with the docstring removed.

    ★ The first version of the test below used raw `inspect.getsource` and FAILED on its
    own docstring, which names the other ledger while explaining why it must not be used.
    That is #1203e6's lesson verbatim: a source assertion that cannot tell code from the
    comment explaining it will keep catching the explanation.
    """
    import ast
    tree = ast.parse(inspect.getsource(fn).lstrip())
    node = tree.body[0]
    body = node.body[1:] if (node.body and isinstance(node.body[0], ast.Expr)
                             and isinstance(getattr(node.body[0], "value", None), ast.Constant)
                             and isinstance(node.body[0].value.value, str)) else node.body
    return "\n".join(ast.unparse(st) for st in body)


def test_it_is_not_folded_into_the_summary_ledger():
    """★ SCOPE. `test_user_squad_1202wn.jsonl` calls itself "the single writer of the file"
    and keeps its entries small on purpose; 3 KB of prose per agent would ruin it."""
    code = _code_only(record_briefing_1203hf)
    assert "test_user_briefings_1203hf.jsonl" in code, code
    assert "test_user_squad_1202wn" not in code, code


def test_the_write_happens_before_the_spawn():
    """★ "What was this agent told" is most needed exactly when the spawn failed, so the
    line must already be on disk by then."""
    import multi_agent.runtime.test_user_squad as TUS
    src = inspect.getsource(TUS.run_test_user_squad)
    i_rec = src.find("record_briefing_1203hf(")
    i_spawn = src.find("spawn_service.spawn(")
    assert i_rec >= 0, "the call site is gone"
    assert i_spawn >= 0, "the spawn moved"
    assert i_rec < i_spawn, (i_rec, i_spawn)
