"""#1203hl — the gate's own conclusion about the evidence lived past the prose cut.

`_note1202wi` appended `text[:400]`: a silent head cut. `business_chain_failing` is the
check these ledgers rank FIRST by final gate record (29 runs; the last red check in r171,
r176 and r177) and the only check whose detail runs past 400 -- 320 of 687 distinct details
on disk, median 759, longest 2161. What sat past the cut is the gate's VERDICT about the
evidence, not more evidence. Measured: kept 22 of 167 -> 167 of 167.
"""

import ast
import inspect
import re

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg

clip = dg._clip_prose_1203hl
MARKER = re.compile(r"…\[(\d+) chars cut; the gate ledger has the rest\]")

# tiktok-web-r177's own gate detail, verbatim (759 characters).
R177_DETAIL = (
    "3 verification chain(s) have NOT passed: login_phone_email, "
    "release_browse_for_you_feed, creator_follow_profile_relationships (first broken step: "
    "[login_phone_email] DELETE /api/users/therock/follow → 422 (expected [200, 204]; "
    "{\"detail\":[{\"type\":\"int_parsing\",\"loc\":[\"path\",\"id\"],\"msg\":\"Input should be a "
    "valid integer, unable to parse string as an integer\",\"input\":\"therock\"}]}) [fw-no). "
    "run_validation must show business_chain green (re-author the broken step or fix the "
    "endpoint) before delivery. ⚠ 2 OF THE FAILING CHAINS ARE THE SAME ENDPOINT "
    "(#1202lb): DELETE /api/users/therock/follow (2 chains) — the verifier re-authors "
    "the same surface under new names, so these are fewer problems than rows: fixing one "
    "endpoint clears every chain listed against it."
)


def test_the_lane_is_told_the_three_chains_are_one_endpoint():
    out = clip(R177_DETAIL)
    assert "fewer problems than rows" in out, out
    assert "clears every chain listed against it." in out, out


def test_that_verdict_was_outside_the_old_window():
    """Premise of the whole patch, pinned: it is a RECOVERY, not a no-op."""
    assert "fewer problems than rows" not in R177_DETAIL[:400]


def test_the_head_is_byte_identical_to_what_1202wi_kept():
    out = clip(R177_DETAIL)
    assert out.startswith(R177_DETAIL[:400]), out[:60]
    m = MARKER.search(out)
    assert m and m.start() >= 400, out[395:460]


def test_the_cut_is_counted_not_silent():
    out = clip(R177_DETAIL)
    m = MARKER.search(out)
    assert m, out
    dropped = int(m.group(1))
    head = out[:m.start()].rstrip()
    tail = out[m.end():].lstrip("… ")
    assert len(head) + len(tail) + dropped == len(R177_DETAIL), (
        len(head), len(tail), dropped, len(R177_DETAIL))


def test_a_detail_that_fits_is_returned_whole_and_unmarked():
    small = "3 verification chain(s) have NOT passed: a, b, c."
    assert clip(small) == small
    assert not MARKER.search(clip(small))


def test_a_detail_just_over_the_cap_is_not_marked_into_being_longer():
    """head+tail+marker must not be spent reproducing a string it already covers."""
    n = dg._PROSE_CAP_1203HL + dg._PROSE_TAIL_1203HL + dg._PROSE_MARK_LEN_1203HL
    just_under = "x" * n
    assert clip(just_under) == just_under
    just_over = "x" * (n + 1)
    assert MARKER.search(clip(just_over))
    assert len(clip(just_over)) < len(just_over) + dg._PROSE_MARK_LEN_1203HL + 8


def test_it_never_raises_on_junk():
    for bad in (None, 0, [], {"a": 1}):
        clip(bad)


def _note1202wi_ast():
    """The builder is a closure inside `validate_delivery_gate`; reach it through the AST
    of the whole function rather than by slicing its text."""
    tree = ast.parse(inspect.getsource(dg.validate_delivery_gate))
    inner = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_note1202wi"]
    assert len(inner) == 1, [getattr(n, "name", None) for n in inner]
    return inner[0]


def test_the_prose_builder_actually_calls_it():
    """Structural: a module-level clipper nothing calls would pass every test above.
    Pin it to the call that feeds `_prose1202wi`."""
    fn = _note1202wi_ast()
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_clip_prose_1203hl"]
    assert calls, ast.unparse(fn)


def test_the_silent_slice_is_gone_from_the_builder():
    """#1034: the old `text[:400]` cut and said nothing. A reader could not tell a short
    detail from a truncated one."""
    src = ast.unparse(_note1202wi_ast())
    assert "[:400]" not in src, src


def test_the_budgets_are_the_measured_ones():
    assert dg._PROSE_CAP_1203HL == 400
    assert dg._PROSE_TAIL_1203HL == 100
