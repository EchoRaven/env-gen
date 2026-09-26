"""#1202vd — the gate decided with one normaliser and reported with another.

The unregistered-endpoint check truncated the path at a helper call to DECIDE and
reconstructed it to REPORT, so the lane was handed its own registry entries and told to
register them.
"""
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg

_SRC = pathlib.Path(dg.__file__)


def test_the_lossy_normaliser_really_is_lossy():
    """The premise of #1202vd, measured on tiktok-r129's three live calls: all three
    collapse onto one path, and that path was never in r129's registry."""
    calls = ["GET /api/users/:encodeURIComponent(id)/follow",
             "GET /api/users/:encodeURIComponent(username)",
             "GET /api/users/:encodeURIComponent(username)/videos"]
    collapsed = {dg._strip_source_fragment_1202dn(c) for c in calls}
    assert collapsed == {"GET /api/users"}


def test_the_decision_uses_both_readings():
    """The union must be built from BOTH normalisers and tested against the declared keys.

    The behavioural tests below prove the outcome; this pins the mechanism, because a
    future edit could get today's cases right while dropping one reading. Bounded by
    landmarks, never a byte window (#943 -- which caught exactly this in the first draft)."""
    src = _SRC.read_text()
    block = src[src.index("_readings_1202vd"):src.index("if unregistered_calls:")]
    assert "_strip_source_fragment_1202dn(call)" in block
    assert "_registerable_path_1202lt(call)" in block
    assert "& declared_path_keys" in block


def _hubs(paths):
    from types import SimpleNamespace
    eps = {f"{m} {p}": {"method": m, "path": p, "status": "implemented"} for m, p in paths}
    return SimpleNamespace(
        registryhub=SimpleNamespace(get_endpoints=lambda: eps),
        schema_hub=SimpleNamespace(list_tables=lambda: {}))


def _project(tmp_path, source):
    (tmp_path / "app/frontend/src").mkdir(parents=True)
    (tmp_path / "app/frontend/src/api.js").write_text(source)
    return tmp_path


_R129_SOURCE = """
export const getUser = (username) => request(`/api/users/${encodeURIComponent(username)}`);
export const getVideos = (username) => request(`/api/users/${encodeURIComponent(username)}/videos`);
export const follow = (id) => request(`/api/users/${encodeURIComponent(id)}/follow`, {method: 'POST'});
"""


def _unregistered(result):
    for e in result.get("errors", []):
        if e.startswith("Frontend calls unregistered endpoint(s)"):
            return e
    return ""


def test_registered_paths_reached_through_a_helper_are_not_reported(tmp_path):
    """tiktok-r129 end to end, through the real extractor and the real check.

    The registry holds the three paths the source denotes; the source spells each param
    with `encodeURIComponent(...)`, which is what the extractor flattens to
    `:encodeURIComponent(username)`. Nothing here is unregistered.
    """
    out = dg.validate_contract_alignment(
        _project(tmp_path, _R129_SOURCE),
        _hubs([("GET", "/api/users/{username}"),
               ("GET", "/api/users/{username}/videos"),
               ("POST", "/api/users/{id}/follow")]))
    assert _unregistered(out) == "", _unregistered(out)


def test_a_genuinely_unregistered_helper_call_is_still_reported(tmp_path):
    """The narrowing must not blind the check: same helper shape, nothing registered
    that covers it. #1202vd removes false positives, not the gate's teeth."""
    out = dg.validate_contract_alignment(
        _project(tmp_path, _R129_SOURCE),
        _hubs([("GET", "/api/videos")]))
    err = _unregistered(out)
    assert err
    assert "/api/users/{username}" in err


def test_a_plain_unregistered_path_is_still_reported(tmp_path):
    out = dg.validate_contract_alignment(
        _project(tmp_path, "export const g = () => request(`/api/nowhere`);"),
        _hubs([("GET", "/api/videos")]))
    assert "/api/nowhere" in _unregistered(out)


def test_the_breadth_report_names_the_failing_pages():
    """Kept from the reverted #1202ve. That ticket proposed copying `pages_failed` to a
    top-level gate field; the fact was already persisted under
    `validation_runtime.ui_evidence_breadth.pages_failed` in 3825 of 3825 blocking
    snapshots across 73 runs -- I had searched for a spelling I invented and read its
    absence as the absence of the fact. This pins the reading that already works."""
    out = dg._ui_evidence_breadth_739([
        {"name": "validation:ui_flow:browse_home", "status": "failed",
         "metadata": {"flow": "browse_home"}},
        {"name": "validation:ui_flow:login", "status": "passed",
         "metadata": {"flow": "login"}},
    ])
    assert out["pages_failed"] == ["browse_home"]
    assert out["failed_records"] == 1
