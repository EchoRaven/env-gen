"""#1112: #1110 let the sequence assign the id, and the children kept pointing at the old one.

#1110 stopped collapsing an unparseable primary key to 0 and dropped the key instead, so
the database assigns one. The parent rows land — and every child row still carries the
value the seed wrote, which now matches nothing:

    users:  id "aaaaaaaa-…" -> assigned 1
    posts:  user_id "aaaaaaaa-…"  ->  ForeignKeyViolation, dropped

Measured before this fix on exactly that shape: users 2, posts 0.

Two halves, both needed:

**The map.** As each row lands, when the id the database chose differs from the one the
seed wrote, remember it; when a later row carries a ``<name>_id`` whose value is a key of
that table's map, rewrite it. A row that kept its explicit PK records nothing, so an
untouched seed is byte-identical.

**The order.** The map only helps if the parent is inserted first. `_seed_topo_order`
read the DECLARED FKs, and a contract that never writes ``references`` — instagram-run50
is one — left `fks` empty, so the order came out alphabetical: `comments` before `posts`.
The edge is now also inferred from the ``<name>_id`` convention this file already relies
on (#807's orphan scan reads ``_fk[:-3]`` the same way). Ordering only: no schema, no
constraint, and a declared-FK contract sorts identically.
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

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    write_backend_skeleton, _seed_topo_order)

_ID = {"name": "id", "type": "serial primary key"}


def _t(*cols):
    return {"schema": {"columns": [_ID, *cols]}}


_UNDECLARED = {
    "users": _t({"name": "email", "type": "text"}),
    "comments": _t({"name": "post_id", "type": "integer"}),
    "posts": _t({"name": "user_id", "type": "integer"}),
}
_DECLARED = {
    "users": _t({"name": "email", "type": "text"}),
    "comments": _t({"name": "post_id", "type": "integer", "references": "posts(id)"}),
    "posts": _t({"name": "user_id", "type": "integer", "references": "users(id)"}),
}


def _order(tables, tmp_path):
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/posts"}], tables)
    src = (tmp_path / "app" / "backend" / "seed_data.py").read_text()
    line = next(l for l in src.splitlines() if l.startswith("_ORDER"))
    return eval(line.split("=", 1)[1])


def test_an_undeclared_fk_still_orders_parent_first(tmp_path):
    """★ instagram-run50's shape: no `references` anywhere, and the old order put
    `comments` before `posts`."""
    o = _order(_UNDECLARED, tmp_path)
    assert o.index("posts") < o.index("comments"), o


def test_a_declared_fk_orders_the_same_way(tmp_path):
    """Non-regression: the path that already worked is unchanged."""
    assert _order(_DECLARED, tmp_path) == _order(_UNDECLARED, tmp_path / "b")


def test_the_topo_sort_reads_the_naming_convention():
    """Directly: `cols` is a list of NAMES on the meta record — the first draft looked
    for `columns` and silently inferred nothing."""
    meta = {"users": {"cols": ["id", "email"], "fks": {}},
            "comments": {"cols": ["id", "post_id"], "fks": {}},
            "posts": {"cols": ["id", "user_id"], "fks": {}}}
    o = _seed_topo_order(meta)
    assert o.index("posts") < o.index("comments"), o
    assert o.index("users") < o.index("posts"), o


def test_a_self_reference_does_not_deadlock():
    """`parent_id` on the same table must not make it depend on itself."""
    meta = {"comments": {"cols": ["id", "parent_id", "post_id"], "fks": {}},
            "posts": {"cols": ["id"], "fks": {}}}
    o = _seed_topo_order(meta)
    assert set(o) == {"comments", "posts"}
    assert o.index("posts") < o.index("comments")


def test_an_id_naming_nothing_is_ignored():
    """`external_id` names no table — it must not invent an edge or drop the table."""
    meta = {"users": {"cols": ["id", "external_id"], "fks": {}},
            "posts": {"cols": ["id", "user_id"], "fks": {}}}
    o = _seed_topo_order(meta)
    assert set(o) == {"users", "posts"}
    assert o.index("users") < o.index("posts")


def test_the_loader_carries_the_remap(tmp_path):
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/posts"}], _DECLARED)
    src = (tmp_path / "app" / "backend" / "seed_data.py").read_text()
    assert "_pk_remap = {}" in src
    i = src.index("_pk_remap = {}")
    j = src.index("db.commit()", i)
    seg = src[i:j]
    assert "_pk_remap.setdefault(t, {})[_orig_pk] = _got_pk" in seg
    assert "_got_pk != _orig_pk" in seg          # a kept PK records nothing


def test_end_to_end_the_child_finds_its_parent(tmp_path):
    """★ Before: users 2, posts 0 (both dropped on posts_user_id_fkey)."""
    sys.path.insert(0, "/tmp/claude-1052/-data-common-haibotong/"
                       "375c5958-8985-4adc-a760-9fb9c9a816cc/scratchpad/probe")
    try:
        from harness import reset_db, PG_BASE
    except Exception:
        pytest.skip("probe harness not available")
    from multi_agent.runtime.oauth_scaffold import write_oauth_as
    tables = {
        "users": _t({"name": "email", "type": "text"}, {"name": "name", "type": "text"},
                    {"name": "password_hash", "type": "text"},
                    {"name": "tenant_id", "type": "text"}),
        "posts": _t({"name": "user_id", "type": "integer", "references": "users(id)"},
                    {"name": "caption", "type": "text"}),
    }
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/posts"}], tables)
    write_oauth_as(tmp_path)
    be = tmp_path / "app" / "backend"
    json.dump({"users": [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "email": "a@x.io"},
                         {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "email": "b@x.io"}],
               "posts": [{"id": 1, "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
                         {"id": 2, "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}]},
              open(be / "seed_data.json", "w"))
    try:
        reset_db("pk1112")
    except Exception:
        pytest.skip("probe postgres not reachable")
    keys = tmp_path / "k"
    keys.mkdir(exist_ok=True)
    code = ("import sys;sys.path.insert(0,'.')\n"
            "import database, seed_data\n"
            "database.Base.metadata.create_all(bind=database.engine)\n"
            "seed_data.seed_if_empty()\n"
            "from sqlalchemy import text\n"
            "db=database.SessionLocal()\n"
            "print([tuple(r) for r in db.execute(text("
            "'select id,user_id from posts order by id'))])\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(be),
                       env=dict(os.environ, DATABASE_URL=PG_BASE + "pk1112",
                                JWT_SECRET="x", JWT_DATA_DIR=str(keys)),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    last = r.stdout.strip().splitlines()[-1]
    assert last == "[(1, 1), (2, 2)]", r.stdout


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
