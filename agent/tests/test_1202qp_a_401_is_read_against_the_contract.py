"""#1202qp: test_api's 401 hint consults the contract. When the endpoint is registered public, it
says the served app disagrees with the contract instead of "a tokenless request is SUPPOSED to be
rejected" (tiktok-r127: the backend made the public feed auth_required to match a stale 401)."""
import asyncio
import io
import urllib.error
from types import SimpleNamespace

from env_generator.llm_generator.tools import runtime_tools as RT


class _Reg:
    def __init__(self, auth):
        self._eps = {"GET /api/videos/{}/comments": {
            "method": "GET", "path": "/api/videos/{id}/comments",
            "schema": {"auth_required": auth}, "metadata": {"auth_required": True}}}

    def get_endpoints(self):
        return self._eps


def _run(monkeypatch, auth):
    def _raise(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"missing token"}'))
    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", _raise)
    tool = RT.TestAPITool()
    tool.set_agent(SimpleNamespace(_hubs=SimpleNamespace(registryhub=_Reg(auth))))
    return tool.execute(method="GET", url="http://localhost:8008/api/videos/7/comments")


def test_a_public_endpoint_answering_401_is_called_a_contract_mismatch(monkeypatch):
    r = _run(monkeypatch, False)
    assert "CONTRACT declares GET /api/videos/{id}/comments PUBLIC" in r.error_message
    assert "SUPPOSED" not in r.error_message


def test_a_protected_endpoint_keeps_the_auth_round_trip_hint(monkeypatch):
    r = _run(monkeypatch, True)
    assert "SUPPOSED" in r.error_message
