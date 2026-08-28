"""#1134b: the wrong-target allowlist was published too late to ever fire.

#1134 attaches a "you are probing someone else's app" notice to `test_api` results. Its
allowlist was populated ONLY by `gather_squad_inputs` — which runs when the test-user squad
runs, i.e. late, and not at all if the squad never runs. For most of a run the allowlist is
empty, and an empty allowlist means "unknown", which never warns.

netflix-local-r9 is the cost. Its compose was written ONCE at 10:24 and never edited (verified
in the run's own git history): 5433:5433, 3000:8081, 8080:3000. The agents nonetheless probed
:49160 and :58081 — ephemeral ports they invented — **66 times, more than the 11 probes that
reached the real backend on :3000**. `#1134 WRONG TARGET` fired 0 times and
ENVGEN_RUN_HTTP_PORTS was never mentioned in the log.

The ports are known as soon as `_generate_docker()` has allocated them, which is where this
now publishes them.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent import orchestrator as om  # noqa: E402
from env_generator.llm_generator.tools.runtime_tools import (  # noqa: E402
    foreign_target_notice_1134,
)

R9_COMPOSE = """services:
  database:
    ports:
      - "5433:5433"
  backend:
    ports:
      - "3000:8081"
  frontend:
    ports:
      - "8080:3000"
"""


class _Log:
    def info(self, *a, **k): pass
    debug = warning = error = info


def _orch(compose_text=R9_COMPOSE, write=True):
    d = Path(tempfile.mkdtemp())
    if write:
        (d / "docker").mkdir()
        (d / "docker" / "docker-compose.yml").write_text(compose_text)
    o = object.__new__(om.Orchestrator)
    o._logger = _Log()
    o.output_dir = str(d)
    return o


class _CleanEnv(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.pop("ENVGEN_RUN_HTTP_PORTS", None)

    def tearDown(self):
        os.environ.pop("ENVGEN_RUN_HTTP_PORTS", None)
        if self._prev is not None:
            os.environ["ENVGEN_RUN_HTTP_PORTS"] = self._prev


class ItPublishesTheRunsOwnPorts(_CleanEnv):

    def test_r9s_compose_yields_its_declared_host_ports(self):
        _orch()._publish_run_ports_1134b()
        self.assertEqual(
            sorted(os.environ["ENVGEN_RUN_HTTP_PORTS"].split(",")), ["3000", "5433", "8080"])

    def test_the_invented_ports_r9_probed_are_now_flagged(self):
        _orch()._publish_run_ports_1134b()
        for url in ("http://localhost:49160/title/1", "http://localhost:58081/health"):
            self.assertTrue(foreign_target_notice_1134(url), url)

    def test_the_runs_own_ports_stay_silent(self):
        _orch()._publish_run_ports_1134b()
        for url in ("http://localhost:8080/", "http://localhost:3000/api/titles"):
            self.assertFalse(foreign_target_notice_1134(url), url)


class ItNeverBreaksTheRun(_CleanEnv):
    """Best-effort by construction — a notice is not worth a raise."""

    def test_a_missing_compose_is_silent(self):
        o = _orch(write=False)
        o._publish_run_ports_1134b()
        self.assertIsNone(os.environ.get("ENVGEN_RUN_HTTP_PORTS"))

    def test_a_compose_without_port_mappings_is_silent(self):
        o = _orch(compose_text="services:\n  backend:\n    image: x\n")
        o._publish_run_ports_1134b()
        self.assertIsNone(os.environ.get("ENVGEN_RUN_HTTP_PORTS"))

    def test_an_unreadable_output_dir_does_not_raise(self):
        o = object.__new__(om.Orchestrator)
        o._logger = _Log()
        o.output_dir = None
        o._publish_run_ports_1134b()          # must not raise

    def test_an_empty_allowlist_never_warns(self):
        """Unknown is not a wrong target — #1134's own rule."""
        self.assertFalse(foreign_target_notice_1134("http://localhost:49160/x"))


class ItIsWiredAtTheEarliestPoint(unittest.TestCase):

    def test_it_runs_right_after_the_compose_is_generated(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        i = src.index("await self._generate_docker()")
        after = src[i:src.index("\n\n", i)]
        self.assertIn("_publish_run_ports_1134b()", after,
                      "the allowlist must be published where the ports become known")


if __name__ == "__main__":
    unittest.main()
