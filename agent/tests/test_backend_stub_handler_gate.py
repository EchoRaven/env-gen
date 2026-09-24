"""FIX #173 — a backend GET route handler that returns a HARDCODED empty collection with
NO database query is a PLACEHOLDER STUB (the backend equivalent of a mock page) and must
BLOCK delivery.

gmrun9 shipped one (runtime-verified): the lane "fixed" /api/transit/{id}/departures by
writing `def get_departures(...): return {"items": []}` with a comment "This is a stub for
departures" — even though real data existed (transit_stops.line_refs → transit_lines). The
DeparturesPage then permanently showed "No departures found." The no_real_data browser gate
was fooled by a weak token elsewhere on the walk. A handler that never touches the DB and
returns an empty collection can NEVER serve real data → catch it by construction at the
backend. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import stub_handler_blockers  # noqa: E402


def _bd(tmp_path, files):
    d = tmp_path / "app" / "backend"
    d.mkdir(parents=True, exist_ok=True)
    for rel, src in files.items():
        (d / rel).write_text(src)
    return d


_STUB = '''
from fastapi import APIRouter, Depends
router = APIRouter()
@router.get("/api/transit/{id}/departures")
def get_departures(id: str, db=Depends(get_db)):
    # This is a stub for departures. In a real app, this would query a schedule table.
    return {"items": []}
'''

_REAL = '''
from fastapi import APIRouter, Depends
router = APIRouter()
@router.get("/api/transit/{id}/departures")
def get_departures(id: str, db=Depends(get_db)):
    rows = db.query(TransitLine).all()
    return {"items": [r.name for r in rows]}
'''


def test_hardcoded_empty_envelope_flagged(tmp_path):
    b = stub_handler_blockers(_bd(tmp_path, {"custom_routes.py": _STUB}))
    assert any("get_departures" in x and "stub" in x.lower() for x in b), b


def test_real_query_handler_not_flagged(tmp_path):
    assert stub_handler_blockers(_bd(tmp_path, {"custom_routes.py": _REAL})) == []


def test_bare_empty_list_return_flagged(tmp_path):
    src = ('from fastapi import APIRouter\nrouter = APIRouter()\n'
           '@router.get("/api/lists/saved")\n'
           'def get_saved(db=Depends(get_db)):\n    return []\n')
    b = stub_handler_blockers(_bd(tmp_path, {"s.py": src}))
    assert any("get_saved" in x for x in b), b


def test_empty_envelope_with_total_flagged(tmp_path):
    src = ('@router.get("/api/x")\n'
           'def list_x(db=Depends(get_db)):\n    return {"items": [], "total": 0}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"x.py": src}))


def test_health_constant_not_flagged(tmp_path):
    # a non-collection constant (health/status) is NOT a placeholder page
    src = ('@router.get("/health")\n'
           'def health():\n    return {"status": "ok"}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"h.py": src})) == []


def test_post_action_constant_not_flagged(tmp_path):
    # a POST action returning a status envelope is not a collection page
    src = ('@router.post("/api/places/{id}/save")\n'
           'def save(id: str):\n    return {"ok": True}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"p.py": src})) == []


def test_static_nonempty_options_not_flagged(tmp_path):
    # a legit static-options endpoint returns a NON-empty constant → not a stub
    src = ('@router.get("/api/modes")\n'
           'def modes():\n    return {"items": ["driving", "walking", "transit"]}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"m.py": src})) == []


def test_projected_query_handler_with_empty_guard_not_flagged(tmp_path):
    # a handler that DOES query but has an early empty-return guard is NOT a stub
    src = ('@router.get("/api/y")\n'
           'def list_y(id: str, db=Depends(get_db)):\n'
           '    if not id:\n        return {"items": []}\n'
           '    rows = db.query(Y).filter(Y.id == id).all()\n'
           '    return {"items": [r.id for r in rows]}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"y.py": src})) == []


def test_delegating_handler_not_flagged(tmp_path):
    # returns a helper CALL (dynamic) → not a constant stub
    src = ('@router.get("/api/z")\n'
           'def list_z(db=Depends(get_db)):\n    return build_z(db)\n')
    assert stub_handler_blockers(_bd(tmp_path, {"z.py": src})) == []


def test_async_handler_flagged(tmp_path):
    src = ('@router.get("/api/a")\n'
           'async def list_a(db=Depends(get_db)):\n    return {"items": []}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"a.py": src}))


def test_stub_blocker_canonicalizes_to_delivery_token():
    from multi_agent.runtime.delivery_gate import _deliverability_check_token
    blocker = ("backend handler `get_departures` (custom_routes.py) is a PLACEHOLDER STUB "
               "— a GET route that returns a hardcoded EMPTY collection with NO database "
               "query, so its page can never render real data.")
    assert _deliverability_check_token(blocker) == "deliverability_placeholder_stub_handler"


def test_env_gate_disables(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_STUB_HANDLER_GATE", "0")
    assert stub_handler_blockers(_bd(tmp_path, {"custom_routes.py": _STUB})) == []


def _gate_owner_map():
    """AST-extract the `_GATE_OWNER` dict (token → owner-lane). This is the gate-level map
    the delivery-gate DECLINE path reads (remediation_dispatcher line ~749); a gate-minted
    `deliverability_*` token missing HERE logs 'NO remediation owner' and rides to STUCK —
    a `_CHECK_OWNER` entry is dead code (gmrun10 caught exactly this, live)."""
    import ast
    from pathlib import Path
    from multi_agent.runtime import remediation_dispatcher as rd
    tree = ast.parse(Path(rd.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                isinstance(t, ast.Name) and t.id == "_GATE_OWNER" for t in node.targets):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and isinstance(v, ast.Tuple) and v.elts
                        and isinstance(v.elts[0], ast.Constant)):
                    out[k.value] = v.elts[0].value
            return out
    return {}


def test_remediation_owner_maps_stub_token_to_backend():
    # the gate-minted token MUST be in _GATE_OWNER (not just _CHECK_OWNER, which is dead code
    # for gate-level tokens) → routed to the backend lane, else the block deadlocks to STUCK.
    assert _gate_owner_map().get("deliverability_placeholder_stub_handler") == "backend"


# ── gmrun9 v1.3.0 real-archive-driven cases (route shadowing + hardcoded mock) ──

def test_hardcoded_mock_rows_flagged(tmp_path):
    # the EXACT get_departures the lane shipped: non-empty HARDCODED mock rows, no DB read.
    # A mock twin is a placeholder too — the user's "no mock" bar.
    src = ('@router.get("/api/transit/{id}/departures")\n'
           'def get_departures(id: str, db=Depends(get_db)):\n'
           '    return {"items": [{"id": "dep_1", "line": "A", "time": "5 min"},\n'
           '                      {"id": "dep_2", "line": "B", "time": "12 min"}]}\n')
    b = stub_handler_blockers(_bd(tmp_path, {"custom_routes.py": src}))
    assert any("get_departures" in x for x in b), b


def test_shadowed_projected_stub_not_flagged_when_custom_serves(tmp_path):
    # FALSE-POSITIVE fix: a route with BOTH a projected empty stub (main.py, _projected_*)
    # AND a real custom handler (custom_routes.py) is SERVED by the custom one — the custom
    # router is included before the projected @app routes, so it wins. Do NOT flag the dead
    # shadowed projected stub.
    main = ('@app.get("/api/directions")\n'
            'def _projected_get_api_directions_4(db=Depends(get_db)):\n'
            '    return {"items": []}\n')
    custom = ('@router.get("/api/directions")\n'
              'def get_directions(origin_id: str, db=Depends(get_db)):\n'
              '    rows = db.query(Route).filter(Route.origin == origin_id).all()\n'
              '    return {"items": [r.id for r in rows]}\n')
    b = stub_handler_blockers(_bd(tmp_path, {"main.py": main, "custom_routes.py": custom}))
    assert b == [], b


def test_route_with_only_projected_stub_is_flagged(tmp_path):
    # no custom handler → the projected empty stub IS the served handler → flag it
    main = ('@app.get("/api/lists/saved")\n'
            'def _projected_get_api_lists_saved_7(db=Depends(get_db)):\n'
            '    return {"items": []}\n')
    b = stub_handler_blockers(_bd(tmp_path, {"main.py": main}))
    assert any("saved" in x for x in b), b


def test_real_saved_handler_shadows_projected_not_flagged(tmp_path):
    # get_saved_lists DOES query (returns empty for a fresh user, legitimately) → the route is
    # served by a real handler → not a placeholder despite the shadowed projected empty stub.
    main = ('@app.get("/api/lists/saved")\n'
            'def _projected_get_api_lists_saved_7(db=Depends(get_db)):\n'
            '    return {"items": []}\n')
    custom = ('@router.get("/api/lists/saved")\n'
              'def get_saved_lists(request, db=Depends(get_db)):\n'
              '    rows = db.query(SavedList).filter(SavedList.user_id == 1).all()\n'
              '    return {"items": rows}\n')
    b = stub_handler_blockers(_bd(tmp_path, {"main.py": main, "custom_routes.py": custom}))
    assert b == [], b


def test_ignores_control_surface_tenants_endpoint(tmp_path):
    # /api/v1/tenants is a framework-owned CONTROL SURFACE — a hardcoded default tenant is
    # intentional infra, not an app placeholder; the lane can't/shouldn't change it, so
    # flagging it would churn to a NO-CONVERGENCE abort (archive audit, gmrun3).
    src = ('@router.get("/api/v1/tenants")\n'
           'def get_tenants(db=Depends(get_db)):\n'
           '    return {"items": [{"id": "default", "name": "Default Tenant"}]}\n')
    assert stub_handler_blockers(_bd(tmp_path, {"custom_routes.py": src})) == []


def test_departures_mock_shadows_projected_query_flagged(tmp_path):
    # the FULL gmrun9 v1.3.0 shape: the projected handler reads a (wrong) table but is
    # SHADOWED by the custom mock handler that actually serves → flag the served mock.
    main = ('@app.get("/api/transit/{id}/departures")\n'
            'def _projected_get_api_transit_id_departures_5(id: str, db=Depends(get_db)):\n'
            '    rows = db.query(Transit).limit(100).all()\n'
            '    return {"items": [{"id": r.id} for r in rows]}\n')
    custom = ('@router.get("/api/transit/{id}/departures")\n'
              'def get_departures(id: str, db=Depends(get_db)):\n'
              '    return {"items": [{"id": "dep_1", "line": "A", "time": "5 min"}]}\n')
    b = stub_handler_blockers(_bd(tmp_path, {"main.py": main, "custom_routes.py": custom}))
    assert any("get_departures" in x for x in b), b
    assert not any("_projected_" in x for x in b), b  # never flag the shadowed one
