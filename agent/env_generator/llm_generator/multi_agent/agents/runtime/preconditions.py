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

from typing import Any, Callable, Dict, Optional


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
    endpoints = registryhub.get_endpoints() or {}
    pending = []
    for ep_id, ep in endpoints.items():
        if not isinstance(ep, dict):
            continue
        provider = ep.get("provider")
        if provider and provider != lane:
            continue
        if ep.get("status") not in _FINISH_TERMINAL_STATUSES:
            method = ep.get("method") or "?"
            path = ep.get("path") or ep_id
            pending.append(f"{method} {path}")
    if not pending:
        return None
    pending.sort()
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

    missing = []
    for ep_id, ep in endpoints.items():
        if not isinstance(ep, dict):
            continue
        provider = ep.get("provider")
        if provider and provider != lane:
            continue
        # Only business endpoints carry a UI/business consumer; skip the
        # runtime-owned fixed surface (auth/health/spine) by registered kind.
        kind = (ep.get("kind") or "").lower()
        if kind in ("infra", "auth", "spine", "control", "system"):
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


PRECONDITION_REGISTRY: Dict[str, PreconditionFn] = {
    "kickoff_endpoints_implemented": kickoff_endpoints_implemented,
    "endpoints_implemented_with_code": endpoints_implemented_with_code,
    "frontend_canonical_root": frontend_canonical_root,
    "orchestrator_ask_cap": orchestrator_ask_cap,
    "release_readiness_consulted": release_readiness_consulted,
    "api_contract_guard_consulted": api_contract_guard_consulted,
}


def resolve_precondition(name: str) -> Optional[PreconditionFn]:
    return PRECONDITION_REGISTRY.get(name)
