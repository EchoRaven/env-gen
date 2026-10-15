"""#1203kr: two documented numbers, both read off the confounded instrument.

#1203kq showed `_meta.version` counts TOUCHES, because `ensure_*_document` bumps it. Two
places had already written conclusions on top of it, and both numbers are wrong:

    #695 (tool_bundles)   "`codehub_pull_requests` sits at _meta.version 1 … in 146 of 146"
    #1202jh (registryhub) "nine stores sit at the initialisation baseline (`_meta.version` 11)"

Measured over 227 kept run directories for `codehub_pull_requests`: the old corpus's mode is
3 (129 runs), then 5 (20), 4 (16); only 5 old runs sit at 1 and only TWO at 11, while 36 of
the 39 modern runs sit at 1. There is no stable baseline.

What holds is the record count: ZERO in 227 of 227, both eras. Both conclusions survive on
that instrument, which is why this corrects the evidence and not the finding.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_BUNDLES = LLM / "multi_agent" / "tool_bundles.py"
_REGISTRY = LLM / "multi_agent" / "runtime" / "registryhub.py"


def _src(p):
    return p.read_text(encoding="utf-8")


def _comment_block_1203kr(path, landmark):
    """The contiguous run of `#` comment lines that contains `landmark`.

    A landmark anchor, which is what #943 asks for: it grows and shrinks with the comment
    instead of assuming a byte distance from it.
    """
    lines = _src(path).split("\n")
    hit = next(i for i, l in enumerate(lines) if landmark in l)
    lo = hit
    while lo > 0 and lines[lo - 1].strip().startswith("#"):
        lo -= 1
    hi = hit
    while hi + 1 < len(lines) and lines[hi + 1].strip().startswith("#"):
        hi += 1
    # Normalised the way `test_dead_pr_tools_are_not_surfaced_695` does it: a sentence in a
    # comment wraps across lines, so `#` and indentation sit in the middle of the phrase.
    return " ".join("\n".join(lines[lo:hi + 1]).replace("#", " ").split())


def test_the_pr_tool_claim_no_longer_rests_on_the_version_1203kr():
    """Anchored on the COMMENT BLOCK, not a byte window: #943's ratchet caught the first
    version of this test twice over (`s[i - 900:i]` and `s[i:i + 1200]`), and a window sized
    in bytes breaks when a comment grows — which is the very thing these comments keep doing.
    """
    block = _comment_block_1203kr(_BUNDLES, "codehub_suggest_reviewers` is PR-")
    assert "ZERO records in 227 of 227 kept runs" in block, block[-400:]
    assert "_meta.version 1 in 146 of 146" not in block, (
        "the old evidence line must be gone, not merely annotated")
    # Without the `#`: normalising a comment block turns `#` into a space, which is also why
    # `test_dead_pr_tools_are_not_surfaced_695` asserts "257 economics" and not "#257".
    assert "1203kr" in block and "1203kq" in block, "point at why the version cannot carry it"


def test_the_registry_claim_drops_the_word_baseline_1203kr():
    """The RegistryHub docstring, read as a whole object rather than as a byte window."""
    from multi_agent.runtime.registryhub import RegistryHub
    doc = RegistryHub.__doc__ or ""
    assert "no stable baseline" in doc, doc[:400]
    assert "ZERO RECORDS is what holds in 227 of 227" in doc, doc[:600]
    assert "sit at the initialisation baseline" not in doc, (
        "`initialisation baseline` was the claim being corrected")


def test_neither_conclusion_was_softened_1203kr():
    """The instrument changed; the findings did not."""
    b = _src(_BUNDLES)
    r = _src(_REGISTRY)
    assert "In commit-only mode a PR cannot be opened" in b
    for name in ("review_threads", "repos", "pull_requests", "code_reviews"):
        assert name in r, name
    assert "ZERO records, ever" in r


def test_the_mechanism_is_named_in_one_place_and_cited_in_the_others_1203kr():
    """#1032: `ensure_*_document` bumping the version is explained once, in #1203kq's home,
    and the two corrected sites cite it rather than re-arguing it."""
    from multi_agent.runtime.hubs.codehub.service import CodeHub
    assert "`ensure_codehub_document` bumps the version" in (CodeHub.__doc__ or "")
    assert _src(_BUNDLES).count("#1203kq") >= 1
    assert _src(_REGISTRY).count("#1203kq") >= 1
