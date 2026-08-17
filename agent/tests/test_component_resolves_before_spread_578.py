r"""#578 (netflix r142, live): nothing stopped the framework from spreading a component that
cannot build.

`src/components/TopNav.jsx` imported `./SearchOverlay.jsx` while that file was momentarily
absent, so `vite build` failed — and `recover_agent_nav` (#440) was busy mounting TopNav into
MORE pages ("recovered agent nav 'TopNav' into 2 page(s)"). Every page carrying it then failed
to render: games, genre_category, movies, my_list, new_and_popular and shows all scored **0.0**,
taking the blocking average from 0.555 to 0.2773 and burning judging cycles. The app recovered
by itself, but only by luck — and #576 would have spread the same broken component more
aggressively.

Fix: both spreading passes require the component's own relative-import graph to exist first.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _component_resolves,
    mount_shared_nav_on_projected_pages as mount,
    recover_agent_nav,
)

_WITH_NAV = """import TopNav from '../components/TopNav.jsx';
export default function P() {
  return (
    <div data-projected="ref" className="flex min-h-screen flex-col">
      <TopNav />
      <main>x</main>
    </div>
  );
}
"""

_NO_NAV = """import { useState } from 'react';
export default function Q() {
  return (
    <div data-projected="ref" className="flex min-h-screen">
      <main>x</main>
    </div>
  );
}
"""


def _tree(tmp_path, nav_src, extra_components=()):
    fe = tmp_path / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    comps = fe / "src" / "components"
    comps.mkdir(parents=True)
    (comps / "TopNav.jsx").write_text(nav_src, encoding="utf-8")
    for name in extra_components:
        (comps / name).write_text("export default function X(){return null;}\n",
                                  encoding="utf-8")
    for i in range(3):
        (fe / "src" / "pages" / f"Nav{i}.jsx").write_text(_WITH_NAV, encoding="utf-8")
    (fe / "src" / "pages" / "Chromeless.jsx").write_text(_NO_NAV, encoding="utf-8")
    return fe


_BROKEN = "import SearchOverlay from './SearchOverlay.jsx';\nexport default function TopNav(){return null;}\n"
_OK = "import SearchOverlay from './SearchOverlay.jsx';\nexport default function TopNav(){return null;}\n"
_NO_IMPORTS = "export default function TopNav(){return <nav/>;}\n"


def test_r142_a_component_with_a_missing_relative_import_does_not_resolve(tmp_path):
    fe = _tree(tmp_path, _BROKEN)                       # SearchOverlay.jsx absent
    assert _component_resolves(fe / "src" / "components" / "TopNav.jsx") is False


def test_the_same_component_resolves_once_the_file_exists(tmp_path):
    fe = _tree(tmp_path, _OK, extra_components=("SearchOverlay.jsx",))
    assert _component_resolves(fe / "src" / "components" / "TopNav.jsx") is True


def test_extensionless_and_index_imports_resolve(tmp_path):
    fe = _tree(tmp_path, "import X from './SearchOverlay';\nexport default function TopNav(){}\n",
               extra_components=("SearchOverlay.jsx",))
    assert _component_resolves(fe / "src" / "components" / "TopNav.jsx") is True
    d = fe / "src" / "components" / "Widget"
    d.mkdir()
    (d / "index.jsx").write_text("export default function W(){}\n", encoding="utf-8")
    (fe / "src" / "components" / "TopNav.jsx").write_text(
        "import W from './Widget';\nexport default function TopNav(){}\n", encoding="utf-8")
    assert _component_resolves(fe / "src" / "components" / "TopNav.jsx") is True


def test_package_imports_are_not_our_business(tmp_path):
    fe = _tree(tmp_path, "import React from 'react';\nexport default function TopNav(){}\n")
    assert _component_resolves(fe / "src" / "components" / "TopNav.jsx") is True


def test_an_unreadable_component_is_treated_as_unresolvable(tmp_path):
    fe = _tree(tmp_path, _NO_IMPORTS)
    assert _component_resolves(fe / "src" / "components" / "Nope.jsx") is False


def test_576_refuses_to_mount_an_unbuildable_component(tmp_path):
    fe = _tree(tmp_path, _BROKEN)
    rep = mount(fe)
    assert rep["mounted"] == [], rep
    assert "unresolved imports" in str(rep.get("skipped")), rep
    assert "TopNav" not in (fe / "src" / "pages" / "Chromeless.jsx").read_text()


def test_576_mounts_once_the_component_is_repaired(tmp_path):
    fe = _tree(tmp_path, _OK, extra_components=("SearchOverlay.jsx",))
    rep = mount(fe)
    assert rep["mounted"] == ["Chromeless"], rep
    assert "<TopNav />" in (fe / "src" / "pages" / "Chromeless.jsx").read_text()


def test_440_refuses_to_rewire_onto_an_unbuildable_nav(tmp_path):
    fe = _tree(tmp_path, _BROKEN)
    rep = recover_agent_nav(fe)
    assert rep.get("rewired") == [], rep
    assert "unresolved imports" in str(rep.get("skipped")), rep


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
