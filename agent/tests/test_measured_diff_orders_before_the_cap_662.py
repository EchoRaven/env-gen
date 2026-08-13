r"""#662: the 10-line measured-diff window was filled in list order, hiding 21% of the facts.

`measured_deviations` is the richest artifact the gate produces and the one I nearly declared
exhausted — 13,750 structured records of {component, kind, expected, actual, distance, region}.
An earlier probe of mine reported it EMPTY because it only counted string elements; the entries
are dicts. That claim is retracted.

Two kinds live in it: `background` (carries a measured `distance`) and `accent_missing` (does
not). `_measured_diff_lines` renders `devs[:10]` in list order under the banner *"facts, not the
judge's opinion; apply these EXACT values"*, and `accent_missing` is ~34% of all measurements —
so the entries WITH a measured delta were being crowded out by the entries without one:

    498 of 1248 screens (40%) had at least one background deviation hidden by the cap
    1881 of 9132 background deviations (21%) never reached the lane

Ordering background-first, then widest gap first, recovers 1012 of them (+14%). It is a
REORDER: nothing is dropped that the cap was not already dropping, and no tuned constant is
introduced.

The accent line is also softened, because its `expected` is sampled from a region of the
REFERENCE IMAGE and on a nav or hero that region often shows artwork through transparent chrome:

    64% (2959 of 4618) are not attributable to the design's own measured palette
    median saturation 0.56 against the brand accent's 0.96
    hue split green 32% / gold 27% / purple 23% / blue 15% / RED 4% — for a red-accent product
    top component: top_nav_bar (546), whose reference nav is transparent over the hero photo

Filtering them on colour was tried and REJECTED rather than shipped: palette-distance and
saturation both separate (red sits at distance 36 vs 73, saturation 0.83 vs 0.37-0.65) but no
cut is clean — the best one still discarded 27% of the genuine red accents. Losing real signal
to suppress noise is the wrong trade, so the line says what it is instead.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _measured_diff_lines as lines,
)


def _bg(name, dist, expected="#141414", actual="#000000"):
    return {"component": name, "kind": "background", "expected": expected,
            "actual": actual, "distance": dist}


def _accent(name, hue="green", expected="#427c3f"):
    return {"component": name, "kind": "accent_missing", "hue": hue, "expected": expected}


def _render(devs):
    return lines({"measured_deviations": devs})


def _bullets(out):
    return [l.strip() for l in out if l.strip().startswith("·")]


# --- the crowding is gone -----------------------------------------------------------------

def test_a_background_deviation_survives_a_flood_of_accents():
    """The defect: 12 accents filled the window and both measured deltas vanished."""
    devs = [_accent(f"a{i}") for i in range(12)] + [_bg("nav", 54.0)]
    body = "\n".join(_render(devs))
    assert "nav: background renders" in body


def test_backgrounds_lead():
    out = _bullets(_render([_accent("a"), _bg("nav", 54.0), _accent("b")]))
    assert "background" in out[0]


def test_the_widest_gap_comes_first():
    """Within backgrounds, the biggest measured delta is the biggest lever."""
    out = _bullets(_render([_bg("small", 12.0), _bg("huge", 300.0), _bg("mid", 90.0)]))
    assert [l.split(":")[0].strip("· ") for l in out[:3]] == ["huge", "mid", "small"]


def test_the_cap_is_unchanged():
    """A REORDER, not a widening — 10 lines in, 10 lines out."""
    out = _bullets(_render([_bg(f"b{i}", float(i)) for i in range(30)]))
    assert len(out) == 10


def test_nothing_is_dropped_that_the_cap_was_not_already_dropping():
    devs = [_bg("a", 10.0), _accent("b")]
    assert len(_bullets(_render(devs))) == 2


def test_a_missing_distance_sorts_last_without_crashing():
    devs = [{"component": "x", "kind": "background", "expected": "#000", "actual": "#fff"},
            _bg("y", 99.0)]
    out = _bullets(_render(devs))
    assert out[0].startswith("· y")


# --- the accent line is honest about what it is -------------------------------------------------

def test_the_accent_line_is_conditional_not_imperative():
    body = "\n".join(_render([_accent("top_nav_bar")]))
    assert "restore it IF it is chrome" in body


def test_it_warns_that_the_sample_can_be_artwork():
    body = "\n".join(_render([_accent("top_nav_bar")]))
    assert "artwork showing through transparent chrome" in body
    assert "poster/backdrop rather than a control" in body


def test_the_accent_still_names_component_hue_and_colour():
    """Softening must not cost the actionable content."""
    body = "\n".join(_render([_accent("hero_billboard", hue="gold", expected="#eeb95b")]))
    assert "hero_billboard" in body and "gold" in body and "#eeb95b" in body


def test_the_background_line_is_still_imperative():
    """Those ARE facts — the hedge must not leak onto them."""
    body = "\n".join(_render([_bg("nav", 54.0)]))
    assert "set it to" in body
    assert "IF it is chrome" not in body


# --- the surrounding body is untouched --------------------------------------------------------

def test_the_header_still_claims_measured_facts():
    body = "\n".join(_render([_bg("nav", 54.0)]))
    assert "MEASURED COLOR DIFF" in body


def test_no_deviations_produces_no_lines():
    assert _render([]) == []
    assert lines({}) == []


def test_it_does_not_mutate_the_caller_list():
    devs = [_accent("a"), _bg("b", 5.0)]
    before = [dict(d) for d in devs]
    _render(devs)
    assert devs == before


def test_it_is_deterministic():
    devs = [_accent("a"), _bg("b", 5.0), _bg("c", 5.0)]
    assert _render(devs) == _render(devs)


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._measured_diff_lines).replace("#", " ").split())
    assert "498 of 1248 screens" in flat
    assert "1881 of 9132" in flat


def test_the_rejected_alternative_is_recorded():
    """A future reader will propose filtering by colour; the reason not to must be in place."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._measured_diff_lines).split())
    assert "lost 27% of the genuine red ones" in flat
    assert "2959 of" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
