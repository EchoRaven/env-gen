r"""#1202rb: a stylesheet under src/ that nothing imports reaches no browser.

A .css file enters the bundle only when a module imports it, or another stylesheet `@import`s
it. Vite drops an unreferenced one in silence -- no warning, no build error, nothing missing on
disk. The page keeps its markup and loses its layout, which reads as a lane that cannot lay out
a page.

tiktok-r129: `src/visual-fixes.css`, 6,368 bytes and 48 classes, was imported by nothing --
`main.jsx` imports `index.css`, `App.jsx` imports `styles.css`, and that was all. Twenty of
`LiveDiscoverPage.jsx`'s class names exist ONLY in that file, so the visual gate photographed a
single unstyled column (its category chips ran together as "For YouFollowingGamingLifestyle...")
and scored the page 0.14, while the test-user squad reported "The LIVE discovery page layout is
severely broken, with overlapping text". tiktok-r127 shipped an orphaned `styles.css` too.

The detector was validated against those three runs before being written into the pipeline:
r127 -> ['styles.css'], r129 -> ['visual-fixes.css'], r128 -> [] (no false positive).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    import_orphan_stylesheets_1202rb, orphan_stylesheets_1202rb)


def _fe(tmp_path, files):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        f = src / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return tmp_path


R129 = {
    "main.jsx": "import React from 'react'\nimport './index.css'\n",
    "App.jsx": "import { Routes } from 'react-router-dom';\nimport './styles.css';\n\nexport default App;\n",
    "index.css": "body{margin:0}\n",
    "styles.css": ".app{color:#fff}\n",
    "visual-fixes.css": ".live-sidebar-ref{padding:16px}\n.live-main-ref{padding:18px}\n",
}


def test_the_r129_orphan_is_found(tmp_path):
    found = orphan_stylesheets_1202rb(_fe(tmp_path, R129))
    assert found["orphans"] == ["visual-fixes.css"]
    assert found["entry"] == "App.jsx"


def test_an_imported_sheet_is_not_an_orphan(tmp_path):
    files = dict(R129)
    files["App.jsx"] += "import './visual-fixes.css';\n"
    assert orphan_stylesheets_1202rb(_fe(tmp_path, files))["orphans"] == []


def test_a_css_at_import_counts_as_a_reference(tmp_path):
    """A sheet pulled in by another sheet is reachable; flagging it would be a false positive."""
    files = dict(R129)
    files["styles.css"] += "@import './visual-fixes.css';\n"
    assert orphan_stylesheets_1202rb(_fe(tmp_path, files))["orphans"] == []


def test_a_relative_path_from_a_subdirectory_counts(tmp_path):
    files = dict(R129)
    files.pop("visual-fixes.css")
    files["styles/extra.css"] = ".x{color:red}\n"
    files["pages/Page.jsx"] = "import '../styles/extra.css';\nexport default Page;\n"
    assert orphan_stylesheets_1202rb(_fe(tmp_path, files))["orphans"] == []


def test_a_clean_app_reports_nothing(tmp_path):
    """r128's shape: every sheet imported. The repair must be invisible on a healthy app."""
    files = {k: v for k, v in R129.items() if k != "visual-fixes.css"}
    assert orphan_stylesheets_1202rb(_fe(tmp_path, files))["orphans"] == []


def test_no_src_dir_is_not_a_finding(tmp_path):
    assert orphan_stylesheets_1202rb(tmp_path)["orphans"] == []


# --- the repair --------------------------------------------------------------------------

def test_the_repair_imports_it_from_the_entry(tmp_path):
    fe = _fe(tmp_path, R129)
    res = import_orphan_stylesheets_1202rb(fe)
    assert res["imported"] == ["visual-fixes.css"]
    app = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "import './visual-fixes.css';" in app


def test_the_fix_sheet_is_imported_LAST(tmp_path):
    """A sheet written beside an existing one corrects it; CSS gives the last rule the win."""
    fe = _fe(tmp_path, R129)
    import_orphan_stylesheets_1202rb(fe)
    app = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
    assert app.index("'./styles.css'") < app.index("'./visual-fixes.css'")


def test_the_repair_is_idempotent(tmp_path):
    fe = _fe(tmp_path, R129)
    import_orphan_stylesheets_1202rb(fe)
    again = import_orphan_stylesheets_1202rb(fe)
    assert again["imported"] == []
    assert (fe / "src" / "App.jsx").read_text(encoding="utf-8").count("visual-fixes.css") == 1


def test_the_repair_leaves_a_clean_app_untouched(tmp_path):
    files = {k: v for k, v in R129.items() if k != "visual-fixes.css"}
    fe = _fe(tmp_path, files)
    before = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
    assert import_orphan_stylesheets_1202rb(fe)["imported"] == []
    assert (fe / "src" / "App.jsx").read_text(encoding="utf-8") == before


def test_the_repair_is_reachable_from_the_heal_pipeline():
    """#1202 ratchet: a repair nothing calls repairs nothing."""
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "heal_pipeline.py").read_text(encoding="utf-8")
    assert "import_orphan_stylesheets_1202rb(fe)" in src
