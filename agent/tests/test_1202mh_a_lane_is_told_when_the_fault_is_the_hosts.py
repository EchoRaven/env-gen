"""#1202mh: when compose fails on something no lane tool can reach, the LANE
must be told -- not just the framework's own log.

`#1202de` stops the framework dispatching remediation for a host fault. It does
not reach the lanes: they read the tool result, and the tool result carried raw
compose stderr with no attribution. netflix-local-r43 is what that looks like --
six tasks for a FULL DISK, created by the orchestrator and the verifier
(measured from that run's workhub ledger), none of which any lane tool could
act on.

The port tokens are deliberately excluded: `docker/` is lane-writable and the
compose ports in a generated run are lane-authored, so re-mapping a clashing
port IS lane work. Calling it futile would be the opposite error, and one test
below pins that.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import visual_fidelity as VF  # noqa: E402


class TheSubsetCannotDriftFromTheTaxonomy(unittest.TestCase):

    def test_every_operator_only_token_is_a_known_host_fault(self):
        """The subset names tokens, so it can go stale silently. It cannot
        contain one the classifier does not recognise."""
        known = {tok for tok, _why in VF._COMPOSE_FATAL_1202DC}
        self.assertTrue(VF._OPERATOR_ONLY_1202MH <= known,
                        VF._OPERATOR_ONLY_1202MH - known)

    def test_the_port_tokens_are_deliberately_excluded(self):
        """A clashing port IS lane-actionable; `_compose_port_conflict_hint`
        already tells the lane how. This pins the judgement so a later edit has
        to argue with it rather than slip past."""
        for tok in ("port is already allocated", "bind: address already in use"):
            self.assertIn(tok, {t for t, _w in VF._COMPOSE_FATAL_1202DC})
            self.assertNotIn(tok, VF._OPERATOR_ONLY_1202MH)


class TheNoticeFiresOnTheRightText(unittest.TestCase):

    def test_a_full_disk_is_named_as_the_hosts(self):
        # the real r43 stderr shape
        msg = VF.operator_only_notice_1202mh(
            "initdb: error: could not create directory \"/var/lib/postgresql/"
            "data/pg_wal\": No space left on device")
        self.assertTrue(msg)
        self.assertIn("HOST FAULT", msg)
        self.assertIn("Do NOT open a remediation task", msg)

    def test_an_unreachable_daemon_is_named(self):
        msg = VF.operator_only_notice_1202mh(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
        self.assertIn("HOST FAULT", msg)

    def test_an_exhausted_address_pool_is_named(self):
        msg = VF.operator_only_notice_1202mh(
            "could not find an available, non-overlapping IPv4 address pool")
        self.assertIn("HOST FAULT", msg)

    def test_a_port_clash_gets_NO_notice(self):
        """Counter-proof. This is the case a lane can and should fix."""
        self.assertEqual(VF.operator_only_notice_1202mh(
            "Bind for 0.0.0.0:8000 failed: port is already allocated"), "")

    def test_an_app_build_failure_gets_NO_notice(self):
        """The false positive this must not produce: a broken Dockerfile is the
        lane's, and telling it otherwise would stall a fixable run."""
        for text in ("failed to solve: process \"/bin/sh -c npm run build\" "
                     "did not complete successfully: exit code: 1",
                     "ERROR [backend 4/7] RUN pip install -r requirements.txt",
                     "the attribute `version` is obsolete, it will be ignored",
                     ""):
            self.assertEqual(VF.operator_only_notice_1202mh(text), "", text[:40])


class TheNoticeReachesTheLaneFacingPaths(unittest.TestCase):
    """A notice that never reaches a tool result is the defect this fixes."""

    def test_docker_tools_delegates_rather_than_restating_the_tokens(self):
        from tools import docker_tools
        self.assertTrue(
            docker_tools._operator_only_notice_1202mh("No space left on device"))
        self.assertEqual(
            docker_tools._operator_only_notice_1202mh("npm ERR! build failed"), "")

    def test_the_validation_detail_carries_it(self):
        """The string `_add('docker_up', False, ...)` records is what the lanes
        read and what the remediation dispatcher classifies."""
        import ast
        import inspect
        from multi_agent.runtime import validation_runner
        tree = ast.parse(inspect.getsource(validation_runner))
        # the call must exist on the path that builds the failure detail
        names = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("operator_only_notice_1202mh", names)

    def test_the_dispatcher_and_the_notice_agree_on_what_a_host_fault_is(self):
        """#1202de refuses to dispatch; #1202mh tells the lane. If those two
        disagreed, one half of the framework would sit on its hands while the
        other told the lane to go fix it."""
        from multi_agent.runtime.remediation_dispatcher import (
            docker_up_host_fault_1202de)
        for text in ("No space left on device",
                     "Cannot connect to the Docker daemon",
                     "non-overlapping IPv4 address pool"):
            self.assertTrue(docker_up_host_fault_1202de(text), text)
            self.assertTrue(VF.operator_only_notice_1202mh(text), text)


if __name__ == "__main__":
    unittest.main()
