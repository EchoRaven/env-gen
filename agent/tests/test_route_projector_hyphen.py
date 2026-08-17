"""N-P0-2 (Netflix) safe subset: hyphenated path segments match snake_case tables.

A kebab-case route segment (``/api/my-list``, ``/api/for-you``) never matched its
snake_case table (``my_list``/``for_you``) in ``_match_model`` — only +s/-s and the
y->ies plural were normalized. So ``GET /api/my-list`` resolved to NO model and the
projector shipped a hardcoded empty stub. Netflix's ``/my-list`` (and ``/for-you``)
are exactly this shape. Normalizing ``-`` -> ``_`` is unambiguous: a segment carrying
a ``-`` matched nothing before, so the change can only add a correct match.

route_projector imports only stdlib at module level, so it loads standalone.
"""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/route_projector.py")


def _load():
    spec = importlib.util.spec_from_file_location("rp_iso", str(_P))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rp = _load()


def _cols():
    return {"columns": ["id"]}


def test_hyphen_segment_matches_snake_table():
    models = {"my_list": _cols(), "titles": _cols()}
    got = rp._match_model("my-list", models)
    assert got is not None and got[0] == "my_list"


def test_hyphen_for_you():
    models = {"for_you": _cols()}
    got = rp._match_model("for-you", models)
    assert got is not None and got[0] == "for_you"


def test_hyphen_plus_plural_combo():
    # normalize the hyphen AND the +s plural together.
    models = {"my_list": _cols()}
    got = rp._match_model("my-lists", models)
    assert got is not None and got[0] == "my_list"


def test_existing_plain_match_preserved():
    models = {"titles": _cols()}
    got = rp._match_model("titles", models)
    assert got is not None and got[0] == "titles"


def test_existing_ies_plural_preserved():
    # FIX #202 regression guard: activity -> activities must still work.
    models = {"activities": _cols()}
    got = rp._match_model("activity", models)
    assert got is not None and got[0] == "activities"


def test_no_false_match():
    models = {"titles": _cols()}
    assert rp._match_model("random-thing", models) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
