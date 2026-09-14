"""#1202mi: the framework's engineering history must not ship inside the app.

The projectors emit their own comments and docstrings into the generated
application. Those carry framework ticket tags and, in the longer ones, whole
forensic narratives naming past runs. Measured across the 161 generated
environments on disk: 140 of them carry at least one ticket tag in
``app/backend/main.py`` and 73 name another run. tiktok-r122's is the worst --
2088 lines, 46 distinct tags, and seven other runs named (netflix-local-r13,
netflix-r22, netflix-r42, tiktok-r58, tiktok-r92, tiktok-r107, tiktok-r114).

Two reasons this matters rather than being untidy:

  * The standing rule (2026-06-18, commit 880a449) is that internal changelog
    tags must not appear in the strings the scaffolders emit into the generated
    application, "above all ... the main.py wiring/entrypoint" -- because to
    anyone reading the generated app a `#1202db` implies a change they can find
    a record of, and there is none. That cleanup has regressed.
  * These environments are released. Shipping another environment's name and
    this framework's ticket numbers inside a published artifact is provenance
    nobody outside can resolve.

WHY POSITION AND NOT PATTERN. `#471`, `#528`, `#390` and `#568` are real ticket
tags in the emitted Python. They are also valid three-digit CSS colours, and
r122's frontend contains 36 of those (`#000`, `#111`, `#222`, `#333`, ...). The
token shape cannot tell them apart, so a text substitution over the file would
silently rewrite the app's palette. Everything here is therefore driven by
tokenize/AST position: COMMENT tokens and docstrings, nothing else.

WHAT IS DELIBERATELY LEFT. Tags inside RUNTIME strings -- `logger.warning(
"#1166 restored %d lane route(s) ...")` -- are not touched. They are load
bearing: `test_1166_dropped_routes_must_be_dropped_for_something` asserts that
exact substring is present in the emitted source, and other detectors may read
these back out of a run's logs. Rewriting them would trade a tidiness fix for a
behavioural regression.

MEASURED, running this over the 1513 projected backend files on disk: 11,500
tags and 3,441 run references removed, and the code of every one of them parses
to an identical AST once docstrings are set aside. The first draft of the
pattern above found only 1,858 -- it required three or four digits and so missed
the largest family entirely (`FIX #93` alone occurs 681 times). The numbers here
are from the corrected pattern.
"""
from __future__ import annotations

import ast
import io
import json
import logging
import re
import time
import tokenize
from pathlib import Path
from typing import List, Tuple

_LOG = logging.getLogger(__name__)

#: Two shapes, on purpose, because their collision risks differ.
#:
#: PREFIXED -- `FIX #93`, `Fix #63`, `PROPOSAL #26`, `Round-8x`. Any number:
#: the prefix is what identifies it, and these are the bulk of the leak (`FIX
#: #93` alone appears 681 times across the generated backends on disk). The
#: prefix is consumed with the tag so no dangling "FIX" is left behind.
#:
#: BARE -- `#1202db`, `#943`, `#528`. Three or four digits only. Widening this
#: to one or two would start eating quoted error text: one projected comment
#: quotes `dictionary update sequence element #0 has length N`, and `#0` there
#: is part of the message, not provenance. A bare low number without a prefix
#: is left alone for that reason.
_TAG_PREFIXED_1202MI = re.compile(
    r"\b(?:FIX|PROPOSAL|Round)[- ]?#?\d{1,4}[a-z]{0,2}\b", re.I)
_TAG_BARE_1202MI = re.compile(r"(?<!\w)#\d{3,4}[a-z]{0,2}\b")

#: A run identifier, in the two shapes the corpus actually uses: `netflix-r42`
#: and `outlook run-47` / `instagram MM run #16`. Both are anchored on an
#: environment name -- a generated netflix app may legitimately say "netflix",
#: but never "netflix-r42" -- so the bare word is never touched.
_RUN_1202MI = re.compile(
    r"\b(?:netflix|tiktok|spotify|youtube|googlemaps|gmail|slack|uber|whatsapp|"
    r"facebook|outlook|instagram|atlassian|calendar|gmrun|bsb\w*)"
    r"(?:[a-z-]*-?r\d+[a-z0-9-]*|[a-z ]{0,6}run[- ]#?\d+)\b", re.I)

#: A tag that is the entire content of a bracketed aside: "(#1202db)",
#: "(see FIX #93)". Matched before the bare forms so the brackets go with it and
#: `_tidy_1202mi` never has to decide whether an empty `()` was ours -- it is
#: not, in `finish()` and `check_inbox()`, which the first version ate.
_PAREN_TAG_1202MI = re.compile(
    r"[ \t]*\((?:see[ \t]+)?(?:\b(?:FIX|PROPOSAL|Round)[- ]?#?\d{1,4}[a-z]{0,2}"
    r"|#\d{3,4}[a-z]{0,2})\)", re.I)

_RUN_REPLACEMENT_1202MI = "an earlier run"


def _offsets(src: str) -> List[int]:
    out = [0]
    for line in src.splitlines(keepends=True):
        out.append(out[-1] + len(line))
    return out


def _comment_and_docstring_spans_1202mi(src: str) -> List[Tuple[int, int]]:
    """Character spans of every comment and every docstring in ``src``.

    Docstrings are located through the AST rather than by looking for triple
    quotes, so a runtime string that merely looks like one is never included.
    """
    off = _offsets(src)

    def pos(row: int, col: int) -> int:
        return off[row - 1] + col

    spans: List[Tuple[int, int]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((pos(*tok.start), pos(*tok.end)))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return []
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return spans
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            c = first.value
            if c.end_lineno is None:
                continue
            spans.append((pos(c.lineno, c.col_offset),
                          pos(c.end_lineno, c.end_col_offset)))
    return spans


def _tidy_1202mi(text: str) -> str:
    """Repair the spacing a removal leaves behind, without touching anything a
    removal did not create.

    The first version swept away every empty pair of parentheses, to clean up
    what `(#1202db)` became once its tag was removed. That
    also ate the parentheses off every `finish()` and `check_inbox()` in the
    prose around it -- a scrub is allowed to remove provenance, not to rewrite
    English. The empty pair is now consumed by the tag patterns themselves, so
    nothing here has to guess whether a `()` was ours.

    Indentation is untouched: a docstring's leading whitespace is layout, and
    only runs BETWEEN non-space characters are collapsed.
    """
    text = re.sub(r"(?<=\S)[ \t]+([.,;:])", r"\1", text)
    text = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", text)
    text = re.sub(r"(?<=\()[ \t]+", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    # A comment that led with its tag ("# FIX #93: call reset()") is left
    # starting "#:", which is a Sphinx attribute-doc marker and means something
    # else. Drop the orphaned punctuation the removal exposed.
    text = re.sub(r"(?m)^([ \t]*#)[ \t]*[:,;][ \t]*", r"\1 ", text)
    return text


def scrub_provenance_1202mi(text: str, filename: str = "") -> str:
    """Return ``text`` with framework provenance removed from its comments and
    docstrings. Python only; anything else is returned unchanged.

    Never raises and never rewrites code: on a parse failure the original text
    is returned, because shipping a tag is better than shipping a broken file.
    """
    if not text or (filename and not str(filename).endswith(".py")):
        return text
    if not (_TAG_PREFIXED_1202MI.search(text) or _TAG_BARE_1202MI.search(text)
            or _RUN_1202MI.search(text)):
        return text
    spans = _comment_and_docstring_spans_1202mi(text)
    if not spans:
        # The text carries provenance but could not be parsed, so there is no
        # safe way to tell a tag from a colour. Say so rather than guessing
        # (#1202be: a guard must not answer in the affirmative when it is
        # blind) and leave the file exactly as the projector wrote it.
        #
        # #947: and record it. "This file shipped with its framework tags
        # intact" is exactly the fact a later reader of a released environment
        # needs, and a log line is gone by then. Written inline rather than
        # through a helper because this is the only branch that produces it.
        if filename:
            _LOG.warning(
                "#1202mi could not parse %s, so its comments keep their "
                "framework tags and run names", filename)
            try:
                src = Path(filename)
                root = next((a.parent for a in src.parents if a.name == "app"),
                            src.parent)
                out = root / "logs" / "provenance_scrub_1202mi.jsonl"
                out.parent.mkdir(parents=True, exist_ok=True)
                prev = out.read_text(encoding="utf-8") if out.is_file() else ""
                out.write_text(
                    prev + json.dumps({"at": time.time(), "file": str(filename),
                                       "outcome": "unparsed_provenance_kept"})
                    + "\n", encoding="utf-8")
            except (OSError, TypeError, ValueError) as exc:
                _LOG.warning("could not record the unscrubbed file %s: %s",
                             filename, exc)
        return text
    out = text
    for start, end in sorted(spans, reverse=True):
        chunk = out[start:end]
        new = _RUN_1202MI.sub(_RUN_REPLACEMENT_1202MI, chunk)
        # Parenthesised first, so "(#1202db)" goes whole rather than leaving an
        # empty pair for a later sweep to guess about.
        new = _PAREN_TAG_1202MI.sub("", new)
        new = _TAG_PREFIXED_1202MI.sub("", new)
        new = _TAG_BARE_1202MI.sub("", new)
        if new != chunk:
            out = out[:start] + _tidy_1202mi(new) + out[end:]
    return out
