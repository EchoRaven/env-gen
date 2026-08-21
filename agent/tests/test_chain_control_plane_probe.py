"""#386: a verifier-authored DENIAL probe (expect=[401,403]) against a CONTROL-PLANE
public infra endpoint (control_plane.py, auth_required=False — e.g. GET /api/v1/tenants,
which the login TenantPicker fetches pre-auth) is mis-authored: the endpoint is
contractually public, so a 2xx is CORRECT. Before the fix it wedged business_chain
forever (netflix r11: 6× GET /api/v1/tenants -> 200 vs expected [401,403], the verifier
unable to 'fix' it without breaking login). _is_control_plane_public gates the waiver so
a denial probe on a real BUSINESS endpoint still fails.

Isolation harness: chain_executor imports `.validation_runner` (stub) and `.control_plane`
(pure -> exec its real source)."""
import sys
import types
from pathlib import Path

_RT = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
       / "multi_agent" / "runtime")


def _load():
    pkg = types.ModuleType("ce_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("ce_pkg.validation_runner")
    vr._http = lambda *a, **k: {}
    vr._form_retry_warranted = lambda *a, **k: False
    cp = types.ModuleType("ce_pkg.control_plane")
    cp.__package__ = "ce_pkg"
    exec(compile((_RT / "control_plane.py").read_text(encoding="utf-8"),
                 "control_plane.py", "exec"), cp.__dict__)
    sys.modules["ce_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["ce_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    sys.modules["ce_pkg.validation_runner"] = vr
    sys.modules["ce_pkg.control_plane"] = cp
    ce = types.ModuleType("ce_pkg.chain_executor")
    ce.__package__ = "ce_pkg"
    exec(compile((_RT / "chain_executor.py").read_text(encoding="utf-8"),
                 "chain_executor.py", "exec"), ce.__dict__)
    return ce


CE = _load()


def test_public_infra_endpoints_matched():
    assert CE._is_control_plane_public("GET", "/api/v1/tenants")
    assert CE._is_control_plane_public("get", "/api/v1/tenants/")       # trailing slash
    assert CE._is_control_plane_public("POST", "/api/v1/tenants")
    assert CE._is_control_plane_public("GET", "/api/v1/tenants?x=1")    # query stripped
    assert CE._is_control_plane_public("GET", "/health")
    assert CE._is_control_plane_public("POST", "/api/v1/reset")


def test_param_template_matches_concrete_path():
    # DELETE /api/v1/tenants/{tenant_id} -> a concrete id matches the {param} segment
    assert CE._is_control_plane_public("DELETE", "/api/v1/tenants/default")
    assert CE._is_control_plane_public("DELETE", "/api/v1/tenants/acme-corp")


def test_business_endpoints_never_matched():
    # a denial probe on a REAL business endpoint must keep its teeth
    for m, p in [("GET", "/api/titles"), ("GET", "/api/profiles"),
                 ("POST", "/api/my-list"), ("GET", "/api/v1/tenants/x/extra"),
                 ("DELETE", "/api/titles/1"), ("GET", "/api/search")]:
        assert not CE._is_control_plane_public(m, p), f"{m} {p} wrongly waived"


def test_method_must_match():
    # /api/v1/tenants is public for GET/POST but there is no PUT in the control surface
    assert not CE._is_control_plane_public("PUT", "/api/v1/tenants")


def test_public_set_built_from_control_plane():
    # every waived path came from control_plane's auth_required=False rows
    assert ("GET", "/api/v1/tenants") in CE._CONTROL_PLANE_PUBLIC
    assert all(isinstance(x, tuple) and len(x) == 2 for x in CE._CONTROL_PLANE_PUBLIC)
    assert len(CE._CONTROL_PLANE_PUBLIC) == 6  # the 6 fixed infra endpoints


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
