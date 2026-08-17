r"""#587: a failing chain step never said WHO owns the route it failed on.

`classify_endpoint_failure` can call a failure a framework defect only when it sees a 5xx WITH a
`_projected_` traceback ("narrow on purpose", #272). Three real defects this arc were **2xx with
no traceback at all**: `GET /api/my-list` and `GET /api/continue-watching` returning ANOTHER
account's rows from an unscoped projected read (#566y, #568). Each surfaced as "DENIAL-PROBE got
success", was classified `broken`, and was dispatched to the LANE — whose own correct handler was
shadowed and who cannot edit `main.py`.

`backend_audit` already states the principle (FIX #201: a projected stub is one "the lane CANNOT
edit", so telling it to replace the handler is non-actionable). The chain executor just had no
way to know which routes those are — until now: `run_chains` already receives `project_dir`.

Annotation only, deliberately NOT reclassification: turning a 4xx/2xx on a projected route into
a framework defect would route genuine app bugs away from the lane and leave them unowned.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _projected_owner_note as note,
    projected_routes,
)

_MAIN = '''
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/my-list")
def _projected_get_api_my_list_9(db=None, user=None):
    return {"items": []}

@app.get("/api/titles/{id}")
def _projected_get_api_titles_id_3(id, db=None):
    return {"item": {}}

@app.post("/api/my-list", status_code=201)
def _projected_post_api_my_list_10(body=None, db=None, user=None):
    return {"item": {}}

@app.get("/api/search")
def lane_authored_search(q: str = ""):
    return {"items": []}
'''


def _proj(tmp_path):
    b = tmp_path / "app" / "backend"
    b.mkdir(parents=True)
    (b / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def test_projected_routes_are_discovered_including_decorator_args(tmp_path):
    got = projected_routes(_proj(tmp_path))
    assert ("GET", "/api/my-list") in got
    assert ("POST", "/api/my-list") in got          # status_code=201 in the decorator
    assert ("GET", "/api/titles/{id}") in got


def test_a_lane_authored_route_is_not_claimed(tmp_path):
    got = projected_routes(_proj(tmp_path))
    assert ("GET", "/api/search") not in got
    assert note(got, "GET", "/api/search") == ""


def test_the_r568_leak_route_is_annotated(tmp_path):
    got = projected_routes(_proj(tmp_path))
    n = note(got, "GET", "/api/my-list")
    assert "FRAMEWORK-PROJECTED" in n and "lane cannot edit it" in n


def test_a_concrete_id_matches_the_emitted_param_shape(tmp_path):
    got = projected_routes(_proj(tmp_path))
    assert "FRAMEWORK-PROJECTED" in note(got, "GET", "/api/titles/7")


def test_a_query_string_does_not_defeat_the_match(tmp_path):
    got = projected_routes(_proj(tmp_path))
    assert "FRAMEWORK-PROJECTED" in note(got, "GET", "/api/my-list?profile_id=9")


def test_the_framework_auth_surface_stays_the_lanes(tmp_path):
    """`POST /auth/login` is served by the embedded AS, not the projector — the one
    app-level failure found in this arc's data must keep its owner."""
    got = projected_routes(_proj(tmp_path))
    assert note(got, "POST", "/auth/login") == ""


def test_a_verb_mismatch_is_not_annotated(tmp_path):
    got = projected_routes(_proj(tmp_path))
    assert note(got, "DELETE", "/api/my-list") == ""


def test_missing_or_unreadable_main_is_inert(tmp_path):
    assert projected_routes(tmp_path) == set()
    assert note(set(), "GET", "/api/my-list") == ""


def test_it_annotates_rather_than_reclassifies():
    """Guard the deliberate choice: the classifier must be untouched."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce.classify_endpoint_failure)
    assert "projected_routes" not in src and "_projected_owner_note" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
