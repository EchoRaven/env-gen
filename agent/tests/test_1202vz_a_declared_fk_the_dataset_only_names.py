"""#1202vz: the dataset states the relationship; the schema declares it under another name.

tiktok-r135 shipped the consequence. `videos.sound_id` was NULL on 31 of 39 rows, the lane's
`GET /api/feed/foryou` INNER JOINs `sounds`, and the app's front page served 8 videos while
its own `total` said 39 — 79% of the delivered content unreachable, with nothing saying so.
Probed live against the delivered stack: the database holds 39, the feed pages out after 8,
and `next_cursor` is then None.

The link was never missing, only unresolved. The dataset row carries
`"sound": "오리지널 사운드 - BTS"`, and the staged `sounds` table has that exact `name` on id 1.

Measured over the corpus datasets with the real function: 66 runs and 2,310 rows get a
declared FK resolved. Self-referential FKs are excluded first and are NOT defects — a
top-level row has no parent, and filling one would invent a hierarchy the materials never
described (24 such cases in the corpus must stay untouched).

Same envelope as #1202rw, which fills a declared TIME column no row populates: keyed off the
declared column rather than any table or product name, byte-identical when nothing applies,
deterministic so the runtime seed fingerprint stays stable.
"""
import json
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import material_prep as MP          # noqa: E402

_R = MP.resolve_dataset_fks_1202vz


def _schema(**over):
    s = {
        "clips": {"id": {"type": "integer", "nullable": False, "pk": True, "fk": None},
                  "track_id": {"type": "integer", "nullable": True, "pk": False,
                               "fk": "tracks.id"}},
        "tracks": {"id": {"type": "integer", "nullable": False, "pk": True, "fk": None},
                   "name": {"type": "string", "nullable": True, "pk": False, "fk": None}},
    }
    s.update(over)
    return s


def _data(n=5):
    return {
        "clips": [{"id": str(i), "track": f"song {i % 2}"} for i in range(n)],
        "tracks": [{"id": "1", "name": "song 0"}, {"id": "2", "name": "song 1"}],
    }


def test_the_natural_key_resolves_the_declared_fk():
    out = _R(_data(), _schema())
    got = [r.get("track_id") for r in out["clips"]]
    assert all(g is not None for g in got), "every row's link was stated and must resolve"
    assert got == ["1", "2", "1", "2", "1"], f"resolved deterministically to the named row: {got}"


def test_an_authored_value_is_never_overwritten():
    """One populated row means the dataset owns the column — #1202rw's rule."""
    d = _data()
    d["clips"][0]["track_id"] = "999"
    out = _R(d, _schema())
    assert out["clips"][0]["track_id"] == "999"
    assert out["clips"][1].get("track_id") is None, (
        "a partially populated column belongs to the dataset; this must not touch it")


def test_a_self_referential_fk_is_left_alone():
    """A top-level row has no parent. 24 corpus cases are this, and filling one would invent
    a hierarchy the materials never described.

    The rows below WOULD resolve if the guard were removed -- each `parent` uniquely names
    another row's `label` -- so this pins the self-reference rule itself rather than passing
    because the data happened to be ambiguous.
    """
    sch = _schema(clips={"id": {"type": "integer", "nullable": False, "pk": True, "fk": None},
                         "label": {"type": "string", "nullable": True, "pk": False, "fk": None},
                         "parent_id": {"type": "integer", "nullable": True, "pk": False,
                                       "fk": "clips.id"}})
    d = {"clips": [{"id": str(i), "label": f"row {i}", "parent": f"row {(i + 1) % 5}"}
                   for i in range(5)]}
    out = _R(json.loads(json.dumps(d)), sch)
    assert all(r.get("parent_id") is None for r in out["clips"]), (
        "a self-referential FK must be refused even when it would resolve cleanly")


def test_a_partial_match_is_refused_rather_than_half_filled():
    """Below the floor the dataset is telling us something other than this link, and half a
    feed joined is still a broken feed. Without the floor, 2 of 5 rows would be filled and
    the other 3 would still vanish from every join -- the failure this fix exists to end,
    now silent AND partial."""
    d = _data()
    for r in d["clips"][2:]:
        r["track"] = "a name no track has"
    out = _R(json.loads(json.dumps(d)), _schema())
    assert all(r.get("track_id") is None for r in out["clips"]), (
        "a minority match is not a resolution")


def test_an_ambiguous_natural_key_is_refused():
    """A value that names two rows identifies neither — the whole candidate column is
    dropped rather than resolved to whichever came first."""
    d = _data()
    d["tracks"] = [{"id": "1", "name": "same"}, {"id": "2", "name": "same"}]
    for r in d["clips"]:
        r["track"] = "same"
    out = _R(d, _schema())
    assert all(r.get("track_id") is None for r in out["clips"])


def test_an_unresolvable_fk_stays_null_and_says_so(caplog):
    """Leaving it NULL is the old behaviour; saying so is the new part (#1202vt's lesson).
    The corpus has 9 of these the rule cannot reach."""
    d = _data()
    for r in d["clips"]:
        r.pop("track", None)
        r["composer"] = "nobody"          # no key named after the FK's base
    with caplog.at_level(logging.WARNING, logger=MP.__name__):
        out = _R(d, _schema())
    assert all(r.get("track_id") is None for r in out["clips"])
    said = " ".join(rec.getMessage() for rec in caplog.records)
    assert "#1202vz" in said and "clips.track_id" in said and "tracks" in said


def test_nothing_changes_when_nothing_applies():
    """Byte-identical for a dataset with no declared FK — the #1202rw envelope."""
    sch = {"clips": {"id": {"type": "integer", "nullable": False, "pk": True, "fk": None}}}
    d = {"clips": [{"id": "1", "track": "song 0"}]}
    before = json.dumps(d, sort_keys=True)
    out = _R(d, sch)
    assert json.dumps(out, sort_keys=True) == before


def test_it_is_deterministic():
    """The runtime seed fingerprint keys on this file; two runs must agree."""
    a = json.dumps(_R(_data(7), _schema()), sort_keys=True)
    b = json.dumps(_R(_data(7), _schema()), sort_keys=True)
    assert a == b


def test_odd_input_is_returned_untouched():
    assert _R(None, {}) is None
    assert _R({"clips": "not a list"}, _schema()) == {"clips": "not a list"}
    assert _R({}, None) == {}


def test_it_runs_in_the_dataset_chain_after_the_ids_exist():
    """AST (#943). It must sit after #1202ry, which gives the TARGET rows the ids this
    writes, and before the id-type alignment, so what it writes is aligned like every
    other id."""
    import ast
    import inspect

    from multi_agent.runtime import backend_skeleton as BS
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(BS)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_ensure_seed_dataset")
    order = [c.func.id for c in ast.walk(fn)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    for name in ("assign_dataset_ids_1202ry", "resolve_dataset_fks_1202vz",
                 "align_dataset_id_types"):
        assert name in order, f"{name} is not called in the dataset chain"
    assert order.index("assign_dataset_ids_1202ry") < order.index("resolve_dataset_fks_1202vz")
    assert order.index("resolve_dataset_fks_1202vz") < order.index("align_dataset_id_types")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
