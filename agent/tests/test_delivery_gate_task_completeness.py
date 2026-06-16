"""GATE-C2/C3 — delivery gate task-completeness HARD check (coverage-aware).

``_validate_delivery_gate`` was a pure "evidence exists" model: it never checked
whether the kickoff-synthesized structural work (one ``implement_endpoint`` /
``implement_table`` per contract entry, one ``validate_api_smoke`` per business
endpoint) was DONE. So dozens of per-endpoint validation tasks could sit pending
forever while a release cut anyway — the user's "task not finished, why did it
release" root cause.

``_incomplete_required_tasks`` adds the missing check, but COVERAGE-AWARE so it
does not 误伤. Calibrated on the released generated/instagram round47: 24
``validate_api_smoke`` tasks sat pending only because the verifier ran ONE
``run_validation()`` covering every endpoint instead of closing each per-endpoint
task; blocking on raw pending status would have falsely blocked that good
release. So a pending task blocks ONLY when registry evidence is missing:

  * implement_endpoint → endpoint not registered implemented/tested
  * implement_table    → table not registered implemented/tested
  * validate_api_smoke → endpoint has NO passing contract-test record

Ad-hoc ``task_*`` (visual / breaking-change / merge / chain-authoring
remediation) are NOT structural kickoff kinds and are governed by their own
gates — excluded here so this gate never double-blocks them.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import Orchestrator  # noqa: E402


# ── stub hubs ────────────────────────────────────────────────────────────────

def _stub(tasks, endpoints=None, tables=None, contract_tests=None):
    """contract_tests: {endpoint_id -> [result_dict, ...]} where each result is
    the ``result`` sub-dict (we wrap it into the stored record shape)."""
    endpoints = endpoints or {}
    tables = tables or {}
    contract_tests = contract_tests or {}

    class _WH:
        def list_tasks(self, **_):
            return list(tasks)

    class _RH:
        def get_endpoints(self):
            return endpoints

        def get_contract_test_results(self, endpoint_id):
            return [{"endpoint_id": endpoint_id, "result": r}
                    for r in contract_tests.get(endpoint_id, [])]

    class _SH:
        def list_tables(self):
            return tables

    return types.SimpleNamespace(hubs=types.SimpleNamespace(
        workhub=_WH(), registryhub=_RH(), schema_hub=_SH()))


def _incomplete(tasks, **kw):
    return Orchestrator._incomplete_required_tasks(_stub(tasks, **kw))


def _ids(rows):
    return {r["id"] for r in rows}


# ── validate_api_smoke: coverage-aware ────────────────────────────────────────

def test_validate_task_covered_by_passing_contract_test_does_not_block():
    tasks = [{"id": "validate.api_smoke.get._api_feed", "status": "pending",
              "metadata": {"kind": "validate_api_smoke",
                           "endpoint": {"method": "GET", "path": "/api/feed"}}}]
    eps = {"GET /api/feed": {"method": "GET", "path": "/api/feed", "status": "implemented"}}
    cts = {"GET /api/feed": [{"passed": True, "verdict": "pass", "status_code": 200}]}
    assert _incomplete(tasks, endpoints=eps, contract_tests=cts) == []


def test_validate_task_without_contract_test_blocks():
    tasks = [{"id": "validate.api_smoke.get._api_feed", "status": "pending",
              "metadata": {"kind": "validate_api_smoke",
                           "endpoint": {"method": "GET", "path": "/api/feed"}}}]
    eps = {"GET /api/feed": {"method": "GET", "path": "/api/feed", "status": "implemented"}}
    rows = _incomplete(tasks, endpoints=eps, contract_tests={})
    assert _ids(rows) == {"validate.api_smoke.get._api_feed"}
    assert "contract-test" in rows[0]["reason"]


def test_validate_task_with_only_failing_contract_test_blocks():
    tasks = [{"id": "v1", "status": "pending",
              "metadata": {"kind": "validate_api_smoke",
                           "endpoint": {"method": "POST", "path": "/api/posts"}}}]
    eps = {"POST /api/posts": {"method": "POST", "path": "/api/posts", "status": "implemented"}}
    cts = {"POST /api/posts": [{"passed": False, "verdict": "fail", "status_code": 500}]}
    assert _ids(_incomplete(tasks, endpoints=eps, contract_tests=cts)) == {"v1"}


# ── implement_endpoint / implement_table: registry-status aware ───────────────

def test_implement_endpoint_pending_but_implemented_does_not_block():
    tasks = [{"id": "impl.endpoint.post._api_posts", "status": "in_progress",
              "metadata": {"kind": "implement_endpoint",
                           "endpoint": {"method": "POST", "path": "/api/posts"}}}]
    eps = {"POST /api/posts": {"method": "POST", "path": "/api/posts", "status": "implemented"}}
    assert _incomplete(tasks, endpoints=eps) == []


def test_implement_endpoint_pending_and_defined_blocks():
    tasks = [{"id": "impl.endpoint.post._api_posts", "status": "pending",
              "metadata": {"kind": "implement_endpoint",
                           "endpoint": {"method": "POST", "path": "/api/posts"}}}]
    eps = {"POST /api/posts": {"method": "POST", "path": "/api/posts", "status": "defined"}}
    rows = _incomplete(tasks, endpoints=eps)
    assert _ids(rows) == {"impl.endpoint.post._api_posts"}
    assert "not implemented" in rows[0]["reason"]


def test_implement_table_status_aware():
    base = {"id": "impl.table.users", "status": "pending",
            "metadata": {"kind": "implement_table", "table": "users"}}
    assert _incomplete([base], tables={"users": {"name": "users", "status": "implemented"}}) == []
    rows = _incomplete([base], tables={"users": {"name": "users", "status": "defined"}})
    assert _ids(rows) == {"impl.table.users"}
    assert "table" in rows[0]["reason"]


# ── ad-hoc tasks are NOT structural → never counted ───────────────────────────

def test_adhoc_remediation_tasks_are_not_counted():
    tasks = [
        {"id": "task_visual1", "status": "pending", "title": "UI does not match reference designs",
         "metadata": {"kind": "visual_remediation", "priority": "P1"}},
        {"id": "task_bc1", "status": "pending", "title": "Fix breaking change in GET /api/users/me",
         "metadata": {"priority": "P0"}},  # no structural kind at all
        {"id": "task_merge", "status": "in_progress", "title": "Resolve step-start merge conflict",
         "metadata": {}},
        {"id": "task_chain", "status": "pending", "title": "Register verification chains (blocks delivery)",
         "metadata": {"kind": "chain_authoring"}},
    ]
    assert _incomplete(tasks) == []


# ── status filter ─────────────────────────────────────────────────────────────

def test_completed_and_cancelled_structural_tasks_ignored():
    tasks = [
        {"id": "v_done", "status": "completed",
         "metadata": {"kind": "validate_api_smoke", "endpoint": {"method": "GET", "path": "/api/x"}}},
        {"id": "i_cancelled", "status": "cancelled",
         "metadata": {"kind": "implement_endpoint", "endpoint": {"method": "GET", "path": "/api/y"}}},
    ]
    # no contract tests / not implemented, but neither is pending → ignored
    assert _incomplete(tasks, endpoints={}) == []


# ── round47 shape: metadata-less id-parse fallback (old stored tasks) ─────────

def test_id_parse_fallback_for_metadata_less_validate_task():
    """round47's stored tasks carry only ``metadata.kind`` (no endpoint dict).
    The endpoint must be recovered from the munged id and matched against the
    registry's clean id via normalization."""
    tasks = [{"id": "validate.api_smoke.get._api_users_me", "status": "pending",
              "metadata": {"kind": "validate_api_smoke"}}]  # NO endpoint dict
    eps = {"GET /api/users/me": {"method": "GET", "path": "/api/users/me", "status": "implemented"}}
    cts = {"GET /api/users/me": [{"passed": True, "verdict": "pass"}]}
    assert _incomplete(tasks, endpoints=eps, contract_tests=cts) == []
    # and blocks when that endpoint has no passing test
    assert _ids(_incomplete(tasks, endpoints=eps, contract_tests={})) == {"validate.api_smoke.get._api_users_me"}


def test_round47_shape_mixed_no_false_block():
    """Mirrors the released round47 state: many validate tasks pending but all
    covered by run_validation contract tests, 0 pending impl, plus ad-hoc
    remediation tasks pending. The gate must add ZERO blockers."""
    business = ["/api/feed", "/api/posts", "/api/users/me", "/api/stories"]
    tasks, eps, cts = [], {}, {}
    for path in business:
        eid = f"GET {path}"
        eps[eid] = {"method": "GET", "path": path, "status": "implemented"}
        cts[eid] = [{"passed": True, "verdict": "pass"}]
        tasks.append({"id": f"validate.api_smoke.get.{path.replace('/', '_')}",
                      "status": "pending",
                      "metadata": {"kind": "validate_api_smoke",
                                   "endpoint": {"method": "GET", "path": path}}})
    # ad-hoc remediation tasks pending (visual + breaking-change), like round47
    tasks += [
        {"id": "task_v", "status": "pending", "metadata": {"kind": "visual_remediation"}},
        {"id": "task_bc", "status": "pending", "metadata": {"priority": "P0"}},
    ]
    assert _incomplete(tasks, endpoints=eps, contract_tests=cts) == []


# ── resilience ────────────────────────────────────────────────────────────────

def test_missing_workhub_returns_empty():
    stub = types.SimpleNamespace(hubs=types.SimpleNamespace())
    assert Orchestrator._incomplete_required_tasks(stub) == []


def test_validate_task_for_unregistered_endpoint_blocks():
    """A validate task whose endpoint isn't even in the registry can't have been
    validated → block (cannot resolve a clean id to query coverage)."""
    tasks = [{"id": "v_ghost", "status": "pending",
              "metadata": {"kind": "validate_api_smoke",
                           "endpoint": {"method": "GET", "path": "/api/ghost"}}}]
    assert _ids(_incomplete(tasks, endpoints={}, contract_tests={})) == {"v_ghost"}
