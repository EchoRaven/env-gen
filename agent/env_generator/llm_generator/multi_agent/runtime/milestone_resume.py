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
