"""PROPOSAL #44: delivery_gate.incomplete_required_tasks must resolve a PASSING
contract-test recorded under the param-NAME-agnostic endpoint_id (``GET /api/notes/{}``)
when the pending validate_api_smoke task / registry path carry the ``{id}`` form.

Regression: smoke-notes run 2026-06-19 — backend correct, smoke tests PASSED (records
under ``GET /api/notes/{}``), but the gate looked them up as ``GET /api/notes/{id}`` →
exact-match miss → validate_api_smoke.*_{id} falsely "incomplete" → delivery blocked
forever (never delivered, hit wall-clock cap).
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    incomplete_required_tasks,
)


class _RH:
    def __init__(self, endpoints, results_by_query):
        self._eps = endpoints
        self._results = results_by_query  # exact-key map: query str -> [records]

    def get_endpoints(self):
        return self._eps

    def get_contract_test_results(self, endpoint_id):
        # Mirrors the real store: records keyed by the canonical ``{}`` form only.
        return self._results.get(endpoint_id, [])


class _WH:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self):
        return self._tasks


class _Hubs:
    def __init__(self, rh, wh):
        self.registryhub = rh
        self.workhub = wh
        self.schema_hub = None


_PASS = [{"result": {"passed": True}, "verdict": "pass"}]


def _validate_task(path):
    return {
        "id": f"validate.api_smoke.{path}",
        "kind": "validate_api_smoke",
        "status": "pending",
        "assignee": "verifier",
        "metadata": {"kind": "validate_api_smoke", "endpoint": {"method": "GET", "path": path}},
    }


class ContractTestParamKeyTests(unittest.TestCase):
    def _hubs(self, results):
        endpoints = {"GET /api/notes/{id}": {"method": "GET", "path": "/api/notes/{id}", "status": "implemented"}}
        return _Hubs(_RH(endpoints, results), _WH([_validate_task("/api/notes/{id}")]))

    def test_passing_record_under_canonical_key_resolves_the_id_task(self):
        # Record stored ONLY under the param-agnostic {} form (as the real store does).
        hubs = self._hubs({"GET /api/notes/{}": _PASS})
        incomplete = incomplete_required_tasks(hubs)
        self.assertEqual(incomplete, [], f"#44: passing {{}}-keyed test should satisfy the {{id}} task, got {incomplete}")

    def test_record_under_exact_id_key_still_resolves(self):
        # If a record happens to be stored under the {id} form, it must still match.
        hubs = self._hubs({"GET /api/notes/{id}": _PASS})
        self.assertEqual(incomplete_required_tasks(hubs), [])

    def test_genuinely_unvalidated_endpoint_still_blocks(self):
        # No passing record under EITHER form → must remain incomplete (no over-loosening).
        hubs = self._hubs({"GET /api/notes/{}": [{"result": {"passed": False}, "verdict": "fail"}]})
        incomplete = incomplete_required_tasks(hubs)
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["kind"], "validate_api_smoke")


if __name__ == "__main__":
    unittest.main()
