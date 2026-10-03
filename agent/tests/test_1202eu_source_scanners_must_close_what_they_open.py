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
import pathlib
import re

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
SCANNERS = ["test_no_new_fixed_width_source_windows.py",
            "test_no_get_event_loop_in_tests.py"]


@pytest.mark.parametrize("name", SCANNERS)
def test_the_scanner_closes_what_it_opens(name):
    src = (TESTS / name).read_text(encoding="utf-8")
    assert "open(path" not in src, f"{name} still leaks a handle per file scanned"
    assert "read_text(" in src


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
        src = "\n".join(l.split("#")[0] for l in p.read_text(encoding="utf-8").split("\n"))
        # #1203d0: `ast.walk` IS NOT A TREE SCAN. The harm this guards is proportional to the
        # number of FILES opened — "1593 handles per run", per the docstring above. An AST
        # traversal opens nothing, so a file holding one single-path `open().read()` beside an
        # `ast.walk` comprehension leaks at most ONE handle and is not this class at all.
        # It cost a full suite run to learn: #1203c9's tests were flagged for
        # `[n for n in ast.walk(tree) ...]`, and 262 of this directory's test files use that
        # idiom — every one of them is a single `open().read()` away from the same false
        # positive. 0 files change status today; the trap is what closes.
        if re.search(r"open\([^)]*\)\.read\(\)", src) and re.search(
                r"for \w+ in .*(rglob|glob|(?<!ast\.)walk)", src):
            offenders.append(p.name)
    assert not offenders, f"tree scanners leaking a handle per file: {offenders}"


def test_the_predicate_still_catches_a_real_leak():
    """#1203d0's counter-proof, inline so the narrowing cannot quietly become a hole.

    A narrowed guard that no longer fires is worse than the false positive it removed, so the
    two shapes are asserted here directly rather than trusted."""
    LEAK = ('for path in root.rglob("*.py"):\n'
            '    src = open(path, encoding="utf-8").read()\n')
    OSWALK = ('for f in os.walk(root):\n'
              '    src = open(f, encoding="utf-8").read()\n')
    AST_ONLY = ('for n in ast.walk(tree):\n'
                '    pass\n'
                'body = open(one_known_path, encoding="utf-8").read()\n')
    pat_open = r"open\([^)]*\)\.read\(\)"
    pat_walk = r"for \w+ in .*(rglob|glob|(?<!ast\.)walk)"

    def flags(src):
        return bool(re.search(pat_open, src)) and bool(re.search(pat_walk, src))

    assert flags(LEAK), "a real rglob tree scanner must still be caught"
    assert flags(OSWALK), "os.walk is a real tree scan and must still be caught"
    assert not flags(AST_ONLY), "an ast.walk traversal is not a tree scan"
