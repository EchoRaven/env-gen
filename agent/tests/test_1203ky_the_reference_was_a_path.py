"""#1203ky: the screen's reference was a path, and the resolver only knew basenames.

`screen["reference"]` is a BASENAME when `build_skeleton_design_system` writes it and a PATH
when the spawned design_analyst rewrites the document:

    "reference": "design/references/fyp_feed_logged_out.png"

`_reference_path` joined that onto `design/references/`, so it looked for
`design/references/design/references/fyp_feed_logged_out.png`, and its `resolved` fallback
compared a basename against the same path. Both miss, silently, and the caller treats a None
as "this screen has no reference".

MEASURED over the 39 modern runs, 429 screens: **0** resolve today, 308 resolve on the
basename, 121 have no staged reference at all. What that costs is the per-component CROP at
`design/crops/<screen>__<id>.png`, which #461 hands to the frontend lane so it can look at one
component in isolation: 38 of 39 modern runs have ZERO crops on disk while all 1341 of their
components carry a `region`, and instagram-core-r174 is the only one with a crops directory.

The same loop also measures `colors.bg`, and that half is NOT what this recovers — all 1341
modern components already carry one. Both counters read 0; only one of them was a loss. Said
here because the counter alone would have let me claim twice the defect I found.

#1032: `visual_fidelity._lane_visible_reference` already takes `Path(raw).name` for this exact
reason, in its own words — "``screen["path"]`` is the orchestrator-side ORIGINAL (often a
host-absolute CLI path the lane's workspace cannot resolve)". Two owners for "resolve a
screen's reference to a staged file"; this was the one that only knew one shape.
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

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082")


def _run(tmp_path, refname="login_modal.png"):
    d = tmp_path / "design" / "references"
    d.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (40, 30), (10, 20, 30)).save(d / refname)
    return tmp_path


def test_both_shapes_of_the_stored_reference_resolve(tmp_path):
    out = _run(tmp_path)
    as_path = {"reference": "design/references/login_modal.png"}
    as_base = {"reference": "login_modal.png"}
    assert DP._reference_path(as_path, {}, out) == out / "design/references/login_modal.png"
    assert DP._reference_path(as_base, {}, out) == out / "design/references/login_modal.png"


def test_a_reference_with_nothing_on_disk_is_still_none(tmp_path):
    """The empty-name cases hold, but the early return that handles them is a SEMANTIC
    NO-OP: `Path("").name` is `""`, the join yields the references directory, `is_file()` is
    False, and an empty basename matches nothing in `resolved`. Mutation cannot distinguish
    it, which is why the function says so in its own words."""
    out = _run(tmp_path)
    assert DP._reference_path({"reference": "design/references/absent.png"}, {}, out) is None
    assert DP._reference_path({"reference": ""}, {}, out) is None
    assert DP._reference_path({}, {}, out) is None


def test_the_resolved_fallback_also_compares_basenames(tmp_path):
    """The second chance is for a reference that was never staged, and it had the same bug:
    it compared `Path(r).name` against the stored value, which is a path."""
    src = tmp_path / "input"
    src.mkdir()
    from PIL import Image
    Image.new("RGB", (8, 8)).save(src / "home_feed.png")
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    got = DP._reference_path({"reference": "design/references/home_feed.png"},
                             {"references": [str(src / "home_feed.png")]}, out)
    assert got == src / "home_feed.png", got


def test_the_crop_comes_back(tmp_path):
    """The half that matters. The bg assertion at the end tests the loop, not a corpus
    defect: every modern component already carries a `colors.bg`."""
    out = _run(tmp_path, "home_feed.png")
    ds = {
        "design_system": {"palette": {"bg": "#000"}},
        "screens": [{
            "name": "home_feed",
            # the analyst's shape, which is what made this dead
            "reference": "design/references/home_feed.png",
            "components": [{"id": "hero", "region": [0, 0, 20, 15], "colors": {}}],
        }],
        "assets": [],
    }
    before = DP._reference_path(ds["screens"][0], {}, out)
    assert before is not None, "NON-VACUITY: the fixture must be resolvable"

    res = DP.complete_design_system(ds, {}, out)
    comp = res["screens"][0]["components"][0]
    assert comp.get("crop") == "design/crops/home_feed__hero.png", comp
    assert (out / comp["crop"]).is_file(), sorted(
        p.name for p in (out / "design" / "crops").iterdir()) if (
            out / "design" / "crops").is_dir() else "no crops dir"
    # and the measured background that the same loop supplies
    assert comp["colors"].get("bg"), comp["colors"]


def test_the_modern_corpus_screens_resolve_now():
    """The measurement in the docstring, re-run. Read-only: it resolves paths and opens
    nothing. Skipped when the corpus is not on this disk."""
    import pytest
    screens = []
    for p in sorted((ROOT.parent / "generated").glob("*/design/design_system.json")):
        m = re.search(r"r(\d+)$", p.parent.parent.name)
        if not m or int(m.group(1)) < 150:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for s in (d.get("screens") or []):
            screens.append((p.parent.parent, s))
    if len(screens) < 50:
        pytest.skip("too few corpus screens on this disk (%d)" % len(screens))
    hit = sum(1 for run, s in screens if DP._reference_path(s, {}, run) is not None)
    # 308 of 429 when this was measured; the rest have no staged reference at all.
    assert hit >= len(screens) * 0.65, (hit, len(screens))
    # and the shape that used to miss is the common one
    paths = sum(1 for _r, s in screens if "/" in str(s.get("reference") or ""))
    assert paths > len(screens) * 0.5, (paths, len(screens))
