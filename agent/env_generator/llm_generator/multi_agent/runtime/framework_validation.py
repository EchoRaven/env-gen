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
from typing import Any, Mapping, Optional

from progress import EventType


def snapshot_passing_chains(orch: Any) -> None:
    """REGRESSION GUARD (snapshot-on-green): called when api_smoke fully passes
    (business_chain green). Snapshot the verification chains + the contract
    (endpoint id set) onto the orchestrator, so a later regression of
    business_chain WHILE the contract is unchanged — an agent re-authored a
    chain into a broken state (smoke run #9: a re-authored chain dropped
    tenant_id from login → 401 → a 1-check-from-delivery app churned back to
    broken) — can be reverted via ``restore_regressed_chains``. Best-effort."""
    try:
        rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
        if rh is None:
            return
        orch._chains_snapshot = dict(rh._verification_chains.value() or {})
        orch._chains_snapshot_endpoints = set((rh.get_endpoints() or {}).keys())
        orch._fwval_green_high_water = (
            getattr(orch, "_fwval_green_high_water", None) or set()
        ) | {"business_chain"}
        # FREEZE-ON-GREEN (2026-07-01): business_chain is green → record the contract it's
        # green FOR on the RegistryHub, so register_verification_chain refuses to RE-AUTHOR an
        # existing (passing) chain into a broken one while the contract is unchanged. This
        # stops the verifier re-break ↔ regression-guard-restore OSCILLATION that wedged
        # delivery for 75min (run-25) at the SOURCE (the restore only reverts after the fact).
        # A CHANGED contract (next milestone) has a different eps set → auto-unfrozen.
        try:
            rh._chains_frozen_eps = set(orch._chains_snapshot_endpoints)
        except Exception:
            pass
    except Exception:
        pass


def _fwval_chain_signature(orch: Any) -> Optional[str]:
    """A stable hash of the AUTHORED verification-chain content (each chain's name +
    steps), EXCLUDING per-run execution metadata (last_result / last_run_at /
    _updated_at / status), which changes every validation. A CHANGED signature ⇒ the
    verifier RE-AUTHORED a chain (real convergence progress the check-level failure set
    can't see). None on any failure (never gates on a hash error). Fix #71."""
    import hashlib
    import json as _json
    try:
        rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
        if rh is None:
            return None
        chains = dict(rh._verification_chains.value() or {})
        content = {
            str(name): (c.get("steps") if isinstance(c, Mapping) else None)
            for name, c in chains.items()
            if not str(name).startswith("_")
        }
        blob = _json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
    except Exception:
        return None


def _fwval_is_chain_authoring_progress(fset, chain_sig, prev_chain_sig,
                                       chain_churn, cap) -> bool:
    """True iff business_chain is the ONLY blocker AND the verifier RE-AUTHORED the
    chains (content signature changed) AND the bounded churn budget isn't spent — the
    verifier is actively converging a chain the check-level failure set can't see, so
    the stuck counter should reset (run-60). Bounded by ``cap`` so a verifier that
    oscillates FOREVER still aborts (no livelock). Fix #71."""
    try:
        return bool(
            fset and set(fset) <= {"business_chain"}
            and chain_sig is not None and prev_chain_sig is not None
            and chain_sig != prev_chain_sig
            and (chain_churn or 0) < cap)
    except Exception:
        return False


def maybe_refresh_stale_build_checklist(orch: Any, failed_checks) -> bool:
    """FIX #120 (run-38 STUCK, 2026-07-09): a transient run_validation failure
    (mid visual-window rebuild churn) stamped all four ``build:*`` CodeHub checks =
    failure, and NOTHING re-ran validation afterwards — the checklist remediation
    messages the VERIFIER (LLM-dependent; it never complied), so an
    otherwise-deliverable run hit the 75-min no-convergence wall on
    ``verification_checklist_not_ready`` alone. Deterministic self-heal: when the
    deliver gate declines with that blocker, reset the framework's own api_smoke
    attempt counter (BOUNDED per milestone) so the fast retry re-runs validation —
    the shared RunValidationTool records FRESH build:* truth either way (a pass
    supersedes the stale failure; a real failure re-records with fresh evidence).
    Returns True when a refresh was armed. Never raises."""
    try:
        if "verification_checklist_not_ready" not in set(failed_checks or ()):
            return False
        ms = str(getattr(orch, "_current_milestone_version", "") or "")
        budget = getattr(orch, "_checklist_refresh_by_ms", None)
        if budget is None:
            budget = {}
            orch._checklist_refresh_by_ms = budget
        if budget.get(ms, 0) >= 3:
            return False
        budget[ms] = budget.get(ms, 0) + 1
        orch._framework_validation_attempts = 0
        try:
            orch._logger.warning(
                "STALE BUILD-CHECKLIST self-heal (FIX #120): "
                "verification_checklist_not_ready is blocking delivery — resetting "
                "the framework validation attempt counter (refresh %s/3 for v%s) so "
                "api_smoke re-runs and records FRESH build:* checks itself.",
                budget[ms], ms)
        except Exception:
            pass
        return True
    except Exception:
        return False


def restore_regressed_chains(orch: Any, fset):
    """REGRESSION GUARD (restore-on-regression): if business_chain passed before
    (high-water) and is now failing AND the contract (endpoint id set) is
    unchanged, an agent re-authored the chains into a broken state — not a real
    app/contract change. Replace the chains store with the last-passing snapshot
    (FULL replace, so a NEW broken chain is dropped too), re-validate next tick,
    and drop business_chain from the failure set so the verifier is NOT
    re-dispatched to re-author (which would loop). Self-correcting: if the app
    genuinely broke, the restored-correct chain still fails and (current ==
    snapshot) so the restore is skipped and normal feedback proceeds — never
    masks a real defect. Returns the (possibly-reduced) failure set."""
    try:
        rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
        snap = getattr(orch, "_chains_snapshot", None)
        if (rh is None or not snap
                or "business_chain" not in (getattr(orch, "_fwval_green_high_water", None) or set())
                or "business_chain" not in fset):
            return fset
        cur_eps = set((rh.get_endpoints() or {}).keys())
        snap_eps = getattr(orch, "_chains_snapshot_endpoints", cur_eps)
        if cur_eps == snap_eps and dict(rh._verification_chains.value() or {}) != snap:
            restore = dict(snap)
            rh._verification_chains.update(
                lambda _v: restore, change_info={"agent": "regression-guard"})
            orch._framework_validation_attempts = 0
            orch._logger.warning(
                "REGRESSION GUARD: business_chain was green then regressed with the "
                "contract unchanged — restored the last-passing verification chains "
                "(agent re-authoring reverted).")
            return fset - {"business_chain"}
    except Exception:
        pass
    return fset


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
        # V29 STALL: the gate-LEVEL owner-dispatch guard (dispatch_gate_level_checks,
        # one entry per delivery-gate check id) is ALSO a one-shot-per-milestone dict
        # that this rearm omitted — so a delivery-gate blocker stranded by a LATE-
        # registered endpoint (V29: 3 endpoints registered AFTER the coverage chain)
        # never re-dispatched its owner. Clear it (and its decline counter) too; same
        # idempotence guarantee (each dispatch only acts while its check still fails).
        try:
            self._orch._gatecheck_owner_dispatched = {}
            self._orch._gatecheck_persist = {}
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
                _fwval_can_early_return, FWVAL_FAST_CAP, FWVAL_CHAIN_CHURN_CAP)
            _FWVAL_CHAIN_CHURN_CAP = FWVAL_CHAIN_CHURN_CAP
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
            # FIX #107 (instagram run-25, live): the heal-on-change gate SKIPPED every
            # repair while docker_up wedged 7 cycles — the lane's diagnosis edits never
            # reached integration, so the signature stayed constant and the frontend
            # import/export reconcilers (which fix exactly this build-failure class,
            # and DID fix run-25's App.jsx when run directly) never fired. When the
            # last failure set contains a BUILD-class check, force the heal pass —
            # the repairs are idempotent; the wasteful-tick concern is the healthy path.
            _build_wedged = bool(
                {"docker_up", "frontend_build"} & set(
                    getattr(orch, "_fwval_failure_set", None) or ()))
            if (_app_sig is None or _build_wedged
                    or _app_sig != getattr(orch, "_fwval_healed_sig", None)):
                # SKELETON根治: regenerate the WHOLE backend from the contract FIRST, so
                # validation runs on the deterministic, by-construction app — not on the
                # lane's variably-structured one. The backend repairs below then no-op on
                # a correct skeleton (kept as a safety net); the frontend repairs still
                # matter (skeleton is backend-only).
                orch._generate_backend_skeleton()
                # Regenerate the DB schema SQL onto integration EVERY tick too — the
                # backend/frontend analogue. _generate_database (orchestrator startup,
                # post-kickoff) wrote app/database/init/01_init.sql ONCE while output_dir
                # was on `main`, so it never reached the `integration` tree the delivery
                # gate globs / create_release snapshots; the per-tick merge then dropped
                # the working-tree copy and docker recreated the bind-mount dir as ROOT,
                # so database_has_sql() stayed False → database_sql_missing wedged
                # delivery FOREVER (instagram_v2/v3: api_smoke green, never delivered).
                # Writing it HERE (on integration, pre-docker) means _commit_framework_
                # delivery below ships it AND docker mounts a populated haibo-owned dir.
                try:
                    await orch._generate_database()
                except Exception as _db_exc:
                    orch._logger.warning("per-tick database scaffold failed: %s", _db_exc)
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
            # CHAIN-AUTHORING proactive trigger (root fix for "verifier never authors
            # chains", run v11): business_chains are CONTRACT-derived — the verifier can
            # author them the moment the backend contract is implemented, WITHOUT a booting
            # app or a finished frontend. The canonical ``validation_ready`` emission is
            # one-shot (fires on the single status-transition that completes the contract)
            # and was missed in v11; the docker-gated verifier trigger below only fires once
            # the stack BOOTS, which a frontend stall blocks — so the verifier sat idle and
            # delivery failed on ``business_chain_missing`` with the contract fully built.
            # Here: contract is complete (we passed the gate above) — if NO chain is
            # registered yet, wake the verifier with an ACCEPTED signal
            # (validation_phase=True is honored by VerifierValidationTriggerPolicy with zero
            # dependence on env tags/phases). Re-armable while chains stay missing, with a
            # wall-clock dedup so it never storms. Domain-agnostic.
            try:
                _vc = getattr(registryhub, "_verification_chains", None)
                _have_chains = bool(_vc.value()) if _vc is not None else True
                _last_ct = getattr(orch, "_chain_authoring_trigger_ts", 0.0)
                if (not _have_chains) and (time.time() - _last_ct) > 90.0:
                    orch._chain_authoring_trigger_ts = time.time()
                    from tools.communication_tools import _create_message
                    _cmsg = _create_message(
                        source_agent_id="orchestrator", target_agent_id="verifier",
                        content=(
                            "Backend contract is FULLY IMPLEMENTED but NO verification "
                            "chains are registered — delivery will fail on business_chain. "
                            "Author them NOW from the registered endpoints "
                            "(registryhub_list_endpoints): one business_chain per critical "
                            "flow (auth round-trip -> create -> read-back -> cross-user "
                            "isolation), register each via "
                            "registryhub_register_verification_chain. This does NOT need a "
                            "running app or a finished frontend — author against the "
                            "contract, then run_validation when the stack is up."),
                        msg_type="task_ready", priority="urgent", persist=True,
                        tags=["verification_chains", "author_proactive"],
                    )
                    # _create_message has NO metadata kwarg; inject post-construction.
                    _cmsg.metadata["validation_phase"] = True
                    await orch.message_bus.send(_cmsg)
                    orch._logger.info(
                        "CHAIN-AUTHORING proactive trigger sent to verifier "
                        "(contract complete, no chains registered yet).")
            except Exception as _cae:
                orch._logger.debug("chain-authoring proactive trigger skipped: %s", _cae)
            # SEED-AUTHORING proactive nudge (same shape as the chain trigger): the backend
            # agent OWNS app/backend/seed_data.json (realistic demo data), but the prompt alone
            # is a weak forcing function — it may never author it (→ bland embedded _SEED
            # fallback) or leave the framework PLACEHOLDER titles (outlook seed1/seed2,
            # 2026-06-29). Past the impl gate above, if the agent's seed is ABSENT or
            # PLACEHOLDER, wake the backend lane with a concrete task. SOFT (the fallback keeps
            # the app functional → never a hard delivery block) + wall-clock-deduped so it never
            # storms; self-terminating once the seed is realistic. Domain-agnostic.
            try:
                from .backend_skeleton import audit_agent_seed
                from pathlib import Path as _Path
                _be = _Path(getattr(orch, "output_dir", "") or ".") / "app" / "backend"
                _sa = audit_agent_seed(_be)
                _last_st = getattr(orch, "_seed_authoring_trigger_ts", 0.0)
                if _sa.get("issues") and (time.time() - _last_st) > 120.0:
                    orch._seed_authoring_trigger_ts = time.time()
                    from tools.communication_tools import _create_message
                    _smsg = _create_message(
                        source_agent_id="orchestrator", target_agent_id="backend",
                        content=("SEED DATA needs work — " + " ".join(_sa["issues"]) +
                                 " Author app/backend/seed_data.json with realistic, FK-valid, "
                                 "domain-specific rows per your SEED DATA instructions (real "
                                 "email subjects/names/descriptions, owners set, derived counts "
                                 "matching). The framework loader reads it + backfills owners/"
                                 "images, so a populated, real-looking preview ships instead of "
                                 "the bland default."),
                        msg_type="task_ready", priority="high", persist=True,
                        tags=["seed_data", "author_proactive"],
                    )
                    _smsg.metadata["validation_phase"] = True
                    await orch.message_bus.send(_smsg)
                    orch._logger.info(
                        "SEED-AUTHORING nudge sent to backend (%s).",
                        "absent" if not _sa.get("authored") else
                        f"placeholder:{_sa.get('placeholder_tables')}")
            except Exception as _sae:
                orch._logger.debug("seed-authoring nudge skipped: %s", _sae)
            session_ts = getattr(orch, "_session_start_ts", 0.0) or 0.0
            runhub = getattr(orch.hubs, "runhub", None)
            if runhub is not None and hasattr(runhub, "last_successful_run_since"):
                # A gate-passing api_smoke run lets us stop — UNLESS the delivery gate is
                # STILL blocked on business_chain_failing (the verifier registered chains but
                # its own run failed, e.g. a stale worktree missing the framework Dockerfile).
                # In that case fall through to RE-RUN validation so the FRAMEWORK validates the
                # chains from the integration tree — decoupling milestone advance from the
                # flaky/idle verifier (outlook-seed1, 2026-06-29). _fwdeliver_last_failed is the
                # delivery gate's failed-check set, cached by _maybe_framework_deliver each tick.
                if _fwval_can_early_return(
                        bool(runhub.last_successful_run_since(session_ts)),
                        getattr(orch, "_fwdeliver_last_failed", None)):
                    return  # gate-passing run AND business_chain not blocking → done
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
                snapshot_passing_chains(orch)
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
                _fset = restore_regressed_chains(orch, _fset)
                _prev_fset = getattr(orch, "_fwval_failure_set", None)
                _chain_sig = _fwval_chain_signature(orch)
                if _prev_fset is None or _fset != _prev_fset:
                    # New/changed failure set → real progress (or first observation).
                    orch._fwval_failure_set = _fset
                    orch._fwval_stuck_count = 0
                    orch._fwval_chain_churn = 0   # #71: fresh chain-churn budget per failure set
                    orch._fwval_chain_sig = _chain_sig
                    if _prev_fset is not None:
                        # An actual change (not the first sight) → fresh fast budget,
                        # exactly like a rising endpoint count (FIX #31).
                        orch._framework_validation_attempts = 0
                        # Re-arm the per-milestone owner-dispatch guards so the
                        # next-failure feedback can fire afresh for the new failure set.
                        orch._fwval_rearm_owner_dispatch()
                # CHAIN-AUTHORING PROGRESS (#71, run-60): business_chain is the only
                # persistent blocker AND the verifier RE-AUTHORED the chains (their
                # content signature changed) since the last validation → real convergence
                # progress the check-level failure set can't see. Reset the stuck counter
                # so an actively-converging verifier isn't aborted mid-flight — BOUNDED by
                # FWVAL_CHAIN_CHURN_CAP so a verifier that oscillates FOREVER (each cycle a
                # different broken chain, never green) still aborts (no livelock). Gated to
                # the POST-FAST-CAP window (review wyy421m0c): below the cap there is NO
                # abort risk, so the grace budget must not be spent during fast-retry —
                # that would shrink the window where it matters. Below the cap a
                # re-authoring falls to the else (stuck++), harmless: the else escalation
                # is itself cap-gated, and a fresh failure-set change resets stuck anyway.
                elif (_attempts >= FWVAL_FAST_CAP
                      and _fwval_is_chain_authoring_progress(
                          _fset, _chain_sig, getattr(orch, "_fwval_chain_sig", None),
                          getattr(orch, "_fwval_chain_churn", 0), _FWVAL_CHAIN_CHURN_CAP)):
                    orch._fwval_chain_churn = getattr(orch, "_fwval_chain_churn", 0) + 1
                    orch._fwval_stuck_count = 0
                    orch._fwval_chain_sig = _chain_sig
                    orch._logger.warning(
                        "CHAIN-AUTHORING PROGRESS: business_chain still failing but the "
                        "verifier re-authored the chains (churn %s/%s) — resetting the "
                        "stuck budget to let it converge (bounded).",
                        orch._fwval_chain_churn, _FWVAL_CHAIN_CHURN_CAP)
                else:
                    # Same failure set as last validation → no functional progress.
                    orch._fwval_chain_sig = _chain_sig
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
                        _rmsg = _create_message(
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
                        )
                        # CRITICAL (v11 root cause): without validation_phase=True the
                        # verifier's VerifierValidationTriggerPolicy REJECTS this task_ready
                        # ("requires explicit validation-phase trigger") — the re-nudge was
                        # silently ignored every time (run v11: "Ignoring task_ready from
                        # orchestrator" at 03:47:53, 30s before the gate). tags alone don't
                        # satisfy the policy unless env-configured into accepted_tags;
                        # validation_phase=True always does (workflow_policies.py:346).
                        _rmsg.metadata["validation_phase"] = True
                        await orch.message_bus.send(_rmsg)
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
