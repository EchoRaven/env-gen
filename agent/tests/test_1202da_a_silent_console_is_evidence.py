"""#1202da — a blank screen with an empty console is not a mount failure.

#740 names the cause when the browser gave one, and its own comment says why: without it
"the lane is told a symptom ('never hydrated') and has to rediscover the cause". When the
browser gave NOTHING the deviation stopped at that symptom — which points the lane at
mounting and data-loading, the one explanation the silence rules out.

Measured across the corpus: 404 screen records carry the console field and only 4 are
non-empty (r11, r25, r26 — nothing since). That near-zero rate is real, not a broken
detector: the listener was run against a page that throws, and console.error, a failed
script load and an uncaught TypeError were all captured. So the blank screens in r40
(player x2) and r41 (shows x2) had a bundle that loaded and ran.
"""
from pathlib import Path

import pytest

SRC = Path("env_generator/llm_generator/multi_agent/runtime/visual_fidelity.py").read_text()


def _blank_branch() -> str:
    i = SRC.index("_err740 = _console740.get(screen[\"name\"]) or []")
    return SRC[i:SRC.index("elif screen[\"name\"] in _auth_bounced", i)]


def test_a_named_browser_error_still_wins():
    """#740's path is the better one when it fires — the new text must not displace it."""
    body = _blank_branch()
    assert "The browser reported: " in body
    assert body.index("The browser reported: ") < body.index("No console error")


def test_the_silence_is_reported_as_evidence():
    """The claim has to be stated, not implied: an empty console MEANS the bundle ran."""
    body = _blank_branch()
    assert "the bundle LOADED and RAN" in body


def test_it_names_where_to_look_instead():
    """A diagnosis that only rules something out leaves the lane where it started."""
    body = _blank_branch()
    assert "returns null/empty" in body
    assert "not for a mount or bundle failure" in body


def test_the_two_branches_are_exclusive():
    """One deviation, one explanation — appending both would contradict itself.

    AMENDED by #1202ix. This asserted the literal `else:`, and #1202ix legitimately turned
    it into `elif not _why1202ix:` — a blank screen whose ROUTE can never match has a third
    explanation, and it is the one that rules out this branch's advice entirely (when nothing
    routed there is no component to look for). The PROPERTY this test exists for is unchanged
    and is what it now checks: the two `_dev +=` sit in different arms of one if-chain, so no
    input can append both. Pinning the keyword instead of the property is what #1202cs was
    about — a correct generalisation must not read as a regression.
    """
    import ast
    import textwrap

    body = _blank_branch()
    assert body.count("_dev +=") == 2

    # The slice starts mid-line, so the first line carries no indent while the rest keep
    # theirs. Restore it from the following lines before dedenting, or ast sees a stray block.
    _lines = body.rstrip().split("\n")
    _ind = min((len(l) - len(l.lstrip()) for l in _lines[1:] if l.strip()), default=0)
    _lines[0] = " " * _ind + _lines[0]
    tree = ast.parse(textwrap.indent(textwrap.dedent("\n".join(_lines)), "    ")
                     .join(("if True:\n", "")))
    chains = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
    assert chains, body

    def _adds(node):
        return sum(1 for c in ast.walk(node)
                   if isinstance(c, ast.AugAssign)
                   and getattr(c.target, "id", None) == "_dev")

    def _arm(stmts):
        return _adds(ast.Module(body=list(stmts), type_ignores=[]))

    # exactly one if-chain must split the two appends across its two arms; no input can
    # then take both. Selecting by that property (rather than by keyword) is the point.
    split = [n for n in chains if _arm(n.body) == 1 and _arm(n.orelse) == 1]
    assert len(split) == 1, [
        (getattr(n, "lineno", None), _arm(n.body), _arm(n.orelse)) for n in chains]
