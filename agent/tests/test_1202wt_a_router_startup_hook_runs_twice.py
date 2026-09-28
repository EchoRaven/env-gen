"""#1202wt: a lane startup hook on an APIRouter runs twice, so one that writes writes twice.

MEASURED on FastAPI 0.121.0:

    a startup handler on an APIRouter + include_router once  -> fires 2x
                                        include_router twice -> fires 4x
    the same handler on the app                              -> fires 1x

and the generated `main.py` includes `_as_router` twice -- bare, then with `prefix="/api"`.

So a lane hook that inserts rows inserts them twice: the shape of #1202uu's duplicated media
rows, arriving from a different direction. Across the corpus 46 of 150 runs register a lane
`on_event` (66 hooks); 8 of those, in 7 runs, write -- `backfill_video_sound_ids_from_seeded
_sound_names`, `ensure_reference_seed_rows`, `_ensure_runtime_contract_columns` and
siblings, the most recent r122. None is known to have doubled anything, because the ones
that survive are check-then-insert; that is luck, not design.

Reports, never blocks, and only for hooks that WRITE: a hook that reorders routes is
harmless run twice, and flagging all 66 would be noise nobody reads.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    router_startup_writes_twice_1202wt,
)


def _backend(tmp_path, body):
    (tmp_path / "custom_routes.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_writing_router_hook_is_reported(tmp_path):
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from fastapi import APIRouter
router = APIRouter()

@router.on_event("startup")
def seed_rows():
    db.add(Thing())
    db.commit()
"""))
    assert len(out) == 1, out
    assert "seed_rows" in out[0] and "router" in out[0]


def test_an_app_level_hook_is_not_reported(tmp_path):
    """The app runs it once; there is nothing to warn about."""
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
app = FastAPI()

@app.on_event("startup")
def seed_rows():
    db.add(Thing())
    db.commit()
"""))
    assert out == [], out


def test_a_router_hook_that_writes_nothing_is_not_reported(tmp_path):
    """Reordering routes twice is the same as reordering them once."""
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from fastapi import APIRouter
router = APIRouter()

@router.on_event("startup")
def promote_routes():
    app = _running_app()
    app.router.routes = sorted(app.router.routes, key=_rank)
"""))
    assert out == [], out


def test_a_write_in_a_LATER_function_is_not_attributed(tmp_path):
    """★ The regression this was shipped with.

    The first draft sliced the body by regex, cutting at the next decorator. In r136 that
    swallowed 17,191 characters and twelve further functions and matched an `INSERT INTO`
    270 lines below the hook, so two of six reported runs were route-reordering hooks that
    write nothing. The AST bounds the function; a text window does not.
    """
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from fastapi import APIRouter
router = APIRouter()

@router.on_event("startup")
def promote_routes():
    app = _running_app()
    app.router.routes = sorted(app.router.routes, key=_rank)


def some_other_helper(db):
    db.execute("INSERT INTO things VALUES (1)")
    db.commit()
"""))
    assert out == [], (
        "a write in a different function was attributed to the hook: %r" % out)


def test_a_shutdown_hook_is_not_a_startup_hook(tmp_path):
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from fastapi import APIRouter
router = APIRouter()

@router.on_event("shutdown")
def flush():
    db.commit()
"""))
    assert out == [], out


def test_raw_sql_counts_as_a_write(tmp_path):
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from fastapi import APIRouter
router = APIRouter()

@router.on_event("startup")
def backfill():
    conn.execute("insert into videos (sound_id) values (1)")
"""))
    assert len(out) == 1, out


def test_a_missing_or_unparseable_file_is_silent(tmp_path):
    assert router_startup_writes_twice_1202wt(tmp_path) == []
    (tmp_path / "custom_routes.py").write_text("def broken(:\n", encoding="utf-8")
    assert router_startup_writes_twice_1202wt(tmp_path) == []


def test_an_unknown_holder_is_not_guessed(tmp_path):
    """A holder this file never constructs could be either; say nothing rather than guess."""
    out = router_startup_writes_twice_1202wt(_backend(tmp_path, """
from .shared import mystery

@mystery.on_event("startup")
def seed():
    db.add(Thing())
    db.commit()
"""))
    assert out == [], out
