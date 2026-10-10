r"""#1203hi: RELEASE HELD named the check and then cut the chain name off the front.

`_salient_error`'s no-marker exit returns `text[-cap:]` — the TAIL — which is right for
compose stderr, whose cause sits at the end (#182/#1119). It is wrong for a
verification-chain detail, which puts the chain name, the endpoint, the status and the
step number at the START. #1203d5 widened this writer's budget from 60 to 300 and the cuts
moved rather than stopped.

MEASURED over every `RELEASE HELD ... FAILS a fresh api_smoke` record on disk — 26
distinct ones — 8 of them, across 7 runs, begin MID-WORD:

    r152  business_chain:rror: [Errno 104                 ("rror:" = tail of "Error:")
    r165  business_chain:ndler.\n[explore_grid_...        ("ndler." = "handler.")
    r168  business_chain:d} save failed at step ...
    r171  business_chain:(source 937c44fa1dbc, built 162f852a0516) -- the container ...
    r171  business_chain:p is what is wrong. Create the resource as THIS actor ...
    r172  business_chain:handler under test; rebuild AND recreate the stack ...
    r173  business_chain:d since the image was built (source 74832b760b9d, ...)
    r176  business_chain:er. BUILD CURRENCY SAYS THE THIRD IS LIVE: app/ has changed ...

and the readable ones show what the message should look like —
`business_chain:[open_login_from_shell`, `[tenant_control_lifecycle`,
`[m2_search_discovery_flow` — which survived only because their detail was short enough
that the tail WAS the whole thing.

Reproduced directly before the fix: a 600-character detail starting
`[home_feed_authenticated] GET /api/feed → 500 (expected [200]) at step 3 of 7` came back
as `ding to push it past the cap. ...` — chain, endpoint, status and step all gone.

★ `_salient_error`'s contract is untouched. This is the one consumer whose information
lives at the FRONT, so the fix belongs at the consumer. Three patches today already turned
on where a window's information sits: #1203h8 (compose markers), #1203hb (the hits join),
and this one — and hb had to be re-scoped when it broke #987/#973 for exactly the same
reason, that "the end matters most" is true per-consumer and not in general.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _keep_chain_head_1203hi, _salient_error)

_HEAD = "[home_feed_authenticated]"
_LONG = (_HEAD + " GET /api/feed → 500 (expected [200]) at step 3 of 7; the handler "
         "raised. " + "padding to push it past the cap. " * 8 +
         "BUILD CURRENCY SAYS THE THIRD IS LIVE: app/ has changed since the image was "
         "built (source 888c7f588fab, built a3fc0ee8b595)")


def test_the_chain_name_survives_a_cut():
    """★ THE defect: 8 of 26 records on disk lost exactly this."""
    out = _keep_chain_head_1203hi(_LONG, 300)
    assert out.startswith(_HEAD), out[:60]


def test_the_causal_end_still_survives():
    """The tail is why `_salient_error` exists; keeping the head must not cost it."""
    out = _keep_chain_head_1203hi(_LONG, 300)
    assert "built a3fc0ee8b595" in out, out[-90:]


def test_the_elision_is_visible():
    """#1034: a cut that does not announce itself reads as a complete message."""
    out = _keep_chain_head_1203hi(_LONG, 300)
    assert "…" in out, out


def test_the_budget_is_respected():
    out = _keep_chain_head_1203hi(_LONG, 300)
    assert len(out) <= 300, len(out)


def test_a_detail_that_fits_is_untouched():
    """★ THE NO-OP GUARANTEE: the readable records on disk must keep reading the same."""
    short = "[open_login_from_shell] POST /auth/login → 401 (expected [200])"
    assert _keep_chain_head_1203hi(short, 300) == _salient_error(short, cap=300)
    assert "…" not in _keep_chain_head_1203hi(short, 300)


def test_a_short_detail_whose_marker_is_on_a_later_line_gains_no_ellipsis():
    """★ THE TEST THAT MAKES THE EARLY RETURN NECESSARY. Mutating
    `if len(text) <= cap` to `if False` stayed GREEN against the case above, because
    there the tail IS the whole string and the `head in tail` guard caught it. The early
    return only earns its place when `_salient_error` picks a MARKER line that does not
    contain the head — then, without it, an uncut message would be handed over with a `…`
    claiming a cut that never happened, which is #883's shape (a notice indistinguishable
    from the real thing)."""
    short_multiline = "[open_login_from_shell] step 1 of 2\nerror: boom"
    assert len(short_multiline) < 300
    out = _keep_chain_head_1203hi(short_multiline, 300)
    assert out == _salient_error(short_multiline, cap=300), out
    assert "…" not in out, out


def test_a_detail_with_no_bracketed_head_is_left_to_salient_error():
    """★ SCOPE. Only a detail that actually names a chain at the front gets this
    treatment; everything else keeps `_salient_error`'s behaviour exactly."""
    plain = "x" * 900
    assert _keep_chain_head_1203hi(plain, 300) == _salient_error(plain, cap=300)


def test_a_runaway_bracket_is_not_treated_as_a_head():
    """A detail that happens to start with `[` but never closes it (or closes it far
    away) must not swallow the budget as a "name"."""
    runaway = "[" + "y" * 400 + "] tail here"
    out = _keep_chain_head_1203hi(runaway, 300)
    assert out == _salient_error(runaway, cap=300), out[:40]


def test_a_head_already_in_the_tail_is_not_repeated():
    """When the tail happens to contain the name, prepending it would say it twice."""
    short_enough = _HEAD + " step 1 failed"
    out = _keep_chain_head_1203hi(short_enough + " " + "z" * 400, 500)
    assert out.count(_HEAD) == 1, out[:120]


def test_empty_and_none_are_empty():
    for v in ("", None):
        assert _keep_chain_head_1203hi(v, 300) == ""


def test_every_writer_of_name_colon_detail_uses_it():
    """★ ONE FACT, THREE EMITTERS — and this test found the other two before the suite did.

    The first version pinned only the RELEASE HELD writer, and its second assertion
    ("no tail-only call remains") went red on `framework_validation`'s other two:
    the #212 validation summary at cap=200 and the wedge message at the default 400.
    Re-measured corpus-wide, not just in RELEASE HELD records:
    `business_chain:<lowercase fragment>` appears 110 times across 29 logs after
    2026-10-01 — `oes` (tail of "does"), `rst;` ("first;"), `ep:` ("step:"),
    `eck.` ("check."), `rror:` ("Error:") — so the blast radius was 110/29, not 8/26.

    A chain detail always begins with `[chain_name]` when it is not cut (the readable
    records on disk show it), so ANY lowercase start is a head-cut."""
    import ast as _ast
    import inspect

    import multi_agent.runtime.framework_validation as FV
    src = inspect.getsource(FV)
    # all three writers route through the helper
    assert src.count("_keep_chain_head_1203hi(c.get") == 3, src.count(
        "_keep_chain_head_1203hi(c.get")
    # and none of them is back to the tail-only call
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                and node.func.id == "_salient_error" and node.args):
            seg = _ast.get_source_segment(src, node.args[0]) or ""
            assert "get('detail')" not in seg and 'get("detail")' not in seg, seg


def test_the_multi_chain_shape_r176_actually_produced():
    """★ THE REAL INPUT, from r176 17:32:50. The detail is a NEWLINE-SEPARATED list of
    failing chains, so the tail keeps the later ones and cuts into the first — which is
    how the operator got `business_chain:er.\n[post_detail_comment_flow] GET ...`: a
    three-character tail of the first chain's prose, then the second chain intact.

    That the raw detail starts with `[` is not assumed: the readable corpus records
    (`business_chain:[open_login_from_shell`) are uncut, and for an uncut detail the tail
    IS the whole string, so its first character is the raw detail's first character.
    """
    real = ("[browse_feed_and_post_detail] GET /api/feed → 200; GET /api/post-detail/23 "
            "→ 200; then the comments call under test; the step raised in the handler. "
            + "more prose from the first chain. " * 6 +
            "\n[post_detail_comment_flow] GET /api/post-detail/23/comments → 422 "
            '(expected [200]; {"detail":[{"type":"string_type","loc":["query","limit"],'
            '"msg":"Input should be a valid string","input":100}')
    out = _keep_chain_head_1203hi(real, 300)
    assert out.startswith("[browse_feed_and_post_detail]"), out[:60]
    assert "post_detail_comment_flow" in out, out[-120:]
    assert "…" in out, out
    assert len(out) <= 300, len(out)


def test_without_the_fix_that_shape_loses_the_first_chain():
    """★ The counter-proof on the same input: the tail-only call keeps the second chain
    and throws the first one's name away, which is exactly the 110 records on disk."""
    real = ("[browse_feed_and_post_detail] " + "prose. " * 60 +
            "\n[post_detail_comment_flow] GET /x → 422")
    old = _salient_error(real, cap=300)
    assert "[browse_feed_and_post_detail]" not in old, old[:60]
    assert not old.startswith("["), old[:40]
