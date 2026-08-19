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

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from progress import EventType


# ── FIX #155 (§6-2): fresh api_smoke before cut on post-smoke backend drift ──
# gmrun3 (precise timeline): last api_smoke PASSED @05:15 → visual escape @05:33 →
# backend lane EDITED custom_routes.py @05:34-35 (broken middleware, crashes at
# import) → cut @05:37. The cut-time _merge_committed_agent_work() imports late
# lane commits into the release snapshot AFTER every gate check — a structural
# window, not a fluke — and the delivery gate reuses the mid-milestone smoke, so
# the delivered archive cold-start-crashes (every request 500). Close it: stamp a
# backend source signature when the framework smoke PASSES; at cut time, if the
# committed backend differs, run ONE fresh RunValidationTool pass (clean docker
# boot + probes, recorded like any run) and HOLD the cut on failure. The failed
# run flips build:* checks red → the existing verification_checklist_not_ready /
# failing-check remediation rails drive the lane; a lane fix changes the sig and
# re-arms the fresh smoke. Same-sig failures are cached — never a docker churn.

def contract_ddl_render_needed(*, orm_introspectable: bool, ddl_exists: bool) -> bool:
    """Whether the CONTRACT-derived DDL render still has to run this tick.

    #347: app/database/init/01_init.sql has two framework writers per tick --
    the contract render (_generate_database) and the ORM render (#43
    _repair_ddl_from_orm), which runs last and always wins. r91 logged 122 vs
    121, r92 102 vs 100, r93 34 vs 33, so ~100 contract renders per run are
    overwritten immediately.

    They are NOT equivalent: the contract version emits a bogus `_meta` table
    and strips every DEFAULT (`"verified" BOOLEAN` vs `boolean default false`).
    The 1-tick gap in those counts is exactly the window where that variant is
    what sits on disk.

    #43 already states the ORM is the runtime truth. So the contract render
    becomes a FALLBACK -- but it cannot be deleted: it is the only DDL author
    before the skeleton has emitted models.py, and the delivery gate globs
    app/database/*.sql, so the file must exist even on the first tick.
    """
    if not ddl_exists:
        return True            # nothing on disk yet — the gate needs a file
    return not orm_introspectable   # a broken/absent models.py means #43 no-ops


def backend_source_signature(app_root: Any) -> Optional[str]:
    """Stable content hash of ``app/backend/**/*.py`` — the code that EXECUTES at
    backend boot (the lane-owned custom_routes.py included). Deliberately excludes
    .sql/.json/frontend: the heal pipeline's DDL/dataset writers are not byte-stable
    (ORM-introspection ordering), so hashing them would false-drift every cut.
    ``None`` when the backend dir is missing or on any fault (caller must NOT block
    delivery on our own failure)."""
    try:
        be = Path(app_root) / "backend"
        if not be.is_dir():
            return None
        h = hashlib.sha256()
        for f in sorted(be.rglob("*.py"), key=lambda p: str(p)):
            if "__pycache__" in f.parts or not f.is_file():
                continue
            h.update(str(f.relative_to(be)).encode() + b"\0")
            h.update(f.read_bytes())
        return h.hexdigest()
    except Exception:
        return None


def frontend_source_signature(app_root: Any) -> Optional[str]:
    """#501 (netflix r70, live): stable content hash of ``app/frontend/src/**`` source
    (jsx/tsx/js/ts/mjs/css) — the code that determines the FRONTEND build. Mirrors
    ``backend_source_signature`` (which deliberately EXCLUDES the frontend) and is used ALONGSIDE
    it by the checklist self-heal so a stale ``build:frontend`` re-invalidated by a FRONTEND-only
    fix also grants a settle-refresh. r70 wedged on ``verification_checklist_not_ready``:
    ``build:frontend`` went stale while the backend source stayed stable, so #492 — which keyed the
    settle-refresh on the BACKEND signature alone — exhausted its flat budget and never re-armed →
    permanent checklist red despite 3 heal attempts. Source files under src/ are lane-authored /
    projector-emitted and byte-stable (unlike the .sql/.json the backend sig excludes). Skips
    node_modules/dist/build (not source). ``None`` when src/ is missing or on any fault (caller must
    NOT block delivery on our own failure)."""
    try:
        fe = Path(app_root) / "frontend" / "src"
        if not fe.is_dir():
            return None
        _exts = {".jsx", ".tsx", ".js", ".ts", ".mjs", ".css"}
        h = hashlib.sha256()
        for f in sorted(fe.rglob("*"), key=lambda p: str(p)):
            if not f.is_file() or f.suffix.lower() not in _exts:
                continue
            if any(seg in ("node_modules", "dist", "build") for seg in f.parts):
                continue
            h.update(str(f.relative_to(fe)).encode() + b"\0")
            h.update(f.read_bytes())
        return h.hexdigest()
    except Exception:
        return None


def fresh_smoke_decision(cur_sig: Optional[str], validated_sig: Optional[str],
                         pass_sig: Optional[str], fail_sig: Optional[str]) -> str:
    """Pure cut-time decision: ``cut`` | ``smoke`` | ``hold``.

    ``cut``   — current backend already validated (by the last passing framework
                smoke, or by a previous cut-time fresh smoke), or we cannot compute
                a signature (our own fault must never block delivery).
    ``hold``  — this EXACT backend already failed a cut-time fresh smoke: hold the
                release (the recorded failing run drives remediation) without
                re-booting docker every tick.
    ``smoke`` — the backend drifted after the last validated state (or no framework
                smoke ever stamped one, e.g. the verifier's run won the race): run
                one fresh smoke now."""
    if cur_sig is None:
        return "cut"
    if validated_sig is not None and cur_sig == validated_sig:
        return "cut"
    if pass_sig is not None and cur_sig == pass_sig:
        return "cut"
    if fail_sig is not None and cur_sig == fail_sig:
        return "hold"
    return "smoke"


async def ensure_fresh_smoke_before_cut(orch: Any) -> bool:
    """Cut-time guard: ``True`` → proceed to create_release, ``False`` → hold this
    tick. Called AFTER _commit_framework_delivery (the tree is final). Best-effort:
    any internal fault returns True — infra must never block delivery."""
    try:
        if os.environ.get("ENVGEN_FRESH_SMOKE_GATE", "1").lower() in (
                "0", "false", "no", "off"):
            return True
        out_dir = getattr(orch, "output_dir", None)
        if not out_dir:
            return True
        app_root = Path(out_dir) / "app"
        if not app_root.exists():
            app_root = Path(out_dir)
        cur = backend_source_signature(app_root)
        decision = fresh_smoke_decision(
            cur,
            getattr(orch, "_smoke_backend_sig", None),
            getattr(orch, "_fresh_smoke_pass_sig", None),
            getattr(orch, "_fresh_smoke_fail_sig", None))
        if decision == "cut":
            return True
        if decision == "hold":
            orch._logger.warning(
                "RELEASE HELD: the backend still matches the tree that FAILED the "
                "pre-cut fresh api_smoke — waiting for a lane fix (the failing run's "
                "checks are dispatched); not re-booting docker on an unchanged tree. "
                "Set ENVGEN_FRESH_SMOKE_GATE=0 to disable.")
            return False
        orch._logger.warning(
            "PRE-CUT FRESH SMOKE: backend source changed AFTER the last passing "
            "api_smoke (post-smoke lane edit / late merge — the gmrun3 cold-start-"
            "crash window). Re-validating the exact release tree before cutting.")
        from tools.validation_tools import RunValidationTool
        tool = RunValidationTool(workspace=None)
        tool._hubs = getattr(orch, "hubs", None)
        tool._agent_id = "orchestrator"
        res = await tool.execute()
        data = getattr(res, "data", None) or {}
        if data.get("runhub_run_id"):
            orch._fresh_smoke_pass_sig = cur
            orch._smoke_backend_sig = cur
            orch._logger.warning(
                "PRE-CUT FRESH SMOKE PASSED (run %s) — the release ships a "
                "validated backend.", data.get("runhub_run_id"))
            return True
        orch._fresh_smoke_fail_sig = cur
        _failed = [f"{c.get('name')}:{(c.get('detail') or '')[:60]}"
                   for c in (data.get("checks") or []) if c.get("status") == "fail"]
        orch._logger.error(
            "RELEASE HELD: the post-smoke backend edit FAILS a fresh api_smoke "
            "(%s) — NOT cutting a release that crashes on cold start (gmrun3 "
            "class). The failing run is recorded; remediation routes to the lane. "
            "A backend source change re-arms this check.",
            _failed or (getattr(res, "error_message", "") or "?")[:160])
        return False
    except Exception as _exc:
        try:
            orch._logger.debug("fresh-smoke-before-cut skipped on fault: %s", _exc)
        except Exception:
            pass
        return True


# #182: markers used to surface the ACTUAL failure line from a long build/validation log rather
# than a blind prefix slice (which grabs meaningless cached-build fragments — image hashes, a
# chopped 'ghcr.io'->'cr.io'). Build failures sit at the END, not the start.
_ERR_MARKERS = (
    "error:", "err!", "failed to solve", "build failed", "has already been declared",
    "npm err", "syntaxerror", "modulenotfound", "traceback", "exit code", "exited with",
    "no space left", "cannot find", "not found", "permission denied", "denied", "unhealthy",
    "fatal:",
)


def _salient_error(detail: Any, cap: int = 400) -> str:
    """Surface the ACTUAL error line(s) from a (possibly long, multi-line) build/validation log,
    instead of a blind PREFIX slice. gmtiktok STUCK-aborted with "Real blocker: docker_up:
    cr.io/astral-sh/uv" — a prefix fragment of the cached backend build — while the real failure
    was a frontend "'LoginPage' has already been declared" at the END (#182). Returns the last few
    marker-matching lines; if none match, returns the TAIL (never the misleading prefix). Pure;
    ``""`` on empty input.

    #973: a postgres ``ERROR:`` is reported together with the ``STATEMENT:`` line that follows
    it. Postgres always emits the pair, and the statement is the ONLY part that localizes the
    fault — the error line alone says `syntax error at or near "?" at character 170`, which
    names neither the table nor the query. That token has now appeared 6 times across r149,
    r157 and r158 and stayed undiagnosable through all of them, because ``STATEMENT`` is not an
    error marker and this extractor DROPPED the line rather than truncating it (raising `cap`
    would not have helped). Same lesson as #972: knowing a thing failed is not knowing why.
    """
    if not detail:
        return ""
    text = str(detail).replace("\\n", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    hits = []
    for i, ln in enumerate(lines):
        if not any(m in ln.lower() for m in _ERR_MARKERS):
            continue
        hits.append(ln)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if "statement:" in nxt.lower() and nxt not in hits:
            hits.append(nxt)
    if hits:
        return " | ".join(hits[-3:])[:cap]
    return text[-cap:].strip()


def _max_chain_restores() -> int:
    """#327: how many times the regression guard may restore the SAME last-passing snapshot
    before treating it as NON-IDEMPOTENT (poisoned) and letting the verifier fix the step
    instead. 2 tolerates a genuine transient re-author; 3+ is the r92 livelock (38 restores)."""
    try:
        return max(1, int(os.environ.get("ENVGEN_MAX_CHAIN_RESTORES", "2")))
    except (TypeError, ValueError):
        return 2


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
        # #327: a genuine green resets the restore counter — this snapshot is proven-good
        # right now, so its restore budget starts fresh.
        orch._chains_restore_count = 0
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


def _should_regen_skeleton(app_sig, healed_sig, build_wedged,
                           contract_sig, healed_contract_sig) -> bool:
    """FIX #203: decide whether to regenerate the by-construction backend skeleton
    this tick. Fires on (a) an app-SOURCE change (the original heal-on-change
    trigger), (b) a build wedge (force the repairs), OR — the fix — (c) a CONTRACT
    change (tables/endpoints registry version moved). r10/r11: the lane registered
    the missing backing tables mid-run, but the gate keyed ONLY on app-source, so
    the skeleton never re-projected the stubbed endpoints against the new tables →
    the `{items:[]}` stubs persisted → #173 wall. A contract change now re-projects
    them. Pure."""
    if app_sig is None or build_wedged:
        return True
    if app_sig != healed_sig:
        return True
    if contract_sig != healed_contract_sig:
        return True
    return False


def _fwval_is_source_edit_progress(app_sig, prev_app_sig, source_churn, cap) -> bool:
    """True iff the integrated APP SOURCE signature changed since the last validation
    cycle AND the bounded churn budget isn't spent — a lane is actively editing code
    the check-level failure set can't see yet, so the stuck counter should reset
    (tiktok-r2: STUCK-ABORT fired ~20s before the backend lane landed its
    /auth/login fix). Unlike the #71 chain grace this is NOT failure-set-restricted:
    a source edit can fix any failure class. Bounded by ``cap`` so a lane that
    thrashes FOREVER without clearing the failure set still aborts (no livelock —
    tiktok-r3's 75-min fabricated-field churn stays bounded). Fix #186."""
    try:
        return bool(
            app_sig is not None and prev_app_sig is not None
            and app_sig != prev_app_sig
            and int(source_churn or 0) < int(cap))
    except Exception:
        return False


# #492 (netflix r64, 2026-08-04): the flat per-milestone budget for FIX #120's
# stale-build refresh, plus a HIGHER hard cap that a LEGITIMATE churn can climb — a
# churny deliver tail regenerates the by-construction backend skeleton on every
# app-source/contract change (r64: 13× in 22min), and each regen is a NEW build
# state whose api_smoke recording legitimately needs one fresh run to re-record
# build:* truth. The flat cap alone (3) was EXHAUSTED at 20:37:32 while the skeleton
# kept regenerating through 20:47:30, so verification_checklist_not_ready could never
# be re-recorded → permanent wedge (delivery relied on the LLM verifier, which never
# complied). See maybe_refresh_stale_build_checklist for the settle-then-record rule.
_CHECKLIST_REFRESH_FLAT_CAP = 3
_CHECKLIST_REFRESH_HARD_CAP = 10

# #511: build/validation checks that a gate-passing api_smoke run PROVES succeeded — a passing
# api_smoke means docker-compose up built every service (backend+frontend+db) and the endpoints
# answered, so a stale FAILURE on any of these is provably wrong and may be recorded = success.
_BUILD_TRUTH_CHECK_RE = re.compile(
    r"^(?:build:(?:docker|backend|frontend|database)|validation:(?:api_smoke|frontend_build))$")


def _record_build_truth_from_passing_run(orch: Any) -> int:
    """#511 — when a gate-passing api_smoke RunHub run exists this session, DIRECTLY re-record
    any stale (non-success) build:*/validation:{api_smoke,frontend_build} check = success with
    deterministic_runtime_evidence (so it outranks the stale opinion, #258). Returns the count
    re-recorded (0 if no passing run, or nothing stale). Never raises. Generalizable: gated on a
    real passing run; a genuinely broken build has no passing api_smoke → records nothing."""
    hubs = getattr(orch, "hubs", None)
    runhub = getattr(hubs, "runhub", None)
    codehub = getattr(hubs, "codehub", None)
    if runhub is None or codehub is None or not hasattr(runhub, "last_successful_run_since"):
        return 0
    session_ts = getattr(orch, "_session_start_ts", 0.0) or 0.0
    passing = runhub.last_successful_run_since(session_ts)
    if not passing:
        return 0  # no proof the app built + booted + served → do NOT fabricate success
    # #511-review (2026-08-05): the passing run must reflect the CURRENT code. A gate-passing
    # api_smoke EARLIER this session does NOT prove the app builds NOW if a later source change
    # broke it and a fresh run FAILED afterwards. Without this guard, the stale earlier pass still
    # satisfies last_successful_run_since → we re-record build:* = success (deterministic evidence
    # OUTRANKS the fresh real failure, #258) AND return True (skipping #492's reset-and-rerun) →
    # a genuinely broken build (white-screen frontend) SHIPS. So: if ANY run FAILED/ABORTED more
    # recently than the last successful run, the build truth is stale — record NOTHING. Best-effort
    # (only enforced when RunHub exposes the run list + a comparable timestamp; degrades to the
    # prior trust-the-pass behavior otherwise, e.g. unit fakes). Generalizable: no product literals.
    try:
        if isinstance(passing, dict) and hasattr(runhub, "list_runs"):
            _pass_ts = float(passing.get("started_at") or 0.0)
            for _r in (runhub.list_runs(limit=1000) or []):
                if (str((_r or {}).get("status") or "").strip().lower() in ("failed", "aborted")
                        and float((_r or {}).get("started_at") or 0.0) > _pass_ts):
                    return 0  # a later run broke the build → the earlier pass is stale
    except Exception:
        pass
    try:
        checks = codehub.list_checks(pr_id="main") or []
    except Exception:
        return 0
    _passok = ("success", "passed", "pass", "ok")
    recorded = 0
    for c in checks:
        name = str((c or {}).get("name") or "")
        if not _BUILD_TRUTH_CHECK_RE.match(name):
            continue
        if str((c or {}).get("status") or "").strip().lower() in _passok:
            continue
        try:
            codehub.record_check(
                pr_id="main", name=name, status="success",
                evidence={"deterministic_runtime_evidence": True, "source": "#511",
                          "reason": "gate-passing api_smoke run exists this session — "
                                    "docker-compose up built every service and endpoints "
                                    "answered, so this stale build/validation failure is "
                                    "provably wrong"},
                agent="")
            recorded += 1
        except Exception:
            pass
    if recorded and hasattr(orch, "_logger"):
        try:
            orch._logger.warning(
                "STALE BUILD-CHECKLIST record-the-truth (#511): a gate-passing api_smoke run "
                "exists → directly re-recorded %d stale build/validation check(s) = success "
                "(app provably built+booted; #492 reset-and-rerun did not land on r80/r84/r85).",
                recorded)
        except Exception:
            pass
    return recorded



def maybe_refresh_stale_build_checklist(orch: Any, failed_checks) -> bool:
    """FIX #120 (run-38 STUCK, 2026-07-09) + #492 (netflix r64, 2026-08-04): a
    transient run_validation failure (mid visual-window rebuild churn) stamped all
    four ``build:*`` CodeHub checks = failure, and NOTHING re-ran validation
    afterwards — the checklist remediation messages the VERIFIER (LLM-dependent; it
    never complied), so an otherwise-deliverable run hit the 75-min no-convergence
    wall on ``verification_checklist_not_ready`` alone. Deterministic self-heal: when
    the deliver gate declines with that blocker, reset the framework's own api_smoke
    attempt counter (BOUNDED per milestone) so the fast retry re-runs validation —
    the shared RunValidationTool records FRESH build:* truth either way (a pass
    supersedes the stale failure; a real failure re-records with fresh evidence).

    SETTLE-THEN-RECORD (#492): the original FLAT cap of 3 fits a STATIC stale
    checklist, but a CHURNY-but-legitimate deliver tail regenerates the backend
    skeleton on each app-source/contract change and re-invalidates build:* freshness
    every regen — r64 exhausted the 3-budget at 20:37:32 while the skeleton kept
    regenerating through 20:47:30, leaving the checklist permanently red. Beyond the
    flat budget, ALSO grant a refresh when the backend BUILD STATE genuinely CHANGED
    since the last refresh (``backend_source_signature`` differs from the stored
    ``_checklist_refresh_last_sig``), up to a HIGHER hard cap. No livelock: a STATIC
    stuck state (sig unchanged) still caps at the flat 3, and a PERPETUAL churn is
    bounded by the hard cap → the existing no-convergence abort still fires.
    Returns True when a refresh was armed. Never raises."""
    try:
        if "verification_checklist_not_ready" not in set(failed_checks or ()):
            return False
        # #511 (netflix r84+r85, 2026-08-05): RECORD-THE-TRUTH. #492's reset-and-rerun (below)
        # demonstrably DOESN'T LAND — r80/r84/r85 all died on verification_checklist_not_ready
        # with build:* + validation:api_smoke stale=failure DESPITE a gate-passing api_smoke run
        # (r85: 34 api_smoke passes, visual passed, app provably built+booted+served). A passing
        # api_smoke run means docker-compose up built EVERY service (backend+frontend+db) and the
        # endpoints answered — so those build/validation checks are LOGICALLY success. Directly
        # re-record them (same pattern as #74/#489 "record the deterministic truth", not #492's
        # reset-and-hope). Marked deterministic_runtime_evidence so it OUTRANKS the stale opinion
        # (#258 guard) and persists. SOUND + GENERALIZABLE: gated on a REAL passing run — a
        # genuinely broken build has no passing api_smoke → nothing recorded; only touches
        # build:*/validation:{api_smoke,frontend_build} that are currently non-success.
        try:
            if _record_build_truth_from_passing_run(orch):
                return True
        except Exception:
            pass
        ms = str(getattr(orch, "_current_milestone_version", "") or "")
        budget = getattr(orch, "_checklist_refresh_by_ms", None)
        if budget is None:
            budget = {}
            orch._checklist_refresh_by_ms = budget
        used = int(budget.get(ms, 0) or 0)
        # Current backend build state — best-effort; None on any fault (never blocks
        # the flat path, which mirrors the original sig-free behaviour exactly).
        cur_sig = None
        try:
            _out = getattr(orch, "output_dir", None)
            if _out:
                _app_root = Path(_out) / "app"
                if not _app_root.exists():
                    _app_root = Path(_out)
                # #501: key the settle-refresh on BOTH backend AND frontend source. A stale
                # build:frontend re-invalidated by a FRONTEND-only fix must also grant a refresh —
                # r70 wedged on verification_checklist_not_ready because #492 keyed on the backend
                # signature alone, so a build:frontend that went stale while the backend stayed
                # stable never re-armed once the flat budget was spent. Combined sig changes if
                # EITHER lane's source changes → additive (strictly more refreshes, still bounded by
                # the hard cap). None only when BOTH are unavailable (preserves the flat-path fallback).
                _be = backend_source_signature(_app_root)
                _fe = frontend_source_signature(_app_root)
                cur_sig = None if (_be is None and _fe is None) else f"{_be}|{_fe}"
        except Exception:
            cur_sig = None
        _flat = used < _CHECKLIST_REFRESH_FLAT_CAP
        _settle = (
            used < _CHECKLIST_REFRESH_HARD_CAP
            and cur_sig is not None
            and cur_sig != getattr(orch, "_checklist_refresh_last_sig", None))
        if not (_flat or _settle):
            return False
        budget[ms] = used + 1
        orch._checklist_refresh_last_sig = cur_sig
        orch._framework_validation_attempts = 0
        try:
            orch._logger.warning(
                "STALE BUILD-CHECKLIST self-heal (FIX #120/#492): "
                "verification_checklist_not_ready is blocking delivery — resetting "
                "the framework validation attempt counter (refresh %s/%s for v%s, %s) "
                "so api_smoke re-runs and records FRESH build:* checks itself.",
                budget[ms], _CHECKLIST_REFRESH_HARD_CAP, ms,
                "flat budget" if _flat else "settle: backend build state changed")
        except Exception:
            pass
        return True
    except Exception:
        return False


def maybe_rerun_unrun_chains(orch: Any, failed_checks) -> bool:
    """#475 (r50, 2026-08-04): delivery blocked on business_chain_failing but the
    offending chains were merely NEVER RUN, not failed. business_chain_blockers
    (delivery_gate.py) flags a chain not-passing when status ∉ (passing,
    framework_blocked) — which lumps a NEVER-EXECUTED chain (status unset/'?', no
    broken last_result) together with a genuinely FAILED one. The verifier keeps
    re-authoring chains (r50: count churned 28→24→31) and the newest stays UNRUN
    before the next run_chains, so the gate re-dispatches the verifier to RE-AUTHOR
    (adding more unrun chains) → churn (r50: 14 deliver_project / 0 release, 29/31
    chains 'passing' + 1 '?'; seed✓ functional✓ visual✓ — this was the SOLE blocker).

    Deterministic self-heal (mirrors FIX #120's stale-build refresh): when the ONLY
    business_chain blockers are unrun chains, reset the framework's api_smoke attempt
    counter (BOUNDED per milestone) so run_chains re-executes ALL registered chains and
    records fresh status — a chain that PASSES clears the gate (and the verifier is no
    longer dispatched → churn broken); one that FAILS re-records broken → stays
    business_chain_failing (verifier dispatched to fix it). NEVER acts when any chain has
    a BROKEN last_result (a real failure must NOT be masked by a re-run). Returns True
    when a re-run was armed. Never raises. Generalizable to every app/env."""
    try:
        if "business_chain_failing" not in set(failed_checks or ()):
            return False
        rh = getattr(getattr(orch, "hubs", None), "registryhub", None)
        if rh is None or not hasattr(rh, "get_verification_chains"):
            return False
        chains = rh.get_verification_chains() or {}
        authored = [
            rec for name, rec in chains.items()
            if name != "_meta" and isinstance(rec, dict) and rec.get("steps")
            and str(rec.get("kind") or "").lower() != "coverage"
        ]
        not_passing = [
            rec for rec in authored
            if rec.get("status") not in ("passing", "framework_blocked")
            or (rec.get("last_result") or {}).get("broken")
        ]
        if not not_passing:
            return False
        # A REAL failure (ran + left steps broken) must go to the verifier, NOT be
        # re-run away — bail so the normal dispatch handles it.
        if any((rec.get("last_result") or {}).get("broken") for rec in not_passing):
            return False
        # All blockers are merely UNRUN → re-run the chains (bounded per milestone).
        ms = str(getattr(orch, "_current_milestone_version", "") or "")
        budget = getattr(orch, "_unrun_chain_rerun_by_ms", None)
        if budget is None:
            budget = {}
            orch._unrun_chain_rerun_by_ms = budget
        if budget.get(ms, 0) >= 4:
            return False
        budget[ms] = budget.get(ms, 0) + 1
        orch._framework_validation_attempts = 0
        try:
            orch._logger.warning(
                "UNRUN-CHAIN self-heal (#475): business_chain_failing is blocked ONLY by "
                "%d never-run chain(s) (status unset, no broken steps) — resetting the "
                "api_smoke attempt counter (rerun %s/4 for v%s) so run_chains executes them "
                "and records fresh status, instead of re-dispatching the verifier to "
                "re-author (which adds more unrun chains → churn).",
                len(not_passing), budget[ms], ms)
        except Exception:
            pass
        return True
    except Exception:
        return False


def maybe_emit_schema_sql(orch: Any, failed_checks) -> bool:
    """#74 (netflix r78, 2026-08-05): delivery blocked on ``database_sql_missing`` while the app's
    DB is FUNCTIONAL (api_smoke passed — a clean docker boot that created + probed the schema).
    ``database_sql_missing`` (delivery_gate.py) is a pure FILE-EXISTENCE check: app/database/**/*.sql
    must exist. The deterministic ``app/database/`` scaffold (scaffolder.write_database_scaffold →
    database_scaffold.render_schema_sql — "no agent, no variance") is called ONCE post-finalize_kickoff;
    if it never ran, or a later lane merge clobbered app/database/, there is NO deliver-tail re-emit,
    so the gate stays red for the rest of the run (r78: gate frozen at 15 for 11min on this + wedged).

    Deterministic self-heal (mirrors #489/#492/#475): when database_sql_missing is a failed check,
    re-emit app/database/ from the registered SchemaHub tables (+ synthesized backing tables for
    endpoint-only resources) using the SAME render_schema_sql the by-construction scaffold uses. This
    GUARANTEES the check clears without depending on the flaky LLM backend lane, and generalizes to
    every app. Idempotent + guarded: no-ops when the check isn't failing, when a .sql already exists,
    or when no tables are registered. Best-effort; never raises. Returns True when it (re-)wrote the
    schema. Validate the gate-clear on a run."""
    try:
        if "database_sql_missing" not in set(failed_checks or ()):
            return False
        out = Path(getattr(orch, "output_dir", "") or "")
        if not str(out):
            return False
        if any((out / "app" / "database").glob("**/*.sql")):
            return False  # already present — nothing to heal
        hubs = getattr(orch, "hubs", None)
        sh = getattr(hubs, "schema_hub", None)
        if sh is None or not hasattr(sh, "list_tables"):
            return False
        tables = sh.list_tables() or {}
        from .database_scaffold import write_database_scaffold, synthesize_missing_tables
        _rh = getattr(hubs, "registryhub", None)
        if _rh is not None:
            try:
                from .lifecycle import business_endpoints
                tables = synthesize_missing_tables(
                    tables, business_endpoints(_rh.get_endpoints() or {}))
            except Exception:
                pass
        if not tables:
            return False  # no contract tables → nothing deterministic to emit
        paths = write_database_scaffold(out, tables)
        try:
            orch._logger.warning(
                "DATABASE-SQL self-heal (#74): database_sql_missing but the app DB is functional — "
                "deterministically re-emitted app/database/ from %d registered table(s) → %s "
                "(by-construction render_schema_sql, no LLM lane).",
                paths.get("table_count", 0), paths.get("schema_sql"))
        except Exception:
            pass
        return True
    except Exception:
        return False


async def maybe_author_ui_flow_evidence(orch: Any, failed_checks) -> bool:
    """#489 (netflix r58/r61, 2026-08-04, task#47): delivery blocked on
    ``deliverability_ui_flow_missing`` while the app is FULLY functional (r61:
    "verifier reports full PASS — 15/15 endpoints, 51/51 chain steps, frontend
    navigable, 0 bugs"). The ONLY gap is that the LLM verifier never authored the
    ``validation:ui_flow`` records the gate requires as evidence — it was dispatched
    to run_validation 6+ times over 11 min and never complied (r68/r91-93 the same
    failure). This is the task#47 convergence wedge: the app works, a bookkeeping
    record the LLM lane keeps failing to write blocks delivery.

    The framework ALREADY converts a passing authenticated browser walk into those
    records — ``_run_browser_test_user`` → ``clean_ui_flow_passes`` →
    ``record_validation_result`` tagged ``DETERMINISTIC_EVIDENCE_KEY`` (#240, proven
    in r80: 7 records cleared the gate). But that walk only runs AFTER the gate is
    already clear (the pre-release browser gate + post-release net), so while
    ui_flow_missing is RED it never fires — chicken-and-egg. Run it HERE, pre-gate,
    so the records get authored from a REAL passing walk and the gate clears
    deterministically instead of waiting on the flaky verifier.

    SOUND (never hacks the gate): ``clean_ui_flow_passes`` is PASS-ONLY — it records
    only pages that render cleanly (auth ok, not blank, no console error, not
    login-bounced, not fallback DOM), so a genuinely-broken flow gets NO record and
    stays blocked (correctly routed to the verifier/frontend lane). COST-SAFE: gated
    on api_smoke having passed (``deliverability_no_successful_run`` absent → the app
    is up) so the expensive Playwright walk never runs against a down app (and
    ``_run_test_user_validation`` itself health-pre-checks + self-skips otherwise),
    and BOUNDED per milestone. Threaded (the walk is blocking + spins its own
    asyncio.run) via ``asyncio.to_thread`` so it never blocks the event loop — the
    same invocation the pre-release gate already uses (orchestrator.py:2943).
    Returns True when a walk was armed/run. Never raises. Generalizes to every
    app/env (critical ui_flows are contract-derived from the registered ui_pages)."""
    try:
        fset = set(map(str, failed_checks or ()))
        if "deliverability_ui_flow_missing" not in fset:
            return False
        # The app must be validated end-to-end (i.e. UP) before spending on a browser
        # walk. If api_smoke never passed, the walk would just self-skip (app
        # unreachable) — skip cheaply here rather than spawn a doomed thread. This
        # also matches the exact r61 shape (api_smoke green, only ui_flow records absent).
        if "deliverability_no_successful_run" in fset:
            return False
        ms = str(getattr(orch, "_current_milestone_version", "") or "")
        budget = getattr(orch, "_ui_flow_walk_by_ms", None)
        if budget is None:
            budget = {}
            orch._ui_flow_walk_by_ms = budget
        if budget.get(ms, 0) >= 3:
            return False
        budget[ms] = budget.get(ms, 0) + 1
        try:
            orch._logger.warning(
                "UI-FLOW EVIDENCE self-heal (#489): deliverability_ui_flow_missing is "
                "blocking delivery but api_smoke passed (app is up) — running the "
                "deterministic authenticated browser walk (walk %s/3 for v%s) to AUTHOR "
                "validation:ui_flow PASS records for the pages that render cleanly, "
                "instead of waiting on the verifier LLM (which keeps failing to author "
                "them). PASS-ONLY: a broken flow gets no record and stays blocked.",
                budget[ms], ms)
        except Exception:
            pass
        import asyncio as _aio
        # _run_test_user_validation is blocking (health pre-check + Playwright walk +
        # its own asyncio.run) → thread it; its browser walk auto-authors the
        # deterministic ui_flow PASS records as a side-effect (heal_pipeline #240).
        await _aio.to_thread(
            orch._run_test_user_validation,
            getattr(orch, "_current_milestone_version", "1.0.0"))
        return True
    except Exception:
        return False


async def reauthor_missing_database_sql(orch: Any) -> bool:
    """#482 — restore ``app/database/*.sql`` whenever it is MISSING, independent of
    skeleton-regen. THE last Part-B blocker on a fully-converged run (r53 + r54, live):

    ``_generate_database`` writes ``app/database/init/01_init.sql`` at startup, but the
    per-tick ``_merge_committed_agent_work`` can DROP the working-tree copy (a lane's
    worktree branched before the scaffold → merging it removes app/database). The only
    per-tick re-author is nested inside ``if _should_regen_skeleton(...)`` — so a merge
    that wipes app/database WITHOUT changing the backend-skeleton signature leaves it
    GONE. The delivery gate's ``database_has_sql`` (globs app/database/**/*.sql) then
    stays False → ``database_sql_missing`` → the final post-loop gate RAISES
    ``RuntimeError`` → the run dies with 0 releases even though 10/10 business chains
    passed, api_smoke was green, and there was zero churn (r54: EXACTLY this).

    FIX: an UNCONDITIONAL write-if-missing each tick (same precedent as
    ``_scaffold_design_readme`` — a required delivery artifact outside the app-source
    signature). Returns True if it re-authored, False if already present / on error.
    Best-effort: never raises into the tick loop. Generalizable to every env — any app
    whose DB is projected from the contract and can be merge-wiped mid-run."""
    try:
        from pathlib import Path as _DBP
        db_dir = _DBP(orch.output_dir) / "app" / "database"
        if any(db_dir.glob("**/*.sql")):
            return False  # present → nothing to do (cheap glob, no subprocess)
        await orch._generate_database()
        restored = any(db_dir.glob("**/*.sql"))
        if restored:
            orch._logger.warning(
                "#482 re-authored app/database/*.sql (a merge wiped it; skeleton "
                "unchanged so the gated re-author never fired) — unblocks the "
                "database_sql_missing delivery gate.")
        return restored
    except Exception as _exc:
        try:
            orch._logger.warning(
                "#482 app/database re-author (write-if-missing) failed: %s", _exc)
        except Exception:
            pass
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
            # #327: POISONED-SNAPSHOT ESCAPE. The old guard assumed the last-passing snapshot
            # is idempotently green ("restore it and it passes again"). But a chain that went
            # green ONCE via a transient/non-deterministic recovery (or a seed that has since
            # drifted) is NOT idempotent — the restored chains fail again, business_chain
            # re-enters the failure set, the verifier is re-dispatched, re-authors, the guard
            # restores… forever. r92: 38 restore↔re-author cycles = 68% of the run, ending in
            # NO-CONVERGENCE ABORT. Count restores of the SAME snapshot; once it has been
            # restored more than the budget WITHOUT sticking, treat it as poisoned: stop
            # restoring, drop it, clear the green-high-water + the freeze, and route the
            # failing step back to the verifier to actually FIX (keep business_chain in fset).
            n = int(getattr(orch, "_chains_restore_count", 0) or 0) + 1
            orch._chains_restore_count = n
            if n > _max_chain_restores():
                orch._chains_snapshot = None
                try:
                    hw = getattr(orch, "_fwval_green_high_water", None)
                    if hw:
                        hw.discard("business_chain")
                except Exception:
                    pass
                try:
                    if hasattr(rh, "_chains_frozen_eps"):
                        rh._chains_frozen_eps = set()
                except Exception:
                    pass
                orch._chains_restore_count = 0
                orch._logger.warning(
                    "REGRESSION GUARD: last-passing snapshot proven NON-IDEMPOTENT — restored "
                    "%d× but business_chain keeps regressing with the contract unchanged. "
                    "Poisoning the snapshot, lifting the freeze, and routing the failing step "
                    "back to the verifier to fix (instead of looping to no-convergence).", n)
                return fset  # keep business_chain so the owner is dispatched to fix it
            restore = dict(snap)
            rh._verification_chains.update(
                lambda _v: restore, change_info={"agent": "regression-guard"})
            orch._framework_validation_attempts = 0
            orch._logger.warning(
                "REGRESSION GUARD: business_chain was green then regressed with the "
                "contract unchanged — restored the last-passing verification chains "
                "(agent re-authoring reverted; restore %d/%d).", n, _max_chain_restores())
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
            "_route_consolidation_dispatched",  # #180 version-variant duplicate-route gate
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
                _fwval_can_early_return, FWVAL_FAST_CAP, FWVAL_CHAIN_CHURN_CAP,
                FWVAL_SOURCE_CHURN_CAP)
            _FWVAL_CHAIN_CHURN_CAP = FWVAL_CHAIN_CHURN_CAP
            _FWVAL_SOURCE_CHURN_CAP = FWVAL_SOURCE_CHURN_CAP
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
            # #482 — restore app/database/*.sql if a merge wiped it (see the helper's
            # docstring). UNCONDITIONAL write-if-missing, same precedent as the design
            # readme scaffold above; the skeleton-gated re-author below is NOT enough
            # because the wipe is independent of skeleton-signature changes.
            await reauthor_missing_database_sql(orch)
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
            # FIX #203: also regen when the CONTRACT (tables/endpoints registry
            # versions) changed — a mid-run table registration doesn't touch
            # app/backend/*.py, so the app-source-only gate never re-projected the
            # stubbed endpoints against the new table (r10/r11 #173 wall).
            _contract_sig = None
            try:
                _rh = getattr(orch.hubs, "registryhub", None)
                _vers = _rh.get_versions() if _rh is not None else {}
                _contract_sig = (_vers.get("registryhub_tables"),
                                 _vers.get("registryhub_endpoints"))
            except Exception:
                _contract_sig = None
            if _should_regen_skeleton(
                    _app_sig, getattr(orch, "_fwval_healed_sig", None), _build_wedged,
                    _contract_sig, getattr(orch, "_fwval_healed_contract_sig", None)):
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
                # #347: the ORM render below (#43) is authoritative and runs
                # last, so re-rendering the contract DDL every tick is
                # overwritten work — and its output differs (bogus `_meta`
                # table, DEFAULTs stripped). Keep it as the FALLBACK that
                # guarantees the delivery gate finds app/database/*.sql.
                try:
                    from pathlib import Path as _DP
                    _be = _DP(orch.output_dir) / "app" / "backend"
                    _ddl = (_DP(orch.output_dir) / "app" / "database"
                            / "init" / "01_init.sql")
                    _orm_ok = False
                    try:
                        from .database_scaffold import introspect_orm_schema
                        _orm_ok = bool(introspect_orm_schema(_be))
                    except Exception:
                        _orm_ok = False
                    if contract_ddl_render_needed(
                            orm_introspectable=_orm_ok, ddl_exists=_ddl.exists()):
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
                orch._fwval_healed_contract_sig = _contract_sig  # #203: contract we projected
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
            # FIX #155: signature of the backend tree this smoke will validate —
            # computed BEFORE execute() (a lane merge can land during the await;
            # the stamp must describe the tree docker actually built, never newer).
            _app_root_155 = Path(getattr(orch, "output_dir", ".")) / "app"
            if not _app_root_155.exists():
                _app_root_155 = Path(getattr(orch, "output_dir", "."))
            _pre_smoke_sig = backend_source_signature(_app_root_155)
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
                # FIX #155: remember WHICH backend this passing smoke validated, so
                # the cut-time freshness check can demand a re-smoke iff it drifts.
                if _pre_smoke_sig is not None:
                    orch._smoke_backend_sig = _pre_smoke_sig
                orch._logger.warning(
                    "Framework validation: api_smoke PASSED → recorded RunHub run %s "
                    "(%s endpoints) — delivery-gate run requirement satisfied.",
                    data.get("runhub_run_id"), data.get("endpoints_tested"),
                )
                await orch._maybe_run_visual_fidelity()
                snapshot_passing_chains(orch)
                # #232 (r20/r22 recurring killer): ui_flow recording was only
                # dispatched when the DELIVERY GATE failed at the very end, so
                # the verifier's endgame (chains + flows + browser walks) ran
                # out of clock — r20 recorded the flows 36s AFTER the abort;
                # r22 registered 13 flows and concluded 0. The app is UP and
                # smoke-green RIGHT NOW: dispatch the flow-recording task
                # immediately (idempotent — dispatch_gate_level_checks guards
                # per milestone, so the later gate-fail path won't duplicate).
                if not getattr(orch, "_early_ui_flow_dispatched", None):
                    try:
                        from .remediation_dispatcher import RemediationDispatcher
                        await RemediationDispatcher(orch).dispatch_gate_level_checks(
                            ["deliverability_ui_flow_missing"])
                        orch._early_ui_flow_dispatched = True
                        orch._logger.warning(
                            "#232: early ui_flow recording dispatched to the "
                            "verifier (api_smoke green — don't wait for the "
                            "delivery gate to complain).")
                    except Exception as _ef_exc:
                        orch._logger.debug("#232 early ui_flow dispatch skipped: %s",
                                           _ef_exc)
            else:
                # FIX #36: log WHY the in-run validation failed (summary + failed
                # check names). The bare "not yet passing" hid the real cause for
                # a whole 2-hour run — the app passes api_smoke when booted by
                # hand, so the in-run failures are environmental (docker
                # contention / build-under-load) and we need the detail to fix it.
                _summ = (data or {}).get("summary", "?")
                # #212: surface the ACTUAL failing line (postgres `ERROR: relation
                # ... does not exist`, a build error at the tail, ...) via the
                # salient extractor — NOT a blind 60-char prefix, which lands on the
                # meaningless "Sending build context to Docker daemon" banner and
                # hides the real cause (r15: docker_up DB-init crash mis-read for
                # 20min as an api.js build error).
                _failed = [
                    f"{c.get('name')}:{_salient_error(c.get('detail'), cap=200)}"
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
                    orch._fwval_source_churn = 0  # #186: fresh source-churn budget too
                    orch._fwval_chain_sig = _chain_sig
                    orch._fwval_app_sig = _app_sig
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
                    orch._fwval_app_sig = _app_sig
                    orch._logger.warning(
                        "CHAIN-AUTHORING PROGRESS: business_chain still failing but the "
                        "verifier re-authored the chains (churn %s/%s) — resetting the "
                        "stuck budget to let it converge (bounded).",
                        orch._fwval_chain_churn, _FWVAL_CHAIN_CHURN_CAP)
                # SOURCE-EDIT PROGRESS (#186, tiktok-r2): a lane is actively editing the
                # integrated app source — the failure set can't reflect the fix until the
                # next validation runs, so give the edit a bounded grace instead of
                # counting it toward the abort (r2 was STUCK-ABORTed ~20s before the
                # backend lane landed its /auth/login fix). Post-FAST-CAP gated like the
                # chain grace (below the cap there is no abort risk to spend budget on);
                # churn-capped so an r3-style forever-thrash still aborts.
                elif (_attempts >= FWVAL_FAST_CAP
                      and _fwval_is_source_edit_progress(
                          _app_sig, getattr(orch, "_fwval_app_sig", None),
                          getattr(orch, "_fwval_source_churn", 0),
                          _FWVAL_SOURCE_CHURN_CAP)):
                    orch._fwval_source_churn = getattr(orch, "_fwval_source_churn", 0) + 1
                    orch._fwval_stuck_count = 0
                    orch._fwval_chain_sig = _chain_sig
                    orch._fwval_app_sig = _app_sig
                    orch._logger.warning(
                        "SOURCE-EDIT PROGRESS: failure set %s unchanged but the app "
                        "source signature moved — a lane is actively editing (churn "
                        "%s/%s); resetting the stuck budget to let the fix land "
                        "(bounded).",
                        sorted(_fset) or "(none)",
                        orch._fwval_source_churn, _FWVAL_SOURCE_CHURN_CAP)
                else:
                    # Same failure set as last validation → no functional progress.
                    orch._fwval_chain_sig = _chain_sig
                    orch._fwval_app_sig = _app_sig
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
                                "{}: {}".format(c.get("name"), _salient_error(c.get("detail")))
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
