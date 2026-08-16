r"""#859: the framework typed its dropdown caret in two places and drew it in a third.

Last open head of the deviation census. After #855–#858 the clusters cover 60% of all 7763
deviation lines (up from 11%), and the largest remaining OPEN class was `icon shape` — 541 entries
across 115 runs. Inside it, 22 runs name the cause outright:

    "get help: implementation uses a ▼ text character; reference uses a chevron-down icon"
    "avatar dropdown uses '▼' text instead of chevron icon"
    "get help caret: implementation renders a dash instead of a chevron"

★ The framework already knew the answer. The landing page's language pill emits a proper stroked
SVG chevron; the avatar chip and every filter `<select>` emitted the literal character U+25BE. It
disagreed with itself, and a typed triangle renders in whatever font the page happens to use —
solid, tiny, and unlike any reference.

One helper now, used at both sites, `currentColor` so it inherits the caret's existing colour and
opacity (#551: a hard-coded stroke paints invisibly on a theme it did not expect), same 14px box
as the language pill so two carets on one page match.

**Deliberately not touched:** the `▲`/`▼` scroll-arrow buttons. The judge's complaint there is
*"floating ▲/▼ scroll arrow buttons appear in implementation but not in reference"* — about their
EXISTENCE, not their shape. Redrawing them would answer a question nobody asked, and deleting them
is a separate decision with its own evidence.
"""
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_GLYPHS = ("\u25be", "\u25bc", "\u25b4", "\u25b2")


def test_the_helper_draws_a_chevron():
    out = fs._chevron_859("text-xs")
    assert "<svg" in out and 'd="M6 9l6 6 6-6"' in out
    assert "text-xs" in out


def test_it_inherits_the_surrounding_colour():
    """#551: a hard-coded stroke paints invisibly on a theme it did not expect."""
    assert 'stroke="currentColor"' in fs._chevron_859("x")
    assert not re.search(r'stroke="#', fs._chevron_859("x"))


def test_it_is_hidden_from_assistive_tech():
    """A decorative caret beside a labelled control must not be announced twice."""
    assert 'aria-hidden="true"' in fs._chevron_859("x")


def test_the_select_caret_is_drawn():
    """The filter control on every catalog screen."""
    bar = fs._control_bar_432b([{"role": "genres dropdown", "id": "g"}])
    assert "<svg" in bar and 'd="M6 9l6 6 6-6"' in bar
    assert not any(g in bar for g in _GLYPHS), "a typed caret survived"


def test_the_select_caret_keeps_its_positioning():
    """It was absolutely positioned inside the select's padding-right; losing that puts the caret
    on top of the label."""
    bar = fs._control_bar_432b([{"role": "genres dropdown", "id": "g"}])
    assert "pointer-events-none" in bar and "absolute right-2" in bar and "-translate-y-1/2" in bar


def test_no_emitted_code_path_types_a_caret():
    """★ The invariant, not the two edits. Anything that reaches the browser must draw it.

    PROSE IS EXCLUDED BY PARSING, not by a line prefix. The first version skipped only lines
    starting with `#` and promptly matched `_chevron_859`'s own docstring, which quotes the
    judge's complaints verbatim — the thirteenth self-match this session, and the standing rule
    says anchor on structure, never on a token a write-up can repeat. Docstring line ranges come
    from `ast`, so a quoted ▼ in any explanation is invisible to the scan and an emitted one is
    not."""
    import ast
    src = pathlib.Path(fs.__file__).read_text(encoding="utf-8")
    doc_lines = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = node.body[0] if node.body else None
            if (isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant)
                    and isinstance(d.value.value, str)):
                doc_lines.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    offenders = []
    for n, line in enumerate(src.split("\n"), 1):
        if n in doc_lines or line.lstrip().startswith("#"):
            continue
        if any(g in line for g in _GLYPHS) or re.search(r"\\\\u25[bB][eEcC]", line):
            offenders.append(f"{n}: {line.strip()[:110]}")
    # the scroll-arrow buttons are a separate, evidenced decision — see the module docstring
    offenders = [o for o in offenders if "scroll" not in o.lower() and "u25BC" not in o]
    assert doc_lines, "non-vacuity: the docstring map must not be empty"
    assert not offenders, "a typed caret in emitted code:\n" + "\n".join(offenders)


def test_the_scan_can_actually_find_one():
    """Non-vacuity for the guard above — otherwise it passes on any regex typo."""
    as_char = "        \"<span>{'" + "\u25be" + "'}</span>\""
    as_escape = r"        \"<span>{'\\u25be'}</span>\""
    assert any(g in as_char for g in _GLYPHS), "the literal-character branch is dead"
    assert re.search(r"\\\\u25[bB][eEcC]", as_escape), "the escape-text branch is dead"


def test_the_language_pill_still_matches():
    """The site that was already right must stay right, and must stay the SAME chevron — two
    different carets on one page is the defect this fix exists to remove."""
    src = pathlib.Path(fs.__file__).read_text(encoding="utf-8")
    assert src.count("M6 9l6 6 6-6") >= 2


def test_a_screen_without_controls_is_untouched():
    """Additive: #432b returns '' for a screen with no filter, and that must not change."""
    assert fs._control_bar_432b([{"role": "hero banner", "id": "h"}]) == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
