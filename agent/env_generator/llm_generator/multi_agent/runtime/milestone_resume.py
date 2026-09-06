"""#1202bz — milestone-level granularity for --resume.

`.checkpoint` recorded exactly one phase, `agent_workflow: planning`, for the whole run --
measured across the corpus: 119 of 121 runs, every one of them that single entry. So a
resume knew the run had started and nothing else, and the milestone loop re-entered at
milestone 1 every time. The state itself was never lost (shared/hubs/ is file-backed
JsonStore, app/ and worktrees/ are git); what was missing was any record of HOW FAR the
run got.

WHY NOT "complete means skip". A milestone's body is where the lanes work: the
implementation dispatch and every coordination tick live inside it. The delivery gate that
ends a run runs AFTER the loop. r35 is the case that matters: milestone 1 finished, the
post-loop gate failed on one check, and the run died. Had "complete" alone meant "skip",
a resume would have walked past the only place remediation can happen, re-run the gate,
failed identically and exited -- worse than today, and worse in a way that looks like
progress.

THE RULE. Skip a completed milestone only when a LATER milestone has a record of its own.
A later start is positive evidence that this milestone was finished with and the run moved
past it; the milestone the run was still working on has no successor, so it is always
re-entered and remediation still has somewhere to happen. A fresh run has no phases at all,
so nothing is ever skipped there.

The key carries the milestone's identity, not just its position, so editing the milestone
list between attempts cannot make a resume skip work it never did.
"""

from __future__ import annotations

import re
from typing import Dict, Mapping

_KEY_RE = re.compile(r"^milestone:(\d+):")


def milestone_key_1202bz(idx: int, milestone: Mapping) -> str:
    """Identity-bearing phase key. Position alone would let an edited milestone list skip
    work that was never done under that name."""
    m = milestone if isinstance(milestone, Mapping) else {}
    name = str(m.get("name", "") or "?").strip()
    version = str(m.get("version", "") or "?").strip()
    return f"milestone:{int(idx)}:{name}@{version}"


def _index_of(key: str):
    m = _KEY_RE.match(key or "")
    return int(m.group(1)) if m else None


def should_skip_milestone_1202bz(phase_status: Mapping[str, str],
                                 idx: int, milestone: Mapping) -> bool:
    """True when this milestone completed AND the run demonstrably moved past it."""
    key = milestone_key_1202bz(idx, milestone)
    if str((phase_status or {}).get(key, "")).lower() != "complete":
        return False
    for other in (phase_status or {}):
        if other == key:
            continue
        j = _index_of(other)
        if j is not None and j > int(idx):
            return True
    return False


def phase_status_map_1202bz(checkpoint_manager) -> Dict[str, str]:
    """{phase key: status} from a CheckpointManager, tolerating either a PhaseCheckpoint
    object or the plain dict a reloaded checkpoint may carry. Best-effort: an unreadable
    checkpoint means "skip nothing", which is the safe direction."""
    out: Dict[str, str] = {}
    try:
        phases = checkpoint_manager.checkpoint.phases or {}
    except Exception:
        return out
    for name, ph in phases.items():
        try:
            status = ph.get("status") if isinstance(ph, dict) else getattr(ph, "status", "")
            out[str(name)] = str(status or "")
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# #1202ce: the OTHER two milestone-scoped deferral gates.
# ---------------------------------------------------------------------------
# The visual gate carries its counters in a class that can persist itself. The page-build
# and test-user-squad gates keep theirs as plain orchestrator attributes, reset in the same
# milestone block, and read by the same shape of release decision --
# `pages_release_decision(deferred_since, attempts, ...)` escapes on
# `(now - deferred_since) > escape_s`. So a resume restarted those clocks at zero too, and a
# run most of the way to an escape had to earn all of it again.
#
# Saved at the coordination tick rather than at each mutation: there are only five fields
# and two write sites each, but a tick is the natural granularity and bounds the loss to one
# tick's movement instead of everything. Keyed by milestone, so advancing still starts clean.

_GATE_STATE_1202CE = "milestone_gates.json"

_GATE_FIELDS_1202CE = (
    "_pages_gate_deferred_since", "_pages_gate_attempts",
    "_tu_squad_passed", "_tu_squad_deferred_since", "_tu_squad_attempts",
    # The same escape shape, found by scanning the orchestrator for `*_deferred_since` /
    # `*_attempts` pairs rather than by waiting for each to surface: both of these feed
    # `squad_release_decision(deferred_since, attempts, now)`, the identical bounded escape.
    # They differ only in being run-scoped rather than milestone-scoped -- initialised
    # lazily (`if getattr(self, ..., None) is None`), which is also why restoring them here
    # is enough: a restored value is not None, so the lazy branch leaves it alone.
    "_rc_deferred_since", "_rc_attempts",
    "_tu_browser_deferred_since", "_tu_browser_attempts",
)


# #1202dv: the seventeen the milestone-boundary reset block ALSO clears, which #1202ce's list
# does not reach. Every one is a bounded budget or the signature a breaker compares against:
# `attempt N/6`, the stuck-loop breakers, #230's per-milestone grace, the abort grace. A
# resume mid-milestone refilled all of them, so the breaker that exists to end a stall
# started over instead. The block resets them per MILESTONE because "a new milestone's
# failures are genuinely new work, not a continuation of the prior stall" — re-entering the
# SAME milestone is the opposite case, and is what this restores.
_FWGATE_FIELDS_1202DV = (
    "_project_delivered",
    "_framework_validation_attempts", "_fwval_last_attempt_ts", "_fwval_healed_sig",
    "_fwval_failure_set", "_fwval_stuck_count", "_fwval_stuck_blocker",
    "_fwdeliver_stuck_count", "_fwdeliver_stuck_key", "_fwdeliver_first_decline_ts",
    "_fwdeliver_grace_count", "_fwdeliver_prev_failed", "_fwdeliver_last_shrink_ts",
    "_fwval_abort_grace_used", "_fwval_abort_deliver_reason", "_fwval_abort_progress_sig",
)
# DELIBERATELY NOT PERSISTED — `_silent_lane_nudges`. It sits in the milestone-reset block,
# so it looked milestone-scoped, but `run()` ALSO resets it at the implementation dispatch
# (orchestrator.py, right after `_dispatch_implementation_phase()`), and orchestrator's own
# note says "init/reset by run()". A resume re-spawns the lanes, so "how long has this lane
# been silent" legitimately restarts. Verified on netflix-r45: restored at the milestone
# entry and clobbered ~400 lines later by that reset, i.e. persisting it stored a value that
# could never survive — a dead field, which is the shape this batch exists to remove.

# Type-aware, because `json.dumps(..., default=str)` turns a set into the STRING "{'a', 'b'}".
# It round-trips without error and then breaks every `==` / `in` the breakers do against it —
# a silent wrong answer, which is worse than a failed restore.
_SET_FIELDS_1202DV = {"_fwdeliver_prev_failed": set, "_fwval_failure_set": frozenset}


def _encode_1202dv(name, value):
    if name in _SET_FIELDS_1202DV and isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    return value


def _decode_1202dv(name, value):
    ctor = _SET_FIELDS_1202DV.get(name)
    if ctor is not None and isinstance(value, list):
        return ctor(value)
    return value


def _gate_state_path_1202ce(output_dir):
    from pathlib import Path as _P
    return _P(output_dir) / "design" / _GATE_STATE_1202CE


def save_gate_counters_1202ce(orch, milestone_key) -> None:
    """Land the page-build and squad deferral counters. Best-effort: failing costs a resume
    the progress it would otherwise have inherited, never the run."""
    import json
    import os
    try:
        p = _gate_state_path_1202ce(orch.output_dir)
        blob = {"milestone": milestone_key}
        for f in _GATE_FIELDS_1202CE:
            blob[f] = getattr(orch, f, None)
        for f in _FWGATE_FIELDS_1202DV:      # #1202dv
            blob[f] = _encode_1202dv(f, getattr(orch, f, None))
        p.parent.mkdir(parents=True, exist_ok=True)
        _text = json.dumps(blob, indent=2, default=str)
        # #1202dv: this is now called every tick rather than only on the snapshot cadence, so
        # guard the write. An identical rewrite is the #1202dk/#1114 hazard — it burns I/O and
        # moves mtime, which this repo has already had read as "the content changed".
        try:
            if p.is_file() and p.read_text(encoding="utf-8") == _text:
                return
        except Exception:
            pass
        tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(_text, encoding="utf-8")
        os.replace(tmp, p)          # atomic, like JsonStore._save_raw
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def restore_gate_counters_1202ce(orch, milestone_key) -> bool:
    """Put the counters back onto ``orch`` when the saved ones belong to THIS milestone.

    Returns True if anything was restored, so the caller can skip its reset. A missing file,
    an unreadable one, or a different milestone all return False and leave the caller's
    fresh-milestone defaults exactly as they were -- today's behaviour.
    """
    import json
    try:
        p = _gate_state_path_1202ce(orch.output_dir)
        if not (milestone_key and p.is_file()):
            return False
        blob = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(blob, dict) or blob.get("milestone") != milestone_key:
            return False
        for f in _GATE_FIELDS_1202CE:
            if f in blob:
                setattr(orch, f, blob[f])
        for f in _FWGATE_FIELDS_1202DV:      # #1202dv
            if f in blob:
                setattr(orch, f, _decode_1202dv(f, blob[f]))
        return True
    except Exception:
        return False
