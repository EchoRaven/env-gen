"""delivery_gate.incomplete_required_tasks: an implement_endpoint task is COVERED
when api_smoke PROVED the endpoint works (a passing contract-test record), not only
when the lane flipped the registry status to implemented/tested.

Regression: youtube run #19 DEADLOCK (2026-06-21) — the framework projects a working
handler for every registered endpoint and api_smoke probed + passed all 33, recording
a passing contract-test per endpoint, but the lanes never called
register_endpoint(status='implemented') → 32 endpoints stayed 'defined' → their
impl tasks blocked delivery forever while the idle lanes couldn't self-heal.

LOCAL-ONLY (agent/tests/ gitignored).
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    incomplete_required_tasks,
)


class _RH:
    def __init__(self, endpoints, results_by_query):
        self._eps = endpoints
        self._results = results_by_query

    def get_endpoints(self):
        return self._eps

    def get_contract_test_results(self, endpoint_id):
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
_FAIL = [{"result": {"passed": False}, "verdict": "fail"}]


def _impl_task(method, path):
    mid = path.strip("/").replace("/", "_")
    return {
        "id": f"impl.endpoint.{method.lower()}._{mid}",
        "kind": "implement_endpoint",
        "status": "pending",
        "metadata": {"kind": "implement_endpoint",
                     "endpoint": {"method": method, "path": path}},
    }


class ImplEndpointApiSmokeCoverageTests(unittest.TestCase):
    def _hubs(self, status, results):
        eps = {"GET /api/videos": {"method": "GET", "path": "/api/videos", "status": status}}
        return _Hubs(_RH(eps, results), _WH([_impl_task("GET", "/api/videos")]))

    def test_defined_endpoint_with_passing_apismoke_is_covered(self):
        # the run #19 deadlock case: status='defined' but api_smoke passed
        hubs = self._hubs("defined", {"GET /api/videos": _PASS})
        self.assertEqual(incomplete_required_tasks(hubs), [],
                         "a passing contract-test must cover the impl_endpoint task")

    def test_implemented_status_still_covered(self):
        hubs = self._hubs("implemented", {})
        self.assertEqual(incomplete_required_tasks(hubs), [])

    def test_defined_no_record_still_blocks(self):
        # no evidence at all → genuinely incomplete (no over-loosening)
        hubs = self._hubs("defined", {})
        inc = incomplete_required_tasks(hubs)
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["kind"], "implement_endpoint")

    def test_defined_failing_record_still_blocks(self):
        hubs = self._hubs("defined", {"GET /api/videos": _FAIL})
        inc = incomplete_required_tasks(hubs)
        self.assertEqual(len(inc), 1)


if __name__ == "__main__":
    unittest.main()
