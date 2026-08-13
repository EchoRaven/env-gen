r"""#644: every screen was judged against a reference 13% out of proportion.

`_VIEWPORT` is the one constant in visual_fidelity carrying no measured rationale. Measuring it
against the reference corpus says why that matters — over all **900** reference images in the 45
kept runs:

    reference aspect   1.7297 – 1.7391   median 1.7344   (tighter than half a percent)
    capture aspect     1380 x 900 = 1.5333
    matching height at width 1380 = 796px, not 900
    => +13.1% relative vertical error, on every screen of every run

Two things ride on it, both silent:

  * the judge compares a 1.533 image against a 1.736 one, so the app looks vertically stretched
    against its reference before any lane has done anything wrong;
  * `_measured_deviations` samples "the SAME fractional regions" from a spec measured on the
    reference. Fractions are resolution-independent but NOT aspect-independent — at 13% the
    sample drifts further from its intended content the lower down the page it sits.

Width is kept: it is a real desktop breakpoint and the layout responds to width, not to aspect.
900 stays as the fallback for a run with no references, which is the pre-#644 behaviour.

This moves every score — that is the point — and costs comparability with the 32 historical runs.
Comparing differently-proportioned images was wrong independently of that.

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


def test_the_capture_call_uses_it():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.capture_route_screenshots)
    assert "capture_viewport_644(out_dir)" in src
    assert "viewport=_VIEWPORT" not in src


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf).replace("#", " ").split())
    assert "median **1.7344**" in flat and "**13.1%**" in flat
    assert "costs comparability with the 32 historical runs" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
