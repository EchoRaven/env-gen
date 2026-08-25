"""#1111: the seed's users point at a tenant nothing creates.

#1105 made the loader create the `default` tenant before inserting users. A seed does
not have to use `default`: instagram-run50's users carry ``tenant_id: "tenant1"``,
run76's carry ``tenant-1`` / ``tenant-1-a1``, tiktok-r33's carry ``tenant-1``. All three
seeds even declare the tenant row — and ``_ORDER`` excludes ``tenants``, because the
identity spine is not seed-managed, so it is never inserted.

Every user row then dies on ``users_tenant_id_fkey``, #218's per-row savepoint drops it,
and the app comes up with no users. Three runs, **all three delivered**.

Brought up under compose — the shipped topology — instagram-run50 goes from a database
holding only ``_seed_meta=1`` and ``tenants=1`` to
``posts=13 follows=12 messages=12 users=5 comments=4 tenants=2``.

The guard now creates every tenant the seed's users refer to, not just `default`. It is
derived from the seed data itself, idempotent, and additive: a tenants row a user
already points at is exactly what the FK needs, so this cannot invalidate a seed that
was already correct.
"""
import ast
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

_TABLES = {"users": {"schema": {"columns": [
    {"name": "id", "type": "serial primary key"},
    {"name": "email", "type": "text"},
    {"name": "tenant_id", "type": "text"}]}}}


@pytest.fixture(scope="module")
def seed_src(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed1111")
    write_backend_skeleton(out, [{"method": "GET", "path": "/api/users"}], _TABLES)
    return (out / "app" / "backend" / "seed_data.py").read_text()


class _Col:
    def __init__(self, name):
        self.name = name


class _Tenant:
    __table__ = types.SimpleNamespace(columns=[_Col("id"), _Col("name"), _Col("status")])

    def __init__(self, **kw):
        self.kw = kw


class _DB:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.added, self.commits = [], 0

    def get(self, cls, pk):
        return object() if pk in self.existing else None

    def add(self, obj):
        self.added.append(obj)
        self.existing.add(obj.kw.get("id"))

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _load(seed_src):
    tree = ast.parse(seed_src)
    want = {"_ensure_default_tenant", "_ensure_one_tenant"}
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    assert len(fns) == 2, [f.name for f in fns]
    ns = {"models": types.SimpleNamespace(Tenant=_Tenant), "_seed_dbg": lambda *a: None}
    exec(compile(ast.Module(body=fns, type_ignores=[]), "seed_data.py", "exec"), ns)
    return ns["_ensure_default_tenant"]


def test_a_referenced_tenant_is_created(seed_src):
    """★ run50's shape: users point at `tenant1`, and nothing else ever makes it."""
    db = _DB()
    _load(seed_src)(db, {"users": [{"tenant_id": "tenant1"}, {"tenant_id": "tenant1"}]})
    ids = [o.kw["id"] for o in db.added]
    assert "tenant1" in ids and "default" in ids


def test_several_distinct_tenants(seed_src):
    """run76 refers to two."""
    db = _DB()
    _load(seed_src)(db, {"users": [{"tenant_id": "tenant-1"}, {"tenant_id": "tenant-1-a1"}]})
    ids = set(o.kw["id"] for o in db.added)
    assert {"default", "tenant-1", "tenant-1-a1"} <= ids


def test_default_alone_when_the_seed_says_nothing(seed_src):
    """#1105's case is unchanged."""
    db = _DB()
    _load(seed_src)(db, None)
    assert [o.kw["id"] for o in db.added] == ["default"]


def test_a_user_without_a_tenant_adds_nothing_extra(seed_src):
    db = _DB()
    _load(seed_src)(db, {"users": [{"email": "a@x.io"}]})
    assert [o.kw["id"] for o in db.added] == ["default"]


def test_an_existing_tenant_is_left_alone(seed_src):
    """Idempotent: it runs on every boot."""
    db = _DB(existing={"default", "tenant1"})
    _load(seed_src)(db, {"users": [{"tenant_id": "tenant1"}]})
    assert db.added == [] and db.commits == 0


def test_the_row_uses_the_columns_the_model_has(seed_src):
    db = _DB()
    _load(seed_src)(db, {"users": [{"tenant_id": "t9"}]})
    row = next(o for o in db.added if o.kw["id"] == "t9")
    assert set(row.kw) <= {"id", "name", "status"}
    assert row.kw["name"] == "t9"


def test_it_still_runs_before_the_first_insert(seed_src):
    """#1105's ordering requirement: users are first in _ORDER and cannot land
    without their tenant."""
    # ORDER, not adjacency: #1112 put `_pk_remap = {}` between the two, and pinning
    # them as neighbours failed on a change that kept the guarantee intact.
    guard = seed_src.index("_ensure_default_tenant(db, data)")
    loop = seed_src.index("for t in _ORDER:", guard)
    assert guard < loop, "the tenant guard must run before the insert loop"


def test_a_missing_tenant_model_is_not_an_error(seed_src):
    tree = ast.parse(seed_src)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)
           and n.name in {"_ensure_default_tenant", "_ensure_one_tenant"}]
    ns = {"models": types.SimpleNamespace(), "_seed_dbg": lambda *a: None}
    exec(compile(ast.Module(body=fns, type_ignores=[]), "seed_data.py", "exec"), ns)
    db = _DB()
    ns["_ensure_default_tenant"](db, {"users": [{"tenant_id": "t"}]})
    assert db.added == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
