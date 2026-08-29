"""#1164: an ordinal column declared `text` sorts lexicographically.

Two framework components disagree about these columns and one of them is right.
The SEED vocabulary lists "seconds"/"count"/"rank"/"position"/"index" and routes
them to `_seed_number`, so the framework writes INTEGERS into them (r13's seed:
progress_seconds 83, 136, 189, 242) — while the contract said `text`, so the
column is TEXT and the API hands the client back "83".

Measured consequence on a feature shipped this session: r13 declared
`top10_rank` TEXT and r14 declared it INTEGER, for the same concept in the same
env. #1155 emits ORDER BY top10_rank, which over TEXT orders 1, 10, 11, 12, 2, 3
— a top-10 that is not the top 10.

Same shape as PROPOSAL #3 one column class over: the framework already overrides
a declared type when leaving it would produce something that cannot work.
"""
import json
import re
import types
from pathlib import Path

import pytest
import sqlalchemy.orm as _orm

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _reconcile_ordinal_types_1164 as reconcile, render_models)
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    render_schema_sql)


def _cols(**kw):
    return [{"name": n, "type": t} for n, t in kw.items()]


def test_ordinals_declared_text_become_integer():
    m = {"t": _cols(top10_rank="text", progress_seconds="text",
                    view_count="varchar", sort_index="text", row_position="text")}
    reconcile(m)
    assert all(c["type"] == "integer" for c in m["t"])


def test_ambiguous_names_are_left_alone():
    """`value`, `rating`, `score` and `price` are excluded on purpose even though the
    seed vocabulary covers them: a lane can legitimately mean text there, and #566t
    saw exactly that ({"rating": "thumbs_up"})."""
    m = {"t": _cols(value="text", rating="text", score="text", price="text")}
    reconcile(m)
    assert all(c["type"] == "text" for c in m["t"])


def test_an_already_numeric_ordinal_is_untouched():
    m = {"t": _cols(top10_rank="integer", progress_seconds="bigint")}
    reconcile(m)
    assert [c["type"] for c in m["t"]] == ["integer", "bigint"]


def test_a_primary_key_or_fk_column_is_never_retyped():
    m = {"t": [{"name": "sort_index", "type": "text", "primary_key": True},
               {"name": "owner_rank", "type": "text", "fk": "users.id"}]}
    reconcile(m)
    assert [c["type"] for c in m["t"]] == ["text", "text"]


def test_it_never_raises_on_junk():
    reconcile(None)
    reconcile({"t": [None, 5, {"name": None}, {}]})


def _contract(run):
    p = (Path(bs.__file__).parents[5] / "generated" / ("netflix-local-%s" % run)
         / "shared" / "hubs" / "registryhub_tables.json")
    if not p.exists():
        pytest.skip("%s artifact not on this box" % run)
    d = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in d.items()
            if isinstance(v, dict) and not str(k).startswith("_")}


@pytest.mark.parametrize("run", ["r13", "r14"])
def test_the_orm_and_the_ddl_agree_on_every_shared_column(run):
    """The two are rendered by DIFFERENT functions from the same contract.
    Retyping in models.py alone would recreate the exact mismatch that cost r13 its
    browse page — `column titles.genres does not exist` — with the sides swapped."""
    import sys
    sys.modules.setdefault("database", types.ModuleType("database"))
    sys.modules["database"].Base = _orm.declarative_base()
    contract = _contract(run)
    orm = dict(re.findall(r'^\s+(\w+) = Column\((\w+)', render_models(contract), re.M))
    ddl = {c: t.strip() for c, t in re.findall(
        r'^\s+"(\w+)" ([A-Z][A-Z ]*)', render_schema_sql(contract), re.M)}
    NUM = ("Integer", "BigInteger", "Float", "Numeric")
    NUMSQL = ("INT", "NUMERIC", "DOUBLE", "SERIAL", "REAL")
    shared = set(orm) & set(ddl)
    assert len(shared) > 15, shared
    for c in sorted(shared):
        assert (orm[c] in NUM) == any(k in ddl[c] for k in NUMSQL), (c, orm[c], ddl[c])
    assert orm.get("top10_rank") == "Integer"
    assert "INT" in ddl.get("top10_rank", "")
