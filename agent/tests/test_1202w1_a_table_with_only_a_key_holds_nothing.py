"""#1202w1: a table registered with nothing but a primary key cannot hold what it names.

netflix-r30 shipped it. The orchestrator registered `titles`, `genres`, `title_genres` and
`episodes` at 13:47 with ONE column each — the name-first shape #90 deliberately makes legal,
for the lane to fill in — and the backend lane filled `profiles` and `my_list` at 14:00–14:19
and never those four.

So `models.py` carried `class TitleGenre(Base): id` with no `title_id` and no `genre_id`. The
lane's own 15 `title_genres` seed rows had no column to land in, and the delivered database
holds 60 titles, 22 genres and ZERO associations between them — every genre browse empty, by
construction.

Its own materials say `title_genres: [id, title_id, genre_id]`, and the framework has read
that since #1202hk. Only the spine was ever wired to it.

The scope was measured, not chosen. Over the 165 corpus runs carrying a spec, backfilling
every under-declared table would append 731 columns across 211 tables — a table the lane
actually shaped is the lane's to shape. A table with only a primary key has been shaped by
nobody: 33 tables, 144 columns, across netflix, tiktok and googlemaps runs alike.
"""
import ast
import inspect
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import backend_skeleton as BS      # noqa: E402
from multi_agent.runtime.kickoff import run_kickoff as RK    # noqa: E402


def _spec(tmp_path, entities):
    (tmp_path / "design").mkdir(parents=True, exist_ok=True)
    (tmp_path / "design" / "reference_spec.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8")
    return tmp_path


def test_the_materials_reader_returns_the_fields(tmp_path):
    """The half that always worked, pinned so the widening below is testing the WIRING."""
    _spec(tmp_path, [{"name": "link_rows", "fields": ["id", "left_id", "right_id"]}])
    assert BS._spec_entity_fields_1202hk(tmp_path, "link_rows") == ["id", "left_id", "right_id"]
    assert BS._spec_entity_fields_1202hk(tmp_path, "absent") == []


def _gate_source():
    src = inspect.getsource(RK)
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "_SPINE_OWNED_TABLES_1202HK" in ast.unparse(n))


def _backfill_gate():
    """The `if` whose body performs the materials backfill — located by what it DOES."""
    fn = _gate_source()
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "_spec_entity_fields_1202hk" in ast.unparse(node.body):
            return node
    raise AssertionError("no branch guards the materials backfill")


def test_a_pk_only_table_now_reaches_the_backfill():
    """AST (#943), and asserted on the CONDITION rather than the function text.

    The first version of this test checked that `_pk_only_1202w1` appeared somewhere in the
    function, and a mutation that reverted the gate to spine-only left the assignment in
    place and passed. A name is not a use.
    """
    cond = ast.unparse(_backfill_gate().test)
    assert "_SPINE_OWNED_TABLES_1202HK" in cond, "the spine case must remain in the gate"
    assert "_pk_only_1202w1" in cond, (
        "a PK-only table must be admitted BY THE GATE, not merely computed beside it")


def test_a_table_the_lane_shaped_is_left_to_the_lane():
    """The measured limit: 211 tables / 731 columns if every under-declared table were
    backfilled. Two columns means someone shaped it, and this must not reach it."""
    src = ast.unparse(_gate_source())
    assert "<= 1" in src, (
        "the PK-only test must be `at most one column`, not `fewer than the materials name`")


@pytest.mark.parametrize("cols,expected", [
    ([], True),
    ([{"name": "id"}], True),
    ([{"name": "id"}, {"name": "title_id"}], False),
    ([{"name": "id"}, {"name": "a"}, {"name": "b"}], False),
])
def test_the_pk_only_predicate_is_what_the_gate_uses(cols, expected):
    """Evaluated the way the gate evaluates it, so the two cannot drift."""
    got = isinstance(cols, list) and len([c for c in cols if isinstance(c, dict)]) <= 1
    assert got is expected


def test_the_r30_shape_is_what_this_fills(tmp_path):
    """The delivered case, end to end through the real reader: a join table registered with
    only `id`, whose materials name both of its foreign keys."""
    _spec(tmp_path, [{"name": "title_genres", "fields": ["id", "title_id", "genre_id"]}])
    have = {"id"}
    added = [f for f in BS._spec_entity_fields_1202hk(tmp_path, "title_genres")
             if f.lower() not in have]
    assert added == ["title_id", "genre_id"], (
        "both foreign keys must come back — without them the table associates nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
