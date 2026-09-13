r"""#943: a ratchet on the test shape that breaks when a COMMENT grows.

Measured across the suite:

    source-text assertions       947 in 223 files
      of which dependency-ish   1020 comparisons (`'_is_navigable_page(page)' in src`) — legitimate:
                                they couple to a call that must exist, and break when it is removed
      of which spelling-pinned   528 — the shape that has cost four tests this session alone
    ★ fixed byte windows          59 in 26 files — `src[i:i + 900]` and friends

The byte windows are the unambiguous subset: nothing about them is a claim on behaviour, and every
one of them fires the day someone writes a longer comment inside the block being measured. That
happened today — #942 added a dozen comment lines and `#588`'s `src[i:i + 2400]` stopped reaching
the line it asserts. The test failed for a change that touched no logic at all.

This does not pretend to fix the 59. It is a RATCHET: the number may fall, never rise. Each one
should be re-anchored on a landmark or an AST node when its file is next touched — that is how
#588's and #917's were replaced today.

    _CEILING is the count as measured now. Lower it when you fix one; never raise it.
"""
import ast
import pathlib

import pytest


# 59 -> 57: the 18 windows in test_login_failure_attribution_612,
# test_ladder_substitution_attribution_592 and test_record_vs_live_fidelity_618 are now
# anchored on landmarks. Two of them are `not in <block>` checks, which a byte window
# cannot express at all — widen it and the next sibling statement walks in — so those
# use an indentation-aware block boundary.
_CEILING = 57

_TESTS = pathlib.Path(__file__).resolve().parent


def _fixed_windows():
    """`<expr>[i : i + N]` with a literal N >= 100 — a slice sized in BYTES of source."""
    out = []
    for p in sorted(_TESTS.glob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)):
                continue
            u = n.slice.upper
            if (isinstance(u, ast.BinOp) and isinstance(u.op, ast.Add)
                    and isinstance(u.right, ast.Constant)
                    and isinstance(u.right.value, int) and u.right.value >= 100):
                out.append(f"{p.name}:{n.lineno}  {ast.unparse(n)[:60]}")
    return out


# #1202lk: THE RATCHET HAD THE SAME BLIND SPOT IT WAS BUILT TO CLOSE.
#
# `_fixed_windows` matches `src[i : i + N]` only. The BACKWARDS form — `src[i - N : i]`, "the
# 2500 bytes before this landmark" — is the identical defect: it is sized in bytes of source
# and it fires the day a comment grows inside the block. It was invisible here, so the 59 was
# never the population; it was the half of the population that happens to count forwards.
#
# Found by being bitten: #1202lk added a re-capture arm to the visual escape branch, and
# `test_visual_release_rejudges_fresh_before_escaping`'s `src[max(0, i_release - 2500):i_release]`
# stopped reaching the call it asserts. No logic changed. That test is now anchored on the
# branch's AST, and #105's sibling assertion on its enclosing function — which is why
# the count below is 29 and not the 31 that were there this morning.
#
# ★ The re-anchor also has to be checked for VACUITY, which is the lesson that cost the most
# here: the natural replacement `"_maybe_run_visual_fidelity" in <branch text>` passes even
# with the call deleted, because #102's own comment inside that branch spells the method name.
# A landmark anchor is not automatically a stronger assertion than the window it replaced —
# counter-prove it by deleting the mechanism.
_CEILING_BACKWARD_1202LK = 29


def _backward_windows():
    """`<expr>[i - N : ...]` with a literal N >= 100 — the same defect, counting backwards.

    `max(0, i - N)` is unwrapped: it is the commonest spelling and hiding behind it would make
    this ratchet trivially evadable.
    """
    def _is_back(e):
        return (isinstance(e, ast.BinOp) and isinstance(e.op, ast.Sub)
                and isinstance(e.right, ast.Constant)
                and isinstance(e.right.value, int) and e.right.value >= 100)

    out = []
    for p in sorted(_TESTS.glob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)):
                continue
            lo = n.slice.lower
            if (isinstance(lo, ast.Call) and getattr(lo.func, "id", "") == "max"
                    and len(lo.args) == 2):
                lo = lo.args[1]
            if lo is not None and _is_back(lo):
                out.append(f"{p.name}:{n.lineno}  {ast.unparse(n)[:60]}")
    return out


def test_the_backward_locator_still_sees_them():
    """★ Non-vacuity, same reason as its forward twin."""
    assert len(_backward_windows()) > 10, "the locator found almost none — suspect the locator"


def test_backward_source_windows_do_not_grow():
    """★ THE ratchet, backwards."""
    found = _backward_windows()
    assert len(found) <= _CEILING_BACKWARD_1202LK, (
        f"{len(found)} backwards source windows, ceiling {_CEILING_BACKWARD_1202LK}. "
        f"`src[i - N : i]` breaks when a comment grows exactly as `src[i : i + N]` does — "
        f"anchor on a landmark or an AST node instead:\n  "
        + "\n  ".join(found[_CEILING_BACKWARD_1202LK:]))


def test_the_backward_ceiling_is_not_stale():
    n = len(_backward_windows())
    assert n >= _CEILING_BACKWARD_1202LK - 5, (
        f"only {n} backwards windows remain against a ceiling of "
        f"{_CEILING_BACKWARD_1202LK}; lower it to {n}")


def test_the_one_fixed_today_stays_fixed():
    """#1202lk re-anchored the visual-escape assertion; a regression to a byte window shows."""
    # Keyed on the SPELLING, not a line number: line numbers move with every edit above
    # them, which would make this assertion pass for the wrong reason.
    found = [f for f in _backward_windows() if f.startswith("test_kickoff_retry.py:")]
    assert not any("2500" in f for f in found), (
        "the visual-escape assertion regressed to a 2500-byte backwards window: " + str(found))


def test_the_locator_still_sees_them():
    """★ Non-vacuity: a ratchet that matches nothing passes forever."""
    assert len(_fixed_windows()) > 10, "the locator found almost none — suspect the locator"


def test_fixed_source_windows_do_not_grow():
    """★ THE ratchet."""
    found = _fixed_windows()
    assert len(found) <= _CEILING, (
        f"{len(found)} fixed source windows, ceiling {_CEILING}. A window sized in bytes breaks "
        f"when a COMMENT grows — anchor on a landmark or an AST node instead:\n  "
        + "\n  ".join(found[_CEILING:]))


def test_the_ceiling_is_not_stale():
    """If someone fixes one, say so — a ceiling that drifts above the real count stops ratcheting."""
    n = len(_fixed_windows())
    assert n >= _CEILING - 5, (
        f"only {n} fixed windows remain against a ceiling of {_CEILING}; lower _CEILING to {n}")


def test_the_two_fixed_today_stay_fixed():
    """#588's and #917's were re-anchored; a regression to a byte window should be visible."""
    found = " ".join(_fixed_windows())
    assert "test_content_dominated_chrome_checklist_588" not in found
    assert "test_a_total_blackout_is_not_silence_917" not in found


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
