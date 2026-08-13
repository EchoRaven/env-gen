r"""#632: the shipped crash the P0 records kept describing.

Auditing the DELIVERED apps of all 45 kept runs, not the logs: a page binds a name with a DEFAULT
import while the module's default export is an object literal listing every function. The binding
is the whole object, so the first call throws — which is verbatim the bug text on file:

    "default-imported listTitles is an object, not a function"
    "Landing page (/) crashes with 'Cn is not a function' — blank render blocks entire landing"

    21 crash sites in 21 files across 6 of 45 runs
    r105 alone ships 8 — BrowseHomePage, MoviesPage, ShowsPage, GamesPage, MyListPage,
                          NewAndPopularPage, BrowseByLanguagesPage

Every one is a page that throws on load, in a delivered app.

The rewrite is provable rather than a guess: in **21 of 21** the symbol is ALSO a named export of
the same module, so `import { X } from …` is valid by construction. Getting there took two wrong
scans first, both recorded in the handoff — a resolver that only collected `.js`/`.jsx` invented
18 phantom "missing module" hits on a real `api.mjs`, and the first version of this very check
asked "does the target have a default export?" (it does — that is the whole point) instead of
"is the imported name a KEY of it?".
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_default_import_of_named_export_632 as repair,
)

_BAG = """\
export function listTitles() { return 1; }
export function getGenres() { return 2; }
export default { listTitles, getGenres };
"""


def _tree(tmp_path, files):
    src = tmp_path / "src"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return src


# --- the repair -------------------------------------------------------------------------------

def test_a_default_import_of_a_bag_key_becomes_a_named_import(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import listTitles from '../services/api';\n"})
    assert repair(src) == ["pages/Browse.jsx: listTitles"]
    assert "import { listTitles } from '../services/api';" in \
        (src / "pages/Browse.jsx").read_text(encoding="utf-8")


def test_an_explicit_extension_resolves_too(tmp_path):
    src = _tree(tmp_path, {
        "services/api.jsx": _BAG,
        "pages/Browse.jsx": 'import getGenres from "../services/api.jsx";\n'})
    assert repair(src) == ["pages/Browse.jsx: getGenres"]


def test_several_files_are_all_repaired(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/A.jsx": "import listTitles from '../services/api';\n",
        "pages/B.jsx": "import getGenres from '../services/api';\n"})
    assert sorted(repair(src)) == ["pages/A.jsx: listTitles", "pages/B.jsx: getGenres"]


def test_the_rest_of_the_line_and_file_is_untouched(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import React from 'react';\n"
                            "import listTitles from '../services/api';\n"
                            "export default function Browse() { return null; }\n"})
    out = (src / "pages/Browse.jsx").read_text(encoding="utf-8")
    repair(src)
    new = (src / "pages/Browse.jsx").read_text(encoding="utf-8")
    assert "import React from 'react';" in new
    assert new.count("\n") == out.count("\n")


def test_it_is_idempotent(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import listTitles from '../services/api';\n"})
    repair(src)
    assert repair(src) == []


# --- every condition that must hold ---------------------------------------------------------------

def test_a_legitimate_default_import_is_left_alone(tmp_path):
    """`export default api` is an identifier, not a bag — the default import is correct."""
    src = _tree(tmp_path, {
        "services/api.js": "const api = {}; export default api;\n",
        "pages/Browse.jsx": "import api from '../services/api';\n"})
    assert repair(src) == []


def test_a_name_that_is_not_a_key_is_left_alone(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import whatever from '../services/api';\n"})
    assert repair(src) == []


def test_a_key_that_is_not_a_named_export_is_left_alone(tmp_path):
    """Then `import { X }` would NOT be valid — 0 of the 21 real sites look like this, and a
    rewrite here would trade one broken import for another."""
    src = _tree(tmp_path, {
        "services/api.js": "const hidden = 1;\nexport default { hidden };\n",
        "pages/Browse.jsx": "import hidden from '../services/api';\n"})
    assert repair(src) == []


def test_a_mixed_default_and_named_import_is_left_alone(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import listTitles, { getGenres } from '../services/api';\n"})
    assert repair(src) == []


def test_a_package_import_is_left_alone(tmp_path):
    src = _tree(tmp_path, {"pages/Browse.jsx": "import React from 'react';\n"})
    assert repair(src) == []


def test_an_unresolvable_specifier_is_left_alone(tmp_path):
    src = _tree(tmp_path, {"pages/Browse.jsx": "import x from '../nope/missing';\n"})
    assert repair(src) == []


def test_a_namespace_import_is_left_alone(tmp_path):
    src = _tree(tmp_path, {
        "services/api.js": _BAG,
        "pages/Browse.jsx": "import * as api from '../services/api';\n"})
    assert repair(src) == []


# --- it must never break the scaffold --------------------------------------------------------------

def test_a_missing_directory_is_a_no_op(tmp_path):
    assert repair(tmp_path / "nope") == []


def test_an_unreadable_tree_returns_a_list(tmp_path):
    assert repair(tmp_path) == []


def test_the_scaffolder_runs_it_over_the_whole_tree():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs)
    i = src.index("#632: whole-tree pass")
    block = src[i:src.index("return {\"scaffolded\"", i)]
    assert "repair_default_import_of_named_export_632(app.parent)" in block


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(
        fs.repair_default_import_of_named_export_632).split())
    assert "21 crash sites in 21 files across 6" in flat
    assert "21 of 21" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
