r"""Guard: no NEW fixed-width slices of `inspect.getsource` output.

A source-assertion written as ``src[i:i + 900]`` breaks the moment anything is inserted into the
block it targets — and it fails LOUDLY, as a wall of assertion errors that reads like a
regression. It happened four times in one session:

    #588  the window stopped short after #589 widened the block
    #614  the window ran PAST the block into an `elif` and matched the wrong code
    #617  seven assertions failed at once — #619 both inserted code into the block AND added a
          "#617" cross-reference 660 lines earlier, so `index("#617")` found the wrong anchor
    #621  the window was broken by the comment of the very commit that introduced it

The fourth happened two turns after writing "semantic boundaries only" into the handoff. A note
does not enforce; this does.

The 46 existing occurrences are frozen per file rather than rewritten: converting them all is
churn with its own risk, and the actual failure mode is that new ones keep being ADDED. No file
may grow, and a file not listed here must have none.

The fix for any new assertion is a semantic boundary:

    i = src.index("#620 — NAME THE SCREENS")          # a unique heading, not a bare "#620"
    block = src[i:src.index("elif check:", i)]        # end at the next construct
"""
import glob
import os
import re

import pytest

_SLICE_RE = re.compile(r"\b(\w+)\[\s*(\w+)\s*:\s*\2\s*\+\s*(\d+)\s*\]")

# frozen 2026-08-12 — see the module docstring. Lower these freely; never raise one.
_BASELINE = {
    "test_ad_state_reference_frame_601.py": 1,
    "test_checklist_blocker_explains_itself_585.py": 2,
    "test_content_dominated_chrome_checklist_588.py": 1,
    "test_declared_405_is_timing_614.py": 4,
    "test_durable_inbox_read_preview_604.py": 4,
    "test_in_batch_read_dedupe_609.py": 1,
    "test_incomplete_player_chrome_blocks_589.py": 3,
    "test_ladder_substitution_attribution_592.py": 5,
    "test_login_failure_attribution_612.py": 8,
    "test_mcp_not_built_is_timing_616.py": 1,
    "test_mid_interaction_reference_frame_595.py": 2,
    "test_primary_dataless_needs_a_fetch_573.py": 1,
    "test_record_vs_live_fidelity_618.py": 5,
    "test_remediation_feedback_619.py": 3,
    "test_stale_route_component_597.py": 1,
    "test_terminal_task_ack_605.py": 2,
    "test_unsatisfiable_chain_rejected_at_registration_586.py": 1,
    "test_user_content_relation_read_scope_598.py": 1,
}


def _counts():
    here = os.path.dirname(os.path.abspath(__file__))
    out = {}
    for path in sorted(glob.glob(os.path.join(here, "test_*.py"))):
        name = os.path.basename(path)
        if name == os.path.basename(__file__):
            continue
        src = open(path, encoding="utf-8").read()
        if "getsource" not in src:
            continue
        n = sum(1 for line in src.split("\n") if _SLICE_RE.search(line))
        if n:
            out[name] = n
    return out


def test_no_file_gains_a_fixed_width_source_window():
    counts = _counts()
    grew = {f: (n, _BASELINE.get(f, 0))
            for f, n in counts.items() if n > _BASELINE.get(f, 0)}
    assert not grew, (
        "fixed-width getsource slices added: " + repr(grew) +
        " — use a semantic boundary instead, e.g. "
        "src[i:src.index('<next construct>', i)]")


def test_a_new_test_file_starts_at_zero():
    counts = _counts()
    new = sorted(f for f in counts if f not in _BASELINE)
    assert not new, f"new test files using a fixed-width source window: {new}"


def test_the_baseline_does_not_list_files_that_are_gone_or_clean():
    """Keeps the frozen list honest as occurrences get cleaned up."""
    counts = _counts()
    stale = sorted(f for f in _BASELINE if f not in counts)
    assert not stale, (f"baseline entries no longer needed (lower or drop them): {stale}")


def test_the_detector_actually_matches_the_shape_it_claims():
    assert _SLICE_RE.search("window = src[i:i + 900]")
    assert _SLICE_RE.search("w = mod[start:start+40]")
    # and does not fire on a semantic slice
    assert not _SLICE_RE.search("block = src[i:src.index('elif check:', i)]")
    assert not _SLICE_RE.search("head = content[:MAX_READ_CHARS]")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
