"""FIX #23 — finish gate requires endpoint route CODE, not just registryhub status.

Instagram run #6: the backend called registryhub_register_endpoint(status='implemented')
58x with ZERO code writes — all 38 endpoints showed 'implemented' in RegistryHub while
the generated app had NO business routes (only the framework auth/spine scaffold),
so it could only fail validation. The kickoff_endpoints_implemented finish-gate
trusted the LLM-asserted status. endpoints_implemented_with_code adds a code-
presence layer: finish stays blocked until each owned endpoint's route actually
exists in the lane's source. Matching is lenient (resource token, not full path)
so router-prefix splitting never FALSE-blocks honest code — it only fires on the
egregious no-route case.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    endpoints_implemented_with_code,
    _collect_source_route_tokens,
    _endpoint_resource_token,
)


def _agent(endpoints, worktree, config_key="backend", tools=("write", "registryhub_register_endpoint")):
    # Default tools include write + registryhub_register_endpoint so the #58
    # satisfiability backstop (no write/register tools → no-op) passes through to
    # the real gate — i.e. these fixtures model the implementation lane, which has
    # both tools. Pass tools=() to model a lane that can't act on the gate.
    return SimpleNamespace(
        _config_key=config_key,
        _worktree_dir=str(worktree) if worktree is not None else None,
        _tool_instances={t: object() for t in tools},
        _hubs=SimpleNamespace(
            registryhub=SimpleNamespace(get_endpoints=lambda: endpoints)
        ),
    )


def _ep(method, path, status="implemented", provider="backend", kind=None):
    return {"method": method, "path": path, "status": status,
            "provider": provider, "kind": kind}


def test_token_extraction():
    assert _endpoint_resource_token("/api/posts") == "posts"
    assert _endpoint_resource_token("/api/posts/{id}/likes") == "likes"
    assert _endpoint_resource_token("/api/users/{username}/followers") == "followers"
    assert _endpoint_resource_token("/") is None


def test_kickoff_turn_does_not_block_finish(tmp_path):
    # PROPOSAL #58: in the KICKOFF turn the lane only DECLARES (it holds the kickoff-only
    # allowlist — no write/register_endpoint), so finish must NOT be blocked demanding an
    # implementation it cannot perform. User-reported deadlock: "I'm in the kickoff phase
    # with only kickoff tools, but finish() is blocked demanding I implement GET /api/v1/notes."
    (tmp_path / "main.py").write_text("app = FastAPI()\n")  # no route code yet
    a = _agent({"GET /api/v1/notes": _ep("GET", "/api/v1/notes", status="defined")}, tmp_path)
    a._active_phase = "kickoff"
    assert endpoints_implemented_with_code(a, "finish", {}) is None, "kickoff finish must not block on impl"
    # In the IMPLEMENTATION phase the same defined-without-code endpoint DOES block (gate works).
    a._active_phase = "implementation"
    assert endpoints_implemented_with_code(a, "finish", {}) is not None, "impl finish must still gate on real code"


def test_blocks_when_implemented_without_route_code(tmp_path):
    # The run #6 gaming case: status='implemented' but no route in source.
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    agent = _agent({"a": _ep("POST", "/api/posts")}, tmp_path)
    err = endpoints_implemented_with_code(agent, "finish", {})
    assert err is not None
    assert "no route handler" in err.lower()
    assert "POST /api/posts" in err


def test_passes_when_route_code_present(tmp_path):
    (tmp_path / "routes.py").write_text(
        '@router.post("/posts")\nasync def create_post():\n    return {}\n'
    )
    agent = _agent({"a": _ep("POST", "/api/posts")}, tmp_path)
    assert endpoints_implemented_with_code(agent, "finish", {}) is None


def test_passes_with_router_prefix_split(tmp_path):
    # router mounted at a prefix; the decorator path is just the suffix.
    (tmp_path / "posts.py").write_text(
        'router = APIRouter(prefix="/api/posts")\n'
        '@router.post("/{post_id}/likes")\nasync def like():\n    return {}\n'
    )
    agent = _agent({"a": _ep("POST", "/api/posts/{post_id}/likes")}, tmp_path)
    assert endpoints_implemented_with_code(agent, "finish", {}) is None


def test_skips_fixed_surface_kind(tmp_path):
    # auth/infra endpoints are runtime-owned, not lane-authored business routes.
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    agent = _agent({"a": _ep("POST", "/auth/login", kind="auth")}, tmp_path)
    assert endpoints_implemented_with_code(agent, "finish", {}) is None


def test_ignores_other_lanes_endpoints(tmp_path):
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    agent = _agent({"a": _ep("GET", "/api/feed", provider="frontend")},
                   tmp_path, config_key="backend")
    assert endpoints_implemented_with_code(agent, "finish", {}) is None


def test_vacuous_pass_when_no_worktree(tmp_path):
    agent = _agent({"a": _ep("POST", "/api/posts")}, None)
    assert endpoints_implemented_with_code(agent, "finish", {}) is None


def test_status_layer_still_blocks_nonterminal(tmp_path):
    # an endpoint still at 'defined' is caught by the underlying status gate.
    (tmp_path / "routes.py").write_text('@router.post("/posts")\n')
    agent = _agent({"a": _ep("POST", "/api/posts", status="defined")}, tmp_path)
    err = endpoints_implemented_with_code(agent, "finish", {})
    assert err is not None
    assert "terminal status" in err.lower() or "implemented" in err.lower()


def test_run6_scenario_many_missing(tmp_path):
    # 38 'implemented' endpoints, scaffold only (auth routes) → business ones block.
    (tmp_path / "oauth_routes.py").write_text('@router.post("/auth/login")\n')
    eps = {f"e{i}": _ep("GET", f"/api/resource{i}") for i in range(12)}
    agent = _agent(eps, tmp_path)
    err = endpoints_implemented_with_code(agent, "finish", {})
    assert err is not None
    assert "12 endpoint(s)" in err


def test_satisfiability_backstop_no_write_register_tools(tmp_path):
    # #58 backstop (run bsb900gpt predated #58 and still wedged): a lane in the
    # implementation phase but WITHOUT write + registryhub_register_endpoint cannot
    # satisfy the gate's corrective action → must no-op, regardless of _active_phase.
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    a = _agent({"a": _ep("POST", "/api/posts")}, tmp_path, tools=())  # no write/register
    a._active_phase = "implementation"
    assert endpoints_implemented_with_code(a, "finish", {}) is None
    # WITH the tools present, the same case blocks (the real gate still fires).
    a2 = _agent({"a": _ep("POST", "/api/posts")}, tmp_path)  # default = write + register
    a2._active_phase = "implementation"
    assert endpoints_implemented_with_code(a2, "finish", {}) is not None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
