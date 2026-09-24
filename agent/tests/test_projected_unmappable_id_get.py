"""FIX #162 (gmrun7 M2 root cause) — an unmappable GET-by-id path must NOT fall back to
querying the spine model with a type-mismatched id.

gmrun7 recurring transit 500: the projector could not map `/api/transit/{id}/departures`
("transit" is not a table — the tables are transit_lines/transit_stops; "departures" is a
derived sub-resource), so `_resource_model` returned None. The fallback GET-by-param
resolver then matched ANY model with a column named after the last param — but the last
param is the GENERIC `id`, which EVERY model has, so it matched the FIRST model (the
`tenants` spine, whose id is TEXT) → it emitted `db.query(Tenant).filter(Tenant.id == id)`
with `id: int` → psycopg `operator does not exist: text = integer` → 500 on every call.

A generic `id` param is a meaningless resolver signal (all models have it). When the path
is unmappable AND its param is a generic id, the projection must serve an honest 404 stub
(a param-path 404 is exempted by the reachability gate; the lane implements the real
handler in custom_routes.py) — never a wrong-model query that 500s forever. A DISTINCTIVE
param (username/slug) still resolves. LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import _generate_handler  # noqa: E402


def _m(cls, cols, fks=None):
    return {"cls": cls, "cols": cols, "fks": fks or {}}


# tenants (spine, TEXT id) is FIRST — exactly the ordering that made the resolver pick it
_MODELS = {
    "tenants": _m("Tenant", ["id", "name", "status"]),
    "users": _m("User", ["id", "email", "name", "password_hash"]),
    "transit_lines": _m("TransitLine", ["id", "from_stop", "to_stop", "name"]),
    "transit_stops": _m("TransitStop", ["id", "name", "lat", "lng"]),
    "places": _m("Place", ["id", "name", "category", "address"]),
}


def test_unmappable_id_get_is_a_404_stub_not_a_spine_query():
    src = _generate_handler("GET", "/api/transit/{id}/departures", auth=False,
                            models=_MODELS, idx=5)
    # the gmrun7 killer: it must NOT query the spine (or ANY) model by a generic id
    assert "db.query(Tenant)" not in src, src
    assert "Tenant.id == id" not in src, src
    # instead: an honest 404 (a param-path 404 is exempted by the reachability gate;
    # the lane implements the real handler; the chain tolerates 404)
    assert "status_code=404" in src, src


def test_unmappable_id_get_param_is_not_typed_against_a_wrong_model():
    # even the signature must not commit `id: int` bound to a text-id spine query
    src = _generate_handler("GET", "/api/transit/{id}/departures", auth=False,
                            models=_MODELS, idx=5)
    # no wrong-model filter of any kind (the 404 stub has no db.query at all)
    assert ".filter(" not in src or "db.query(" not in src, src


def test_distinctive_param_still_resolves():
    # a DISTINCTIVE (non-id) param must STILL resolve via its matching column — the fix
    # only skips the meaningless generic-id match, not real single-resource GETs.
    models = {"tenants": _m("Tenant", ["id", "name"]),
              "profiles": _m("Profile", ["id", "handle", "bio"])}
    src = _generate_handler("GET", "/api/lookup/{handle}", auth=False, models=models, idx=2)
    assert "Profile" in src and "handle" in src, src
    assert "db.query(Profile)" in src, src


def test_resolvable_resource_by_id_unaffected():
    # /api/places/{id} resolves "places" -> Place via _resource_model BEFORE the fallback,
    # so a legit single-resource by-id GET is untouched.
    src = _generate_handler("GET", "/api/places/{id}", auth=False, models=_MODELS, idx=3)
    assert "db.query(Place)" in src or "db.get(Place" in src, src
    assert "db.query(Tenant)" not in src, src


def test_unmappable_nonparam_get_unaffected():
    # a non-param unmappable GET keeps its existing stub behaviour (not this branch)
    src = _generate_handler("GET", "/api/health/status", auth=False, models=_MODELS, idx=4)
    assert "db.query(Tenant)" not in src, src
