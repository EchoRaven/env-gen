"""#499 (netflix r67, live): repair_frontend_default_api_import must add the aggregated default
export to the module ACTUALLY default-imported — not just src/services/api.js.

r67 wedged here: ProfileMenu.jsx did ``import api from '../services/api.mjs'`` while api.mjs had 27
NAMED exports and no default. The old heal hard-targeted api.js, so api.mjs stayed default-less →
vite build kept HARD-failing ("default is not exported") → docker_up FAIL → build:frontend red →
verification_checklist_not_ready → no delivery. The frontend lane burned 6+ dispatches / ~20 min on
the 1-line bug. The heal now resolves the import specifier to the real module and fixes THAT file.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_frontend_default_api_import,
)

_NAMED_API = (
    "export function getTenant() {}\n"
    "export function clearAuth() {}\n"
    "export const getCurrentUser = () => {};\n"
)


def _mk(tmp_path: Path, files: dict) -> Path:
    fe = tmp_path / "frontend"
    for rel, body in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return fe


def test_mjs_sibling_gets_default_export(tmp_path):
    # the exact r67 shape: default-import of api.mjs (named-only)
    fe = _mk(tmp_path, {
        "src/services/api.mjs": _NAMED_API,
        "src/components/ProfileMenu.jsx": "import api from '../services/api.mjs';\nexport default function P(){return null;}\n",
    })
    res = repair_frontend_default_api_import(fe)
    assert res.get("repaired") is True, res
    mjs = (fe / "src/services/api.mjs").read_text()
    assert "export default {" in mjs, mjs
    assert "clearAuth" in mjs.split("export default")[1]  # aggregated names present in the default


def test_classic_api_js_no_extension_unregressed(tmp_path):
    # the pre-#499 common case: import api from '../services/api' → resolves to api.js
    fe = _mk(tmp_path, {
        "src/services/api.js": _NAMED_API,
        "src/components/Nav.jsx": "import api from '../services/api';\n",
    })
    res = repair_frontend_default_api_import(fe)
    assert res.get("repaired") is True, res
    assert "export default {" in (fe / "src/services/api.js").read_text()


def test_only_imported_module_is_touched(tmp_path):
    # both api.js and api.mjs exist; a component default-imports ONLY api.mjs → api.js untouched
    fe = _mk(tmp_path, {
        "src/services/api.js": _NAMED_API,
        "src/services/api.mjs": _NAMED_API,
        "src/components/ProfileMenu.jsx": "import api from '../services/api.mjs';\n",
    })
    repair_frontend_default_api_import(fe)
    assert "export default" in (fe / "src/services/api.mjs").read_text()
    assert "export default" not in (fe / "src/services/api.js").read_text()


def test_already_has_default_is_noop(tmp_path):
    body = _NAMED_API + "\nexport default { clearAuth };\n"
    fe = _mk(tmp_path, {
        "src/services/api.mjs": body,
        "src/components/ProfileMenu.jsx": "import api from '../services/api.mjs';\n",
    })
    res = repair_frontend_default_api_import(fe)
    assert res.get("repaired") is False, res
    # exactly one default export (not double-appended)
    assert (fe / "src/services/api.mjs").read_text().count("export default") == 1


def test_no_default_import_is_noop(tmp_path):
    fe = _mk(tmp_path, {
        "src/services/api.mjs": _NAMED_API,
        "src/components/Nav.jsx": "import { clearAuth } from '../services/api.mjs';\n",
    })
    res = repair_frontend_default_api_import(fe)
    assert res.get("repaired") is False, res
    assert "export default" not in (fe / "src/services/api.mjs").read_text()


def test_empty_named_module_gets_empty_default(tmp_path):
    fe = _mk(tmp_path, {
        "src/services/api.mjs": "// no exports here\n",
        "src/components/ProfileMenu.jsx": "import api from '../services/api.mjs';\n",
    })
    res = repair_frontend_default_api_import(fe)
    assert res.get("repaired") is True, res
    assert "export default {}" in (fe / "src/services/api.mjs").read_text()


def test_idempotent(tmp_path):
    fe = _mk(tmp_path, {
        "src/services/api.mjs": _NAMED_API,
        "src/components/ProfileMenu.jsx": "import api from '../services/api.mjs';\n",
    })
    repair_frontend_default_api_import(fe)
    repair_frontend_default_api_import(fe)  # second run must not double-append
    assert (fe / "src/services/api.mjs").read_text().count("export default") == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
