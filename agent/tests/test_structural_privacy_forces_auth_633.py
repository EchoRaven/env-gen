r"""#633: a private table became a PUBLIC DUMP whenever the contract forgot `auth_required`.

Found by auditing the delivered backends of all 45 kept runs. Four of them ship this, verbatim:

    @app.get("/api/search")
    def _projected_get_api_search_9(q: str = "", db=Depends(get_db)):    # no actor
        query = db.query(ContinueWatching)                               # no filter
        ...
        return {"items": [... "user_id" ... "progress_seconds" ... for r in rows]}

Unauthenticated, unfiltered, 50 rows of every account's watch progress. r101, r106, r109, r119.

It is LIVE, not historical: projecting that shape with today's code reproduced it exactly. #569
fixed WHICH table a bare `/api/search` resolves to; it did not make that table's privacy hold.

The cause is an ordering one. #566y and #598 established that a table's SHAPE settles privacy —
a sub-entity owner (`profile_id → profiles → users`), or a direct user FK alongside a content FK
(`my_list.user_id` + `my_list.title_id`). Both are computed INSIDE `_generate_handler`, but the
force-auth decision is made by the CALLER, before it:

    auth  = resolve_endpoint_auth(...) or _owner_scoped   # _owner_scoped: CONTRACT only
    ...
    owner_fk = _owner_fk(meta) if auth else None          # auth False -> no owner column
    read_scoped = bool(owner_fk) and (...)                # -> False -> no filter at all

So the two signals whose entire purpose is "do not wait for the contract" could never fire on an
endpoint the contract left unauthenticated. Asking the same structural question at the caller is
the fix; #598's discriminator keeps a public feed public.
"""
import os
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _structurally_private_resource_633 as private,
    project_missing_routes,
)

_MAIN = 'from fastapi import FastAPI, Depends\napp = FastAPI()\n\nif __name__ == "__main__":\n    pass\n'

_PRIVATE = """
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base
class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title_id = Column(Integer, ForeignKey("titles.id"))
    note = Column(String)
"""

_PUBLIC_FEED = """
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base
class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(String)
"""


def _project(models_src, endpoint):
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "models.py"), "w").write(models_src)
        open(os.path.join(td, "main.py"), "w").write(_MAIN)
        project_missing_routes(td, [endpoint])
        src = open(os.path.join(td, "main.py")).read()
    i = src.find(f'@app.{endpoint["method"].lower()}("{endpoint["path"]}")')
    assert i != -1, "endpoint was not projected"
    nxt = src.find("@app.", i + 10)
    return src[i:nxt if nxt > 0 else len(src)]


def _scoped(block):
    return ("user=Depends(get_current_user)" in block) and ("_fw_owner_val" in block)


_SEARCH_PUBLIC = {"method": "GET", "path": "/api/search", "auth_required": False,
                  "schema": {"types": {"note": "string", "body": "string"}}}


# --- the leak, closed ------------------------------------------------------------------------

def test_an_unauthenticated_search_over_a_private_table_is_now_scoped():
    """The exact shape r101/r106/r109/r119 shipped."""
    assert _scoped(_project(_PRIVATE, _SEARCH_PUBLIC))


def test_it_holds_even_when_the_contract_declares_the_read_public():
    """`auth_required=False` and "per-user-private" are contradictory; a private read is
    unscopable without an actor. Same precedent the contract-flag path already sets."""
    block = _project(_PRIVATE, _SEARCH_PUBLIC)
    assert "user=Depends(get_current_user)" in block


def test_an_unstated_contract_is_scoped_too():
    ep = {"method": "GET", "path": "/api/search", "schema": {"types": {"note": "string"}}}
    assert _scoped(_project(_PRIVATE, ep))


def test_a_plain_collection_read_of_a_private_table_is_scoped():
    ep = {"method": "GET", "path": "/api/continue-watching", "auth_required": False}
    assert _scoped(_project(_PRIVATE, ep))


# --- what must stay public ---------------------------------------------------------------------

def test_a_public_feed_is_untouched():
    """`posts(user_id, body)` — a user FK and NO content FK. #598's discriminator, unchanged."""
    block = _project(_PUBLIC_FEED, _SEARCH_PUBLIC)
    assert "user=Depends(get_current_user)" not in block
    assert "_fw_owner_val" not in block


def _models(src):
    """Load through the REAL loader — a hand-built meta dict is a guess at an internal shape,
    and guessing at one is how the measurement in #627 went wrong twice."""
    from pathlib import Path
    from env_generator.llm_generator.multi_agent.runtime.route_projector import _orm_models
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "models.py"), "w").write(src)
        return _orm_models(Path(td))


def test_the_predicate_separates_the_two_shapes():
    assert private("GET", "/api/continue-watching", _models(_PRIVATE)) is True
    assert private("GET", "/api/posts", _models(_PUBLIC_FEED)) is False


def test_the_predicate_rescues_a_bare_search_path_the_same_way():
    """`/api/search` names no resource; the search resolver finds the table, and privacy must
    follow it there — that is the shape all four leaks took."""
    assert private("GET", "/api/search", _models(_PRIVATE)) is True
    assert private("GET", "/api/search", _models(_PUBLIC_FEED)) is False


def test_a_path_with_no_resolvable_model_is_not_private():
    assert private("GET", "/api/nothing-here", {}) is False


def test_it_never_raises_on_a_malformed_model_map():
    assert private("GET", "/api/x", {"x": None}) is False
    assert private("GET", "/api/x", None) is False


# --- where the decision has to live ----------------------------------------------------------

def test_the_question_is_asked_before_the_auth_decision():
    """The whole defect was ordering: the structural signals were computed after the auth
    decision they should inform."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
    src = inspect.getsource(rp.project_missing_routes)
    # #1202og: read CODE, not prose — a comment that QUOTED the auth line made `src.index`
    # find the quote first and this probe went red on a correctly-ordered file.
    src = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert (src.index("_structurally_private_resource_633(method, path, models)")
            < src.index("auth = resolve_endpoint_auth("))


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
    flat = " ".join(inspect.getsource(rp._structurally_private_resource_633).split())
    assert "4 of them ship" in flat
    assert "LIVE defect, not a historical" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
