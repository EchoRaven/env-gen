r"""#638: the framework's own gap-fill shipped 21 runs with two API clients.

I had recorded this as "a content decision no offline artifact can settle". That was wrong, and
checking rather than asserting is what showed it — the same correction as #630 and #615.

Across the 45 delivered frontends, every same-stem module collision is `services/api`, and the
framework's own baseline is one side of every single one:

    13 runs   api.js + api.jsx
     6 runs   api.js + api.mjs
     2 runs   api.js + api.jsx + api.mjs      (r103: 27 B, 74 B and 5035 B of one module)

The cause is mechanical, not editorial. The gap-fill asks "does THIS FILENAME exist" —

    if p.exists() and p.read_text().strip(): continue

— but the unit JS resolves is the MODULE. A lane that writes `services/api.jsx` leaves
`services/api.js` missing, so the baseline lands beside it. It is also how #632's crash class
arises: half the pages import one client, half the other.

Skipping the write is NOT safe: projected code imports `../services/api.js` by exact filename
(r120 does, from framework pages). A re-export shim keeps every such import resolving while
leaving one implementation — the lane's.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _reexport_shim_638 as shim,
)

_NAMED = "export function getTitles() {}\nexport function listGenres() {}\n"
_WITH_DEFAULT = _NAMED + "export default { getTitles, listGenres };\n"


def _svc(tmp_path, name, body):
    d = tmp_path / "src" / "services"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return d / "api.js"


# --- when the lane already wrote the module -------------------------------------------------------

def test_a_jsx_sibling_produces_a_shim(tmp_path):
    out = shim(_svc(tmp_path, "api.jsx", _NAMED))
    assert out and "export * from './api.jsx';" in out


def test_an_mjs_sibling_works_too(tmp_path):
    out = shim(_svc(tmp_path, "api.mjs", _NAMED))
    assert "export * from './api.mjs';" in out


def test_a_default_export_is_forwarded_when_it_exists(tmp_path):
    out = shim(_svc(tmp_path, "api.jsx", _WITH_DEFAULT))
    assert "export { default } from './api.jsx';" in out


def test_a_missing_default_is_NOT_forwarded(tmp_path):
    """Re-exporting a default that does not exist is a build error — a dead app is worse than
    a duplicate module."""
    out = shim(_svc(tmp_path, "api.jsx", _NAMED))
    assert "export { default }" not in out


def test_the_shim_explains_itself(tmp_path):
    out = shim(_svc(tmp_path, "api.jsx", _NAMED))
    assert "#638" in out and "single module" in out


# --- when it must not fire -------------------------------------------------------------------------

def test_no_sibling_means_the_ordinary_baseline_is_written(tmp_path):
    d = tmp_path / "src" / "services"
    d.mkdir(parents=True)
    assert shim(d / "api.js") is None


def test_an_empty_sibling_is_not_an_implementation(tmp_path):
    assert shim(_svc(tmp_path, "api.jsx", "   \n")) is None


def test_a_non_module_baseline_is_untouched(tmp_path):
    """index.html / package.json have no module resolution — exact names must stay exact."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert shim(tmp_path / "index.html") is None
    assert shim(tmp_path / "package.json") is None


def test_a_broken_path_returns_None(tmp_path):
    assert shim(tmp_path / "nope" / "api.js") is None
    assert shim(None) is None


# --- the writer -----------------------------------------------------------------------------------

def test_the_gap_fill_prefers_the_shim_over_the_baseline_body():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs)
    i = src.index("#638: the gap-fill asks")
    block = src[i:src.index("p.parent.mkdir(parents=True, exist_ok=True)\n            _fw_write_1202cw(p, content", i)]
    assert "_shim = _reexport_shim_638(p)" in block
    assert "if _shim is not None:" in block


def test_it_is_checked_only_after_the_exact_file_is_found_missing():
    """An existing baseline with content is still left alone — the shim is the missing-file path."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs)
    assert (src.index("if p.exists() and p.read_text(encoding=\"utf-8\", errors=\"ignore\").strip():")
            < src.index("_shim = _reexport_shim_638(p)"))


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._reexport_shim_638).split())
    assert "trade a duplicate module for a dead app" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- composed with #632/#645, in the order the scaffolder actually runs them ----------------------

def _api_bag():
    return ("export function listTitles() {}\n"
            "export function getGenres() {}\n"
            "export default { listTitles, getGenres };\n")


def _tree_638(tmp_path):
    src = tmp_path / "src"
    for d in ("services", "pages", "components"):
        (src / d).mkdir(parents=True, exist_ok=True)
    (src / "services" / "api.jsx").write_text(_api_bag(), encoding="utf-8")
    (src / "pages" / "Browse.jsx").write_text(
        "import listTitles from '../services/api';\n", encoding="utf-8")
    (src / "components" / "Nav.jsx").write_text(
        "import getGenres from '../services/api.jsx';\n", encoding="utf-8")
    return src


def _gap_fill_and_repair(src):
    """The real order: the baseline gap-fill writes the shim, then the whole-tree repair runs."""
    from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
        repair_default_import_of_named_export_632 as repair,
    )
    api_js = src / "services" / "api.js"
    if not (api_js.exists() and api_js.read_text(encoding="utf-8").strip()):
        s = shim(api_js)
        if s is not None:
            api_js.write_text(s, encoding="utf-8")
    return sorted(repair(src))


def test_the_shim_and_the_bag_repair_compose(tmp_path):
    """#645's reason for existing, pinned as a PAIR: a per-fix test proves a fix, only a
    per-pair test proves the set. The suite was green with this regression in it."""
    src = _tree_638(tmp_path)
    assert _gap_fill_and_repair(src) == ["components/Nav.jsx: getGenres",
                                         "pages/Browse.jsx: listTitles"]


def test_a_second_scaffold_pass_changes_nothing(tmp_path):
    """The scaffolder runs repeatedly; the pair must settle."""
    src = _tree_638(tmp_path)
    _gap_fill_and_repair(src)
    before = {p.name: p.read_text(encoding="utf-8") for p in src.rglob("*.jsx")}
    assert _gap_fill_and_repair(src) == []
    assert {p.name: p.read_text(encoding="utf-8") for p in src.rglob("*.jsx")} == before


def test_the_shim_survives_the_repair_pass(tmp_path):
    """The repair walks every file including the shim — it must not rewrite it."""
    src = _tree_638(tmp_path)
    _gap_fill_and_repair(src)
    body = (src / "services" / "api.js").read_text(encoding="utf-8")
    assert "export * from './api.jsx';" in body


def test_the_named_import_the_repair_writes_actually_resolves(tmp_path):
    """`import { listTitles }` from the SHIM only works because the shim re-exports *."""
    src = _tree_638(tmp_path)
    _gap_fill_and_repair(src)
    assert "import { listTitles } from '../services/api';" in \
        (src / "pages" / "Browse.jsx").read_text(encoding="utf-8")
    assert "export *" in (src / "services" / "api.js").read_text(encoding="utf-8")
