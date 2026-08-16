r"""#858: the filter controls render on their own row, above the page title.

Third-largest class in the corpus, and the last of the long-tail candidates item 180 left open:
**144 entries across 86 runs**, on `movies` (70 / 68 runs) and `shows` (66 / 64).

    "header: implementation has a SECOND ROW for genres; reference places 'tv shows'
     title + genres [on one line]"
    "sub-header: reference shows large 'movies' title left with genres dropdown"

★ **The complaint is never "missing".** `_control_bar_432b` works — it was written to fix controls
being dropped entirely. Only its PLACEMENT is wrong, which is exactly why every presence-shaped
probe called this class clean. A component can be present, correct, and still be the defect.

`_render_reference_page` concatenated `top_jsx + control_jsx + main_jsx`, and the page heading
lives *inside* `main_jsx`, so the rendered order was **nav → controls → title → grid** against a
reference that is **title + controls on one line → grid**.

`_heading_row_858` folds them into one flex row (title left, controls right) at all three heading
branches, and the standalone row is then skipped. The skip is detected **from the rendered markup**
(`_MERGED_CTL_CLS_858 in main_jsx`) rather than from a flag, so a branch that does not merge still
gets its own row and the controls can never render twice.

A screen with no filter controls gets the bare `<h2>` byte-for-byte as before.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _ctl(*roles):
    return fs._control_bar_432b([{"role": r, "id": r.replace(" ", "-")} for r in roles])


def test_the_control_bar_still_builds():
    """Non-vacuity: if #432b stopped emitting, every merged case below would pass by returning the
    unmerged branch."""
    assert "<select" in _ctl("genres dropdown")


def test_a_screen_without_controls_is_byte_identical():
    """The whole additive claim. Most screens have no filter."""
    assert fs._heading_row_858("Movies", "") == (
        '          <h2 className="mb-4 text-xl font-semibold">Movies</h2>\n')


@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t\n  "])
def test_whitespace_is_not_a_control_bar(blank):
    assert "<div" not in fs._heading_row_858("Movies", blank)


def test_the_title_and_the_control_share_one_row():
    out = fs._heading_row_858("Movies", _ctl("genres dropdown"))
    assert fs._MERGED_CTL_CLS_858 in out
    assert "justify-between" in out
    assert out.count("<h2") == 1
    assert "<select" in out


def test_the_title_comes_first_in_the_row():
    """Left-aligned title, right-aligned control — reversing them is the same defect mirrored."""
    out = fs._heading_row_858("Movies", _ctl("genres dropdown"))
    assert out.index("<h2") < out.index("<select")


def test_the_standalone_row_padding_is_dropped_when_nested():
    """`px-6 pt-4` positioned the bar as a top-level row. Left in place it would double the
    section's own padding and push the control off the title's baseline."""
    out = fs._heading_row_858("Movies", _ctl("genres dropdown"))
    assert "px-6 pt-4" not in out


def test_several_controls_all_survive_the_fold():
    """browse_by_languages carries two adjacent dropdowns (#551); the fold must not eat one."""
    out = fs._heading_row_858("Browse", _ctl("genres dropdown", "original language dropdown"))
    assert out.count("<select") == 2


def test_the_caller_skips_the_standalone_row_when_merged():
    """★ The double-render guard, and why it reads the MARKUP rather than a flag: a heading branch
    that does not merge must still get its own control row."""
    src = inspect.getsource(fs._render_reference_page)
    assert '("" if _MERGED_CTL_CLS_858 in main_jsx else control_jsx)' in src


def test_every_heading_branch_uses_the_helper():
    """All three sites emitted the identical `<h2>` string; if a fourth appears it must not
    silently reintroduce the stacked layout."""
    src = inspect.getsource(fs._render_reference_page)
    assert src.count("_heading_row_858(label, control_jsx)") == 3
    assert 'mb-4 text-xl font-semibold\\">{label}' not in src, "a raw heading branch survived"


def test_the_module_still_compiles():
    """★ The seam this fix actually broke: the replaced line was followed by an IMPLICITLY
    concatenated string literal, so swapping a literal for a call produced
    `SyntaxError: invalid syntax. Perhaps you forgot a comma?` at all three sites. Errors cluster
    at the boundary the edit introduces, not in its logic — and `compile()` is the check that
    catches it (#814)."""
    import pathlib
    src = pathlib.Path(fs.__file__).read_text(encoding="utf-8")
    compile(src, fs.__file__, "exec")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
