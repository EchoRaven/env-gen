"""PR3.2 — per-(stage, tool) precondition guard registry.

A precondition is a callable that runs in the dispatch site
``_execute_tool`` BEFORE a tool's ``execute`` method. It returns
``None`` when the call is allowed; returns an error string when the
call must be blocked. The engine wraps the string in
``ToolResult(success=False, ...)`` so the LLM sees the failure plus the
corrective action in-context — replacing "DO NOT call X until Y" prose
with an engine-enforced sequence guard (the user's
"我不太希望prompt里面出现DO not use" feedback).

Lookup is by string id, declared on agents_config.yaml as
``stage_tool_preconditions.<stage>.<tool>: <id>``. Unknown ids are
rejected at agent construction (``ConfigurableAgent.__init__``), not at
dispatch — a yaml typo fails fast at start-up, never silently no-ops at
runtime.
"""
from __future__ import annotations

import logging as _logging
from typing import Any, Callable, Dict, Optional

_log = _logging.getLogger(__name__)


PreconditionFn = Callable[[Any, str, Dict[str, Any]], Optional[str]]


# Terminal endpoint statuses — finish does NOT block on these. Loop B
# iter-3 ⑭: ``deprecated`` is a real reachable terminal status
# (registryhub.py:425/643, set by registryhub_deprecate_endpoint); a deprecated
# endpoint can never transition to ``implemented``, so blocking on it
# is a permanent finish-wedge with a directed error the LLM cannot
# satisfy. Add to the terminal set, not the blocking set.
_FINISH_TERMINAL_STATUSES = frozenset({"implemented", "deprecated"})


def _agent_owning_lane(agent: Any) -> Optional[str]:
    """Return the agent's owning-lane identity for endpoint
    provider-matching. Prefers ``_config_key`` (the profile id, stable
    across spawned workers) over ``agent_id`` (unique per instance,
    e.g. ``backend_worker_abc123``)."""
    cfg_key = getattr(agent, "_config_key", None)
    if cfg_key:
        return str(cfg_key)
    ag_id = getattr(agent, "agent_id", None)
    return str(ag_id) if ag_id else None


def kickoff_endpoints_implemented(
    agent: Any,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> Optional[str]:
    """Block ``finish`` until every endpoint OWNED BY THIS AGENT'S LANE
    reaches a terminal status (``implemented`` or ``deprecated``).

    Reads ``agent._hubs.registryhub.get_endpoints()`` and filters by the
    endpoint's ``provider`` field (the owning lane). Returns an error
    string naming the pending endpoints and the action that resolves
    them. Vacuously passes when:
      - RegistryHub is empty (e.g. during the kickoff stage before
        ``finalize_kickoff`` has run);
      - the agent's lane owns no endpoints in this milestone;
      - all owned endpoints are at a terminal status.

    Smoke #28's wedge — backend wrote 8 files in the correct worktree
    but called ``finish`` with 4 endpoints still at ``status='defined'``
    — is exactly the case this guard catches: the LLM sees a directed
    error message and learns the right sequence in-context.

    Loop B iter-3 ⑮ (lane-scoping): the predicate filters by
    ``ep.provider == agent._config_key`` so backend's finish only
    blocks on endpoints backend owns. A frontend lane completing
    finish() with backend's endpoints still at 'defined' is the
    expected case (frontend doesn't own backend's contracts) and now
    passes through.

    Milestone-scoping (Loop B ⑮'s M2+ concern) is a follow-up: today
    endpoints carry no ``milestone_index`` metadata at registration,
    so we can't filter by current milestone yet. When the M2 loop
    lands and finalize_kickoff stamps ``milestone_index`` on each
    registered endpoint, add a ``milestone_index == agent.current_M``
    filter below. M1-only runs are unaffected by the missing filter.
    """
    hubs = getattr(agent, "_hubs", None)
    if hubs is None:
        return None
    registryhub = getattr(hubs, "registryhub", None)
    if registryhub is None or not hasattr(registryhub, "get_endpoints"):
        return None
    lane = _agent_owning_lane(agent)
    if not lane:
        return None
    # STATUS AUTO-SYNC (env-gated ENVGEN_SYNC_STATUS_AT_FINISH, default-off): the
    # framework PROJECTS working CRUD handlers for every contract endpoint into the
    # skeleton main.py the lane branches from, but the CODE-TRUTH audit that flips
    # defined→implemented (backend_audit.sync_endpoint_statuses) only runs post-merge
    # in the heal pipeline. So during the lane's OWN phase every projected endpoint
    # sits at 'defined' even though its route is already SERVED in the worktree, and
    # this gate then wrongly orders the lane to "write the route" for code the
    # framework owns and the lane cannot touch (main.py is framework-owned). When the
    # flag is set, run that SAME audit against the lane's worktree HERE so served
    # (projected OR custom_routes) routes flip to 'implemented' first — the gate then
    # blocks only on genuinely-unserved endpoints (a missing custom route / a contract
    # path that no served route matches), which is exactly what the lane can act on.
    import os as _os
    if _os.environ.get("ENVGEN_SYNC_STATUS_AT_FINISH"):
        _wt = getattr(agent, "_worktree_dir", None)
        if _wt:
            try:
                from ...runtime.backend_audit import sync_endpoint_statuses
                sync_endpoint_statuses(_wt, registryhub)
            except Exception:
                pass
    endpoints = registryhub.get_endpoints() or {}
    # PROPOSAL #30 S1: skip the FRAMEWORK-OWNED fixed surface (auth/oauth/infra/spine)
    # via the canonical lifecycle.is_business — the SAME predicate
    # all_business_endpoints_implemented (the delivery driver) uses. Without this the
    # STATUS gate counted the framework's tenant control-plane (control_plane.py,
    # kind='infra', registered provider='backend') against the backend → it was told
    # to "implement" framework endpoints it neither owns nor can write → deadlock
    # (the code gate already skips these kinds, but it calls THIS gate as Layer 1 and
    # returns its block before its own kind-skip is reached). Using is_business (not a
    # copied kind literal) also covers kind='oauth' — which the code gate's inline set
    # misses — and is metadata-aware.
    from ...runtime.lifecycle import is_business
    pending = []
    for ep_id, ep in endpoints.items():
        if not isinstance(ep, dict):
            continue
        provider = ep.get("provider")
        if provider and provider != lane:
            continue
        if not is_business(ep):
            continue
        if ep.get("status") not in _FINISH_TERMINAL_STATUSES:
            method = ep.get("method") or "?"
            path = ep.get("path") or ep_id
            pending.append(f"{method} {path}")
    if not pending:
        return None
    pending.sort()
    if _os.environ.get("ENVGEN_SYNC_STATUS_AT_FINISH"):
        # Auto-sync already flipped every SERVED route to 'implemented', so a
        # still-pending endpoint genuinely has no served handler. Tell the lane the
        # truth about the projection model — do NOT send it to rewrite main.py.
        return (
            f"finish blocked: {len(pending)} endpoint(s) you own have NO served "
            f"route yet: {pending}. The framework AUTO-PROJECTS a working handler "
            f"for every STANDARD CRUD endpoint in your contract (you do NOT and "
            f"CANNOT write those — main.py is framework-owned), so a still-pending "
            f"endpoint is one of: (a) a NON-standard endpoint (action verb like "
            f"/x/{{id}}/send, custom search, a computed/aggregate result the "
            f"projector can't express) — implement it in app/backend/custom_routes.py "
            f"(an APIRouter named `router`); or (b) a CONTRACT gap — the registered "
            f"method/path matches no served route (e.g. its table was never "
            f"registered, or the path is wrong), so FIX THE CONTRACT "
            f"(registryhub_register_table / re-register the endpoint at the correct "
            f"path). Do NOT re-implement standard CRUD."
        )
    return (
        f"finish blocked: {len(pending)} endpoint(s) you own are not "
        f"yet implemented: {pending}. For EACH: (1) WRITE the FastAPI route "
        f"handler + its DB logic in your backend worktree using the `write`/"
        f"`edit` tools (the route MUST exist in code — do not skip this), THEN "
        f"(2) registryhub_register_endpoint(method=..., path=..., "
        f"status='implemented'). Registering as implemented WITHOUT writing the "
        f"route leaves the app non-functional and will be rejected — write the "
        f"code first."
    )


def _require_skill_consulted(required_skill: str, tool_name: str, agent: Any) -> Optional[str]:
    """Block ``tool_name`` until ``required_skill`` is in
    ``agent._consulted_skills`` (populated by L3a record_skill_consult when
    the agent calls get_skill). Returns a directed error the LLM can act on
    in-context — the skill-mandatory-trigger L2 lever, implemented via the
    existing precondition mechanism rather than a separate gate policy."""
    consulted = getattr(agent, "_consulted_skills", None) or set()
    if required_skill in consulted:
        return None
    # SATISFIABILITY GUARD (bsb900gpt run): the gate tells the agent to "call
    # get_skill(...)", but if THIS agent has no get_skill in its tool surface the
    # instruction is IMPOSSIBLE — the gate is unsatisfiable and the gated tool
    # loops until action rounds are exhausted. That is exactly what killed the
    # run: the orchestrator's delivery toolset omitted get_skill, so the
    # release-readiness gate blocked deliver_project forever ("I don't have
    # access to the get_skill tool" ×N → rounds exhausted → no delivery).
    # Blocking forever is strictly worse than proceeding, and the real safety
    # gates (delivery_phase_reached + the deterministic delivery gate) still
    # apply. So when get_skill is uncallable, best-effort auto-consult (preserve
    # intent + record it) and let the call through. The nudge is unchanged for
    # agents that CAN consult — they still get the directed "call get_skill" block.
    tools = getattr(agent, "_tool_instances", None)
    if not (tools and "get_skill" in tools):
        if not isinstance(getattr(agent, "_consulted_skills", None), set):
            agent._consulted_skills = set()
        agent._consulted_skills.add(required_skill)
        _log.warning(
            "[precondition] %s gated on '%s' skill-consult but agent %r has no "
            "get_skill tool — auto-consulting to keep the gate satisfiable "
            "(prevents the deliver_project deadlock that killed run bsb900gpt).",
            tool_name, required_skill, getattr(agent, "agent_id", "?"),
        )
        return None
    return (
        f"{tool_name} blocked: consult the `{required_skill}` skill first. "
        f"Call get_skill(name='{required_skill}') and follow it, then retry "
        f"{tool_name}."
    )


import re as _re
from pathlib import Path as _Path

# Matches a FastAPI route path literal from either a method decorator
# (``@router.post("/posts")`` / ``@app.get("/api/feed")``) or an
# ``APIRouter(prefix="/api/posts")`` declaration. Group 1 is the path literal.
_ROUTE_PATH_RE = _re.compile(
    r"""(?:@\s*\w+\s*\.\s*(?:get|post|put|patch|delete|api_route|websocket)\s*\(|"""
    r"""APIRouter\s*\([^)]*?prefix\s*=)\s*["']([^"']+)["']""",
    _re.IGNORECASE,
)

def _endpoint_resource_token(path: Any) -> Optional[str]:
    """Last non-parameter path segment, lowercased — the endpoint's distinctive
    resource token (``/api/posts/{id}/likes`` → ``likes``)."""
    segs = [
        s for s in str(path or "").split("/")
        if s and not (s.startswith("{") or s.startswith(":"))
    ]
    return segs[-1].lower() if segs else None


def _collect_source_route_tokens(root: "_Path") -> set:
    """Set of path segments that appear in route decorators / APIRouter prefixes
    across the lane's source (lowercased, params dropped). Empty on any error so
    the gate degrades to vacuous-pass rather than wedging the lane."""
    tokens: set = set()
    try:
        files = list(root.rglob("*.py"))
    except Exception:
        return tokens
    for pf in files:
        sp = str(pf)
        if "__pycache__" in sp:
            continue
        try:
            text = pf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in _ROUTE_PATH_RE.finditer(text):
            for seg in m.group(1).split("/"):
                seg = seg.strip().lower()
                if seg and not (seg.startswith("{") or seg.startswith(":")):
                    tokens.add(seg)
    return tokens


def endpoints_implemented_with_code(
    agent: Any,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> Optional[str]:
    """``finish`` gate: every endpoint this lane owns must be (1) at a terminal
    status AND (2) actually backed by route code in the lane's source.

    Layer 1 reuses :func:`kickoff_endpoints_implemented` (status gate). Layer 2
    closes the GAMING loophole that gutted Instagram run #6: the backend marked
    all 38 endpoints ``implemented`` via 58 ``registryhub_register_endpoint`` calls
    with ZERO code writes — the status gate trusts the LLM-asserted registryhub
    status, so the lane escaped implementation without authoring a single route,
    leaving an app with no business logic that can only fail validation.
    'implemented' must be backed by code, not assertion (charter §8).

    Layer 2 scans the lane's worktree for route decorators / APIRouter prefixes
    and requires each owned endpoint's distinctive resource token (its last
    non-param path segment, e.g. ``feed``/``likes``/``followers``) to appear in
    some route literal. Matching is deliberately LENIENT (token, not full path)
    so router-prefix splitting + path-format variance never FALSE-blocks honest
    code; it only fires on the egregious no-route case. Vacuous-pass when the
    worktree can't be resolved (don't wedge).
    """
    # PROPOSAL #58: skip the whole "endpoints implemented + code present" demand during the
    # KICKOFF turn (lane only declares; no write tools yet) — both Layer 1 (status) and
    # Layer 2 (code-presence) are unsatisfiable then, so a kickoff finish must not block.
    if getattr(agent, "_active_phase", None) == "kickoff":
        return None
    # Satisfiability backstop for #58 (run bsb900gpt predated #58 and still wedged):
    # this gate's corrective action is "WRITE the route + registryhub_register_endpoint".
    # If the lane currently holds NEITHER tool, that instruction is impossible and blocking
    # only wedges finish — regardless of how _active_phase happens to be set. Mirrors
    # _require_skill_consulted's uncallable-tool escape. The implementation lane grants both
    # (implementation:action allowlist), so the real gate still fires there unchanged.
    _tools = getattr(agent, "_tool_instances", None) or {}
    if not ("write" in _tools and "registryhub_register_endpoint" in _tools):
        return None
    status_block = kickoff_endpoints_implemented(agent, tool_name, tool_args)
    if status_block is not None:
        return status_block

    hubs = getattr(agent, "_hubs", None)
    registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
    if registryhub is None or not hasattr(registryhub, "get_endpoints"):
        return None
    lane = _agent_owning_lane(agent)
    if not lane:
        return None
    wt = getattr(agent, "_worktree_dir", None)
    if not wt:
        return None
    root = _Path(wt)
    if not root.exists():
        return None

    endpoints = registryhub.get_endpoints() or {}
    route_tokens = _collect_source_route_tokens(root)

    from ...runtime.lifecycle import is_business  # PROPOSAL #30 S1 (canonical filter)
    missing = []
    for ep_id, ep in endpoints.items():
        if not isinstance(ep, dict):
            continue
        provider = ep.get("provider")
        if provider and provider != lane:
            continue
        # PROPOSAL #30 S1: skip the framework-owned fixed surface via the canonical
        # lifecycle.is_business (covers auth/oauth/infra/spine + metadata-nested kind)
        # — converged with the status gate above + the delivery driver, replacing the
        # ad-hoc kind literal that missed kind='oauth'.
        if not is_business(ep):
            continue
        if ep.get("status") not in _FINISH_TERMINAL_STATUSES:
            continue  # status layer already handled non-terminal
        token = _endpoint_resource_token(ep.get("path") or ep_id)
        if token and token not in route_tokens:
            method = (ep.get("method") or "?").upper()
            missing.append(f"{method} {ep.get('path') or ep_id}")

    if not missing:
        return None
    missing.sort()
    shown = missing[:8]
    more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
    return (
        f"finish blocked: {len(missing)} endpoint(s) are marked 'implemented' "
        f"in RegistryHub but have NO route handler in your source code: "
        f"{shown}{more}. Marking endpoints implemented without writing the "
        f"FastAPI route + logic leaves the app non-functional (validation will "
        f"404). Write the actual route handler(s) (e.g. "
        f"@router.<method>(\"<path>\") + DB logic) in your backend worktree, "
        f"THEN finish."
    )


def orchestrator_ask_cap(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """Bound the orchestrator's ``ask_agent`` drift (FIX #28).

    instagram-core froze after the orchestrator asked ~28 questions in a
    no-progress question/answer ping-pong that DERAILED the implementing backend
    (it kept answering instead of writing routes — it managed only 1 of 8
    endpoints) and ended in a coordination deadlock. Interrogation is not the
    coordination signal — the deterministic validate/deliver drivers + lane
    ``agent_status`` events are. Allow asks freely WHILE the run is progressing
    (implemented-endpoint count rising); block once the orchestrator has asked
    > THRESHOLD times with NO new endpoint implemented (a stall), redirecting it
    to let the lanes work. Self-resets on real progress, so it never wedges a
    healthy run.
    """
    THRESHOLD = 15
    registryhub = getattr(getattr(agent, "_hubs", None), "registryhub", None)
    cur = 0
    try:
        from ...runtime.lifecycle import business_endpoints
        eps = registryhub.get_endpoints() if (registryhub and hasattr(registryhub, "get_endpoints")) else {}
        cur = sum(
            1 for e in business_endpoints(eps or {})
            if isinstance(e, dict) and e.get("status") == "implemented"
        )
    except Exception:
        cur = 0
    last = getattr(agent, "_ask_cap_last_impl", -1)
    if cur > last:
        agent._ask_cap_last_impl = cur
        agent._ask_cap_count = 0
    n = getattr(agent, "_ask_cap_count", 0) + 1
    agent._ask_cap_count = n
    if n <= THRESHOLD:
        return None
    return (
        f"ask_agent paused: you've asked {n} questions with no new endpoint "
        f"implemented since. STOP interrogating the lanes — repeated questions "
        f"derail their implementation and stall the run. LET THEM WORK: the "
        f"framework validates + delivers automatically as endpoints land. Use "
        f"check_inbox for status; ask again only after delivery progress."
    )


def release_readiness_consulted(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """Gate delivery on having consulted the release-readiness skill."""
    return _require_skill_consulted("release-readiness", tool_name, agent)


def api_contract_guard_consulted(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """Gate PR-open on having consulted the api-contract-guard skill."""
    return _require_skill_consulted("api-contract-guard", tool_name, agent)


def frontend_canonical_root(
    agent: Any,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> Optional[str]:
    """Block ``finish`` when the frontend built its app at the WRONG ROOT
    (repo-root ``./src``) instead of the canonical ``app/frontend/src`` that the
    docker build (``build: ../app/frontend``) and the delivery gate use.

    Live (run #5): the lane authored its pages via ``execute_bash`` heredocs to
    cwd-relative ``src/pages`` — bash bypasses the write-tool path routing — so
    ``app/frontend/src/pages`` stayed an empty shell AND most pages were left
    untracked (lost at merge). The delivery-time relocator only catches the
    committed subset at ``output_dir``; enforcing HERE puts the fix in the
    model's face immediately (mirrors the backend's
    ``endpoints_implemented_with_code`` gate).

    Tight trigger — the exact heuristic the delivery relocator uses: fires ONLY
    when the repo-root tree is MATERIALLY richer than the canonical one
    (>= 2 pages and strictly more). A frontend that built correctly under
    ``app/frontend/`` has an empty/absent ``./src`` → passes straight through,
    so this never wedges a correct finish. Best-effort; never raises.
    """
    try:
        ws = getattr(agent, "workspace", None)
        base = getattr(ws, "base_dir", None)
        if not base:
            return None
        from pathlib import Path as _P
        base = _P(base)

        def _pages(p: "_P") -> int:
            d = p / "pages"
            if not d.is_dir():
                return 0
            return len(list(d.glob("*.jsx")) + list(d.glob("*.tsx")))

        root_pages = _pages(base / "src")
        canon_pages = _pages(base / "app" / "frontend" / "src")
        if root_pages >= 2 and root_pages > canon_pages:
            return (
                f"finish blocked: your frontend pages are at the REPO ROOT "
                f"(./src/pages = {root_pages} page(s)) but docker builds and the "
                f"delivery gate use ONLY app/frontend/src (currently {canon_pages} "
                f"page(s) — a blank shell), so your app is INVISIBLE to delivery. "
                f"Re-create each page UNDER app/frontend/ with the `write`/`edit` "
                f"tools, using paths that START WITH `app/frontend/src/` (e.g. "
                f"write app/frontend/src/pages/Home.jsx, app/frontend/src/App.jsx). "
                f"Do NOT use execute_bash heredocs to ./src — bash writes bypass "
                f"path routing (wrong root) and leave files untracked (lost at "
                f"merge). Then delete the stray repo-root ./src tree."
            )
        return None
    except Exception:
        return None


def kickoff_finalized_signal(hubs: Any, agent: Any = None) -> bool:
    """PROPOSAL #28 (F0) — GATE-SAFE "has kickoff finalized?" predicate.

    True once kickoff has produced contract surface, from the SAME signals
    ``KickoffBootstrapGate`` uses: the agent's sticky ``_kickoff_bootstrapped`` flag,
    OR RegistryHub has any endpoint, OR WorkHub has any task. The flag ALONE is
    insufficient for the ORCHESTRATOR, which has no KickoffBootstrapGate (its flag is
    never set) — #24's flag-only check therefore mis-classified the orchestrator as
    "in KICKOFF" forever (a latent permanent over-block). The hub read fixes that.

    Gate-safe — unlike the DISPLAY-only ``hub_pulse.current_run_phase`` (which gates
    must NOT call): the hub stores are append-only within a run (``deprecate_endpoint``
    does a status ``.set()``, not a delete), so this signal is MONOTONIC and cannot
    invert a gate decision once True (the #24/#25 subtlety-1 concern that forbade the
    display helper does not apply to a fresh predicate over these monotonic signals)."""
    if getattr(agent, "_kickoff_bootstrapped", False):
        return True
    try:
        rh = getattr(hubs, "registryhub", None)
        if rh is not None and hasattr(rh, "_endpoints") and rh._endpoints.value():
            return True
        if rh is not None and hasattr(rh, "get_endpoints") and rh.get_endpoints():
            return True
    except Exception:
        pass
    try:
        wh = getattr(hubs, "workhub", None)
        if wh is not None and hasattr(wh, "list_tasks") and wh.list_tasks():
            return True
    except Exception:
        pass
    return False


def validation_ready_signal(hubs: Any, agent: Any = None) -> bool:
    """PRE-LAUNCH AUDIT F1/F5 — STICKY "is the run VALIDATION-ready?" predicate.

    True once every business endpoint is implemented (the IMPL→VALIDATION boundary the
    delivery driver + the verifier's validation trigger already use). LATCHED per-agent
    (``_validation_ready_latched``) so it cannot REGRESS mid-validation if a late
    ``defined`` endpoint is registered — ``all_business_endpoints_implemented`` is NOT
    monotonic (audit F5), so a fresh read alone could re-block a tool after validation
    began; the latch makes it sticky like ``_kickoff_bootstrapped``. Never raises."""
    if getattr(agent, "_validation_ready_latched", False):
        return True
    try:
        rh = getattr(hubs, "registryhub", None)
        if rh is None or not hasattr(rh, "get_endpoints"):
            return False
        from ...runtime.lifecycle import all_business_endpoints_implemented
        if all_business_endpoints_implemented(rh.get_endpoints() or {}):
            if agent is not None:
                try:
                    agent._validation_ready_latched = True
                except Exception:
                    pass
            return True
    except Exception:
        pass
    return False


def delivery_phase_reached(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """PRE-LAUNCH AUDIT F1 — block the orchestrator's delivery/validation LLM tools
    (deliverability_check / run_start / run_validation) until the run is VALIDATION-ready.

    They were gated only on ``kickoff_finalized``, which opens the instant
    finalize_kickoff registers endpoints — i.e. all through IMPLEMENTATION, where there
    is nothing built to validate/deliver. So the orchestrator polled deliverability_check
    ×48 (run #28/#31) and fired run_start = ``docker compose up`` against a half-built
    tree. Gate them on the STICKY validation-ready signal instead. The DETERMINISTIC
    framework validate/deliver drivers run on a SEPARATE run()-loop path and never call
    these LLM tools, so delivery itself is unaffected. Never raises."""
    if validation_ready_signal(getattr(agent, "_hubs", None), agent):
        return None
    return (
        f"{tool_name} is unavailable until VALIDATION: not every business endpoint is "
        f"implemented yet, so there is nothing to validate or deliver. During "
        f"IMPLEMENTATION your job is to COORDINATE the lanes (answer questions, dispatch "
        f"failing checks, keep work flowing) — the framework validates + delivers "
        f"AUTOMATICALLY once every endpoint is implemented; you do not call {tool_name} "
        f"to trigger it."
    )


def release_phase_and_readiness(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """#36-cluster (run #35): deliver_project / report_completion require BOTH the
    VALIDATION phase (delivery_phase_reached — every business endpoint implemented) AND a
    release-readiness skill consult. They were only skill-gated (release_readiness_consulted),
    so the orchestrator called deliver_project mid-KICKOFF ("Round 10 … finalize this run")
    — harmless (the deterministic delivery gate blocked the real release) but a wasted-round
    loop that ended its wake prematurely. Phase gate FIRST so premature delivery during
    kickoff/implementation is impossible, not merely discouraged. Never raises."""
    phase_block = delivery_phase_reached(agent, tool_name, tool_args)
    if phase_block:
        return phase_block
    return release_readiness_consulted(agent, tool_name, tool_args)


def kickoff_finalized(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """PROPOSAL #24 — block premature delivery/validation tools during KICKOFF.

    The orchestrator's prompt calls ``deliverability_check`` "the critical first
    step", so its resident-loop LLM fires ``deliverability_check`` / ``run_start``
    / ``run_validation`` immediately — DURING kickoff, before any contract is
    declared or code exists (smoke-notes run #3 kickoff window: deliverability_check
    ×10, run_start ×8, each returning a meaningless "no successful run / dead
    artifacts" and emitting ``run_completed`` that woke the debugger into spurious
    ``bug_create`` ×6). These actions are meaningless until kickoff is finalized.

    KICKOFF = ``not kickoff_finalized_signal(...)`` (PROPOSAL #28 F1): uses the
    GATE-SAFE hub-derived predicate (RegistryHub endpoint OR WorkHub task OR the agent
    flag) — NOT the agent flag alone. The orchestrator has no KickoffBootstrapGate, so
    its ``_kickoff_bootstrapped`` is never set; the #24 flag-only check therefore
    PERMANENTLY blocked the orchestrator's deliverability_check/run_start/run_validation
    even post-kickoff (a latent over-block + wasted rounds — NOT a delivery breaker, as
    delivery is driven deterministically by the run() loop, never by these LLM tools).
    The hub read unblocks them once the contract exists. Keyed under the bare ``action``
    stage so it fires in the orchestrator's RESIDENT coordination loop where
    ``_active_phase`` is ``None``. The deterministic framework drivers run on a SEPARATE
    run()-loop path and never call these LLM tools, so they are unaffected. Never raises."""
    if kickoff_finalized_signal(getattr(agent, "_hubs", None), agent):
        return None
    return (
        f"{tool_name} is unavailable during KICKOFF: kickoff is not finalized "
        f"(no endpoints declared / no tasks assigned yet), so there is nothing to "
        f"validate or deliver — a run now returns a meaningless 'no successful run' "
        f"and wakes the debugger into spurious bugs. During kickoff your job is to "
        f"chair the meeting and drive the lanes to declare the full contract "
        f"(endpoints/tables/ui_pages/chains) and reach finalize_kickoff. The framework "
        f"runs validation + delivery AUTOMATICALLY once endpoints are implemented — you "
        f"do not call {tool_name} to trigger it."
    )


def validation_phase_reached(agent: Any, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
    """PROPOSAL #24 — block the debugger filing/triaging bugs before VALIDATION.

    The debugger wakes on ``run_completed``. When the orchestrator fires a premature
    run during kickoff/early-implementation (see :func:`kickoff_finalized`), the
    resulting ``run_completed`` wakes the debugger, which files ``bug_create`` /
    ``bug_triage`` about an empty validation — there is no implemented code to debug
    yet (smoke-notes run #3 kickoff window: bug_create ×6, bug_triage ×4).
    ``KickoffBootstrapGate`` on the debugger suppresses the pre-finalize WAKEUP; this
    gate additionally blocks the bug TOOLS until the IMPL→VALIDATION boundary the
    deterministic drivers use, so a ``run_completed`` fired during early
    IMPLEMENTATION (post-finalize, pre-impl) is also caught (review condition 1).

    VALIDATION = ``all_business_endpoints_implemented(registryhub.get_endpoints())``
    — the SAME predicate ``framework_validation`` and the delivery driver gate on
    (review Q2). Once a real validation run can occur, a genuine failing run
    legitimately wakes the debugger and these tools open. Hub-derived; never raises."""
    try:
        registryhub = getattr(getattr(agent, "_hubs", None), "registryhub", None)
        if registryhub is None or not hasattr(registryhub, "get_endpoints"):
            return None  # can't determine phase → don't block
        from ...runtime.lifecycle import all_business_endpoints_implemented
        eps = registryhub.get_endpoints() or {}
        if eps and all_business_endpoints_implemented(eps):
            return None
        return (
            f"{tool_name} is unavailable before VALIDATION: not all business "
            f"endpoints are implemented yet, so there is no working app to debug — a "
            f"run that completes now reflects an empty/partial build, not a real "
            f"defect. The framework validates automatically once every endpoint is "
            f"implemented; a genuine failing validation run will then wake you and "
            f"{tool_name} will be available. Until then, monitor via check_inbox."
        )
    except Exception:
        return None


PRECONDITION_REGISTRY: Dict[str, PreconditionFn] = {
    "kickoff_endpoints_implemented": kickoff_endpoints_implemented,
    "endpoints_implemented_with_code": endpoints_implemented_with_code,
    "frontend_canonical_root": frontend_canonical_root,
    "orchestrator_ask_cap": orchestrator_ask_cap,
    "release_readiness_consulted": release_readiness_consulted,
    "release_phase_and_readiness": release_phase_and_readiness,
    "api_contract_guard_consulted": api_contract_guard_consulted,
    # PROPOSAL #24 — run-phase hygiene (EXTEND existing hub-derived gates):
    "kickoff_finalized": kickoff_finalized,
    "validation_phase_reached": validation_phase_reached,
    # PRE-LAUNCH AUDIT F1 — orchestrator delivery/validation tools gate on validation-ready:
    "delivery_phase_reached": delivery_phase_reached,
}


def resolve_precondition(name: str) -> Optional[PreconditionFn]:
    return PRECONDITION_REGISTRY.get(name)
