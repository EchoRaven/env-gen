"""#290 — run_start must not trust a model-supplied generated_dir.

r75 live: the orchestrator LLM called ``run_start`` with an explicit
``generated_dir`` guess (a bad relative path). run_tools only auto-derived the
env root when the arg was OMITTED (``if not generated_dir:``), so a *wrong*
value was forwarded verbatim to ``ComposeLifecycle(cwd=generated_dir)`` →
``subprocess.run(cwd=...)`` → ``FileNotFoundError: [Errno 2] No such file or
directory: 'app'`` / ``'docker'``. The run crashed, M2 never got a clean
RunHub validation run, and delivery fell back to the force_deliver bypass.

``generated_dir`` is framework CONTEXT the model cannot know (the tool schema
even marks it auto-derived) and base_dir is the single authoritative env root
for the process. The tool must therefore resolve it from base_dir and never let
a model guess (which on a shared box could even name a *different* env)
override it.
"""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.run_tools import RunStartTool  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RunStartGeneratedDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="run_start_290_"))
        # #1202ln: a real env root always carries docker/docker-compose.yml, and run_start now
        # resolves the backend's HOST port from it instead of defaulting to :8000 (which in
        # tiktok-r121 was the database — seven runs aborted probing Postgres for /health).
        # A bare tmp dir was never a faithful env root; giving it one keeps #290's property
        # under test and pins the resolution in the same place.
        (self.tmp / "docker").mkdir(parents=True, exist_ok=True)
        (self.tmp / "docker" / "docker-compose.yml").write_text(
            "services:\n"
            "  database:\n"
            "    ports:\n"
            "      - \"8000:8000\"\n"
            "  backend:\n"
            "    ports:\n"
            "      - \"3001:8000\"\n", encoding="utf-8")
        self.reg = HubRegistry(self.tmp)
        self.captured = {}

        def _fake_start_run(*, branch, generated_dir, base_url, agent, **kwargs):
            self.captured["generated_dir"] = generated_dir
            self.captured["base_url"] = base_url
            return {"id": "run_fake", "status": "completed", "fail_count": 0}

        self.reg.runhub.start_run = _fake_start_run
        self.tool = RunStartTool(agent_id="orch", hub_workspace=self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bad_model_supplied_generated_dir_is_overridden_to_base_dir(self) -> None:
        # The exact r75 failure: a bad relative guess like 'app'.
        result = _run_async(self.tool._run(branch="feature/x", generated_dir="app"))
        self.assertTrue(result.success)
        self.assertEqual(self.captured["generated_dir"], str(self.tmp),
                         "a model-supplied generated_dir must NOT reach start_run — "
                         "the authoritative base_dir must win")

    def test_omitted_generated_dir_uses_base_dir(self) -> None:
        result = _run_async(self.tool._run(branch="feature/x"))
        self.assertTrue(result.success)
        self.assertEqual(self.captured["generated_dir"], str(self.tmp))

    def test_wrong_but_existing_absolute_dir_still_overridden(self) -> None:
        # On a shared box the model could name a *different* env's real dir.
        other = Path(tempfile.mkdtemp(prefix="other_env_290_"))
        try:
            result = _run_async(self.tool._run(branch="feature/x",
                                               generated_dir=str(other)))
            self.assertTrue(result.success)
            self.assertEqual(self.captured["generated_dir"], str(self.tmp),
                             "even an existing-but-wrong dir must not override base_dir")
        finally:
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


    def test_the_base_url_comes_from_the_compose_file_not_a_default(self) -> None:
        """#1202ln: the same "the model cannot know this" argument #290 makes for
        generated_dir. :8000 is this fixture's DATABASE, exactly as it was r121's."""
        result = _run_async(self.tool._run(branch="feature/x",
                                           base_url="http://localhost:8000"))
        self.assertTrue(result.success)
        self.assertEqual(self.captured["base_url"], "http://localhost:3001")
