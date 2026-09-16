"""FIX #119 — custom-route path-param annotations are corrected against the PROJECTED
route's signature (instagram-core-di run-35 M4 STUCK, 2026-07-09 00:0x, live-diagnosed).

run-35 aborted on `business_endpoints_reachable: GET /api/users/{username} → 500`.
Live forensics on the still-up containers: the contract declares
GET /api/users/{username} (STRING semantic); the framework PROJECTION renders it
correctly (`username: str`, queries by username) — but the lane's custom_routes.py
twin annotated **`username: int`**, and the custom router overrides the projected
route by design, so every real username 422/500'd. This is FIX #106's MIRROR
(there: `str` on an integer PK; here: `int` on a string-keyed param). #106's
table-PK heuristic cannot see this case — but the projected signature is the
contract-derived source of truth for BOTH directions. Repair: for each custom route
whose (method, path-template) exactly matches a projected route in main.py, rewrite
any path-param annotation that differs from the projection's. AST-anchored surgical
edit, parse-guarded, idempotent. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_scaffold import (  # noqa: E402
    repair_custom_routes_param_types_vs_projection)

_MAIN = '''\
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/users/{username}")
def _projected_get_api_users_username_8(username: str):
    return {"item": {"username": username}}

@app.get("/api/posts/{id}")
def _projected_get_api_posts_id_3(id: int):
    return {"item": {"id": id}}
'''

_CUSTOM = '''\
from fastapi import APIRouter
router = APIRouter()

@router.get("/api/users/{username}")
def get_user_profile(username: int):
    return {"user": username}

@router.get("/api/posts/{id}")
def get_post(id: str):
    return {"post": id}

@router.get("/api/reels/{reel_id}")
def get_reel(reel_id: str):
    return {"reel": reel_id}
'''


def _mk(tmp_path, main_src=_MAIN, custom_src=_CUSTOM):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "main.py").write_text(main_src, encoding="utf-8")
    (be / "custom_routes.py").write_text(custom_src, encoding="utf-8")
    # #1202pk: narrowing str -> int needs models.py to show an integer PK
    (be / "models.py").write_text(
        'class Post(Base):\n    __tablename__ = "posts"\n'
        '    id = Column(Integer, primary_key=True)\n', encoding="utf-8")
    return be


def test_both_directions_corrected_against_projection(tmp_path):
    be = _mk(tmp_path)
    out = repair_custom_routes_param_types_vs_projection(be)
    assert out.get("fixed") == 2
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "def get_user_profile(username: str):" in src      # run-35's exact bug
    assert "def get_post(id: int):" in src                     # the #106 direction
    assert "def get_reel(reel_id: str):" in src                # no projected twin → untouched
    import ast
    ast.parse(src)
    # idempotent
    assert repair_custom_routes_param_types_vs_projection(be).get("fixed") == 0


def test_matching_annotations_untouched(tmp_path):
    be = _mk(tmp_path, custom_src=_CUSTOM
             .replace("username: int", "username: str")
             .replace("id: str", "id: int"))
    before = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert repair_custom_routes_param_types_vs_projection(be).get("fixed") == 0
    assert (be / "custom_routes.py").read_text(encoding="utf-8") == before


def test_method_mismatch_not_confused(tmp_path):
    # a POST custom route must not be corrected against a GET projection
    custom = ('from fastapi import APIRouter\nrouter = APIRouter()\n\n'
              '@router.post("/api/users/{username}")\n'
              'def act(username: int):\n    return {}\n')
    be = _mk(tmp_path, custom_src=custom)
    assert repair_custom_routes_param_types_vs_projection(be).get("fixed") == 0


def test_graceful_without_files(tmp_path):
    be = tmp_path / "backend"
    be.mkdir()
    assert isinstance(repair_custom_routes_param_types_vs_projection(be), dict)


def test_wired_into_heal_pipeline():
    import inspect
    from multi_agent.runtime import heal_pipeline
    assert "repair_custom_routes_param_types_vs_projection" in inspect.getsource(heal_pipeline)


def test_fix125_wired_into_validation_runner_cleanboot():
    """FIX #125 (run-43 M3 STUCK, live): #119's param-vs-projection repair fixed the
    live artifact standalone (fixed=2) but never fired in the run — it was wired into
    tools/docker_tools._run_compose (#121) and heal, but the FRAMEWORK VALIDATION
    build goes through validation_runner's OWN _compose clean-boot, which only staged
    assets (#113). So the framework validation kept building an image with the lane's
    `username: int` on a string-keyed route → GET /api/users/{username} 422/500 →
    business_endpoints_reachable wedged. The clean-boot must run the param repair too
    (same build-input floor as #113)."""
    import inspect
    from multi_agent.runtime import validation_runner
    src = inspect.getsource(validation_runner)
    assert "repair_custom_routes_param_types_vs_projection" in src
    # and it must be applied to app/backend before the build
    assert 'app' in src and 'backend' in src
