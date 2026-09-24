"""#1202co — a staged-asset path in a seed row must be ROOT-relative.

The staged dataset writes `assets/posters/movie_1275779.jpg` with no leading slash. That
value goes into the DB, out of the API, and straight into an `<img src>`. On `/browse` the
browser resolves it against the route, asks for `/browse/assets/posters/...`, and the SPA
fallback answers — with **200 and index.html**, not a 404. Nothing detects it: no network
error, no console error, no failing gate. The image renders as nothing.

r38 is what that costs. 368 assets staged, 31 paths seeded, 12 of 12 `<img>`/backgroundImage
sites rendering the raw value, every hero black and every poster a solid block. Its verdict:
eleven screens, median 0.27 against a 0.65 bar, the judge writing "implementation has only an
empty black background". The app was otherwise right — dark theme, correct nav, hero title,
metadata row, TOP-10 badge, synopsis, Play/More Info, rails.

Verified on the live r38 stack: `/assets/posters/movie_1275779.jpg` → 200, 102,684 bytes;
`/browse/assets/posters/movie_1275779.jpg` → 200, 1,226 bytes (the SPA shell).

Corpus: 39 of 101 runs carrying a staged dataset (39%), 4641 paths.
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

from multi_agent.runtime.material_prep import (  # noqa: E402
    _root_relative_asset_1202co as F, assemble_seed_dataset)


def test_the_r38_shape_is_rooted():
    assert F("assets/posters/movie_1275779.jpg") == "/assets/posters/movie_1275779.jpg"
    assert F("assets/backdrops/movie_1275779.jpg") == "/assets/backdrops/movie_1275779.jpg"


def test_a_dot_slash_prefix_is_also_rooted():
    assert F("./assets/backdrops/y.jpg") == "/assets/backdrops/y.jpg"


def test_an_already_rooted_path_is_untouched():
    assert F("/assets/posters/x.jpg") == "/assets/posters/x.jpg"


def test_absolute_urls_and_data_uris_are_untouched():
    """THE control. Rewriting these would break the very cases that already work."""
    for v in ("https://image.tmdb.org/t/p/w500/x.jpg", "http://cdn/x.png",
              "data:image/png;base64,AAAA"):
        assert F(v) == v, v


def test_ordinary_strings_are_untouched():
    """Only values pointing into the staged tree. `assets` appearing mid-string, a title, a
    synopsis — none of those are paths."""
    for v in ("Disclosure Day", "A show about assets/markets", "", "posters/x.jpg",
              "public/assets/x.jpg"):
        assert F(v) == v, v


def test_non_strings_pass_through():
    for v in (None, 42, 3.5, True, [], {}):
        assert F(v) is v or F(v) == v


def test_it_is_applied_when_the_dataset_is_folded_in(tmp_path):
    """End to end: the value that reaches seed_dataset.json is what reaches the DB, the API
    and the <img>. A normalizer that is never called changes nothing."""
    d = tmp_path / "dataset"
    d.mkdir()
    (d / "titles.json").write_text(json.dumps([
        {"id": 1, "name": "X", "poster": "assets/posters/a.jpg",
         "backdrop": "assets/backdrops/a.jpg", "video_url": "https://cdn/v.mp4"},
    ]), encoding="utf-8")
    out = assemble_seed_dataset(d)
    row = out["titles"][0]
    assert row["poster"] == "/assets/posters/a.jpg"
    assert row["backdrop"] == "/assets/backdrops/a.jpg"
    assert row["video_url"] == "https://cdn/v.mp4", "an external URL must survive"
    assert row["name"] == "X"


def test_the_real_r38_dataset_would_be_fixed():
    """Ground truth rather than a fixture: the file that produced the black heroes."""
    p = Path("/data/common/haibotong/forgingground-gen/generated/netflix-local-r38"
             "/design/dataset")
    if not p.is_dir():
        return
    out = assemble_seed_dataset(p)
    rows = out.get("titles") or []
    if not rows:
        return
    bad = [r[k] for r in rows for k in ("poster", "backdrop")
           if isinstance(r.get(k), str) and not r[k].startswith(("/", "http", "data:"))]
    assert bad == [], bad
