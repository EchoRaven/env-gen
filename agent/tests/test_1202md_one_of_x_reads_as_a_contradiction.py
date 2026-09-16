"""#1202md — with ONE subject FK, "one of X is required" contradicts the contract that says X?.

#1202bl refuses a create that names no subject FK, because such a row "is nothing but its own
id and owner". With two or more FKs the message reads as what it is — a choice. With exactly
one it degenerates into "sound_id is required", while the SAME endpoint's registered request
schema declares `sound_id: "int?"`.

Both statements are true about different things: each field is optional INDIVIDUALLY, and what
is required is that at least one subject FK be named. Nothing said so, so a lane reading its
own contract sees a framework demanding a field the framework published as optional.

★ Measured over the corpus, after a first measurement that framed it wrongly. 24 runs carry
the guard. My first pass counted "field in a required list AND marked optional" and reported
11 runs — but a MULTI-element list is not a contradiction at all. Re-measured on the
degenerate case only:

    15 multi-FK guards   (already read as a choice — untouched)
     8 single-FK endpoints across 7 runs:
         POST /api/videos.sound_id     r101 r102 r103 r107 r109 r121
         POST /api/comments.video_id   r120
         POST /api/feed.sound_id       r121

Message only: the guard's behaviour is unchanged, so #1202bl's measured "zero corpus steps
break" still holds.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp

_SRC = inspect.getsource(rp)


def _emitted_detail(n_fks: int) -> str:
    """The `detail=` string this projector would emit for a guard over `n_fks` subject FKs."""
    i = _SRC.index("_why_1202md = (")
    j = _SRC.index("body_lines += [", i)
    ns = {"_subj_1202bl": ["f%d" % k for k in range(n_fks)]}
    exec(_SRC[i:j].strip(), ns)
    return ns["_why_1202md"]


def test_a_single_fk_explains_the_apparent_contradiction():
    d = _emitted_detail(1)
    assert "only subject FK" in d
    assert "optional INDIVIDUALLY" in d, (
        "the lane must be told why its contract and this 400 can both be right")
    assert "at least one subject FK be named" in d


def test_several_fks_keep_the_plain_disjunction_wording():
    d = _emitted_detail(3)
    assert "at least one subject FK must be named" in d
    assert "optional INDIVIDUALLY" not in d, (
        "with a real choice there is no contradiction to explain away")


def test_both_wordings_name_the_reason_and_the_ticket():
    for n in (1, 3):
        d = _emitted_detail(n)
        assert "nothing but its own id and owner" in d
        # #1202oi: the REASON stays, the internal ticket does not — this string is an HTTP 400
        # body an API consumer receives, and internal markers must not ship in generated
        # output (standing rule). The marker stays in the emitter's own comment.
        assert "#1202bl" not in d


def test_the_guard_itself_is_unchanged():
    """★ #1202bl measured 'zero corpus steps break' — that rests on the CONDITION, which
    this change must not touch."""
    i = _SRC.index("_why_1202md = (")
    tail = _SRC[i:_SRC.index("else:", _SRC.index("body_lines += [", i))]
    assert "if not any(valid.get(_k) is not None for _k in %r):" in tail
    assert "status_code=400" in tail


def test_the_detail_still_opens_with_the_field_list():
    """Anything reading the head of the message keeps working; the reason is appended."""
    # #923: the AugAssign node, not "everything up to the next `]`" — a bare-delimiter slice
    # moves the moment anything nested appears inside the span, and that ratchet caught this
    # very assertion.
    import ast
    stmts = [ast.unparse(n) for n in ast.walk(ast.parse(_SRC))
             if isinstance(n, ast.AugAssign)
             and isinstance(n.target, ast.Name) and n.target.id == "body_lines"
             and "_why_1202md" in (ast.unparse(n) or "")]
    assert stmts, "the guard's emission moved"
    stmt = stmts[0]
    assert "one of %s is " in stmt
    assert "required: %s" in stmt


def test_the_measurement_that_was_corrected_is_recorded():
    """A first framing that counted the wrong property must not be quietly replaced."""
    i = _SRC.index("#1202md: SAY WHY")
    block = _SRC[i:_SRC.index("_why_1202md = (", i)]
    assert "15 multi-FK" in block and "8 single-FK" in block
    assert re.search(r"r10[1237]", block)
