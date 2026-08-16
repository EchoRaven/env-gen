"""Per-milestone remediation dispatch, extracted from the Orchestrator
(PROPOSAL #8 — RemediationDispatcher).

When a hard delivery gate fails (a registered-implemented endpoint answering
404/405, a blank-shell / unwired frontend, or a frontend the lane built at the
repo root instead of under app/frontend/), the failure must be routed back to
the lane that can fix it — the verifier has no bug-write channel. Each helper
files ONE P0 task + an urgent wake to the owning lane, guarded to once per
milestone (validation retries every tick; re-dispatching would spam workhub).

Stateless: the dispatcher borrows the orchestrator for its collaborators (hubs /
message_bus / logger / output_dir) and the per-milestone dispatch guards
(``_unimpl_routes_dispatched`` etc.) live on the orchestrator — they are reset
by ``Orchestrator._fwval_rearm_owner_dispatch``, so they MUST stay there. The
orchestrator shims construct a fresh ``RemediationDispatcher(self)`` per call.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

# FIX #143 — content-based owner routing for docker_up build failures.
# run-65 M4 (2nd occurrence of the run-52 class): a frontend syntax error
# (Unterminated regex in HomeFeedPage.jsx) broke the build; the docker_up
# check went to the VERIFIER (two-hop: diagnose → file a bug to the owner)
# and under contention that hop took 47min — the 75-min no-convergence
# FAIL-FAST killed the run one minute after the bug was finally filed. The
# captured build tail (validation_runner: 3000-char up tail + container
# logs) already names the offending file, so the owner is deterministically
# classifiable — route the P0 straight to the lane that can edit the file.
# Both-signals/no-signal tails keep the verifier route (a lane without
# docker tools must not dead-end on an error it cannot see — smoke-notes
# 2026-06-19).
_FE_BUILD_RE = re.compile(
    r"\.jsx\b|\.tsx\b|\bvite\b|\brollup\b|\besbuild\b|npm (?:ERR|error)|"
    r"Unterminated regular expression|node_modules|\[frontend[ \]]",
    re.IGNORECASE)
_BE_BUILD_RE = re.compile(
    r"\.py\b|\bpip\b|\bpoetry\b|\buvicorn\b|ModuleNotFoundError|"
    r"\balembic\b|\[backend[ \]]",
    re.IGNORECASE)


def docker_up_owner(detail: str) -> str:
    """'frontend'/'backend' when the build-failure tail names exactly one
    side's toolchain; 'verifier' (the diagnose-first route) otherwise."""
    d = str(detail or "")
    fe = bool(_FE_BUILD_RE.search(d))
    be = bool(_BE_BUILD_RE.search(d))
    if fe and not be:
        return "frontend"
    if be and not fe:
        return "backend"
    return "verifier"


# FIX #148 — content-based owner routing for business_chain_failing.
# run-72 M4 (1st occurrence, recorded → pre-authorized): a contract-REGISTERED
# action endpoint (POST /api/users/{id}/unfollow) was never implemented by the
# lane, and the projection deliberately serves route_projector's FIX #124 stub
# 404 for it ("action endpoint not implemented by the projection — the app's
# own handler serves this route"). business_chain_failing routed to the
# VERIFIER — which can only re-author chains, not add a backend route — so the
# blocker spun 7 post-cap cycles to STUCK-abort. The chain executor already
# records the 404 body into each broken-step string (execute_chain: note =
# body_text[:160], and the #124 stub fits), so the owner is deterministically
# classifiable from the registry's last_result — mirror #143 and P0 the
# BACKEND with the exact endpoint list. Broken steps WITHOUT the stub
# signature keep the verifier diagnose-first route unchanged.
_ACTION_404_RE = re.compile(r"action endpoint not implemented", re.IGNORECASE)


def action_unimplemented_broken(broken) -> List[str]:
    """The broken-step strings whose 404 body carries the projection's
    action-endpoint stub signature (route_projector FIX #124) — a registered
    ACTION route only the backend lane can implement."""
    return [str(b) for b in (broken or []) if _ACTION_404_RE.search(str(b))]


def suppress_verifier_chain_reauthor(name: str, owner: str, chain_rerun_armed: bool) -> bool:
    """#70(b) (netflix r76, 2026-08-05): should the ``business_chain_failing`` verifier
    RE-AUTHOR dispatch be SKIPPED this deliver-tail tick?

    True iff the blocker is ``business_chain_failing``, it is STILL owned by the verifier
    (the #148 action-404 re-route did NOT flip it to the backend lane for a real missing
    endpoint), AND the framework armed a deterministic chain re-run this tick
    (``orch._chain_rerun_armed``, set from ``maybe_rerun_unrun_chains`` / #475). In that
    state the framework is re-running the EXISTING chains to settle them green; dispatching
    the verifier in parallel just makes it author MORE never-run chains, so run_chains never
    catches up (r76: gate 17→2, then business_chain green→REGRESSED→restored with 11
    never-run chains piling up, 0 delivery). Bounded by #475's 4/milestone cap: once spent,
    ``chain_rerun_armed`` is False here and normal dispatch resumes; a genuinely-BROKEN chain
    (where #475 no-ops) also leaves it False → the verifier IS dispatched to fix it. Pure."""
    return bool(name == "business_chain_failing" and owner == "verifier"
                and chain_rerun_armed)


def _uncovered_endpoints_799(orch) -> List[str]:
    """#799: name the uncovered endpoints. `business_chain_api_coverage`'s body said *"Add steps
    ... for the uncovered endpoints"* without listing one — while `delivery_gate` already computes
    exactly that set with `_uncovered_business_endpoints`, using the same `${var}` -> `{x}` collapse
    `register_verification_chain` validates with. Same defect as #798, same table, one entry over.
    Best-effort: any fault -> [] and the generic text stands."""
    try:
        from .delivery_gate import _uncovered_business_endpoints
        rh = orch.hubs.registryhub
        chains = rh.get_verification_chains() or {}
        authored = [rec for name, rec in (chains.items() if isinstance(chains, dict) else [])
                    if name != "_meta" and isinstance(rec, dict)]
        return list(_uncovered_business_endpoints(rh, authored) or [])[:12]
    except Exception:
        return []


def _red_checklist_checks_799(orch) -> List[str]:
    """#799: name the RED build check. `verification_checklist_not_ready` listed all four
    (`build:database`/`docker`/`frontend`/`backend`) and left the lane to work out which is not
    green — the store holds each one's status. Best-effort: any fault -> []."""
    try:
        rows = orch.hubs.codehub.list_checks() or []
        out: List[str] = []
        for c in rows:
            if not isinstance(c, Mapping):
                continue
            nm = str(c.get("name") or "")
            if not nm.startswith("build:"):
                continue
            st = str(c.get("status") or "")
            if st in ("success", "passed", "pass"):
                continue
            det = str((c.get("evidence") or {}).get("summary") or "").strip() \
                if isinstance(c.get("evidence"), Mapping) else ""
            out.append(f"{nm} = {st or 'never recorded'}" + (f" — {det[:140]}" if det else ""))
        return out[:6]
    except Exception:
        return []


def _chain_broken_detail_798(orch) -> List[str]:
    """#798: name the broken step. The `business_chain_failing` task body said "read the broken
    step" and stopped there — while the framework already holds, per chain, exactly which step
    broke and why.

    `registryhub_verification_chains.json` records `last_result.broken` plus a per-step row with
    `action` / `method` / `path` / `status` / `ok` / `kind` / `note` / `expect`. Measured over the
    corpus: **30 of 140 runs carry at least one failing chain, and all 30 have that payload.**
    Meanwhile `"Make business_chain pass (blocks delivery)"` is the most re-filed title in the
    corpus (13 copies in r130 alone, #794) — so the single most-repeated instruction in the system
    was asking the verifier to go and find something already written down.

    Same `_extra` mechanism as #284's ui_flow names and #148's action-404 list. Best-effort: any
    fault → [] and the generic text stands.
    """
    try:
        chains = orch.hubs.registryhub.get_verification_chains() or {}
        out: List[str] = []
        for name, rec in (chains.items() if isinstance(chains, dict) else []):
            if name == "_meta" or not isinstance(rec, dict):
                continue
            lr = rec.get("last_result") or {}
            for st in (lr.get("steps") or []):
                if not isinstance(st, Mapping) or st.get("ok") is True:
                    continue
                got = st.get("status")
                exp = st.get("expect")
                note = str(st.get("note") or "").strip()
                out.append(
                    "%s -> step %r: %s %s returned %s, expected %s%s" % (
                        name, str(st.get("action") or "?"),
                        str(st.get("method") or "?"), str(st.get("path") or "?"),
                        got if got is not None else "no response",
                        exp if exp else "a 2xx",
                        (" — " + note[:160]) if note else ""))
            if not (lr.get("steps") or []):
                for b in (lr.get("broken") or []):
                    out.append("%s -> broken: %s" % (name, str(b)[:200]))
        return out[:8]
    except Exception:
        return []


def _chain_action_404s(orch) -> List[str]:
    """Re-derive the #124-stub broken steps from the chain registry's
    last_result (the gate-level failed_checks carry names only — same
    re-derivation pattern as the business_chain_api_coverage branch).
    Best-effort: no registryhub / malformed records → [] (verifier route)."""
    try:
        chains = orch.hubs.registryhub.get_verification_chains() or {}
        broken: List[str] = []
        for name, rec in (chains.items() if isinstance(chains, dict) else []):
            if name == "_meta" or not isinstance(rec, dict):
                continue
            broken.extend((rec.get("last_result") or {}).get("broken") or [])
        seen: set = set()
        out: List[str] = []
        for b in action_unimplemented_broken(broken):
            if b not in seen:
                seen.add(b)
                out.append(b)
        return out
    except Exception:
        return []


def _ui_flow_missing_names(orch) -> List[str]:
    """FIX #284: re-derive the EXACT critical flows the ui_flow gate counts as missing,
    from the same source the gate uses (compute_flow_coverage over the hub) — NOT from any
    status the verifier reported. r68's verifier BROADCAST that fyp_feed / login_modal_route
    were "recorded status=success" when the hub held no record under either name; the
    dispatch trusted nothing it could contradict, so recompute the truth here.
    Best-effort: any hub/import hiccup → [] (the dispatch falls back to #280's generic text)."""
    try:
        # module-level name so tests can monkeypatch rd.compute_flow_coverage; falls back
        # to the real import when the attribute was not injected.
        _cfc = globals().get("compute_flow_coverage")
        if _cfc is None:
            from .flow_coverage import compute_flow_coverage as _cfc
        report = _cfc(orch.hubs.registryhub)
        seen: set = set()
        out: List[str] = []
        for f in (getattr(report, "missing", None) or []):
            s = str(f).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out
    except Exception:
        return []


def _ui_flow_missing_extra(missing: List[str]) -> str:
    """The gate-specific remediation body for deliverability_ui_flow_missing. Names the exact
    missing flows and states the contradiction that broke r68 out loud — so a verifier that
    believes it "already recorded" them is forced to re-check the hub instead of re-asserting.
    Empty when nothing is missing, leaving #280's generic text untouched."""
    if not missing:
        return ""
    names = "\n- ".join(missing)
    return (
        "\n\nThese CRITICAL flows have NO passing `validation:ui_flow:<name>` record in the "
        "hub RIGHT NOW — re-read the hub before claiming otherwise; a broadcast that they were "
        "'already recorded' does not make the record exist (r68 idled 40min on exactly that "
        "false claim):\n- " + names +
        "\n\nFor EACH: run_validation to DRIVE the real browser flow (navigate + interact) and "
        "WRITE a passing validation:ui_flow record under that exact name. If the flow genuinely "
        "FAILS, bug_create for the owning lane (usually frontend) and re-run once fixed. Do not "
        "report the task complete until a fresh compute shows these names cleared.")


class RemediationDispatcher:
    """Routes failed-gate remediation back to the owning lane. Stateless —
    reads/writes the orchestrator's collaborators + per-milestone guards live."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    async def dispatch_unimplemented_routes(self, data) -> None:
        """GATE-C1 feedback loop: a ``business_endpoints_implemented`` FAIL (an
        endpoint registered ``status=implemented`` answering 404/405) must reach
        the lane that can fix it — the verifier has no bug-write channel
        (TOOL-C1), so without this the hard gate just pins validation red until
        the budget dies. Mirrors the business_chain #53 dispatch: ONE P0 task +
        urgent wake to the BACKEND lane per milestone (validation retries every
        tick; re-dispatching would spam workhub). The fix is either real
        (implement the route) or registry hygiene (deprecate a junk
        registration via registryhub_deprecate_endpoint — it then leaves the
        business contract and the gate self-clears). Best-effort: never raises
        into the coordination loop."""
        orch = self._orch
        try:
            check = next(
                (c for c in ((data or {}).get("checks") or [])
                 if c.get("name") == "business_endpoints_implemented"
                 and c.get("status") == "fail"),
                None)
            if not check:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_unimpl_routes_dispatched", None) == milestone:
                return
            detail = str(check.get("detail") or "")
            task = orch.hubs.workhub.create_task(
                title="Registered-implemented endpoint(s) answer 404/405 (blocks delivery)",
                description=(
                    "api_smoke's business_endpoints_implemented gate FAILED: the "
                    "following endpoints are registered status=implemented but the "
                    "live app answers 404/405 — the route is not actually wired:\n"
                    f"{detail}\n"
                    "For each one, either IMPLEMENT the route in the backend, or — "
                    "if the registration is junk/obsolete — deprecate it via "
                    "registryhub_deprecate_endpoint so it leaves the business "
                    "contract. Delivery stays blocked until a validation pass shows "
                    "every registered-implemented endpoint serving its route."),
                assignee="backend",
                agent="orchestrator",
                priority="P0",
            )
            orch._unimpl_routes_dispatched = milestone
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="backend",
                content=(
                    "URGENT: delivery is blocked on business_endpoints_implemented "
                    "— endpoint(s) registered as implemented answer 404/405. Claim "
                    f"task {(task or {}).get('id')} and implement the route(s) or "
                    "deprecate the junk registration(s) NOW."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["unimplemented_routes", "remediation"],
            ))
            orch._logger.warning(
                "UNIMPLEMENTED-ROUTE remediation dispatched to backend (task %s): %s",
                (task or {}).get("id"), detail[:200])
        except Exception as exc:
            orch._logger.error("unimplemented-route dispatch failed: %s", exc)

    async def dispatch_route_consolidation(self, dups) -> None:
        """#180: the contract registered ONE logical endpoint at VERSION-VARIANT duplicate
        paths (e.g. GET /api/directions AND GET /api/v1/directions). The lane implements one
        and leaves the other a projected empty stub that the frontend may actually call → the
        page renders empty, and #173 flags that stub with a "query the table" remediation that
        CANNOT fix a path mismatch (run-13: 80min no-convergence abort on exactly this). Route
        the CORRECT fix — consolidate to ONE path — to the backend lane. ONE P0 task + urgent
        wake per milestone (guard reset by _fwval_rearm_owner_dispatch). Best-effort: never
        raises into the coordination loop."""
        orch = self._orch
        if not dups:
            return
        try:
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_route_consolidation_dispatched", None) == milestone:
                return
            lines = "\n".join(f"  - {d.get('method')} at {d.get('paths')}" for d in dups)
            task = orch.hubs.workhub.create_task(
                title="Version-variant DUPLICATE route(s) — consolidate to ONE path (blocks delivery)",
                description=(
                    "The contract registered the SAME logical endpoint under version-variant "
                    "duplicate paths:\n" f"{lines}\n"
                    "A frontend client calls only ONE of each pair; the other is left an "
                    "unimplemented projected stub that returns an empty collection, so its page "
                    "renders empty (it may ALSO be flagged separately as a placeholder-stub). Do "
                    "NOT implement the stub path as a new handler — CONSOLIDATE: serve the real "
                    "logic at the path the frontend api client actually calls, and DEPRECATE the "
                    "duplicate via registryhub_deprecate_endpoint so it leaves the contract. That "
                    "clears both the duplicate and any stub flag on it."),
                assignee="backend",
                agent="orchestrator",
                priority="P0",
            )
            orch._route_consolidation_dispatched = milestone
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="backend",
                content=(
                    "URGENT: the contract has version-variant DUPLICATE routes "
                    f"{[d.get('paths') for d in dups]}. Claim task {(task or {}).get('id')} and "
                    "CONSOLIDATE each to the single path the frontend calls (deprecate the "
                    "duplicate) — do NOT implement the stub path separately."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["route_consolidation", "remediation"],
            ))
            orch._logger.warning(
                "ROUTE-CONSOLIDATION remediation dispatched to backend (task %s): %s",
                (task or {}).get("id"), [d.get("paths") for d in dups])
        except Exception as exc:
            orch._logger.error("route-consolidation dispatch failed: %s", exc)

    async def dispatch_frontend_navigable(self, data) -> None:
        """frontend_navigable feedback loop: a blank-shell frontend (page
        components present but 0 routes wired, or 0 pages) FAILS the navigable
        gate, but the failure routed NOWHERE — the framework deliberately does
        not author UI (lane owns it, 2026-06-11), and the frontend lane has
        already finish()ed, so it never re-engages and the gate pins validation
        red until the budget dies (observed: gemini wrote 2 components, 0 routes,
        imported one into App.jsx, finished → "blank shell" forever). Close the
        loop the same way visual-fidelity and GATE-C1 do: ONE P0 task + urgent
        wake to the FRONTEND lane per milestone, with a concrete instruction to
        wire the router. Framework still authors no UI content — it only routes
        the failure back to the owner. Best-effort: never raises into the loop."""
        orch = self._orch
        try:
            check = next(
                (c for c in ((data or {}).get("checks") or [])
                 if c.get("name") == "frontend_navigable"
                 and c.get("status") == "fail"),
                None)
            if not check:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_frontend_navigable_dispatched", None) == milestone:
                return
            detail = str(check.get("detail") or "")
            # Derive the screen list from the CONTRACT (the declared ui_pages), not a
            # hardcoded social-app vocabulary — this instruction is what the frontend
            # LLM lane reads and acts on, so a baked-in "feed/explore/reels/profile"
            # enumeration would steer EVERY generated app toward an instagram shape
            # (mirrors dispatch_unwired_ui_pages, which already builds from the contract).
            try:
                pages = orch.hubs.registryhub.list_ui_pages() or {}
            except Exception:
                pages = {}
            lines: List[str] = []
            for name, pg in (pages.items() if isinstance(pages, dict) else []):
                if not isinstance(pg, dict):
                    continue
                route = pg.get("route") or pg.get("path") or "?"
                comp = pg.get("component") or name or "?"
                apis = ", ".join(pg.get("apis_used") or []) or "(its declared apis_used)"
                lines.append(
                    f"  - <Route path=\"{route}\" element={{<{comp}/>}} /> → {comp} "
                    f"(calls [{apis}])")
            # Domain-neutral fallback when the registry is empty (the gate can fire at
            # 0 pages) — NEVER re-introduce social-screen examples here.
            page_list = "\n".join(lines) or (
                "  - a <Route> for EVERY screen depicted in the reference images "
                "(design/reference_spec.json), each pointing at its page component")
            task = orch.hubs.workhub.create_task(
                title="Frontend is a blank shell — wire routes + build the pages (blocks delivery)",
                description=(
                    "The frontend_navigable gate FAILED: " + detail + ".\n"
                    "The app renders blank because react-router routes are not "
                    "wired. Do ALL of the following, then finish:\n"
                    "1. In src/App.jsx set up react-router (BrowserRouter + Routes) "
                    "with a <Route> for EVERY declared page below, each pointing at "
                    "its page component:\n"
                    f"{page_list}\n"
                    "2. Author any page component that doesn't exist yet (one per "
                    "route above), reading data via src/services/api.js (data.items / "
                    "data.item).\n"
                    "3. A logged-out user lands on the auth/login page; an authed user "
                    "lands on the page whose route is \"/\" (the declared default).\n"
                    "frontend_navigable requires >=1 page AND >=1 route; delivery "
                    "stays blocked until a validation pass shows a navigable UI."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            orch._frontend_navigable_dispatched = milestone
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    "URGENT: delivery is blocked on frontend_navigable — the app is "
                    "a blank shell (routes not wired). Claim task "
                    f"{(task or {}).get('id')} and wire src/App.jsx react-router "
                    "Routes for every reference-spec screen (+ author the missing "
                    "page components) NOW, then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["frontend_navigable", "remediation"],
            ))
            orch._logger.warning(
                "FRONTEND-NAVIGABLE remediation dispatched to frontend (task %s): %s",
                (task or {}).get("id"), detail[:200])
        except Exception as exc:
            orch._logger.error("frontend-navigable dispatch failed: %s", exc)

    async def dispatch_failing_checks(self, data) -> None:
        """PROPOSAL #21 — close the remediation-dispatch COVERAGE gap. The
        validate→remediate loop previously re-dispatched only TWO lane-actionable
        failing checks (``business_endpoints_implemented``→backend via
        dispatch_unimplemented_routes, ``frontend_navigable``→frontend above), so
        EVERY OTHER failing check sat unremediated when its owning lane had finished
        and gone idle — the orchestrator LLM "waits" but does not deterministically
        re-task it (run #4: the frontend went idle 30min on ``frontend_dead_controls``
        while the orchestrator logged "Waiting for frontend to fix dead controls"; the
        backend stalled on ``business_endpoints_reachable`` the same way). For each
        UNCOVERED failing check, create ONE P0 task + urgent ``task_ready`` to the
        OWNING lane, carrying the check's detail (``frontend_dead_controls`` detail
        names the offending .jsx files). Same family as #20 — re-wake the idle owner
        deterministically, independent of the (unreliable) orchestrator LLM. Guarded
        per-milestone in ``orch._check_owner_dispatched`` (a dict; reset by
        rearm_owner_dispatch so a changed/stuck failure set re-fires). The two
        already-covered checks are intentionally ABSENT (their bespoke helpers own
        them, untouched). Best-effort: never raises into the loop."""
        # check_id → (owner_lane, task_title, concrete how-to-fix instruction)
        _CHECK_OWNER = {
            "deliverability_missing_authored_seed": (
                # #41's gate (run-34, live: logged "NO remediation owner" — the check sat
                # undispatched). The BACKEND lane owns seed_data.json.
                "backend", "Author app/backend/seed_data.json (blocks delivery)",
                "app/backend/seed_data.json is absent/empty ({}), so the app ships the "
                "bland framework-fallback seed. Author domain-REALISTIC rows for users + "
                "EVERY business table: FK-valid ids, believable names/subjects/bodies/"
                "timestamps matching this app's domain (never 'Getting Started'/'Item 1' "
                "placeholders), enough rows that list screens look like the references "
                "(e.g. ~a dozen inbox messages). Write valid JSON: "
                "{\"users\": [...], \"<table>\": [...], ...}."),
            "deliverability_placeholder_stub_handler": (
                # #173 (gmrun9): the lane "implemented" a GET route as
                # `return {"items": []}` (no DB read) — a placeholder that renders an
                # empty page forever, even though real seed data existed. The BACKEND
                # lane owns the handler.
                "backend", "Replace the placeholder-stub GET handler with a real query "
                "(blocks delivery)",
                "a GET route handler returns a HARDCODED empty collection (e.g. "
                "`return {\"items\": []}`) with NO database query, so its page can never "
                "show real data. Query the real seeded table(s) — join/scope as the "
                "resource needs (e.g. a stop's departures from its lines) — and return the "
                "actual rows. Do NOT return a hardcoded empty/placeholder collection."),
            "deliverability_fabricated_field_fallback": (
                # #175 (gmrun9): the frontend renders `place.rating || '4.5'` /
                # `? place.name : 'HI Point Montara Lighthouse'` — invented data. The
                # FRONTEND lane owns the fix.
                "frontend", "Remove the fabricated member-field fallbacks (blocks delivery)",
                "the frontend renders a member field with a HARDCODED realistic fallback "
                "(`place.rating || '4.5'`, `? place.name : 'HI Point Montara Lighthouse'`) — "
                "fake data whenever the field is absent (often ALWAYS, if the field name "
                "drifted from the backend response). For EACH flagged site: render only the "
                "real field, and if it can be missing show an honest empty state ('—'/'N/A') "
                "— never a realistic fake value. Also fix any drifted field NAME to match the "
                "API response (e.g. review_count, not reviews)."),
            "frontend_dead_controls": (
                "frontend", "Bind the dead frontend controls (blocks delivery)",
                "interactive markup (<form>/submit button) with NO bound handler — a "
                "user clicking it gets nothing. Wire onSubmit/onClick + the matching "
                "src/services/api.js call in EACH listed file."),
            "frontend_reachable": (
                "frontend", "Frontend container must serve over HTTP (blocks delivery)",
                "the frontend container does not actually serve (build/serve crash) — "
                "fix the vite/nginx/start config so the UI loads."),
            "docker_up": (
                # Route a build/up failure to the VERIFIER — the only lane with
                # docker_build/docker_logs (agents_config.yaml). Otherwise the build
                # error dead-ends on whoever was messaged: smoke-notes 2026-06-19, the
                # frontend escalated a vite build failure to the BACKEND, which has no
                # docker tools and no bash menu, and the run wedged on docker_up.
                "verifier", "Docker build/up is failing — diagnose the FULL build error (blocks delivery)",
                "the stack build fails (e.g. a vite/esbuild Transform error). Run "
                "docker_build(service='frontend', no_cache=True) (or docker_logs) to get "
                "the FULL error with file:line, then file a precise bug to the owning lane."),
            "business_endpoints_reachable": (
                "backend", "Wire the unreachable business endpoints (blocks delivery)",
                "registered+implemented endpoints answer 404/405 — the routes are not "
                "actually mounted. Wire them in app/backend/main.py (include_router / "
                "the @app.<method> path) so each declared path responds."),
            "business_endpoints_correct_shape": (
                "backend", "Fix business endpoint response shapes (blocks delivery)",
                "endpoints return the wrong response body/shape — match the declared "
                "schema (fields/types/nesting) for each named endpoint."),
            "auth_enforced_401": (
                "backend", "Enforce auth on business endpoints (blocks delivery)",
                "a business GET must return 401 without a valid token — add the auth "
                "dependency so unauthenticated requests are rejected."),
            "business_writes_persist": (
                "backend", "Fix write persistence (blocks delivery)",
                "a POST then GET readback does not return the written row — fix the "
                "handler/ORM commit so writes persist and read back."),
        }
        orch = self._orch
        try:
            milestone = getattr(orch, "_current_milestone_version", "")
            guard = getattr(orch, "_check_owner_dispatched", None)
            if not isinstance(guard, dict):
                guard = {}
                orch._check_owner_dispatched = guard
            from tools.communication_tools import _create_message
            for c in ((data or {}).get("checks") or []):
                if not isinstance(c, dict) or c.get("status") != "fail":
                    continue
                name = c.get("name")
                spec = _CHECK_OWNER.get(name)
                if not spec:
                    continue  # covered by a bespoke helper, or not lane-actionable
                if guard.get(name) == milestone:
                    continue  # one dispatch per milestone (storm control)
                owner, title, how = spec
                detail = str(c.get("detail") or "")
                if name == "docker_up":
                    # FIX #143: when the captured build tail names exactly one
                    # side's toolchain, skip the verifier diagnose-hop and P0
                    # the lane that owns the failing source — the tail already
                    # carries file:line, no docker tools needed to act on it.
                    _own = docker_up_owner(detail)
                    if _own != "verifier":
                        owner = _own
                        title = (f"Docker build fails in YOUR ({_own}) build — "
                                 "fix the named source file (blocks delivery)")
                        how = ("the build-error tail below names the failing "
                               "file (e.g. a parse/import error with file:line)."
                               " Fix that source file directly — you do NOT "
                               "need docker tools; the error is in your code.")
                task = orch.hubs.workhub.create_task(
                    title=title,
                    description=(
                        f"The `{name}` validation check FAILED: {detail}\n{how}\n"
                        "Delivery stays blocked until a validation pass shows this "
                        "check green. Fix it, then finish."),
                    assignee=owner, agent="orchestrator", priority="P0")
                guard[name] = milestone
                await orch.message_bus.send(_create_message(
                    source_agent_id="orchestrator", target_agent_id=owner,
                    content=(
                        f"URGENT: delivery is blocked on `{name}`. Claim task "
                        f"{(task or {}).get('id')} and fix it NOW, then finish. "
                        f"Detail: {detail[:300]}"),
                    msg_type="task_ready", priority="urgent", persist=True,
                    tags=[str(name), "remediation"]))
                orch._logger.warning(
                    "FAILING-CHECK remediation dispatched to %s (task %s): %s — %s",
                    owner, (task or {}).get("id"), name, detail[:160])
        except Exception as exc:
            orch._logger.error("failing-check dispatch failed: %s", exc)

    async def dispatch_unwired_ui_pages(self, blockers) -> None:
        """ui_page-wiring feedback loop: declared ui_pages whose route is not
        wired in App.jsx (or whose component file is missing) HARD-block delivery
        (``deliverability_ui_page_unwired``) even on a functionally-validated app
        — but, unlike GATE-C1 / frontend_navigable / visual-fidelity, this blocker
        routed NOWHERE. ``frontend_navigable`` passes on >=1 route (a lone wired
        ``/login`` satisfies it), so ITS dispatch goes quiet while delivery still
        requires EVERY declared page wired — the frontend lane finish()es with one
        route wired and nothing ever tells it to wire the rest, so the run
        deadlocks (gemini instagram 2026-06-13: App.jsx wired only ``/login``; 12
        declared pages — home/explore/reels/messages/profile/… — sat unwired and
        delivery blocked for hours with no feedback). Close the loop the same way
        the others do: ONE P0 task + urgent wake to the FRONTEND lane per
        milestone, listing the specific unwired pages + their declared routes +
        components. The framework authors NO UI — it routes the gap (with registry
        truth) back to the owner. Best-effort: never raises into the loop."""
        orch = self._orch
        try:
            if not blockers:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_unwired_ui_pages_dispatched", None) == milestone:
                return  # one dispatch per milestone — the gate recomputes every tick
            try:
                pages = orch.hubs.registryhub.list_ui_pages() or {}
            except Exception:
                pages = {}
            # PROPOSAL #51 (b): build a per-page directive that DISTINGUISHES the two
            # failure modes (a lane that already wired the routes misread the old
            # "wire pages" message as done — smoke-notes 2026-06-19 finished with 3
            # stub pages). For a STUB (file exists, placeholder body) the fix is to
            # WRITE the real component body + its apis_used — NOT to touch App.jsx.
            # Carry the exact file path + apis_used so the lane doesn't guess (it
            # hallucinated HomePage.jsx + wrote introspection scripts last run).
            lines: List[str] = []
            n_stub = 0
            for name, pg in (pages.items() if isinstance(pages, dict) else []):
                if not isinstance(pg, dict):
                    continue
                _b = next((str(b) for b in blockers if ("`%s`" % name) in str(b)), None)
                if _b is None:
                    continue
                route = pg.get("route") or pg.get("path") or "?"
                comp = pg.get("component") or "?"
                apis = ", ".join(pg.get("apis_used") or []) or "(its declared apis_used)"
                # "declared but unusable" is the generic prefix on EVERY blocker — the
                # SPECIFIC reason discriminates: a placeholder/stub body vs a not-wired
                # route vs a missing component. Match only the stub-body reasons.
                is_stub = any(s in _b.lower() for s in (
                    "placeholder", "stub", "renders no real", "no real ui"))
                # FIX #171: a #166 MAP blocker shares the "declared but unusable" prefix, but
                # the map page IS wired — the "add a Route" message is misleading and drops the
                # actionable "build the real Leaflet map" instruction. Pass the blocker's own
                # reason (everything after "declared but unusable: ") through verbatim.
                is_map = ("map surface" in _b.lower() or "no map library" in _b.lower())
                if is_map:
                    _reason = _b.split("declared but unusable:", 1)[-1].strip() or _b
                    n_stub += 1  # count as a build-real-content fix, not an unwired-route one
                    lines.append(f"  - {comp} (route {route}): FAKE MAP — {_reason}")
                elif is_stub:
                    n_stub += 1
                    lines.append(
                        f"  - {comp} (route {route}): STUB — the file "
                        f"app/frontend/src/pages/{comp}.jsx EXISTS but is a placeholder "
                        f"that renders no real UI. OPEN it and write the REAL {comp} body: "
                        f"render data from [{apis}] via src/services/api.js "
                        f"(data.items / data.item), with forms/lists + bound "
                        f"onSubmit/onClick handlers. The route is already wired — editing "
                        f"App.jsx will NOT fix this.")
                else:
                    lines.append(
                        f"  - {comp} (route {route}): UNWIRED — add "
                        f"`<Route path=\"{route}\" element={{<{comp}/>}} />` to "
                        f"app/frontend/src/App.jsx (and author the component if missing, "
                        f"calling [{apis}]).")
            page_list = "\n".join(lines) or "\n".join("  - " + str(b) for b in blockers[:15])
            _verb = "are placeholder STUBS / unwired" if n_stub else "are unwired"
            task = orch.hubs.workhub.create_task(
                title="Make the declared pages deliverable: fill stubs + wire routes (blocks delivery)",
                description=(
                    f"Delivery is HARD-BLOCKED: {len(blockers)} declared ui_page(s) {_verb}. "
                    "api_smoke is green but the UI is a near-blank shell. Wiring a route is "
                    "NOT enough — each page must render its REAL UI and call its declared "
                    "apis_used. Fix EACH below, then finish:\n"
                    f"{page_list}\n"
                    "For STUB pages the fix is to WRITE THE COMPONENT BODY (open the named "
                    ".jsx and replace the placeholder), NOT to edit App.jsx routes. Delivery "
                    "stays blocked until every declared page renders real UI (a gate tick "
                    "re-checks)."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            orch._unwired_ui_pages_dispatched = milestone
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    f"URGENT: delivery is blocked — {len(blockers)} declared page(s) "
                    f"{_verb} (api_smoke is green but the UI is a near-blank shell). Claim "
                    f"task {(task or {}).get('id')}: for each STUB, OPEN its "
                    "app/frontend/src/pages/<Component>.jsx and WRITE the real UI (render "
                    "its apis_used) — do NOT just edit App.jsx routes — then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["ui_page_unwired", "remediation"],
            ))
            orch._logger.warning(
                "UI-PAGE-UNWIRED remediation dispatched to frontend (task %s): %s "
                "unwired page(s): %s",
                (task or {}).get("id"), len(blockers),
                "; ".join(str(b) for b in blockers)[:200])
        except Exception as exc:
            orch._logger.error("ui-page-unwired dispatch failed: %s", exc)

    async def dispatch_unbuilt_pages(self, components) -> None:
        """Page-BUILD feedback loop (2026-06-22, user goal: real reference-faithful
        UI, not the framework fallback). A declared business ui_page the lane never
        authored ships as the framework FALLBACK (data-fallback marker) — it is wired
        + functional so it passes ui_page_unwired / frontend_navigable / the whole
        delivery gate, but it is NOT the real page the references show (outlook: the
        inbox/calendar shipped as the generic placeholder list). The bounded page-build
        gate (orchestrator) detects these and re-dispatches HERE: ONE P0 task + urgent
        wake to the frontend, each fallback page with its route/component/apis_used +
        reference image, so the lane authors the real UI. Best-effort; never raises."""
        orch = self._orch
        try:
            comps = [str(c) for c in (components or []) if str(c).strip()]
            if not comps:
                return
            try:
                pages = orch.hubs.registryhub.list_ui_pages() or {}
            except Exception:
                pages = {}
            _by_comp: Dict[str, dict] = {}
            for _name, _pg in (pages.items() if isinstance(pages, dict) else []):
                if isinstance(_pg, dict) and _pg.get("component"):
                    _by_comp[str(_pg["component"])] = _pg
            lines: List[str] = []
            for comp in comps:
                pg = _by_comp.get(comp, {})
                route = pg.get("route") or pg.get("path") or "?"
                apis = ", ".join(pg.get("apis_used") or []) or "(its declared apis_used)"
                ref = pg.get("reference_image") or pg.get("reference") or ""
                ref_hint = f" Match the reference screenshot {ref} (view_image it first)." if ref else \
                    " view_image its reference screenshot first."
                lines.append(
                    f"  - {comp} (route {route}): currently the GENERIC framework "
                    f"FALLBACK (a placeholder list, marked data-fallback). OPEN "
                    f"app/frontend/src/pages/{comp}.jsx and write the REAL {comp}: render "
                    f"[{apis}] via src/services/api.js (data.items / data.item) in the "
                    f"layout the reference shows, with bound controls.{ref_hint}")
            page_list = "\n".join(lines)
            task = orch.hubs.workhub.create_task(
                title="Replace framework-fallback pages with REAL UI (blocks delivery)",
                description=(
                    f"Delivery is DEFERRED: {len(comps)} business page(s) are still the "
                    "framework FALLBACK (a generic placeholder list, not the real page). "
                    "api_smoke is green, but these pages do not match the references. "
                    "Author the REAL component for each, then finish:\n"
                    f"{page_list}\n"
                    "Each page must render its declared apis_used data in the layout the "
                    "reference shows (view_image first). A gate tick re-checks; this is "
                    "bounded — build them now."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    f"URGENT: delivery deferred — {len(comps)} page(s) are still the "
                    f"generic framework fallback, not the real UI. Claim task "
                    f"{(task or {}).get('id')}: for each, view_image its reference, then "
                    "OPEN app/frontend/src/pages/<Component>.jsx and write the REAL page "
                    "(render its apis_used in the reference's layout), then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["ui_page_fallback", "remediation"],
            ))
            orch._logger.warning(
                "PAGE-BUILD remediation dispatched to frontend (task %s): %s fallback "
                "page(s): %s", (task or {}).get("id"), len(comps), ", ".join(comps))
        except Exception as exc:
            orch._logger.error("page-build dispatch failed: %s", exc)

    async def dispatch_gate_level_checks(self, failed_checks) -> None:
        """PROPOSAL #49 (user: a gate-detected problem must route back to the OWNING
        lane for repair, not silently dead-end). The DELIVERY-GATE-level failed_checks
        (``delivery_gate.failed_checks`` — a DIFFERENT set from the validation-run
        ``checks`` that #21 ``dispatch_failing_checks`` covers) routed NOWHERE except the
        bespoke ui_page_unwired / frontend_navigable helpers, so a gate-level blocker
        (e.g. ``business_response_key_noncanonical``, ``contract_alignment_failed``) sat
        unremediated forever even on a functionally-validated app (smoke-notes
        2026-06-19 stalled on ``business_response_key_noncanonical`` with no path back to
        the backend). For each gate check with an UNAMBIGUOUS lane owner, create ONE P0
        task + urgent wake to the owner (guarded per-milestone). Any failing check NOT
        routed here AND not bespoke-covered is LOGGED so it never silently dead-ends
        (complements #45's failed_checks log). Conservative: ambiguous / relaxed /
        framework-deterministic checks are logged, not mis-routed. Best-effort."""
        _GATE_OWNER = {
            "business_response_key_noncanonical": (
                "backend", "Fix non-canonical business response_key (blocks delivery)",
                "a business endpoint declares a response_key the projector never emits — "
                "the backend returns {\"items\": [...]} (list) / {\"item\": {...}} (single). "
                "Set each flagged endpoint's response_key to 'items' (collection) or "
                "'item' (single resource), then re-register it."),
            "contract_alignment_failed": (
                "backend", "Align implemented routes with the registered contract (blocks delivery)",
                "implemented backend routes don't match the registered endpoint contract "
                "(path/method/shape drift). Reconcile app/backend so every registered "
                "endpoint is served at its declared path + shape."),
            # DELIVERY-QUALITY (user 2026-06-24): a real, passing, verifier-authored
            # business-flow chain covering every critical flow is REQUIRED to ship.
            # All three business_chain_* gate checks route back to the verifier (it
            # owns release validation; the synthesized default does not satisfy delivery).
            "business_chain_missing": (
                "verifier", "Author business-flow verification chains (blocks delivery)",
                "NO verifier-authored verification chain is registered — delivery requires "
                "real business-flow verification, not just api_smoke, and the synthesized "
                "default does not count. Register chains via registryhub_register_verification_chain "
                "(auth round-trip first, then one chain per critical flow: create -> read-back -> "
                "cross-user), then run_validation to execute them."),
            "business_chain_failing": (
                "verifier", "Make business_chain pass (blocks delivery)",
                "a registered verification chain is NOT passing. run_validation must show "
                "business_chain green before delivery — read the broken step, fix the chain "
                "(or bug_create for the endpoint it exposed), then re-run run_validation."),
            "business_chain_api_coverage": (
                "verifier", "Cover every API endpoint with a verification chain (blocks delivery)",
                "some registered business API endpoints are exercised by NO verification chain "
                "— the union of all your chains must hit every endpoint at least once. Add "
                "steps to existing chains (or author a new chain) for the uncovered endpoints, "
                "then re-run run_validation."),
            "business_chain_coverage": (
                "verifier", "Cover every critical flow with a verification chain (blocks delivery)",
                "fewer verification chains than declared critical flows — author one "
                "business-flow chain per critical flow so each is covered, then re-run run_validation."),
            "business_chain_isolation": (
                "verifier", "Add a cross-user isolation/negative assertion (blocks delivery)",
                "your chains are a pure 2xx happy-path sweep — that cannot tell a real, "
                "tenancy-enforcing backend from one returning dummy 2xx. Add at least one "
                "NEGATIVE step proving ownership/tenant isolation is ENFORCED: a SECOND user "
                "(or an unauthenticated request) reading/modifying another user's resource MUST "
                "be refused (expect 401/403). Author the isolation step, register the chain, "
                "re-run run_validation."),
            # AUTHORED-SEED family (#41/#54). These tokens are minted ONLY by the
            # delivery gate's deliverability canonicalization (delivery_gate.py) —
            # i.e. THIS gate-level path, not the validation-run `checks` path that
            # dispatch_failing_checks covers — so their owner mapping must live in
            # THIS map (review w6x6art4t: a _CHECK_OWNER entry here is dead code;
            # run-34's "NO remediation owner" recurs and the non-waivable blocker
            # rides to STUCK-ABORT with the backend lane idle).
            "deliverability_missing_authored_seed": (
                "backend", "Author app/backend/seed_data.json (blocks delivery)",
                "app/backend/seed_data.json is absent/empty ({}), so the app ships "
                "the bland framework-fallback seed. Author domain-REALISTIC rows for "
                "users + EVERY business table: FK-valid ids, believable names/"
                "subjects/bodies/timestamps matching this app's domain, enough rows "
                "that list screens look like the references (~a dozen for the "
                "primary table). Write valid JSON: {\"users\": [...], \"<table>\": "
                "[...], ...}."),
            "deliverability_authored_seed_quality": (
                # #54 — the seed exists (#41 cleared) but fails the content audit.
                "backend", "Raise app/backend/seed_data.json to realistic density (blocks delivery)",
                "app/backend/seed_data.json exists but fails the content-quality "
                "audit: either fewer than ~10 structured rows in total (rows must "
                "be JSON objects), or a table whose values contain 2+ unambiguous "
                "placeholder markers (lorem/ipsum/placeholder/dummy/foo...). "
                "Rewrite it with domain-REALISTIC rows: enough rows that list "
                "screens look like the references (~a dozen for the primary "
                "table), believable names/subjects/bodies/timestamps, mixed "
                "states (read/unread, flagged), FK-valid ids."),
            "deliverability_bare_authed_fetch": (
                # #154 (§6-1, gmrun4): the frontend calls authed /api/ endpoints with a
                # bare fetch() that never attaches the Authorization token — every such
                # request 401s at runtime, pages render empty / bounce to the login
                # wall, while api_smoke (framework-minted token) stays green. The owner
                # is unambiguous: only the frontend lane can wire the token.
                "frontend", "Attach the auth token to every frontend /api/ call (blocks delivery)",
                "frontend code calls authed /api/ endpoints with a BARE fetch() that "
                "never attaches the Authorization token — at runtime every such request "
                "answers 401, so pages render empty or bounce to the login wall (the "
                "backend and api_smoke are fine; the framework token they use is not "
                "available to your bare call). For EACH flagged call site: route the "
                "call through the authed api client (src/services/api.js — its "
                "request() attaches authHeaders()) or add an Authorization: Bearer "
                "<token from localStorage> header at the call site. If services/api.js "
                "itself is flagged, fix IT to attach authHeaders() on every request."),
            "deliverability_placeholder_stub_handler": (
                # #173 (gmrun9/gmrun10, live): a GET route whose SERVED handler does no DB
                # read and returns a hardcoded empty/mock collection → a permanently
                # empty/fake page. Minted by the delivery-gate canonicalization → owner MUST
                # live in THIS gate-level map (the _CHECK_OWNER entry is dead code). BACKEND.
                "backend", "Replace the placeholder-stub GET handler with a real query (blocks delivery)",
                "a GET route handler returns a HARDCODED empty or mock collection (e.g. "
                "`return {\"items\": []}` or `return {\"items\": [{\"line\": \"A\", \"time\": "
                "\"5 min\"}]}`) with NO database query, so its page can never show real data. "
                "Query the real seeded table(s) — join/scope as the resource needs (e.g. a "
                "stop's departures from its lines) — and return the ACTUAL rows. Do NOT "
                "return a hardcoded empty/mock collection. #201: if the flagged handler is a "
                "FRAMEWORK `_projected_*` stub (in main.py, which you CANNOT edit), the path "
                "maps to NO backing table — DECLARE the backing table for that resource, or "
                "REMOVE the endpoint from the contract; the projector then reads it "
                "automatically."),
            "deliverability_frontend_fallback_page": (
                # #223: a route-wired GENERIC framework-fallback page, detected by
                # CONTENT fingerprint (#222 — marker-stripping doesn't clear it).
                # The registered-page variant rides ui_page_unwired; this covers
                # pages the registry can't see. Gate-minted → owner MUST be in
                # THIS map. FRONTEND.
                "frontend", "Author the real page for the fallback route (blocks delivery)",
                "a route is wired to the framework's GENERIC fallback page (top-nav + "
                "row list). Author the REAL page for that route: the reference "
                "screen's layout (open its crop/screenshot under design/), the "
                "route's real data fields, real working controls. Removing framework "
                "comments/attributes or reformatting API calls does NOT count — the "
                "gate fingerprints the page CONTENT, not markers."),
            "deliverability_dead_nav_link": (
                # #238 (tiktok r27 M1, runtime-verified): the app's own Profile+
                # Upload <Link>s pointed at routes App.jsx never wired → 404 on
                # click. Only the frontend lane owns both App.jsx routing and the
                # nav components. Gate-minted → owner MUST be in THIS map. FRONTEND.
                "frontend", "Fix the dead nav link (blocks delivery)",
                "a nav <Link to=...> / navigate(...) target resolves to NO route "
                "in App.jsx, so clicking that control hits the catch-all 404. For "
                "EACH flagged target: either add the missing <Route path=...> in "
                "App.jsx wired to the real page, or point the link at the correct "
                "existing route (e.g. a `/profile` link should go to the wired "
                "`/@:username` for the current user). The app's own navigation "
                "must not 404."),
            "deliverability_fabricated_field_fallback": (
                # #175 (gmrun9/gmrun10, live): the frontend renders `place.rating || '4.5'` /
                # `? place.name : 'HI Point Montara Lighthouse'` — invented data whenever the
                # field is absent (often ALWAYS, on a field-name drift). Gate-minted → owner
                # MUST be in THIS map. FRONTEND.
                "frontend", "Remove the fabricated member-field fallbacks (blocks delivery)",
                "the frontend renders a member field with a HARDCODED realistic fallback "
                "(`place.rating || '4.5'`, `? place.name : 'HI Point Montara Lighthouse'`) — "
                "fake data shown whenever the field is absent (often ALWAYS, if the field name "
                "drifted from the API response, e.g. `place.reviews` when the API returns "
                "`review_count`). For EACH flagged site: render ONLY the real field, and if it "
                "can be missing show an honest empty state ('—' / 'N/A') — never a realistic "
                "fake value. Fix any drifted field NAME to match the API response."),
            "deliverability_ui_flow_missing": (
                # A critical UI flow (login/signup/search/…) lacks a validation:ui_flow record.
                # Gate-minted but genuinely UNOWNED before (not in _GATE_OWNER / _COVERED_ELSEWHERE
                # / any helper) → logged "NO remediation owner" and relied on incidental clearing
                # (blocked gmrun12 M2). The VERIFIER runs+records the flow (non-destructive,
                # mirrors verification_checklist_not_ready); a genuinely broken flow routes on to
                # the frontend via bug_create. dead_artifacts is INTENTIONALLY left unowned — its
                # "wire-or-remove" remediation is destructive and needs a bespoke design.
                "verifier", "Record the missing critical UI flow validations (blocks delivery)",
                "one or more CRITICAL UI flows lack a validation:ui_flow record. run_validation to "
                "EXERCISE and RECORD each named flow (e.g. login / signup / search); if a flow just "
                "isn't recorded yet, run_validation records it; if a flow FAILS, bug_create for the "
                "owning lane (usually frontend) and re-run once fixed. Re-run until every critical "
                "flow has a passing validation:ui_flow record."),
            "deliverability_ui_flow_failed": (
                # #280 (r63, live): the delivered app's FYP feed ui_flow FAILED — the SPA
                # crashed post-login with "(void 0) is not a function" — and the gate logged
                # "NO remediation owner" and dead-ended delivery. _GATE_OWNER had ui_flow_
                # MISSING but not ui_flow_FAILED, so a merely-unrecorded flow was owned while a
                # genuinely BROKEN one was not — backwards. The verifier owns the walk; on a
                # failure it reads the recorded console/step evidence, locates the crash, and
                # bug_creates for the owning lane (usually frontend), mirroring ui_flow_missing.
                "verifier", "Fix the failing critical UI flow (blocks delivery)",
                "a CRITICAL UI flow has a FAILING validation:ui_flow record — the delivered app "
                "broke when the walk exercised it (e.g. a post-login SPA crash, a blank render, a "
                "dead control). Read the recorded reason + console_errors for the failing flow, "
                "bug_create for the owning lane (a JS/render crash or dead control is FRONTEND; a "
                "500/data gap is BACKEND) with the exact error, then re-run run_validation until "
                "the flow's validation:ui_flow record passes."),
            "verification_checklist_not_ready": (
                "verifier", "Record a green verification/build checklist (blocks delivery)",
                "the build checklist is NOT all-green — it needs the CodeHub checks "
                "build:database, build:docker, build:frontend, build:backend all = success. "
                "run_validation to RUN and RECORD them; if one is just unrecorded (pending), "
                "run_validation records it; if one FAILS, bug_create for the failing component "
                "(it routes to the owning lane) and re-run once fixed. Re-run until ready."),
        }
        # Owned by a bespoke helper, or framework-deterministic (re-runs/records itself),
        # or routed via the task's own assignee — NOT dead-ends, so don't log as uncovered.
        _COVERED_ELSEWHERE = {
            "deliverability_ui_page_unwired", "ui_page_unwired", "frontend_navigable",
            "deliverability_no_successful_run", "frontend_build_not_recorded",
            "validation_api_smoke_missing", "validation_ui_smoke_missing",
            "incomplete_required_tasks",
        }
        orch = self._orch
        try:
            if not failed_checks:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            guard = getattr(orch, "_gatecheck_owner_dispatched", None)
            if not isinstance(guard, dict):
                guard = {}
                orch._gatecheck_owner_dispatched = guard
            # PERSISTENCE RE-ARM (V29 stall): the guard below is one-shot per milestone.
            # If a dispatched wake doesn't resolve the check — the owning lane's turn
            # failed/idled, or (the v11/V29 bug fixed above) the verifier wake was
            # rejected — the one-shot guard blocked every retry and the gate spun to
            # fail-fast. Re-fire a STILL-failing owned check every _GATECHECK_REFIRE
            # declines instead of never (the stuck-abort is at 7 declines, so this yields
            # real retries first). Dup remediation tasks are kind=None, so they never
            # inflate the incomplete_required_tasks gate.
            _persist = getattr(orch, "_gatecheck_persist", None)
            if not isinstance(_persist, dict):
                _persist = {}
                orch._gatecheck_persist = _persist
            _GATECHECK_REFIRE = 3
            from tools.communication_tools import _create_message
            uncovered: List[str] = []
            # #328 (r93 dead-nav storm): a single gate decline surfaces one entry PER dead
            # link (7× 'deliverability_dead_nav_link'), and the persist-counter below treated
            # each in-list duplicate as a separate re-decline — firing 3 duplicate P0 tasks
            # (dup #1/#4/#7) and waking the lane 10× for one trivial fix. Collapse duplicates
            # so each DISTINCT check is handled once per gate-tick (order-preserving).
            for name in dict.fromkeys(str(r) for r in failed_checks):
                spec = _GATE_OWNER.get(name)
                if not spec:
                    if name not in _COVERED_ELSEWHERE:
                        uncovered.append(name)
                    continue
                if guard.get(name) == milestone:
                    # already dispatched this milestone — but re-fire a PERSISTING blocker
                    # every _GATECHECK_REFIRE declines so a wake that didn't land gets
                    # retried (V29: the verifier wake bounced and was never re-attempted).
                    _persist[name] = _persist.get(name, 0) + 1
                    if _persist[name] % _GATECHECK_REFIRE != 0:
                        continue  # storm control between re-fires
                else:
                    _persist[name] = 0
                owner, title, how = spec
                _extra = ""
                # #799: two more entries in this table told the lane to go and find something the
                # framework already computes — the same defect #798 fixed one row up.
                if name == "business_chain_api_coverage":
                    _unc799 = _uncovered_endpoints_799(orch)
                    if _unc799:
                        _extra = ("\n\nTHE UNCOVERED ENDPOINTS (computed by the same check that "
                                  "blocked you — cover THESE):\n- " + "\n- ".join(_unc799))
                elif name == "verification_checklist_not_ready":
                    _red799 = _red_checklist_checks_799(orch)
                    if _red799:
                        _extra = ("\n\nTHE CHECK(S) THAT ARE NOT GREEN right now:\n- "
                                  + "\n- ".join(_red799))
                if name == "business_chain_failing":
                    # FIX #148: the failing steps answering the projection's #124
                    # action-endpoint stub 404 need a BACKEND route, not a chain
                    # re-author — route the P0 to the lane that can add it.
                    _act = _chain_action_404s(orch)
                    if _act:
                        owner = "backend"
                        title = ("Implement the registered ACTION endpoint(s) — "
                                 "the projection serves a deliberate 404 stub "
                                 "(blocks delivery)")
                        how = (
                            "a verification chain hits contract-REGISTERED action "
                            "endpoint(s) answering the projection's 404 stub. The "
                            "framework does NOT project a semantically-unmappable "
                            "action route (a POST whose action segment maps to no "
                            "model) — YOUR handler must serve it, and it is missing/"
                            "unmounted. For EACH endpoint below, implement the real "
                            "action semantics in app/backend (e.g. custom_routes.py: "
                            "unfollow = delete the follows row) and register it "
                            "status=implemented; if a registration is junk/obsolete, "
                            "deprecate it via registryhub_deprecate_endpoint instead:"
                            "\n- " + "\n- ".join(_act[:8]))
                    else:
                        # #798: the general case — name the step the framework already knows broke,
                        # instead of telling the verifier to go and look it up.
                        _brk798 = _chain_broken_detail_798(orch)
                        if _brk798:
                            _extra = ("\n\nTHE BROKEN STEP(S), from the chain registry's own "
                                      "last_result — fix THESE, do not re-author the chain:\n- "
                                      + "\n- ".join(_brk798))
                # #70(b) (netflix r76, 2026-08-05): if the framework armed a deterministic chain
                # RE-RUN this tick (maybe_rerun_unrun_chains → orch._chain_rerun_armed) AND this
                # blocker is STILL owned by the verifier (i.e. the action-404 re-route above did
                # NOT flip it to backend for a real missing endpoint), SKIP the verifier RE-AUTHOR
                # dispatch this tick. The framework is re-running the EXISTING chains to settle
                # them green; dispatching the verifier in parallel makes it author MORE never-run
                # chains → run_chains never catches up (r76: 17→2 then green→regressed→restored
                # with 11 never-run chains, 0 delivery). Bounded: #475 caps at 4/milestone, so
                # once spent _chain_rerun_armed is False and this dispatch resumes; a genuinely-
                # BROKEN chain (where #475 no-ops) also leaves it False → verifier IS dispatched.
                if suppress_verifier_chain_reauthor(
                        name, owner, getattr(orch, "_chain_rerun_armed", False)):
                    continue
                if name == "business_chain_api_coverage":
                    # Hand the verifier the EXACT uncovered endpoints. The generic "cover the
                    # uncovered endpoints" left it guessing — run v17 got business_chain green
                    # + ui_page_unwired cleared, then stalled on api_coverage (3 chains / 32
                    # endpoints) and fail-fast aborted because it never knew WHICH endpoints
                    # were still uncovered. Re-derive the set exactly as the gate does.
                    try:
                        from .delivery_gate import _uncovered_business_endpoints
                        _rh = orch.hubs.registryhub
                        _chains = (_rh._verification_chains.value() or {})
                        _authored = [rec for n, rec in _chains.items()
                                     if n != "_meta" and isinstance(rec, dict) and rec.get("steps")]
                        _unc = _uncovered_business_endpoints(_rh, _authored)
                        if _unc:
                            _extra = (
                                "\n\nThese endpoints are exercised by NO chain yet — author ONE "
                                "dedicated coverage chain (auth round-trip first, then a step per "
                                "endpoint) that hits EACH of them, register it, and re-run "
                                "run_validation:\n- " + "\n- ".join(_unc))
                    except Exception:
                        pass
                if name == "deliverability_bare_authed_fetch":
                    # #154: hand the lane the EXACT call sites (file:line + URL).
                    # Imprecise diagnosis is why gmrun4's lane missed 7 repair
                    # attempts ("blank page" told it nothing about the token).
                    try:
                        from .frontend_audit import bare_authed_fetch_blockers
                        _root = getattr(orch, "output_dir", None)
                        if _root:
                            _off = bare_authed_fetch_blockers(
                                Path(_root) / "app" / "frontend" / "src")
                            if _off:
                                _extra = ("\n\nExact call sites:\n- "
                                          + "\n- ".join(_off[:10]))
                    except Exception:
                        pass
                if name == "deliverability_ui_flow_missing":
                    # FIX #284: hand the verifier the EXACT missing flow names + the
                    # contradiction that broke r68 (it broadcast "already recorded" for
                    # flows the hub never held). Generic #280 text gave a drifting verifier
                    # nothing to refute; the specific names + "re-read the hub" do.
                    _mf = _ui_flow_missing_names(orch)
                    if _mf:
                        _extra = _ui_flow_missing_extra(_mf)
                # #794: re-dispatch NAGS; it must not clone the task. The decline counter
                # deliberately re-dispatches a still-failing check every few minutes, and each
                # pass used to create a NEW P0 — r130 accumulated 13 copies of "Make
                # business_chain pass" ~4 min apart with the last FIVE simultaneously
                # `in_progress`. Cost: `incomplete_required_tasks` (a delivery blocker count)
                # inflates with clones of one problem, and an agent can claim copy #9 while
                # #10-13 sit unclaimed looking like unstarted work. The nag itself is kept —
                # only the duplicate row goes. Present in 8 of the last 22 corpus runs.
                _open794 = None
                try:
                    for _t in (orch.hubs.workhub.list_tasks() or []):
                        if (isinstance(_t, Mapping) and str(_t.get("title")) == title
                                and str(_t.get("status")) in ("pending", "in_progress", "open")):
                            _open794 = _t
                            break
                except Exception:
                    _open794 = None            # best-effort: on any fault, file as before
                if _open794 is not None:
                    task = _open794
                    try:
                        orch._logger.info(
                            "#794: `%s` still failing and an identical task (%s, %s) is already "
                            "open — re-waking %s instead of filing a duplicate P0.",
                            name, _open794.get("id"), _open794.get("status"), owner)
                    except Exception:
                        pass
                else:
                    task = orch.hubs.workhub.create_task(
                        title=title,
                        description=(
                            f"The `{name}` delivery-gate check FAILED.\n{how}{_extra}\n"
                            "Delivery stays blocked until a gate tick shows this check "
                            "green. Fix it, then finish."),
                        assignee=owner, agent="orchestrator", priority="P0")
                guard[name] = milestone
                _persist[name] = 0  # reset the decline counter on a (re-)dispatch
                _gmsg = _create_message(
                    source_agent_id="orchestrator", target_agent_id=owner,
                    content=(
                        f"URGENT: delivery is blocked on the `{name}` gate check. Claim "
                        f"task {(task or {}).get('id')} and fix it NOW, then finish."),
                    msg_type="task_ready", priority="urgent", persist=True,
                    tags=[name, "remediation"])
                # CRITICAL (v11 root cause, mirrors framework_validation.py:587): the
                # verifier's VerifierValidationTriggerPolicy REJECTS a task_ready that
                # lacks metadata["validation_phase"]=True ("requires explicit validation-
                # phase trigger", workflow_policies.py:369) — its tags [name,"remediation"]
                # do not intersect accepted_tags. V29: the gate-check coverage re-dispatch
                # to the verifier bounced 38× and the run STUCK-ABORTed with NO delivery.
                # The flag always satisfies the policy (workflow_policies.py:346); harmless
                # for non-verifier owners, so set it whenever the wake targets the verifier.
                if owner == "verifier":
                    _gmsg.metadata["validation_phase"] = True
                await orch.message_bus.send(_gmsg)
                orch._logger.warning(
                    "GATE-CHECK remediation dispatched to %s (task %s): %s",
                    owner, (task or {}).get("id"), name)
            # FIX C (V29 stall): incomplete_required_tasks is in _COVERED_ELSEWHERE
            # ("routed via the task's own assignee") — but the assignee may have FINISHED
            # and gone idle WITHOUT producing the task's required evidence (V29: the verifier
            # finished without re-running run_validation, so 3 validate_api_smoke tasks stayed
            # pending with NO driver -> co-stalled the gate). Re-wake the assignee of each
            # still-incomplete structural task (the tasks already exist — no new task) so an
            # idle owner is re-engaged. Same persistence re-fire + validation_phase injection
            # (verifier) as the gate-check dispatch above.
            if "incomplete_required_tasks" in failed_checks:
                _itn = "incomplete_required_tasks"
                _fire = True
                if guard.get(_itn) == milestone:
                    _persist[_itn] = _persist.get(_itn, 0) + 1
                    _fire = (_persist[_itn] % _GATECHECK_REFIRE == 0)
                else:
                    _persist[_itn] = 0
                if _fire:
                    try:
                        from .delivery_gate import incomplete_required_tasks as _irt
                        _by_assignee = {}
                        for _t in (_irt(orch.hubs) or []):
                            _a = str(_t.get("assignee") or "").strip()
                            if _a:
                                _by_assignee.setdefault(_a, []).append(_t)
                        for _a, _ts in _by_assignee.items():
                            _ids = ", ".join(str(t.get("id")) for t in _ts[:8])
                            _wmsg = _create_message(
                                source_agent_id="orchestrator", target_agent_id=_a,
                                content=(
                                    f"URGENT: delivery is blocked — you have {len(_ts)} "
                                    f"unfinished required task(s) whose evidence is still "
                                    f"missing ({_ids}). Claim + COMPLETE them now (verifier: "
                                    "re-run run_validation to record the missing per-endpoint "
                                    "contract tests), then finish."),
                                msg_type="task_ready", priority="urgent", persist=True,
                                tags=[_itn, "remediation"])
                            if _a == "verifier":
                                _wmsg.metadata["validation_phase"] = True
                            await orch.message_bus.send(_wmsg)
                        if _by_assignee:
                            guard[_itn] = milestone
                            _persist[_itn] = 0
                            orch._logger.warning(
                                "INCOMPLETE-TASK remediation re-woke %d assignee(s): %s",
                                len(_by_assignee), ", ".join(sorted(_by_assignee)))
                    except Exception:
                        pass
            # Dedup to once-per-CHANGE (mirrors #45) — _maybe_framework_deliver runs every
            # ≤60s loop, so an undeduped log would spam while the same checks persist.
            _uncov = sorted(uncovered)
            if _uncov and _uncov != getattr(orch, "_gatecheck_uncovered_last", None):
                orch._gatecheck_uncovered_last = _uncov
                orch._logger.warning(
                    "Delivery declined on gate check(s) with NO remediation owner "
                    "(needs a fix at source or an owner mapping): %s", _uncov)
        except Exception as exc:
            orch._logger.error("gate-level check dispatch failed: %s", exc)

    def detect_misplaced_frontend_root(self) -> Optional[Dict[str, Any]]:
        """Detect a frontend the lane authored at the REPO ROOT (``./src``) while
        the canonical ``app/frontend/src`` the framework builds+gates is the blank
        baseline. Observed live (gemini instagram 2026-06-13): the lane built a
        full Vite app at ``./src`` (10 routes, 8 pages, own ``./package.json``) —
        but docker uses ``build: ../app/frontend`` and the gate audits
        ``app/frontend/src``, so the real app was invisible and delivery saw a
        blank shell. Returns a small count summary when the repo-root tree is
        materially richer than the canonical one (→ misplaced), else None.
        Deterministic, best-effort — never raises."""
        orch = self._orch
        try:
            root_src = orch.output_dir / "src"
            canon_src = orch.output_dir / "app" / "frontend" / "src"
            if not root_src.is_dir():
                return None

            def _pages(p: Path) -> int:
                d = p / "pages"
                return len(list(d.glob("*.jsx")) + list(d.glob("*.tsx"))) if d.is_dir() else 0

            def _routes(p: Path) -> int:
                f = p / "App.jsx"
                if not f.is_file():
                    f = p / "App.tsx"
                try:
                    txt = f.read_text(encoding="utf-8", errors="ignore") if f.is_file() else ""
                except Exception:
                    txt = ""
                # count <Route …> elements but NOT the <Routes> wrapper (which
                # contains the substring "<Route") — match only when a delimiter
                # follows, so "<Routes>" is excluded.
                return len(re.findall(r"<Route[\s/>]", txt))

            rp, cp = _pages(root_src), _pages(canon_src)
            rr, cr = _routes(root_src), _routes(canon_src)
            # Misplaced when the repo-root tree is the real app and the canonical
            # one is (at most) the baseline shell — i.e. root is materially richer.
            if (rp >= 2 and rp > cp) or (rr >= 2 and rr > cr):
                return {"root_pages": rp, "canonical_pages": cp,
                        "root_routes": rr, "canonical_routes": cr}
            return None
        except Exception:
            return None

    async def dispatch_misplaced_frontend_root(self, info) -> None:
        """The frontend lane authored a real app at the REPO ROOT (``./src`` +
        ``./package.json``) instead of under ``app/frontend/`` — so docker
        (``build: ../app/frontend``) and the delivery gate (``app/frontend/src``)
        never see it and report a blank shell despite a full app existing. The
        framework does NOT move the lane's files (the lane owns the UI); it routes
        the fix back to the owner: ONE P0 task + urgent wake per milestone to
        RELOCATE the app into ``app/frontend/``. This is the ROOT-cause remedy for
        the ``ui_page_unwired`` block when the pages exist but at the wrong root —
        preferred over the per-page wiring dispatch, which would give misleading
        'wire each route' advice when the whole app just needs moving.
        Best-effort: never raises into the loop."""
        orch = self._orch
        try:
            if not info:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_misplaced_frontend_dispatched", None) == milestone:
                return
            task = orch.hubs.workhub.create_task(
                title="Move the frontend into app/frontend/ — it was built at the repo root (blocks delivery)",
                description=(
                    f"Your frontend app is at the REPO ROOT (./src/App.jsx + ./src/pages/ "
                    f"= {info.get('root_routes')} route(s) / {info.get('root_pages')} page(s)), "
                    f"but the framework builds and gates ONLY `app/frontend/` (currently "
                    f"{info.get('canonical_routes')} route(s) / {info.get('canonical_pages')} "
                    "page(s) — a blank shell). docker-compose uses `build: ../app/frontend` "
                    "and the delivery gate audits `app/frontend/src`, so your real app is "
                    "INVISIBLE to delivery. MOVE the whole app under app/frontend/: "
                    "app/frontend/src/App.jsx, app/frontend/src/pages/*.jsx, "
                    "app/frontend/src/components/*.jsx, app/frontend/src/services/api.js, "
                    "app/frontend/package.json, app/frontend/index.html, "
                    "app/frontend/vite.config.js — then delete the repo-root ./src + "
                    "./package.json + ./index.html + ./vite.config.js duplicates, and "
                    "finish. EVERY file-tool path must start with `app/frontend/`."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            orch._misplaced_frontend_dispatched = milestone
            from tools.communication_tools import _create_message
            await orch.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    f"URGENT: your frontend is at the repo ROOT (./src, "
                    f"{info.get('root_pages')} pages) but the framework only builds "
                    f"app/frontend/ — delivery sees a blank shell. Claim task "
                    f"{(task or {}).get('id')} and MOVE the app into app/frontend/ "
                    "(full app/frontend/src/... paths, delete the root duplicates), "
                    "then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["frontend_misplaced_root", "remediation"],
            ))
            orch._logger.warning(
                "MISPLACED-FRONTEND-ROOT remediation dispatched to frontend (task %s): "
                "repo-root=%s routes/%s pages vs canonical app/frontend=%s routes/%s pages",
                (task or {}).get("id"), info.get("root_routes"), info.get("root_pages"),
                info.get("canonical_routes"), info.get("canonical_pages"))
        except Exception as exc:
            orch._logger.error("misplaced-frontend-root dispatch failed: %s", exc)
