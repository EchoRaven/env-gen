r"""#796: the measured content box reached the DESIGN prompt but not the REPAIR text.

#787 named `screens[].layout_metrics` to the frontend lane in both kickoff prompts, closing an
orphan (a field `design_prep.py` wrote and nobody read). But the kickoff prompt is read once, at
design time. What the lane reads on **every repair round** is `remediation_text()`, and its
LAYOUT GEOMETRY block carried only per-component regions — so the measurement was present when
designing and absent when fixing, which is the round that actually matters for a layout
deviation.

Per-component regions only *imply* the container. The case an implied container gets wrong is
full-bleed: `left 0, width 100%` means no max-width wrapper at all, and r151 carries **15 distinct
boxes across its 20 screens**, so it is not one global value to be inferred once.

Executed against the real builder rather than asserted against its source, because a source
assertion here is what #782 showed can pin a defect for 122 runs.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _ds(metrics=None, comps=True):
    screen = {"name": "login", "layout": "two-column split",
              "components": ([{"id": "form", "region": [0.5, 0.1, 0.9, 0.8],
                               "colors": {"bg": "#141414"}}] if comps else [])}
    if metrics is not None:
        screen["layout_metrics"] = metrics
    return {"screens": [screen]}


def _lines(metrics=None, comps=True):
    return vf._layout_geometry_lines(_ds(metrics, comps), "login")


def test_without_metrics_the_block_is_unchanged():
    """Non-vacuity + non-regression: the per-component rows are what existed before."""
    out = _lines(None)
    assert any("form" in l and "width 40%" in l for l in out)
    assert not any("CONTENT BOX" in l for l in out)


def test_the_content_box_is_stated():
    out = _lines({"left": 0.0344, "width": 0.9302})
    box = [l for l in out if "CONTENT BOX" in l]
    assert box, out
    assert "width 93%" in box[0]
    assert "x 3-96%" in box[0]      # 0.0344 + 0.9302 = 0.9646, not 0.97


def test_full_bleed_is_called_out_by_name():
    """The case an implied container always gets wrong."""
    out = _lines({"left": 0.0, "width": 1.0})
    box = next(l for l in out if "CONTENT BOX" in l)
    assert "FULL-BLEED" in box and "no max-width container" in box


def test_a_gutter_box_is_not_called_full_bleed():
    box = next(l for l in _lines({"left": 0.0344, "width": 0.9302}) if "CONTENT BOX" in l)
    assert "FULL-BLEED" not in box


def test_it_leads_the_component_rows():
    """The container decision must precede the components placed inside it. Indexed against the
    component row, not against out[0] — out[0] is the block HEADER, which the first version of
    this test forgot."""
    out = _lines({"left": 0.0, "width": 1.0})
    i_box = next(i for i, l in enumerate(out) if "CONTENT BOX" in l)
    i_comp = next(i for i, l in enumerate(out) if "form" in l)
    assert i_box < i_comp


def test_it_says_the_value_is_per_screen():
    """r151 has 15 distinct boxes over 20 screens — a lane that applies one globally is wrong on
    most of them, which is the failure this line exists to prevent."""
    box = next(l for l in _lines({"left": 0.0, "width": 1.0}) if "CONTENT BOX" in l)
    assert "per screen" in box and "screens differ" in box


@pytest.mark.parametrize("bad", [{}, {"left": "x", "width": 1.0}, {"left": 0.1},
                                 [0.0, 1.0], "nope", None])
def test_malformed_metrics_never_break_the_repair_text(bad):
    """This text is the largest object the system produces and the lane's only repair input —
    a fault here would cost a whole round."""
    out = _lines(bad)
    assert any("form" in l for l in out), "the rest of the block must survive"
    assert not any("CONTENT BOX" in l for l in out)


# --- #812: the measured vertical rhythm ---------------------------------------------------------

def _geo(**g):
    return {"screens": [{"name": "login", "layout": "x", "components": [
        {"id": "flyout", "region": [0.1, 0.1, 0.4, 0.9], "geometry": g}]}]}


def test_a_multi_row_component_gets_its_rhythm():
    """r151's profile flyout is 7 detected rows 57px apart — written by design_prep, read by
    nobody, while `layout` is a floor dimension and the repair text carried no spacing at all."""
    out = vf._layout_geometry_lines(_geo(rows=7, row_gap_px=57), "login")
    assert any("7 rows 57px apart (measured)" in l for l in out)


def test_a_single_row_component_gets_none():
    """One row has no rhythm; emitting '1 rows 0px apart' is noise on every nav bar."""
    out = vf._layout_geometry_lines(_geo(rows=1, pitch_px=7, columns=25), "login")
    assert not any("rows" in l and "apart" in l for l in out)


def test_the_stripe_measures_are_never_emitted():
    """★ `columns`/`pitch_px` are a low-level stripe detector — 25 "columns" at 7px pitch across a
    top nav is not a layout grid. Handing that to a lane as "columns" would be #782's mistake in
    reverse: a plausible NAME whose meaning does not match it. Looking at the values is what
    stopped it; the field had been deferred twice as "narrow" without ever being opened."""
    out = " ".join(vf._layout_geometry_lines(_geo(rows=7, row_gap_px=57, columns=25, pitch_px=7),
                                             "login"))
    assert "columns" not in out and "pitch" not in out


@pytest.mark.parametrize("g", [{}, {"rows": "x", "row_gap_px": 57}, {"rows": 7},
                               {"rows": 7, "row_gap_px": 0}, {"rows": 7, "row_gap_px": None}])
def test_malformed_geometry_leaves_the_row_intact(g):
    out = vf._layout_geometry_lines(_geo(**g), "login")
    assert any("flyout" in l and "width 30%" in l for l in out)
    assert not any("apart" in l for l in out)


def test_a_component_without_geometry_is_unchanged():
    ds = {"screens": [{"name": "login", "components": [
        {"id": "plain", "region": [0.2, 0.2, 0.5, 0.5]}]}]}
    out = vf._layout_geometry_lines(ds, "login")
    assert any("plain" in l for l in out) and not any("apart" in l for l in out)


def test_the_design_prompt_and_the_repair_text_now_agree():
    """#787 and #796 must name the same measurement, or the lane is told two different things at
    two different moments."""
    import pathlib
    prompts = pathlib.Path(__file__).resolve().parents[1] / (
        "env_generator/llm_generator/multi_agent/prompts")
    for v in ("v3", "v4"):
        s = (prompts / v / "frontend_agent.j2").read_text(encoding="utf-8")
        assert "layout_metrics" in s and "FULL-BLEED" in s, v


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
