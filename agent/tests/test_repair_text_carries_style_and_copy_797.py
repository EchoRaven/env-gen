r"""#797: the same #796 gap, for the two FLOOR dimensions.

#796's rule — *"has a reader" is not one question, it is one per moment the reader reads* — run as
a query over every measured field the kickoff prompt names. Occurrences in `visual_fidelity.py`,
which owns the repair text:

    shadow_scale     0      type_scale    0      radius_scale  0      build_notes  0
    material         2  -> all `material_prep`, the MODULE. Not the field.
    copy             7  -> the English word and the dimension key. Not the per-component field.

`_spec_snippet` carries colours, `_layout_geometry_lines` carries geometry (+ #796's content box).
Nothing carried **style** or **copy** — and those are precisely the two dimensions measured as
floors:

    style     lowest mean of any dimension, 0.615; `flat` in 79% of 504 notes   (#779)
    ui_copy   84% of 9152 text components DESCRIBE the text instead of quoting  (#778)

So both floors had their ground truth measured, written to `design_system.json`, and named to the
lane **only at design time** — absent from every repair round, which is the round with a concrete
score to move.

Executed, not source-asserted (#782). Both helpers return `[]` rather than raising on anything
malformed: this text is the lane's only repair input and a fault costs a whole round.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_DS = {
    "material": "FLAT dark chrome throughout — top nav TRANSPARENT over the hero, "
                "OPAQUE #141414 after ~50px of scroll",
    "shadow_scale": [{"role": "card_hover_preview", "css": "0 20px 40px -8px rgba(0,0,0,.75)"},
                     {"role": "modal", "css": "0 8px 24px rgba(0,0,0,.6)"}],
    "screens": [{"name": "login", "components": [
        {"id": "submit", "copy": "Sign In"},
        {"id": "help", "copy": "Need help?"},
        {"id": "logo"}]}],
}


# --- style ----------------------------------------------------------------------------------------

def test_the_measured_material_is_quoted():
    out = vf._style_lines_797(_DS, "login")
    assert any("MATERIAL (measured)" in l and "OPAQUE #141414" in l for l in out)


def test_the_shadow_scale_is_paste_ready():
    out = vf._style_lines_797(_DS, "login")
    assert any("box-shadow: 0 20px 40px -8px rgba(0,0,0,.75);" in l for l in out)


def test_the_header_carries_the_reason():
    """#779's measurement travels with the instruction, so a later reader can tell whether the
    line is load-bearing and can re-measure it."""
    out = vf._style_lines_797(_DS, "login")
    assert "0.615" in out[0] and "79%" in out[0]
    assert "do not default to flat" in out[0]


def test_nothing_measured_means_no_block():
    """Non-vacuity in the other direction — an empty header would be noise on every screen."""
    assert vf._style_lines_797({"shadow_scale": [], "material": ""}, "login") == []
    assert vf._style_lines_797(None, "login") == []


def test_the_design_system_may_be_nested():
    """design_system.json is read in two shapes across the corpus; both must work."""
    out = vf._style_lines_797({"design_system": {"material": "glassy translucent panels"}}, "x")
    assert any("glassy translucent" in l for l in out)


def test_duplicate_css_is_not_repeated():
    ds = {"shadow_scale": [{"role": "a", "css": "X"}, {"role": "b", "css": "X"}]}
    out = vf._style_lines_797(ds, "login")
    assert sum(1 for l in out if "box-shadow: X;" in l) == 1


# --- copy -----------------------------------------------------------------------------------------

def test_the_verbatim_copy_is_quoted():
    out = vf._copy_lines_797(_DS, "login")
    assert any('submit: "Sign In"' in l for l in out)
    assert any('help: "Need help?"' in l for l in out)


def test_a_component_without_copy_is_skipped():
    """An absent `copy` means the reference showed no text there — inventing one is the defect."""
    out = vf._copy_lines_797(_DS, "login")
    assert not any("logo" in l for l in out)


def test_the_instruction_forbids_paraphrase():
    out = vf._copy_lines_797(_DS, "login")
    assert "character for character" in out[0]
    assert "paraphrase" in out[0]


def test_an_unknown_screen_yields_nothing():
    assert vf._copy_lines_797(_DS, "no_such_screen") == []


# --- both, hardened -------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, {}, {"screens": "nope"}, {"shadow_scale": "nope"},
                                 {"screens": [{"name": "login", "components": "nope"}]},
                                 {"material": 12345}])
@pytest.mark.parametrize("fn", ["_style_lines_797", "_copy_lines_797"])
def test_malformed_input_never_raises(fn, bad):
    getattr(vf, fn)(bad, "login")          # must not raise


def test_both_are_wired_into_the_repair_text():
    import inspect
    src = inspect.getsource(vf.remediation_text)
    assert "_style_lines_797(_ds" in src and "_copy_lines_797(_ds" in src


def test_they_sit_with_the_other_measured_blocks():
    """Colours (_spec_snippet) and geometry (_layout_geometry_lines) already ship here; style and
    copy join them rather than living somewhere the lane reads at a different time."""
    import inspect
    src = inspect.getsource(vf.remediation_text)
    i_geo = src.index("_layout_geometry_lines(_ds")
    assert src.index("_style_lines_797(_ds") > i_geo
    assert "_spec_snippet(output_dir" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
