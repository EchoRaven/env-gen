r"""#1203qj: the DDL had the column; the parser could not see it, and the lane was told to add it.

`extract_sql_tables` skips table-level constraint CLAUSES by testing the line's first token
against {CONSTRAINT, PRIMARY, FOREIGN, UNIQUE, CHECK, INDEX}. It stripped the quotes BEFORE
that test -- and the quotes are the only thing distinguishing the two cases postgres allows:

    UNIQUE (email, tenant_id)     a table-level clause, which MUST be unquoted
    "unique" TEXT                 a column whose name collides with a reserved word, which
                                  MUST be quoted

So a quoted column named `unique` was read as a constraint clause and dropped from
`sql_tables`, while sitting in plain sight in the DDL.

WHAT IT COST: the contract check then reported `SQL table `follows` missing registered
columns: unique` -- **690 of the 988 "missing registered columns" errors in the entire gate
ledger (70%)**, r171 358 and r183 294, and **124 of them on gate rows that PASSED**. The lane
was told to add a column the DDL already contained.

HOW IT WAS IDENTIFIED, after two wrong hypotheses that measurement killed:
  1. "fix it at the registration boundary -- drop the constraint-pseudo-column" -- WRONG and
     harmful: `database_scaffold._is_constraint_pseudo_column` (#32/#1031/#1203gx) legitimately
     converts two of those entries into real `UNIQUE (...)` clauses, and the DDL renderer reads
     the registry, so dropping them would have LOST a constraint. #1203gx's own comment states
     that cost: "the delivered app accepts duplicate likes and duplicate follows".
  2. "exclude pseudo-columns in the contract check" -- insufficient: that predicate recognises
     only 2 of the 10 corpus entries.
  3. Running `extract_sql_tables` on r171's own `app/database` returned
     ['created_at','follower_id','following_id','id'] for `follows` -- no `unique` -- while
     r188's non-reserved `unique_follow` came back fine. The quoting, not the registration,
     was the cause.

STILL OPEN AND DELIBERATELY NOT LANDED HERE: 8 of those 10 entries emit a junk column
(`"unique_user_video" TEXT UNIQUE`) instead of `UNIQUE(user_id, video_id)`, so the composite
constraint is lost. Fixing that ADDS constraints, which makes initdb fail where seed data
already holds duplicates -- #32's "postgres aborts, app never boots" in reverse -- so it needs
the duplicate measurement first and a live run (#1202w6).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.delivery.contract_extract import extract_sql_tables  # noqa: E402


def _tables(tmp_path, sql: str):
    d = tmp_path / "database"
    d.mkdir(parents=True, exist_ok=True)
    (d / "01_init.sql").write_text(sql, encoding="utf-8")
    return extract_sql_tables(d)


# r171's own shape, verbatim in structure
_R171 = '''
CREATE TABLE IF NOT EXISTS "follows" (
    "id" SERIAL PRIMARY KEY,
    "follower_id" INTEGER NOT NULL,
    "following_id" INTEGER NOT NULL,
    "created_at" TIMESTAMPTZ DEFAULT now(),
    "unique" TEXT
);
'''

# the spine's shape, which the skip list exists for
_SPINE = '''
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    tenant_id INTEGER NOT NULL,
    UNIQUE (email, tenant_id)
);
'''


def test_a_quoted_reserved_word_column_is_extracted(tmp_path):
    """★ r171's `follows`: the DDL has `"unique" TEXT` and the parser must see it."""
    t = _tables(tmp_path, _R171)
    assert "unique" in t["follows"], sorted(t["follows"])
    assert sorted(t["follows"]) == ["created_at", "follower_id", "following_id", "id", "unique"]


def test_an_unquoted_table_level_clause_is_still_skipped(tmp_path):
    """★ The other half, and the reason the skip list exists: postgres requires a table-level
    clause to be UNQUOTED, so `UNIQUE (email, tenant_id)` must not become a column."""
    t = _tables(tmp_path, _SPINE)
    assert sorted(t["users"]) == ["email", "id", "tenant_id"]
    assert "unique" not in t["users"]


@pytest.mark.parametrize("clause", [
    "UNIQUE (email, tenant_id)",
    "PRIMARY KEY (id)",
    "FOREIGN KEY (tenant_id) REFERENCES tenants(id)",
    "CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)",
    "CHECK (id > 0)",
])
def test_every_unquoted_clause_keyword_is_still_skipped(tmp_path, clause):
    sql = 'CREATE TABLE IF NOT EXISTS t (\n    id SERIAL,\n    %s\n);\n' % clause
    assert sorted(_tables(tmp_path, sql)["t"]) == ["id"]


@pytest.mark.parametrize("name", ["unique", "check", "index", "constraint", "primary", "foreign"])
def test_a_quoted_column_of_any_reserved_name_survives(tmp_path, name):
    """The rule is about QUOTING, not about which keyword it is."""
    sql = 'CREATE TABLE IF NOT EXISTS t (\n    id SERIAL,\n    "%s" TEXT\n);\n' % name
    # sorted() on BOTH sides: the first draft compared against the literal ["id", name],
    # which is only in order for names that sort after "id" -- so `check`, `constraint` and
    # `foreign` failed on the comparison rather than on the behaviour.
    assert sorted(_tables(tmp_path, sql)["t"]) == sorted(["id", name])


def test_ordinary_columns_are_unaffected(tmp_path):
    sql = ('CREATE TABLE IF NOT EXISTS "videos" (\n'
           '    "id" SERIAL PRIMARY KEY,\n'
           '    "caption" TEXT,\n'
           '    "views" INTEGER DEFAULT 0\n);\n')
    assert sorted(_tables(tmp_path, sql)["videos"]) == ["caption", "id", "views"]


class TheCorpusCaseStillReadsThatWay:
    """Against the artifacts the measurement came from, when they are on this machine."""

    @staticmethod
    def _db(run):
        return (Path(__file__).resolve().parents[2] / "generated" / run / "app" / "database")

    def test_r171_follows_now_carries_its_quoted_column(self):
        d = self._db("tiktok-web-r171")
        if not d.exists():
            pytest.skip("tiktok-web-r171 is not on this machine")
        t = extract_sql_tables(d)
        assert "unique" in t.get("follows", set()), sorted(t.get("follows", []))

    def test_the_spine_table_gains_nothing_spurious(self):
        d = self._db("tiktok-web-r171")
        if not d.exists():
            pytest.skip("tiktok-web-r171 is not on this machine")
        t = extract_sql_tables(d)
        assert "unique" not in t.get("users", set()), sorted(t.get("users", []))
