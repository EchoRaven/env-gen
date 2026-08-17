r"""#576 (netflix r139, live, in the DELIVERED app): a projected page that renders NO nav is
invisible to `recover_agent_nav` (#440), which only REWIRES a page already rendering the generic
inline fw-nav. It therefore ships without the app's own chrome, and the visual judge charges it
on every dimension at once — "Missing: top nav bar, logo, nav links, search icon, notifications
bell, profile avatar".

Two r139 projected pages, identical but for one line:

    GamesPage          <div data-projected="ref" className="flex min-h-screen flex-col">
                         <TopNav />
                         <main …>
    GenreCategoryPage  <div data-projected="ref" className="flex min-h-screen">
                         <main …>

`genre_category` scored 0.28 (components 0.25, copy 0.20) against `browse_home`'s 0.85, and was
the single screen holding the blocking average at 0.6382 under the 0.65 bar. Whether the chrome
is emitted depends on the reference screen's region classification, which drifts per draw; the
APP's own shell does not — 6 of its pages mount `<TopNav />`.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    mount_shared_nav_on_projected_pages as mount,
)

_NAV = "export default function TopNav() { return <nav/>; }\n"

_WITH_NAV = """import { useState } from 'react';
import TopNav from '../components/TopNav.jsx';
export default function GamesPage() {
  return (
    <div data-projected="ref" className="flex min-h-screen flex-col">
      <TopNav />
      <main className="flex-1"><section>x</section></main>
    </div>
  );
}
"""

_NO_NAV = """import { useState } from 'react';
import { useParams } from 'react-router-dom';
export default function GenreCategoryPage() {
  return (
    <div data-projected="ref" className="flex min-h-screen">
      <main className="flex-1"><section>x</section></main>
    </div>
  );
}
"""


def _app(tmp_path, pages, comps=("TopNav",)):
    fe = tmp_path / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    for c in comps:
        (fe / "src" / "components" / f"{c}.jsx").write_text(_NAV, encoding="utf-8")
    for name, src in pages.items():
        (fe / "src" / "pages" / f"{name}.jsx").write_text(src, encoding="utf-8")
    return fe


def test_r139_a_chromeless_projected_page_gets_the_shared_nav(tmp_path):
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV,
                         "GenreCategoryPage": _NO_NAV})
    rep = mount(fe)
    assert rep["mounted"] == ["GenreCategoryPage"], rep
    out = (fe / "src" / "pages" / "GenreCategoryPage.jsx").read_text()
    assert "import TopNav from '../components/TopNav.jsx';" in out
    assert "<TopNav />" in out
    # mounted INSIDE the root, before <main>
    assert out.index("<TopNav />") < out.index("<main")
    # and the root becomes a column so the nav stacks above the content (sibling shape)
    assert 'className="flex min-h-screen flex-col"' in out


def test_a_page_that_already_mounts_it_is_untouched(tmp_path):
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "D": _WITH_NAV})
    before = (fe / "src" / "pages" / "C.jsx").read_text()
    assert mount(fe)["mounted"] == []
    assert (fe / "src" / "pages" / "C.jsx").read_text() == before


def test_a_lane_authored_page_is_untouched(tmp_path):
    """Only pages carrying the projected marker are ours to edit."""
    lane = _NO_NAV.replace(' data-projected="ref"', "")
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "Lane": lane})
    assert mount(fe)["mounted"] == []
    assert "TopNav" not in (fe / "src" / "pages" / "Lane.jsx").read_text()


def test_no_shared_shell_no_mount(tmp_path):
    """If the app has no widely-shared shell, inventing one is not this pass's business."""
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _NO_NAV, "C": _NO_NAV})
    assert mount(fe)["mounted"] == []


def test_the_real_r139_distribution_is_recognised(tmp_path):
    """The rule must fire on r139's ACTUAL shape — TopNav on 6 pages, runner-up 2, with four
    auth/landing pages legitimately chrome-less. A majority-of-all-pages rule found nothing
    here; that miss was caught by dry-running the pass against the generated app."""
    pages = {f"Nav{i}": _WITH_NAV for i in range(6)}
    pages.update({f"Auth{i}": _NO_NAV.replace(' data-projected="ref"', "") for i in range(4)})
    other = _WITH_NAV.replace("TopNav", "PosterCard")
    pages.update({f"Other{i}": other for i in range(2)})
    pages["GenreCategoryPage"] = _NO_NAV
    fe = _app(tmp_path, pages, comps=("TopNav", "PosterCard"))
    got = mount(fe)
    assert got["nav"] == "TopNav", got
    assert "GenreCategoryPage" in got["mounted"], got
    # the four LANE-authored auth/landing pages keep their deliberate chrome-less shape
    assert not any(m.startswith("Auth") for m in got["mounted"]), got
    # any OTHER chrome-less projected page is covered too — that is the intent, not a leak
    assert set(got["mounted"]) <= {"GenreCategoryPage", "Other0", "Other1"}, got


def test_a_missing_component_file_is_a_no_op(tmp_path):
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "D": _NO_NAV}, comps=())
    assert mount(fe)["mounted"] == []


def test_an_already_column_root_keeps_its_classes(tmp_path):
    col = _NO_NAV.replace('className="flex min-h-screen"',
                          'className="flex min-h-screen flex-col"')
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "D": col})
    assert mount(fe)["mounted"] == ["D"]
    out = (fe / "src" / "pages" / "D.jsx").read_text()
    assert out.count("flex-col") == 1, out


def test_missing_dirs_and_garbage_never_raise(tmp_path):
    assert mount(tmp_path / "nope")["mounted"] == []
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "D": "not jsx at all"})
    assert mount(fe)["mounted"] == []


def test_the_result_is_still_parseable_jsx_shape(tmp_path):
    """Cheap structural check: tags stay balanced around the insertion."""
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "D": _NO_NAV})
    mount(fe)
    out = (fe / "src" / "pages" / "D.jsx").read_text()
    assert out.count("<div") == out.count("</div>")
    assert out.count("<main") == out.count("</main>")
    assert out.count("return (") == 1


def test_a_multi_line_import_is_never_split(tmp_path):
    """Self-review catch: anchoring the inserted import to the LAST `^import .*$` splits a
    multi-line import down the middle, because the regex matches only its first line. The
    insert is anchored to the FIRST import instead, which cannot land inside a statement."""
    multi = (
        "import {\n  useEffect,\n  useState,\n} from 'react';\n"
        "export default function Q() {\n"
        "  return (\n"
        '    <div data-projected="ref" className="flex min-h-screen">\n'
        "      <main>x</main>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
    fe = _app(tmp_path, {"A": _WITH_NAV, "B": _WITH_NAV, "C": _WITH_NAV, "Multi": multi})
    assert mount(fe)["mounted"] == ["Multi"]
    out = (fe / "src" / "pages" / "Multi.jsx").read_text()
    # the original statement survives intact, and the new import precedes it
    assert "import {\n  useEffect,\n  useState,\n} from 'react';" in out, out
    assert out.index("components/TopNav.jsx") < out.index("import {"), out
    assert out.count("import ") == 2, out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
