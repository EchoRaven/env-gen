"""#1168: density was audited, parentage never was.

The framework audits how MANY seeded rows exist (#84's floor, #1039's live
COUNT(*)) and has never once audited whether those rows REFERENCE anything.
#1105 is what that costs: a seed backfilled a tenant nobody created,
users.tenant_id pointed at it, and 58 of 59 runs lost every seeded user --
found by disaster, not by a check. #1160 produced the same shape from the other
end (the owner auto-fill wrote a USER id into a PROFILE column, so every
my_list row referenced a profile that does not exist) and surfaced only because
a live app was probed by hand.

The DDL carries no FK CONSTRAINTS -- #1162's foreign keys are ORM metadata and
the tables come from 01_init.sql -- so information_schema cannot answer this.
Parentage is derived with the SAME rule #1162 renders from, `<x>_id` -> a table
named `<x>`/`<x>s`/`<x>es`, entirely inside SQL.

Verified against r13's live database: the query derives 13 FK pairs (r14: 12)
and reports zero orphans; injecting one my_list row with profile_id 999999 --
#1160's exact shape -- is reported as `my_list.profile_id: 1`, and deleting it
returns the count to zero.
"""
import inspect
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import seed_audit as sa
from env_generator.llm_generator.multi_agent.runtime import deliverability as dv


def test_the_audit_reports_orphans():
    assert "orphan_fk_rows" in {f.name for f in
                                __import__("dataclasses").fields(sa.SeedReport)}


def test_it_is_evidence_not_a_verdict():
    """`is_clean` must not move: a false seed blocker wedges a run (#566j), and
    #956/#1023d deliberately froze this audit's verdict."""
    src = Path(sa.__file__).read_text(encoding="utf-8")
    i = src.index("def is_clean") if "def is_clean" in src else -1
    if i >= 0:
        body = src[i:src.index("\n\n", i)]
        assert "orphan" not in body
    r = sa.SeedReport(flagged_tables=[], orphan_fk_rows={"my_list.profile_id": 3})
    assert r.is_clean is True


def test_it_never_measures_without_a_project():
    assert sa.orphan_fk_rows_1168(None) == {}


def test_a_missing_compose_returns_not_measured(tmp_path):
    """`{}` must mean "not measured", never "everything is broken" -- the #1039
    contract this follows."""
    assert sa.orphan_fk_rows_1168(tmp_path) == {}


def test_it_can_never_raise(tmp_path):
    sa.orphan_fk_rows_1168(tmp_path / "nope")
    sa.orphan_fk_rows_1168(12345)


def test_the_sql_derives_parentage_the_same_way_1162_renders_it():
    """Two rules for one question become two rules the first time either is edited
    (#1036). Both spell `<x>_id` -> <x> / <x>s / <x>es."""
    src = inspect.getsource(sa.orphan_fk_rows_1168)
    assert "left(c.column_name, -3)" in src
    assert "||'s'" in src and "||'es'" in src
    assert "c.table_name <> t.tablename" in src      # a self-reference is not an orphan
    assert "IS NOT NULL" in src                      # a NULL FK is unset, not dangling


def test_the_finding_reaches_the_deliverability_report():
    """Computing it and not publishing it is the #691 mistake."""
    src = Path(dv.__file__).read_text(encoding="utf-8")
    assert "orphan_fk_rows" in src and "orphan_fk_total" in src
