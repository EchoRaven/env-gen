"""#1202jt: a projected handler kept the auth guard it was born with.

#1202ic named the mechanism while fixing it for param types — "a handler emitted once is never
revisited, so the param type it was born with outlives the column it was derived from". The
same sentence was true of the auth guard and nothing re-derived it.

Measured over the 20 runs since #1202ga: 20 projected handlers serve anonymously while their
contract requires auth, and 18 of the 20 carry `schema=True, metadata=False` — the mirror
frozen at registration says PUBLIC, so the handler was projected open and was RIGHT to be, and
the contract was flipped afterwards. googlemaps-r16 is the case: `GET /api/titles`,
`/api/genres`, `/api/search`, `/api/transit-stops/{stop_id}` all emitted as
`(db=Depends(get_db))` with no actor, while `custom_routes.py:3192` holds the lane's own
guarded route that #528 overrides. Verified on that run's real main.py: only CORSMiddleware,
no router-level dependency, nothing else guarding it.

The pass DOES NOT DECIDE AUTH — that is four interacting rules (#320, #1202ht, #633, #271) and
duplicating them here is the one-fact-many-emitters trap. It drops the stale handler so the
projection loop rebuilds it through the same code that built it the first time.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import inspect                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import route_projector as RP  # noqa: E402

_SRC = '''from fastapi import Depends
app = FastAPI()


@app.get("/api/titles")
def _projected_get_api_titles_19(db=Depends(get_db)):
    rows = db.query(Title).limit(100).all()
    return {"items": rows}


@app.get("/api/kept")
def _projected_get_api_kept_2(db=Depends(get_db)):
    return {"items": []}


@app.get("/api/lane-owned")
def lane_authored_titles(db=Depends(get_db)):
    return {"items": []}
'''


def _ep(method, path, *, mirror, schema):
    return {"method": method, "path": path,
            "metadata": {"auth_required": mirror},
            "schema": {"auth_required": schema}}


def test_a_handler_whose_contract_moved_is_dropped_for_rebuild():
    """★ googlemaps-r16's shape: registered public, flipped to auth, handler still open."""
    out, dropped = RP._reproject_stale_auth_1202jt(
        _SRC, [_ep("GET", "/api/titles", mirror=False, schema=True)])
    assert dropped and "/api/titles" in dropped[0], dropped
    assert "_projected_get_api_titles_19" not in out
    assert "@app.get(\"/api/titles\")" not in out
    assert "_projected_get_api_kept_2" in out, "only the moved endpoint is touched"


def test_an_unmoved_contract_leaves_the_file_byte_identical():
    out, dropped = RP._reproject_stale_auth_1202jt(
        _SRC, [_ep("GET", "/api/titles", mirror=True, schema=True)])
    assert dropped == [] and out == _SRC


def test_an_endpoint_that_never_mirrored_is_not_treated_as_moved():
    """No frozen mirror means there is nothing to have moved FROM — #1039's invariant."""
    out, dropped = RP._reproject_stale_auth_1202jt(
        _SRC, [{"method": "GET", "path": "/api/titles",
                "schema": {"auth_required": True}}])
    assert dropped == [] and out == _SRC


def test_lane_authored_routes_are_never_dropped():
    """Only `_projected_*` — the prefix `_generate_handler` stamps and no lane writes."""
    out, dropped = RP._reproject_stale_auth_1202jt(
        _SRC, [_ep("GET", "/api/lane-owned", mirror=False, schema=True)])
    assert dropped == [] and "lane_authored_titles" in out


def test_the_other_direction_moves_too():
    """auth → public is the r97 pain (#1202ga's own case), one field over: the guard the
    handler was born with outlives a contract that has since declared the read public."""
    src = _SRC.replace("def _projected_get_api_titles_19(db=Depends(get_db)):",
                       "def _projected_get_api_titles_19(db=Depends(get_db), "
                       "user=Depends(get_current_user)):")
    out, dropped = RP._reproject_stale_auth_1202jt(
        src, [_ep("GET", "/api/titles", mirror=True, schema=False)])
    assert dropped and "_projected_get_api_titles_19" not in out


def test_a_route_the_loop_cannot_rebuild_is_never_dropped():
    """★ Dropping without a rebuild DELETES an endpoint. The loop projects `/api/` and nothing
    else, so anything outside that prefix must be left alone — r111's moved set really does
    contain POST /auth/register and POST /auth/login."""
    src = _SRC + '''

@app.post("/auth/register")
def _projected_post_auth_register_9(db=Depends(get_db)):
    return {"ok": True}
'''
    out, dropped = RP._reproject_stale_auth_1202jt(
        src, [_ep("POST", "/auth/register", mirror=True, schema=False)])
    assert dropped == [], dropped
    assert "_projected_post_auth_register_9" in out


def test_it_runs_before_existing_routes_are_taken():
    """★ Reachability: dropping after `existing` is computed would leave the route 'already
    present' and the rebuild would never happen."""
    src = inspect.getsource(RP.project_missing_routes)
    i = src.index("_reproject_stale_auth_1202jt(")
    j = src.index("existing = _existing_routes(src)")
    assert i < j, "the drop must precede the existing-route census, or it is inert"


def test_it_does_not_decide_auth_itself():
    """One fact, one emitter: the auth rules stay in the loop that already applies them."""
    body = inspect.getsource(RP._reproject_stale_auth_1202jt)
    for rule in ("resolve_endpoint_auth", "_owner_scoped", "_structurally_private"):
        assert rule not in body, (
            f"{rule} belongs to the projection loop; recomputing it here would make two "
            "places decide auth and they would drift")


# --- the delete-without-rebuild hole --------------------------------------------------

def test_a_drop_is_never_written_without_its_rebuild(tmp_path):
    """★ `project_missing_routes` has two write paths. The second one — "nothing was missing
    but the types moved" — would carry the drops with no re-projection beside them, i.e. it
    would DELETE the endpoints instead of refreshing them.

    Under the loop's current skips (only `/api/` and `existing`, both accounted for) a drop
    always produces a re-projection, so that branch is unreachable with drops pending. An
    implicit invariant guarding a delete is the shape that bites; this pins the explicit
    fallback instead.
    """
    src = inspect.getsource(RP.project_missing_routes)
    i = src.index('what="retype_projected_params_1202ic"')
    head = src[src.index("elif _retyped_1202ic:"):i]
    assert "_src_predrop_1202jt" in head, (
        "the types-only write must fall back to the source as it stood BEFORE the drops")
    assert "if _reauth_1202jt else src" in head, (
        "and only when drops actually happened, so the no-drop path stays byte-identical")


def test_the_predrop_source_is_captured_before_the_drop():
    src = inspect.getsource(RP.project_missing_routes)
    assert (src.index("_src_predrop_1202jt = src")
            < src.index("_reproject_stale_auth_1202jt(src")), (
        "capturing it after the drop would make the fallback a no-op")
