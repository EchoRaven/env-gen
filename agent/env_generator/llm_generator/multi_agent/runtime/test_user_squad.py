"""Multi-agent test-user squad (2026-06-22, design §3.1/§3.4 + the user directive that the
test-user be built from ConfigurableAgents on the shared tool chain, spawned in MULTIPLES, in
THREE modality forms — api / mcp / browser — each a state machine that predicts then compares).

Instead of one deterministic Playwright script, the orchestrator PLANS a set of user-goal
workflows (from the kickoff user_flows + the registered contract + the milestone's acceptance
criteria), tags each with the MODALITY it exercises (api / mcp / browser), and spawns ONE
specialised test-user agent PER goal — concurrently, in waves — each driving the running app
through its modality's tool chain as its assigned identity (and tenant, for isolation goals).
Defects route back via each agent's bug_create (detect-only); this module just plans, fans out,
and collects completion.

Split into a PURE planner (`plan_test_user_goals` / `build_briefing` — unit-tested without a
runtime) and a defensive async runner (`run_test_user_squad`) that drives the spawn service.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

# modality -> the configurable-agent profile that handles it (agents_config.yaml).
MODALITY_PROFILE = {
    "api": "api_test_user",
    "mcp": "mcp_test_user",
    "browser": "browser_test_user",
}

# bug_create `source` values the three test-user forms file under.
TEST_USER_SOURCES = frozenset(MODALITY_PROFILE.values())

# #625 — NEVER DRIVE A TARGET THAT ISN'T LISTENING.
# The squad spawns one agent per goal and each files its own bugs. When the stack is down every
# agent independently discovers "connection refused" and files it as a product defect: 47 of the
# 555 bugs across 40 runs are connectivity-shaped and 46 of those are P0 — 19 in r121, 15 in
# r137, 8 in r125. They are one environment event reported N times, and the lanes then spend
# real turns triaging them ("False-positive: test-user targeted wrong ports", "Root cause
# resolved: docker stack was not up when test-users ran", "Duplicate: same stack-down root
# cause").
#
# test_user_validation already got this guard in Round 32 — it waits for /health and reports
# ENV_UNAVAILABLE "instead of misdiagnosing the app". The SQUAD, which is what actually files
# the bugs, never did. Same guard, per modality, so a half-up stack only silences the half that
# cannot run.
#
# Deliberately a SOCKET probe, not a filter on bug text: "unreachable" appears in real product
# bugs too (r119's P2 "POST /api/continue-watching returns 404 — endpoint unreachable / route
# not mounted" is genuine), and classifying findings after the fact would suppress those.
_PROBE_DEADLINE_625 = 60.0
_PROBE_INTERVAL_625 = 5.0
# #1202qu: what a COLD boot costs -- `down -v` + build + migrations + seed. The 60s above was
# sized for "is anything there", not for "wait for the stack this squad just leased".
_BOOT_DEADLINE_1202QU = 240.0


def _probe_http_625(url: str, timeout: float = 4.0):
    """ANY status proves the socket serves (404 from a bare root is still 'up'). None = down.
    Module-level so tests can monkeypatch it instead of opening real sockets."""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return getattr(resp, "status", None) or resp.getcode()
    except Exception as exc:
        return getattr(exc, "code", None)  # an HTTPError still means something answered


def targets_reachable_625(ui_base: str, api_base: str, *,
                          deadline: Optional[float] = None) -> Dict[str, bool]:
    """{'ui': bool, 'api': bool} — retried until `deadline` so a slow-starting stack is not
    misreported as down. Returns as soon as both answer; the healthy case costs two probes.

    `deadline` resolves at CALL time, not at def time: a module-level default would bind 60.0
    into the signature, leaving the constant unadjustable and every caller stuck with it."""
    import time as _time
    out = {"ui": False, "api": False}
    end = _time.time() + max(_PROBE_DEADLINE_625 if deadline is None else deadline, 0.0)
    while True:
        if not out["api"] and api_base:
            out["api"] = _probe_http_625(api_base.rstrip("/") + "/health") is not None
        if not out["ui"] and ui_base:
            out["ui"] = _probe_http_625(ui_base) is not None
        if (out["api"] or not api_base) and (out["ui"] or not ui_base):
            return out
        if _time.time() >= end:
            return out
        _time.sleep(min(_PROBE_INTERVAL_625, max(end - _time.time(), 0.0)))


# #1202qw: how long a stack verdict is worth consulting. Long enough to cover the seconds
# between a validation and the delivery tick that follows it; short enough that a stack which
# came back while nothing re-validated is not held down by an old reading.
STACK_VERDICT_TTL_1202QW = 300.0


def squad_launch_held_1202qw(verdict, now, ttl=STACK_VERDICT_TTL_1202QW):
    """Why the squad LAUNCH should be held, or "" to launch.

    `verdict` is the orchestrator's `_stack_verdict_1202qw` -- `(when, (failing stack checks))`
    -- stamped by every framework validation. No verdict, no failing stack check, and a verdict
    older than `ttl` all launch: this may only hold the squad on a MEASURED, RECENT
    "nothing answers".
    """
    try:
        when, failing = float(verdict[0]), tuple(verdict[1] or ())
    except Exception:
        return ""
    if not failing:
        return ""
    age = now - when
    if age < 0 or age > max(float(ttl), 0.0):
        return ""
    return "%ds ago the framework's validation found the stack not serving (%s)" % (
        int(age), ", ".join(str(f) for f in failing))


def _runnable_goals_625(goals: Sequence[Mapping[str, Any]],
                        reach: Mapping[str, bool]) -> List[Dict[str, Any]]:
    """Drop the goals whose modality has no listening target.

    `mcp` talks to the API. So does `browser`, transitively and always: a browser test-user
    drives the UI to exercise the APP, and every page it opens reads through the API. With the
    API down it sees empty lists, spinners and failed fetches on every page -- the stack's
    state, which is exactly what #625 exists to keep out of the bug queue.

    tiktok-r128 17:25-17:34 measured it: the squad took the stack lease while the backend was
    still down, the 60s probe gave up, the 3 api/mcp goals were skipped -- and the 7 browser
    goals were dispatched anyway, because `browser` needed only the UI. They ran nine minutes
    against a frontend whose backend answered `Connection refused` to every call (the log has
    their `test_api ... NOTHING IS LISTENING at localhost:8008` lines), and their findings were
    thrown away wholesale by the `skipped_env_unavailable` early return.
    """
    need = {"browser": ("ui", "api"), "api": ("api",), "mcp": ("api",)}
    return [dict(g) for g in goals
            if all(reach.get(t, False)
                   for t in need.get(str(g.get("modality") or "browser"), ("api",)))]


def _collection_groups(business_eps: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group business endpoints into resource collections (base path -> verbs present).

    Mirrors test_user_validation._api_crud_journey's grouping so a CRUD-fallback goal lines up
    with what the deterministic journey would exercise.
    """
    cols: Dict[str, Dict[str, Any]] = {}
    for ep in business_eps or []:
        if not isinstance(ep, Mapping):
            continue
        path = str(ep.get("path") or "")
        method = str(ep.get("method") or "GET").upper()
        if not path.startswith("/api"):
            continue
        if not re.search(r"\{|\$\{|:[A-Za-z_]", path):  # collection-level (no params)
            c = cols.setdefault(path, {"post": False, "list": False, "item": False})
            if method == "POST":
                c["post"] = True
            elif method == "GET":
                c["list"] = True
            continue
        m = re.match(r"^(/api/[^/]+(?:/[^/{}$:]+)*)/(?:\{[^}]+\}|:\w+|\$\{[^}]+\})$", path)
        if m:
            cols.setdefault(m.group(1), {"post": False, "list": False, "item": False})["item"] = True
    return cols


def _resource_label(base_col: str) -> str:
    seg = base_col.rstrip("/").split("/")[-1]
    return seg or "resource"


def _flow_goal_text(flow: Mapping[str, Any]) -> str:
    """Render an ORCHESTRATOR-defined flow (or a supplied flow dict) into a plain-language goal."""
    name = str(flow.get("name") or flow.get("id") or "user flow")
    desc = str(flow.get("description") or flow.get("goal") or "").strip()
    steps = flow.get("steps") or flow.get("path") or []
    if isinstance(steps, (list, tuple)) and steps:
        step_txt = "; ".join(str(s) for s in steps)
        return f"Complete the '{name}' user flow: {desc or step_txt}. Steps: {step_txt}."
    return f"Complete the '{name}' user flow" + (f": {desc}." if desc else ".")


def _ui_page_entries(ui_pages: Any) -> List[Dict[str, str]]:
    """Normalize registryhub ui_pages (dict{name->page} or list) to [{name, route}]."""
    out: List[Dict[str, str]] = []
    items: List[Any] = []
    if isinstance(ui_pages, Mapping):
        for name, pg in ui_pages.items():
            if isinstance(pg, Mapping):
                items.append({**pg, "name": pg.get("name") or name})
    elif isinstance(ui_pages, (list, tuple)):
        items = [p for p in ui_pages if isinstance(p, Mapping)]
    for pg in items:
        route = str(pg.get("route") or pg.get("path") or "").strip()
        name = str(pg.get("name") or route or "page").strip()
        low = route.rstrip("/").lower()
        if not route or low in ("", "/login", "/signup", "/signin", "/register"):
            continue  # auth pages are covered by every agent's login; skip as standalone goals
        out.append({"name": name, "route": route})
    return out


def _missing_write_goals(
    business_eps: Optional[Sequence[Mapping[str, Any]]],
    tables: Optional[Mapping[str, Any]],
    feature_inventory: Optional[Mapping[str, Any]],
    acc: Sequence[str],
) -> List[Dict[str, Any]]:
    """R2(a): ENTITIES/FLOWS-NEEDING-WRITE that the DECLARED contract can't satisfy.

    Reuses the #557 classifier (``completeness_audit``) — the SINGLE source that also
    drives the oracle + the route-projector heal — so a state-bearing entity that is
    READABLE but has NO POST/PUT/PATCH (the Continue-Watching class), or a declared
    feature-inventory FLOW whose verb implies a mutation with no backing write, yields
    an EXPLICIT ``missing_write_path`` goal instead of being silently skipped (today the
    squad only derives goals from collections that already declare a POST, so a missing
    write-path is invisible and coverage reads 100%). Each goal fails loudly: it tells
    its agent to file a P0 via bug_create ("no endpoint to create/update <entity>").

    Empty (⇒ the caller's output is byte-identical) when no table/inventory is supplied
    or every state entity / mutation flow already has its write endpoint. Never raises."""
    try:
        from .completeness_audit import (
            state_entities_missing_write, check_flow_no_write, _normalize_inventory)
    except Exception:
        return []
    eps_dict = {i: dict(e) for i, e in enumerate(business_eps or [])
                if isinstance(e, Mapping)}
    goals: List[Dict[str, Any]] = []
    seen: set = set()

    def _slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")

    try:
        missing_state = state_entities_missing_write(dict(tables or {}), eps_dict)
    except Exception:
        missing_state = {}
    for entity, cols in sorted(missing_state.items()):
        key = _slug(entity)
        if not key or key in seen:
            continue
        seen.add(key)
        col_txt = ", ".join(cols) or "its state"
        goals.append({
            "modality": "api", "kind": "missing_write_path",
            "name": f"missing_write_{key}", "entity": entity,
            "missing_verb": "POST/PUT/PATCH", "critical": True,
            "goal": (f"CONTRACT GAP — MISSING WRITE PATH: the app declares the state-bearing "
                     f"entity '{entity}' (mutable field(s): {col_txt}) with a READ endpoint but "
                     f"NO create/update endpoint (no POST/PUT/PATCH). A user can VIEW '{entity}' "
                     f"but can NEVER write it, so the feature cannot work and the write is lost. "
                     f"Confirm there is NO endpoint to create/update '{entity}', then FILE A P0 "
                     f"via bug_create titled 'no endpoint to create/update {entity}'. This goal "
                     f"is a FAILURE until the write path exists — do NOT mark it passed."),
            "acceptance": list(acc) or None,
        })
    try:
        _, fi_flows = _normalize_inventory(dict(feature_inventory or {}))
        flow_findings = check_flow_no_write(None, eps_dict, fi_flows,
                                            dict(tables or {}))
    except Exception:
        flow_findings = []
    for r in flow_findings:
        flow = getattr(r, "flow", None) or ""
        key = _slug(flow)
        if not key or key in seen:
            continue
        seen.add(key)
        goals.append({
            "modality": "api", "kind": "missing_write_path",
            "name": f"missing_write_{key}", "flow": flow,
            "missing_verb": getattr(r, "missing_verb", None), "critical": True,
            "goal": (f"CONTRACT GAP — MISSING WRITE PATH: the declared feature flow '{flow}' "
                     f"implies a mutation (verb '{getattr(r, 'missing_verb', None)}') but NO "
                     f"write endpoint (POST/PUT/PATCH) backs it — the flow can be viewed but "
                     f"not performed. Confirm no write endpoint exists for '{flow}', then FILE "
                     f"A P0 via bug_create titled 'no endpoint to perform {flow}'. This goal is "
                     f"a FAILURE until the write path exists — do NOT mark it passed."),
            "acceptance": list(acc) or None,
        })
    return goals


def plan_test_user_goals(
    *,
    business_eps: Optional[Sequence[Mapping[str, Any]]] = None,
    ui_pages: Optional[Any] = None,
    acceptance: Optional[Sequence[str]] = None,
    tenants: Optional[Sequence[str]] = None,
    multi_tenant: bool = False,
    mcp_present: bool = False,
    extra_flows: Optional[Sequence[Mapping[str, Any]]] = None,
    tables: Optional[Mapping[str, Any]] = None,
    feature_inventory: Optional[Mapping[str, Any]] = None,
    max_goals: int = 12,
) -> List[Dict[str, Any]]:
    """Define the test workflows (one agent per workflow), tagged by MODALITY. PURE.

    The ORCHESTRATOR owns workflow definition at the test/verify/fix stage (user directive
    2026-06-22): a user_flow is NOT a frontend-kickoff artifact and the frontend agent does not
    author it — workflows are derived here from the registered CONTRACT (the reliably-present
    ``ui_pages`` + endpoints), so the test-user never depends on optional kickoff ``user_flows``.
    One workflow == one task == one spawned agent.

      * BROWSER workflows — ``extra_flows`` (optional orchestrator/LLM-defined rich flows) +
        ui_crud per writable resource + an "exercise this page" flow per remaining declared ui_page,
        so every declared screen is walked and its controls asserted.
      * API workflows — CRUD-per-resource lifecycle over the HTTP API (independent of the UI).
      * MCP workflow — when an MCP server exists: completeness (a tool per endpoint) + parity vs API.
      * ISOLATION workflow (§3.4) — when multi-tenant: a two-actor cross-tenant leak check (X-Tenant-Id).
      * MISSING-WRITE-PATH goals (R2) — when ``tables``/``feature_inventory`` is supplied: for a
        state-bearing entity or mutation flow the DECLARED contract can READ but not WRITE (the
        #557 classifier), emit an explicit ``missing_write_path`` goal that fails loudly + files a
        P0, instead of silently skipping it (the ROOT gap: goals were derived only from declared
        POST collections, so a missing write-path was invisible and coverage read 100%).
    Each goal: {modality, kind, name, goal, steps?, acceptance?, tenant?, actor?}.
    """
    goals: List[Dict[str, Any]] = []
    acc = [str(a) for a in (acceptance or [])]
    cols = _collection_groups(business_eps or [])
    writable = [b for b in sorted(cols) if cols[b].get("post")]
    pages = _ui_page_entries(ui_pages)
    # resource collection -> its likely UI route (so a page isn't double-covered by ui_crud).
    resource_labels = {_resource_label(b) for b in writable}

    # --- BROWSER workflows ---
    # 1) orchestrator/LLM-supplied explicit flows (the rich multi-step scenarios), each a task.
    for f in (extra_flows or []):
        if not isinstance(f, Mapping):
            continue
        goals.append({
            "modality": "browser", "kind": "flow",
            "name": str(f.get("name") or f.get("id") or f"flow_{len(goals)+1}"),
            "goal": _flow_goal_text(f), "steps": list(f.get("steps") or []) or None,
            "critical": bool(f.get("critical", True)), "acceptance": acc or None,
        })
    # 2) ui_crud per writable resource (rich create->list->edit->delete through the UI).
    for base_col in writable:
        res = _resource_label(base_col)
        goals.append({
            "modality": "browser", "kind": "ui_crud", "name": f"ui_{res}",
            # #1202qh: only the writes the screens OFFER. "create, open, edit and delete a {res}
            # through the UI" was asked of every table with a POST: tiktok-r126's M2 squad filed P0s
            # that `video_likes`, `dm_messages` and `notifications` had "no UI to create, open, edit,
            # or delete" - screens no reference image has, which the lanes would then build off-
            # design. A like is a heart toggle, a notification is never hand-authored. A control
            # that exists and fails is still a P0; a write no screen offers is api_crud's to test.
            "goal": (f"As a user, exercise every way the app's screens let you change {res}: use "
                     f"each control that creates, toggles, edits or removes it (a form, a button, "
                     f"a like/follow/save toggle, ...), confirm the change shows where the UI "
                     f"displays {res}, reverse it where the UI offers that, and cross-check each "
                     f"change via the API. A control that exists but does not work, or a change "
                     f"that does not persist: FILE A P0. An operation no screen offers a control "
                     f"for (for example no edit form) is NOT a defect of this flow - note it and "
                     f"do not file a P0; the API workflow covers that write."),
            "acceptance": acc or None,
        })
    # 3) exercise each remaining declared page (covers read-only/aggregate screens —
    #    dashboards, list/aggregate views, settings, detail screens — whatever the app declared)
    #    and assert its controls' effects. Page names come from the contract, never hardcoded.
    for pg in pages:
        slug = re.sub(r"[^a-z0-9]+", "_", pg["name"].lower()).strip("_") or "page"
        if slug in resource_labels or any(slug in str(g["name"]) for g in goals):
            continue  # already covered by a ui_crud flow
        goals.append({
            "modality": "browser", "kind": "page", "name": f"page_{slug}",
            "goal": (f"Open the '{pg['name']}' page ({pg['route']}) as the user and exercise every "
                     f"interactive control on it; assert each control's RESULT matches its intent "
                     f"(navigation / API call + status / DOM change). For any control that CHANGES "
                     f"STATE (play/resume/rate/like/mark/toggle/save/add/progress/…), do a "
                     f"PERSIST-THEN-RELOAD check: perform the action, RELOAD the page, and assert "
                     f"the new state is still reflected — if it reverts, the write did not persist; "
                     f"FILE A P0. Then VERIFY the objective "
                     f"signals a real user would notice (#181): the page shows REAL seeded data "
                     f"(specific realistic rows — NOT an empty state, placeholder/lorem/'Untitled' "
                     f"filler, or one value repeated); if it shows a MAP it is a REAL interactive "
                     f"map (draggable tiles + real markers), NOT a static image or a colored box; "
                     f"and you actually reached this page logged-in, not bounced to a login wall. "
                     f"FILE A P0 for any blank/placeholder content, fake map, or auth bounce you "
                     f"find. No console errors."),
            "acceptance": acc or None,
        })

    # --- API workflows: CRUD lifecycle per writable resource over HTTP ---
    for base_col in writable:
        res = _resource_label(base_col)
        goals.append({
            "modality": "api",
            "kind": "api_crud",
            "name": f"api_{res}",
            "goal": (f"Over the HTTP API, drive the full {res} lifecycle as the user: create "
                     f"(POST {base_col}) -> read it back (it must persist + be owner-scoped) -> "
                     f"list -> update -> delete. Assert status codes, response shape, persistence, "
                     f"and that auth is required (401 without a token)."),
            "acceptance": acc or None,
        })
    if not writable:  # no writable resource -> at least smoke the API auth + a read
        goals.append({
            "modality": "api", "kind": "api_smoke", "name": "api_smoke",
            "goal": ("Over the HTTP API: register/login to get a token, then GET each readable "
                     "endpoint and assert it returns a valid-shape 2xx (no 5xx), and that calling "
                     "without a token is rejected."),
            "acceptance": acc or None,
        })

    # --- MCP goal: completeness + parity ---
    if mcp_present:
        goals.append({
            "modality": "mcp", "kind": "mcp_parity", "name": "mcp_surface",
            "goal": ("Connect to the env's MCP server with a token, list its tools and verify there "
                     "is one per business endpoint (completeness), then call representative read + "
                     "write tools and assert each result MIRRORS the equivalent HTTP API call "
                     "(parity). Reject-on-no-auth too."),
            "acceptance": acc or None,
        })

    # --- ISOLATION goal (multi-tenant) ---
    if multi_tenant or (tenants and len(tenants) >= 2):
        t = list(tenants or ["tenant_a", "tenant_b"])
        goals.append({
            "modality": "api", "kind": "isolation", "name": "tenant_isolation",
            "goal": (f"Multi-tenant isolation: as user A in tenant '{t[0]}', create some data; then "
                     f"as user B in tenant '{t[1] if len(t) > 1 else 'tenant_b'}', confirm you CANNOT "
                     f"see or access user A's / tenant '{t[0]}'s data (lists exclude it; direct id "
                     f"access is denied). File a P0 bug on ANY cross-tenant leak."),
            "tenant": t[0], "actor": "userA", "acceptance": acc or None,
        })

    # --- MISSING-WRITE-PATH goals (R2): entities/flows the DECLARED contract can't write ---
    # Prepended (they are the loudest failures) and built SEPARATELY so they never perturb the
    # page-dedup above; when nothing is missing this is `[] + goals` → byte-identical output.
    missing_write = _missing_write_goals(business_eps, tables, feature_inventory, acc)
    return (missing_write + goals)[:max_goals]


def build_briefing(goal: Mapping[str, Any], *, ui_base: str, api_base: str,
                   identity: Optional[str] = None) -> str:
    """Render a goal into the full task briefing string passed to the agent (as task
    `description` so it lands verbatim in the rendered task prompt). PURE."""
    lines = [
        "You are a test-user. Complete this assignment against the RUNNING app, asserting each "
        "step's real result, and file any defect via bug_create. Then finish(notify=['orchestrator']).",
        "",
        f"GOAL: {goal.get('goal', 'Exercise the app as a typical user and report anything broken.')}",
    ]
    steps = goal.get("steps")
    if steps:
        lines.append("STEP HINTS:")
        for i, s in enumerate(steps, 1):
            lines.append(f"  {i}. {s}")
    lines.append(f"UI base:  {ui_base}")
    lines.append(f"API base: {api_base}")
    if goal.get("tenant") and goal.get("kind") != "isolation":
        # Per-agent tenant: each concurrent test-user runs in its OWN fresh tenant so the squad
        # is mutually independent (no cross-contamination), exploiting the app's multi-tenancy.
        lines.append(f"YOUR TENANT: '{goal['tenant']}' — you are INDEPENDENT of all other concurrent test-users.")
        lines.append(f"  - Send header 'X-Tenant-Id: {goal['tenant']}' on EVERY API call (and via browser_eval/localStorage if the UI uses it).")
        lines.append(f"  - Initialize it FIRST if the app exposes a tenant control plane (e.g. POST /api/v1/admin/init-tenant with that header).")
        lines.append(f"  - Register your OWN user in this tenant and CREATE whatever data your flow needs — your tenant starts EMPTY, which is correct (an empty list before you create anything is NOT a bug).")
    elif goal.get("kind") == "isolation":
        lines.append(f"Identity: {identity or '(register fresh users per the two tenants in the goal)'}")
    else:
        lines.append(f"Identity: {identity or '(register a fresh user; or the seeded demo user, password `password`)'}")
    if goal.get("actor"):
        lines.append(f"Actor label: {goal['actor']}")
    if goal.get("acceptance"):
        lines.append("ACCEPTANCE (this milestone's bar — verify these specifically):")
        for a in goal["acceptance"]:
            lines.append(f"  - {a}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Async runner — fans the goals out to N concurrent `test_user` agents. Defensive: a spawn
# or wait failure for one goal never sinks the squad; returns a per-goal completion report.
# --------------------------------------------------------------------------------------

async def run_test_user_squad(
    orch: Any,
    goals: Sequence[Mapping[str, Any]],
    *,
    ui_base: str,
    api_base: str,
    identity: Optional[str] = None,
    max_concurrent: int = 4,
    per_agent_timeout: float = 180.0,
) -> Dict[str, Any]:
    """Spawn one `test_user` agent per goal, concurrently in waves of ``max_concurrent``.

    Each agent gets the full briefing as its task ``description`` (so it renders into the prompt)
    and drives the app via its tool chain; defects are filed by the agents themselves via
    bug_create. Returns ``{spawned, completed, timed_out, failed, agents:[{name, agent_id,
    completed, error}]}``. Never raises — a per-goal failure is recorded, not propagated.
    """
    import asyncio
    from ..agent_spawn_service import AgentSpawnRequest

    report: Dict[str, Any] = {"spawned": 0, "completed": 0, "timed_out": 0, "failed": 0, "agents": []}
    spawn_service = getattr(orch, "spawn_service", None)
    if spawn_service is None:
        report["error"] = "orchestrator has no spawn_service"
        return report

    logger = getattr(orch, "_logger", None)
    goals = list(goals)

    # #625: probe before spawning. An agent that cannot reach the app files the environment's
    # state as a product defect, once per goal.
    # #1202qu: a stack that is still BOOTING is not a stack that is down. The squad holds the
    # compose lease (#1202nx) by the time it gets here, so nothing can tear the stack down
    # while it waits -- and in r128 the API answered nowhere near the 60s the probe allowed
    # after a `down -v` + rebuild. Give a cold boot the same budget every other verifier gives
    # it before calling the environment unavailable.
    _reach = targets_reachable_625(ui_base, api_base,
                                   deadline=_BOOT_DEADLINE_1202QU)
    report["reachable"] = dict(_reach)
    if not (_reach["ui"] and _reach["api"]):
        _kept = _runnable_goals_625(goals, _reach)
        _skipped = len(goals) - len(_kept)
        report["skipped_env_unavailable"] = _skipped
        report["error"] = (
            f"env_unavailable: ui={ui_base} {'up' if _reach['ui'] else 'DOWN'}, "
            f"api={api_base} {'up' if _reach['api'] else 'DOWN'} — "
            f"{_skipped} goal(s) not dispatched (their findings would be the stack's state, "
            f"not the app's)")
        if logger is not None:
            logger.warning("[test-user squad] %s", report["error"])
        goals = _kept
        if not goals:
            return report

    async def _run_one(idx: int, goal: Mapping[str, Any]) -> Dict[str, Any]:
        name = str(goal.get("name") or f"goal_{idx+1}")
        modality = str(goal.get("modality") or "browser")
        profile = MODALITY_PROFILE.get(modality, "browser_test_user")
        agent_id = f"{profile}_{idx+1}_{re.sub(r'[^a-zA-Z0-9_]', '_', name)[:20]}"
        rec: Dict[str, Any] = {"name": name, "agent_id": agent_id, "modality": modality,
                               "kind": goal.get("kind"), "completed": False, "error": None}
        # Each agent runs in its OWN fresh tenant (independence for concurrent runs). The
        # isolation goal manages its own two tenants — leave it. Others get a unique tenant.
        goal_b = dict(goal)
        if goal.get("kind") != "isolation" and not goal.get("tenant"):
            goal_b["tenant"] = f"tu_{idx+1}_{modality}"
        rec["tenant"] = goal_b.get("tenant")
        briefing = build_briefing(goal_b, ui_base=ui_base, api_base=api_base, identity=identity)
        try:
            res = await spawn_service.spawn(AgentSpawnRequest(
                agent_id=agent_id,
                agent_type=profile,
                config_key=profile,
                task=str(goal.get("goal") or name),   # short label; full briefing rides metadata.description
                parent_id="orchestrator",
                role=profile,
                resident=False,
                metadata={"description": briefing},
            ))
        except Exception as exc:  # spawn failure for this goal only
            rec["error"] = f"spawn failed: {type(exc).__name__}: {exc}"
            return rec
        report["spawned"] += 1
        ev = getattr(res, "task_done_event", None)
        if ev is None:
            rec["error"] = "no task_done_event"
        else:
            try:
                await asyncio.wait_for(ev.wait(), timeout=per_agent_timeout)
                rec["completed"] = True
            except asyncio.TimeoutError:
                rec["error"] = f"did not finish within {per_agent_timeout:.0f}s"
        try:
            await spawn_service.terminate(agent_id, wait=False)
        except Exception:
            pass
        return rec

    # Wave the gather so we respect the spawn/active caps (orchestrator parent cap is 8).
    wave = max(1, int(max_concurrent))
    indexed = list(enumerate(goals))
    for start in range(0, len(indexed), wave):
        chunk = indexed[start:start + wave]
        results = await asyncio.gather(
            *[_run_one(i, g) for i, g in chunk], return_exceptions=True)
        for r in results:
            if isinstance(r, dict):
                report["agents"].append(r)
                if r.get("completed"):
                    report["completed"] += 1
                elif str(r.get("error") or "").startswith("did not finish"):
                    report["timed_out"] += 1
                else:
                    report["failed"] += 1
            else:  # an unexpected gather exception
                report["failed"] += 1
                report["agents"].append({"error": f"{type(r).__name__}: {r}", "completed": False})
        if logger:
            try:
                logger.warning("TEST-USER SQUAD wave %d: %d completed / %d spawned so far",
                               start // wave + 1, report["completed"], report["spawned"])
            except Exception:
                pass
    return report


def gather_squad_inputs(orch: Any) -> Dict[str, Any]:
    """Best-effort gather of the planner inputs from the orchestrator's hubs + the running env.

    Returns {business_eps, user_flows, ui_pages, multi_tenant, mcp_present, ui_base, api_base,
    identity, acceptance}. Never raises — missing pieces default empty so the squad still runs a
    sensible subset. SYNC (pure hub/file reads)."""
    from pathlib import Path as _P
    out: Dict[str, Any] = {
        "business_eps": [], "ui_pages": {}, "multi_tenant": False,
        "mcp_present": False, "ui_base": None, "api_base": None, "identity": None,
        "acceptance": [], "tables": {}, "feature_inventory": {},
    }
    proj = _P(getattr(orch, "output_dir", ".") or ".")
    hubs = getattr(orch, "hubs", None)
    registryhub = getattr(hubs, "registryhub", None) if hubs else None

    try:
        from .lifecycle import business_endpoints
        if registryhub is not None:
            out["business_eps"] = business_endpoints(registryhub.get_endpoints())
    except Exception:
        pass
    try:
        if registryhub is not None:
            out["ui_pages"] = registryhub.list_ui_pages() or {}
    except Exception:
        pass
    try:
        if registryhub is not None:
            tbls = registryhub.list_tables() or {}
            out["tables"] = tbls  # R2: state-entity source for missing-write-path goals
            out["multi_tenant"] = any(
                str(k).rstrip("s").endswith("tenant") or "tenant" in str(k).lower()
                for k in tbls.keys())
    except Exception:
        pass
    # R2: feature_inventory (the INTENDED feature set) — reuse the #557 loader so a
    # mutation flow with no backing write also yields a missing_write_path goal.
    try:
        from .completeness_audit import _load_feature_inventory
        out["feature_inventory"] = _load_feature_inventory(hubs) or {}
    except Exception:
        pass
    try:
        out["mcp_present"] = (proj / "mcp_server").exists()
    except Exception:
        pass
    # NOTE: workflows are DEFINED HERE by the orchestrator from the contract (ui_pages +
    # endpoints) — NOT read from frontend kickoff `user_flows` (which are optional/often absent
    # and no longer a frontend artifact). The orchestrator may pass richer LLM-planned flows as
    # `extra_flows` to plan_test_user_goals.
    # acceptance from the current milestone slice, if the orchestrator exposes it.
    try:
        ms = getattr(orch, "_current_milestone", None) or {}
        acc = ms.get("acceptance") if isinstance(ms, Mapping) else None
        out["acceptance"] = [str(a) for a in (acc or [])]
    except Exception:
        pass
    # resolve the running app's ports + the seeded demo identity.
    try:
        from .validation_runner import _service_host_port, _backend_host_port
        compose = proj / "docker" / "docker-compose.yml"
        if compose.exists():
            be = _backend_host_port(compose, compose.parent)
            fe = (_service_host_port(compose, compose.parent, "frontend")
                  or _service_host_port(compose, compose.parent, "ui"))
            out["api_base"] = f"http://localhost:{be}" if be else None
            out["ui_base"] = f"http://localhost:{fe}" if fe else None
            # #1134: publish the run's OWN ports so `test_api` can tell a probe of this app
            # apart from a probe of some other sandbox on the same host. Measured: in all
            # three runs on the current code the app's real port is the LEAST-probed one,
            # and :3011 (the rydr/Uber sandbox here) answered 22 probes in netflix-local-r2
            # and 31 in smoke-notes. r2's squad filed all six of ITS 404s as this product's
            # missing endpoints while this run's own chains were getting 201/200 on the same
            # paths. Process-global on purpose: every lane agent runs in this process, and
            # the ports are a property of the run, not of a caller.
            try:
                import os as _os1134
                _known = {str(x) for x in (be, fe) if x}
                _prev = (_os1134.environ.get("ENVGEN_RUN_HTTP_PORTS") or "").split(",")
                _known.update(x.strip() for x in _prev if x.strip())
                if _known:
                    _os1134.environ["ENVGEN_RUN_HTTP_PORTS"] = ",".join(sorted(_known))
            except Exception:
                pass
    except Exception:
        pass
    try:
        from .visual_fidelity import _seed_demo_login
        demo = _seed_demo_login(proj)
        if demo:
            out["identity"] = f"{demo.get('email')} / password `{demo.get('password')}`"
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------------------
# Test->fix ladder (design §3.5): collect the bugs the test-user agents filed, decide whether
# to DEFER the release (bounded, mirroring the visual gate), and persist a failure ledger so a
# previously-failing goal is RE-TESTED FIRST next cycle.
# --------------------------------------------------------------------------------------

def collect_open_p0_by_source(orch: Any) -> Dict[str, int]:
    """#630 — every OPEN P0 bug, by the source that filed it.

    The delivery gate consumed only `collect_test_user_bugs`, which skips any bug whose source is
    not one of the three test-user profiles. That is the minority of them: across 40 runs the
    **verifier files 207 of the 314 P0 bugs**, and 32 of the 73 P0s still open at run end are
    invisible to the gate. No other gate reads `list_open_bugs` at all, so a run could — and did —
    release while carrying "Landing page (/) crashes … blank render blocks entire landing".

    This was deferred twice as "a release-path change no artifact can validate". That reasoning
    was wrong, and the counterfactual is cheap: replay each released run and count the open
    non-test-user P0s at the moment of its first release.

        21 runs released
        17 carried ZERO — the gate is invisible to them
         4 would have deferred, with 1–4 open P0s
           r127 (1 of 1) and r128 (3 of 4) had them RESOLVED later in the same run
           r109 (2) and r133 (1) never did -> they ride the existing escape budget

    So the blast radius is 4 of 21 runs, the deferral is what the standing goal asks for, and it
    cannot wedge: `squad_gate_outcome`'s `defect` branch burns an escape attempt and
    `squad_release_decision`'s wall-clock remains the backstop. Best-effort; {} on any hub error.
    """
    out: Dict[str, int] = {}
    try:
        workhub = getattr(getattr(orch, "hubs", None), "workhub", None)
        if workhub is None or not hasattr(workhub, "list_open_bugs"):
            return out
        for b in workhub.list_open_bugs() or []:
            meta = (b.get("metadata") or {}) if isinstance(b, Mapping) else {}
            if str(meta.get("severity") or "").upper() != "P0":
                continue
            src = str(meta.get("source") or "unknown")
            out[src] = out.get(src, 0) + 1
    except Exception:
        pass
    return out


def collect_test_user_bugs(orch: Any) -> Dict[str, Any]:
    """Read the OPEN bugs filed by the test-user agents (source in TEST_USER_SOURCES).

    Returns {p0, p1, total, by_modality:{modality:count}, titles:[...]}. Best-effort; empty on
    any hub error. (bug_create stores source+severity on the bug task metadata; the gate reads it.)
    """
    out = {"p0": 0, "p1": 0, "total": 0, "by_modality": {}, "titles": []}
    try:
        workhub = getattr(getattr(orch, "hubs", None), "workhub", None)
        if workhub is None or not hasattr(workhub, "list_open_bugs"):
            return out
        src_to_mod = {v: k for k, v in MODALITY_PROFILE.items()}
        for b in workhub.list_open_bugs() or []:
            meta = (b.get("metadata") or {}) if isinstance(b, Mapping) else {}
            source = meta.get("source")
            if source not in TEST_USER_SOURCES:
                continue
            sev = str(meta.get("severity") or "P3").upper()
            out["total"] += 1
            if sev == "P0":
                out["p0"] += 1
            elif sev == "P1":
                out["p1"] += 1
            mod = src_to_mod.get(source, source)
            out["by_modality"][mod] = out["by_modality"].get(mod, 0) + 1
            if b.get("title"):
                out["titles"].append(str(b.get("title"))[:120])
    except Exception:
        pass
    return out


def squad_release_decision(deferred_since: Optional[float], attempts: int, now: float,
                           *, max_attempts: int = 3, wall_s: float = 900.0) -> str:
    """'defer' | 'release'. Called ONLY when test-user agents left open P0 defects.

    Mirrors the visual gate's bounded deferral (orchestrator._visual_release_decision): keep
    deferring (re-dispatch fixes, re-test next cycle) until either the per-milestone attempt cap
    or the wall-clock anchored to the FIRST defer is hit — then release anyway (never deadlock).
    """
    # #1202es: `or 0` because a RESTORED counter is None, not absent — `_rc_attempts` and
    # `_tu_browser_attempts` are both persisted and both sit as null in a
    # milestone_gates.json written before #1202el. #1202em hardened the `+ 1` increments and
    # missed the reads that feed this comparison.
    if (attempts or 0) >= max_attempts:
        return "release"
    if deferred_since is not None and (now - deferred_since) >= wall_s:
        return "release"
    return "defer"


class FailureLedger:
    """Persists per-goal test-user pass/fail across delivery CYCLES so a previously-failing goal
    is re-tested FIRST next cycle (design §3.5 'regression of previously-failed flows'). Pure +
    JSON-backed; no hub coupling. Keyed by '<modality>::<goal name>'."""

    def __init__(self, path: Any):
        self.path = Path(path)
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"cycle": 0, "goals": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _key(goal: Mapping[str, Any]) -> str:
        return f"{goal.get('modality')}::{goal.get('name')}"

    def record_cycle(self, results: Sequence[Mapping[str, Any]]) -> None:
        """results: [{modality, name, passed: bool, defects: int}]."""
        self.data["cycle"] = int(self.data.get("cycle", 0)) + 1
        c = self.data["cycle"]
        goals = self.data.setdefault("goals", {})
        for r in results:
            key = f"{r.get('modality')}::{r.get('name')}"
            g = goals.setdefault(key, {"fail_streak": 0, "pass_count": 0, "last_cycle": 0,
                                       "last_defects": 0, "passed": False})
            g["last_cycle"] = c
            g["last_defects"] = int(r.get("defects", 0) or 0)
            if r.get("passed"):
                g["pass_count"] += 1
                g["fail_streak"] = 0
                g["passed"] = True
            else:
                g["fail_streak"] += 1
                g["passed"] = False
        self._save()

    def open_failures(self) -> List[str]:
        return [k for k, g in self.data.get("goals", {}).items() if not g.get("passed", False)]

    def order_replay_first(self, planned_goals: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """Reorder planned goals so ones that FAILED in a prior cycle run first (regression pass)."""
        open_keys = set(self.open_failures())
        return sorted((dict(g) for g in planned_goals),
                      key=lambda g: (0 if self._key(g) in open_keys else 1, str(g.get("name"))))


def squad_gate_enabled(env: Mapping[str, Any]) -> bool:
    """#179: the test-user squad runs on delivery by DEFAULT (validated live on gmrun13, where it
    spawned 9 agents, detected a broken frontend, and filed bugs). An operator disables it with
    ENVGEN_TESTUSER_SQUAD in {0,false,no,off}. Default-ON is the fix for "test-user 功能都没测":
    a build with dead controls / a blank detail page no longer slips past the test-user gate."""
    return str(env.get("ENVGEN_TESTUSER_SQUAD", "1")).strip().lower() in ("1", "true", "yes", "on")


def squad_gate_outcome(*, ran: bool, p0: int) -> str:
    """#179: classify a squad result into the delivery-gate action.

    - 'pass'   : squad ran and filed zero P0 → the milestone may release.
    - 'defect' : squad ran and filed P0 defect(s) → defer AND burn an escape-budget attempt.
    - 'retry'  : squad could not run (app ports not resolved yet / empty contract / crash →
                 ran=False) → defer but do NOT burn an attempt, so flaky first-attempt port
                 timing can't erode the defer/escape budget. squad_release_decision's wall-clock
                 remains the escape backstop, so a genuinely-never-ready app still releases.
    """
    if not ran:
        return "retry"
    return "pass" if int(p0 or 0) == 0 else "defect"


def squad_relaunch_blocked_1202rd(app_sig, last_verdict_sig, open_p0: int) -> str:
    """#1202rd: why a re-launch should wait, or "" to launch.

    `squad_gate_tick_action`'s own docstring says the handle is cleared "so the next 'launch'
    may re-arm AFTER THE FIX LANDS". Nothing checked that. Consume clears the handle and the
    very next tick sees `task_exists=False` and launches twelve more agents.

    tiktok-r130: squad #1 returned `verdict=DEFECTS: 19 open P0 (18 from test-users)` at
    23:42:53, and squad #2 spawned twelve agents at 23:44:29 -- ninety-six seconds later. In
    that gap the lanes read files and claimed tasks and wrote nothing, so the second squad was
    paid to rediscover the same nineteen defects.

    The condition is deliberately "the app changed", not "the P0s are closed": a lane may fix
    something without closing a ticket, and a squad that re-runs over changed code is doing its
    job. With no open P0 there is nothing to wait for either, so it launches.
    """
    try:
        if int(open_p0 or 0) <= 0:
            return ""
    except (TypeError, ValueError):
        return ""
    if not app_sig or not last_verdict_sig:
        return ""                     # no signature to compare -- never block on ignorance
    if app_sig != last_verdict_sig:
        return ""                     # the app moved; re-testing is the point
    return ("the app source has not changed since the last squad returned %d open P0(s); "
            "twelve more agents would rediscover them" % int(open_p0))


def squad_gate_tick_action(*, task_exists: bool, task_done: bool) -> str:
    """#532: single-flight decision for the BACKGROUND test-user squad gate.

    The squad is ~42min of work (12 browser agents in 3 sequential waves) — running it
    INLINE inside ``_maybe_framework_deliver`` wedges the whole coordination loop so
    create_release is never reached. Instead the gate runs the squad as ONE background
    task and consults this pure predicate each delivery tick (given the single task
    handle's ``exists`` / ``done`` state):

    - 'launch'  : no task in flight (first defer, or the prior one was consumed) → spawn
                  exactly ONE background squad and defer this tick (never a 2nd — the
                  single-flight invariant).
    - 'defer'   : a task is in flight but not finished → defer WITHOUT spawning another
                  and WITHOUT awaiting it inline; the loop keeps ticking.
    - 'consume' : the in-flight task finished → read its result this tick (then the
                  handle is cleared, so the next 'launch' may re-arm after the fix lands).

    Pure + total (no I/O); the wall-clock/attempt escape (squad_release_decision) is
    evaluated by the caller BEFORE this and can RELEASE the gate regardless of task state.
    """
    if not task_exists:
        return "launch"
    if not task_done:
        return "defer"
    return "consume"


# #1202rt: WHEN THE REALISM JUDGE RUNS.
#
# #1202rh built the judge -- an independent subagent that uses the app for an ordinary task and
# reports whether anything gave away that it is generated -- and left it with no dispatch. A
# mechanism nobody calls is the defect class this session has spent the day removing, so this
# is its trigger.
#
# Three constraints decide the moment, and they are not the squad's:
#   * SAMPLED, not every tick. It is an LLM judging a live app; the proposal that specified it
#     asked for periodic sampling for exactly this reason.
#   * The stack must be SERVING. M1 is defined as noticing while working; there is nothing to
#     notice against a stack that does not answer.
#   * ADVISORY. It reports "someone would see through this", not "the build is broken", so it
#     records findings and never holds a release. A judge that can block would be primed to
#     find something.
#
# The squad-gate release point satisfies all three: the squad has just driven the stack, so it
# is up; the release is about to be cut, so this is the last honest look; and the decision is
# already made, so nothing here can be mistaken for a blocker.
# Corpus (generated/, 20 runs whose name records the count): 16 ship 4 milestones, 3 ship 3,
# 1 ships 2. Sampling every 3rd starting at the first lands on milestones 1 and 4 of a 4-run --
# the first release, whose seed/copy/imagery every later one inherits, and the final one, which
# is what actually ships. A 3-run gets milestone 1 only.
_REALISM_EVERY_N_1202RT = 3
# NOT a measurement: a POLICY cap on how long a release may wait for an advisory observation.
# The judge's own profile budget is 2700s (agents_config.yaml realism_judge.timeout); this is
# far tighter because unlike that budget, this wait sits on the release path holding the stack
# lease. On expiry the release proceeds and the finding is simply lost -- the right trade for
# something that is never allowed to block.
_REALISM_DEADLINE_1202RT = 420.0


def realism_probe_due_1202rt(milestone_index: Any, every_n: int = _REALISM_EVERY_N_1202RT,
                             enabled_env: Any = None) -> bool:
    """Should the realism judge run for this milestone? Pure; False on anything unreadable.

    Samples every Nth milestone starting with the FIRST -- the first release is the one whose
    seed, copy and imagery every later milestone inherits, so a tell found there is a tell
    found before it propagates.
    """
    import os as _os
    env = _os.environ if enabled_env is None else enabled_env
    try:
        if str(env.get("ENVGEN_REALISM_PROBE", "1")).strip().lower() in (
                "0", "false", "off", "no"):
            return False
        n = max(1, int(every_n))
        i = int(milestone_index)
    except (TypeError, ValueError):
        return False
    return i >= 0 and i % n == 0


async def run_realism_probe_1202rt(orch: Any, version: str = "") -> Dict[str, Any]:
    """Dispatch ONE realism judge against the running app. Advisory; never raises.

    Unprimed (M1): the briefing is an ordinary information-gathering task, and the word
    "realism" does not appear in it. Priming over-detects by roughly 4x -- a judge told it is
    hunting for fakery finds tells no working agent would ever have met -- so what this
    measures is whether anything surfaces WHILE WORKING.
    """
    report: Dict[str, Any] = {"ran": False}
    try:
        from ..agent_spawn_service import AgentSpawnRequest
    except Exception as exc:
        report["reason"] = "spawn service unavailable: %s" % exc
        return report
    spawn = getattr(orch, "spawn_service", None)
    if spawn is None:
        report["reason"] = "orchestrator has no spawn_service"
        return report
    logger = getattr(orch, "_logger", None)
    try:
        # #1202rt: gather_squad_inputs, not a name I remembered. The first draft called
        # _delivery_inputs, which does not exist -- it would have raised into the except
        # below and reported "no app address resolved" on every run, a probe that never
        # probes. Third time today a guessed name nearly shipped a silent no-op.
        inp = gather_squad_inputs(orch)
        ui, api = inp.get("ui_base") or "", inp.get("api_base") or ""
    except Exception:
        ui = api = ""
    if not (ui or api):
        report["reason"] = "no app address resolved"
        return report
    # The stack must be SERVING: M1 is noticing while working, and there is nothing to notice
    # against a stack that does not answer. Same probe the squad uses (#1202qu's budget).
    reach = targets_reachable_625(ui, api)
    if not (reach.get("ui") and reach.get("api")):
        report["reason"] = "env_unavailable: ui=%s api=%s" % (reach.get("ui"), reach.get("api"))
        if logger:
            logger.info("#1202rt realism probe skipped: %s", report["reason"])
        return report
    goal = ("Use this app to answer a question a real user would ask of it: find the most "
            "prominent items or people it features, open one, and report what it shows about "
            "them. Work through the UI.")
    try:
        # Local, like run_squad_for_delivery's -- stack_lease_1202nx is NOT a module-level
        # name here. Referencing it bare raised NameError straight into the except below,
        # which would have reported a reason string and never spawned anything.
        import asyncio as _aio
        from .compose_mutex import stack_lease_1202nx
        with stack_lease_1202nx(Path(str(getattr(orch, "output_dir", ".") or ".")),
                                "realism probe"):
            res = await spawn.spawn(AgentSpawnRequest(
                agent_id="realism_judge_1", agent_type="realism_judge",
                config_key="realism_judge", task=goal, parent_id="orchestrator",
                role="realism_judge", resident=False,
                metadata={"description": goal, "ui_base": ui, "api_base": api,
                          "regime": "unprimed"}))
            ev = getattr(res, "task_done_event", None)
            if ev is not None:
                # Bounded. This runs at the release point holding the stack lease: an
                # unbounded wait on a judge that hangs would hold the lease and stall the
                # release it was only ever meant to observe. Advisory work never blocks.
                try:
                    await _aio.wait_for(ev.wait(), timeout=_REALISM_DEADLINE_1202RT)
                except _aio.TimeoutError:
                    report["timed_out"] = True
                    if logger:
                        logger.info("#1202rt realism probe hit its %.0fs deadline; "
                                    "releasing anyway", _REALISM_DEADLINE_1202RT)
        report["ran"] = True
        if logger:
            logger.warning(
                "#1202rt REALISM PROBE (v%s) ran unprimed against %s — its findings are "
                "ADVISORY and recorded as bugs, never a release blocker: a judge that could "
                "block would be primed to find something.", version or "?", ui)
    except Exception as exc:
        report["reason"] = "%s: %s" % (type(exc).__name__, exc)
        if logger:
            logger.info("#1202rt realism probe did not run: %s", report["reason"])
    return report


async def run_squad_for_delivery(orch: Any, version: str = "",
                                 *, max_concurrent: int = 4) -> Dict[str, Any]:
    """#1202nx: the squad tests a RUNNING stack for minutes; hold the stack lease so a validation
    does not `down -v` it underneath (tiktok-r126: phantom "backend unreachable" P0s)."""
    from pathlib import Path as _P1202nx
    from .compose_mutex import stack_lease_1202nx
    with stack_lease_1202nx(_P1202nx(str(getattr(orch, "output_dir", ".") or ".")),
                            "test-user squad"):
        return await _run_squad_for_delivery_impl(orch, version, max_concurrent=max_concurrent)


async def _run_squad_for_delivery_impl(orch: Any, version: str = "",
                                       *, max_concurrent: int = 4) -> Dict[str, Any]:
    """Orchestrator-facing entry point: gather inputs, plan modality goals, fan out the squad.

    Best-effort + never raises into delivery. Returns {ran, report?, goals?, reason?}. Env-gated
    by the caller (ENVGEN_TESTUSER_SQUAD) until validated on a live run.
    """
    logger = getattr(orch, "_logger", None)
    try:
        inp = gather_squad_inputs(orch)
        if not inp.get("api_base") and not inp.get("ui_base"):
            return {"ran": False, "reason": "could not resolve running app ports"}
        goals = plan_test_user_goals(
            business_eps=inp["business_eps"], ui_pages=inp["ui_pages"],
            acceptance=inp["acceptance"], multi_tenant=inp["multi_tenant"],
            mcp_present=inp["mcp_present"], tables=inp.get("tables"),
            feature_inventory=inp.get("feature_inventory"))
        if not goals:
            return {"ran": False, "reason": "no goals planned (empty contract)"}
        # Regression: re-test previously-FAILED goals first (design §3.5).
        proj = Path(getattr(orch, "output_dir", ".") or ".")
        ledger = FailureLedger(proj / "test_user_reports" / "failure_ledger.json")
        goals = ledger.order_replay_first(goals)
        modalities = sorted({g["modality"] for g in goals})
        if logger:
            logger.warning(
                "TEST-USER SQUAD (v%s): spawning %d agents across modalities %s "
                "(api=%s ui=%s mcp=%s multi_tenant=%s); replaying %d prior failure(s) first",
                version, len(goals), modalities, inp["api_base"], inp["ui_base"],
                inp["mcp_present"], inp["multi_tenant"], len(ledger.open_failures()))
        # #1202qe: the squad's agents register accounts and create rows as real users; the
        # seeded state comes back when the squad finishes (see verification_isolation).
        from .verification_isolation import isolated_verification_1202qe
        with isolated_verification_1202qe(proj, "test_user_squad", logger):
            report = await run_test_user_squad(
                orch, goals,
                ui_base=inp["ui_base"] or inp["api_base"],
                api_base=inp["api_base"] or inp["ui_base"],
                identity=inp["identity"], max_concurrent=max_concurrent)
        # #625: if the target was down, some or all goals were never dispatched. That must NOT
        # read as a pass — with no agent running, no P0 is filed, and `ran=True, p0=0` is
        # exactly the input that sets _tu_squad_passed and releases the milestone UNTESTED.
        # `squad_gate_outcome` already models this as `retry` (defer without burning an
        # attempt), which is what "could not run" deserves. Returning before the ledger also
        # keeps a stack-down cycle from recording every goal as a fresh failure.
        if report.get("skipped_env_unavailable"):
            if logger:
                logger.warning("TEST-USER SQUAD (v%s): %s", version, report.get("error"))
            return {"ran": False, "reason": report.get("error"), "report": report,
                    "goals": goals, "modalities": modalities, "verdict": "ENV_UNAVAILABLE"}
        # Collect the defects the agents filed and record per-goal pass/fail in the ledger.
        bugs = collect_test_user_bugs(orch)
        agent_by_mod = {}
        for a in report.get("agents", []):
            agent_by_mod.setdefault(a.get("modality"), []).append(a)
        cycle_results = []
        for g in goals:
            mod = g.get("modality")
            # coarse per-goal verdict: passed iff its agent completed AND no P0 bug in its modality.
            completed = any(a.get("completed") for a in agent_by_mod.get(mod, [])
                            if a.get("name") == g.get("name")) or any(
                a.get("completed") for a in agent_by_mod.get(mod, []))
            mod_p0 = bugs.get("by_modality", {}).get(mod, 0)
            cycle_results.append({"modality": mod, "name": g.get("name"),
                                  "passed": bool(completed and mod_p0 == 0),
                                  "defects": mod_p0})
        ledger.record_cycle(cycle_results)
        # #630: the gate reads `bugs["p0"]` and nothing else, so widening it HERE is the whole
        # change — the orchestrator is untouched. `p0` becomes every open P0 regardless of who
        # filed it (the verifier files 207 of 314 across the corpus and was invisible); the
        # test-user-only figure is kept under `p0_test_user` so the per-modality ledger and the
        # reporting above keep meaning what they meant.
        by_source = collect_open_p0_by_source(orch)
        bugs["p0_test_user"] = bugs.get("p0", 0)
        bugs["p0_by_source"] = by_source
        # explicit, not `sum(...) or old`: a genuine zero must stay zero, and only a FAILED
        # reading (empty dict from a hub error) may fall back to the narrower count.
        bugs["p0"] = sum(by_source.values()) if by_source else bugs.get("p0", 0)
        verdict = "PASS" if bugs.get("p0", 0) == 0 else "DEFECTS"
        if logger:
            logger.warning("TEST-USER SQUAD (v%s) verdict=%s: %d open P0 (%d from test-users) / "
                           "%d P1 %s by-source=%s",
                           version, verdict, bugs.get("p0", 0), bugs.get("p0_test_user", 0),
                           bugs.get("p1", 0), bugs.get("by_modality") or "", by_source or {})
        return {"ran": True, "report": report, "goals": goals, "modalities": modalities,
                "bugs": bugs, "verdict": verdict}
    except Exception as exc:  # never break delivery
        if logger:
            try:
                logger.debug("test-user squad skipped: %s", exc)
            except Exception:
                pass
        return {"ran": False, "reason": f"{type(exc).__name__}: {exc}"}
