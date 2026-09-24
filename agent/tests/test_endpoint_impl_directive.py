"""FIX #24 — framework-driven per-endpoint implementation directive.

The backend implements single endpoints fine but games/drifts on "implement all
25" (Instagram runs #6/#8). This injects, every step, a deterministic directive
naming the next owned endpoint that still lacks a route handler in source —
decomposing the contract to one-at-a-time without relying on LLM memory. Returns
None outside active endpoint implementation (kickoff / all-done / other lanes).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime.step_pipeline.action import (  # noqa: E402
    AgentActionStageMixin,
)


class _Lane(AgentActionStageMixin):
    def __init__(self, endpoints, worktree, config_key="backend"):
        self._config_key = config_key
        self._worktree_dir = str(worktree) if worktree is not None else None
        self._hubs = SimpleNamespace(
            registryhub=SimpleNamespace(get_endpoints=lambda: endpoints))


def _ep(method, path, provider="backend", kind=None):
    return {"method": method, "path": path, "provider": provider,
            "kind": kind, "status": "defined"}


def test_none_when_no_endpoints(tmp_path):
    assert _Lane({}, tmp_path)._build_endpoint_impl_directive() is None


def test_lists_missing_endpoints(tmp_path):
    (tmp_path / "main.py").write_text("app = FastAPI()\n")  # no business routes
    eps = {"a": _ep("POST", "/api/posts"), "b": _ep("GET", "/api/feed")}
    d = _Lane(eps, tmp_path)._build_endpoint_impl_directive()
    assert d is not None
    assert "0/2" in d
    assert "NEXT to implement" in d
    assert ("/api/posts" in d) and ("/api/feed" in d)


def test_none_when_all_have_routes(tmp_path):
    (tmp_path / "r.py").write_text(
        '@router.post("/posts")\n@router.get("/feed")\n')
    eps = {"a": _ep("POST", "/api/posts"), "b": _ep("GET", "/api/feed")}
    assert _Lane(eps, tmp_path)._build_endpoint_impl_directive() is None


def test_partial_progress_counts_and_names_remaining(tmp_path):
    (tmp_path / "r.py").write_text('@router.post("/posts")\n')  # posts done
    eps = {"a": _ep("POST", "/api/posts"), "b": _ep("GET", "/api/feed")}
    d = _Lane(eps, tmp_path)._build_endpoint_impl_directive()
    assert d is not None
    assert "1/2" in d
    assert "feed" in d.lower()
    assert "posts" not in d.split("NEXT to implement")[1].lower()  # posts not in "next"


def test_skips_fixed_surface(tmp_path):
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    eps = {"a": _ep("POST", "/auth/login", kind="auth")}
    assert _Lane(eps, tmp_path)._build_endpoint_impl_directive() is None


def test_ignores_other_lanes(tmp_path):
    (tmp_path / "main.py").write_text("app = FastAPI()\n")
    eps = {"a": _ep("GET", "/api/feed", provider="frontend")}
    assert _Lane(eps, tmp_path, config_key="backend")._build_endpoint_impl_directive() is None


def test_none_when_no_worktree(tmp_path):
    assert _Lane({"a": _ep("POST", "/api/posts")}, None)._build_endpoint_impl_directive() is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
