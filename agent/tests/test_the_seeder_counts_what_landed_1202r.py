r"""#1202r: the projected seeder counts what actually landed and says when it is short.

Every insert is wrapped in a SAVEPOINT (#218) so one bad row does not take its table down, and
a row that still fails is dropped through `_seed_dbg`, which prints nothing unless FW_DEBUG is
set. The result is a silent shortfall — and it is not rare. Measured against the LIVE delivered
databases of 13 runs:

    r26 (DELIVERED)  continue_watching 8->1   my_list 8->1   ratings 8->1   profiles 8->5
    r30 (DELIVERED)  genres 10->0   title_genres 15->0   my_list 22->2   ratings 14->7
    r25              my_list 8->0
    r16-r24, r27     clean

The chain: some parent rows fail, so they never get a #1112 pk-remap entry, so every child
pointing at them violates its FK and is dropped too. r26 ships a Netflix whose Continue Watching
rail can never fill, and every delivery gate passed it.

The framework HAS an audit for this and it has never run: across r22-r26 and r30 the live row
count succeeded 0 times, and its fallback filter examines 0 tables in 145 of 147 runs (that
number is seed_audit's own comment). #1202q removed one structural reason; this removes the need
for that audit to be reachable at all — the session is open and the declared counts are in scope,
so the seeder can check itself.

Reports; never raises. A seeder that died on its own bookkeeping would be worse than the silence.
"""

import io
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import write_backend_skeleton  # noqa: E402


def _projected_seeder(tmp_path):
    eps = [{"method": "GET", "path": "/api/profiles", "metadata": {"response_key": "items"}}]
    tbls = {"users": {"columns": [{"name": "id", "type": "integer"}]},
            "profiles": {"columns": [{"name": "id", "type": "integer"},
                                     {"name": "user_id", "type": "integer"}]}}
    (tmp_path / "app" / "backend").mkdir(parents=True)
    write_backend_skeleton(tmp_path, eps, tbls)
    return (tmp_path / "app" / "backend" / "seed_data.py").read_text(encoding="utf-8")


def _load_checker(src, counts):
    """Exec just the checker with fakes standing in for the app's models and session."""
    start = src.index("def _verify_seed_counts_1202r")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]

    class _Q:
        def __init__(self, n): self.n = n
        def count(self): return self.n

    class _DB:
        def query(self, cls): return _Q(counts[cls.__name__])

    class _M:  # a models module holding one class per table
        pass
    for t, cname in (("users", "User"), ("profiles", "Profile")):
        setattr(_M, cname, type(cname, (), {}))

    err = io.StringIO()
    ns = {"_ORDER": ["users", "profiles"], "_CLASS": {"users": "User", "profiles": "Profile"},
          "models": _M, "_sys": type("S", (), {"stderr": err})()}
    exec(compile(body, "<projected>", "exec"), ns)
    return ns["_verify_seed_counts_1202r"], _DB(), err


def test_a_shortfall_is_reported(tmp_path):
    src = _projected_seeder(tmp_path)
    fn, db, err = _load_checker(src, {"User": 5, "Profile": 1})
    fn(db, {"users": [{}] * 5, "profiles": [{}] * 8})
    out = err.getvalue()
    assert "SEED SHORTFALL (#1202r)" in out
    assert "profiles 8->1" in out
    assert "users" not in out.split("--")[1]      # users landed in full, not named


def test_a_complete_seed_says_nothing(tmp_path):
    src = _projected_seeder(tmp_path)
    fn, db, err = _load_checker(src, {"User": 5, "Profile": 8})
    fn(db, {"users": [{}] * 5, "profiles": [{}] * 8})
    assert err.getvalue() == ""


def test_more_rows_than_declared_is_not_a_shortfall(tmp_path):
    """Runtime and test-user rows land on top of the seed; that is not a defect."""
    src = _projected_seeder(tmp_path)
    fn, db, err = _load_checker(src, {"User": 31, "Profile": 8})
    fn(db, {"users": [{}] * 5, "profiles": [{}] * 8})
    assert err.getvalue() == ""


def test_it_never_raises(tmp_path):
    src = _projected_seeder(tmp_path)
    fn, _db, err = _load_checker(src, {"User": 1, "Profile": 1})

    class _Angry:
        def query(self, cls): raise RuntimeError("session closed")

    fn(_Angry(), {"profiles": [{}] * 8})          # a dead session must not break seeding
    fn(None, None)
    fn(object(), {"profiles": "not-a-list"})


def test_the_call_is_wired_into_the_projected_seeder(tmp_path):
    src = _projected_seeder(tmp_path)
    assert "_verify_seed_counts_1202r(db, data)" in src
    # It runs while the session is still open. Scope the check to seed_if_empty's own body
    # (#943: a landmark, not a file-wide index — `db.close()` occurs in earlier functions too).
    body = src[src.index("def seed_if_empty():"):]
    call = body.index("_verify_seed_counts_1202r(db, data)")
    assert body.index("_store_fingerprint(db, fp)") < call < body.index("db.close()")
