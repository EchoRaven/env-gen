"""#293 — runhub.start_run must point docker compose at the real compose file.

r76 live: ALL 16 runhub runs aborted with
    compose_stderr = 'no configuration file provided: not found'
→ 0 successful runs → hard deadlock (orchestrator: "run_start systematically
fails 'no configuration file provided' — cannot verify the env boots", correctly
refused force_deliver since zero successful runs = shipping broken code).

Root cause: the generated compose lives at <env_root>/docker/docker-compose.yml
(framework-wide convention — validation_runner, visual_fidelity, heal_pipeline,
docker_tools all use `-f <env_root>/docker/docker-compose.yml`). But
``start_run`` built ``ComposeLifecycle(cwd=str(generated_dir))`` with
compose_file=None, so `docker compose up` ran in the ROOT (no compose file
there). It only stayed latent because the verifier's api_smoke (validation_runner)
brings the app up on the correct path and RECORDS the run; when the orchestrator
leaned on run_start directly (r76), every attempt aborted.

start_run must resolve the compose file the same way the rest of the framework
does: docker/docker-compose.yml, falling back to a root compose file.
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.runhub import service as runhub_service  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class ResolveComposeFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="compose293_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prefers_docker_subdir(self):
        (self.tmp / "docker").mkdir()
        f = self.tmp / "docker" / "docker-compose.yml"
        f.write_text("services: {}\n")
        got = runhub_service._resolve_compose_file(str(self.tmp))
        self.assertEqual(Path(got), f)

    def test_falls_back_to_root_compose(self):
        f = self.tmp / "docker-compose.yml"
        f.write_text("services: {}\n")
        got = runhub_service._resolve_compose_file(str(self.tmp))
        self.assertEqual(Path(got), f)

    def test_none_when_absent(self):
        self.assertIsNone(runhub_service._resolve_compose_file(str(self.tmp)))


class StartRunWiresComposeFileTests(unittest.TestCase):
    """start_run's DEFAULT ComposeLifecycle must carry the resolved compose_file,
    not None — otherwise `docker compose up` runs in the wrong dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="startrun293_"))
        (self.tmp / "docker").mkdir()
        (self.tmp / "docker" / "docker-compose.yml").write_text("services: {}\n")
        self.reg = HubRegistry(self.tmp)
        self.captured = {}
        self._orig = runhub_service_compose_cls()

    def tearDown(self):
        restore_compose_cls(self._orig)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_compose_has_compose_file_set(self):
        captured = self.captured

        from multi_agent.runtime.hubs.runhub import compose as compose_mod

        class _FakeCompose:
            def __init__(self, cwd, runner=None, compose_file=None):
                captured["cwd"] = cwd
                captured["compose_file"] = compose_file

            def up(self, timeout=180.0):
                # abort immediately so start_run returns without real docker
                return compose_mod.ComposeResult(returncode=1, stderr="stub-abort")

            def down(self, timeout=60.0):
                return compose_mod.ComposeResult(returncode=0)

        compose_mod.ComposeLifecycle = _FakeCompose
        try:
            self.reg.runhub.start_run(
                branch="x", generated_dir=str(self.tmp),
                base_url="http://localhost:8000")
        finally:
            pass  # restored in tearDown

        self.assertIsNotNone(
            captured.get("compose_file"),
            "start_run default ComposeLifecycle must set compose_file (was None → "
            "'no configuration file provided')")
        self.assertTrue(
            str(captured["compose_file"]).endswith("docker/docker-compose.yml"),
            f"compose_file should point at docker/docker-compose.yml, got "
            f"{captured.get('compose_file')!r}")


def runhub_service_compose_cls():
    from multi_agent.runtime.hubs.runhub import compose as compose_mod
    return compose_mod.ComposeLifecycle


def restore_compose_cls(cls):
    from multi_agent.runtime.hubs.runhub import compose as compose_mod
    compose_mod.ComposeLifecycle = cls


if __name__ == "__main__":
    unittest.main()
