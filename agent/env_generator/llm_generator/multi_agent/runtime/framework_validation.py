"""Deterministic framework validation driver, extracted from the Orchestrator
(PROPOSAL #8 — FrameworkValidation; reviewed PASS as PROPOSAL #15).

Runs api_smoke + records the RunHub run the delivery gate requires, once the
contract is implemented and no gate-passing run exists — heal-on-change, capped
fast retries with a slow-retry downshift (PIPE-C2), and a stuck-loop escalation
ladder (re-dispatch → terminal signal → fail-fast abort, PROPOSAL #5). Also
self-triggers the verifier's validation pass (Design A) and routes failed-gate
feedback (GATE-C1 / frontend_navigable / business_chain) to the owning lanes.

STATELESS by design: the per-run state (``_framework_validation_attempts``,
``_verifier_triggered_impl_count``, and the ``_fwval_*`` family — healed_sig,
last_attempt_ts, last_impl_count, failure_set, stuck_count, stuck_blocker,
last_fail_detail, abort_reason) stays ON THE ORCHESTRATOR. This keeps three
contracts intact with zero churn: (1) the run() loop reads ``_fwval_abort_reason``
back via ``getattr(self, ...)`` after the call (NOT by reaching into this object);
(2) run()'s per-milestone reset writes those same fields on the orchestrator; and
(3) the shim constructs a fresh ``FrameworkValidation(self)`` per call so the
unbound methods still drive a bare orchestrator stub. The module-level pure
predicates (``_fwval_should_attempt`` etc.) + ``FWVAL_*`` constants remain in
orchestrator.py (unit-tested + imported there by tests) and are imported live —
CALL-TIME inside ``maybe_run`` (never module-top: that would cycle).
"""

from __future__ import annotations

import time
from typing import Any

from progress import EventType


class FrameworkValidation:
    """Deterministic api_smoke validation + stuck-loop escalation + lane
    feedback. Stateless; reads/writes the orchestrator's ``_fwval_*`` state and
    collaborators live via the back-ref."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    def rearm_owner_dispatch(self) -> None:
        """RESILIENCE: clear the per-milestone owner-dispatch guards so the existing
        ``_dispatch_*`` feedback helpers (business_endpoints → backend,
        frontend_navigable / unwired_ui_pages → frontend, business_chain → verifier)
        re-fire their P0 task + urgent wake for a failure set that has either CHANGED
        (genuine progress — the new gap deserves a fresh dispatch) or PERSISTED past
        the fast cap (stuck — re-wake the owner that's gone quiet). Reuses the
        existing dispatch machinery; invents no new control flow. Clearing the guard
        is safe — each ``_dispatch_*`` is idempotent within a milestone (it re-sets
        its own guard) and only acts when its specific check is still failing."""
        for _guard in (
            "_unimpl_routes_dispatched",
            "_frontend_navigable_dispatched",
            "_unwired_ui_pages_dispatched",
            "_chain_task_dispatched",
        ):
            try:
                setattr(self._orch, _guard, None)
            except Exception:
                pass
        # PROPOSAL #21: the per-check dispatch guard is a DICT (one entry per
        # failing check id) — clear it so a changed/persisting failure set re-fires
        # the dead_controls/reachable/endpoints-reachable/etc. dispatches too. Missing
        # this reset is the exact #20-family latent omission (a guard that never re-arms).
        try:
            self._orch._check_owner_dispatched = {}
        except Exception:
            pass

    async def maybe_run(self) -> None:
        """Deterministically run api_smoke + record the RunHub run when the
        contract is fully implemented and no gate-passing run exists yet.

        WHY: the verifier/orchestrator LLMs run run_validation too early
        (pre-merge → ~700ms fast-fail) and don't retry, so a WORKING app (proven:
        run_smoke_validation passes manually on the generated tree) never records
        the RunHub run the delivery gate requires (compute_deliverability blocker
        #1). This runs the SAME deterministic procedure (RunValidationTool: clean
        docker boot + live probe of every business endpoint + record_run/probes
        with framework authority) once per idle tick until it passes — natural
        retry across ticks as the merge/app settles. Capped so a genuinely broken
        app doesn't churn docker forever. Best-effort: never raises into the loop."""
        orch = self._orch
        try:
            from .lifecycle import all_business_endpoints_implemented
            from ..orchestrator import (
                _fwval_should_attempt, _fwval_failure_set, _fwval_stuck_decision,
                FWVAL_FAST_CAP)
            registryhub = getattr(orch.hubs, "registryhub", None)
            if registryhub is None:
                return
            # FIX #25: surface committed agent-branch work to integration every
            # tick (before the gate), so the integrated app reflects code the
            # lanes wrote+committed even before they finish-merge.
            orch._merge_committed_agent_work()
            # design/README.md is a delivery-gate required artifact but lives outside
            # the app-source signature, so scaffold it unconditionally (write-if-
            # missing) — cheap, and keeps the final delivery gate from failing an
            # otherwise-working app on a missing doc.
            orch._scaffold_design_readme()
            # OPTIMIZATION (heal-on-change): the deterministic heal repairs
            # (frontend baseline/api.js, backend entrypoint/AS-wiring/auth, ORM-DDL)
            # are idempotent, but re-running them EVERY coordination tick is wasteful
            # (the ORM introspection spawns a subprocess; file IO) and needlessly
            # races the lanes. Gate them on a CONTENT signature of the integrated app
            # source: heal only when the lanes actually changed something. CRUCIALLY,
            # reset the validation attempt-cap on that same change — FIX #31 only
            # reset on endpoint-COUNT increase, so an app made deliverable by a REPAIR
            # (e.g. the DDL/auth fix, not a new endpoint) stayed capped and never got
            # re-validated → no delivery. Now any real source change → fresh budget.
            _app_sig = orch._compute_app_source_signature()
            if _app_sig is None or _app_sig != getattr(orch, "_fwval_healed_sig", None):
                # SKELETON根治: regenerate the WHOLE backend from the contract FIRST, so
                # validation runs on the deterministic, by-construction app — not on the
                # lane's variably-structured one. The backend repairs below then no-op on
                # a correct skeleton (kept as a safety net); the frontend repairs still
                # matter (skeleton is backend-only).
                orch._generate_backend_skeleton()
                orch._scaffold_frontend_baseline()
                orch._repair_frontend_api()
                # FRONTEND SKELETON (PROPOSAL #19 — now actually wired; this was a
                # dead comment): project the contract-derived page set BEFORE
                # validation, so the ui_page-unwired gate validates the real
                # deliverable. Creates a stub per declared ui_page (only-if-missing)
                # and ADDITIVELY injects any declared route the lane omitted into its
                # own App.jsx (never clobbers lane routes/bodies). Re-applied EVERY
                # tick post-merge because the per-tick merge stashes+drops the
                # uncommitted working-tree write (the at-release call commits it).
                orch._scaffold_frontend_pages()
                orch._repair_backend_entrypoint()
                orch._repair_backend_as_wiring()
                orch._repair_backend_auth()
                orch._repair_backend_packaging()
                orch._repair_ddl_from_orm()
                orch._repair_handler_fk_aliases()
                orch._repair_psycopg_dsn()
                # PROPOSAL #41 (reviewer-corrected ROOT): COMMIT the framework-scaffolded
                # baseline (backend skeleton + frontend infra/api.js + projected
                # routes/pages) onto integration NOW — every tick, not just at release.
                # Run #38 aborted because the scaffold wrote src/services/api.js + the
                # frontend infra to the integration WORKING TREE but left them UNCOMMITTED;
                # the next per-tick merge stashes+drops uncommitted writes, so the COMMITTED
                # merge that RunValidationTool builds lacked api.js → vite "Could not resolve
                # ../services/api" → docker_up FAIL → no delivery. Committing here makes the
                # build (below) AND the lane's next pull_main_into_worktree see the baseline
                # (also fixing the frontend required-files finish-gate: the infra files now
                # reach the lane worktree). It also breaks the re-scaffold churn (the dropped
                # writes flipped the app-signature every tick). Best-effort; idempotent
                # ("nothing to commit" when already clean). Reuses the at-release commit.
                orch._commit_framework_delivery()
                # RESILIENCE (stuck-loop breaker): record the post-heal signature so
                # the heal-gate (line above) only re-heals when the *integrated source*
                # changed — but DO NOT reset the validation budget on that delta. The
                # heal/skeleton/DDL regeneration is the orchestrator's OWN output and is
                # not byte-stable across cycles (subprocess ORM introspection ordering,
                # write churn), so a post-heal-signature reset re-granted a fresh fast
                # budget EVERY cycle → the FAST cap never tripped → the SAME failing
                # validation cycle (merge → regen → run_validation → fail) spun every
                # ~60s forever with zero agent activity (observed: 36 identical cycles).
                # The fast budget is now reset ONLY on genuine LANE progress: a rising
                # implemented-endpoint count (below) or a CHANGED failure set (after the
                # validation result is known) — never on self-induced signature churn.
                orch._fwval_healed_sig = orch._compute_app_source_signature()
            # FIX #26: fire when the contract is implemented by registryhub registration
            # OR by route code present in the integrated source (registration lags
            # the actual code). api_smoke is the real arbiter downstream.
            if not (all_business_endpoints_implemented(registryhub.get_endpoints())
                    or orch._all_business_endpoints_have_route_code()):
                return
            session_ts = getattr(orch, "_session_start_ts", 0.0) or 0.0
            runhub = getattr(orch.hubs, "runhub", None)
            if runhub is not None and hasattr(runhub, "last_successful_run_since"):
                if runhub.last_successful_run_since(session_ts):
                    return  # already have a gate-passing run
            # FIX #31: reset the attempt cap on real progress. The 6-attempt
            # cap (anti-docker-churn) was exhausting in a ~5-min window WHILE the
            # app was still implementing/merging (instagram-core: all 6 attempts
            # 05:13-05:19 reported "app may still be booting/merging", then
            # endpoints kept landing until 05:37 — by which point the now-ready,
            # all-22-implemented app could NEVER be re-validated → no delivery).
            # Reset the counter whenever the implemented-endpoint count rises, so
            # validation keeps retrying as the app converges; the cap only bites
            # once the app is STABLE and still failing. Same self-reset shape as
            # FIX #28's ask_cap.
            try:
                from .lifecycle import business_endpoints
                _cur_impl = sum(
                    1 for e in business_endpoints(registryhub.get_endpoints() or {})
                    if isinstance(e, dict) and e.get("status") == "implemented"
                )
            except Exception:
                _cur_impl = 0
            if _cur_impl > getattr(orch, "_fwval_last_impl_count", -1):
                orch._fwval_last_impl_count = _cur_impl
                orch._framework_validation_attempts = 0
                # PROPOSAL #5: a rising implemented-endpoint count is REAL progress on the
                # second stable axis — reset the stuck counter too (today it resets only on a
                # failure-set change below), so an app still landing endpoints never counts
                # toward the fail-fast abort.
                orch._fwval_stuck_count = 0
            # PIPE-C2: cap the FAST (every-tick) retries to stop docker churn, but
            # past the cap DOWNSHIFT to a slow retry instead of hard-stopping — a
            # sig-stable app failing on transient docker contention must still
            # eventually record the gate-required RunHub run (else: silent budget
            # death, 0 release). _fwval_should_attempt gates the slow phase by a
            # wall-clock interval; attempts stays pinned at the cap (logs read 6/6).
            _attempts = getattr(orch, "_framework_validation_attempts", 0)
            _now = time.time()
            if not _fwval_should_attempt(
                    _attempts, getattr(orch, "_fwval_last_attempt_ts", 0.0), _now):
                return  # capped + within the slow-retry interval — wait, don't churn
            orch._fwval_last_attempt_ts = _now
            if _attempts < FWVAL_FAST_CAP:
                orch._framework_validation_attempts = _attempts + 1
            from tools.validation_tools import RunValidationTool
            tool = RunValidationTool(workspace=None)
            tool._hubs = orch.hubs
            tool._agent_id = "orchestrator"
            res = await tool.execute()
            # ── Verifier self-trigger (Design A — PROPOSAL #2, reviewed_version:2 PASS) ──
            # The deterministic driver (NOT the orchestrator LLM) wakes the verifier to run its
            # validation pass whenever api_smoke is ATTEMPTED on a bootable impl (we reach here
            # only past the route-code floor above), independent of the canonical
            # `validation_ready` signal — which needs ALL endpoints `implemented` and did NOT
            # fire in run #15 (validation_ready count=0), leaving the verifier idle
            # `awaiting ['frontend']` forever because the frontend finished notify=[] (Defect C).
            # Re-armable, keyed to the impl epoch (`_fwval_last_impl_count`): one guarded message
            # per epoch (no storm); re-fires after the impl lanes implement MORE endpoints —
            # i.e. after they fix the bugs the verifier filed. Placed AFTER tool.execute() so the
            # verifier validates a SETTLED docker stack (no contention with the framework's own
            # api_smoke boot), but fired UNCONDITIONALLY (not gated on the api_smoke result). Do
            # NOT move this above the passing-run early-return: once a clean run exists this
            # function returns first and the canonical `validation_ready` (all-implemented) path
            # owns the verifier — this driver trigger is the failing/pre-pass regime only.
            # DEPENDS ON a3aea89: task_ready must wake an IDLE resident lane
            # (allow_resident_wakeup → allow_task_ready); if reverted this silently no-ops
            # (guarded by tests/test_verifier_validation_trigger.py).
            try:
                _epoch = getattr(orch, "_fwval_last_impl_count", -1)
                if orch._verifier_trigger_due(
                        _epoch, getattr(orch, "_verifier_triggered_impl_count", -1)):
                    from tools.communication_tools import _create_message
                    _vmsg = _create_message(
                        source_agent_id="orchestrator", target_agent_id="verifier",
                        content=(
                            "Implementation is bootable and api_smoke is being validated — run "
                            "your validation pass now: docker_up -> the 5 check categories "
                            "(build:docker / build:frontend / validation:api_smoke / "
                            "validation:ui_smoke / validation:ui_flow:<name>) -> bug_create per "
                            "failure -> route summary -> finish."
                        ),
                        msg_type="task_ready", priority="urgent", persist=True,
                    )
                    # _create_message has NO metadata kwarg; inject the explicit-trigger key
                    # post-construction. validation_phase=True alone satisfies
                    # VerifierValidationTriggerPolicy.explicit_trigger (workflow_policies.py:327),
                    # with zero dependence on env-configured accepted_tags/phases/keywords.
                    _vmsg.metadata["validation_phase"] = True
                    await orch.message_bus.send(_vmsg)
                    orch._verifier_triggered_impl_count = _epoch
                    orch._logger.info(
                        "Orchestrator triggered verifier validation pass (impl epoch=%s; "
                        "validation_ready not required).", _epoch,
                    )
            except Exception as _vte:
                orch._logger.debug("verifier validation trigger skipped: %s", _vte)
            data = getattr(res, "data", None) if res is not None else None
            # CHAINS-BLOCKED early-exit (round 39 deadlock): RunValidationTool
            # refuses to run until chains are registered, returning a fail with
            # data=None. The framework validation shares that tool — so a
            # missing-chains block looks like "no checks returned" AND #53's
            # data.checks scan finds nothing. Detect the block via the error
            # string and SYNTHESIZE a business_chain-fail check so the #53
            # dispatch path below fires (verifier gets the P0 task).
            _err = getattr(res, "error_message", "") or "" if res is not None else ""
            if (not data) and "no verification chains" in _err.lower():
                data = {"summary": "blocked: no verification chains registered",
                        "checks": [{"name": "business_chain", "status": "fail",
                                    "detail": _err}]}
            if data and data.get("runhub_run_id"):
                orch._logger.warning(
                    "Framework validation: api_smoke PASSED → recorded RunHub run %s "
                    "(%s endpoints) — delivery-gate run requirement satisfied.",
                    data.get("runhub_run_id"), data.get("endpoints_tested"),
                )
                await orch._maybe_run_visual_fidelity()
            else:
                # FIX #36: log WHY the in-run validation failed (summary + failed
                # check names). The bare "not yet passing" hid the real cause for
                # a whole 2-hour run — the app passes api_smoke when booted by
                # hand, so the in-run failures are environmental (docker
                # contention / build-under-load) and we need the detail to fix it.
                _summ = (data or {}).get("summary", "?")
                _failed = [
                    f"{c.get('name')}:{(c.get('detail') or '')[:60]}"
                    for c in ((data or {}).get("checks") or [])
                    if c.get("status") == "fail"
                ]
                orch._logger.warning(
                    "Framework validation attempt %s/6: api_smoke NOT passing — %s "
                    "| failed=%s",
                    orch._framework_validation_attempts, str(_summ)[:200],
                    _failed or "(no checks returned)",
                )
                # RESILIENCE (stuck-loop breaker): track the FAILURE SET (the set of
                # failing check ids) across validations. A CHANGED failure set is
                # genuine lane-driven progress (a check now passes, or a new one
                # fails) → grant a fresh fast budget and reset the stuck counter, so a
                # converging app is never slowed. An UNCHANGING failure set means the
                # last fast-cap of validations achieved nothing — the lanes are idle
                # and the orchestrator is re-running the identical cycle (the 36-cycle
                # spin). The self-induced heal/skeleton churn no longer resets the
                # budget (above), so the fast cap now actually trips; once it does on a
                # stable failure set we ESCALATE rather than spin to wall-clock.
                _fset = _fwval_failure_set(data)
                _prev_fset = getattr(orch, "_fwval_failure_set", None)
                if _prev_fset is None or _fset != _prev_fset:
                    # New/changed failure set → real progress (or first observation).
                    orch._fwval_failure_set = _fset
                    orch._fwval_stuck_count = 0
                    if _prev_fset is not None:
                        # An actual change (not the first sight) → fresh fast budget,
                        # exactly like a rising endpoint count (FIX #31).
                        orch._framework_validation_attempts = 0
                        # Re-arm the per-milestone owner-dispatch guards so the
                        # next-failure feedback can fire afresh for the new failure set.
                        orch._fwval_rearm_owner_dispatch()
                else:
                    # Same failure set as last validation → no functional progress.
                    orch._fwval_stuck_count = getattr(orch, "_fwval_stuck_count", 0) + 1
                    # Only escalate once the FAST budget is spent (the converging
                    # window is over); below the cap we are still in the normal
                    # fast-retry phase and must not interfere with a healthy run.
                    if _attempts >= FWVAL_FAST_CAP:
                        _stage = _fwval_stuck_decision(orch._fwval_stuck_count)
                        if _stage == "redispatch":
                            # Re-wake the lane(s) that own the failing dimension: the
                            # existing per-milestone _dispatch_* guards have gone quiet
                            # (one dispatch per milestone), so re-arm them — the
                            # _dispatch_* calls below will then re-fire the owner task +
                            # urgent wake for this specific, persisting failure set.
                            orch._fwval_rearm_owner_dispatch()
                            orch._logger.warning(
                                "STUCK-LOOP ESCALATION: framework validation has failed "
                                "on the SAME failure set %s for %s post-cap cycles with no "
                                "lane progress — re-dispatching the owning lane(s).",
                                sorted(_fset) or "(none)", orch._fwval_stuck_count,
                            )
                        elif _stage == "terminal":
                            # Re-dispatch did not break the stall → surface a clear,
                            # terminal "stuck on <blocker>" signal so the run stops
                            # churning to wall-clock and the UI/monitor shows the real
                            # blocker (instead of looking dead with idle lanes + a
                            # spinning orchestrator). We do NOT hard-kill here — the run
                            # budget cap is the terminator; this downshifts the cadence
                            # (attempts pinned at the cap → slow interval) and makes the
                            # blocker visible exactly once.
                            _blocker = ", ".join(sorted(_fset)) or (str(_summ)[:120] or "unknown")
                            if getattr(orch, "_fwval_stuck_blocker", None) != _blocker:
                                orch._fwval_stuck_blocker = _blocker
                                orch._logger.error(
                                    "STUCK: framework validation is wedged on %s — the "
                                    "same failure set has persisted for %s post-cap "
                                    "cycles with no lane progress AND re-dispatch did not "
                                    "help. Downshifting to the slow re-validation "
                                    "interval; the run will end on its budget cap unless "
                                    "a lane makes progress. Real blocker: %s",
                                    _blocker, orch._fwval_stuck_count, str(_summ)[:200],
                                )
                                try:
                                    orch.progress.emit(
                                        EventType.PHASE_ERROR,
                                        "Framework Validation",
                                        {"error": f"stuck on {_blocker}",
                                         "failure_set": sorted(_fset),
                                         "cycles": orch._fwval_stuck_count},
                                    )
                                except Exception:
                                    pass
                        elif _stage == "abort":
                            # PROPOSAL #5 — terminal-surface ALSO did not help: redispatch +
                            # the terminal warning have run and the SAME failure set still
                            # persists with no lane progress. This is an unrecoverable
                            # framework-generation bug the in-run agents cannot fix (the
                            # framework regenerates the same artifact every cycle). FAIL FAST:
                            # record the abort reason WITH the real root — the failing checks'
                            # detail, which now carries the S1 crashed-container logs (PROPOSAL
                            # #3) — so the delivery-wait loop terminates and raises a
                            # root-surfacing message instead of limping to the wall-clock.
                            _blocker = ", ".join(sorted(_fset)) or (str(_summ)[:120] or "unknown")
                            _root_detail = "; ".join(
                                "{}: {}".format(c.get("name"), str(c.get("detail"))[:400])
                                for c in ((data or {}).get("checks") or [])
                                if isinstance(c, dict) and c.get("status") == "fail"
                                and c.get("detail")
                            )[:1500] or (str(_summ)[:400] or "(no detail)")
                            orch._fwval_last_fail_detail = _root_detail
                            orch._fwval_abort_reason = (
                                "framework validation wedged on [{}] for {} post-cap cycles "
                                "with no lane progress (re-dispatch + terminal escalation did "
                                "not help). Real blocker: {}".format(
                                    _blocker, orch._fwval_stuck_count, _root_detail)
                            )
                            orch._logger.error("STUCK-ABORT: %s", orch._fwval_abort_reason)
                            try:
                                orch.progress.emit(
                                    EventType.PHASE_ERROR, "Framework Validation",
                                    {"error": "stuck-abort: {}".format(_blocker),
                                     "failure_set": sorted(_fset),
                                     "cycles": orch._fwval_stuck_count, "abort": True},
                                )
                            except Exception:
                                pass
                # GATE-C1 feedback loop: a business_endpoints_implemented FAIL
                # (registered-implemented endpoint answering 404/405) routes to
                # the backend lane — a hard gate with no exit deadlocks the run.
                await orch._dispatch_unimplemented_routes(data)
                # frontend_navigable feedback loop: a blank-shell frontend (0
                # routes) otherwise pins validation red with no path back to the
                # lane that owns the UI.
                await orch._dispatch_frontend_navigable(data)
                # PROPOSAL #21: re-dispatch the OTHER lane-actionable failing checks
                # that previously routed NOWHERE (frontend_dead_controls/reachable →
                # frontend; business_endpoints_reachable/correct_shape/auth_enforced_401/
                # writes_persist → backend). Without this, an idle owning lane is never
                # re-woken for these (run #4: frontend idle 30min on dead_controls) →
                # api_smoke never goes unanimous-green → no RunHub gate run → no delivery.
                await orch._dispatch_failing_checks(data)
                # Mechanism #53 (round 33 deadlock): business_chain failing
                # because the verifier never authored verification_chains.json
                # must CLOSE THE LOOP — the chain fallback was removed (user
                # decision: agent feedback over framework content), so the
                # framework must actually deliver that feedback: one P0 task +
                # urgent wake per milestone, carrying the authoring spec.
                # Match VERB-INDEPENDENTLY (the chain_executor wording moved
                # authored→registered when chains became registry-backed; the
                # old literal "authored" match silently broke #53 — found in
                # the 2026-06-12 scheduling audit). Key on the stable prefix.
                _chain_fail = next(
                    (c for c in ((data or {}).get("checks") or [])
                     if c.get("name") == "business_chain"
                     and c.get("status") == "fail"
                     and "no verification chains" in str(c.get("detail") or "")),
                    None)
                if _chain_fail and getattr(orch, "_chain_task_dispatched", None) == \
                        getattr(orch, "_current_milestone_version", ""):
                    # already dispatched but STILL failing → the verifier has
                    # not digested it (round 34: a 97-message inbox swallowed
                    # the first wake). Re-nudge, urgent, no duplicate task.
                    try:
                        from tools.communication_tools import _create_message
                        await orch.message_bus.send(_create_message(
                            source_agent_id="orchestrator",
                            target_agent_id="verifier",
                            content=(
                                "STILL BLOCKED on business_chain: you have not "
                                "registered any verification chains. Drop "
                                "everything, claim your P0 chain task, and "
                                "register them via "
                                "registryhub_register_verification_chain, then "
                                "run_validation."),
                            msg_type="task_ready", priority="urgent",
                            persist=True, tags=["verification_chains", "renudge"],
                        ))
                        orch._logger.warning(
                            "CHAIN-AUTHORING re-nudge sent to verifier.")
                    except Exception:
                        pass
                if _chain_fail and getattr(orch, "_chain_task_dispatched", None) != \
                        getattr(orch, "_current_milestone_version", ""):
                    orch._chain_task_dispatched = getattr(
                        orch, "_current_milestone_version", "")
                    try:
                        from .chain_executor import AUTHORING_INSTRUCTIONS
                        _ct = orch.hubs.workhub.create_task(
                            title="Register verification chains (blocks delivery)",
                            description=(
                                "The business_chain delivery check FAILS until you "
                                "register chains. " + AUTHORING_INSTRUCTIONS +
                                " Derive the chains from THIS app's registered endpoints "
                                "(registryhub_list_endpoints) and the kickoff user_flows, "
                                "register each via registryhub_register_verification_chain, "
                                "then re-run run_validation."),
                            assignee="verifier",
                            agent="orchestrator",
                            priority="P0",
                        )
                        from tools.communication_tools import _create_message
                        await orch.message_bus.send(_create_message(
                            source_agent_id="orchestrator",
                            target_agent_id="verifier",
                            content=(
                                "URGENT: delivery is blocked on business_chain — you have "
                                "registered no verification chains. Claim task "
                                f"{(_ct or {}).get('id')} and register them via "
                                "registryhub_register_verification_chain NOW, then "
                                "run_validation."),
                            msg_type="task_ready",
                            priority="urgent",
                            persist=True,
                            tags=["verification_chains", "remediation"],
                        ))
                        orch._logger.warning(
                            "CHAIN-AUTHORING remediation dispatched to verifier "
                            "(task %s).", (_ct or {}).get("id"))
                    except Exception as _cd_exc:
                        orch._logger.error(
                            "chain-authoring dispatch failed: %s", _cd_exc)
        except Exception as exc:  # never break the coordination loop
            orch._logger.error("framework validation raised (non-fatal): %s", exc)
