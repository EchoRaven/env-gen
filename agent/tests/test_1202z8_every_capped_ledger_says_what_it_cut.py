r"""#1202z8: every capped ledger in run_budget.json says what the cap left out.

#1202z7 fixed one of four. The other three cap the same way and are equally silent:
`stage_tools_1202cy` (16 stages x 10 tools), `tool_result_bytes` (12 tools),
`lane_clobbers_1202cw` (12 paths per kind). Each cap is defensible on its own — "the
question is answered by the head" — and each lets a reader sum the map and believe they
have the run.

MEASURED, and twice it was me who was misled:
  * `llm_by_phase_1202cr` held 5691 of 6807 calls and $366.22 of $402.92 in r140 — 9% of
    the run in no bucket (that is #1202z7).
  * `tool_result_bytes` keeps 12 of the 75 tools that returned a result in r140, covering
    4643 of 7254 invocations. I read "tool results are 19% of uncached" off that head
    mid-run; the final head alone is 24.73 MB against 24.44M uncached tokens, so the true
    share is at least 25% and the ledger cannot say how much more.
  * `stage_tools_1202cy`'s own comment says the cap leaves "enough to see an EMPTY stage,
    which is the question" — but a stage past the 16th is indistinguishable from one that
    never ran, which is that question unanswered.

★ THE CAPS STAY. Nothing here restores the detail a cap exists to drop; each ledger gains
one `_capped_1202z8` entry naming how much fell off, so the head can be told from the whole.
"""
import json
import logging
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.run_budget as RB  # noqa: E402


def _write(monkeypatch, tmp_path, *, stage_tools=None, tool_bytes=None):
    import utils.llm as LL
    monkeypatch.setattr(LL, "llm_usage", lambda: {"calls": 0, "usd": 0.0}, raising=False)
    monkeypatch.setattr(LL, "llm_usage_by_label_1202cr", lambda: {}, raising=False)
    monkeypatch.setattr(LL, "tool_result_bytes", lambda: tool_bytes or {}, raising=False)
    monkeypatch.setattr(RB, "tool_result_bytes", lambda: tool_bytes or {}, raising=False)
    monkeypatch.setattr(LL, "stage_tools_1202cy", lambda: stage_tools or {}, raising=False)
    b = RB.RunBudget(tmp_path, logging.getLogger("t1202z8"))
    b.write({"max_wall_sec": 1.0, "max_ticks": 1}, 1.0, 1.0, 1, "running")
    return json.loads((tmp_path / "run_budget.json").read_text(encoding="utf-8"))


def _stages(n):
    return {"agent%02d:stage" % i: {"read": 5, "write": 3} for i in range(n)}


def _tools(n):
    return {"tool%02d" % i: {"calls": 10, "bytes": 1000, "max": 100} for i in range(n)}


def test_a_stage_past_the_cap_is_not_an_absent_stage(monkeypatch, tmp_path):
    """★ The ledger's own stated purpose: see an EMPTY stage. Twenty stages, sixteen kept —
    the four that fell off must not read as four stages that never ran."""
    d = _write(monkeypatch, tmp_path, stage_tools=_stages(20))
    m = d["stage_tools_1202cy"]
    assert "_capped_1202z8" in m, sorted(m)
    assert m["_capped_1202z8"]["dropped_stages"] == 4, m["_capped_1202z8"]


def test_sixteen_stages_are_reported_exactly_as_before(monkeypatch, tmp_path):
    d = _write(monkeypatch, tmp_path, stage_tools=_stages(16))
    m = d["stage_tools_1202cy"]
    assert "_capped_1202z8" not in m, sorted(m)
    assert len(m) == 16


def test_the_tool_bytes_ledger_reports_what_it_dropped(monkeypatch, tmp_path):
    """75 tools returned a result in r140 and this keeps 12. A reader summing the head was
    reading 64% of the invocations without being told."""
    d = _write(monkeypatch, tmp_path, tool_bytes=_tools(20))
    m = d["tool_result_bytes"]
    assert "_capped_1202z8" in m, sorted(m)
    cut = m["_capped_1202z8"]
    assert cut["dropped"] == 8, cut
    assert cut["calls"] == 80 and cut["bytes"] == 8000, cut


def test_the_tool_bytes_arithmetic_closes(monkeypatch, tmp_path):
    tools = _tools(20)
    d = _write(monkeypatch, tmp_path, tool_bytes=tools)
    m = d["tool_result_bytes"]
    for key in ("calls", "bytes"):
        want = sum(v[key] for v in tools.values())
        got = sum(float(v.get(key) or 0) for v in m.values())
        assert abs(got - want) < 1e-6, "%s: %r vs %r" % (key, got, want)


def test_twelve_tools_are_reported_exactly_as_before(monkeypatch, tmp_path):
    d = _write(monkeypatch, tmp_path, tool_bytes=_tools(12))
    assert "_capped_1202z8" not in d["tool_result_bytes"]


def test_the_head_is_still_the_head(monkeypatch, tmp_path):
    """The caps are unchanged: the same entries are kept, in the same order."""
    d = _write(monkeypatch, tmp_path, tool_bytes=_tools(20))
    kept = [k for k in d["tool_result_bytes"] if k != "_capped_1202z8"]
    assert kept[:3] == ["tool00", "tool01", "tool02"], kept[:3]
    assert len(kept) == 12


def test_the_helper_is_shared_not_copied():
    """★ #1032: four ledgers cap the same way; four hand-rolled slices would drift into
    four different answers about what 'dropped' means."""
    import ast
    import inspect
    src = inspect.getsource(RB.RunBudget)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "_cap_1202z8"]
    assert len(calls) >= 2, "the shared cap helper has %d call sites" % len(calls)


def test_a_cap_never_raises_on_an_odd_bucket(monkeypatch, tmp_path):
    """Buckets are built by several writers; one that is not a dict must not cost the
    whole ledger — accounting never fails a run record (#792's rule, one file over)."""
    tools = _tools(14)
    tools["tool13"] = None
    d = _write(monkeypatch, tmp_path, tool_bytes=tools)
    assert "tool_result_bytes" in d
