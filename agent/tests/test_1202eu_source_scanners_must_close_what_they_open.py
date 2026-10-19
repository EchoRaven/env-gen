r"""#1202eu: the two whole-tree ratchet scanners leaked one file handle per file scanned.

Both used `open(path, encoding="utf-8").read()`, which never closes. Each walks the entire
source tree, so each leaked 1593 handles per run — 3186 between them, every suite run.

The FD limit on this box is 1048576, so nothing failed. That is the whole problem with
this shape: it works until it is run somewhere with a normal limit (1024 is a common
default), and then a ratchet that guards other people's discipline is the thing that
falls over.

Found by running the suite with -W always, which surfaces the ResourceWarnings pytest
suppresses by default. The same pass looked for invalid escape sequences — the potentially
real bugs, where `"\b"` in a pattern is a backspace rather than a word boundary — and found
three, all of them `\``, `\s` and `\w`, which Python leaves untouched. No regex was
misbehaving.
"""
import io
import pathlib
import re
import tokenize

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
SCANNERS = ["test_no_new_fixed_width_source_windows.py",
            "test_no_get_event_loop_in_tests.py"]


@pytest.mark.parametrize("name", SCANNERS)
def test_the_scanner_closes_what_it_opens(name):
    src = (TESTS / name).read_text(encoding="utf-8")
    assert "open(path" not in src, f"{name} still leaks a handle per file scanned"
    assert "read_text(" in src


# #1203ph: ONE owner for the predicate, and prose cannot trip it.
#
# Two defects, both found when this ratchet failed on a file whose only mention of the pattern
# was in its MODULE DOCSTRING -- a test that describes the leak it is documenting.
#
#   * the stripping was comments-only. This file's own comment below already records learning
#     that lesson for `#` comments ("my first version matched the comment I had just written
#     beside the fix ... Fifth time this session a comment tripped a source assertion"). A
#     docstring is the same class one level up, and so is any string literal that quotes code.
#   * the two regexes were written TWICE -- once in the scanner, once in the counter-proof
#     below -- so a narrowing applied to one could silently miss the other (#1032).
#
# Blanking keeps LAYOUT: each comment/string span becomes spaces in place, so
# `open(path, encoding="utf-8").read()` stays one contiguous call (the blanked `"utf-8"` is
# still `[^)]*`) while a docstring that merely quotes the pattern goes away.

_PAT_OPEN_READ = r"open\([^)]*\)\.read\(\)"
# `ast.walk` is NOT a tree scan (#1203d0) -- see the counter-proof.
_PAT_TREE_WALK = r"for \w+ in .*(rglob|glob|(?<!ast\.)walk)"


def code_only_1203ph(src: str) -> str:
    """`src` with comment and string-literal CONTENTS blanked, layout preserved."""
    lines = src.split("\n")
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        # A file this cannot tokenise is not evidence of anything (#1039): fall back to the
        # comment-only strip rather than reporting a clean scan.
        return "\n".join(l.split("#")[0] for l in lines)
    chars = [list(l) for l in lines]
    for t in toks:
        if t.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (sr, sc), (er, ec) = t.start, t.end
        for r in range(sr - 1, min(er, len(chars))):
            lo = sc if r == sr - 1 else 0
            hi = ec if r == er - 1 else len(chars[r])
            for c in range(lo, min(hi, len(chars[r]))):
                chars[r][c] = " "
    return "\n".join("".join(c) for c in chars)


def is_tree_scanner_1203ph(code: str) -> bool:
    """Both halves of the shape: a handle-per-file open INSIDE a whole-tree walk."""
    return bool(re.search(_PAT_OPEN_READ, code)) and bool(re.search(_PAT_TREE_WALK, code))


def test_no_test_reads_a_whole_tree_with_bare_open():
    """The class, so a third scanner cannot arrive with the same leak."""
    offenders = []
    for p in sorted(TESTS.glob("test_*.py")):
        if p.name == pathlib.Path(__file__).name:
            continue          # this file quotes the pattern it hunts for
        # CODE only: my first version matched the comment I had just written beside the
        # fix, and reported two files I had already corrected (#943's lesson, again).
        # strip trailing comments too — mine sits at the end of the fixed line, so a
        # whole-line filter walked straight past it and re-reported both files I had
        # already corrected. Fifth time this session a comment tripped a source assertion.
        # #1203ph: docstrings and string literals go too, for the same reason.
        if is_tree_scanner_1203ph(code_only_1203ph(p.read_text(encoding="utf-8"))):
            offenders.append(p.name)
    assert not offenders, f"tree scanners leaking a handle per file: {offenders}"


def test_the_predicate_still_catches_a_real_leak():
    """#1203d0's counter-proof, inline so the narrowing cannot quietly become a hole.

    A narrowed guard that no longer fires is worse than the false positive it removed, so the
    shapes are asserted here directly rather than trusted — now through the SAME predicate the
    scanner uses, because writing it twice is how a narrowing reaches one copy only."""
    LEAK = ('for path in root.rglob("*.py"):\n'
            '    src = open(path, encoding="utf-8").read()\n')
    OSWALK = ('for f in os.walk(root):\n'
              '    src = open(f, encoding="utf-8").read()\n')
    AST_ONLY = ('for n in ast.walk(tree):\n'
                '    pass\n'
                'body = open(one_known_path, encoding="utf-8").read()\n')

    assert is_tree_scanner_1203ph(LEAK), "a real rglob tree scanner must still be caught"
    assert is_tree_scanner_1203ph(OSWALK), "os.walk is a real tree scan and must still be caught"
    assert not is_tree_scanner_1203ph(AST_ONLY), "an ast.walk traversal is not a tree scan"


def test_the_blanking_does_not_blunt_the_predicate():
    """#1203ph's own counter-proof: stripping strings must not hide real code.

    The risk is specific — `open(path, encoding="utf-8")` carries a string literal INSIDE the
    call, so blanking has to preserve layout or the call stops looking like one call."""
    LEAK = ('for path in root.rglob("*.py"):\n'
            '    src = open(path, encoding="utf-8").read()\n')
    assert is_tree_scanner_1203ph(code_only_1203ph(LEAK)), (
        "blanking the encoding= literal broke the open(...).read() match")


def test_prose_that_quotes_the_pattern_is_not_an_offender():
    """The failure that produced #1203ph: a test whose MODULE DOCSTRING describes the leak."""
    DOC_ONLY = ('"""A test that documents the leak.\n'
                '\n'
                'It used open("fixture.json").read() in a glob loop.\n'
                '"""\n'
                'for p in sorted(root.glob("*.py")):\n'
                '    with open(p, encoding="utf-8") as fh:\n'
                '        src = fh.read()\n')
    assert is_tree_scanner_1203ph(DOC_ONLY), (
        "precondition: the raw text does look like an offender")
    assert not is_tree_scanner_1203ph(code_only_1203ph(DOC_ONLY)), (
        "a docstring quoting the pattern still reads as a leak")


def test_a_comment_quoting_the_pattern_is_not_an_offender():
    """The older half of the same lesson, kept driven rather than described."""
    CMT_ONLY = ('for p in sorted(root.glob("*.py")):\n'
                '    # was: src = open(p, encoding="utf-8").read()\n'
                '    with open(p, encoding="utf-8") as fh:\n'
                '        src = fh.read()\n')
    assert not is_tree_scanner_1203ph(code_only_1203ph(CMT_ONLY))


def test_an_untokenisable_file_does_not_read_as_clean():
    """#1039: "could not tell" must not be reported as a clean scan, so the fallback keeps the
    comment-only strip instead of returning nothing."""
    BROKEN = ('for path in root.rglob("*.py"):\n'
              '    src = open(path, encoding="utf-8").read()\n'
              'def (  # deliberately unparseable\n')
    assert is_tree_scanner_1203ph(code_only_1203ph(BROKEN)), (
        "a file that cannot be tokenised came back looking clean")
