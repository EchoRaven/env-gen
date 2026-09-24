"""The framework nginx config must cache Vite's hashed /assets immutably and NEVER cache
index.html — eliminating the stale-bundle / "my change doesn't show" phantom-bug class
(PIPELINE.md §5.3/§9). LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402


def test_hashed_assets_are_immutable():
    ng = fs._BASELINE_NGINX
    assert "location /assets/" in ng
    assert "immutable" in ng and "max-age=31536000" in ng


def test_index_and_spa_routes_are_no_store():
    ng = fs._BASELINE_NGINX
    # the SPA fallback location must carry no-store so a stale index can't reference an old JS hash
    assert "try_files $uri $uri/ /index.html" in ng
    assert "no-store" in ng


def test_nginx_is_registered_in_the_baseline_with_the_policy():
    bf = fs._BASELINE_FILES
    assert "nginx.conf.template" in bf
    conf = bf["nginx.conf.template"]
    assert "immutable" in conf and "no-store" in conf


def test_nginx_braces_balanced():
    ng = fs._BASELINE_NGINX
    assert ng.count("{") == ng.count("}")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
