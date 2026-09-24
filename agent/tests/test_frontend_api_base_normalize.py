"""A lane that hardcodes an absolute ``http://localhost:<in-container-port>`` API base
in browser code bypasses the nginx same-origin proxy AND targets the wrong host port
(the published mapping is e.g. ``8000:8082``), so the browser's login + every authed
call fails → the SPA can never authenticate → every protected route renders the login
form (the "hollow preview" outlook MM shipped, 2026-06-29). normalize_frontend_api_base
strips such origins to same-origin RELATIVE URLs so requests flow through the proxy.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import normalize_frontend_api_base  # noqa: E402


def _fe(tmp_path, files):
    fe = tmp_path / "app" / "frontend"
    for rel, body in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return fe


def test_bare_api_base_constant_becomes_relative(tmp_path):
    fe = _fe(tmp_path, {"src/services/api.js":
                        "const API_BASE = 'http://localhost:8082';\n"
                        "fetch(`${API_BASE}/auth/login`);\n"})
    res = normalize_frontend_api_base(fe)
    out = (fe / "src/services/api.js").read_text()
    assert "src/services/api.js" in res["normalized"]
    assert "const API_BASE = '';" in out
    # the constant is now empty → the call resolves to a same-origin relative path
    assert "${API_BASE}/auth/login" in out
    assert "localhost" not in out


def test_origin_with_path_keeps_the_path(tmp_path):
    fe = _fe(tmp_path, {"src/api.js":
                        "const u = 'http://localhost:8082/api/folders';\n"
                        "const v = \"http://127.0.0.1:5000/api/x\";\n"
                        "const w = `http://0.0.0.0:8000/auth/me`;\n"})
    normalize_frontend_api_base(fe)
    out = (fe / "src/api.js").read_text()
    assert "const u = '/api/folders';" in out
    assert 'const v = "/api/x";' in out
    assert "const w = `/auth/me`;" in out


def test_external_and_lookalike_hosts_untouched(tmp_path):
    # a real third-party origin and a host that merely STARTS with localhost must survive
    src = ("const a = 'https://api.stripe.com/v1/charges';\n"
           "const b = 'http://localhost.example.com/api/x';\n"
           "const c = 'https://my-localhost-cdn.net/asset.js';\n")
    fe = _fe(tmp_path, {"src/ext.js": src})
    res = normalize_frontend_api_base(fe)
    out = (fe / "src/ext.js").read_text()
    assert out == src                       # byte-for-byte unchanged
    assert res["normalized"] == []


def test_idempotent(tmp_path):
    fe = _fe(tmp_path, {"src/services/api.js":
                        "const API_BASE = 'http://localhost:8082';\n"})
    normalize_frontend_api_base(fe)
    first = (fe / "src/services/api.js").read_text()
    res2 = normalize_frontend_api_base(fe)  # second pass: nothing left to strip
    assert res2["normalized"] == []
    assert (fe / "src/services/api.js").read_text() == first


def test_no_port_origin_stripped(tmp_path):
    fe = _fe(tmp_path, {"src/x.js": "const u = 'http://localhost/api/x';\n"})
    normalize_frontend_api_base(fe)
    assert "const u = '/api/x';" in (fe / "src/x.js").read_text()


def test_missing_src_is_noop(tmp_path):
    res = normalize_frontend_api_base(tmp_path / "nope")
    assert res == {"normalized": []}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
