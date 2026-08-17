"""#73 (netflix r77, 2026-08-05) — Part-A near-zero CAPTURE artifact. The visual-fidelity
capture authenticates (seed demo login, to see populated screens); a framework-public page
(login/signup) that redirects authed users away (`if(isAuthed())nav('/profiles')`) then gets
captured AUTHED → redirects → the judge scores the WRONG (redirected) page ~0.00 (r77 login=0.00,
a top Part-A drag). Root: map_reference_screens let a MIS-MEASURED requires_auth=true OVERRIDE the
public-route logged-out capture (old guard `and not isinstance(requires_auth, bool)`).

FIX: a route in _FRAMEWORK_PUBLIC_ROUTES (login/signup) is PUBLIC BY CONSTRUCTION → ALWAYS auth=False
(captured logged-out) regardless of a wrong measured flag. Non-public routes are unaffected (their
measured requires_auth still governs). Validate-by-render for the fidelity lift; this test locks the
auth-STATE resolution (the change's logic). Harness mirrors test_visual_coverage_routed_screens.py."""
import sys
import types
import json
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg73")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg73.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg73"] = pkg
    sys.modules["vf_pkg73.validation_runner"] = vr
    mod = types.ModuleType("vf_pkg73.visual_fidelity")
    mod.__package__ = "vf_pkg73"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()

# login (public) + account (non-public) BOTH measured requires_auth=true by the analyst.
_KNOWN = {"/", "/login", "/signup", "/account"}
_SCREENS = [
    {"name": "login", "route": "/login", "kind": "page", "requires_auth": True,
     "components": [{"id": "form"}]},
    {"name": "signup", "route": "/signup", "kind": "page", "requires_auth": True,
     "components": [{"id": "form"}]},
    {"name": "account", "route": "/account", "kind": "page", "requires_auth": True,
     "components": [{"id": "panel"}]},
]


def _build(tmp_path):
    proj = tmp_path
    (proj / "design").mkdir(parents=True, exist_ok=True)
    (proj / "shared" / "hubs").mkdir(parents=True, exist_ok=True)
    (proj / "design" / "design_system.json").write_text(
        json.dumps({"screens": _SCREENS}), encoding="utf-8")
    (proj / "shared" / "hubs" / "registryhub_ui_pages.json").write_text(
        json.dumps({}), encoding="utf-8")
    refs = []
    for s in _SCREENS:
        f = proj / f"{s['name']}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))
    return proj, refs


def _map(tmp_path):
    proj, refs = _build(tmp_path)
    cls = VF.load_screen_classifications(proj)
    pages = VF.load_ui_pages(proj)
    return {s["name"]: s for s in
            VF.map_reference_screens(refs, _KNOWN, classifications=cls, ui_pages=pages)}


def test_public_login_captured_logged_out_despite_measured_requires_auth(tmp_path):
    # #73: login is framework-public → auth=False even though requires_auth=true was measured
    # (else it redirects authed → scores ~0.00).
    by = _map(tmp_path)
    assert by["login"]["route"] == "/login", by["login"]
    assert by["login"]["auth"] is False, by["login"]


def test_public_signup_also_logged_out(tmp_path):
    by = _map(tmp_path)
    assert by["signup"]["auth"] is False, by["signup"]


def test_non_public_route_keeps_measured_requires_auth(tmp_path):
    # the fix is SCOPED to framework-public routes: a normal authed page still captures authed.
    by = _map(tmp_path)
    assert by["account"]["auth"] is True, by["account"]


def test_public_route_frozenset_unchanged(tmp_path):
    # guard: the framework-public set is still exactly login/signup (no accidental widening)
    assert VF._FRAMEWORK_PUBLIC_ROUTES == frozenset({"/login", "/signup"})


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
