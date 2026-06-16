"""commit_gate - step-end stage that scans for loose ends and reports to next step."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DEFAULT_THRESHOLDS = {
    "stale_task_steps": 5,
    "stale_review_steps": 3,
    "stale_pr_steps": 10,
}


def collect_loose_ends(hubs: Any, agent_id: str, step_num: int,
                        thresholds: Optional[Dict[str, int]] = None) -> Dict[str, bool]:
    """Return six-category boolean dict. Use collect_loose_ends_details for the data backing each flag."""
    t = thresholds or DEFAULT_THRESHOLDS
    details = collect_loose_ends_details(hubs, agent_id, step_num, t)
    return {
        "dirty_worktree": bool(details.get("dirty_files")),
        "unpushed_commits": details.get("ahead", 0) > 0 and not details.get("has_open_pr"),
        "stale_claimed_tasks": bool(details.get("stale_claimed_tasks")),
        "forgotten_reviews": bool(details.get("forgotten_reviews")),
        "unhandled_breaking_changes": bool(details.get("unhandled_breaking_changes")),
        "conflict_prs_unresolved": bool(details.get("conflict_prs_unresolved")),
    }


def collect_loose_ends_details(hubs: Any, agent_id: str, step_num: int,
                                thresholds: Dict[str, int]) -> Dict[str, Any]:
    """Return full details dict used by both the bool collect and the prompt renderer."""
    details: Dict[str, Any] = {
        "dirty_files": [], "ahead": 0, "branch": f"agent/{agent_id}",
        "has_open_pr": False, "stale_claimed_tasks": [],
        "forgotten_reviews": [], "unhandled_breaking_changes": [],
        "conflict_prs_unresolved": [],
    }
    ch = getattr(hubs, "codehub", None)
    if ch is not None and hasattr(ch, "get_my_branch_loose_ends"):
        bl = ch.get_my_branch_loose_ends(agent_id)
        details["dirty_files"] = []
        if hasattr(ch, "get_branch_status"):
            bs = ch.get_branch_status(agent_id)
            details["dirty_files"] = bs.get("dirty_files") or []
        details["ahead"] = bl.get("ahead", 0)
        details["has_open_pr"] = bl.get("has_open_pr", False)
        details["conflict_prs_unresolved"] = bl.get("conflict_prs") or []

    wh = getattr(hubs, "workhub", None)
    if wh is not None and hasattr(wh, "list_tasks"):
        stale_threshold = thresholds.get("stale_task_steps", 5)
        in_progress = wh.list_tasks(assignee=agent_id, status="in_progress") or []
        for t in in_progress:
            # We approximate step age - if claimed_at recorded, fall back to step_num
            # threshold comparison since we don't have step_num at claim time
            if step_num >= stale_threshold:
                details["stale_claimed_tasks"].append({
                    "id": t.get("id"), "title": t.get("title"),
                    "claimed_at": t.get("claimed_at"),
                })

    if ch is not None and hasattr(ch, "list_prs_needing_review"):
        forgotten = ch.list_prs_needing_review(agent_id)
        review_threshold = thresholds.get("stale_review_steps", 3)
        for pr in forgotten:
            if step_num >= review_threshold:
                details["forgotten_reviews"].append({
                    "pr_id": pr.get("id"), "author": pr.get("author"),
                })

    ah = getattr(hubs, "registryhub", None)
    if ah is not None and hasattr(ah, "get_breaking_changes"):
        breaking = ah.get_breaking_changes(since_ts=None) or []
        consumers = ah._consumers.value() if hasattr(ah, "_consumers") else {}
        my_consumer_eps = {c.get("endpoint_id") for c in consumers.values()
                           if c.get("agent") == agent_id}
        for change in breaking:
            ep = change.get("endpoint_id")
            if ep in my_consumer_eps:
                handled = False
                if wh is not None and hasattr(wh, "list_tasks"):
                    related = [t for t in (wh.list_tasks(assignee=agent_id) or [])
                                if ep in (t.get("metadata", {}).get("linked_apis") or [])]
                    if any(t.get("status") in ("in_progress", "completed") for t in related):
                        handled = True
                if not handled:
                    details["unhandled_breaking_changes"].append({"endpoint_id": ep})

    return details


def build_commit_gate_prompt(loose: Dict[str, bool], details: Dict[str, Any]) -> Optional[str]:
    """Render an INTEGRITY CHECK markdown block. Returns None if no loose end is set."""
    if not any(loose.values()):
        return None
    lines: List[str] = ["### INTEGRITY CHECK"]
    lines.append("")
    lines.append("You finished this step with the following loose ends:")
    lines.append("")
    if loose.get("dirty_worktree"):
        files = details.get("dirty_files") or []
        lines.append("**Dirty work tree** (uncommitted changes)")
        lines.append(f"  - {len(files)} file(s): {', '.join(files[:5])}{'...' if len(files) > 5 else ''}")
        lines.append("  -> next step: `codehub_commit(message=..., files=[...])`")
        lines.append("")
    if loose.get("unpushed_commits"):
        ahead = details.get("ahead", 0)
        branch = details.get("branch", "")
        lines.append(f"**Branch has {ahead} commits but NO open PR** (on {branch})")
        lines.append("  -> consider: `codehub_open_pr(branch=..., reviewers=[...], linked_tasks=[...])`")
        lines.append("")
    if loose.get("stale_claimed_tasks"):
        tasks = details.get("stale_claimed_tasks") or []
        lines.append(f"**{len(tasks)} claimed task(s) with no progress this step**")
        for t in tasks[:3]:
            lines.append(f"  - {t.get('id', '?')} \"{t.get('title', '')}\"")
        lines.append("  -> either `workhub_task(action=\"complete\", task_id=..., result={...})` / `workhub_fail_task(task_id=..., reason=...)` / `workhub_comment(body=\"progress: ...\")`")
        lines.append("")
    if loose.get("forgotten_reviews"):
        prs = details.get("forgotten_reviews") or []
        lines.append(f"**{len(prs)} PR(s) waiting on your review**")
        for pr in prs[:3]:
            lines.append(f"  - {pr.get('pr_id', '?')} by {pr.get('author', '?')}")
        lines.append("  -> `codehub_review_pr(pr_id, state, inline_comments=[...])`")
        lines.append("")
    if loose.get("unhandled_breaking_changes"):
        bc = details.get("unhandled_breaking_changes") or []
        lines.append(f"**{len(bc)} unhandled breaking change(s) on endpoints you consume**")
        for c in bc[:3]:
            lines.append(f"  - {c.get('endpoint_id', '?')}")
        lines.append("")
    if loose.get("conflict_prs_unresolved"):
        prs = details.get("conflict_prs_unresolved") or []
        lines.append(f"**{len(prs)} of your PR(s) in conflict, unresolved**")
        for pid in prs[:3]:
            lines.append(f"  - {pid}")
        lines.append("  -> `codehub_resolve_conflict(pr_id, resolution_files={...})`")
    return "\n".join(lines)
