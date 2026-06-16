"""Skeleton tests for RunHub service (Task 4); start_run tests added in Task 5."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.service import RunHub  # noqa: E402
from multi_agent.runtime.hubs.runhub.stores import RunHubStores  # noqa: E402


class RunHubSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runhub_stores_have_runs_json(self) -> None:
        stores = RunHubStores.create(self.tmp / "shared" / "hubs")
        self.assertTrue(hasattr(stores, "runs"))
        # JsonStore exposes value() returning dict
        self.assertEqual(stores.runs.value(), {})

    def test_runhub_service_init_creates_store_dir(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        self.assertEqual(rh.list_runs(), [])

    def test_record_run_persists_and_get_run_reads_back(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        run = rh.record_run(branch="feature/x", generated_dir="/tmp/gen", agent="orch")
        self.assertIn("id", run)
        self.assertEqual(run["branch"], "feature/x")
        self.assertEqual(run["status"], "starting")
        self.assertEqual(rh.get_run(run["id"])["id"], run["id"])
        self.assertEqual(len(rh.list_runs()), 1)

    def test_update_run_status_transitions_state(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        run = rh.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        updated = rh.update_run_status(run["id"], status="healthy", agent="runhub")
        self.assertEqual(updated["status"], "healthy")
        self.assertIn("updated_at", updated)

    def test_list_runs_sorted_most_recent_first(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        a = rh.record_run(branch="a", generated_dir="/tmp/g", agent="orch")
        b = rh.record_run(branch="b", generated_dir="/tmp/g", agent="orch")
        c = rh.record_run(branch="c", generated_dir="/tmp/g", agent="orch")
        ids = [r["id"] for r in rh.list_runs()]
        self.assertEqual(ids, [c["id"], b["id"], a["id"]])

    def test_hub_registry_exposes_runhub(self) -> None:
        reg = HubRegistry(self.tmp)
        self.assertIsNotNone(reg.runhub)
        self.assertEqual(reg.runhub.list_runs(), [])


class RunHubStartRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_start_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wire_endpoint(self, method, path, status="defined", auth_required=False, provider="backend"):
        self.reg.registryhub.register_endpoint(method, path, schema={},
                                          provider=provider, agent=provider,
                                          status=status, auth_required=auth_required)

    def _fake_compose(self, up_rc=0, down_rc=0):
        class _Compose:
            def __init__(s):
                s.up_called = False
                s.down_called = False
            def up(s, timeout=180.0):
                s.up_called = True
                from multi_agent.runtime.hubs.runhub.compose import ComposeResult
                return ComposeResult(returncode=up_rc, stdout="up ok" if up_rc == 0 else "", stderr="")
            def down(s, timeout=60.0):
                s.down_called = True
                from multi_agent.runtime.hubs.runhub.compose import ComposeResult
                return ComposeResult(returncode=down_rc)
        return _Compose()

    def _fake_healthcheck(self, healthy=True):
        from multi_agent.runtime.hubs.runhub.compose import HealthcheckResult
        class _HC:
            def wait(s):
                return HealthcheckResult(
                    healthy=healthy, status_code=200 if healthy else 503,
                    attempts=1, elapsed_s=0.1)
        return _HC()

    def _fake_probe_runner(self, responses_by_url):
        """responses_by_url: {url: (status_code, body)} or {url: ("error", "timeout")}"""
        from unittest.mock import MagicMock
        def runner(plan):
            resp = responses_by_url.get(plan.url, (200, ""))
            if isinstance(resp, tuple) and resp[0] == "error":
                return {"status_code": None, "body_excerpt": "",
                        "transport_error": resp[1], "latency_ms": 0.0}
            sc, body = resp
            return {"status_code": sc, "body_excerpt": body,
                    "transport_error": None, "latency_ms": 10.5}
        return runner

    def test_start_run_happy_path_all_endpoints_pass(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        self._wire_endpoint("GET", "/api/health")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(healthy=True),
            probe_runner=self._fake_probe_runner({}),  # all 200
        )
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["fail_count"], 0)
        self.assertEqual(len(run["probes"]), 2)
        self.assertTrue(all(p["verdict"] == "pass" for p in run["probes"]))
        self.assertTrue(compose.up_called and compose.down_called)

    def test_start_run_compose_up_failure_aborts(self) -> None:
        compose = self._fake_compose(up_rc=1)
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "aborted")
        self.assertTrue(compose.down_called, "down() must run even after up() failure")

    def test_start_run_healthcheck_failure_aborts_before_probes(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(healthy=False),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "aborted")
        self.assertEqual(run["probes"], [])  # never probed
        self.assertTrue(compose.down_called)

    def test_start_run_5xx_probe_publishes_run_failed_event(self) -> None:
        self._wire_endpoint("GET", "/api/feed", provider="backend")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({
                "http://localhost:8000/api/feed": (500, "server error"),
            }),
        )
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["fail_count"], 1)
        events = list(self.reg.eventhub.list_events_by_type("run_failed"))
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["severity"], "P1")
        self.assertEqual(payload["bug_artifacts"]["affected_endpoint"], "GET /api/feed")
        self.assertEqual(payload["bug_artifacts"]["actual"], "500")
        self.assertEqual(payload["bug_artifacts"]["run_id"], run["id"])

    def test_start_run_publishes_run_completed_event_at_end(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        compose = self._fake_compose()
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        events = list(self.reg.eventhub.list_events_by_type("run_completed"))
        self.assertEqual(len(events), 1)

    def test_start_run_skipped_endpoints_dont_count_as_failures(self) -> None:
        self._wire_endpoint("DELETE", "/api/feed/1")  # destructive -> skip
        self._wire_endpoint("POST", "/api/login", auth_required=True)  # auth -> skip
        self._wire_endpoint("GET", "/api/health")  # probed
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "completed")
        verdicts = [p["verdict"] for p in run["probes"]]
        self.assertIn("skipped", verdicts)
        self.assertIn("pass", verdicts)
        self.assertNotIn("fail", verdicts)


if __name__ == "__main__":
    unittest.main()
