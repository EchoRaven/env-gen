r"""#1202z5: `count: 0` from a seed audit that inspected NOTHING must not read as "clean".

`SeedReport.measured` exists for exactly this — its docstring is "False when the audit
inspected nothing — `is_clean` then carries no information" — and #1023d put it into
`to_dict()` with the note that "a consumer reading is_clean must be able to see whether
anything was read". `seed_audit_check` returns `to_dict()` and carries it.

`list_seed_issues` rebuilt the payload by hand as `{"issues": [...], "count": N}` and dropped
it. That is the tool whose own description offers it "for the orchestrator's
deliver-readiness checklist", so the one consumer that most needs the distinction was the
one that could not see it. Same shape as #1202vp: the sink rebuilds what you hand it.

THE BLIND STATE IS NOT HYPOTHETICAL. The audit inspects zero tables at some point in 42 of
the 158 run logs — `SEED AUDIT EXAMINED 0 OF n TABLES`, up to 20 tables skipped — including
r140 at 03:21 with 11 registered, which is 23 minutes after its M1 was released.

★ FIXED RATHER THAN DELETED, and the tool IS dead: 0 calls across the 50 runs carrying
stage-tool counts, against 2999 `seed_audit_check` calls, and no reference anywhere in the
tree but its own class and one test. Deleting is what #1199 did to the table-registration
tool — but that one was a tool NOBODY SHOULD CALL, its audit having been removed. This one
is useful if called; it just is not. A tool that nobody calls costs a schema. A tool that
would LIE the day somebody calls it costs a wrong delivery decision.
"""
import asyncio
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.seed_audit import SeedReport  # noqa: E402
import tools.seed_tools as ST  # noqa: E402


def _run(report, monkeypatch):
    monkeypatch.setattr(ST, "audit_seed_data", lambda *a, **k: report)
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: None)
    tool = ST.ListSeedIssuesTool(hub_registry=types.SimpleNamespace())
    res = asyncio.run(tool.execute())
    return res.data if hasattr(res, "data") else res["data"]


def test_an_audit_that_examined_nothing_says_so(monkeypatch):
    """★ The case the whole ticket is about: no flagged tables AND nothing inspected."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=11), monkeypatch)
    assert d["count"] == 0
    assert d["measured"] is False, d
    assert d["examined"] == 0 and d["candidates"] == 11, d


def test_a_real_clean_audit_is_distinguishable(monkeypatch):
    """The other half: same `count: 0`, and now a reader can tell them apart."""
    d = _run(SeedReport(flagged_tables=[], examined=11, candidates=11), monkeypatch)
    assert d["count"] == 0
    assert d["measured"] is True, d
    assert d["examined"] == 11


def test_the_two_are_not_the_same_payload(monkeypatch):
    """Stated as the property rather than as two separate assertions: a blind audit and a
    clean one must not serialise identically, which is precisely what they did before."""
    blind = _run(SeedReport(flagged_tables=[], examined=0, candidates=4), monkeypatch)
    clean = _run(SeedReport(flagged_tables=[], examined=4, candidates=4), monkeypatch)
    assert blind != clean


def test_the_issues_payload_is_unchanged(monkeypatch):
    """Additive only — every existing key keeps its meaning and its spelling."""
    rep = SeedReport(
        flagged_tables=[{"table": "videos", "reason": "missing_seed", "detail": {"x": 1}}],
        examined=3, candidates=3)
    d = _run(rep, monkeypatch)
    assert d["count"] == 1
    assert d["issues"] == [{"table": "videos", "reason": "missing_seed", "detail": {"x": 1}}]


def test_no_candidates_counts_as_measured(monkeypatch):
    """`measured` is `examined > 0 or candidates == 0`: an app with nothing auditable was
    not blind, it simply had nothing to look at. Pinned so a future edit does not turn an
    empty project into a permanent 'unknown'."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=0), monkeypatch)
    assert d["measured"] is True, d


def test_the_sibling_tool_still_carries_it(monkeypatch):
    """`seed_audit_check` was already right; this pins that the pair now AGREE, because the
    defect was one of two siblings disagreeing about the same fact (#1032)."""
    rep = SeedReport(flagged_tables=[], examined=0, candidates=7)
    monkeypatch.setattr(ST, "audit_seed_data", lambda *a, **k: rep)
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: None)
    a = asyncio.run(ST.SeedAuditCheckTool(hub_registry=types.SimpleNamespace()).execute())
    b = asyncio.run(ST.ListSeedIssuesTool(hub_registry=types.SimpleNamespace()).execute())
    da = a.data if hasattr(a, "data") else a["data"]
    db = b.data if hasattr(b, "data") else b["data"]
    assert da["measured"] == db["measured"] is False
    assert da["examined"] == db["examined"] == 0


def test_it_reads_the_report_rather_than_recomputing():
    """★ #1032: the moment this tool works out `measured` for itself, the two siblings can
    disagree about whether the audit saw anything — which is the defect, one level up."""
    import ast
    import inspect

    src = inspect.getsource(ST.ListSeedIssuesTool)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and "examined" in ast.dump(node):
            raise AssertionError("measured is being recomputed here: %s" % ast.dump(node)[:120])
    assert "report.measured" in src
