r"""#1203c1: the agent read `is_clean: true` and cancelled the task that would have fixed it.

`seed_audit_check` returns `{"flagged_tables": [], "is_clean": true, "examined": 0,
"candidates": 7, "measured": false}` — #1023d added the last three so "examined nothing" could be
told from "found nothing wrong" — and the framework also LOGS it in words: "SEED AUDIT EXAMINED
0 OF 4 TABLES … Its clean verdict below means NOT CHECKED, not nothing wrong." 47 run logs carry
that line.

The log is the orchestrator's; the agent reads tool results, and there the affirmative field
comes first. r145's orchestrator agent called this tool 328 times and cancelled "Register
realistic seed data for videos table (blocks delivery)" with `cancel_reason: "Seed audit is now
clean (0 flagged tables); this P0 backend seed remediation is stale…"` over an audit that had
examined 0 of 4. The cancelled task named what it would fix: "table `videos` has missing_seed
with live_row_count=0". The run then held to the end — the dataset's 35 real captions never
reached `videos.title/description`, every video shipped captionless, the walk found no seed text
on `/`, and `primary_dataless` is in `browser_gate_decision`'s HARD set and never escapes.

★ THE VERDICT IS DELIBERATELY NOT TOUCHED. #1023d's comment explains why flipping `is_clean`
is wrong on the merits — it would flag 145 of 147 runs, and r154's twelve tables would read
`missing_seed` over a live database holding 60 titles, because the audit's notion of "seeded" is
`list_seed_registrations()` while the app seeds by SQL INSERT. False blockers wedge runs (#566j).
This adds one field, where the agent reads.
"""
import asyncio
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.seed_audit import SeedReport  # noqa: E402
import tools.seed_tools as ST  # noqa: E402

_KEY = "not_checked_1203c1"


def _run(report, monkeypatch):
    monkeypatch.setattr(ST, "audit_seed_data", lambda *a, **k: report)
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: None)
    res = asyncio.run(ST.SeedAuditCheckTool(hub_registry=types.SimpleNamespace()).execute())
    return res.data if hasattr(res, "data") else res["data"]


def test_an_unmeasured_audit_says_not_checked(monkeypatch):
    """★ r145's exact state: 0 of 4 examined, nothing flagged."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=4), monkeypatch)
    assert _KEY in d, sorted(d)
    assert "NOT CHECKED" in d[_KEY]
    assert "0 of 4" in d[_KEY], d[_KEY]


def test_it_tells_the_reader_not_to_cancel_remediation(monkeypatch):
    """★ The measured harm, named: the agent cancelled a seed task on this verdict."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=4), monkeypatch)
    assert "Do NOT cancel" in d[_KEY], d[_KEY]
    assert "live database" in d[_KEY], d[_KEY]


def test_a_real_clean_audit_carries_no_such_field(monkeypatch):
    """No noise on a verdict that means something — #1202vx: the explanation must not spend the
    evidence budget."""
    d = _run(SeedReport(flagged_tables=[], examined=4, candidates=4), monkeypatch)
    assert _KEY not in d, d
    assert d["is_clean"] is True and d["measured"] is True


def test_a_flagged_audit_carries_no_such_field(monkeypatch):
    d = _run(SeedReport(flagged_tables=[{"table": "videos", "reason": "missing_seed"}],
                        examined=4, candidates=4), monkeypatch)
    assert _KEY not in d
    assert d["is_clean"] is False


def test_an_app_with_nothing_auditable_is_not_flagged(monkeypatch):
    """`measured` is `examined > 0 or candidates == 0`: nothing to look at is not blindness."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=0), monkeypatch)
    assert _KEY not in d, d


def test_every_existing_field_keeps_its_meaning(monkeypatch):
    """★ Additive only. `is_clean` STAYS True on an unmeasured audit — #1023d rejected flipping
    it with evidence (145 of 147 runs, r154's live 60 titles), and this ticket does not reopen
    that."""
    d = _run(SeedReport(flagged_tables=[], examined=0, candidates=7), monkeypatch)
    assert d["is_clean"] is True
    assert d["measured"] is False
    assert d["examined"] == 0 and d["candidates"] == 7
    assert d["flagged_tables"] == []


def test_the_verdict_property_is_unchanged():
    """Pinned at the source: if someone later makes `is_clean` consider `measured`, that is a
    different decision with its own evidence, and this test is where they will notice."""
    import inspect
    src = inspect.getsource(SeedReport.is_clean.fget)
    assert "flagged_tables" in src
    assert "measured" not in src and "examined" not in src, src


def test_the_sibling_tool_still_carries_measured(monkeypatch):
    """#1202z5 put `measured` into `list_seed_issues`; this must not regress it."""
    rep = SeedReport(flagged_tables=[], examined=0, candidates=7)
    monkeypatch.setattr(ST, "audit_seed_data", lambda *a, **k: rep)
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: None)
    res = asyncio.run(ST.ListSeedIssuesTool(hub_registry=types.SimpleNamespace()).execute())
    d = res.data if hasattr(res, "data") else res["data"]
    assert d["measured"] is False and d["examined"] == 0
