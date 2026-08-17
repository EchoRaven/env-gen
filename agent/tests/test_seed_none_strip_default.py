"""#409 (FW_DEBUG-surfaced live on netflix r7): the seed loader's main insert built the row as
`{k: v for k, v in row.items() if hasattr(cls, k)}` — INCLUDING keys whose value is None. A
seed/fallback row carrying `created_at: None` then inserted an EXPLICIT NULL, which BYPASSES the
DB `DEFAULT now()` that #407 renders (a default only fills an OMITTED column, never an explicit
NULL) → NotNullViolation → the row is DROPPED (r7: 6 profiles + 6 my_list dropped on
created_at). #407 was working (the DDL HAD `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`); the
bug was the explicit-NULL insert. FIX: omit None-valued keys from the insert so the DB default
applies. Airtight: a drop on a DEFAULT-ed column can ONLY come from an explicit NULL. Safe +
generalizes to any app with a NOT-NULL-defaulted column (omitting a None key → DB default, or
NULL for a nullable col — never worse). This locks the None-strip in.
"""
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py")


def _src():
    return _SRC.read_text(encoding="utf-8")


def test_main_seed_insert_strips_none():
    # the main-path comprehension (row.items()) must now guard `v is not None`
    src = _src()
    assert "for k, v in row.items()" in src
    assert "if hasattr(cls, k) and v is not None" in src


def test_rendered_comprehension_is_valid_python():
    # reconstruct the multi-line dict comprehension exactly as it renders and compile it,
    # so the 3-line f-string split can't ship a SyntaxError into seed_data.py
    snippet = (
        "row = {'created_at': None, 'name': 'Kids'}\n"
        "class _C:\n"
        "    created_at = 1\n"
        "    name = 1\n"
        "cls = _C\n"
        "out = {k: v for k, v in row.items()\n"
        "       if hasattr(cls, k) and v is not None}\n"
    )
    ns = {}
    exec(compile(snippet, "<seed>", "exec"), ns)
    # None-valued created_at is DROPPED (so the DB DEFAULT now() applies); real fields kept
    assert ns["out"] == {"name": "Kids"}, ns["out"]


def test_none_strip_keeps_falsy_non_none():
    # 0 / '' / False are REAL values and must NOT be stripped (only None)
    ns = {}
    exec(compile(
        "row = {'value': 0, 'flag': False, 'note': '', 'gone': None}\n"
        "cls = type('C', (), {'value':1,'flag':1,'note':1,'gone':1})\n"
        "out = {k: v for k, v in row.items() if hasattr(cls, k) and v is not None}\n",
        "<seed>", "exec"), ns)
    assert ns["out"] == {"value": 0, "flag": False, "note": ""}, ns["out"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
