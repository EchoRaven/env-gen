r"""#1202u: a seed row whose parent never landed attaches to a parent that did.

#1202r made the loss visible; this stops it. Measured against the live delivered databases:

    r26   continue_watching 8->1   my_list 8->1   ratings 8->1   profiles 8->5
    r30   genres 10->0   title_genres 15->0   my_list 22->2   ratings 14->7

The chain: a parent row fails its insert, so #1112 records no pk-remap entry for it, so every
child still carrying the parent's PRE-assignment id violates its FK and the per-row SAVEPOINT
(#218) drops it — silently, since `_seed_dbg` prints only under FW_DEBUG. r26's
continue_watching rows all name `profile_id: 1` while the profiles that survived took 26-30.
r26 delivers a Netflix whose Continue Watching rail can never fill.

The seeder ALREADY has the right policy and applies it one case too narrowly: `_real_owner_ids`
points an owner column at ids that exist — but only when the column is EMPTY. A seed that spells
out `profile_id: 1` skips it and dies. This extends the same policy to an explicit FK.

Only rows that were going to be DROPPED change: the fallback fires solely when the value names
no live parent. A demo row attached to a different real parent is worth more than no row.
"""

import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402


def _seeder(tmp_path):
    (tmp_path / "app" / "backend").mkdir(parents=True, exist_ok=True)
    write_backend_skeleton(
        tmp_path, [{"method": "GET", "path": "/api/profiles", "metadata": {}}],
        {"users": {"columns": [{"name": "id", "type": "integer"}]},
         "profiles": {"columns": [{"name": "id", "type": "integer"},
                                  {"name": "user_id", "type": "integer"}]}})
    return (tmp_path / "app" / "backend" / "seed_data.py").read_text(encoding="utf-8")


def _load(src, ids_by_table):
    start = src.index("def _live_parent_ids_1202u")
    end = src.index("\ndef ", start + 1)

    class _Col:
        def __init__(self, vals): self.vals = vals

    class _Q:
        def __init__(self, vals): self.vals = vals
        def all(self): return [(v,) for v in self.vals]

    class _DB:
        def query(self, col): return _Q(col.vals)

    class _M:
        pass
    for t, vals in ids_by_table.items():
        setattr(_M, t.title(), type(t.title(), (), {"id": _Col(vals)}))

    ns = {"models": _M,
          "_CLASS": {t: t.title() for t in ids_by_table},
          "_PK": {t: ["id"] for t in ids_by_table}}
    exec(compile(src[start:end], "<projected>", "exec"), ns)
    return ns["_live_parent_ids_1202u"], _DB()


def test_it_reports_the_ids_that_exist(tmp_path):
    fn, db = _load(_seeder(tmp_path), {"profiles": [26, 27, 28, 29, 30]})
    assert fn(db, "profile_id", {}) == [26, 27, 28, 29, 30]


def test_an_unknown_column_yields_nothing_so_the_row_is_left_alone(tmp_path):
    """No parent table -> no opinion. The row keeps whatever the seed said."""
    fn, db = _load(_seeder(tmp_path), {"profiles": [1]})
    assert fn(db, "external_vendor_id", {}) == []


def test_the_result_is_cached_per_column(tmp_path):
    fn, db = _load(_seeder(tmp_path), {"profiles": [26]})
    cache = {}
    assert fn(db, "profile_id", cache) == [26]
    assert cache["profile_id"] == [26]


def test_a_dead_session_is_survivable(tmp_path):
    fn, _db = _load(_seeder(tmp_path), {"profiles": [26]})

    class _Angry:
        def query(self, col): raise RuntimeError("closed")

    assert fn(_Angry(), "profile_id", {}) == []


def test_the_fallback_only_fires_for_an_id_that_no_parent_has(tmp_path):
    """The projected guard, read as written: remap first, fallback only if still unmatched."""
    src = _seeder(tmp_path)
    body = src[src.index("def seed_if_empty():"):]
    guard = body[body.index("_live_parent_ids_1202u(db, _fkc"):]
    guard = guard[:guard.index("_orig_pk")]
    assert "row.get(_fkc) not in _live" in guard
    assert "if _live and" in guard          # no live parents -> leave the row untouched


def test_it_runs_after_the_1112_remap_and_before_the_insert(tmp_path):
    src = _seeder(tmp_path)
    b = src[src.index("def seed_if_empty():"):]
    assert b.index("_pk_remap.get(_cand)") < b.index("_live_parent_ids_1202u(db, _fkc") \
        < b.index("_obj = cls(")
