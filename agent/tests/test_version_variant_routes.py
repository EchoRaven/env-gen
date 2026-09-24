"""FIX #180 — run-13 aborted (80min no-convergence) because the contract registered directions
under TWO version-variant paths: GET /api/directions (implemented by a real custom handler) AND
GET /api/v1/directions (left a projected empty stub {"items":[],"total":0}). The frontend api
client calls /api/v1/directions → hits the stub → directions can never render, and the backend
lane — seeing a working get_directions at /api/directions — could not converge on "fix the OTHER
path". #173 correctly flagged the stub, but the real fix is CONSOLIDATE the duplicate paths, and
which of the two the lane implements is LLM-nondeterministic (run-12 delivered, run-13 aborted,
SAME env) → a flaky-abort source. This detector finds version-variant duplicate route
registrations so a SOFT gate can route a precise "consolidate to the path your frontend calls"
remediation EARLY instead of the lane thrashing 80min on the wrong fix. Pure; LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.contract_drift import version_variant_duplicate_routes  # noqa: E402


def test_flags_directions_version_duplicate():
    # the exact run-13 shape: same method, /api/X and /api/v1/X.
    eps = {
        "GET /api/directions": {"method": "GET", "path": "/api/directions"},
        "GET /api/v1/directions": {"method": "GET", "path": "/api/v1/directions"},
    }
    blockers = version_variant_duplicate_routes(eps)
    assert len(blockers) == 1
    b = blockers[0]
    assert b["method"] == "GET"
    assert set(b["paths"]) == {"/api/directions", "/api/v1/directions"}
    assert "consolidate" in b["hint"].lower()


def test_no_flag_single_path():
    eps = {"GET /api/v1/directions": {"method": "GET", "path": "/api/v1/directions"}}
    assert version_variant_duplicate_routes(eps) == []


def test_no_flag_distinct_endpoints():
    eps = {
        "GET /api/places": {"method": "GET", "path": "/api/places"},
        "GET /api/reviews": {"method": "GET", "path": "/api/reviews"},
    }
    assert version_variant_duplicate_routes(eps) == []


def test_no_flag_different_methods():
    # same version-variant path but different METHOD = different operations, not a dup.
    eps = {
        "GET /api/directions": {"method": "GET", "path": "/api/directions"},
        "POST /api/v1/directions": {"method": "POST", "path": "/api/v1/directions"},
    }
    assert version_variant_duplicate_routes(eps) == []


def test_no_flag_genuinely_distinct_non_version_paths():
    # /api/places vs /api/place-groups differ but NOT by a version segment → not flagged.
    eps = {
        "GET /api/places": {"method": "GET", "path": "/api/places"},
        "GET /api/place-groups": {"method": "GET", "path": "/api/place-groups"},
    }
    assert version_variant_duplicate_routes(eps) == []


def test_skips_meta_and_non_endpoint_entries():
    eps = {
        "_meta": {"generated_at": 123, "version": 2},
        "GET /api/directions": {"method": "GET", "path": "/api/directions"},
        "GET /api/v1/directions": {"method": "GET", "path": "/api/v1/directions"},
    }
    assert len(version_variant_duplicate_routes(eps)) == 1


def test_real_registryhub_shape_multiple_dups():
    # run-13 had BOTH directions and places/search duplicated; places/{id} was single.
    eps = {
        "_meta": {},
        "GET /api/directions": {"method": "GET", "path": "/api/directions"},
        "GET /api/v1/directions": {"method": "GET", "path": "/api/v1/directions"},
        "GET /api/places/search": {"method": "GET", "path": "/api/places/search"},
        "GET /api/v1/places/search": {"method": "GET", "path": "/api/v1/places/search"},
        "GET /api/places/{id}": {"method": "GET", "path": "/api/places/{id}"},
    }
    blockers = version_variant_duplicate_routes(eps)
    assert len(blockers) == 2  # directions + places/search; places/{id} not duplicated
    flagged = {tuple(sorted(b["paths"])) for b in blockers}
    assert ("/api/directions", "/api/v1/directions") in flagged
    assert ("/api/places/search", "/api/v1/places/search") in flagged
