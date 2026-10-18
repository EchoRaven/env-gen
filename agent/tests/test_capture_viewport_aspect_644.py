r"""#644: the capture and the reference are different shapes — measured, then NOT acted on.

`_VIEWPORT` is the one constant in visual_fidelity carrying no measured rationale. Measuring it
against the reference corpus says why that matters — over all **900** reference images in the 45
kept runs:

    reference aspect   1.7297 – 1.7391   median 1.7344   (tighter than half a percent)
    capture aspect     1380 x 900 = 1.5333
    matching height at width 1380 = 796px, not 900   => 13.1% apart

I changed the viewport to 796 and then measured the consequence instead of assuming it. On 389
screens where a top edge is detectable in BOTH images:

    reference top edge   97px of 1107  -> fraction 0.0876
    capture   top edge   86px of  900  -> fraction 0.0956

The two objectives point in OPPOSITE directions:

    same IMAGE SHAPE (what the judge compares)                 -> 796px
    same CONTENT FRACTION (what the spec sampler assumes)      -> 981px

because web layout is absolute from the top and scales with WIDTH — a shorter viewport makes a
fixed-height nav bar occupy a LARGER fraction, not a smaller one. 796px would have taken the
sampler's error from +9.1% to +23%.

So the change is REVERTED and only the measurement is kept. I have no offline evidence that the
judge scores a same-shaped pair any better, and the one half I could measure moved the wrong way.
The calculation is retained, unused by the capture path, so whichever direction a run's data
supports can be wired without re-deriving it. Same call as #628b.

#1203oa — THE RECORDED RANGE ABOVE NO LONGER DESCRIBES ONE IMAGE IN THE CORPUS, and a future
wiring would read it. Re-measured over the 406 reference images in today's 32 runs:

    range 1.4222 – 1.8467   median 1.7732   -> 0 of 406 (0%) inside 1.7297-1.7391
    histogram (2dp): 1.77 x250, 1.84 x75, 1.76 x36, 1.78 x25, 1.85 x9, 1.42 x8, 1.83 x3

The BAND is what went, not just the number: #644 could call its spread "tighter than half a
percent" and lean on the median, while today's data is bimodal (a 1.77 mass, a 1.84 mass, and
8 instagram login variants at 1.42). And the gap WIDENED -- 1.7732 against 1.5333 is 15.6%
apart, not 13.1% -- so the calculation yields 778px today where it yielded 796px then.

The decision stands: its reasoning never depended on the exact median, the two objectives
still point in opposite directions, and the half that can be measured still moves the wrong
way. `test_the_recorded_range_still_describes_the_corpus_1203oa` below is the ratchet, so the
number cannot rot silently a third time.

The SYNTHETIC fixtures below are deliberately left at 1920x1107 (= 1.7344). They test the
FUNCTION -- "given this aspect, compute this height" -- which is independent of what the
corpus happens to contain, and rewriting them to today's median would test nothing new while
losing the 796 arithmetic that is already checked by hand.

Finding it took three wrong instruments, all caught: `screenshots/*.png` (1280x720) is the browser
test-users' output, not the gate's; the gate writes `design/visual_gate/**` at 1380x900. Measuring
the wrong directory produced a confident aspect comparison about images the judge never sees.
"""
from pathlib import Path

import pytest
from PIL import Image

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _VIEWPORT,
    _VIEWPORT_FALLBACK_H_644 as FALLBACK_H,
    capture_viewport_644 as viewport,
)


def _refs(root, sizes):
    d = root / "design" / "references"
    d.mkdir(parents=True, exist_ok=True)
    for i, (w, h) in enumerate(sizes):
        Image.new("RGB", (w, h), (10, 10, 10)).save(d / f"ref_{i}.png")
    return root


# --- the measured case ---------------------------------------------------------------------------

def test_the_real_reference_shape_yields_796(tmp_path):
    """1920x1107 is the corpus median (1.7344); at width 1380 that is 796px, not 900."""
    vp = viewport(_refs(tmp_path, [(1920, 1107)]))
    assert vp == {"width": 1380, "height": 796}


def test_the_aspect_now_matches_the_reference(tmp_path):
    vp = viewport(_refs(tmp_path, [(1920, 1107)]))
    assert abs(vp["width"] / vp["height"] - 1920 / 1107) < 0.01


def test_the_old_fixed_height_was_13_percent_out():
    """The number this fix exists for."""
    assert abs((900 * (1920 / 1107) / 1380) - 1) == pytest.approx(0.131, abs=0.005)


def test_the_median_is_used_not_the_first_or_the_extreme(tmp_path):
    root = _refs(tmp_path, [(1920, 1104), (1920, 1107), (1920, 1109), (100, 900)])
    assert viewport(root)["height"] == pytest.approx(796, abs=2)


def test_width_is_never_changed(tmp_path):
    """A real breakpoint — the app's layout responds to width, not to aspect."""
    for sizes in ([(1920, 1107)], [(800, 600)], []):
        assert viewport(_refs(tmp_path / str(len(sizes)), sizes))["width"] == _VIEWPORT["width"]


# --- fallbacks -------------------------------------------------------------------------------

def test_no_references_keeps_the_previous_behaviour(tmp_path):
    assert viewport(tmp_path)["height"] == FALLBACK_H


def test_an_empty_references_dir_falls_back(tmp_path):
    assert viewport(_refs(tmp_path, []))["height"] == FALLBACK_H


def test_a_corrupt_image_is_skipped(tmp_path):
    root = _refs(tmp_path, [(1920, 1107)])
    (root / "design" / "references" / "broken.png").write_text("not an image", encoding="utf-8")
    assert viewport(root)["height"] == 796


def test_a_nonsense_aspect_is_refused(tmp_path):
    """A 1x5000 sliver must not produce a 0-pixel viewport."""
    root = _refs(tmp_path, [(1, 5000)])
    assert viewport(root)["height"] >= 320


def test_non_image_files_are_ignored(tmp_path):
    root = _refs(tmp_path, [(1920, 1107)])
    (root / "design" / "references" / "notes.md").write_text("x", encoding="utf-8")
    assert viewport(root)["height"] == 796


def test_a_bad_path_never_raises(tmp_path):
    assert viewport(None)["height"] == FALLBACK_H
    assert viewport(tmp_path / "nope")["height"] == FALLBACK_H


# --- it is found from anywhere in the tree ---------------------------------------------------

def test_it_resolves_from_the_out_dir_not_the_project_root(tmp_path):
    """The capture helper is handed `out_dir`, which sits several levels inside the project."""
    root = _refs(tmp_path, [(1920, 1107)])
    out = root / "design" / "visual_gate" / "history"
    out.mkdir(parents=True)
    assert viewport(out)["height"] == 796


def test_the_capture_path_is_UNCHANGED():
    """The behaviour change was reverted: 796px fixes the judge's picture-shape and breaks the
    spec sampler, and only the second half is measurable offline. The calculation stays; the
    capture keeps the fixed viewport until a run says which direction pays."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.capture_route_screenshots)
    assert "viewport=_VIEWPORT" in src
    assert "capture_viewport_644(out_dir)" not in src


def test_both_targets_and_the_conflict_are_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf).replace("#", " ").split())
    assert "OPPOSITE directions" in flat
    assert "-> 796px" in flat and "-> 981px" in flat
    assert "+9.1% to +23%" in flat


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf).replace("#", " ").split())
    assert "median 1.7344" in flat and "13.1% apart" in flat
    assert "fraction 0.0876" in flat and "fraction 0.0956" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_the_recorded_range_still_describes_the_corpus_1203oa():
    """#1203oa: the numbers in this file's docstring are load-bearing for a future wiring, so
    they must keep matching the corpus. #644's original range (1.7297-1.7391) described 0 of
    406 images by the time anyone looked again.

    Asserts the RE-MEASURED range, with a margin, rather than the exact median: the point is
    to catch another silent drift, not to fail on one new reference image.
    """
    import glob
    import statistics
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    root = Path(__file__).resolve().parents[2] / "generated"
    if not root.is_dir():
        pytest.skip("no generated/ corpus on this machine")
    asp = []
    for f in sorted(root.glob("*/design/references/*.png")):
        try:
            with Image.open(f) as im:
                w, h = im.size
        except Exception:
            continue
        if w > 0 and h > 0:
            asp.append(w / h)
    if len(asp) < 50:
        pytest.skip("too few reference images on this disk to re-measure")
    med = statistics.median(asp)
    assert 1.70 <= med <= 1.85, (
        "the reference aspect median moved to %.4f, outside the band #1203oa recorded "
        "(1.7732). The #644 decision is unaffected but its numbers are stale again — "
        "re-measure and update both docstrings." % med)
    inside = sum(1 for a in asp if 1.40 <= a <= 1.86)
    assert inside == len(asp), (
        "%d of %d reference aspects fell outside the re-measured 1.4222-1.8467 range"
        % (len(asp) - inside, len(asp)))
