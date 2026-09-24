"""SSRF guard tests for SaveImageTool (Cutover 18).

The guard must short-circuit BEFORE any aiohttp/network call, so we
patch aiohttp.ClientSession to blow up if it is ever instantiated for
a rejected URL.
"""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_tool(tmp):
    from tools.image_search_tools import SaveImageTool
    from workspace import Workspace
    return SaveImageTool(workspace=Workspace(Path(tmp)))


class _NetworkAccessedError(AssertionError):
    """Raised if the SSRF guard fails to short-circuit before aiohttp use."""


def _explode(*args, **kwargs):  # pragma: no cover - only fires on guard miss
    raise _NetworkAccessedError(
        "aiohttp was used despite SSRF guard — guard did not short-circuit"
    )


class SaveImageSSRFTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="save_img_ssrf_"))
        self.tool = _make_tool(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reject(self, url, label):
        # Patch aiohttp's session entry points so that the test fails
        # loudly if the guard ever lets the request hit the network layer.
        import aiohttp
        with patch.object(aiohttp, "ClientSession", side_effect=_explode), \
                patch.object(aiohttp, "TCPConnector", side_effect=_explode):
            result = _run_async(self.tool.execute(url=url, path="test.png"))
        self.assertFalse(
            result.success,
            f"expected SSRF rejection for {label} ({url})",
        )
        # Verify the rejection reason looks like the guard, not some
        # unrelated failure further down the pipeline.
        self.assertIn(
            "refused for safety",
            (result.error_message or "").lower(),
            f"expected guard-style rejection for {label}; "
            f"got: {result.error_message!r}",
        )

    def test_rejects_localhost(self):
        self._reject("http://localhost/x.png", "localhost")

    def test_rejects_aws_metadata(self):
        self._reject("http://169.254.169.254/x.png", "aws-metadata")

    def test_rejects_rfc1918(self):
        self._reject("http://10.0.0.1/x.png", "rfc1918")

    def test_rejects_file_scheme(self):
        self._reject("file:///etc/passwd", "file scheme")


if __name__ == "__main__":
    unittest.main()
