"""#491 (netflix r63, confirmed): App.jsx routes catalog pages as
``<RequireProfile><XxxPage/></RequireProfile>``; RequireProfile redirects to
``/profiles`` when ``getActiveProfileId()`` (= ``localStorage.getItem(
'active_profile_id')``) is empty. The visual-fidelity capture (and the browser
test-user) log in — setting a token — but NEVER select a profile, so every
catalog route bounces to the profiles chooser: all catalog screenshots become
IDENTICAL (the profiles list) and fidelity collapses (~0.06-0.12) instead of
scoring the real pages.

FIX: after the token is set, ALSO establish an active profile in localStorage.
Mirroring the token block (FIX #103), the profile-selection storage KEY is pure
lane variance, so ``_profile_select_init_js`` writes the id under EVERY common
alias in BOTH localStorage and sessionStorage. This locks in the pure helper's
contract (falsy id → no-op; every alias set once per storage; JSON-encoded value
so the JS is always well-formed).

Self-contained harness (mirrors test_visual_capture_param_route.py): stub the
one sibling import, exec the module under a synthetic package — no heavy deps."""
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf491_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf491_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf491_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["vf491_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    sys.modules["vf491_pkg.validation_runner"] = vr
    mod = types.ModuleType("vf491_pkg.visual_fidelity")
    mod.__package__ = "vf491_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()
_js = VF._profile_select_init_js
_ALIASES = VF._PROFILE_KEY_ALIASES


def test_falsy_id_is_a_noop():
    # (a) no id to establish → empty string → the caller injects nothing.
    for falsy in (None, "", 0):
        assert _js(falsy) == "", f"falsy id {falsy!r} must yield no JS"


def test_id_one_sets_all_the_expected_pieces():
    # (b) the documented required substrings for id "1".
    out = _js("1")
    for needle in ("active_profile_id", "profileId",
                   "localStorage.setItem", "sessionStorage.setItem", "1"):
        assert needle in out, f"expected {needle!r} in the init JS"


def test_one_setitem_per_alias_per_storage():
    # (c) valid-ish JS: exactly one localStorage.setItem AND one
    # sessionStorage.setItem per alias — no missing/duplicated writes.
    out = _js("42")
    n = len(_ALIASES)
    assert n >= 5, "expected the full alias table"
    assert out.count("localStorage.setItem") == n
    assert out.count("sessionStorage.setItem") == n
    # every alias appears (quoted as a JS key)
    for k in _ALIASES:
        assert f"'{k}'" in out, f"alias {k!r} missing from the init JS"


def test_value_is_json_encoded_and_quotes_balanced():
    # the value goes through json.dumps → always a quoted JS string literal, so
    # the snippet is well-formed for any id (no unbalanced quotes).
    out = _js("7")
    assert '"7"' in out, "id must be JSON-encoded as a quoted string literal"
    assert out.count('"') % 2 == 0, "double quotes must be balanced"
    assert out.count("'") % 2 == 0, "single quotes must be balanced"


def test_helper_and_discover_js_are_exported():
    # the browser test-user lazy-imports both — guard the public names.
    assert callable(_js)
    assert isinstance(VF._PROFILE_DISCOVER_JS, str) and VF._PROFILE_DISCOVER_JS
    assert "fetch" in VF._PROFILE_DISCOVER_JS


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
