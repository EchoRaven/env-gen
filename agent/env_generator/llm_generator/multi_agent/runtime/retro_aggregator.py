"""Retro stats aggregator (Cutover 16). Pure read-side over HubRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RetroStats:
    bug_stats: Dict[str, Any] = field(default_factory=dict)
    run_stats: Dict[str, Any] = field(default_factory=dict)
    review_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bug_stats": dict(self.bug_stats),
            "run_stats": dict(self.run_stats),
            "review_stats": dict(self.review_stats),
        }


def _bug_stats(workhub) -> Dict[str, Any]:
    if workhub is None or not hasattr(workhub, "stores"):
        return {"total_bugs": 0, "by_severity": {}, "closed": 0, "escalated": 0}
    bugs = [t for t in (workhub.stores.tasks.value() or {}).values()
            if (t.get("metadata") or {}).get("kind") == "bug"]
    by_sev: Dict[str, int] = {}
    closed = 0
    escalated = 0
    for b in bugs:
        meta = b.get("metadata") or {}
        sev = meta.get("severity", "P3")
        by_sev[sev] = by_sev.get(sev, 0) + 1
        state = meta.get("bug_state", "")
        if state == "closed":
            closed += 1
        elif state == "escalated":
            escalated += 1
    return {
        "total_bugs": len(bugs),
        "by_severity": by_sev,
        "closed": closed,
        "escalated": escalated,
    }


def _run_stats(runhub) -> Dict[str, Any]:
    if runhub is None or not hasattr(runhub, "list_runs"):
        return {"total_runs": 0, "passed": 0, "failed": 0, "failure_rate": 0.0}
    runs = runhub.list_runs(limit=1000)
    total = len(runs)
    passed = sum(1 for r in runs if r.get("status") == "completed"
                  and r.get("fail_count", 0) == 0)
    failed = sum(1 for r in runs if r.get("status") == "failed"
                  or r.get("fail_count", 0) > 0)
    return {
        "total_runs": total, "passed": passed, "failed": failed,
        "failure_rate": (failed / total) if total else 0.0,
    }


def _review_stats(codehub) -> Dict[str, Any]:
    if codehub is None or not hasattr(codehub, "stores"):
        return {"total_prs": 0, "force_merged": 0}
    prs = list((codehub.stores.pull_requests.value() or {}).values())
    force_merged = sum(1 for p in prs if p.get("force_merged"))
    return {"total_prs": len(prs), "force_merged": force_merged}


def compute_retro_stats(hub_registry) -> RetroStats:
    return RetroStats(
        bug_stats=_bug_stats(getattr(hub_registry, "workhub", None)),
        run_stats=_run_stats(getattr(hub_registry, "runhub", None)),
        review_stats=_review_stats(getattr(hub_registry, "codehub", None)),
    )


__all__ = ["RetroStats", "compute_retro_stats"]
