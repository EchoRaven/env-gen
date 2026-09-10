"""#1202jd: a cross-actor denial probe on a WRITE the projected handler cannot deny.

A projected write owner-checks by comparing the row's OWNER COLUMN against the caller. A table
with no owner column has nothing to compare, so the handler serves every authenticated caller
and a step demanding 401/403 from an intruder token can never pass. Verified directly:
projecting `PUT /api/sounds/{id}` with owner_scoped True and False emits the SAME handler,
because `read_scoped = bool(owner_fk) and ...` — marking such a table is inert.

r111 spent four hours and $762 with exactly this as its last blocker.

WRITES ONLY, and that is what makes rejecting safe. #77 records that a cross-user PUT/DELETE
denial is deliberately NOT used to infer read-scoping ("it proves only WRITE authz, which is
true for PUBLIC resources too"), so refusing one cannot starve
`_isolation_scoped_tables_from_chains` — that mechanism reads cross-user GET denials.

TWO ROOT CAUSES, separated because the repairs point opposite ways: a table that genuinely has
no owner, and a table registered with an EMPTY column schema (#568) whose model therefore
carries only a primary key. Telling a #568 lane "your table has no owner column" sends it to
add one the table already declares.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    unenforceable_owner_denials_1202jd as _flag)


def _tables(**specs):
    """The shape RegistryHub stores: keyed by id, `name` inside, columns as dicts."""
    return {f"tbl_{n}": {"name": n, "schema": {"columns": [{"name": c} for c in cols]}}
            for n, cols in specs.items()}


_TABLES = _tables(
    sounds=["id", "name", "author", "video_count"],      # `author` is free text, not an FK
    videos=["id", "author_id", "caption"],               # has an owner
    my_list=["id"],                                      # #568 degenerate
)


def _step(method="PUT", path="/api/sounds/${sound_id}",
          auth="__chain_intruder_token", expect=(401, 403, 404)):
    return {"method": method, "path": path, "auth": auth, "expect": list(expect)}


def test_the_r111_blocker_is_named():
    got = _flag([_step()], _TABLES)
    assert got == [(0, "PUT /api/sounds/${sound_id}", "sounds", "no_owner")], got


def test_a_degenerate_table_gets_its_own_verdict():
    got = _flag([_step(method="DELETE", path="/api/my-list/${id}")], _TABLES)
    assert got == [(0, "DELETE /api/my-list/${id}", "my_list", "degenerate")], got


def test_a_table_that_can_deny_is_left_alone():
    """66 of the 78 cross-actor write probes in the corpus are this. A false positive here
    rejects a chain that was testing exactly what it should."""
    assert _flag([_step(path="/api/videos/${id}")], _TABLES) == []


def test_reads_are_never_touched():
    """THE load-bearing exemption. #77 infers read-scoping FROM a cross-user GET denial —
    that probe is the framework's INPUT for learning a table is private, and rejecting it
    would remove the mechanism. Only writes are judged here."""
    for m in ("GET", "HEAD"):
        assert _flag([_step(method=m, path="/api/sounds/${id}")], _TABLES) == []


def test_an_unauthenticated_probe_is_satisfiable():
    """The step r111's verifier eventually wrote for itself. The projected handler carries
    Depends(get_current_user), so an anonymous write DOES get 401 — nothing to reject."""
    assert _flag([_step(auth=None)], _TABLES) == []
    assert _flag([_step(auth="token")], _TABLES) == []


def test_a_mixed_expectation_belongs_to_591():
    assert _flag([_step(expect=(200, 403))], _TABLES) == []


def test_post_is_exempt():
    assert _flag([_step(method="POST", path="/api/sounds")], _TABLES) == []


def test_an_unresolvable_path_says_nothing():
    assert _flag([_step(path="/api/unknown-thing/${id}")], _TABLES) == []
    assert _flag([_step()], {}) == []


def test_control_plane_paths_are_exempt():
    assert _flag([_step(path="/auth/sounds/${id}")], _TABLES) == []
    assert _flag([_step(path="/api/v1/sounds/${id}")], _TABLES) == []


def test_the_call_site_reads_the_store_not_the_store_object():
    """`RegistryHub._tables` is a JsonStore. The first draft passed the store itself and every
    chain registration raised `AttributeError: 'JsonStore' object has no attribute 'items'` —
    70 failures I first misread as a design flaw, because I reached for an explanation instead
    of the traceback. Pinned so the wrong accessor cannot come back quietly."""
    src = (_AGENT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "registryhub.py").read_text(encoding="utf-8")
    assert "unenforceable_owner_denials_1202jd(norm, self._tables.value()" in src, \
        "the call site must pass the store's VALUE, not the store"
