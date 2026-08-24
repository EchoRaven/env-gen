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
