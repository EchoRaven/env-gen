"""`export default { api };` wrapper breaks every default-import member call (run-35).

api.js declared `export const api = {...}` then ended `export default { api };` — pages doing
`import api from '../services/api'; api.getMessages(...)` hit `TypeError: … is not a
function` → blank inbox (live, run-35 v1.3.0). The repair rewrites the single-identifier
wrapper to `export default api;` ONLY when that identifier is itself a top-level export in
the file. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import repair_frontend_default_export_wrapper  # noqa: E402


def _api(tmp_path, body):
    d = tmp_path / "src" / "services"
    d.mkdir(parents=True)
    f = d / "api.js"
    f.write_text(body, encoding="utf-8")
    return f


def test_run35_wrapper_unwrapped(tmp_path):
    f = _api(tmp_path, "export const api = {\n  getMessages: () => [],\n};\n\nexport default { api };\n")
    out = repair_frontend_default_export_wrapper(tmp_path)
    assert "services/api.js" in out["repaired"]
    txt = f.read_text(encoding="utf-8")
    assert "export default api;" in txt and "export default { api }" not in txt
    # idempotent
    assert repair_frontend_default_export_wrapper(tmp_path)["repaired"] == []


def test_wrapper_of_unexported_local_left_alone(tmp_path):
    body = "const helpers = { a: 1 };\nexport default { helpers };\n"
    f = _api(tmp_path, body)
    assert repair_frontend_default_export_wrapper(tmp_path)["repaired"] == []
    assert f.read_text(encoding="utf-8") == body


def test_multi_key_object_left_alone(tmp_path):
    body = "export const api = {};\nexport const auth = {};\nexport default { api, auth };\n"
    f = _api(tmp_path, body)
    assert repair_frontend_default_export_wrapper(tmp_path)["repaired"] == []
    assert f.read_text(encoding="utf-8") == body


def test_proper_default_export_untouched(tmp_path):
    body = "export const api = {};\nexport default api;\n"
    f = _api(tmp_path, body)
    assert repair_frontend_default_export_wrapper(tmp_path)["repaired"] == []
    assert f.read_text(encoding="utf-8") == body


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
