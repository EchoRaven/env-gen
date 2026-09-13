"""#1202ly — the ui_page id was fed back in as a name, and the prefix accumulated.

GROUND TRUTH (tiktok-web-r121, from `shared/hubs/registryhub_ui_pages.json`):

    root_for_you_page                  component=''  route=''
    page:ui:root_for_you_page          component=''  route=''
    page:ui:page:ui:root_for_you_page  component=''  route=''

`register_ui_page` stores `"id": f"page:ui:{name}"`. Feed that id back as `name` and the
prefix accumulates once per pass. The frontend scaffold then PascalCased each key into a
build-integrity stub for an import nothing declares — four files in that one run:

    src/pages/PageUiRootForYouPage.jsx
    src/pages/PageUiPageUiRootForYouPage.jsx
    src/pages/PageUiPageUiPageUiRootForYouPage.jsx
    src/pages/PageUiPageUiPageUiPageUiRootForYouPage.jsx

each carrying "// framework-generated page — edits are overwritten" and a heading that
degrades with the name (`<h2>Ui  Ui Root For You</h2>`). Nothing imports any of them; #1014
commits them as lane-owned paths at delivery and they feed the dead-artifact gate.

#1193/#1195 already merge a page registered under two NAMES and cannot see this: each
accumulated key is a genuinely new name whose route AND component are both empty, so neither
the route test nor the component test has anything to match on. The guard therefore goes on
the VALUE at the entry point, not on any one caller.
"""
import json
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry


@pytest.fixture
def reg(tmp_path):
    return HubRegistry(tmp_path)


def _pages(reg):
    out = reg.registryhub.list_ui_pages()
    if isinstance(out, dict):
        return {k: v for k, v in out.items() if k != "_meta"}
    return {str(p.get("name")): p for p in (out or [])}


def test_an_id_fed_back_as_a_name_does_not_accumulate(reg):
    """★ r121's exact sequence."""
    reg.registryhub.register_ui_page("root_for_you_page", agent="frontend")
    reg.registryhub.register_ui_page("page:ui:root_for_you_page", agent="frontend")
    reg.registryhub.register_ui_page("page:ui:page:ui:root_for_you_page", agent="frontend")
    names = set(_pages(reg))
    assert not [n for n in names if "page:ui:" in n], names
    assert "root_for_you_page" in names


def test_the_record_keeps_one_canonical_id(reg):
    reg.registryhub.register_ui_page("page:ui:login_page", route="/login",
                                     component="LoginPage", agent="frontend")
    recs = _pages(reg)
    rec = recs.get("login_page")
    assert rec is not None, recs
    assert rec.get("id") == "page:ui:login_page"
    assert rec.get("name") == "login_page"


def test_a_normal_name_is_untouched(reg):
    """★ Non-vacuity: the guard must not rewrite names that were never prefixed."""
    reg.registryhub.register_ui_page("explore_grid_page", route="/explore",
                                     component="ExploreGridPage", agent="frontend")
    rec = _pages(reg).get("explore_grid_page")
    assert rec and rec.get("name") == "explore_grid_page"
    assert rec.get("route") == "/explore"


def test_the_contract_survives_the_normalisation(reg):
    """A re-registration under the id must still UPDATE the page, not create a second one."""
    reg.registryhub.register_ui_page("more_page", agent="frontend")
    reg.registryhub.register_ui_page("page:ui:more_page", route="/more",
                                     component="MorePage", agent="frontend")
    recs = _pages(reg)
    assert len(recs) == 1, recs
    rec = recs["more_page"]
    assert rec.get("route") == "/more"
    assert rec.get("component") == "MorePage"


def test_deep_accumulation_is_stripped_completely(reg):
    reg.registryhub.register_ui_page("page:ui:" * 5 + "deep_page", agent="frontend")
    assert set(_pages(reg)) == {"deep_page"}


def test_it_announces_rather_than_silently_rewriting():
    """#1202ah: a silent normalisation hides which caller is re-feeding the id."""
    # #943: the enclosing FunctionDef by AST, never "the N bytes after the name" — the
    # first draft used a two-thousand-byte forward slice and pushed the fixed-window
    # ratchet from 57 to 58. (Written without the literal slice syntax: that ratchet's
    # detector scans TEXT, so quoting the shape it forbids trips it from a comment.)
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "register_ui_page"), None)
    assert fn is not None, "register_ui_page moved"
    seg = ast.get_source_segment(src, fn) or ""
    assert "_n1202ly" in seg, "the normalisation left register_ui_page"
    assert "warn_once_1201" in seg, (
        "the normalisation is silent — nobody can tell which caller re-feeds the id")


def test_the_prefix_matches_the_id_the_method_writes():
    """★ The guard and the producer must never drift apart."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    assert 'f"page:ui:{name}"' in src, "the id format changed — update the strip prefix"
    assert 'startswith("page:ui:")' in src
