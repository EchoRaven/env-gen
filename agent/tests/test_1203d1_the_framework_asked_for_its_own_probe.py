r"""#1203d1: the framework declares its own probe, then tells the lane the backend is missing it.

`validate_contract_alignment` compares every DECLARED endpoint against the backend's routes and
warns about the gap. Nothing excluded the framework's own `__`-prefixed probes — and the
orchestrator REGISTERS them. r148's `registryhub_endpoints.json`, verbatim:

    "GET /__noop_orchestrator_probe__"        _updated_by: orchestrator, status: deprecated
    "GET /__noop_monitoring_read_not_write__" _updated_by: orchestrator, status: defined

so the warning read:

    Backend route coverage missing declared endpoints: GET /__noop_monitoring_read_not_write__

MEASURED over every gate ledger: a `__` probe reaches `contract_alignment` output in 421 of 8979
records across 30 runs — 310 as a warning (28 runs, r148 live) and 111 as an ERROR (3 runs;
netflix-r22 alone has 108, and an error fires `contract_alignment_failed`, which blocks).

★ THE WARNING FEEDS A DEFECT THE CORPUS ALREADY RECORDS. `format_delivery_gate_report` puts
`warnings[:5]` into the resident-tick instruction, so the lane is told to build it — and a
`__noop_*` route built to satisfy a framework check is a measured, SHIPPED defect: 35 of 179
runs with a generated backend carry one (20%; 38% of September's), r140's being a public,
auth-free `SELECT COUNT(*)` over four business tables whose own docstring says it exists "so
code-truth can distinguish it from a static placeholder". #1202lt states the rule this breaks:
"the framework asked a lane to chase a defect that did not exist, which is the one thing
framework-authored instructions are not allowed to do."

★ SCOPE IS ONE OF THE THREE PATHS, DELIBERATELY. A probe also reaches "Frontend calls
unregistered endpoint(s)" (107 ERROR records — a probe in the delivered FRONTEND) and "SQL
schema missing registered table" (4 — a probe registered as a TABLE). Those are real defects
and must keep firing; only "the lane did not build the framework's own probe" is not the lane's.
"""
import os
import sys
from types import SimpleNamespace

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.delivery_gate as dg  # noqa: E402


def _hubs(paths):
    eps = {f"{m} {p}": {"method": m, "path": p, "status": "implemented"} for m, p in paths}
    return SimpleNamespace(
        registryhub=SimpleNamespace(get_endpoints=lambda: eps),
        schema_hub=SimpleNamespace(list_tables=lambda: {}))


def _project(tmp_path, backend="", frontend="export const x = 1;\n"):
    (tmp_path / "app/frontend/src").mkdir(parents=True)
    (tmp_path / "app/frontend/src/api.js").write_text(frontend, encoding="utf-8")
    (tmp_path / "app/backend").mkdir(parents=True)
    (tmp_path / "app/backend/main.py").write_text(
        backend or '@app.get("/api/videos")\ndef v(): return []\n', encoding="utf-8")
    return tmp_path


def _coverage(out):
    return " ".join(w for w in (out.get("warnings") or [])
                    if "Backend route coverage missing" in w)


def test_the_frameworks_own_probe_is_not_the_lanes_to_build(tmp_path):
    """★ r148's exact state: the orchestrator declared the probe, the backend has no route."""
    out = dg.validate_contract_alignment(
        _project(tmp_path),
        _hubs([("GET", "/api/videos"), ("GET", "/__noop_monitoring_read_not_write__")]))
    assert "__noop_monitoring_read_not_write__" not in _coverage(out), out.get("warnings")


def test_a_real_missing_endpoint_is_still_reported(tmp_path):
    """★ The direction that matters: this check exists to find unbuilt contract surface."""
    out = dg.validate_contract_alignment(
        _project(tmp_path),
        _hubs([("GET", "/api/videos"), ("GET", "/api/sounds")]))
    assert "/api/sounds" in _coverage(out), out.get("warnings")


def test_an_api_scoped_double_underscore_is_still_product_surface(tmp_path):
    """#1203b5's convention, which registryhub's tagger states: `/api/__x` is app surface and is
    left alone. Only a LEADING `__` segment is the framework's own."""
    out = dg.validate_contract_alignment(
        _project(tmp_path),
        _hubs([("GET", "/api/videos"), ("GET", "/api/__internal_stats")]))
    assert "/api/__internal_stats" in _coverage(out), out.get("warnings")


def test_the_declared_count_is_unchanged(tmp_path):
    """This changes who is asked to build what, not what the contract says it holds."""
    out = dg.validate_contract_alignment(
        _project(tmp_path),
        _hubs([("GET", "/api/videos"), ("GET", "/__noop_probe__")]))
    assert out.get("declared_endpoints") == 2, out


def test_a_probe_called_by_the_frontend_still_errors(tmp_path):
    """★ A DIFFERENT PATH AND A REAL DEFECT: the probe reached the delivered frontend. 107 error
    records across netflix-r22/r4/r44 are this shape, and silencing it is the one thing a guard
    must never do."""
    out = dg.validate_contract_alignment(
        _project(tmp_path, frontend="export const p = () => fetch('/__noop_probe__');\n"),
        _hubs([("GET", "/api/videos")]))
    blob = " ".join((out.get("errors") or []) + (out.get("warnings") or []))
    assert "__noop_probe__" in blob, out


def test_the_filter_is_applied_to_the_report_not_to_the_contract():
    """★ Structural: the exemption belongs on `missing_endpoints`. Applied to `declared_keys` it
    would also change the matching set and the count, and every later consumer with it."""
    import ast
    import inspect

    src = inspect.getsource(dg.validate_contract_alignment)
    tree = ast.parse(src.lstrip())
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "_declared_probe_1203d1"]
    assert len(hits) == 1, "called %d times" % len(hits)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "declared_keys" for t in node.targets)):
            assert "_declared_probe_1203d1" not in ast.dump(node), \
                "the filter moved onto declared_keys — that changes the contract, not the ask"


def test_the_predicate_reads_the_path_half():
    """A registry entry is `"GET /__noop__"`; the method must not be mistaken for the path."""
    fn = getattr(dg, "_declared_probe_1203d1", None)
    assert fn is not None, "_declared_probe_1203d1 is not defined"
    assert fn("GET /__noop_orchestrator_probe__") is True
    assert fn("/__noop_orchestrator_probe__") is True
    assert fn("GET /api/videos") is False
    assert fn("GET /api/__internal") is False
    assert fn("") is False
    assert fn(None) is False


def test_it_shares_1203b5s_predicate_rather_than_copying_it():
    """#1080: eight inlined copies of one test is how they drift. The `__` convention has one
    implementation, and its docstring carries the measurement that shaped it."""
    import inspect
    src = inspect.getsource(dg._declared_probe_1203d1)
    assert "_is_framework_probe_1203b5" in src, src[:200]
