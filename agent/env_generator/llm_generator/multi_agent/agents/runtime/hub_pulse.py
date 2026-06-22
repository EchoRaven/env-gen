"""hub_pulse — step-start stage that pulls each agent's view of the 4 hubs + MessageBus."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# PROPOSAL #25 A1 — run lifecycle phases, DISPLAY ONLY. Surfaced to agents via
# hub_pulse so they have a communicated model of where the run is + their role.
# These names are for orientation; the #24 GATES stay on their own raw predicates.
_PHASE_ORDER = {"KICKOFF": 0, "IMPLEMENTATION": 1, "VALIDATION": 2}

# One-line meaning of each phase (shown to every lane).
_PHASE_MEANING = {
    "KICKOFF": "the team is DECLARING the contract (endpoints/tables/ui_pages/chains). No code yet.",
    "IMPLEMENTATION": "the contract is finalized; lanes are WRITING the app against it.",
    "VALIDATION": "every business endpoint is implemented; the framework is validating + delivering.",
}

# Per-(lane, phase) role text — the agent's job RIGHT NOW. Keyed by lane keyword
# (matched against agent_id) so spawned workers (backend_worker_xyz) resolve too.
_PHASE_ROLE = {
    ("backend", "KICKOFF"): "respond to kickoff_request: declare your DB tables + API endpoints in the meeting; do NOT write code yet.",
    ("backend", "IMPLEMENTATION"): "write the FastAPI routes + DB logic for endpoints you own in your worktree, then registryhub_register_endpoint(status='implemented'). Put logic in custom_routes.py; the framework owns main.py.",
    ("backend", "VALIDATION"): "answer the verifier's contract questions + fix any failing-check the orchestrator dispatches to you; do not start new features.",
    ("frontend", "KICKOFF"): "respond to kickoff_request: declare your ui_pages + the endpoints they consume; do NOT build pages yet.",
    ("frontend", "IMPLEMENTATION"): "build each declared ui_page (real component, not a stub) + wire its route in App.jsx against the registered endpoints.",
    ("frontend", "VALIDATION"): "fix navigation/dead-control failing-checks the orchestrator dispatches; keep pages faithful to the declared ui_page identity.",
    ("verifier", "KICKOFF"): "wait — verification starts after implementation. Participate in kickoff only if asked.",
    ("verifier", "IMPLEMENTATION"): "wait for the validation-phase trigger; do not start chains until endpoints are implemented.",
    ("verifier", "VALIDATION"): "register + run the verification chains; report failing checks to their owning lane.",
    ("debugger", "KICKOFF"): "stand by — there is no code to debug during kickoff.",
    ("debugger", "IMPLEMENTATION"): "stand by until a real validation run completes; do not file bugs against an empty/partial build.",
    ("debugger", "VALIDATION"): "triage real failing validation runs to the owning lane.",
    ("orchestrator", "KICKOFF"): "chair the kickoff meeting; drive every lane to declare its contract section + reach finalize_kickoff. Do NOT validate/deliver yet.",
    ("orchestrator", "IMPLEMENTATION"): "monitor the lanes, answer questions, keep work flowing; the framework validates/delivers automatically once endpoints are implemented.",
    ("orchestrator", "VALIDATION"): "compose the delivery gate; dispatch failing checks to owners; deliver once green.",
}


def _lane_keyword(agent_id: str) -> str:
    """Map a (possibly worker-suffixed) agent_id to its lane keyword."""
    aid = str(agent_id or "").lower()
    for lane in ("orchestrator", "backend", "frontend", "verifier", "debugger", "knowledge"):
        if lane in aid:
            return lane
    return aid


def _active_kickoff_meeting_unfinalized(hubs: Any) -> bool:
    """True iff the most-recent kickoff meeting has NOT reached phase 'finalized'.

    Source of truth = ``run_kickoff._current_phase`` (the last phase_transition
    decision), matching the kickoff driver's own finalized signal. An open kickoff
    meeting means the team is DECLARING the current milestone's contract — and at
    milestone N>=2 the RegistryHub still holds M1's implemented endpoints, so the
    registry-derived read below would otherwise return VALIDATION and tell a fresh
    lane "do not start new features", causing it to ignore the new milestone's
    kickoff_request as stale (youtube run #15: backend never authored its M2
    section → kickoff timeout → hard abort). Keying on live meeting state re-arms
    KICKOFF for every milestone. Never raises; degrades to False."""
    try:
        wh = getattr(hubs, "workhub", None)
        stores = getattr(wh, "stores", None)
        pages_store = getattr(stores, "pages", None)
        pages = pages_store.value() if pages_store is not None else None
        if not isinstance(pages, dict):
            return False
        latest_id = None
        latest_at = None
        for mid, page in pages.items():
            if not isinstance(page, dict):
                continue
            if str(page.get("kind") or "").lower() != "kickoff":
                continue
            at = page.get("created_at") or 0
            if latest_at is None or at >= latest_at:
                latest_at = at
                latest_id = mid
        if latest_id is None:
            return False
        from ...runtime.kickoff import run_kickoff
        return run_kickoff._current_phase(hubs, latest_id) != "finalized"
    except Exception:
        return False


def current_run_phase(hubs: Any, agent: Any = None) -> str:
    """Return the run lifecycle phase: KICKOFF | IMPLEMENTATION | VALIDATION.

    DISPLAY ONLY — the #24 gates (preconditions.kickoff_finalized /
    validation_phase_reached) MUST NOT import or call this. The gates stay on
    their own sticky predicates so a transient hub re-read here can never invert
    a gate decision (#24 reviewer's subtlety-1 ruling). This is a fresh read that
    MIRRORS the gate SIGNALS for orientation:
      - KICKOFF→IMPL: KickoffBootstrapGate's signal — any RegistryHub endpoint OR
        any WorkHub task. Prefer the agent's STICKY ``_kickoff_bootstrapped`` flag
        when an agent is in scope (so display matches the gate exactly); fall back
        to the hub read otherwise.
      - IMPL→VALIDATION: ``all_business_endpoints_implemented`` (the same predicate
        validation_phase_reached + the delivery driver use).
    Never raises; degrades to KICKOFF on any read error."""
    try:
        # An OPEN kickoff meeting overrides the registry-derived read: at milestone
        # N>=2 the registry still holds M1's endpoints (registry is never reset), so
        # the checks below return VALIDATION and a fresh lane treats the new
        # milestone's kickoff_request as stale. Live meeting state re-arms KICKOFF.
        if _active_kickoff_meeting_unfinalized(hubs):
            return "KICKOFF"
        bootstrapped = bool(getattr(agent, "_kickoff_bootstrapped", False)) if agent is not None else False
        if not bootstrapped:
            rh = getattr(hubs, "registryhub", None)
            has_ep = False
            try:
                if rh is not None and hasattr(rh, "_endpoints"):
                    has_ep = bool(rh._endpoints.value())
                elif rh is not None and hasattr(rh, "get_endpoints"):
                    has_ep = bool(rh.get_endpoints())
            except Exception:
                has_ep = False
            has_task = False
            try:
                wh = getattr(hubs, "workhub", None)
                if wh is not None and hasattr(wh, "list_tasks"):
                    has_task = bool(wh.list_tasks())
            except Exception:
                has_task = False
            if not has_ep and not has_task:
                return "KICKOFF"
        # bootstrapped (or hub shows endpoints/tasks) → IMPL unless validation-ready
        rh = getattr(hubs, "registryhub", None)
        eps = rh.get_endpoints() if (rh is not None and hasattr(rh, "get_endpoints")) else {}
        if eps:
            from ...runtime.lifecycle import all_business_endpoints_implemented
            if all_business_endpoints_implemented(eps):
                return "VALIDATION"
        return "IMPLEMENTATION"
    except Exception:
        return "KICKOFF"


def _pulse_phase(hubs: Any, agent_id: str, agent: Any) -> Dict[str, Any]:
    """Phase block for the pulse: current phase (monotonic display), the
    once-per-transition source, the meaning line, and this lane's role NOW."""
    phase = current_run_phase(hubs, agent=agent)
    transition_from = None
    if agent is not None:
        last = getattr(agent, "_last_shown_phase", None)
        # Monotonic display: never visibly regress (guards a transiently-empty read).
        if last and _PHASE_ORDER.get(phase, 0) < _PHASE_ORDER.get(last, 0):
            phase = last
        if last and last != phase:
            transition_from = last
        agent._last_shown_phase = phase
    lane = _lane_keyword(agent_id)
    return {
        "phase": phase,
        "transition_from": transition_from,
        "meaning": _PHASE_MEANING.get(phase, ""),
        "role": _PHASE_ROLE.get((lane, phase), ""),
    }


def collect_hub_pulse(hubs: Any, agent_id: str, step_num: int = 0, agent: Any = None) -> Dict[str, Any]:
    """Collect the agent's view across 4 hubs. Top-K bounded to control token usage."""
    # Cutover 12: install default subscriptions for this agent (idempotent).
    try:
        from ...runtime.agent_subscriptions import ensure_default_subscriptions
        ensure_default_subscriptions(hubs, agent_id)
    except Exception:
        pass  # never let subscription install break the pulse
    # Bound inbox growth on long sessions: evict read items older than
    # a day, keeping the most recent 50 for short-term recall. Never
    # touches unread items. Cost: O(read_items) per step — negligible.
    try:
        eh = getattr(hubs, "eventhub", None)
        if eh is not None and hasattr(eh, "prune_read_inbox"):
            eh.prune_read_inbox(agent_id)
    except Exception:
        pass
    report: Dict[str, Any] = {
        "codehub": _pulse_codehub(hubs, agent_id, step_num),
        "registryhub": _pulse_registryhub(hubs, agent_id),
        "workhub": _pulse_workhub(hubs, agent_id),
        "eventhub": _pulse_eventhub(hubs, agent_id),
        "assigned_bugs": _pulse_assigned_bugs(hubs, agent_id),
        "open_bug_queue": _pulse_open_bug_queue(hubs, agent_id),
    }
    ready, blocked = _pulse_assigned_tasks(hubs, agent_id)
    report["ready_tasks"] = ready
    report["blocked_tasks"] = blocked
    report["latest_run"] = _pulse_latest_run(hubs, agent_id)
    report["self_audit"] = _pulse_self_audit(hubs, agent_id)
    report["stale_tasks"] = _pulse_stale_tasks(hubs, agent_id)
    report["phase"] = _pulse_phase(hubs, agent_id, agent)  # PROPOSAL #25 A2/A3
    return report


def _pulse_stale_tasks(hubs: Any, agent_id: str) -> List[Dict[str, Any]]:
    """Surfaced only to the orchestrator: tasks that have been pending
    or in_progress past the staleness threshold so the orchestrator can
    nudge the assignee or reassign."""
    if agent_id not in ("orchestrator", "debugger"):
        return []
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_stale_tasks"):
        return []
    try:
        stale = list(wh.list_stale_tasks())
    except Exception:
        return []
    # Cap at top 5 by age (oldest first) to bound pulse size.
    stale.sort(key=lambda t: -int(t.get("age_seconds") or 0))
    return stale[:5]


def _pulse_self_audit(hubs: Any, agent_id: str) -> Dict[str, Any]:
    """Compare the agent's worktree writes against what they've registered
    in the hubs. Surfaces "you wrote code but forgot to register it"
    drift BEFORE the agent finishes — long-context recovery hint.

    Returns a small dict the renderer can interpret. Empty dict means
    nothing to flag.
    """
    # Resolve worktree-side evidence: dirty (uncommitted) + committed-
    # but-on-this-branch. The latter catches the "I wrote AND committed
    # the route but forgot to register it" case where dirty_files is
    # empty and a dirty-only audit silently misses the drift.
    ch = getattr(hubs, "codehub", None)
    if ch is None or not hasattr(ch, "get_branch_status"):
        return {}
    try:
        bs = ch.get_branch_status(agent_id) or {}
    except Exception:
        return {}
    dirty = list(bs.get("dirty_files") or [])
    committed: List[str] = []
    if hasattr(ch, "list_files_changed_on_branch"):
        try:
            committed = list(ch.list_files_changed_on_branch(agent_id) or [])
        except Exception:
            committed = []
    # Union — same path in both lists is OK, set-dedup downstream.
    all_paths = list({p for p in (dirty + committed) if p})
    # Treat any "app/<area>/..." path as in-domain. We don't want to
    # flag README, configs, or design/* edits — those don't correspond
    # to any hub kind.
    code_paths = [
        p for p in all_paths
        if (p.startswith("app/") or "/src/" in p)
        and not any(ex in p for ex in (".md", ".lock", "package.json", "Dockerfile",
                                          "/tests/", "test_", ".test.", ".spec."))
    ]
    if not code_paths:
        return {}

    out: Dict[str, Any] = {}
    # API drift — any app/backend/* code present but registryhub shows no
    # endpoints owned by this agent.
    api_paths = [p for p in code_paths if "backend" in p or "routes/" in p or "controllers/" in p or "/api/" in p]
    if api_paths:
        ah = getattr(hubs, "registryhub", None)
        owned = 0
        if ah is not None and hasattr(ah, "get_endpoints"):
            try:
                owned = sum(1 for ep in ah.get_endpoints().values() if ep.get("provider") == agent_id)
            except Exception:
                owned = 0
        if owned == 0:
            out["api_drift"] = {
                "code_paths_sample": api_paths[:3],
                "code_paths_count": len(api_paths),
                "owned_endpoints": 0,
            }

    # UI drift — any page/component file but workhub has no ui_pages owned by this agent.
    ui_paths = [p for p in code_paths if any(s in p for s in ("/pages/", ".jsx", ".tsx", ".vue"))]
    if ui_paths:
        rh = getattr(hubs, "registryhub", None)
        owned_pages = 0
        if rh is not None and hasattr(rh, "list_ui_pages"):
            try:
                pages = rh.list_ui_pages()
                owned_pages = sum(
                    1 for p in pages.values()
                    if (p.get("_updated_by") == agent_id or p.get("created_by") == agent_id)
                )
            except Exception:
                owned_pages = 0
        if owned_pages == 0:
            out["ui_drift"] = {
                "code_paths_sample": ui_paths[:3],
                "code_paths_count": len(ui_paths),
                "owned_pages": 0,
            }

    return out


def _pulse_latest_run(hubs: Any, agent_id: str) -> Optional[Dict[str, Any]]:
    if agent_id not in ("orchestrator", "debugger"):
        return None
    rh = getattr(hubs, "runhub", None)
    if rh is None or not hasattr(rh, "list_runs"):
        return None
    try:
        recent = rh.list_runs(limit=1)
    except Exception:
        return None
    return recent[0] if recent else None


def collect(agent_id: str, hub_registry: Any, step_num: int = 0) -> Dict[str, Any]:
    """Cutover 10 convenience alias matching the (agent_id, hub_registry, ...) signature
    used by the bug-triage pulse tests. Returns the same pulse dict that
    ``collect_hub_pulse`` produces, with bug sections populated."""
    return collect_hub_pulse(hub_registry, agent_id, step_num)


def _pulse_assigned_bugs(hubs: Any, agent_id: str) -> List[Dict[str, Any]]:
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_bugs_assigned_to"):
        return []
    try:
        return list(wh.list_bugs_assigned_to(agent_id))
    except Exception:
        return []


def _pulse_assigned_tasks(hubs: Any, agent_id: str):
    """Cutover 23: split assigned pending tasks into (ready, blocked) per dep status."""
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_ready_tasks"):
        return [], []
    try:
        ready = list(wh.list_ready_tasks(assignee=agent_id))
        blocked = list(wh.list_blocked_tasks(assignee=agent_id))
    except Exception:
        return [], []
    return ready, blocked


def _pulse_open_bug_queue(hubs: Any, agent_id: str) -> List[Dict[str, Any]]:
    # Only the Bug Triage Orchestrator gets the global open-bug queue.
    if agent_id != "debugger":
        return []
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_open_bugs"):
        return []
    try:
        return list(wh.list_open_bugs())
    except Exception:
        return []


def _pulse_codehub(hubs: Any, agent_id: str, step_num: int) -> Dict[str, Any]:
    ch = getattr(hubs, "codehub", None)
    if ch is None:
        return {"branch": "", "branch_status": {"clean": True, "dirty_files": [],
                                                  "commits_ahead_of_main": 0, "unpushed_commits": 0},
                "my_open_prs": [], "prs_needing_my_review": []}
    branch_status = ch.get_branch_status(agent_id) if hasattr(ch, "get_branch_status") else {
        "clean": True, "dirty_files": [], "commits_ahead_of_main": 0, "unpushed_commits": 0}
    branch = f"agent/{agent_id}"
    my_open_prs = []
    for pr in ch.stores.pull_requests.value().values():
        if pr.get("author") != agent_id:
            continue
        if pr.get("status") not in (None, "open"):
            continue
        reviews = [r for r in ch.stores.code_reviews.value().values()
                   if r.get("pr_id") == pr.get("id") and r.get("state") == "approve"]
        approvals_received = len({r.get("reviewer") for r in reviews})
        approvals_needed = len(pr.get("reviewers") or [])
        my_open_prs.append({
            "id": pr.get("id"),
            "merge_state": pr.get("merge_state"),
            "approvals_received": approvals_received,
            "approvals_needed": approvals_needed,
            "linked_apis": pr.get("linked_apis") or [],
            "linked_tasks": pr.get("linked_tasks") or [],
        })
    prs_needing_my_review = []
    if hasattr(ch, "get_pending_reviews_for"):
        prs_needing_my_review = ch.get_pending_reviews_for(agent_id, since_steps=0)
    return {
        "branch": branch,
        "branch_status": branch_status,
        "my_open_prs": my_open_prs[:5],
        "prs_needing_my_review": prs_needing_my_review[:5],
    }


def _pulse_registryhub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    ah = getattr(hubs, "registryhub", None)
    if ah is None:
        return {"my_endpoints_with_failed_tests": [],
                "my_consumed_endpoints_with_breaking_changes": [],
                "api_reviews_pending_my_decision": [],
                "my_stale_pending_consumers": []}
    failed = []
    for ep_id, ep in ah.get_endpoints().items():
        if ep.get("provider") != agent_id:
            continue
        tests = ah.get_contract_test_results(ep_id)
        if not tests:
            continue
        latest = max(tests, key=lambda t: t.get("created_at", 0))
        if not latest.get("result", {}).get("passed"):
            failed.append({"id": ep_id,
                            "last_contract_test_status": "failed",
                            "evidence": latest.get("evidence", {})})

    breaking_for_me = []
    consumers = ah._consumers.value()
    my_consumer_endpoints = {(c.get("endpoint_id"), c.get("file_path"))
                              for c in consumers.values()
                              if c.get("agent") == agent_id}
    recent_breaking = ah.get_breaking_changes(since_ts=None)
    for change in recent_breaking[:20]:
        ep_id = change.get("endpoint_id")
        for (consumed_ep, my_file) in my_consumer_endpoints:
            if consumed_ep == ep_id:
                breaking_for_me.append({
                    "endpoint_id": ep_id,
                    "my_file": my_file,
                    **(change.get("breaking") or {}),
                })
                break

    reviews_pending = []
    for r in ah._api_reviews.value().values():
        if agent_id in (r.get("reviewers") or []) and r.get("status") == "pending":
            reviews_pending.append({
                "review_id": r.get("id"),
                "endpoint_id": r.get("endpoint_id"),
                "requested_by": r.get("created_by"),
            })
    stale_pending: List[Dict[str, Any]] = []
    if hasattr(ah, "list_stale_pending_consumers"):
        try:
            for entry in ah.list_stale_pending_consumers():
                if entry.get("agent") == agent_id:
                    stale_pending.append({
                        "endpoint_id": entry.get("endpoint_id"),
                        "file_path": entry.get("file_path"),
                        "age_seconds": int(entry.get("age_seconds") or 0),
                    })
        except Exception:
            stale_pending = []

    return {
        "my_endpoints_with_failed_tests": failed[:5],
        "my_consumed_endpoints_with_breaking_changes": breaking_for_me[:5],
        "api_reviews_pending_my_decision": reviews_pending[:5],
        "my_stale_pending_consumers": stale_pending[:5],
    }


def _pulse_workhub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    wh = getattr(hubs, "workhub", None)
    if wh is None:
        return {"tasks_assigned_to_me_pending": [],
                "tasks_in_progress_by_me": [],
                "mentions_unread": [], "plans_i_own": []}
    pending = wh.list_tasks(assignee=agent_id, status="pending")[:5] if hasattr(wh, "list_tasks") else []
    in_progress = wh.list_tasks(assignee=agent_id, status="in_progress")[:5] if hasattr(wh, "list_tasks") else []
    mentions = []
    if hasattr(wh, "stores"):
        for c in wh.stores.comments.value().values():
            if agent_id in (c.get("mentions") or []):
                mentions.append({
                    "comment_id": c.get("id"),
                    "resource_id": c.get("resource_id"),
                    "from": c.get("agent"),
                    "body": c.get("body", "")[:200],
                })
    # Surface each in-progress task with a ``task.plan`` subfield.
    enriched_plans = []
    for t in in_progress:
        plan = t.get("plan") if isinstance(t, dict) else None
        if not isinstance(plan, dict):
            continue
        stages = plan.get("stages") or {}
        # Count tasks across stages (PlanTool plan structure).
        total = 0
        completed = 0
        for stage in stages.values():
            if not isinstance(stage, dict):
                continue
            for pt in (stage.get("tasks") or {}).values():
                if not isinstance(pt, dict):
                    continue
                total += 1
                if pt.get("status") == "completed":
                    completed += 1
        enriched_plans.append({
            "id": t.get("id"),
            "title": plan.get("title") or plan.get("plan_name"),
            "current_stage_id": plan.get("current_stage_id"),
            "tasks_total": total,
            "tasks_completed": completed,
        })
        if len(enriched_plans) >= 3:
            break
    return {
        "tasks_assigned_to_me_pending": pending,
        "tasks_in_progress_by_me": in_progress,
        "mentions_unread": mentions[:5],
        "plans_i_own": enriched_plans,
    }


def _pulse_eventhub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    eh = getattr(hubs, "eventhub", None)
    if eh is None:
        return {"unread_count_by_priority": {},
                "top_unread": [], "active_subscriptions": 0}
    unread = eh.list_inbox(agent_id, unread_only=True) if hasattr(eh, "list_inbox") else []
    counts = {"urgent": 0, "high": 0, "normal": 0, "low": 0}
    for e in unread:
        p = e.get("priority", "normal")
        counts[p] = counts.get(p, 0) + 1
    sorted_unread = sorted(
        unread,
        key=lambda e: ({"urgent": 0, "high": 1, "normal": 2, "low": 3}.get(e.get("priority", "normal"), 2),
                       -float(e.get("created_at", 0))),
    )
    top = []
    for e in sorted_unread[:3]:
        top.append({
            "event_id": e.get("id"),
            "source_hub": e.get("source_hub"),
            "event_type": e.get("event_type"),
            "resource_id": e.get("resource_id"),
        })
    subs = eh.get_subscriptions(agent=agent_id) if hasattr(eh, "get_subscriptions") else []
    # PROPOSAL #26 N2: surface framework_decision notices addressed to THIS lane (the
    # message body, not just the event_type) so the lane actually sees "the framework
    # superseded your edit to X; don't re-edit it". Filter by payload.lane so a lane
    # never sees another lane's note (both lanes subscribe inbox_only → fan-out reaches
    # both inboxes).
    framework_notices: List[str] = []
    for e in unread:
        if e.get("event_type") != "framework_decision":
            continue
        pl = e.get("payload") or {}
        if pl.get("lane") in (None, agent_id) and pl.get("message"):
            framework_notices.append(pl["message"])
    return {
        "unread_count_by_priority": counts,
        "top_unread": top,
        "active_subscriptions": len(subs),
        "framework_notices": framework_notices,
    }


def should_render(pulse: Dict[str, Any]) -> bool:
    """Return True if any section has content worth showing."""
    ch = pulse.get("codehub") or {}
    bs = ch.get("branch_status") or {}
    if not bs.get("clean", True):
        return True
    if bs.get("commits_ahead_of_main", 0) > 0:
        return True
    if ch.get("my_open_prs") or ch.get("prs_needing_my_review"):
        return True
    ah = pulse.get("registryhub") or {}
    if (ah.get("my_endpoints_with_failed_tests")
        or ah.get("my_consumed_endpoints_with_breaking_changes")
        or ah.get("api_reviews_pending_my_decision")
        or ah.get("my_stale_pending_consumers")):
        return True
    wh = pulse.get("workhub") or {}
    if (wh.get("tasks_assigned_to_me_pending")
        or wh.get("tasks_in_progress_by_me")
        or wh.get("mentions_unread")
        or wh.get("plans_i_own")):
        return True
    eh = pulse.get("eventhub") or {}
    if eh.get("top_unread") or any((eh.get("unread_count_by_priority") or {}).values()):
        return True
    if pulse.get("assigned_bugs") or pulse.get("open_bug_queue"):
        return True
    if pulse.get("ready_tasks") or pulse.get("blocked_tasks"):
        return True
    if pulse.get("latest_run"):
        return True
    sa = pulse.get("self_audit") or {}
    if sa.get("api_drift") or sa.get("ui_drift"):
        return True
    if pulse.get("stale_tasks"):
        return True
    return False


def _build_phase_lines(pulse: Dict[str, Any]) -> List[str]:
    """PROPOSAL #25 A2/A3 — the phase block: a once-per-transition banner (if the
    phase just changed) + the always-on current phase + this lane's role NOW."""
    ph = pulse.get("phase") or {}
    phase = ph.get("phase")
    if not phase:
        return []
    out: List[str] = []
    tr = ph.get("transition_from")
    if tr:
        out.append(f"### ▶ PHASE TRANSITION: {tr} → {phase}")
        out.append(f"The run just moved to **{phase}**. {ph.get('meaning', '')}")
    out.append(f"### 📍 PHASE: {phase} — {ph.get('meaning', '')}")
    role = ph.get("role")
    if role:
        out.append(f"**YOUR ROLE NOW:** {role}")
    out.append("")
    return out


def _framework_notice_lines(pulse: Dict[str, Any]) -> List[str]:
    """PROPOSAL #26 N2 — render framework-decision notices (the framework superseded
    this lane's file / regenerated it) prominently so the lane stops fighting it."""
    notices = ((pulse.get("eventhub") or {}).get("framework_notices")) or []
    if not notices:
        return []
    out = ["### ⚙ FRAMEWORK NOTICES (act on these — do not fight the framework)"]
    for msg in notices[:4]:
        out.append(f"  - {msg}")
    out.append("")
    return out


def build_hub_pulse_prompt(pulse: Dict[str, Any]) -> Optional[str]:
    """Render the pulse dict as a markdown block. Returns None if all sections empty.

    The phase block (#25 A2/A3) renders even on an otherwise-empty pulse so a quiet
    step still orients the agent — it is prepended ahead of the should_render gate."""
    # Always-render prefix (#25 A2/A3 phase + #26 N2 framework notices): these must
    # surface even on an otherwise-empty pulse, so they precede the should_render gate.
    prefix = _build_phase_lines(pulse) + _framework_notice_lines(pulse)
    if not should_render(pulse):
        return "\n".join(prefix).rstrip() if prefix else None
    lines: List[str] = list(prefix)
    lines.append("### HUB PULSE")

    ch = pulse.get("codehub") or {}
    bs = ch.get("branch_status") or {}
    ch_has_content = (not bs.get("clean", True)
                       or bs.get("commits_ahead_of_main", 0) > 0
                       or ch.get("my_open_prs") or ch.get("prs_needing_my_review"))
    if ch_has_content:
        lines.append("")
        lines.append(f"**CodeHub** -- branch `{ch.get('branch', '')}`")
        if not bs.get("clean", True):
            files = bs.get("dirty_files") or []
            lines.append(f"  - Working tree: **dirty** ({len(files)} file(s): {', '.join(files[:3])}{'...' if len(files) > 3 else ''})")
        if bs.get("commits_ahead_of_main", 0) > 0 and not ch.get("my_open_prs"):
            # #35: commit-only pipeline — committed work auto-integrates to the
            # integration branch. Ahead-of-main with no PR is the NORMAL state; do NOT
            # nag to open a PR (the tool is not surfaced and PR-mode is dead).
            lines.append(f"  - {bs['commits_ahead_of_main']} commit(s) ahead — will auto-integrate (no PR needed)")
        for pr in ch.get("my_open_prs") or []:
            lines.append(f"  - Your open PR {pr['id']} -- {pr.get('merge_state', 'unknown')} ({pr.get('approvals_received', 0)}/{pr.get('approvals_needed', 0)} approvals)")
        if ch.get("prs_needing_my_review"):
            lines.append(f"  - PRs needing your review ({len(ch['prs_needing_my_review'])}):")
            for pr in ch["prs_needing_my_review"]:
                lines.append(f"    - {pr['pr_id']} by {pr.get('author', '?')} ({pr.get('files_changed_count', 0)} files)")
            lines.append(f"      -> `codehub_get_diff(pr_id)` then `codehub_review_pr(...)`")

    ah = pulse.get("registryhub") or {}
    ah_has_content = (ah.get("my_endpoints_with_failed_tests")
                       or ah.get("my_consumed_endpoints_with_breaking_changes")
                       or ah.get("api_reviews_pending_my_decision")
                       or ah.get("my_stale_pending_consumers"))
    if ah_has_content:
        lines.append("")
        lines.append("**RegistryHub**")
        for ep in ah.get("my_endpoints_with_failed_tests") or []:
            ev = ep.get("evidence", {})
            lines.append(f"  - Your endpoint has **FAILED** contract test: {ep['id']} (evidence: {ev})")
        for br in ah.get("my_consumed_endpoints_with_breaking_changes") or []:
            removed = br.get("removed_response_fields") or []
            type_changed = br.get("type_changed_fields") or []
            details = []
            if removed:
                details.append(f"removed_response_fields={removed}")
            if type_changed:
                details.append(f"type_changed_fields={type_changed}")
            lines.append(f"  - BREAKING CHANGE on endpoint you consume: {br['endpoint_id']} ({'; '.join(details) or 'see details'}) -- your file: {br.get('my_file', '?')}")
        for rv in ah.get("api_reviews_pending_my_decision") or []:
            lines.append(f"  - API review pending your decision: {rv['review_id']} for {rv['endpoint_id']}")
        for sp in ah.get("my_stale_pending_consumers") or []:
            mins = (sp.get("age_seconds") or 0) // 60
            lines.append(
                f"  - Pending consumer waiting on {sp.get('endpoint_id')} "
                f"for {mins}m (file: {sp.get('file_path')}) — nudge the "
                f"producer or remove the dependency."
            )

    wh = pulse.get("workhub") or {}
    wh_has_content = (wh.get("tasks_assigned_to_me_pending")
                       or wh.get("tasks_in_progress_by_me")
                       or wh.get("mentions_unread")
                       or wh.get("plans_i_own"))
    if wh_has_content:
        lines.append("")
        lines.append("**WorkHub**")
        if wh.get("tasks_assigned_to_me_pending"):
            lines.append(f"  - {len(wh['tasks_assigned_to_me_pending'])} tasks pending assigned to you:")
            for t in wh["tasks_assigned_to_me_pending"]:
                lines.append(f"    - [{t.get('priority', 'normal').upper()}] {t.get('id', '?')} \"{t.get('title', '')}\"")
        if wh.get("tasks_in_progress_by_me"):
            lines.append(f"  - {len(wh['tasks_in_progress_by_me'])} tasks in progress")
        if wh.get("plans_i_own"):
            for p in wh["plans_i_own"]:
                lines.append(f"  - You own plan {p['id']} ({p.get('tasks_completed', 0)}/{p.get('tasks_total', 0)} done)")
        if wh.get("mentions_unread"):
            lines.append(f"  - {len(wh['mentions_unread'])} unread @mentions:")
            for m in wh["mentions_unread"]:
                lines.append(f"    - from {m.get('from', '?')} on {m.get('resource_id', '?')}: \"{m.get('body', '')[:60]}\"")

    eh = pulse.get("eventhub") or {}
    eh_has_content = eh.get("top_unread") or any((eh.get("unread_count_by_priority") or {}).values())
    if eh_has_content:
        lines.append("")
        counts = eh.get("unread_count_by_priority") or {}
        summary = " ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)
        lines.append(f"**EventHub** -- Inbox unread by priority ({summary or 'none'})")
        for e in eh.get("top_unread") or []:
            lines.append(f"  - Top: {e['source_hub']}/{e['event_type']} {e.get('resource_id', '')}")

    assigned_bugs = pulse.get("assigned_bugs") or []
    if assigned_bugs:
        lines.append("")
        lines.append("## ASSIGNED BUGS")
        for bug in assigned_bugs:
            meta = bug.get("metadata") or {}
            severity = meta.get("severity", "P3")
            title = bug.get("title", "")
            task_id = bug.get("id", "")
            lines.append(f"- [{severity}] {title} ({task_id})")

    open_bug_queue = pulse.get("open_bug_queue") or []
    if open_bug_queue:
        lines.append("")
        lines.append("## OPEN BUG QUEUE")
        for bug in open_bug_queue:
            meta = bug.get("metadata") or {}
            severity = meta.get("severity", "P3")
            title = bug.get("title", "")
            task_id = bug.get("id", "")
            bug_state = meta.get("bug_state", "open")
            lines.append(f"- [{severity}] {title} ({task_id}) — {bug_state}")

    ready_tasks = pulse.get("ready_tasks") or []
    if ready_tasks:
        lines.append("")
        lines.append("## YOUR TASK QUEUE")
        for t in ready_tasks:
            meta = t.get("metadata") or {}
            priority = meta.get("priority", "P2")
            title = t.get("title", "")
            task_id = t.get("id", "")
            lines.append(f"- [{priority}] {title} ({task_id})")

    blocked_tasks = pulse.get("blocked_tasks") or []
    if blocked_tasks:
        lines.append("")
        lines.append("## BLOCKED ON OTHERS")
        for t in blocked_tasks:
            meta = t.get("metadata") or {}
            priority = meta.get("priority", "P2")
            title = t.get("title", "")
            task_id = t.get("id", "")
            dep_ids = [d for d in (t.get("depends_on") or []) if d != task_id]
            dep_str = ", ".join(dep_ids[:3]) if dep_ids else "(unknown)"
            lines.append(
                f"- [{priority}] {title} ({task_id}) — waiting on: {dep_str}"
            )

    sa = pulse.get("self_audit") or {}
    if sa.get("api_drift") or sa.get("ui_drift"):
        lines.append("")
        lines.append("## SELF-AUDIT (hub drift)")
        api_drift = sa.get("api_drift")
        if api_drift:
            sample = ", ".join(api_drift.get("code_paths_sample") or [])
            count = api_drift.get("code_paths_count", 0)
            lines.append(
                f"- You've written {count} backend/route file(s) "
                f"(e.g. {sample}) but RegistryHub shows **0 endpoints owned by you**. "
                f"Call `registryhub_register_endpoint(...)` for each route before finish()."
            )
        ui_drift = sa.get("ui_drift")
        if ui_drift:
            sample = ", ".join(ui_drift.get("code_paths_sample") or [])
            count = ui_drift.get("code_paths_count", 0)
            lines.append(
                f"- You've written {count} page/component file(s) "
                f"(e.g. {sample}) but RegistryHub shows **0 ui_pages owned by you**. "
                f"Call `registryhub_register_ui_page(...)` for each."
            )

    stale = pulse.get("stale_tasks") or []
    if stale:
        lines.append("")
        lines.append("## STALE TASKS (assignee not making progress)")
        for t in stale:
            reason = t.get("stale_reason", "?")
            age_min = int(t.get("age_seconds") or 0) // 60
            lines.append(
                f"- [{reason}] {t.get('id', '?')} \"{t.get('title', '')}\" "
                f"→ {t.get('assignee')} (age={age_min}m)"
            )
        lines.append(
            "  -> nudge via `send_message(to_agent=<assignee>, ...)`, "
            "or reassign via `workhub_create_task` to another agent."
        )

    latest_run = pulse.get("latest_run")
    if latest_run:
        lines.append("")
        lines.append("## RECENT RUN")
        lines.append(
            f"- {latest_run.get('id')}: status={latest_run.get('status')}, "
            f"branch={latest_run.get('branch')}, "
            f"fail_count={latest_run.get('fail_count', 0)}"
        )

    return "\n".join(lines)
