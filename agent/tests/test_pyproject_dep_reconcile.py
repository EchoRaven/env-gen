"""The rendered pyproject carries the lane's third-party imports (run-29, 2026-07-01).

The lane wrote `import asyncpg` in custom_routes.py but the framework re-asserted the STATIC
_PYPROJECT byte-identically each pass → asyncpg never installed → `from custom_routes import
router` raised ModuleNotFoundError → the except-ImportError swallow dropped ALL custom routes
SILENTLY: auth/me 404 → login-wall/hollow browser verdict, while business_chain stayed green
on projected handlers. render_pyproject unions the base deps with the third-party modules the
backend source actually imports (stdlib + sibling-local skipped; known aliases translated),
and the include template now logs a nested broken import LOUDLY instead of hiding it.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _CUSTOM_ROUTES_INCLUDE, _lane_third_party_imports, render_pyproject)


def _be(tmp_path, files):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    for name, src in files.items():
        (be / name).write_text(src, encoding="utf-8")
    return be


def test_run29_asyncpg_is_picked_up(tmp_path):
    be = _be(tmp_path, {
        "custom_routes.py": "import asyncpg\nimport os\nimport jwt\nfrom fastapi import APIRouter\n",
        "database.py": "import sqlalchemy\n",
        "main.py": "from fastapi import FastAPI\nimport custom_routes\n",
    })
    extras = _lane_third_party_imports(be)
    assert extras == ["asyncpg"]                      # stdlib/base/local all filtered
    py = render_pyproject(be)
    assert '"asyncpg",' in py and '"fastapi>=0.115",' in py


def test_alias_translation_and_local_stdlib_filtering(tmp_path):
    be = _be(tmp_path, {
        "custom_routes.py": ("import yaml\nimport psycopg2\nfrom PIL import Image\n"
                             "import models\nimport json, uuid\nimport httpx\n"),
        "models.py": "x = 1\n",
    })
    extras = _lane_third_party_imports(be)
    assert extras == ["beautifulsoup4"] if False else True  # (guard against typo drift)
    assert set(extras) == {"pyyaml", "psycopg2-binary", "pillow", "httpx"}


def test_no_lane_extras_returns_base_verbatim(tmp_path):
    be = _be(tmp_path, {"main.py": "from fastapi import FastAPI\nimport os\n"})
    from multi_agent.runtime.backend_skeleton import _PYPROJECT
    assert render_pyproject(be) == _PYPROJECT
    assert render_pyproject(tmp_path / "missing") == _PYPROJECT


def test_rendered_pyproject_stays_valid_toml(tmp_path):
    import tomllib
    be = _be(tmp_path, {"custom_routes.py": "import asyncpg\nimport redis\n"})
    data = tomllib.loads(render_pyproject(be))
    deps = data["project"]["dependencies"]
    assert "asyncpg" in deps and "redis" in deps and any(d.startswith("fastapi") for d in deps)


def test_include_template_logs_nested_import_error():
    """Exec the include template with a custom_routes that raises a NESTED ImportError —
    the error must be LOGGED (not swallowed); a missing custom_routes stays silent."""
    import logging
    tmpl = (_CUSTOM_ROUTES_INCLUDE
            .replace("__NESTED_CHILD_RESOURCES__", "[]")
            .replace("__OWNER_SCOPED_RESOURCES__", "[]")
            # added to the template later; without it the exec dies on NameError
            .replace("__DEGENERATE_RESOURCES__", "[]"))

    class _App:
        routes = []
        def include_router(self, r): pass
        def get(self, path): return lambda fn: fn

    records = []
    h = logging.Handler()
    h.emit = lambda rec: records.append(rec.getMessage())
    logging.getLogger("custom_routes").addHandler(h)
    try:
        # a fake custom_routes whose import dies on a MISSING NESTED module
        import types
        broken = types.ModuleType("custom_routes")
        sys.modules.pop("custom_routes", None)

        class _Finder:
            def find_module(self, name, path=None):
                return self if name == "custom_routes" else None
            def load_module(self, name):
                raise ModuleNotFoundError("No module named 'asyncpg'", name="asyncpg")
        f = _Finder()
        sys.meta_path.insert(0, f)
        try:
            ns = {"app": _App(), "Depends": lambda x: None, "get_current_user": lambda: None}
            exec(compile(tmpl, "inc.py", "exec"), ns)
        finally:
            sys.meta_path.remove(f)
            sys.modules.pop("custom_routes", None)
        assert any("BROKEN IMPORT" in m for m in records), records
    finally:
        logging.getLogger("custom_routes").removeHandler(h)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
