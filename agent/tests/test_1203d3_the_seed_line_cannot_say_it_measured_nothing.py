r"""#1203d3: the gate report's seed line shows a definite 0 and cannot say it measured nothing.

`_seed_summary` builds the dict the DELIVERY GATE REPORT prints, and dropped the audit's own
`examined` / `candidates` / `measured`.

That field exists for exactly this. `#1023d` put it on `SeedReport.to_dict()` — "a consumer
reading is_clean must be able to see whether anything was read" — because `is_clean` is
`not flagged_tables`: an audit that inspected NOTHING returns clean, indistinguishable on the
wire from one that inspected everything. `#1203c1` carried it into `list_seed_issues`.
`_seed_summary` is the THIRD reader of that report and still dropped it — #1202lf's shape,
third instance.

★ AND THE NUMBER BESIDE IT IS STRUCTURALLY ZERO. `registered` reads
`schema_hub.list_seed_registrations()`, which `#956`'s comment ten lines above it calls "0
records corpus-wide" — the reason it moved the AUDIT onto row counts. MEASURED over every gate
ledger: `registered` is **0 in 2312 of 2312 records across 52 runs**, never once non-zero, while
`tables` in the same records runs 7 to 17. r148 live: `{tables: 7, registered: 0, missing: 0}`.

★ `registered` ITSELF IS NOT CHANGED, deliberately. #1023d states the real repair "counts rows
at gate time, which needs a live database and stays open", and #956 showed forcing the verdict
is wrong on the merits (r154's twelve tables would all read `missing_seed` while its live
database held titles 60, episodes 16 and six more above the minimum). Swapping one always-zero
number for `examined` — 0 in 145 of 147 runs by #956's own measurement — would move the zero,
not repair it. What this adds is the ability to SAY so.
"""
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.deliverability as D  # noqa: E402
from multi_agent.runtime.seed_audit import SeedReport  # noqa: E402


def _hub(n_tables):
    return types.SimpleNamespace(schema_hub=types.SimpleNamespace(
        list_tables=lambda: {f"t{i}": {} for i in range(n_tables)},
        list_seed_registrations=lambda: {}))      # the real corpus state: always empty


def _summary(monkeypatch, report, n_tables=7):
    """★ `_seed_summary` imports `audit_seed_data` FUNCTION-LOCALLY
    (`from .seed_audit import audit_seed_data`), so patching it on `deliverability` does
    nothing — the real audit runs. It has to be patched on the module the import resolves
    against. My first fixture patched `D` and every assertion failed, including the two that
    must pass unpatched; that is what said the fixture was wrong rather than the patch."""
    import multi_agent.runtime.seed_audit as SA
    monkeypatch.setattr(SA, "audit_seed_data", lambda *a, **k: report)
    return D._seed_summary(_hub(n_tables), None)


def test_an_audit_that_looked_at_nothing_says_so(monkeypatch):
    """★ The case: no flagged tables AND nothing inspected — clean on the wire, blind in fact."""
    out = _summary(monkeypatch, SeedReport(flagged_tables=[], examined=0, candidates=11))
    assert out["flagged"] == 0 and out["missing"] == 0
    assert out["measured"] is False, out
    assert out["examined"] == 0 and out["candidates"] == 11, out


def test_a_real_clean_audit_is_distinguishable(monkeypatch):
    out = _summary(monkeypatch, SeedReport(flagged_tables=[], examined=11, candidates=11))
    assert out["flagged"] == 0
    assert out["measured"] is True, out
    assert out["examined"] == 11


def test_the_two_are_not_the_same_payload(monkeypatch):
    """Stated as the property rather than two assertions — identical payloads IS the defect."""
    blind = _summary(monkeypatch, SeedReport(flagged_tables=[], examined=0, candidates=4))
    clean = _summary(monkeypatch, SeedReport(flagged_tables=[], examined=4, candidates=4))
    assert blind != clean


def test_registered_is_unchanged_and_its_source_is_named(monkeypatch):
    """★ The number stays (the real repair is open, #1023d) — what changes is that a reader is
    told a 0 here says nothing about the database."""
    out = _summary(monkeypatch, SeedReport(flagged_tables=[], examined=3, candidates=3))
    assert out["registered"] == 0
    assert "list_seed_registrations" in out["registered_source_1203d3"], out
    assert "never writes it" in out["registered_source_1203d3"], out


def test_every_existing_key_keeps_its_meaning(monkeypatch):
    """Additive only — `tables`, `missing`, `flagged`, `flagged_tables` are untouched."""
    rep = SeedReport(
        flagged_tables=[{"table": "videos", "reason": "missing_seed"},
                        {"table": "users", "reason": "low_row_count"}],
        examined=2, candidates=2)
    out = _summary(monkeypatch, rep, n_tables=12)
    assert out["tables"] == 12
    assert out["missing"] == 1 and out["flagged"] == 2
    assert out["flagged_tables"] == [{"table": "videos", "reason": "missing_seed"},
                                     {"table": "users", "reason": "low_row_count"}]


def test_1203c5_still_has_what_it_names_tables_with(monkeypatch):
    """★ #1203c5's blocker reads `flagged_tables` out of this very dict. If a later edit drops
    it the blocker silently returns to a bare count, and this is where that shows."""
    out = _summary(monkeypatch, SeedReport(
        flagged_tables=[{"table": "video_likes", "reason": "missing_seed"}],
        examined=1, candidates=1))
    names = [t["table"] for t in out["flagged_tables"] if t.get("reason") == "missing_seed"]
    assert names == ["video_likes"], out


def test_an_audit_that_could_not_run_is_the_loudest_unmeasured_state(monkeypatch):
    """The two degraded returns (`audit_seed_data` missing, or raising) must not look clean."""
    import multi_agent.runtime.seed_audit as SA

    def _boom(*a, **k):
        raise RuntimeError("no audit")
    monkeypatch.setattr(SA, "audit_seed_data", _boom)
    out = D._seed_summary(_hub(7), None)
    assert out["measured"] is False, out
    assert out["tables"] == 0 and out["flagged"] == 0
    assert "did not run" in out["registered_source_1203d3"], out


def test_measured_is_read_from_the_report_not_recomputed():
    """★ #1032: the moment this computes `measured` for itself, the three readers of one report
    can disagree about whether the audit saw anything — which is the defect, one level up."""
    import ast
    import inspect

    src = inspect.getsource(D._seed_summary)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and "examined" in ast.dump(node):
            raise AssertionError("measured is being recomputed: %s" % ast.dump(node)[:120])
    assert 'getattr(report, "measured"' in src
