"""#1203gy: the route-coverage warning named the framework's own fixed surface.

#1203d1 closed the `__`-probe half of this warning and deliberately left the rest open,
citing #1203b5's note that "the control plane the lane must build" must not be skipped. The
code the framework ships contradicts that reading: `main.py`'s `_FW_FIXED_PATHS_1202KI`
snapshots /api/v1/reset, /api/v1/tenants, /api/v1/tenants/{tenant_id} and
/api/v1/admin/init-tenant BEFORE lane code runs and puts back anything a lane removed,
"because the fixed surface is not the lane's to replace". #1203fy settled it the same way for
the implementation-progress nudge.

Replayed over the 211 runs with a hub and a backend on disk: this warning named 297 endpoints
and 267 of them were that fixed surface; after the exemption, 30 remain and every one is
business. #1202ki counted what the warning costs: 13 of 153 runs delete framework routes and
re-register their own, "almost always the whole control plane the test harness drives", one
verified by curl answering `401 {"detail":"missing bearer token"}` on an endpoint the
framework declares public.
"""
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    validate_contract_alignment,
)


def _hubs(endpoints):
    """A hub pair shaped like the real one: `get_endpoints()` returns id -> record."""
    return types.SimpleNamespace(
        registryhub=types.SimpleNamespace(get_endpoints=lambda: endpoints),
        schema_hub=types.SimpleNamespace(list_tables=lambda: {}),
    )


def _tree(tmp_path, backend_src):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(backend_src, encoding="utf-8")
    return tmp_path


# One implemented business route, so the check runs at all (it needs both sides non-empty).
_IMPLEMENTED = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "@router.get('/api/videos')\n"
    "def videos():\n"
    "    return []\n"
)


def _missing_warning(report):
    return next((w for w in report["warnings"]
                 if "missing declared endpoints" in w), "")


def test_the_control_plane_is_not_reported_as_the_lanes_missing_work(tmp_path):
    eps = {
        "a": {"method": "GET", "path": "/api/videos", "metadata": {"kind": "business"}},
        "b": {"method": "POST", "path": "/api/v1/reset", "metadata": {"kind": "infra"}},
        "c": {"method": "GET", "path": "/api/v1/tenants", "metadata": {"kind": "control"}},
        "d": {"method": "DELETE", "path": "/api/v1/tenants/{tenant_id}",
              "metadata": {"kind": "infra"}},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "/api/v1/reset" not in w, w
    assert "/api/v1/tenants" not in w, w


def test_a_business_endpoint_the_lane_did_not_build_is_still_reported(tmp_path):
    """The warning's whole purpose. Silencing this would trade one defect for a blind gate."""
    eps = {
        "a": {"method": "GET", "path": "/api/videos", "metadata": {"kind": "business"}},
        "b": {"method": "POST", "path": "/api/videos/{id}/like",
              "metadata": {"kind": "business"}},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "/api/videos/{id}/like" in w or "/api/videos/:id/like" in w, w


def test_a_business_endpoint_with_NO_kind_is_still_reported(tmp_path):
    """The over-match guard: `is_business` treats an untagged business path as business.

    2906 of the corpus's 6231 records are non-business and 217 of those carry no `kind` at
    all -- they are framework-owned by PATH. An untagged product path must not join them.
    """
    eps = {
        "a": {"method": "GET", "path": "/api/videos"},
        "b": {"method": "POST", "path": "/api/videos/{id}/save"},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "/api/videos/{id}/save" in w or "/api/videos/:id/save" in w, w


def test_the_control_plane_is_exempt_even_with_no_kind(tmp_path):
    """`lifecycle`'s path net is what covers the 217 untagged framework records."""
    eps = {
        "a": {"method": "GET", "path": "/api/videos"},
        "b": {"method": "POST", "path": "/api/v1/reset"},
        "c": {"method": "GET", "path": "/health"},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "/api/v1/reset" not in w, w
    assert "/health" not in w, w


def test_the_kind_is_honoured_on_a_path_the_net_does_not_know(tmp_path):
    """The reason the hub RECORD is consulted instead of re-deriving from the path.

    `api_spec` above projects only method+path, so a framework endpoint on an unfamiliar path
    is only recognisable through its `metadata.kind` -- the #1203d8/#1203e5 shape.
    """
    eps = {
        "a": {"method": "GET", "path": "/api/videos"},
        "b": {"method": "POST", "path": "/internal/zz-framework-only",
              "metadata": {"kind": "infra"}},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "zz-framework-only" not in w, w


def test_the_probe_exemption_still_holds(tmp_path):
    """#1203d1 is regression surface, not history."""
    eps = {
        "a": {"method": "GET", "path": "/api/videos"},
        "b": {"method": "GET", "path": "/__noop_orchestrator_probe__"},
    }
    w = _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps)))
    assert "__noop" not in w, w


def test_the_two_status_filters_stay_the_same_pair():
    """The exemption and `api_spec` must apply the same `deprecated` filter.

    The obvious behavioural test -- "a deprecated endpoint is not reported missing" -- is
    VACUOUS: `api_spec` already drops it, so it never reaches `declared_keys` and the
    assertion passes whether the exemption filters it or not. A mutation removing the
    exemption's filter proved that. So assert the coupling in the source instead, which is
    the property actually worth keeping.
    """
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as _dg

    src = inspect.getsource(_dg.validate_contract_alignment)
    tree = ast.parse(src.lstrip())
    deprecated_tests = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Compare) and "deprecated" in ast.unparse(n)
    ]
    assert len(deprecated_tests) >= 2, (
        "api_spec and the #1203gy exemption must each filter deprecated records; found %d: %s"
        % (len(deprecated_tests), deprecated_tests))


def test_the_check_still_reports_nothing_when_everything_is_built(tmp_path):
    eps = {"a": {"method": "GET", "path": "/api/videos", "metadata": {"kind": "business"}}}
    assert _missing_warning(validate_contract_alignment(
        _tree(tmp_path, _IMPLEMENTED), _hubs(eps))) == ""
