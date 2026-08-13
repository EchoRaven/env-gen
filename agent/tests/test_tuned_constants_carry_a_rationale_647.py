r"""Guard: a NEW tuned constant must say where its number came from.

This codebase's strongest convention is that a tuned number carries the measurement that produced
it — which is why so much of this session's work was possible: `#500`, `#542a`, `#566y`, `#598`
and the rest can be re-derived from their own comments.

The convention was never enforced, and it has decayed. Sweeping module-level numeric constants in
`runtime/` and `agents/runtime/`: **17 of 37 carry no rationale**. Most are harmless vocabulary
sets (`_TRUTHY_STRS`, `_VIDEO_EXTS`), but three were viewports that silently disagreed — the lane
checked its work at 1280x720 while the gate scored 1380x900 (#646) — and two were seed-gate floors
whose calibration turned out to be good but unrecorded (#647: rows/table p10 = 5 against a bar of
5; 3 of 43 runs below a total-rows floor of 10).

The existing 17 are frozen per file rather than annotated in bulk: writing 17 rationales I did not
measure would be inventing them, which is worse than the gap. What matters is that the count
cannot grow — the same shape as the fixed-width-window guard and the `get_event_loop` guard, both
of which caught a real regression in this session.

To satisfy this for a new constant, put the measurement above it:

    # #NNN: median 12 rows/table over 43 runs, p10 = 5 — only 3% fall below.
    _DEFAULT_MIN_ROWS = 5
"""
import glob
import os
import re

import pytest

_ROOTS = ("multi_agent/runtime", "multi_agent/agents/runtime")
_CONST = re.compile(r'^(_?[A-Z][A-Z0-9_]{3,})\s*=\s*(\d+(?:\.\d+)?|\{[^}]*\d[^}]*\})\s*(#.*)?$')

# frozen 2026-08-12 — lower these freely, never raise one.
_BASELINE = {
    "approval.py": 1,
    "auto_commit.py": 1,
    "flow_coverage.py": 2,
    "framework_validation.py": 1,
    "frontend_scaffold.py": 1,
    "material_prep.py": 2,
    "reference_materials.py": 2,
    "seed_audit.py": 1,
    "test_user_squad.py": 1,
    "visual_fidelity.py": 1,
}


def _unexplained():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(here, "env_generator", "llm_generator")
    out = {}
    for root in _ROOTS:
        for path in sorted(glob.glob(os.path.join(base, root, "*.py"))):
            lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
            n = 0
            for i, line in enumerate(lines):
                m = _CONST.match(line)
                if not m:
                    continue
                inline = m.group(3)
                ctx, j = [], i - 1
                while j >= 0 and lines[j].lstrip().startswith("#"):
                    ctx.append(lines[j].strip())
                    j -= 1
                if (inline and len(inline) > 12) or len(" ".join(ctx)) > 60:
                    continue
                n += 1
            if n:
                out[os.path.basename(path)] = n
    return out


def test_no_file_gains_an_unexplained_tuned_constant():
    found = _unexplained()
    grew = {f: (n, _BASELINE.get(f, 0)) for f, n in found.items() if n > _BASELINE.get(f, 0)}
    assert not grew, (
        "tuned constant(s) added without a measured rationale: " + repr(grew) +
        " — put the measurement in a comment above the number, e.g. "
        "'# #NNN: median 12 over 43 runs, p10 = 5'.")


def test_a_file_not_in_the_baseline_must_have_none():
    found = _unexplained()
    new = sorted(f for f in found if f not in _BASELINE)
    assert not new, f"new file(s) with unexplained tuned constants: {new}"


def test_the_baseline_does_not_list_files_that_are_clean_now():
    """Keeps the frozen list honest as rationales get written."""
    found = _unexplained()
    stale = sorted(f for f in _BASELINE if f not in found)
    assert not stale, f"baseline entries no longer needed (lower or drop them): {stale}"


def test_the_detector_matches_the_shape_it_claims():
    assert _CONST.match("_MIN_ROWS = 5")
    assert _CONST.match('_VIEWPORT = {"width": 1380, "height": 900}')
    assert not _CONST.match("_NAMES = ('a', 'b')")          # no digit: not a tuned number
    assert not _CONST.match("x = 5")                        # not a module constant


def test_the_two_seed_floors_now_carry_their_measurement():
    """#647 — the ones this sweep actually measured, rather than annotating blind."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import seed_audit
    flat = " ".join(inspect.getsource(seed_audit).replace("#", " ").split())
    assert "p10 **5**, median 12, p90 32" in flat
    assert "median **119**" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
