r"""#857: #781 restrained `missing`, and the over-claim moved to `deviations`.

Found by asking a verification question instead of a search question: **did a shipped fix move its
own metric?**

`#652` emits a rail/carousel position indicator — the corpus's most persistent missing component,
~140 reports at ~100% persistence, no channel had ever emitted one. It shipped 2026-08-12 22:34,
and **7 corpus runs executed after that** (r145–r151). Split on the SHIP TIME rather than a round
run number (#795's rule — my first cut used r100, which is 6 days too early):

    pagination-indicator deviation   before #652: 92/124 (74%)   after: 5/7 (71%)

**It did not move.** But the fix is not broken — checked at both ends:

    gate fires (design enumerates an indicator)   7 of 7
    emitter markup in the DELIVERED source        7 of 7   ('h-1 w-1 rounded-full' / 'h-0.5 w-4')

The component is on the page. The judge reports it absent anyway, in 5 of those 7.

★ **`#781` already fixed exactly this class** — *"Never list under `missing` an element you cannot
point to in the first image"* — and scoped it to `missing`. `deviations` carried no such
constraint, so the over-claim moved one field over. And `deviations` is the more costly field:
`remediation_text` turns it into the lane's concrete to-do list (#855), so an unanchored entry
spends a round building something already there.

The rule is stated symmetrically because a deviation is a claim about BOTH images: *"X is missing"*
must be pointable in the reference; *"X is wrong/extra"* must be pointable in the implementation.
It demands POINTING, not silence — the judge must still report every difference it can locate.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _prompt():
    cands = [v for v in vars(vf).values()
             if isinstance(v, str) and '"deviations"' in v and '"similarity"' in v]
    assert len(cands) == 1, f"expected exactly one judge prompt, found {len(cands)}"
    return cands[0]


def test_the_prompt_is_findable():
    """Non-vacuity: every assertion below reads this string, and a renamed constant would make
    them all vacuous — the failure mode this session hit repeatedly."""
    p = _prompt()
    assert len(p) > 800 and "deviations" in p


def test_deviations_now_carry_the_anchor_rule():
    p = _prompt()
    i = p.index('"deviations"')
    block = p[i:i + 700]
    assert "ANCHOR EVERY" in block, block[:300]
    assert "FIRST" in block and "SECOND" in block, block[:300]


def test_it_names_both_directions():
    """A deviation is a claim about both images. Constraining only the 'missing' direction is what
    left #781 half-applied in the first place."""
    p = _prompt()
    block = p[p.index('"deviations"'):]
    assert "missing" in block and ("wrong" in block or "extra" in block)


def test_it_forbids_inference_from_the_real_product():
    """The mechanism #781 identified: the judge scores against its prior of what the product looks
    like rather than against the image in front of it."""
    block = _prompt()[_prompt().index('"deviations"'):]
    assert "do not infer it from what the real product usually has" in block


def test_it_demands_pointing_not_silence():
    """★ The guard must not become a gag. A judge told to report less would hide real defects;
    this one is told where to look before writing."""
    block = _prompt()[_prompt().index('"deviations"'):]
    assert "point to" in block
    assert "WHERE on the screen + WHAT differs" in block, "the original instruction must survive"


def test_the_missing_rule_is_untouched():
    """#781 stays exactly as it was — #857 extends its discipline, it does not replace it."""
    assert "Never list under `missing` an element you cannot point to in the first image" in _prompt()


def test_the_prompt_still_renders():
    """The block is an f-string-formatted template with `{{`-escaped JSON braces; a stray single
    brace turns the whole judge call into a KeyError at runtime, and the gate swallows it.

    Rendered with the REAL call site's arguments (visual_fidelity.py:2206) rather than a guessed
    subset — my first version passed only `rubric_block` and died on `KeyError: 'name'`, which is
    #804's lesson exactly: a prompt test that does not use the caller's arguments is testing a
    template nobody renders."""
    out = _prompt().format(name="browse_home", route="/browse",
                           rubric_block=vf._rubric_block())
    assert '"deviations"' in out and '"similarity"' in out
    assert "ANCHOR EVERY" in out and "browse_home" in out


def test_the_fix_it_was_written_for_is_still_wired():
    """Non-vacuity for the whole premise: if #652's emitter went away, the 7-of-7 measurement in
    this docstring stops meaning anything and the finding should be re-derived, not trusted."""
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    out = fs._rail_pagination_652(
        {"screens": [{"components": [{"role": "carousel pagination dots", "id": "pg"}]}]})
    assert out and ("rounded-full" in out or "h-0.5" in out)
    assert fs._rail_pagination_652({"screens": [{"components": [{"role": "hero", "id": "h"}]}]}) == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
