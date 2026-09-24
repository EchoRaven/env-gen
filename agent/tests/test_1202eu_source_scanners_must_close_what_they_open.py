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
        if re.search(r"open\([^)]*\)\.read\(\)", src) and re.search(r"for \w+ in .*(rglob|glob|walk)", src):
            offenders.append(p.name)
    assert not offenders, f"tree scanners leaking a handle per file: {offenders}"
