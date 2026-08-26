"""#1113: the owner backfill guessed 1..n, and a seed that does not start at 1 lost every child.

A child row with no owner value gets one filled in. The rule was positional:

    row[owner] = (i % nu) + 1

which is right only when the users table happens to start at 1 and run contiguously.
instagram-run77 seeds users with explicit ids 1001.., and a re-seed onto an advanced
sequence produces the same mismatch — every guess then points at a user that does not
exist, the FK rejects the row, #218's savepoint drops it, and the table ships empty.

Measured before this fix, users 1001/1002 with two ownerless posts: users landed, posts
came out `[]`. After: `[(2001, 1001), (2002, 1002)]`, and a seed whose users really are
1 and 2 is unchanged at `[(1, 1), (2, 2)]`.

`users` is first in _ORDER, so the ids exist by the time a child is built. The lookup is
cached per seed pass and falls back to the old guess when it finds nothing, so a schema
with no user model behaves exactly as before.

★ Found by reviewing my own #1110/#1112 rather than by a probe: both changed which id a
row ends up with, which is precisely what this backfill assumes it knows.
"""
import ast
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402

_ID = {"name": "id", "type": "serial primary key"}
_TABLES = {
    "users": {"schema": {"columns": [
        _ID, {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]}},
    "posts": {"schema": {"columns": [
        _ID, {"name": "user_id", "type": "integer", "references": "users(id)"},
        {"name": "caption", "type": "text"}]}},
}


@pytest.fixture(scope="module")
def seed_src(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed1113")
    write_backend_skeleton(out, [{"method": "GET", "path": "/api/posts"}], _TABLES)
    return (out / "app" / "backend" / "seed_data.py").read_text()


def _load(seed_src, models_mod):
    tree = ast.parse(seed_src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_real_owner_ids")
    ns = {"models": models_mod, "_seed_dbg": lambda *a: None,
          "_CLASS": {"users": "User"}, "_PK": {"users": ["id", "integer"]}}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "seed_data.py", "exec"), ns)
    return ns["_real_owner_ids"]


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *a):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows, fail=False):
        self._rows, self.fail, self.queries = rows, fail, 0

    def query(self, cls):
        self.queries += 1
        if self.fail:
            raise RuntimeError("no table")
        return _Q(self._rows)


def test_it_returns_the_ids_that_exist(seed_src):
    m = types.SimpleNamespace(User=type("User", (), {"id": None}))
    db = _DB([types.SimpleNamespace(id=1001), types.SimpleNamespace(id=1002)])
    assert _load(seed_src, m)(db, {}) == [1001, 1002]


def test_it_caches_within_one_pass(seed_src):
    """It is called once per ownerless row; a query each time would be a table scan
    per row."""
    m = types.SimpleNamespace(User=type("User", (), {"id": None}))
    db = _DB([types.SimpleNamespace(id=5)])
    fn, cache = _load(seed_src, m), {}
    assert fn(db, cache) == [5] and fn(db, cache) == [5]
    assert db.queries == 1


def test_no_user_model_falls_back_quietly(seed_src):
    assert _load(seed_src, types.SimpleNamespace())(_DB([]), {}) == []


def test_a_broken_query_falls_back_quietly(seed_src):
    m = types.SimpleNamespace(User=type("User", (), {"id": None}))
    assert _load(seed_src, m)(_DB([], fail=True), {}) == []


def test_the_backfill_uses_it_and_keeps_the_old_guess_as_fallback(seed_src):
    i = seed_src.index("elif owner and not row.get(owner):")
    seg = seed_src[i:seed_src.index("for _ic in _IMAGE_COL", i)]
    assert "_real_owner_ids(db, _owner_id_cache)" in seg
    assert "(i % nu) + 1" in seg          # still there, for an empty result


@pytest.mark.parametrize("uids,pids,expect", [
    ([1001, 1002], [2001, 2002], "[(2001, 1001), (2002, 1002)]"),
    ([1, 2], [1, 2], "[(1, 1), (2, 2)]"),
])
def test_end_to_end(tmp_path, uids, pids, expect):
    """★ The first case used to come out `[]`."""
    sys.path.insert(0, "/tmp/claude-1052/-data-common-haibotong/"
                       "375c5958-8985-4adc-a760-9fb9c9a816cc/scratchpad/probe")
    try:
        from harness import reset_db, PG_BASE
    except Exception:
        pytest.skip("probe harness not available")
    from multi_agent.runtime.oauth_scaffold import write_oauth_as
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/posts"}], _TABLES)
    write_oauth_as(tmp_path)
    be = tmp_path / "app" / "backend"
    json.dump({"users": [{"id": u, "email": f"u{u}@x.io", "name": f"U{u}"} for u in uids],
               "posts": [{"id": p, "caption": f"p{p}"} for p in pids]},
              open(be / "seed_data.json", "w"))
    db = "own1113x" + str(uids[0])
    try:
        reset_db(db)
    except Exception:
        pytest.skip("probe postgres not reachable")
    keys = tmp_path / "k"
    keys.mkdir(exist_ok=True)
    code = ("import sys;sys.path.insert(0,'.')\n"
            "import database, seed_data\n"
            "database.Base.metadata.create_all(bind=database.engine)\n"
            "seed_data.seed_if_empty()\n"
            "from sqlalchemy import text\n"
            "print([tuple(r) for r in database.SessionLocal().execute(text("
            "'select id,user_id from posts order by id'))])\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(be),
                       env=dict(os.environ, DATABASE_URL=PG_BASE + db,
                                JWT_SECRET="x", JWT_DATA_DIR=str(keys)),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().splitlines()[-1] == expect, r.stdout


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
