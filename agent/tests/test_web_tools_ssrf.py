"""SSRF guard tests for WebFetchTool (Cutover 18)."""

import asyncio
import sys
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


class WebFetchSSRFTests(unittest.TestCase):
    def setUp(self) -> None:
        from tools.web_tools import WebFetchTool
        self.tool = WebFetchTool()

    def _reject(self, url: str, label: str) -> None:
        result = _run_async(self.tool.execute(url=url))
        self.assertFalse(result.success,
                          f"expected SSRF rejection for {label} ({url})")

    def test_rejects_localhost_by_name(self) -> None:
        self._reject("http://localhost/", "localhost")

    def test_rejects_127_loopback(self) -> None:
        self._reject("http://127.0.0.1/", "127.0.0.1")

    def test_rejects_aws_metadata_ip(self) -> None:
        self._reject("http://169.254.169.254/latest/meta-data/",
                      "aws-metadata")

    def test_rejects_rfc1918_10(self) -> None:
        self._reject("http://10.0.0.5/", "10/8")

    def test_rejects_rfc1918_192_168(self) -> None:
        self._reject("http://192.168.1.1/", "192.168/16")

    def test_rejects_rfc1918_172_16(self) -> None:
        self._reject("http://172.16.0.1/", "172.16/12")

    def test_rejects_ipv6_loopback(self) -> None:
        self._reject("http://[::1]/", "ipv6 loopback")

    def test_rejects_file_scheme(self) -> None:
        self._reject("file:///etc/passwd", "file://")

    def test_rejects_ftp_scheme(self) -> None:
        self._reject("ftp://example.com/", "ftp://")

    def test_allows_public_https_url_does_not_short_circuit(self) -> None:
        # We don't actually make the network call — we just verify the
        # SSRF guard didn't reject up front. Mock urlopen to return a
        # minimal HTTP response stub compatible with _read_url's expectations.
        class _Headers:
            def __init__(self, items):
                self._items = items
            def get(self, key, default=None):
                return self._items.get(key.lower(), default)
            def get_content_charset(self):
                return "utf-8"
        class _Resp:
            headers = _Headers({"content-type": "text/html"})
            def read(self, n=-1):
                return b"<html><title>ok</title><body>hi</body></html>"
            def geturl(self):
                return "https://example.com/"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
        with patch("tools.web_tools.urllib.request.urlopen", return_value=_Resp()):
            result = _run_async(self.tool.execute(url="https://example.com/"))
        self.assertTrue(result.success, f"public URL should be allowed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
