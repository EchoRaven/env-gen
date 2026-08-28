"""#1134: a probe of a DIFFERENT sandbox on the host was recorded as evidence about this one.

`test_api` accepts any URL and reports whatever answers. On a machine running more than one
sandbox that is not theoretical: :3011 here is the rydr/Uber sandbox
(`curl :3011/openapi.json` → `{"info":{"title":"uber"}}`), and netflix-local-r2's test-user
squad drove it 22 times, filing all six of its API steps as 404 "missing endpoints"
(api_passed=0, verdict PARTIAL) while the run's OWN chains were getting 201/200 on the same
paths minutes earlier. That report is a delivery-gate input.

Measured over the three runs built by the current code — each run's compose backend port vs
the ports its agents actually probed:

    netflix-local-r1   8081 → 17 probes    8080(286) 5173(45) 3000(42)
    netflix-local-r2   3000 → 10 probes    8080(64)  8000(38) 3011(22)
    smoke-notes        3000 →  9 probes    8080(45)  3011(31) 8096(7)

The app's real port is the LEAST-probed one in every run. #625 already guards the squad
against a target that is not LISTENING; this is the other half — something answered, and it
was not ours.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from env_generator.llm_generator.tools.runtime_tools import (  # noqa: E402
    foreign_target_notice_1134, _RUN_PORTS_ENV_1134,
)


class _Ports:
    """Set the run's published ports for the duration of a test."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.old = os.environ.get(_RUN_PORTS_ENV_1134)
        if self.value is None:
            os.environ.pop(_RUN_PORTS_ENV_1134, None)
        else:
            os.environ[_RUN_PORTS_ENV_1134] = self.value
        return self

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop(_RUN_PORTS_ENV_1134, None)
        else:
            os.environ[_RUN_PORTS_ENV_1134] = self.old


class TheProbeThatHitAnotherProduct(unittest.TestCase):

    def test_the_r2_case_is_called_out(self):
        """r2 published :3000 and its squad probed :3011 — the Uber sandbox."""
        with _Ports("3000,8080"):
            note = foreign_target_notice_1134(
                "http://localhost:3011/api/v1/admin/init-tenant")
        self.assertIn("#1134", note)
        self.assertIn("3011", note)
        self.assertIn("3000", note, "it must name the port that IS ours")

    def test_the_tool_description_port_is_caught_too(self):
        """:8000 is this tool's own example port — 38 probes in r2, nothing serving."""
        with _Ports("3000,8080"):
            self.assertTrue(foreign_target_notice_1134("http://localhost:8000/health"))

    def test_the_runs_own_ports_are_silent(self):
        with _Ports("3000,8080"):
            self.assertEqual(foreign_target_notice_1134("http://localhost:3000/health"), "")
            self.assertEqual(
                foreign_target_notice_1134("http://127.0.0.1:8080/browse"), "")


class ItMustNeverBlockOnWhatItDoesNotKnow(unittest.TestCase):
    """An allowlist that is best-effort must fail OPEN — #504/r81 are what false blocks cost."""

    def test_no_allowlist_means_no_opinion(self):
        with _Ports(None):
            self.assertEqual(foreign_target_notice_1134("http://localhost:3011/x"), "")

    def test_an_empty_allowlist_means_no_opinion(self):
        for empty in ("", "   ", ",,"):
            with _Ports(empty):
                self.assertEqual(foreign_target_notice_1134("http://localhost:3011/x"), "")

    def test_non_local_hosts_are_not_judged(self):
        """A deliberate external call is not a mis-aimed sandbox probe."""
        with _Ports("3000"):
            self.assertEqual(
                foreign_target_notice_1134("https://api.github.com/repos"), "")

    def test_junk_urls_do_not_raise(self):
        with _Ports("3000"):
            for bad in ("", None, "not a url", "http://", 12345):
                self.assertEqual(foreign_target_notice_1134(bad), "")


class TheNoticeReachesTheCaller(unittest.TestCase):
    """A notice only a log reader sees would not have stopped r2's six false 404s."""

    def test_test_api_attaches_it_to_the_result(self):
        from env_generator.llm_generator.tools.runtime_tools import TestAPITool
        tool = TestAPITool()
        with _Ports("3000,8080"):
            # nothing is listening on this port in the test environment; the call fails and
            # the notice must ride along on the failure just as it would on a 404.
            res = tool.execute("GET", "http://localhost:3011/api/continue-watching")
        self.assertTrue([n for n in (res.notices or []) if "#1134" in n],
                        "the caller must be told, not only the log")

    def test_the_original_body_still_runs(self):
        from env_generator.llm_generator.tools.runtime_tools import TestAPITool
        self.assertTrue(hasattr(TestAPITool, "_execute_1134"),
                        "execute is a thin wrapper over the original body")


if __name__ == "__main__":
    unittest.main()
