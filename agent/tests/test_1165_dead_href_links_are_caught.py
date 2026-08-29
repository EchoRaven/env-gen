"""#1165: the dead-nav detector did not know about `href`.

Its pattern matched `to="/x"` and `navigate("/x")` only. A plain `<a href="/x">`
is a dead control exactly the way a `<Link to>` is — it just fails LOUDER, with
a full page load onto the SPA's catch-all.

netflix-local-r13 shipped `<a href="/home">Home</a>` in NewAndPopularPage while
App.jsx declares no `/home` route, and this detector — which exists for
precisely that defect (#238, tiktok r27) — logged nothing for the whole run.
Found by checking every internal link in the two delivered artifacts against
their declared routes.
"""
import textwrap
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    dead_nav_link_blockers as dead)


def _app(tmp_path, routes, page):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text(
        "\n".join('<Route path="%s" element={<X/>} />' % r for r in routes),
        encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(textwrap.dedent(page), encoding="utf-8")
    return src


def test_a_bare_anchor_to_a_missing_route_is_caught(tmp_path):
    """r13's exact shape."""
    src = _app(tmp_path, ["/", "/browse"], '<a href="/home">Home</a>')
    out = dead(src)
    assert len(out) == 1 and "/home" in out[0]


def test_an_anchor_to_a_declared_route_is_fine(tmp_path):
    src = _app(tmp_path, ["/", "/home"], '<a href="/home">Home</a>')
    assert dead(src) == []


def test_a_static_file_href_is_not_a_route(tmp_path):
    """`to=`/`navigate()` never point at files, but `href` does — admitting the
    spelling without this would report every logo as a dead control."""
    src = _app(tmp_path, ["/"], '''
        <a href="/assets/brand/logo.svg">logo</a>
        <a href="/static/doc.pdf">doc</a>
        <img src="/images/x.png" />
        <a href="/favicon.ico">icon</a>
        ''')
    assert dead(src) == []


def test_external_and_hash_hrefs_are_untouched(tmp_path):
    src = _app(tmp_path, ["/"], '''
        <a href="https://example.com/home">out</a>
        <a href="#">noop</a>
        <a href="mailto:a@b.c">mail</a>
        ''')
    assert dead(src) == []


def test_the_link_spellings_it_already_caught_still_work(tmp_path):
    src = _app(tmp_path, ["/"], '<Link to="/gone">x</Link>')
    assert len(dead(src)) == 1


def test_the_two_delivered_artifacts_reproduce_the_finding():
    """r13 ships one dead href; r14 ships none. The second half is the
    false-positive check that matters — a detector that fires on a healthy app
    costs a run (#566j)."""
    root = Path(fa.__file__).parents[5] / "generated"
    r13 = root / "netflix-local-r13" / "app" / "frontend" / "src"
    r14 = root / "netflix-local-r14" / "app" / "frontend" / "src"
    if not (r13.exists() and r14.exists()):
        pytest.skip("delivered artifacts not on this box")
    out13 = dead(r13)
    assert len(out13) == 1 and "/home" in out13[0]
    assert dead(r14) == []
