"""#1202cb — a DEFAULT import against a named-only target breaks Rollup too.

`repair_frontend_named_default_imports` only ever handled one direction: a NAMED import
whose target exports only a default. The mirror fails identically ("No default export"), and
it is the FRAMEWORK's own shape — the page scaffolder emits
`import {comp} from '../components/{comp}.jsx'` for a component the LANE writes.

r35 live: framework-projected GenresPage did `import CatalogExperience from
'../components/CatalogExperience.jsx'` against a file exporting only BrowsePage /
CategoryPage / LanguagesPage / NewPopularPage → frontend build blocked → visual fidelity
scored 0.0592 against a 0.6000 record → delivery deferred. Corpus: 6 of 3799 default imports
across 120 delivered frontends, in 3 runs.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    repair_frontend_named_default_imports, _HAS_DEFAULT_EXPORT)


def _fe(tmp_path, files):
    src = tmp_path / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def test_a_default_import_of_a_name_the_target_exports_is_rewritten(tmp_path):
    fe = _fe(tmp_path, {
        "pages/MoviesPage.jsx":
            "import CategoryPage from '../components/CatalogExperience.jsx';\n"
            "export default () => <CategoryPage />;\n",
        "components/CatalogExperience.jsx":
            "export function CategoryPage() { return <div/>; }\n",
    })
    res = repair_frontend_named_default_imports(fe)
    assert res["repaired"] is True
    got = (fe / "src" / "pages" / "MoviesPage.jsx").read_text(encoding="utf-8")
    assert "import { CategoryPage } from '../components/CatalogExperience.jsx'" in got


def test_r35s_shape_is_reported_rather_than_guessed(tmp_path):
    """No default AND no matching name: any rewrite would be a guess at which export was
    meant. Naming the build-breaker beats repairing it wrongly."""
    fe = _fe(tmp_path, {
        "pages/GenresPage.jsx":
            "import CatalogExperience from '../components/CatalogExperience.jsx';\n",
        "components/CatalogExperience.jsx":
            "export function BrowsePage() {}\nexport function CategoryPage() {}\n",
    })
    res = repair_frontend_named_default_imports(fe)
    assert res["repaired"] is False
    assert res["unrepairable"], "the build-breaker was neither fixed nor reported"
    msg = res["unrepairable"][0]
    assert "CatalogExperience" in msg and "no default" in msg
    assert "BrowsePage" in msg, "the message should name what IS available"
    # untouched
    assert "import CatalogExperience from" in (
        fe / "src" / "pages" / "GenresPage.jsx").read_text(encoding="utf-8")


def test_a_target_with_a_default_export_is_left_alone(tmp_path):
    fe = _fe(tmp_path, {
        "pages/HomePage.jsx": "import Hero from '../components/Hero.jsx';\n",
        "components/Hero.jsx": "export default function Hero() {}\n",
    })
    res = repair_frontend_named_default_imports(fe)
    assert res["repaired"] is False and res["unrepairable"] == []


def test_a_mixed_import_is_never_rewritten(tmp_path):
    """`import X, { Y } from` — rewriting the default half would silently drop the named
    half. The `\\s+from` in the pattern is what keeps this out."""
    body = "import Catalog, { CategoryPage } from '../components/CatalogExperience.jsx';\n"
    fe = _fe(tmp_path, {
        "pages/P.jsx": body,
        "components/CatalogExperience.jsx": "export function CategoryPage() {}\n",
    })
    repair_frontend_named_default_imports(fe)
    assert (fe / "src" / "pages" / "P.jsx").read_text(encoding="utf-8") == body


def test_a_named_import_is_not_matched_by_the_default_pattern(tmp_path):
    """Regression guard on the pattern itself: `import { X } from` must stay the other
    repair's business."""
    fe = _fe(tmp_path, {
        "pages/P.jsx": "import { NavBar } from '../components/NavBar.jsx';\n",
        "components/NavBar.jsx": "export default function NavBar() {}\n",
    })
    res = repair_frontend_named_default_imports(fe)
    # the ORIGINAL direction still repairs this one
    assert res["repaired"] is True
    assert "import NavBar from" in (fe / "src" / "pages" / "P.jsx").read_text(encoding="utf-8")


def test_a_dangling_import_is_not_reported_as_a_breaker(tmp_path):
    """A missing target is a different repair's job (dangling-import scaffolding); claiming
    it here would double-report it."""
    fe = _fe(tmp_path, {"pages/P.jsx": "import Gone from '../components/Gone.jsx';\n"})
    res = repair_frontend_named_default_imports(fe)
    assert res["unrepairable"] == []


def test_package_imports_are_untouched(tmp_path):
    """Only LOCAL (dot-relative) imports — `import React from 'react'` must never match."""
    body = "import React from 'react';\nimport clsx from 'clsx';\n"
    fe = _fe(tmp_path, {"pages/P.jsx": body})
    res = repair_frontend_named_default_imports(fe)
    assert res["unrepairable"] == []
    assert (fe / "src" / "pages" / "P.jsx").read_text(encoding="utf-8") == body


def test_the_heal_pipeline_announces_what_it_cannot_repair():
    """An unrepairable build-breaker that nobody prints is the silent-default failure this
    repo has shipped seven times. #943: landmark anchor."""
    src = (LLM / "multi_agent" / "runtime" / "heal_pipeline.py").read_text(encoding="utf-8")
    i = src.index("_nd = repair_frontend_named_default_imports(fe)")
    stanza = src[i:src.index("Build-integrity: the frontend lane routinely imports", i)]
    assert '_nd.get("unrepairable")' in stanza and "#1202cb" in stanza


def test_a_re_exported_default_counts_as_a_default():
    """Caught while measuring the corpus: netflix-r26 HeroBillboard.jsx is exactly
    `export { HeroBillboard as default } from './BrowseChrome'` and tiktok-r86 has the same
    shape. A detector that knows only the keyword form calls those build-breakers -- a false
    warning about correct code, handed to a lane. Two of six corpus hits were this; the real
    count is four."""
    for src in ("export default function X(){}",
                "export { HeroBillboard as default } from './BrowseChrome';",
                "export { default } from './x';"):
        assert _HAS_DEFAULT_EXPORT.search(src), src


def test_named_only_modules_are_still_not_mistaken_for_having_a_default():
    """The control: widening the pattern must not make everything look default-exporting."""
    for src in ("export function BrowsePage(){}\nexport const a = 1;",
                "export { BrowsePage, CategoryPage };",
                "const defaultThing = 1; export { defaultThing };"):
        assert not _HAS_DEFAULT_EXPORT.search(src), src


def test_a_re_exported_default_is_not_reported_as_a_breaker(tmp_path):
    """End to end: the r26 shape must pass through untouched and unreported."""
    fe = _fe(tmp_path, {
        "App.jsx": "import HeroBillboard from './components/HeroBillboard.jsx';\n",
        "components/HeroBillboard.jsx":
            "export { HeroBillboard as default } from './BrowseChrome';\n",
    })
    res = repair_frontend_named_default_imports(fe)
    assert res["unrepairable"] == [] and res["repaired"] is False
