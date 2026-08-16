r"""#820: a string literal followed by `+` is a concatenation PREFIX, not an empty nav target.

`navigate('/watch/' + tid)` is correctly parameterised code. The extractor captured `/watch/`,
stopped at the closing quote, and reported *"a parameterised route with an EMPTY parameter"* — a
defect that does not exist and that the lane cannot fix, because every correct spelling produces
the same capture. The #566z class: an unsatisfiable expectation, where the remedy the gate demands
cannot be written.

`dead_nav_link_blockers` feeds `deliverability`, so this is on the release-BLOCKING path.

Verified by executing the extractor with and without the guard:

    navigate('/watch/' + tid)   unfixed 1 blocker  ->  fixed 0     the false positive is gone
    navigate('/watch/')         unfixed 1 blocker  ->  fixed 1     the real defect still caught

★ Provenance note, stated because it matters: this change was found already in the working tree
and its accompanying comment attributes r151's STUCK abort to it. **The source claim checks out** —
`HoverPreviewCard.jsx:29,72` and `ContinueWatchingRail.jsx:44` really do read
`navigate('/title/' + tid)` / `navigate('/watch/' + tid)`. **The abort claim could not be
confirmed**: r151's `logs/` holds only `progress_events.jsonl`, which does not carry that message.
So the false positive is proven and the causal story behind it is not; the fix stands on the
former.
"""
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _blockers(body, *, guard=True, monkeypatch=None):
    with tempfile.TemporaryDirectory() as d:
        s = pathlib.Path(d) / "src"
        s.mkdir()
        (s / "App.jsx").write_text("<Route path='/watch/:id' element={<W/>} />", encoding="utf-8")
        (s / "C.jsx").write_text(body, encoding="utf-8")
        if guard:
            return fa.dead_nav_link_blockers(s)
        orig = fa._is_concat_prefix_820
        fa._is_concat_prefix_820 = lambda t, e: False
        try:
            return fa.dead_nav_link_blockers(s)
        finally:
            fa._is_concat_prefix_820 = orig


_CONCAT = "export default function C(){ return <a onClick={() => navigate('/watch/' + tid)}/> }"
_EMPTY = "export default function C(){ return <a onClick={() => navigate('/watch/')}/> }"


def test_the_false_positive_really_existed():
    """Non-vacuity: without the guard, correct code is flagged."""
    assert len(_blockers(_CONCAT, guard=False)) == 1


def test_concatenated_code_is_not_flagged():
    assert _blockers(_CONCAT) == []


def test_a_genuinely_empty_target_is_still_flagged():
    """★ The half that matters more: the guard must not suppress the real defect."""
    assert len(_blockers(_EMPTY)) == 1
    assert len(_blockers(_EMPTY, guard=False)) == 1


@pytest.mark.parametrize("expr", [
    "navigate('/watch/'+tid)", "navigate('/watch/' +tid)", "navigate('/watch/'  +  tid)",
])
def test_whitespace_around_the_plus_does_not_matter(expr):
    assert _blockers("export default function C(){ return <a onClick={() => %s}/> }" % expr) == []


def test_the_helper_is_pure_and_cheap():
    assert fa._is_concat_prefix_820("'/x/' + y", 5) is True
    assert fa._is_concat_prefix_820("'/x/')", 5) is False
    assert fa._is_concat_prefix_820("", 99) is False


@pytest.mark.parametrize("body,expect", [
    ("<a onClick={() => navigate(`/watch/${tid}`)}/>", 0),
    ("<a onClick={() => navigate('/watch/' + tid)}/>", 0),
    ("<Link to={'/watch/' + tid}/>", 0),
    ("<Link to={`/watch/${tid}`}/>", 0),
    ("<a onClick={() => navigate(dest)}/>", 0),
    ("<a onClick={() => navigate('/watch/')}/>", 1),
    ("<Link to='/nope'/>", 1),
])
def test_the_whole_input_space_is_sound(body, expect):
    """★ #820 fixed one spelling; soundness means EVERY correct spelling clears and EVERY real
    defect stays. The sibling extractors had already learned this — `_API_URL_BOUNDARY_631` treats
    `+` and `${` as boundaries and `_PAGE_FETCH_RE_615` rejects a following `{?$+`. The nav
    extractor was the one that had not: three implementations of one idea, two correct.

    Sweeping the space rather than patching the report is the point — the report named the
    concatenation, and said nothing about whether template literals were handled."""
    got = _blockers("export default function C(){ return %s }" % body)
    assert len(got) == expect, got


def test_the_source_claim_in_the_comment_holds():
    """The comment cites two r151 files by name; if they are present they must say what it says."""
    gen = pathlib.Path(__file__).resolve().parents[1] / "generated" / "netflix-web-r151"
    hp = gen / "app/frontend/src/components/HoverPreviewCard.jsx"
    if not hp.is_file():
        pytest.skip("r151 not present")
    assert "navigate('/title/' + tid)" in hp.read_text(encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
