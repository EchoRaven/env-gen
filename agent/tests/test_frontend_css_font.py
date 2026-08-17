"""render_measured_base_css must emit a font-family STRING, not a Python dict repr.

The measured font_stack is a dict {'display','ui','note'}; str(dict) put a Python literal
into `font-family` → postcss "Missed semicolon" → npm run build fails → docker_up wedge
(netflix r1). Body uses the 'ui' stack; 'note' is metadata.
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import render_measured_base_css

def _css(ds): return render_measured_base_css(ds, font_files=["ui_inter_x.woff2"])

def test_dict_font_stack_emits_ui_string():
    css = _css({"design_system": {"font_stack": {
        "display": "'Anton',sans-serif", "ui": "'Inter',sans-serif", "note": "shipped fonts x"}}})
    assert "font-family: 'Inter',sans-serif;" in css
    assert "{'" not in css and "'note'" not in css

def test_dict_falls_back_to_display_when_no_ui():
    css = _css({"design_system": {"font_stack": {"display": "'Anton',sans-serif"}}})
    assert "font-family: 'Anton',sans-serif;" in css and "{'" not in css

def test_legacy_string_font_stack_preserved():
    css = _css({"design_system": {"font_stack": "'Inter',sans-serif"}})
    assert "font-family: 'Inter',sans-serif;" in css

def test_no_dict_repr_anywhere():
    css = _css({"design_system": {"font_stack": {"display": "a", "ui": "b", "note": "c"}}})
    assert "'note'" not in css and "{'display'" not in css

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
