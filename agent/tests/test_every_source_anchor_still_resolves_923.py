r"""#923: the one anchor check that is soundly decidable — and the one that is not.

The suite locates code by anchoring on strings in module source. When an anchor stops resolving,
the test using it fails on whatever its assertion happened to be about and the reader chases a
behaviour change that never happened — #921 cost a full-suite run and a false *"the key is no
longer persisted"* before the extractor turned out to be at fault.

★ **What this file checks: no span locator ends on a bare `}` / `)` / `]`.** That shape moves the
moment anything nests inside the span, it broke once for real (#720, on #921's nested coverage
dict), and it needs no attribution to detect — the offending call is right there in the AST.

★ **What it deliberately does NOT check: whether every anchor still resolves.** Three attempts, three
different false-positive mechanisms, all of them instances of the class this file exists to police:

    v1  regex over the file text          → matched anchors quoted in neighbours' DOCSTRINGS, and
                                            compared undecoded literals (`"\nclass "` as two chars)
    v2  AST, attributed to the first
        imported module                   → a test reading two modules had half its anchors checked
                                            against the wrong source
    v3  AST, attributed per receiver      → `src` is reassigned per test in most files, so a
                                            file-level {var: module} map cannot represent it

Each version reported dozens of "unresolved" anchors and every one I checked was the instrument.
A guard that cries wolf is worse than no guard, and sound attribution needs flow analysis this is
not worth. Recorded so the next attempt starts from the three failures rather than repeating them.

The measured risk it would have covered is small: across the last 40 commits, four `#NNN:` heading
lines disappeared and three were reverts (the code went with them). The one genuine rewording
(#891's, kept alive by #896) had no test anchored on it.
"""
import ast
import importlib
import inspect
import pathlib

import pytest


_TESTS = pathlib.Path(__file__).parent
_LOCATORS = ("index", "rindex")


def _bare_delimiter_offenders():
    """Every `.index("}")`-style span end in the suite, read through the AST so a docstring that
    EXPLAINS such a slice is not itself reported as one — that false positive is how v1 of this
    file first ran."""
    out = []
    for f in sorted(_TESTS.glob("test_*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue
        text = f.read_text(encoding="utf-8")
        if "getsource" not in text:
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _LOCATORS and node.args):
                continue
            a = node.args[0]
            if isinstance(a, ast.Constant) and a.value in ("}", ")", "]"):
                out.append(f"{f.name}: slices to a bare {a.value!r}")
    return out


def test_there_are_locators_to_check():
    """Non-vacuity: the sweep must actually be looking at something."""
    n = 0
    for f in _TESTS.glob("test_*.py"):
        t = f.read_text(encoding="utf-8")
        if "getsource" in t and (".index(" in t or ".rindex(" in t):
            n += 1
    assert n > 100, n


def test_no_span_locator_ends_on_a_bare_delimiter():
    offenders = _bare_delimiter_offenders()
    assert not offenders, (
        "these locate a span by counting to the next bracket, so any nesting introduced inside "
        "the span moves the end; read the structure through `ast` instead:\n  "
        + "\n  ".join(sorted(offenders)))


def test_the_detector_sees_a_planted_offender(tmp_path):
    """★ Item 266's rule — prove the check catches the thing it exists for before trusting its
    zero. A zero from an unvalidated instrument is not a measurement."""
    planted = tmp_path / "test_planted_923.py"
    planted.write_text(
        "import inspect\n"
        "def test_x():\n"
        "    src = inspect.getsource(inspect)\n"
        "    assert src[0:src.index('}')]\n", encoding="utf-8")
    global _TESTS
    real, _TESTS = _TESTS, tmp_path
    try:
        assert _bare_delimiter_offenders(), "the planted bare-delimiter slice was not caught"
    finally:
        _TESTS = real


def test_it_ignores_a_docstring_that_merely_mentions_one(tmp_path):
    """The v1 false positive, pinned: prose describing a fixed slice must not be reported."""
    planted = tmp_path / "test_prose_923.py"
    planted.write_text(
        'import inspect\n'
        'def test_x():\n'
        '    """Was src[i:src.index("}", i)] before the fix."""\n'
        '    assert inspect.getsource(inspect)\n', encoding="utf-8")
    global _TESTS
    real, _TESTS = _TESTS, tmp_path
    try:
        assert _bare_delimiter_offenders() == []
    finally:
        _TESTS = real


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
