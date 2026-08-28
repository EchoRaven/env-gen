"""#1136: the port resolver read another project's container and called it this app's address.

`_service_host_port` asks `compose ps -q <service>` first. That returns EMPTY whenever this
run's stack is down — which is often — and the fallback then took the FIRST container matching
`ps -q --filter name=<service>` ANYWHERE on the host, with no check that it belongs to this
run, and reported ITS published port.

Replaying `gather_squad_inputs` against netflix-local-r2's own artifact returned
`api_base=http://localhost:3011` and `ui_base=http://localhost:8096`, while that run's compose
declares `3000:8081` and `8080:3000`. :3011 is the rydr/Uber sandbox on this host
(`/openapi.json` → `{"info":{"title":"uber"}}`); :8096 is another project's frontend. So the
FRAMEWORK is what pointed r2's test-user squad at a different product — it filed all six of
its API steps as this app's 404s (api_passed=0, verdict PARTIAL) while this run's own chains
were getting 201/200 on the same paths. In all three runs on the current code the app's real
port is the LEAST-probed one.

#962 fixed exactly this shape for `container_id()` — match the compose `config_files` label,
return nothing rather than guess. The guard never reached this second, older lookup. The fix
reuses the guarded resolver instead of keeping a second copy (#665: the copy drifts).
"""
from __future__ import annotations

import subprocess
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

from multi_agent.runtime import validation_runner as vr  # noqa: E402

COMPOSE = """services:
  backend:
    image: x
    ports:
      - "3000:8081"
  frontend:
    image: y
    ports:
      - "8080:3000"
"""


def _project():
    d = Path(tempfile.mkdtemp())
    (d / "docker").mkdir()
    cf = d / "docker" / "docker-compose.yml"
    cf.write_text(COMPOSE)
    return cf


class _Patched:
    """compose ps -q returns nothing (stack down); container_id decides the rest."""

    def __init__(self, test, cid, port_out=""):
        self.test, self.cid, self.port_out = test, cid, port_out

    def __enter__(self):
        self.old_compose = vr._compose
        self.old_run = vr.subprocess.run
        vr._compose = lambda *a, **k: subprocess.CompletedProcess([], 0, stdout="", stderr="")

        def _run(cmd, *a, **k):
            return subprocess.CompletedProcess(cmd, 0, stdout=self.port_out, stderr="")
        vr.subprocess.run = _run

        import multi_agent.runtime.container_runtime as cr
        self.cr = cr
        self.old_cid = cr.container_id
        cr.container_id = lambda *a, **k: self.cid
        return self

    def __exit__(self, *a):
        vr._compose = self.old_compose
        vr.subprocess.run = self.old_run
        self.cr.container_id = self.old_cid


class ItRefusesAStrangersPort(unittest.TestCase):

    def test_no_owned_container_falls_back_to_our_own_compose(self):
        """The r2 case: 3 containers named `backend`, none ours."""
        cf = _project()
        with _Patched(self, cid=""):
            self.assertEqual(vr._service_host_port(cf, cf.parent, "backend"), 3000)
            self.assertEqual(vr._service_host_port(cf, cf.parent, "frontend"), 8080)

    def test_it_never_reports_the_foreign_port_it_used_to(self):
        """Even when a stranger's container WOULD have published 3011."""
        cf = _project()
        with _Patched(self, cid="", port_out="8081/tcp -> 0.0.0.0:3011\n"):
            self.assertNotEqual(vr._service_host_port(cf, cf.parent, "backend"), 3011)


class ItStillUsesOurOwnRunningContainer(unittest.TestCase):
    """The fix must not blind the resolver to a legitimately running stack."""

    def test_an_owned_container_supplies_the_live_port(self):
        cf = _project()
        with _Patched(self, cid="ours", port_out="8081/tcp -> 0.0.0.0:34567\n"):
            self.assertEqual(vr._service_host_port(cf, cf.parent, "backend"), 34567)

    def test_an_owned_container_with_unreadable_ports_still_falls_back(self):
        cf = _project()
        with _Patched(self, cid="ours", port_out="(nothing parseable)"):
            self.assertEqual(vr._service_host_port(cf, cf.parent, "backend"), 3000)


class TheUnguardedLookupIsGone(unittest.TestCase):

    def test_the_resolver_no_longer_greps_the_whole_host_by_name(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
               / "validation_runner.py").read_text(encoding="utf-8")
        i = src.index("def _service_host_port(")
        body = src[i:src.index("\ndef ", i + 10)]
        self.assertNotIn('"--filter", f"name={service}"', body,
                         "the unguarded host-wide name lookup must not come back")
        self.assertIn("container_id as _cid1136", body)


if __name__ == "__main__":
    unittest.main()
