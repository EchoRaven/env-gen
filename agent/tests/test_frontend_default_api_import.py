"""A component that DEFAULT-imports the api module (`import api from '../services/api'`)
while api.js exports only NAMED members hard-fails the Rollup build ("default is not exported
by src/services/api.js") → frontend image won't build → docker_up FAIL → no delivery (outlook
M2, 2026-06-29). repair_frontend_default_api_import adds an aggregating default export.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import repair_frontend_default_api_import  # noqa: E402


def _fe(tmp_path, api_src, components):
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "services").mkdir(parents=True)
    (fe / "src" / "services" / "api.js").write_text(api_src, encoding="utf-8")
    (fe / "src" / "pages").mkdir(parents=True)
    for name, body in components.items():
        (fe / "src" / "pages" / name).write_text(body, encoding="utf-8")
    return fe


_NAMED_API = "export const getMessages = async () => {};\nexport const sendReply = async () => {};\n"


def test_adds_default_export_when_component_default_imports(tmp_path):
    fe = _fe(tmp_path, _NAMED_API,
             {"ReadEmail.jsx": "import api from '../services/api';\napi.getMessages();\n"})
    res = repair_frontend_default_api_import(fe)
    out = (fe / "src/services/api.js").read_text()
    assert res["repaired"] is True
    assert "export default {" in out
    assert "getMessages" in out and "sendReply" in out
    # the named exports are preserved
    assert "export const getMessages" in out


def test_noop_when_default_export_already_present(tmp_path):
    api = _NAMED_API + "\nconst api = { getMessages, sendReply };\nexport default api;\n"
    fe = _fe(tmp_path, api,
             {"X.jsx": "import api from '../services/api';\n"})
    res = repair_frontend_default_api_import(fe)
    assert res["repaired"] is False
    # the reason text was pluralised ("module(s) already have"); assert the two
    # stable halves rather than a sentence that reads the same either way
    _reason = res.get("reason", "")
    assert "already have a default export" in _reason, _reason


def test_noop_when_no_default_import(tmp_path):
    fe = _fe(tmp_path, _NAMED_API,
             {"X.jsx": "import { getMessages } from '../services/api';\ngetMessages();\n"})
    res = repair_frontend_default_api_import(fe)
    assert res["repaired"] is False
    # api.js untouched — still no spurious default export
    assert "export default" not in (fe / "src/services/api.js").read_text()


def test_idempotent(tmp_path):
    fe = _fe(tmp_path, _NAMED_API,
             {"X.jsx": "import api from '../services/api';\n"})
    repair_frontend_default_api_import(fe)
    first = (fe / "src/services/api.js").read_text()
    res2 = repair_frontend_default_api_import(fe)   # now has a default export → no-op
    assert res2["repaired"] is False
    assert (fe / "src/services/api.js").read_text() == first


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
