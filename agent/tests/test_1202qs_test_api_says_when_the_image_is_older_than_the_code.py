"""#1202qs: a 4xx/5xx from a stack whose image predates the source says so, so a lane does not
rewrite code or contract to match the old binary (tiktok-r127 23:22)."""
import io
import urllib.error
import urllib.request
from types import SimpleNamespace

from env_generator.llm_generator.tools import runtime_tools as RT


class _Reg:
    def get_endpoints(self):
        return {}


def _run(monkeypatch, verdict, code=401):
    def _raise(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b'{"detail":"x"}'))
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    monkeypatch.setattr(RT, "_contract_says_public_1202qp", lambda *a, **k: None)
    import env_generator.llm_generator.multi_agent.runtime.chain_executor as CE
    monkeypatch.setattr(CE, "build_currency_1202ex", lambda base: {"verdict": verdict})
    tool = RT.TestAPITool()
    tool.set_agent(SimpleNamespace(_hubs=SimpleNamespace(registryhub=_Reg(), base_dir="/tmp/x")))
    return tool.execute(method="GET", url="http://localhost:8008/api/videos")


def test_a_changed_source_is_flagged_on_a_401(monkeypatch):
    assert "may come from the OLD code" in _run(monkeypatch, "changed").error_message


def test_a_500_is_flagged_too(monkeypatch):
    assert "may come from the OLD code" in _run(monkeypatch, "changed", code=500).error_message


def test_a_current_image_adds_nothing(monkeypatch):
    assert "OLD code" not in _run(monkeypatch, "current").error_message
