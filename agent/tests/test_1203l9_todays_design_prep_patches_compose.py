r"""#1203l9: #1203kv, #1203l0 and #1203l1 all land in `complete_design_system` — do they compose?

Each has its own test and each drives the pass alone. Nothing asserted that ONE call restores
all of it at once, on one tree, in the order they depend on:

    #1203kv  re-measures every asset entry from the staged file  (type, dims, transparent,
             dominant_colors) — the analyst's rewrite drops them
    #1203ky  makes the screen's reference resolvable again, which is what lets
    #1203l0   re-measure `layout_metrics`, and rebuild the `dataset` manifest from the files
             still staged under design/dataset/
    #1203l1  keeps `avatar` out of the content-image pattern, so the restored manifest elects
             the visual catalog rather than the chattiest table

The dependency is real and one-directional: without #1203ky the reference does not resolve and
#1203l0's layout half cannot run; without #1203kv's `dominant_colors` #1203kw cannot tell a
monochrome icon from a coloured one; without #1203l1 the manifest #1203l0 restores makes
`_content_entity_from_design` answer `comments`.

This is the shape #1203kn pinned for the squad-coverage patches on 2026-10-14, for the same
reason: four tickets that pass individually can still leave a gap between them.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import design_prep as DP  # noqa: E402
from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402

MONO = ('<svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 48 48" '
        'width="24" height="24"><path d="M24 3a10 10 0 1 1 0 20Z"/></svg>')
COLOURED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" '
            'height="24"><circle cx="12" cy="12" r="11" fill="#20d5ec"/></svg>')


def _run_tree(tmp_path):
    """A run directory shaped like the real thing: a staged reference, staged icons, a staged
    dataset — and a document in the shape the design_analyst rewrites it into."""
    from PIL import Image
    d = tmp_path / "design"
    (d / "references").mkdir(parents=True)
    im = Image.new("RGB", (60, 40), (8, 8, 8))
    for x in range(10, 50):
        for y in range(8, 32):
            im.putpixel((x, y), (240, 240, 240))
    im.save(d / "references" / "home_feed.png")

    icons = d / "assets" / "icons"
    icons.mkdir(parents=True)
    (icons / "search_20.svg").write_text(MONO, encoding="utf-8")
    (icons / "profile_94.svg").write_text(MONO, encoding="utf-8")
    (icons / "verified.svg").write_text(COLOURED, encoding="utf-8")

    data = d / "dataset"
    data.mkdir(parents=True)
    (data / "videos.json").write_text(json.dumps(
        [{"id": i, "caption": "c", "thumbnail": "t.jpg"} for i in range(4)]), encoding="utf-8")
    (data / "comments.json").write_text(json.dumps(
        [{"video_id": 1, "text": "x", "avatar": "a.jpg"} for _ in range(40)]), encoding="utf-8")

    def _entry(aid, rel):
        # exactly the five keys the analyst's rewrite carries
        return {"id": aid, "file": rel, "staged_path": "public/assets/" + rel,
                "description": "An icon.", "use": ["left navigation"]}

    doc = {
        "design_system": {"palette": {"bg": "#000"}},
        "assets": [_entry("search-20", "icons/search_20.svg"),
                   _entry("profile-94", "icons/profile_94.svg"),
                   _entry("verified", "icons/verified.svg")],
        "screens": [{
            "name": "home_feed",
            # the analyst's PATH form, which #1203ky taught the resolver to read
            "reference": "design/references/home_feed.png",
            "components": [{"id": "hero", "region": [0, 0, 30, 20], "colors": {"bg": "#111"}}],
        }],
    }
    return tmp_path, doc


def test_one_pass_restores_all_of_it(tmp_path):
    out, doc = _run_tree(tmp_path)
    res = DP.complete_design_system(doc, {}, out)

    # #1203kv — the measured asset fields are back, from the FILE not the filename
    by = {a["id"]: a for a in res["assets"]}
    assert by["search-20"]["type"] == "svg", by["search-20"]
    assert by["search-20"]["dominant_colors"] == [], by["search-20"]
    assert by["verified"]["dominant_colors"] == ["#20d5ec"], by["verified"]

    # #1203ky + #1203l0 — the reference resolved, so the screen was measured and cropped
    scr = res["screens"][0]
    assert scr.get("layout_metrics"), scr
    assert scr["components"][0].get("crop") == "design/crops/home_feed__hero.png", scr
    assert (out / scr["components"][0]["crop"]).is_file()

    # #1203l0 — the dataset manifest is back, rebuilt from the files still on disk
    ids = {e["id"]: e for e in (res.get("dataset") or [])}
    assert set(ids) == {"videos", "comments"}, ids
    assert ids["videos"]["records"] == 4 and ids["comments"]["records"] == 40

    # #1203l1 — and the restored manifest elects the visual catalog, not the chattiest table
    assert FS._content_entity_from_design(res) == "videos", res.get("dataset")

    # #1203kv + #1203kw — the restored colours are what keeps a monochrome icon off the nav's
    # <img> channel while the resolver still finds it
    assert dict(FS._nav_utility_icons(res)).get("Account"), FS._nav_utility_icons(res)
    jsx = FS._ref_nav_jsx([("Home", "/")], "#e50914", vertical=False, design=res)
    assert "profile_94.svg" not in jsx, jsx


def test_the_analysts_own_values_survive_all_four(tmp_path):
    """Every one of them is a RESTORE, never an overwrite — asserted together, because each
    ticket only checked its own field."""
    out, doc = _run_tree(tmp_path)
    doc["assets"][0]["type"] = "sprite"
    doc["assets"][0]["dominant_colors"] = ["#000000"]
    doc["screens"][0]["layout_metrics"] = {"content": True, "mine": 1}
    doc["dataset"] = [{"id": "mine", "file": "x.json"}]
    res = DP.complete_design_system(doc, {}, out)
    by = {a["id"]: a for a in res["assets"]}
    assert by["search-20"]["type"] == "sprite"
    assert by["search-20"]["dominant_colors"] == ["#000000"]
    assert res["screens"][0]["layout_metrics"] == {"content": True, "mine": 1}
    assert res["dataset"] == [{"id": "mine", "file": "x.json"}]


def test_the_pass_still_cannot_raise(tmp_path):
    """It is a completion FLOOR: a tree missing everything must return the document, not an
    exception — the property each ticket's own `except` clause claims."""
    doc = {"design_system": {}, "screens": [{"name": "x", "reference": "nope.png",
                                             "components": [{"id": "c"}]}],
           "assets": [{"id": "ghost", "file": "icons/gone.svg"}]}
    res = DP.complete_design_system(doc, {}, tmp_path / "empty")
    assert res is doc or isinstance(res, dict)
    assert res["assets"][0]["type"] == "svg", "the suffix is the fallback when the file is gone"
    for k in ("dims", "transparent", "dominant_colors"):
        assert k not in res["assets"][0], k
