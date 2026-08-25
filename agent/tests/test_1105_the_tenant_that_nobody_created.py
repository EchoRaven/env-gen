"""#1105: the seed backfills a tenant id, and nothing ever creates that tenant.

The spine makes ``users.tenant_id`` a ``ForeignKey("tenants.id"), nullable=False``, and
the seed loader fills it in for every user row::

    row.setdefault('tenant_id', 'default')

Nothing creates that tenant. The only writer of a ``tenants`` row is
``oauth_store.register_user``, which runs when somebody REGISTERS — long after seeding.
So every seeded user row dies on ``users_tenant_id_fkey``, is dropped by #218's per-row
savepoint, and the app comes up with no demo users at all.

Measured by booting all 84 delivered backends against a real Postgres and counting rows
WITHOUT registering: of the 59 runs whose ``seed_data.json`` carries users, **58 end
with zero users**, and in all 58 ``tenants`` is zero too. The single run that worked had
a tenants row from elsewhere. 29 of the 58 have a delivered milestone.

What that costs:

  * the demo login the loader's own docstring promises ("Demo users log in with password
    'password'") cannot work — there is no such user;
  * every seeded content row FKs to a user that does not exist, so any read that JOINs
    users returns nothing. instagram-run77 ships 4 posts, 4 comments and 12 likes, and
    its ``GET /api/posts`` — ``FROM posts p JOIN users u ON p.user_id = u.id`` — answers
    ``{"items": []}``. A delivered app with a permanently empty feed.

Verified on that run's own contract and lane code with this fix in place: users 0 → 5,
tenants 0 → 1, and the feed returns its 4 posts.

★ It has to run BEFORE the first insert, not merely somewhere in the loader: `users` is
first in `_ORDER` and everything after it FKs to `users`.
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

_TABLES = {
    "users": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "username", "type": "text"},
        {"name": "email", "type": "text"},
        {"name": "password_hash", "type": "text"},
        {"name": "tenant_id", "type": "text"}]}},
    "posts": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
        {"name": "caption", "type": "text"}]}},
}


@pytest.fixture(scope="module")
def seed_src(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed1105")
    write_backend_skeleton(out, [{"method": "GET", "path": "/api/posts"}], _TABLES)
    return (out / "app" / "backend" / "seed_data.py").read_text()


def test_the_loader_creates_the_tenant(seed_src):
    assert "def _ensure_default_tenant(db):" in seed_src
    ast.parse(seed_src)


def test_it_runs_before_the_first_insert(seed_src):
    """★ `users` is first in `_ORDER`; a tenant created afterwards is too late."""
    call = seed_src.index("_ensure_default_tenant(db)\n        for t in _ORDER:")
    assert call > 0, "the call must sit immediately before the insert loop"


def test_the_spine_still_declares_the_constraint_this_fixes(seed_src, tmp_path):
    """Pin the premise: if users.tenant_id stopped being a NOT NULL FK, this fix would
    be pointless and the next reader should see that stated."""
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/posts"}], _TABLES)
    models = (tmp_path / "app" / "backend" / "models.py").read_text()
    line = next(l for l in models.splitlines() if "tenant_id" in l and "Column" in l)
    assert 'ForeignKey("tenants.id")' in line
    assert "nullable=False" in line


# ── the helper's own behaviour, against a fake session ───────────────────────
def _load_helper(seed_src, models_mod, dbg):
    """exec just `_ensure_default_tenant` with the names it closes over."""
    tree = ast.parse(seed_src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_ensure_default_tenant")
    ns = {"models": models_mod, "_seed_dbg": dbg}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "seed_data.py", "exec"), ns)
    return ns["_ensure_default_tenant"]


class _Col:
    def __init__(self, name):
        self.name = name


class _Table:
    def __init__(self, names):
        self.columns = [_Col(n) for n in names]


def _tenant_cls(names):
    class Tenant:
        __table__ = _Table(names)

        def __init__(self, **kw):
            self.kw = kw
    return Tenant


class _DB:
    def __init__(self, existing=None, fail=False):
        self.existing, self.fail = existing, fail
        self.added, self.commits, self.rollbacks = [], 0, 0

    def get(self, cls, pk):
        return self.existing

    def add(self, obj):
        if self.fail:
            raise RuntimeError("boom")
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_it_inserts_the_default_tenant(seed_src):
    m = types.SimpleNamespace(Tenant=_tenant_cls(["id", "name", "status", "created_at"]))
    db = _DB()
    _load_helper(seed_src, m, lambda *a: None)(db)
    assert len(db.added) == 1 and db.commits == 1
    assert db.added[0].kw["id"] == "default"
    assert db.added[0].kw["name"] == "default"


def test_it_sets_only_columns_the_model_has(seed_src):
    """A tenants table without `status` must not get one — the insert would fail and
    take the whole point of the fix with it."""
    m = types.SimpleNamespace(Tenant=_tenant_cls(["id", "name"]))
    db = _DB()
    _load_helper(seed_src, m, lambda *a: None)(db)
    assert set(db.added[0].kw) == {"id", "name"}


def test_it_is_idempotent(seed_src):
    m = types.SimpleNamespace(Tenant=_tenant_cls(["id", "name"]))
    db = _DB(existing=object())
    _load_helper(seed_src, m, lambda *a: None)(db)
    assert db.added == [] and db.commits == 0


def test_no_tenant_model_is_not_an_error(seed_src):
    """A schema with no tenants table (sqlite fixtures, minimal contracts) must pass
    straight through — seeding still has to happen."""
    db = _DB()
    _load_helper(seed_src, types.SimpleNamespace(), lambda *a: None)(db)
    assert db.added == [] and db.rollbacks == 0


def test_a_failure_rolls_back_and_is_reported(seed_src):
    """It runs on the path to seeding everything else; it must not poison the session,
    and #218's own diagnostic must see it."""
    m = types.SimpleNamespace(Tenant=_tenant_cls(["id", "name"]))
    db = _DB(fail=True)
    seen = []
    _load_helper(seed_src, m, lambda where, exc: seen.append(where))(db)
    assert db.rollbacks == 1
    assert seen and "tenant" in seen[0]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
