"""#1202cp — an asset path without a leading slash fetches the app shell, not the image.

`_ASSET_REF_1202J` requires a leading slash, so the relative form was invisible to it. That
is how #1202co survived: the DB held `assets/posters/x.jpg`, twelve render sites emitted it
verbatim, and on `/browse` the browser asked for `/browse/assets/posters/x.jpg` and got 200 +
index.html from the SPA fallback. Not a 404 — so no probe, no console error and no gate ever
saw it, and eleven screens scored a median 0.27 with every hero black.

#1202co fixes the source; this catches whatever gets past it.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    relative_asset_refs_1202cp as F, unstaged_asset_refs_1202j)


def _fe(tmp_path, files):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_a_relative_ref_is_named(tmp_path):
    out = F(_fe(tmp_path, {"P.jsx": "<img src=\"assets/posters/a.jpg\"/>"}))
    assert len(out) == 1 and "assets/posters/a.jpg" in out[0]


def test_a_rooted_ref_is_not_named(tmp_path):
    """THE control. `/assets/x.jpg` is the same file from every route and is correct."""
    assert F(_fe(tmp_path, {"P.jsx": "<img src=\"/assets/posters/a.jpg\"/>"})) == []


def test_a_dot_relative_ref_is_named(tmp_path):
    assert F(_fe(tmp_path, {"P.jsx": "<img src=\"./assets/a.jpg\"/>"})) != []


def test_absolute_urls_are_not_named(tmp_path):
    for src in ("https://cdn/assets/a.jpg", "http://x/assets/a.jpg", "data:image/png;base64,A"):
        assert F(_fe(tmp_path, {"P.jsx": f"<img src=\"{src}\"/>"})) == [], src


def test_the_seed_is_scanned_too(tmp_path):
    """The r38 shape: the frontend renders a value it reads from the API, so the bad path is
    in the DATA, not in any .jsx."""
    fe = _fe(tmp_path, {"P.jsx": "<img src={r.poster}/>"})
    seed = tmp_path / "seed_dataset.json"
    seed.write_text(json.dumps([{"poster": "assets/posters/a.jpg"}]), encoding="utf-8")
    out = F(fe, seed)
    assert any("assets/posters/a.jpg" in x for x in out)


def test_it_would_have_caught_1202co():
    """Ground truth: r38's own seed_dataset.json, the file that produced the black heroes."""
    d = Path("/data/common/haibotong/forgingground-gen/generated/netflix-local-r38/app")
    if not (d / "backend" / "seed_dataset.json").is_file():
        return
    out = F(d / "frontend", d / "backend" / "seed_dataset.json")
    assert len(out) >= 10, out[:3]


def test_the_older_check_is_blind_to_this(tmp_path):
    """Why a second detector exists at all: #1202j requires the leading slash, so it cannot
    see the shape that actually shipped."""
    fe = _fe(tmp_path, {"P.jsx": "<img src=\"assets/posters/a.jpg\"/>"})
    assert unstaged_asset_refs_1202j(fe) == []
    assert F(fe) != []


def test_a_missing_tree_is_silent(tmp_path):
    assert F(tmp_path / "nope") == []


def test_the_finding_reaches_a_lane():
    """#780/#947: a finding that only logs reaches nobody — measured at one filed task across
    154 runs."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    i = src.index("#1202cp %d asset path(s) are NOT root-relative")
    stanza = src[i:src.index("warn_once_1201(\"relative_asset_refs_1202cp", i)]
    assert "create_task(" in stanza and "assignee=\"frontend\"" in stanza


def test_the_task_explains_the_silent_200():
    """The reason this is worth a P1: the failure looks like success at every layer."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    i = src.index("Root-relative %d asset path(s)")
    stanza = src[i:src.index("assignee=", i)]
    assert "NOT a 404" in stanza and "200" in stanza
