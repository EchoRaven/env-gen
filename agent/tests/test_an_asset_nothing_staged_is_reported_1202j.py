r"""#1202j: an asset the code references that nothing ever staged.

FIX #113 re-stages `design/assets` at every build entry point, because a lane checkout window
could drop files that WERE staged. Nothing checks the other direction: a lane referencing
`/assets/icons/apps_24.svg` when no such icon was ever in the design input. The file is simply
not there, the browser 404s, and the visual judge scores the broken-glyph render.

That symptom is in #113's own docstring — "every /assets/icons/*.svg 404 while the JS bundle
loaded fine", dm_inbox scored 0.00 — arriving through a cause #113 does not cover.

Measured across all 114 generated frontends: 21 reference assets that exist nowhere in the
delivered tree, 142 references in total. googlemaps gmrun3 references 22 icons it does not
have against 72 it does; `apps_24.svg` and `bookmark_border_24.svg` were confirmed absent from
the whole app, not merely from the directory searched.

Reports rather than blocks: a reference may legitimately resolve at runtime, and a missing
icon is not worth failing a delivery over. What it is worth is not being invisible until a
judge scores the hole it leaves.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import unstaged_asset_refs_1202j  # noqa: E402


def _fe(tmp_path, page_src, staged=()):
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "pages" / "P.jsx").write_text(page_src, encoding="utf-8")
    for rel in staged:
        f = fe / "public" / rel.lstrip("/")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("<svg/>", encoding="utf-8")
    return fe


def test_a_referenced_icon_that_was_never_staged_is_reported(tmp_path):
    fe = _fe(tmp_path, "export default () => <img src='/assets/icons/apps_24.svg'/>;")
    assert unstaged_asset_refs_1202j(fe) == ["/assets/icons/apps_24.svg"]


def test_a_staged_asset_is_not_reported(tmp_path):
    fe = _fe(tmp_path, "export default () => <img src='/assets/icons/apps_24.svg'/>;",
             staged=["/assets/icons/apps_24.svg"])
    assert unstaged_asset_refs_1202j(fe) == []


def test_the_seed_is_scanned_too(tmp_path):
    """Seed rows carry avatar and photo paths, and a missing one is a broken row on screen."""
    fe = _fe(tmp_path, "export default () => null;")
    seed = tmp_path / "seed.json"
    seed.write_text('{"users": [{"avatar": "/assets/placeholders/ph-avatar-9.svg"}]}',
                    encoding="utf-8")
    assert unstaged_asset_refs_1202j(fe, seed) == ["/assets/placeholders/ph-avatar-9.svg"]


def test_a_remote_url_is_not_an_asset_path(tmp_path):
    fe = _fe(tmp_path, "export default () => <img src='https://cdn.example.com/a.png'/>;")
    assert unstaged_asset_refs_1202j(fe) == []


def test_the_report_is_capped_and_deterministic(tmp_path):
    refs = "".join("<img src='/assets/icons/i%d.svg'/>" % i for i in range(80))
    fe = _fe(tmp_path, "export default () => <>%s</>;" % refs)
    out = unstaged_asset_refs_1202j(fe, cap=40)
    assert len(out) == 40
    assert out == sorted(out)


def test_a_missing_tree_never_raises(tmp_path):
    assert unstaged_asset_refs_1202j(tmp_path / "nope") == []
    assert unstaged_asset_refs_1202j(None, None) == []


def test_it_is_wired_with_its_own_guard():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
           ).read_text(encoding="utf-8")
    assert "unstaged_asset_refs_1202j" in src
    at = src.index("unstaged_asset_refs_1202j")
    enclosing = src.rindex("try:", 0, at)
    assert "reconcile_ui_page_apis_1199" not in src[enclosing:at]
