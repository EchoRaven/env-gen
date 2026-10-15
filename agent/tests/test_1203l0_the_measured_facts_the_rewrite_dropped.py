"""#1203l0/#1203l1: two more measured facts the analyst's rewrite drops, and the word that
made restoring one of them harmful.

The spawned design_analyst rewrites design/design_system.json wholesale (see #1203kv, which
found the same thing one level over, on assets[]). Comparing what
`build_skeleton_design_system` WRITES against what the modern documents actually carry, level
by level, two more framework-MEASURED fields are gone:

    layout_metrics   (#220, a screen's measured content bounds)   0 of 429 screens
    dataset          (the fourth design-input channel's manifest)  0 of 39 documents

while 36 of those 39 runs still have the dataset FILES staged under `design/dataset/`.

`layout_metrics` is read by #796's measured-layout block for a FAILING screen in the repair
round, so restoring it changes prose a lane receives and nothing else. It is re-measured with
`content_bounds`, and that is only reachable because #1203ky fixed the reference resolver --
before that `im` was None for every screen in the corpus.

`dataset` is read by `_content_entity_from_design` (#513) at four call sites in the frontend
projector. Restoring it ALONE is harmful, and that is #1203l1: measured on the restored
manifests, #513 answers `comments` in 36 of 36 runs. r185 stages comments.json (295 rows, an
`avatar` column), videos.json (35 rows, `thumbnail`) and users.json (9 rows, `avatar`); #513
takes the matching table with the MOST records, and an avatar is the author's face hanging off
a row, so every chatty table has one and record count elects the chattiest. With `avatar` out
of the pattern, all 36 pick `videos`.

That is the same word and the same mistake as #1203kx, which took `avatar` out of
`_ref_image_pool`'s `_EXCLUDE` siblings for the same reason on the same day. The pattern here
has exactly ONE consumer, so the change cannot touch a "this column holds an image, render it"
decision anywhere.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import design_prep as DP  # noqa: E402
from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402
from multi_agent.runtime import material_prep as MP  # noqa: E402


def _staged_run(tmp_path):
    """A run directory shaped like the real thing: a staged reference and a staged dataset."""
    from PIL import Image
    refs = tmp_path / "design" / "references"
    refs.mkdir(parents=True)
    im = Image.new("RGB", (60, 40), (8, 8, 8))
    for x in range(10, 50):
        for y in range(8, 32):
            im.putpixel((x, y), (240, 240, 240))
    im.save(refs / "home_feed.png")

    data = tmp_path / "design" / "dataset"
    data.mkdir(parents=True)
    (data / "videos.json").write_text(json.dumps(
        [{"id": i, "caption": "c", "thumbnail": "t.jpg"} for i in range(4)]), encoding="utf-8")
    (data / "comments.json").write_text(json.dumps(
        [{"video_id": 1, "text": "x", "avatar": "a.jpg"} for _ in range(40)]), encoding="utf-8")
    return tmp_path


def _doc():
    return {"design_system": {"palette": {"bg": "#000"}},
            "screens": [{"name": "home_feed",
                         "reference": "design/references/home_feed.png",
                         "components": [{"id": "hero", "region": [0, 0, 30, 20],
                                         "colors": {"bg": "#111"}}]}],
            "assets": []}


def test_the_screen_layout_is_measured_again(tmp_path):
    out = _staged_run(tmp_path)
    doc = _doc()
    assert not doc["screens"][0].get("layout_metrics"), "NON-VACUITY: absent to begin with"
    res = DP.complete_design_system(doc, {}, out)
    lm = res["screens"][0].get("layout_metrics") or {}
    assert lm, lm
    # it is a MEASUREMENT, not a placeholder: content bounds of the light block above
    assert lm.get("content") is not False, lm
    assert any(isinstance(v, (int, float)) for v in lm.values()), lm


def test_a_layout_the_analyst_authored_is_kept(tmp_path):
    out = _staged_run(tmp_path)
    doc = _doc()
    doc["screens"][0]["layout_metrics"] = {"content": True, "mine": 1}
    res = DP.complete_design_system(doc, {}, out)
    assert res["screens"][0]["layout_metrics"] == {"content": True, "mine": 1}


def test_the_dataset_manifest_is_rebuilt_from_the_staged_files(tmp_path):
    out = _staged_run(tmp_path)
    res = DP.complete_design_system(_doc(), {}, out)
    got = {e["id"]: e for e in (res.get("dataset") or [])}
    assert set(got) == {"videos", "comments"}, got
    assert got["videos"]["records"] == 4 and got["comments"]["records"] == 40, got
    assert got["videos"]["columns"] == ["id", "caption", "thumbnail"], got["videos"]
    # the runtime location, which is what the readers use
    assert got["videos"]["staged_path"] == "backend/dataset/videos.json", got["videos"]
    # and nothing was copied on top of itself
    assert sorted(p.name for p in (out / "design" / "dataset").iterdir()) == [
        "comments.json", "videos.json"]


def test_a_dataset_the_analyst_authored_is_not_replaced(tmp_path):
    out = _staged_run(tmp_path)
    doc = _doc()
    doc["dataset"] = [{"id": "mine", "file": "x.json"}]
    res = DP.complete_design_system(doc, {}, out)
    assert res["dataset"] == [{"id": "mine", "file": "x.json"}], res["dataset"]


def test_the_entry_shape_has_one_owner():
    """#1032: the restore calls `ingest_dataset` with `stage=False` instead of writing a
    second loop, so the entry shape and the id de-duplication cannot drift."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(DP.complete_design_system))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("material_prep"):
            names |= {a.name for a in n.names}
    assert "ingest_dataset" in names, names
    # and the call passes stage=False, or it would copy the staged files onto themselves
    kw = [k for n in ast.walk(tree) if isinstance(n, ast.Call)
          for k in (n.keywords or []) if k.arg == "stage"]
    assert kw and all(isinstance(k.value, ast.Constant) and k.value.value is False
                      for k in kw), ast.dump(tree)[:200]


def test_the_restored_manifest_elects_the_visual_catalog_1203l1(tmp_path):
    """#1203l1. The fixture mirrors the corpus: a comments table with an `avatar` column and
    many rows, a videos table with a `thumbnail` and few."""
    out = _staged_run(tmp_path)
    res = DP.complete_design_system(_doc(), {}, out)
    assert FS._content_entity_from_design(res) == "videos", (
        res.get("dataset"), FS._CONTENT_IMG_COL_RE.pattern)
    # NON-VACUITY: the chooser is alive and does prefer records among real catalogs
    two = {"dataset": [{"id": "small", "columns": ["poster"], "records": 2},
                       {"id": "big", "columns": ["poster"], "records": 99}]}
    assert FS._content_entity_from_design(two) == "big", two


def test_an_avatar_only_table_is_not_a_catalog():
    assert FS._content_entity_from_design(
        {"dataset": [{"id": "comments", "columns": ["text", "avatar"], "records": 900}]}) is None
    # a table that has BOTH is still a catalog, by its content column
    assert FS._content_entity_from_design(
        {"dataset": [{"id": "titles", "columns": ["avatar", "poster"], "records": 3}]}) == "titles"
    assert "avatar" not in FS._CONTENT_IMG_COL_RE.pattern, FS._CONTENT_IMG_COL_RE.pattern


def test_the_corpus_runs_restore_and_elect_videos(tmp_path):
    """The measurement in the docstring, against the real staged dataset files. The pass
    writes design_system.json, so it is pointed at a scratch dir whose design/dataset
    SYMLINKS the corpus files -- never at a run. Skipped when the corpus is absent."""
    import pytest
    runs = []
    for p in sorted((ROOT.parent / "generated").glob("*/design/dataset")):
        m = re.search(r"r(\d+)$", p.parent.parent.name)
        if m and int(m.group(1)) >= 150 and p.is_dir() and any(p.iterdir()):
            runs.append(p)
    if len(runs) < 10:
        pytest.skip("too few corpus dataset dirs on this disk (%d)" % len(runs))
    picked = []
    for i, dsdir in enumerate(runs):
        work = tmp_path / ("r%d" % i) / "design"
        work.mkdir(parents=True)
        (work / "dataset").symlink_to(dsdir)
        res = DP.complete_design_system(
            {"design_system": {}, "screens": [], "assets": []}, {}, work.parent)
        assert res.get("dataset"), dsdir
        picked.append(FS._content_entity_from_design(res))
    assert picked and all(p == "videos" for p in picked), (
        "the corpus is tiktok-shaped; a different product here means update the assertion",
        sorted(set(picked)))
