"""#1110: coercing an unparseable id to 0 keeps ONE row and loses the rest.

``_coerce_nested_for_string_cols`` neutralises a non-numeric string in a numeric column
to 0 — #213's fix, and right for a DATA column: a caption in a count column becomes 0 and
the row survives instead of the per-table commit rolling the whole table back.

For a PRIMARY KEY it does the opposite of what it is for. Every unparseable id collapses
to the SAME 0, so the first row takes it and every other row dies on a UniqueViolation.
The table keeps one row.

instagram-run50 is the delivered case: its ``seed_data.json`` gives users, posts,
comments and messages UUID-string ids while the schema declares SERIAL. Brought up under
compose — the real topology, postgres built from ``app/database/init`` — its database
holds ``_seed_meta=1`` and ``tenants=1`` and nothing else. A delivered app with no data.

47 seed rows across 4 runs (2 delivered) carry an id whose type conflicts with the
declared PK type.

★ The framework already had the right answer one branch below: #600's datetime branch
drops the key on anything unparseable, "so a bad value can never take the whole row down
with it". This applies that to the primary key — drop it and let the sequence assign.
The data-column behaviour is untouched, which the tests below pin.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402

_TABLES = {"users": {"schema": {"columns": [
    {"name": "id", "type": "serial primary key"},
    {"name": "email", "type": "text"},
    {"name": "follower_count", "type": "integer"}]}}}


@pytest.fixture(scope="module")
def coerce():
    """The emitted helper, exec'd standalone against a stub model."""
    import types
    out = Path(tempfile.mkdtemp())
    write_backend_skeleton(out, [{"method": "GET", "path": "/api/users"}], _TABLES)
    src = (out / "app" / "backend" / "seed_data.py").read_text()
    i = src.index("def _coerce_nested_for_string_cols")
    j = src.index("\ndef ", i + 10)
    m = types.ModuleType("coerce1110")
    m.__dict__["json"] = json
    exec(compile(src[i:j], "seed_data.py", "exec"), m.__dict__)
    return m._coerce_nested_for_string_cols


class _Col:
    def __init__(self, name, type_, pk=False):
        self.name, self.type, self.primary_key = name, type_, pk


class _Cols(dict):
    pass


def _cls(*cols):
    import types as _t
    from sqlalchemy import Integer, Text
    kinds = {"int": Integer(), "text": Text()}
    d = _Cols({c[0]: _Col(c[0], kinds[c[1]], len(c) > 2 and c[2]) for c in cols})
    return _t.SimpleNamespace(__table__=_t.SimpleNamespace(columns=d))


def test_an_unparseable_primary_key_is_dropped(coerce):
    """★ Dropped, not zeroed — otherwise every such row lands on the same id."""
    cls = _cls(("id", "int", True), ("email", "text"))
    out = coerce(cls, {"id": "11111111-1111-1111-1111-111111111111", "email": "a@x.io"})
    assert "id" not in out
    assert out["email"] == "a@x.io"


def test_two_unparseable_keys_no_longer_collide(coerce):
    """The failure this ticket is about: both used to become 0."""
    cls = _cls(("id", "int", True))
    a = coerce(cls, {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"})
    b = coerce(cls, {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"})
    assert "id" not in a and "id" not in b


def test_an_unparseable_data_column_is_still_zeroed(coerce):
    """★ #213's behaviour must not change: 0 keeps the row, and losing the row loses
    the whole table to the per-table rollback."""
    cls = _cls(("id", "int", True), ("follower_count", "int"))
    out = coerce(cls, {"follower_count": "lots"})
    assert out["follower_count"] == 0


def test_a_parseable_key_is_kept(coerce):
    """An explicit numeric id is the seed's intent — #56/#135 rely on it."""
    cls = _cls(("id", "int", True))
    assert coerce(cls, {"id": "7"})["id"] == 7
    assert coerce(cls, {"id": 7})["id"] == 7


def test_a_parseable_data_value_is_kept(coerce):
    cls = _cls(("id", "int", True), ("follower_count", "int"))
    assert coerce(cls, {"follower_count": "7"})["follower_count"] == 7


def test_a_text_key_is_untouched(coerce):
    """A uuid/text PK is a legitimate schema — only the INTEGER branch changes."""
    cls = _cls(("id", "text", True))
    v = "11111111-1111-1111-1111-111111111111"
    assert coerce(cls, {"id": v})["id"] == v


def test_the_emitted_source_drops_rather_than_zeroes():
    out = Path(tempfile.mkdtemp())
    write_backend_skeleton(out, [{"method": "GET", "path": "/api/users"}], _TABLES)
    src = (out / "app" / "backend" / "seed_data.py").read_text()
    # landmark-anchored, not a byte window: #943's ratchet exists because a comment
    # growing above the assertion pushes the subject out of a fixed slice, which is
    # exactly what the first draft of this test did to itself.
    i = src.index("elif _is_int and not isinstance(v, int):")
    j = src.index("elif _is_num and not isinstance(v, (int, float)):", i)
    seg = src[i:j]
    assert "primary_key" in seg and "out.pop(k, None)" in seg
    assert "out[k] = 0" in seg          # the data-column path still exists


def test_end_to_end_every_row_survives(tmp_path):
    """★ The whole point: three users, two with UUID ids, all three land."""
    sys.path.insert(0, "/tmp/claude-1052/-data-common-haibotong/"
                       "375c5958-8985-4adc-a760-9fb9c9a816cc/scratchpad/probe")
    try:
        from harness import reset_db, PG_BASE
    except Exception:
        pytest.skip("probe harness/postgres not available")
    from multi_agent.runtime.oauth_scaffold import write_oauth_as
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/users"}], _TABLES)
    write_oauth_as(tmp_path)
    be = tmp_path / "app" / "backend"
    json.dump({"users": [
        {"id": "11111111-1111-1111-1111-111111111111", "email": "a@x.io"},
        {"id": "22222222-2222-2222-2222-222222222222", "email": "b@x.io"},
        {"id": 3, "email": "c@x.io"}]}, open(be / "seed_data.json", "w"))
    try:
        reset_db("pk1110")
    except Exception:
        pytest.skip("probe postgres not reachable")
    keys = tmp_path / "k"
    keys.mkdir(exist_ok=True)
    code = ("import sys;sys.path.insert(0,'.')\n"
            "import database, seed_data\n"
            "database.Base.metadata.create_all(bind=database.engine)\n"
            "seed_data.seed_if_empty()\n"
            "from sqlalchemy import text\n"
            "print(database.SessionLocal().execute(text('select count(*) from users')).scalar())\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(be),
                       env=dict(os.environ, DATABASE_URL=PG_BASE + "pk1110",
                                JWT_SECRET="x", JWT_DATA_DIR=str(keys)),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().splitlines()[-1] == "3", r.stdout


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
