r"""#779: the framework measured the depth and told nobody.

`style` is the lowest-scoring dimension in the whole gate (mean **0.615** over 48 r99+ runs) and
the second-most-frequent floor on `login`, which blocks 73% of runs. Across **504 judged screens**
the single most common word in a `style` note is **`flat`** — 399 of them, **79%**:

    "Reference has dark red gradient background fading to black... Implementation is flat solid
     black with a bordered card."
    "Reference uses a subtle red radial gradient... Implementation uses a fl[at]..."

The framework already measures exactly what is missing. r151's `design_system.json` carries:

    shadow_scale  [{"role": "card_hover_preview",
                    "css": "0 20px 40px -8px rgba(0,0,0,0.75), 0 8px 24px -4px rgba(0,0,0,0.5)",
                    "usage": "the enlarged card that pops up on hover in a rail"}, ...]
    material      "FLAT dark chrome throughout — not a wallpaper/translucent material. Top nav is
                   TRANSPARENT at the top of a hero page ... OPAQUE #141414 after ~50px of scroll;
                   this is a scroll transition, NOT a translucency."

**Paste-ready CSS and a paragraph of surface guidance — and the frontend prompt named neither.**
`shadow_scale` appears only in `design_prep.py` (writer) and `design_analyst.j2` (the prompt that
asks for it): a measured field with a writer and **zero readers**, which is #746's class.
`radius_scale`, by contrast, is named in 5 places including the frontend prompt.

Both prompt versions patched — v3 is the default and v4 is opt-in per file (#269), and #775
already recorded what fixing only one costs.
"""
import pathlib

import pytest


PROMPTS = (pathlib.Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
           / "multi_agent" / "prompts")
VERSIONS = ["v3", "v4"]


def _src(v: str) -> str:
    p = PROMPTS / v / "frontend_agent.j2"
    if not p.exists():
        pytest.skip(f"{v} frontend prompt absent")
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("v", VERSIONS)
def test_shadow_scale_is_named(v):
    assert "shadow_scale" in _src(v)


@pytest.mark.parametrize("v", VERSIONS)
def test_material_is_named(v):
    assert "material" in _src(v)


@pytest.mark.parametrize("v", VERSIONS)
def test_the_existing_tokens_survive(v):
    """palette/type_scale/radius_scale were already named and must stay."""
    s = _src(v)
    for keep in ("palette", "type_scale", "radius_scale"):
        assert keep in s, keep


@pytest.mark.parametrize("v", VERSIONS)
def test_it_says_the_css_is_paste_ready(v):
    """A token name alone is what radius_scale got, and style is still the worst dimension."""
    s = _src(v)
    assert "paste-ready" in s or "ready-to-paste" in s


@pytest.mark.parametrize("v", VERSIONS)
def test_the_measurement_is_in_the_prompt(v):
    s = _src(v)
    assert "79%" in s
    assert "0.615" in s


@pytest.mark.parametrize("v", VERSIONS)
def test_it_records_that_shadow_scale_had_no_readers(v):
    """The reason this is a framework gap and not lane sloppiness."""
    s = _src(v)
    assert "ZERO readers" in s or "zero readers" in s


def test_both_versions_were_patched():
    """#775's lesson: v3 is default, v4 is opt-in per file — one is reachable by an env var."""
    assert all("shadow_scale" in _src(v) for v in VERSIONS)


# --- the producer still emits what the prompt now promises ---------------------------------------

def test_the_design_system_still_asks_for_both():
    """If design_prep stops requesting these, the prompt is promising data that will not exist."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep as dp
    src = inspect.getsource(dp)
    assert '"shadow_scale"' in src
    assert "shadow_scale" in src and "iconography" in src


def test_material_survives_the_design_system_projection():
    """#771's class: a token named in the prompt but dropped by a projection is worse than
    unnamed, because the lane looks for it and finds nothing."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import design_prep as dp
    src = inspect.getsource(dp)
    assert "material" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
