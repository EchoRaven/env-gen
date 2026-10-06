"""Deliverability aggregator (Cutover 24).

Pure read-side over RunHub + RegistryHub + WorkHub + coverage_audit + seed_audit.
Replaces the LLM-judged checklist with an evidence-based unified report.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import json
import re
from collections.abc import Mapping
from pathlib import Path
from .message_format import join_capped  # #1034

_LOG_700 = logging.getLogger(__name__)

# #1067: one-shot latch so a per-tick failure cannot flood the log.
_DUPE_REPORT_FAILED_1067 = {"said": False}
_WIRING_REPORT_FAILED_1202TM = {"said": False}   # #1202tm, beside its sibling
_SEED_REPAIR_FAILED_1068 = {"said": False}
# #760: groups already announced this process. See the call site for why a module-level set is
# the right shape here and why item 78's dual-import bound (<=2 announcements) is acceptable.
_SAID_700: set = set()


def reset_said_700() -> None:
    """#762: clear #760's say-once memory.

    #760 made the identical-content warning state a group ONCE per run by remembering it in a
    module-level set. Module state outlives a test, so whichever test reached the detector first
    silenced every later one — the suite passed file-by-file and failed as a whole, which is the
    worst failure mode a guard can have because it looks like flakiness rather than coupling.

    A process-lifetime memory is right for a RUN (one generation = one process) and wrong for a
    test session (hundreds of runs in one process). Rather than have tests poke a private global,
    the reset is part of the contract."""
    _SAID_700.clear()
    _GATES_ABSENT_792.clear()

# --- #792: a delivery GATE that cannot load must not read as a delivery gate that PASSED -------
# Each of the blocker gates below is two `try`s: import the audit, then run it. Both handlers
# returned a bare `[]`, so an ImportError in `backend_audit`/`frontend_audit` — or a fault inside
# the audit — made the ENTIRE gate disappear and the release path saw "no blockers". That is
# #789's write-guard failure (a whole enforcer vanishing on an import) sitting on the gates from
# #154/#173/#175. The permissive default is KEPT — a broken audit must not wedge every release —
# but it is no longer indistinguishable from a clean scan. Reuses this module's own say-once
# memory (#760/#762) rather than inventing a third mechanism.
_GATES_ABSENT_792: list = []


def _gate_absent_792(gate: str, exc: BaseException, stage: str) -> None:
    """Record + announce a delivery gate that could not run. Never raises."""
    try:
        note = "%s (%s): %s: %s" % (gate, stage, type(exc).__name__, exc)
        key = "792:" + gate + ":" + stage
        if key in _SAID_700:
            return
        _SAID_700.add(key)
        _GATES_ABSENT_792.append(note)
        _LOG_700.warning(
            "DELIVERY GATE DID NOT RUN (#792): %s. It is returning NO BLOCKERS, which is the "
            "permissive default so a broken audit cannot wedge every release — but that is NOT "
            "evidence the app is clean on this axis. A release cut with this present is "
            "unverified there.", note)
    except Exception:
        pass


def gates_absent_792() -> list:
    """Delivery gates that could not run this process. Empty is the normal, healthy state."""
    return list(_GATES_ABSENT_792)



# §2 gate-hardening (2026-06-22): the api_smoke RunHub run that sets
# ``functionally_validated`` probes the BACKEND only and never opens a frontend page, so a
# real-backend / blank-UI app currently gets the coverage/seed/visual/ui_flow gates waived.
# When ENVGEN_REQUIRE_UI_EVIDENCE is enabled, the UI-facing gates additionally require at
# least ONE passing browser/UI validation record before they may be downgraded — closing the
# "api_smoke green, blank screen shipped" class.
# FIX #193: default-ON. It was default-off because the evidence matcher was
# double-dead (status 'success' vs 'passed' + check nested at
# evidence.metadata.check — verified on run80's archive): enabling it would have
# blocked EVERY delivery. get_validation_results now canonicalizes both, the
# ui_flow records healthy runs already write (7 in run80) match, and the
# blank-UI waiver is finally closed. ENVGEN_REQUIRE_UI_EVIDENCE=0 reverts.
_UI_EVIDENCE_CHECKS = {"ui_flow", "ui_smoke", "ui_page_reachable", "test_user"}


def _require_ui_evidence() -> bool:
    return os.environ.get("ENVGEN_REQUIRE_UI_EVIDENCE", "1").lower() in (
        "1", "true", "yes", "on")


def _has_passing_ui_evidence(hub_registry) -> bool:
    """True iff at least one passing UI/browser/test-user validation record exists."""
    try:
        results = hub_registry.get_validation_results(limit=1000) or []
    except Exception:
        return False
    for r in results:
        if not isinstance(r, dict) or r.get("status") != "passed":
            continue
        if (r.get("metadata") or {}).get("check") in _UI_EVIDENCE_CHECKS:
            return True
    return False


@dataclass
class DeliverabilityReport:
    last_successful_run: Optional[dict] = None
    run_within_session: bool = False
    # #1203e4 put `source_1203e4` / `run_id_1203e4` beside the counts, so this is no
    # longer int-only. Every reader takes named count keys (`total`/`passed`/`failed`),
    # so the extra strings pass through the cap and into the ledger untouched.
    endpoint_probes: Dict[str, Any] = field(default_factory=dict)
    mcp_probes: Dict[str, int] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    seed_data: Dict[str, Any] = field(default_factory=dict)
    visual_reviews: Dict[str, int] = field(default_factory=dict)
    flow_coverage: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    verdict: str = "blocked"

    def to_dict(self) -> dict:
        return {
            "last_successful_run": self.last_successful_run,
            "run_within_session": self.run_within_session,
            "endpoint_probes": dict(self.endpoint_probes),
            "mcp_probes": dict(self.mcp_probes),
            "coverage": dict(self.coverage),
            "seed_data": dict(self.seed_data),
            "visual_reviews": dict(self.visual_reviews),
            "flow_coverage": dict(self.flow_coverage),
            "blockers": list(self.blockers),
            "verdict": self.verdict,
        }


def probed_something_1203d6(ep_counts: Dict[str, int]) -> bool:
    """Did the latest run actually ASK the app anything?

    `functionally_validated` downgrades the dead-artifact, visual and ui_flow blockers from hard
    to warning, and it used to be satisfied by `failed == 0` alone -- which a run that skipped
    every endpoint satisfies by construction, not by merit. Measured over the gate ledgers: 146
    of 532 `deliverable` verdicts (27%, 9 runs; 47 in r149, 24 in r148, 14 in r145) rest on a
    run whose endpoint probes were 100% skipped. `passed` and `skipped` were already counted and
    already written to `delivery_gate.jsonl`; nothing ever read them (#1202wk).

    `total == 0` means there is nothing to ask about, which other gates own, so this predicate
    must not wedge such a run: it answers True there.
    """
    if int(ep_counts.get("total", 0) or 0) == 0:
        return True
    return int(ep_counts.get("passed", 0) or 0) > 0


def _other_writers_failures_1203e8(runs, chosen_run_id: str,
                                   since_ts: float = 0.0) -> List[str]:
    """What the probe writers the gate did NOT read found. `METHOD /path (code)`, sorted.

    The gate judges one run: `last_successful_run_since`, which requires `completed` AND
    `fail_count == 0`. Two writers produce runs (#1203e4), and the one with the WIDER coverage is
    systematically disqualified by its own findings: `RunHub.run_start`'s generic battery probes
    every live endpoint anonymously, so a single 404 anywhere marks its run `failed` and the gate
    reads `validation_tools`' authenticated sweep instead. The run that finds more is the run that
    counts less.

    r153, live: the battery's runs carry `POST /auth/signup (404)` twice, `POST /api/auth/signup
    (404)` and `POST /api/auth/login (401)` -- lane-declared auth aliases that are not wired --
    while the gate record reads `endpoint_probes {total: 7, passed: 7}` from the other writer.
    Four findings, invisible to anyone reading the ledger afterwards.

    This RECORDS, it does not block. #1203e7 blocks on 5xx only, because a 401 on a write whose
    contract says `auth_required: false` may be the contract's error and a declared endpoint's 404
    is GATE-C1's job -- those judgements are deliberately not made here. But "not blockable" is not
    "not worth writing down": the ledger is what a post-mortem has, and it was showing one
    writer's answer as though it were the only one.
    """
    newest: Dict[str, tuple] = {}       # writer -> (started_at, run)
    for r in runs or []:
        if not isinstance(r, dict):
            continue
        when = r.get("started_at", 0.0)
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        if float(when) < float(since_ts or 0.0):
            continue
        if str(r.get("id") or "") == str(chosen_run_id or ""):
            continue                    # the gate already reports this one
        w = str(r.get("started_by") or "")
        prev = newest.get(w)
        if prev is None or float(when) >= prev[0]:
            newest[w] = (float(when), r)
    out = set()
    for w, (_when, r) in newest.items():
        for p in (r.get("probes") or []):
            if not isinstance(p, dict) or p.get("verdict") != "fail":
                continue
            out.add("%s %s (%s)" % (str(p.get("method") or "?").upper(),
                                    p.get("path") or "?", p.get("status_code")))
    return sorted(out)


def _server_error_probes_1203e7(runs, since_ts: float = 0.0,
                                unreadable: Optional[List[str]] = None) -> List[str]:
    """Endpoints whose NEWEST probe record in this session is a 5xx. `METHOD /path (code)`, sorted.

    Keyed by (WRITER, method, path), and arriving at that key took two corrected drafts, both
    caught by replaying against r152's own records rather than by reasoning:

      draft 1, "does the LATEST RUN show a 5xx" -- blocked nothing. At delivery the newest run was
      a `validation_tools` one (00:12:05) that the battery's finding is not in; the battery's last
      look was three runs earlier. The two writers interleave, so "the latest run" is just
      whichever went last.

      draft 2, "per ENDPOINT, newest record wins" -- also blocked nothing, and for a much more
      interesting reason. The two writers DISAGREE about this endpoint at the same minutes:
      23:52:59 `""` pass/200, 23:55:45 `orchestrator` fail/500, 23:57:07 `""` pass/200, 23:59:06
      and 23:59:42 `orchestrator` fail/500, 00:05:44 and 00:12:05 `""` pass/200. Not a flapping
      app: `api_smoke` probes WITH a real token and the generic battery probes ANONYMOUSLY, so
      `GET /api/users/suggested` answers 200 to one and 500 to the other -- a handler that crashes
      with no user context instead of returning 401. Letting "newest" span both writers averages a
      real defect away, which is exactly what #1203e4 said these two sets must not be allowed to
      do to each other.

    So: within ONE writer's own sequence, is the newest thing it knows about this endpoint a 5xx?
    A later probe BY THE SAME WRITER that gets 200 retires it; a different writer's 200 does not,
    because it asked a different question.

    THE BLOCKER THIS FEEDS COULD NOT FIRE. `compute_deliverability` reads
    `last_run = runhub.last_successful_run_since(...)`, which filters `fail_count == 0`, and
    `fail_count` counts exactly the failing probes -- so `ep_counts["failed"]` on that run is 0 by
    construction and "latest run has N failed endpoint probe(s)" was unreachable. Measured across
    every gate ledger on disk: that prose appears in **0 files**, as does the MCP twin, against 47
    for "dead artifact" and 56 for "no successful RunHub run" -- so the corpus has blocker prose
    and these two simply never fired.

    r152 shipped through the hole. `GET /api/users/suggested` went `pass/200` at 22:52 and
    `fail/500` from 23:45 in six consecutive validation runs; those runs were therefore `failed`
    and could not qualify, so the gate read a `validation_tools` run -- the other writer (#1203e4),
    which probes only what api_smoke exercised and never touched that endpoint. `ok=True`,
    `failed_checks=[]`, v1.0.0 delivered with a P1 server error. The remediation had been
    dispatched (124 mentions in the run log); nothing required it to land.

    ONLY 5xx, deliberately. Of the 369 failing probe records on disk, #1203e3/d9/e0 account for
    266, and of the 154 that remain 91 are 401 and 54 are 404 -- two classes I cannot adjudicate
    safely. A 401 on a write whose contract says `auth_required: false` may be the CONTRACT's
    error (#1202zr: the framework itself advised declaring writes public), and a 404 on a declared
    endpoint is already GATE-C1's job via `_unimplemented_route`'s calibrated exemptions. A 5xx is
    never the correct answer to any probe: 6 records, all of them r152's regression. So the new
    hard blocker would have fired exactly once in the whole corpus, on a real one.
    """
    if unreadable is None:
        unreadable = []
    newest: Dict[tuple, tuple] = {}     # (writer, method, path) -> (started_at, code, verdict)
    for r in runs or []:
        if not isinstance(r, dict):
            continue
        when = r.get("started_at", 0.0)
        # #883's ratchet caught the first draft swallowing an unreadable value into `code = 0`
        # inside an `except`, which reads as "not a server error" -- the permissive side, with no
        # one told. There is no exception path here now: a value that is not a number is NOT
        # silently a zero, it is counted and handed back, so the caller can say the gate could
        # not read N probe records rather than implying it read them and found nothing.
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            unreadable.append("run %s has a non-numeric started_at" % (r.get("id") or "?"))
            continue
        if float(when) < float(since_ts or 0.0):
            continue
        for p in (r.get("probes") or []):
            if not isinstance(p, dict):
                continue
            key = (str(r.get("started_by") or ""),
                   str(p.get("method") or "?").upper(), str(p.get("path") or "?"))
            raw = p.get("status_code")
            if raw is None:
                continue        # a skip carries no status; it says nothing either way
            if not isinstance(raw, int) or isinstance(raw, bool):
                unreadable.append("%s %s has status_code=%r" % (key[1], key[2], raw))
                continue
            prev = newest.get(key)
            if prev is None or float(when) >= prev[0]:
                newest[key] = (float(when), raw, str(p.get("verdict")))
    return sorted({"%s %s (%d)" % (k[1], k[2], v[1])
                   for k, v in newest.items()
                   if v[2] == "fail" and 500 <= v[1] < 600})


def _probe_source_1203e4(run) -> str:
    """WHICH writer produced the probe records the gate is about to judge the app on.

    `RunHub` runs are created by two different things and the gate reads whichever one happened
    to be the most recent `completed` run with `fail_count == 0`. They are not interchangeable:

      ``""``             -- `tools/validation_tools.RunValidationTool`, which records the
                            endpoints API_SMOKE ACTUALLY EXERCISED, with a real token and a real
                            body. 3317 runs on disk, and every one of their probe records carries
                            `endpoint_id` and no `severity`.
      ``"orchestrator"`` -- `RunHub.run_start`'s generic battery, which asks every registered
                            endpoint ANONYMOUSLY with an empty body. 1434 runs, records carrying
                            `severity` and `url`. The two sets never overlap.

    The summary the gate wrote named neither, so `endpoint_probes {total: 19, passed: 19}` could
    mean "api_smoke exercised 19 endpoints with credentials" or "an anonymous sweep got 19 2xx",
    and nothing on disk said which. r152 alternated between the two every few minutes -- and
    reading that field without this, I attributed a `passed: 19` to #1203d6 when it belonged to
    the other writer entirely, and had to retract it. The field is the gate's primary functional
    evidence; it has to say where the evidence came from.

    Raw value, deliberately not mapped to a friendlier name: the mapping above is what the corpus
    shows TODAY, and a third writer would be mislabelled by a guess but merely unfamiliar here.
    """
    try:
        return str((run or {}).get("started_by") or "") or "(unset)"
    except Exception:
        return "(unknown)"


def _probe_counts(probes: list) -> Dict[str, int]:
    counts = {"total": len(probes or []), "passed": 0, "failed": 0, "skipped": 0}
    for p in probes or []:
        v = p.get("verdict") if isinstance(p, dict) else None
        if v == "pass":
            counts["passed"] += 1
        elif v == "fail":
            counts["failed"] += 1
        elif v == "skipped":
            counts["skipped"] += 1
    return counts


# #1202ag: a coverage audit that CRASHED told the gate the app was clean.
#
# Both failure paths returned `{"is_clean": True, "dead_count_by_kind": {}}`, and the gate
# reads it as `if not coverage.get("is_clean", True) ...` — so a broken audit and a spotless
# app produce byte-identical gate behaviour, silently. This is the shape the session has been
# removing all day (#1201, #1039, #1202ae, #1202af), sitting in the gate module itself.
#
# `is_clean: True` STAYS. Flipping it would turn every audit fault into a hard blocker, which
# is #566j's false-blocker failure and cost r117/r120 a 75-minute abort. What changes is that
# the result now carries `degraded: True` — the convention this same module already uses for
# `_DEGRADED_FLOW_COVERAGE`, whose docstring says it exists "so operators can distinguish a
# broken audit from a clean app" — and says so once.
_DEGRADED_COVERAGE_1202AG = {
    "is_clean": True, "dead_count_by_kind": {}, "source": "degraded", "degraded": True,
}


def _coverage_summary(hub_registry, app_root) -> Dict[str, Any]:
    try:
        from .coverage_audit import compute_coverage
    except Exception as _e1202ag:
        from .message_format import warn_once_1201
        warn_once_1201("_coverage_summary.import",
                       "the coverage audit (#1202ag) — dead endpoints/tables/files are NOT "
                       "known absent; the gate is reading a DEGRADED clean", _e1202ag)
        return dict(_DEGRADED_COVERAGE_1202AG)
    try:
        report = compute_coverage(hub_registry, Path(app_root))
    except Exception as _e1202ag:
        from .message_format import warn_once_1201
        warn_once_1201("_coverage_summary.run",
                       "the coverage audit (#1202ag) — dead endpoints/tables/files are NOT "
                       "known absent; the gate is reading a DEGRADED clean", _e1202ag)
        return dict(_DEGRADED_COVERAGE_1202AG)
    return {
        "is_clean": report.is_clean,
        "dead_count_by_kind": {
            "endpoints": len(report.dead_endpoints),
            "tables": len(report.dead_tables),
            "files": len(report.dead_files),
            "mcp_tools": len(report.dead_mcp_tools),
            "empty_mcp_servers": len(report.empty_mcp_servers),
            "pages_without_files": len(report.pages_without_files),
        },
        # #1086: the NAMES, kind-prefixed. #1042 restored the kinds here for the same reason
        # — the breakdown "was already computed one function up; only the sum was ever
        # printed" — and stopped one step short. The remediation for this blocker is owned by
        # BACKEND and ends "those are FRONTEND: bug_create for frontend WITH THE NAMES", but
        # the lane only ever receives the blocker string, and `coverage_audit_check` (the
        # tool that would answer the question) is orchestrator-only: gate_registry.py:388,
        # "coverage_tools bundle restricts callers to orchestrator". So the owner was told to
        # relay names it had no way to obtain.
        "dead_names": _dead_artifact_names_1086(report),
    }


def _dead_artifact_names_1086(report, cap: int = 20) -> List[str]:
    """``kind:name`` for each dead artifact, bounded. Kind-prefixed so the routing sentence
    in the remediation ("endpoints/tables/mcp_tools are yours … files are FRONTEND") can be
    acted on without a second lookup. Never raises — this feeds a gate."""
    out: List[str] = []
    try:
        for kind, items in (("endpoints", report.dead_endpoints),
                            ("tables", report.dead_tables),
                            ("files", report.dead_files),
                            ("mcp_tools", report.dead_mcp_tools),
                            ("empty_mcp_servers", report.empty_mcp_servers),
                            ("pages_without_files", report.pages_without_files)):
            for item in (items or []):
                if len(out) >= cap:
                    return out
                if isinstance(item, dict):
                    name = (item.get("path") or item.get("id") or item.get("name")
                            or item.get("tool") or "")
                    if not name:
                        method, path = item.get("method"), item.get("route")
                        name = f"{method} {path}".strip() if (method or path) else str(item)
                else:
                    name = str(item)
                name = str(name).strip()
                if name:
                    out.append(f"{kind}:{name}")
    except Exception:
        return out
    return out


def _ui_page_wiring_blockers(hub_registry, app_root) -> List[str]:
    """ui_pages with a HARD wiring defect (declared route not wired in App.jsx,
    or declared component file missing) → delivery blockers.

    Deterministic from code; recomputed each gate tick so a fixed page clears
    it (never a permanent block). Crucially this is NOT relaxed on a
    functionally-validated app: the framework api_smoke probes the BACKEND
    only — it never opens a frontend page, so an unwired page (round 44's
    blank-screen-but-api_smoke-green class) must still block delivery."""
    try:
        from .frontend_audit import ui_page_delivery_blockers
    except Exception as exc:
        _gate_absent_792("_ui_page_wiring_blockers", exc, "run")
        return []
    workhub = getattr(hub_registry, "workhub", None)
    if workhub is None:
        return []
    # #566b: reconcile lane-authored REAL page components onto integration BEFORE the audit
    # reads (mirrors #324's seed reconcile). Else a page the frontend lane already built in
    # its worktree, but not yet merged, reads as the integration stub → a spurious
    # deliverability_ui_page_unwired that can persist and trip the 7-cycle STUCK-ABORT
    # (netflix r113). Idempotent, best-effort, never clobbers a real integration page.
    try:
        from .heal_pipeline import reconcile_integration_frontend_pages
        reconcile_integration_frontend_pages(Path(app_root).parent)
        # #566e: also wire DECLARED routes into integration App.jsx (the route analogue of #566b's
        # component reconcile). A lane's committed App.jsx route edit reaches integration only via a
        # conflict-abort/supersede merge, so it can sit unmerged across every poll → 'route not wired'
        # stays red → re-dispatch churn (r117). Source the same page set the audit uses; additive +
        # idempotent, so byte-identical once all routes are wired. Component reconcile runs FIRST so the
        # injected ./pages/{comp} import resolves to a real component.
        from .heal_pipeline import reconcile_integration_frontend_app_jsx
        _pages = workhub.get_ui_pages() or {}
        reconcile_integration_frontend_app_jsx(Path(app_root).parent, list(_pages.values()))
    except Exception:
        pass
    # #700: REPORT the #615 groups. The detector `duplicate_route_content_groups` has existed
    # since #615 and has never been called — not as a blocker and not as anything else. Its own
    # comment explains the first half and leaves the second open: "Deliberately NOT wired as a
    # delivery blocker. At 32/45 it would wedge nearly every run, and whether 'six identical
    # pages' should block OR MERELY BE REPORTED is a calibration decision." Nobody took the
    # reporting option either, so a defect measured in 32 of 45 runs has never once been said
    # out loud.
    #
    # It still happens. Running the detector over r146's DELIVERED frontend finds one group:
    # /browse, /browse/browse-by-languages, /browse/games and /browse/latest all fetch the
    # bare unparameterised /api/titles, so four nav destinations render identical content.
    # r145 finds none, so this is not a universal artifact of the projection.
    #
    # WARNING only — the calibration decision is untouched and nothing blocks. Same disposition
    # as #691, #696 and #698: a finding that is computed and unobservable is worth no more than
    # one that was never computed.
    #
    # NOTE THE PATH. `ui_page_delivery_blockers` below takes frontend/**src**, but
    # `duplicate_route_content_groups` appends "src"/"pages" itself and so takes the frontend
    # ROOT. Passing it the same argument as the line below silently returns [] — its contract
    # is "[] when nothing can be resolved", which is indistinguishable from "nothing found".
    try:
        # Fetches its OWN pages rather than reusing `_pages` above: that name is bound inside a
        # try/except-pass, so if the reconcile raised, reusing it would NameError into this
        # block's own except and skip the report silently — the exact failure mode this fix is
        # about.
        from .frontend_audit import duplicate_route_content_groups
        _pages_700 = workhub.get_ui_pages() or {}
        # #708b: name the filters the CONTRACT already declares for the shared endpoint, so the
        # report says what to do and not just what is wrong. #615 declined to fix the cause partly
        # because "the seed gives every title kind='standard'" — retired in #708: the shipped
        # seed_dataset.json carries kind movie/series and real genres, and the endpoint's own
        # `schema.request` records its optional query params. Reading them here costs one lookup
        # and turns "these 5 routes are the same page" into "…and /api/titles takes kind, genre,
        # language". Purely contract-derived; no product vocabulary.
        def _filters_708b(endpoints):
            try:
                _rh = getattr(hub_registry, "registryhub", None)
                _all = (_rh.get_endpoints() or {}) if _rh is not None else {}
            except Exception:
                return {}
            out = {}
            for _ep in endpoints or []:
                for _rec in _all.values():
                    if not isinstance(_rec, dict):
                        continue
                    if str(_rec.get("path") or "") != str(_ep):
                        continue
                    _req = ((_rec.get("schema") or {}).get("request") or {})
                    _opt = [k for k, v in _req.items()
                            if isinstance(v, str) and v.endswith("?")
                            and k not in ("limit", "offset", "page", "per_page")]
                    if _opt:
                        out[_ep] = sorted(_opt)
                    break
            return out
        # #728: name the CAUSE beside #700's symptom. #700 says "these routes render identical
        # content"; when the reason is that a page calls another page's endpoint while its own
        # sits implemented and unused, say so — r148 shipped GenreCategoryPage fetching
        # /api/my-list with GET /api/genres/{id}/titles implemented and untouched.
        try:
            from .frontend_audit import crossed_page_endpoints_728
            _rh728 = getattr(hub_registry, "registryhub", None)
            _eps728 = (_rh728.get_endpoints() or {}) if _rh728 is not None else {}
            _cross728 = crossed_page_endpoints_728(_pages_700, _eps728) or []
            # #1202bu: report the STATE, not once per deliverability_check. r34 logged 382
            # copies of the same two findings — 193 for my_list_page and 189 for
            # browse_home_page — because this runs on every check and the finding does not
            # change until a lane re-registers the page. Same rule as #1202n/#1202p/#1202v/
            # #1202ab/#1202au; a finding that CHANGES is news and reports again.
            from .message_format import state_changed_1202ad as _sc728
            if _cross728 and not _sc728(
                    "crossed_page_endpoints_728",
                    tuple(sorted(str(_x) for _x in _cross728))):
                _cross728 = []
            for _x in _cross728:
                _LOG_700.warning(
                    "#728 %s (%s) declares %s, which shares no path word with its own route, "
                    "while %s is implemented and used by nothing. The page is calling another "
                    "page's endpoint — code and declaration agree, so the consistency audits "
                    "pass on the wrong thing.",
                    _x["page"], _x["route"], ", ".join(_x["declares"]),
                    ", ".join(_x["unused_match"][:1]))
        except Exception:
            pass
        for _g in duplicate_route_content_groups(Path(app_root) / "frontend", _pages_700) or []:
            # #760: SAY IT ONCE PER GROUP, NOT ONCE PER PASS. This runs on every deliverability
            # sweep, and r149 logged `routes render identical content` **108 times carrying two
            # distinct findings** — the same two groups, 54 times each. That is not a cosmetic
            # problem: it buries every other warning in the file, and it makes a COUNT
            # meaningless. My own checker line reported "#700 identical-content routes x108",
            # which reads as 108 defects and is 2.
            #
            # Keyed on the group's identity, so a group that CHANGES (a route joins or leaves)
            # is reported again — the interesting event — while a stable one is stated once.
            #
            # Bounded by item 78's dual-import hazard rather than defeated by it: this module
            # is in sys.modules under both `multi_agent...` and `env_generator...`, so this set
            # exists twice and a group can be announced at most TWICE per run. 108 -> <=2 is the
            # fix; pretending the set is a singleton would be the bug.
            _key760 = (tuple(_g.get("routes") or []), tuple(_g.get("endpoints") or []))
            if _key760 in _SAID_700:
                continue
            _SAID_700.add(_key760)
            _f708 = _filters_708b(_g.get("endpoints"))
            if _f708:
                _LOG_700.warning(
                    "#615 the shared endpoint(s) already accept filters the contract declares: "
                    "%s — a route-derived filter is available, the pages just do not pass one.",
                    "; ".join(f"{k} takes {', '.join(v)}" for k, v in sorted(_f708.items())))
                # #780: FILE IT. Everything above is a log line, and the lane does not read the
                # log. r151 computed all of it — "6 routes render identical content: /browse,
                # /browse/languages, /games, /movies, /new, /shows" and "/api/titles takes genre,
                # kind, language — the pages just do not pass one" — printed it ONCE in a
                # 116-minute run, and filed nothing. 136 tasks existed; none was this.
                #
                # This is #748/#740/#769/#770's family with the stakes raised: those discarded a
                # CAUSE, and this discards a FIX. The framework has the route list, the endpoint,
                # and the exact parameter names the endpoint accepts.
                #
                # Gated on `_f708` deliberately. Without declared filters the finding is "these
                # pages look alike", which #615's own comment refuses to act on ("at 32/45 it
                # would wedge nearly every run"). WITH them it is a one-line change per page, and
                # naming the parameter is what makes it a task rather than an observation.
                #
                # Deduped by #760's key, so one task per distinct group per process, and
                # create_task's own #672 twin-check catches a repeat across processes.
                try:
                    _routes780 = ", ".join(_g.get("routes") or [])
                    _params780 = "; ".join(f"{k} accepts {', '.join(v)}"
                                           for k, v in sorted(_f708.items()))
                    workhub.create_task(
                        title=f"Pass a route-derived filter on: {_routes780}"[:180],
                        description=(
                            f"These {len(_g.get('routes') or [])} routes render IDENTICAL "
                            f"content because each calls {', '.join(_g.get('endpoints') or [])} "
                            f"with no query parameter: {_routes780}.\n\n"
                            f"The contract already declares the filters: {_params780}.\n\n"
                            "Fix: give each page the parameter its own route implies (e.g. a "
                            "/movies page passes the kind that means film, /browse/languages "
                            "passes language) and label its rows from that grouping. Judges "
                            "report duplicated row titles on 39% of runs for exactly this "
                            "reason — different rows, one repeated heading, because there is no "
                            "grouping to name them from."),
                        assignee="frontend", agent="deliverability", priority="P1",
                        kind="fidelity")
                except Exception as _t780:
                    _LOG_700.warning(
                        "#780 could not file the route-filter task (%s: %s) — the finding above "
                        "is therefore log-only again, which is the defect #780 exists to fix.",
                        type(_t780).__name__, str(_t780)[:120])
            # #959: and to an ARTIFACT, not only to the logger.
            #
            # #780 exists to stop this finding being log-only — it files a P1 fidelity task. But
            # the filing sits behind `if _f708:`, i.e. only when the framework can derive WHICH
            # filter each route should pass. When it cannot, the finding falls back to this log
            # line, which is the state #780 was written to end. Measured: **1 such task exists
            # across the whole corpus, in 1 run of 154**, while #615 fires routinely — twice in a
            # single gate evaluation on r154 (/browse/languages+/games+/shows all fetching only
            # /api/titles, and /movies+/new both fetching only /api/titles/top10).
            #
            # Five nav destinations showing the same list is a real fidelity defect and the visual
            # gate cannot see it (this line says so itself). Writing it costs nothing and changes
            # no behaviour; filing a task on every run would change what agents do, which needs a
            # live run to validate (#956/#957/#958's disposition).
            try:
                import json as _j959
                _f959 = Path(app_root).parent / "design" / "duplicate_routes_959.json"
                _f959.parent.mkdir(parents=True, exist_ok=True)
                _prev959 = {}
                if _f959.is_file():
                    try:
                        _prev959 = _j959.loads(_f959.read_text(encoding="utf-8")) or {}
                    except Exception as _r959:
                        # #883's guard caught this within the hour, and it was right: `is_file()`
                        # above already separates "no prior file" from "the file is there and will
                        # not parse", and `{}` collapses them back — every duplicate group
                        # recorded on an earlier tick would vanish from the artifact this one
                        # writes. #884 is the same defect one module over.
                        _LOG_700.warning(
                            "duplicate_routes_959.json is UNREADABLE (%s: %s) — earlier groups in "
                            "it are being dropped, not merged; this tick's file will hold only "
                            "what it found now.", type(_r959).__name__, str(_r959)[:100])
                        _prev959 = {}
                _prev959[", ".join(_g.get("routes") or [])] = {
                    "routes": list(_g.get("routes") or []),
                    "endpoints": list(_g.get("endpoints") or []),
                    "components": list(_g.get("components") or []),
                    "task_filed": bool(_f708),
                }
                _f959.write_text(  # raw: design/, outside app/ (#1202ts)
                    _j959.dumps(_prev959, indent=1, sort_keys=True), encoding="utf-8")
            except Exception as _e959:
                # #883's rule, applied to my own handler: a swallow in a gate file must say so.
                # Its guard caught this within the hour — the write is best-effort (observability
                # must not break the gate it observes) but a LOST artifact is not a clean one.
                _LOG_700.warning(
                    "could not persist duplicate_routes_959.json (%s: %s) — the finding below is "
                    "log-only again, which is what #959 exists to stop.",
                    type(_e959).__name__, str(_e959)[:120])
            _LOG_700.warning(
                "#615 %d routes render identical content: %s — all fetch only %s (components: "
                "%s). Not a blocker; a nav destination that shows the same list as its siblings "
                "is a fidelity defect the visual gate cannot see.",
                len(_g.get("routes") or []), ", ".join(_g.get("routes") or []),
                ", ".join(_g.get("endpoints") or []), ", ".join(_g.get("components") or []))
    except Exception as _dupe_exc_1067:
        # #1067: say it. This block's own preamble is "a finding that is computed and
        # unobservable is worth no more than one that was never computed", and it goes to
        # the trouble of re-fetching pages rather than reuse a name bound inside another
        # try/except-pass — because that would "skip the report silently — the exact
        # failure mode this fix is about". Then it ended in a bare `pass`, so 173 lines of
        # duplicate-route reporting could vanish per gate tick with nothing recorded.
        # Once per process, with the exception type; the verdict is unchanged.
        if not _DUPE_REPORT_FAILED_1067["said"]:
            _DUPE_REPORT_FAILED_1067["said"] = True
            _LOG_700.warning(
                "#1067 duplicate-route report SKIPPED: %s: %s. The gate verdict below is "
                "unaffected, but this run has no duplicate-route findings because the "
                "reporter raised, not because there are none. Logged once per process.",
                type(_dupe_exc_1067).__name__, str(_dupe_exc_1067)[:200])
    try:
        return ui_page_delivery_blockers(Path(app_root) / "frontend" / "src", workhub)
    except Exception as _wiring_exc_1202tm:
        # #1202tm: this is the producer of `deliverability_ui_page_unwired` -- the most
        # frequent blocker in the corpus -- and returning [] means the GATE SEES ZERO UNWIRED
        # PAGES. "Could not look" and "nothing to find" are the same answer to every reader.
        #
        # The right treatment is ten lines above, in this same function: #1067 says of the
        # duplicate-route reporter that "this run has no duplicate-route findings because the
        # reporter raised, not because there are none." One fact, two emitters, the guard on
        # one of them.
        #
        # The VERDICT is left alone, exactly as #1067 left it: turning a detector fault into a
        # blocker would wedge a run on the framework's own error, which is the opposite of what
        # a gate is for. Only the silence goes.
        if not _WIRING_REPORT_FAILED_1202TM["said"]:
            _WIRING_REPORT_FAILED_1202TM["said"] = True
            _LOG_700.warning(
                "#1202tm ui_page wiring report SKIPPED: %s: %s. The gate verdict below is "
                "unaffected, but this run has no unwired-page findings because the reporter "
                "raised, not because every page is wired. Logged once per process.",
                type(_wiring_exc_1202tm).__name__, str(_wiring_exc_1202tm)[:200])
        return []


def _bare_fetch_blockers(app_root) -> List[str]:
    """#154 (§6-1, gmrun4): bare unauthenticated ``fetch('/api/…')`` call sites →
    delivery blockers. Purely static (frontend source only), recomputed each gate
    tick, best-effort ``[]`` on any fault. ``ENVGEN_BARE_FETCH_GATE=0`` disables."""
    if os.environ.get("ENVGEN_BARE_FETCH_GATE", "1").lower() in ("0", "false", "no", "off"):
        return []
    try:
        from .frontend_audit import bare_authed_fetch_blockers, inject_auth_fetch_wrapper
    except Exception as exc:
        _gate_absent_792("_bare_fetch_blockers", exc, "import")
        return []
    try:
        _fe = Path(app_root) / "frontend"
        # #566r: install the global auth-fetch wrapper (idempotent) BEFORE the audit reads, so a
        # bare fetch('/api/…') is auth'd at runtime and the gate self-clears deterministically —
        # not dependent on lane/remediation/reconcile timing (r126 wedged 79min because the lane's
        # fix reached the gate-read integration tree only after the no-convergence abort).
        try:
            inject_auth_fetch_wrapper(_fe)
        except Exception as _rep770:
            # #770: A REPAIR THAT FAILS SILENTLY REPORTS ITS OWN SYMPTOM. The very next line is
            # the blocker check this repair exists to clear, so a throw here means the gate
            # blocks and nothing says the framework already tried and could not. The lane is
            # then handed a blocker it cannot reconcile with the code in front of it. #769's
            # class one layer up: the reason was caught and dropped at the `except`.
            _LOG_700.warning(
                "#770 auto-repair inject_auth_fetch_wrapper failed (%s: %s) — the blocker check below may now "
                "report the very defect this was meant to clear, so read it as a CONSEQUENCE "
                "before dispatching a lane at it.",
                type(_rep770).__name__, str(_rep770)[:160])
        return bare_authed_fetch_blockers(_fe / "src")
    except Exception as exc:
        _gate_absent_792("_bare_fetch_blockers", exc, "run")
        return []


def _stub_handler_blockers(app_root) -> List[str]:
    """#173 (gmrun9): a GET route handler that does NO DB read and returns only a hardcoded
    EMPTY collection is a PLACEHOLDER STUB (backend twin of a mock page) → delivery blocker.
    The lane 'implemented' /api/transit/{id}/departures as ``return {"items": []}`` while real
    seed data existed; the DeparturesPage then shipped 'No departures found.' forever. Static
    AST, recomputed each gate tick, best-effort ``[]``. ``ENVGEN_STUB_HANDLER_GATE=0`` off."""
    try:
        from .backend_audit import stub_handler_blockers
    except Exception as exc:
        _gate_absent_792("_stub_handler_blockers", exc, "import")
        return []
    try:
        return stub_handler_blockers(Path(app_root) / "backend")
    except Exception as exc:
        _gate_absent_792("_stub_handler_blockers", exc, "run")
        return []


def _auth_override_blockers_1202s(app_root) -> List[str]:
    """#1202s: lane code that replaces the framework's password check.

    r30 delivered milestone 1 at 13:32:37 carrying a `custom_routes.py` patch merged at
    13:10:30 that reassigned `OAuthStore.verify_user_password` to a helper which, on a wrong
    password for an EXISTING user, overwrote that user's password_hash and returned it — and
    created the account outright for an unknown email. Verified against the delivered stack:
    a wrong password returns 200 with a valid bearer token, and so does an email that has
    never existed. Only an empty pair is refused.

    The framework's denial-probe chain did catch it (`POST /auth/login -> 200, expected
    [401, 400]`) and blocked milestone 2 until the run aborted STUCK — 148 minutes and one
    release too late, because that probe runs in validation and the release gate had already
    passed. This blocks at the gate on the structural property instead: the framework owns
    /auth/login and /auth/register, so lane code reassigning an auth primitive is never
    legitimate. Static and best-effort — `[]` on any failure, per #792.
    """
    try:
        from .backend_audit import auth_override_findings_1202s
    except Exception as exc:
        _gate_absent_792("_auth_override_blockers_1202s", exc, "import")
        return []
    try:
        return auth_override_findings_1202s(Path(app_root) / "backend")
    except Exception as exc:
        _gate_absent_792("_auth_override_blockers_1202s", exc, "run")
        return []


def _declared_in_1203b4(hit: str, spec) -> bool:
    """Did the materials declare a verdict for the table this hit names? #1203b4

    Each hit is built two lines above as ``"%s %s (table `%s`: ...)"``, so the table name is
    read back from the one place it is written rather than re-resolved -- re-running
    `_resource_model` here could disagree with the string the lane is about to read.
    """
    try:
        import re as _re1203b4
        m = _re1203b4.search(r"\(table `([^`]+)`", str(hit))
        if not m:
            # Not a fault: the hit carries no table name, so the materials cannot have a
            # verdict for it and the silent half is the right one.
            return False
        from .backend_skeleton import _spec_verdict_for_table_1202oh
        return bool(_spec_verdict_for_table_1202oh(m.group(1), spec or {}))
    except Exception as exc:
        # #1202ah: a swallowed fault here would route the hit into the materials-SILENT half
        # and the lane would be told to re-register a table the materials may well have
        # settled -- a crashed check reading as a decided one, which is what that ratchet
        # exists to stop. Announced the way every sibling in this module announces.
        _gate_absent_792("_declared_in_1203b4", exc, "run")
        return False


def _shape_demoted_publics_1202y9(app_root, hub_registry) -> str:
    """One sentence naming the contract-public routes the SHAPE projected private. `""` on
    anything unreadable.

    This is the answer to the question a tampering lane is asking. r140: the lane registered
    `GET /api/feed` `auth_required=False` at 03:17:07 because the logged-out landing page
    reads it; the materials said NOTHING about `feed`; `_structurally_private_resource_633`
    demoted it on shape alone (`author_id -> users` beside `sound_id -> sounds`, the #598
    signal); the projected handler took an actor; the anonymous request came back 401; and
    the lane appended to `_FW_PUBLIC_API_1202KH` from custom_routes.py. The gate then blocked
    delivery 8 times across 90 minutes.

    The framework KNEW all of that. `announce_shape_override_1202vt` said it 39 times on that
    run -- into `route_projector`'s logger. Measured on r140: `SHAPE OVERRODE`, `1202vt` and
    `materials declare NOTHING` appear in ZERO files under `shared/hubs/` -- the tasks,
    messages and documents that are the whole of what a lane can read. The notice fired and
    reached nobody. #1202kx's own comment is the test this fails: "a lane that knew WHY it
    was being refused had no reason to build that."

    And the remediation text is not a substitute, because it gives the RULE and not this
    failure: "change its CONTRACT (`auth_required: false` on a table the materials call
    public)". The lane did the first half. The half it could not see -- that the materials
    say nothing about this table, so the shape decided -- is exactly what this sentence
    carries, at the moment the lane is stopped.

    Corpus: `deliverability_guard_tampering` blocked 10 of the 86 runs with a gate ledger
    (12%, 63 occurrences) and is present in every one of the last eight -- r133 (26x), r134,
    r136, r137, r138, r139 (10x), r140. #1202vt has been live for three of those (firing 109,
    75 and 39 times) and the tampering happened anyway, which is what "announced to the wrong
    audience" predicts.

    Recomputed here rather than carried: the announcer has no run directory to write to, and
    reading the same predicate the projector used keeps the gate and the generator from
    disagreeing about what is private (#1032).
    """
    try:
        from .backend_audit import _models_919
        from .route_projector import (_structurally_private_resource_633 as _priv1202y9,
                                      _resource_model as _res1202y9)
        models, _ = _models_919(Path(app_root) / "backend")
        if not models:
            return ""
        # #1203b4: SEE WHAT THE PROJECTOR SAW. `_priv1202y9` reads `meta["visibility"]`, and
        # the projector stamps the materials' verdict onto its models BEFORE asking
        # (route_projector.py's `_stamp_spec_visibility_1202og` call). This function did not,
        # so the same predicate on the same app answered the opposite way: measured on r144,
        # it emitted 1008 characters saying `GET /api/feed` "was projected WITH an actor"
        # while the delivered handler `_projected_get_api_feed_1` takes (limit, offset, db)
        # and no actor, because `videos` had already been stamped `public`. The lane was
        # handed an explanation it could not reconcile with its own code, and went for the
        # guard this very blocker calls forbidden.
        #
        # Corpus, 71 runs where this fires: 42 unchanged (the materials are silent -- r140's
        # `feed`, the case it was built for) and 29 change.
        _spec1203b4 = {}
        try:
            from .backend_skeleton import _spec_visibility_1202hh as _sv1203b4
            from .route_projector import _stamp_spec_visibility_1202og as _stamp1203b4
            # `app_root` is `<run>/app`; the spec lives at `<run>/design/reference_spec.json`.
            # `Path(app_root).parent` is this module's own convention for the run root (seven
            # other call sites, incl. `Path(app_root).parent / "design" / ...`). Passing
            # `app_root` reads `<run>/app/design/`, which does not exist: the loader returns {},
            # nothing is stamped, and the fix silently does nothing. My first draft did exactly
            # that -- the monkeypatched experiment that proved the fix used the run root, the
            # patch used `app_root`, and only running the real code showed 1016 chars instead
            # of 0 on r144.
            _root1203b4 = Path(app_root).parent
            _spec1203b4 = _sv1203b4(_root1203b4) or {}
            _stamp1203b4(models, _root1203b4)
        except Exception as _e1203b4:
            # Not swallowed: without the stamp this says what it said before #1203b4, which
            # is the wrong half of a disagreement -- so the reader has to know it happened.
            _gate_absent_792("_shape_demoted_publics_1202y9/stamp_1203b4", _e1203b4, "run")
        # #1202rm already paid for this once: "the method is get_endpoints, not
        # list_endpoints. The first draft guessed." Same accessor, same order.
        _rh1202y9 = getattr(hub_registry, "registryhub", None) or hub_registry
        _get1202y9 = (getattr(_rh1202y9, "get_endpoints", None)
                      or getattr(_rh1202y9, "list_endpoints", None))
        if not callable(_get1202y9):
            return ""
        try:
            eps = _get1202y9() or {}
        except Exception:
            return ""
        # the table records, for the owner-scope attribution below. Absent is fine --
        # but #883's rule applies: the empty default is set BEFORE the try, so the
        # handler carries no silent `= {}`, and a reader that FAILS says so. Losing the
        # attribution costs the blocker the one fact a lane cannot derive (which chain
        # owner-scoped the table), so it must not vanish quietly.
        _tables1202y9 = {}
        try:
            _gt1202y9 = (getattr(_rh1202y9, "get_tables", None)
                         or getattr(_rh1202y9, "list_tables", None))
            if callable(_gt1202y9):
                _tables1202y9 = _gt1202y9() or {}
        except Exception as _et1202y9:
            _gate_absent_792("_shape_demoted_publics_1202y9/table-attribution",
                             _et1202y9, "run")
        hits = []
        for rec in (eps.values() if isinstance(eps, dict) else (eps or [])):
            if not isinstance(rec, dict):
                continue
            if ((rec.get("schema") or {}).get("auth_required")) is not False:
                continue
            _m = str(rec.get("method") or "").upper()
            _p = str(rec.get("path") or "")
            # `/api/v1/*` is the framework's own tenancy control plane, never the lane's
            # question, and `/auth/*` is public by construction.
            if not _p.startswith("/api/") or _p.startswith("/api/v1/"):
                continue
            try:
                # #1202zn: `explicit_public=True` — every record reaching here was filtered
                # on `auth_required is False` twelve lines up, which IS the deliberate
                # declaration the predicate now takes. The gate must ask the projector's
                # question with the projector's arguments or it names routes that were never
                # demoted (#1032, and this function's own note about recomputing rather than
                # carrying).
                if not _priv1202y9(_m, _p, models, True):
                    continue
            except Exception:
                continue
            # #1202y9 (cross-domain check): `_resource_model` returns None for a
            # feed/search path that names no table, and the predicate above resolves it
            # through the SAME two fallbacks — so naming the table `?` here describes a
            # route the decision was made about and tells the lane nothing. Caught on
            # netflix-local-r30: "GET /api/search (table `?`: no FKs)". Call the projector's
            # own helpers rather than restating the rule (#1032).
            _r = _res1202y9(_p, models)
            if _r is None:
                # #883: the empty default is the value `_r` already holds, so the handler
                # carries no silent `= None` — and a fallback that FAILS says so, because
                # losing it turns a named table back into the `?` this exists to remove.
                try:
                    from .route_projector import (_search_target_model as _stm1202y9,
                                                  _primary_content_model as _pcm1202y9)
                    _r = (_stm1202y9(models) if "search" in _p.lower() else None) \
                        or _pcm1202y9(models)
                except Exception as _ef1202y9:
                    _gate_absent_792("_shape_demoted_publics_1202y9/table-fallback",
                                     _ef1202y9, "run")
            if _r is None:
                # Nothing nameable: a route with no table is not a story the lane can act
                # on, and spending a slot of the capped evidence on `?` costs a real one.
                continue
            _fks = (_r[1] or {}).get("fks") or {}
            # #1202y9: and WHO owner-scoped the table, when the record says. r140's `feed`
            # carries `owner_scoped_reads_set_by_chain_1202kv: authored_video_ownership_flow`
            # -- a verification chain flipped it, which is a cause no amount of reading the
            # lane's own code would reveal. r118 lost an hour to exactly this, going six
            # rounds against a flag it never touched.
            # No try here on purpose (#883): every step is a guarded `.get` on a value
            # already proven to be a Mapping, so there is nothing to catch -- and an
            # `except: _by = ""` would be exactly the silent empty default the ratchet
            # is counting.
            _by = ""
            _rec1202y9 = _tables1202y9.get(_r[0]) if isinstance(_tables1202y9, dict) else None
            _tm = _rec1202y9.get("metadata") if isinstance(_rec1202y9, dict) else None
            if isinstance(_tm, dict) and _tm.get("owner_scoped_reads") is True:
                _who = (_tm.get("owner_scoped_reads_set_by_chain_1202kv")
                        or _tm.get("owner_scoped_reads_cleared_by_1202io"))
                _by = ", owner-scoped%s" % (" by chain `%s`" % _who if _who else "")
            hits.append("%s %s (table `%s`: %s%s)" % (
                _m, _p, _r[0],
                ", ".join("%s->%s" % kv for kv in sorted(_fks.items())) or "no FKs", _by))
        if not hits:
            return ""
        # #1203b4: the sentence used to say "the table carries no `visibility`" of every
        # hit. After the stamp above that is only true of the SILENT ones -- a table the
        # materials call `owner` now reaches here BECAUSE of the verdict, not despite it, and
        # telling that lane to "re-register with visibility: 'public'" would have it overwrite
        # a deliberate verdict. #1202me made exactly this split, one module over: settled
        # where the materials speak, unresolved where they do not.
        _silent1203b4 = [h for h in hits if not _declared_in_1203b4(h, _spec1203b4)]
        _owned1203b4 = [h for h in hits if _declared_in_1203b4(h, _spec1203b4)]
        _out1203b4 = " WHY THE 401 YOU ARE WORKING AROUND HAPPENS:"
        if _silent1203b4:
            _out1203b4 += (
                " %s — these are declared `auth_required: false`, but the materials say "
                "NOTHING about the table, so the SHAPE decided (a users FK beside another "
                "entity's FK reads as per-user-private, #598) and the handler was projected "
                "WITH an actor. The contract's half you already did; the half you cannot see "
                "is the table's. THE WAY OUT, and editing the guard is not it: re-register "
                "that table with `metadata.visibility: 'public'` — the write boundary then "
                "also clears `owner_scoped_reads` (#1202io), which is the flag actually "
                "filtering the rows. Use `'owner'` instead if the rows really are per-user, "
                "and fix the endpoint's `auth_required` to match."
                % join_capped(_silent1203b4, total=len(_silent1203b4), cap=4, sep="; "))
        if _owned1203b4:
            _out1203b4 += (
                " %s — here the materials DO speak and they say `owner`, so the table is not "
                "missing a verdict and re-registering it `public` would overwrite one. The "
                "endpoint declaring `auth_required: false` is the half that disagrees: either "
                "the read really is per-user and the CONTRACT is wrong, or the materials are "
                "and the dataset entity has to be corrected. Editing the framework guard "
                "changes neither."
                % join_capped(_owned1203b4, total=len(_owned1203b4), cap=4, sep="; "))
        return _out1203b4
    except Exception as exc:
        _gate_absent_792("_shape_demoted_publics_1202y9", exc, "run")
        return ""


def _guard_tampering_blockers_1202oj(app_root, hub_registry=None) -> List[str]:
    """#1202oj — #1202lj's findings, delivered to the gate. It had no caller at all.

    `framework_guard_tampering_1202lj` (backend_audit) detects lane code that strips or rebinds
    the framework's auth guard — the shape that makes an anonymous read of owner-private rows
    legitimate-looking to every later check. Committed 2026-09-12; across the four runs since
    (r123-r126) its condition is present in EVERY ONE (r126 `custom_routes.py:352`
    `app.router.routes[:] = kept`; r125:618 rebinds `_FW_PUBLIC_API_1202KH`; r123:221 rebinds
    `_fw_contract_public_1202kh`) and it fired zero times, because the only importer in the tree
    was its own unit test. Its sibling `auth_override_findings_1202s` reaches the gate through
    this exact channel and its findings appear in six gate ledgers.

    Wired like the siblings: import-guarded, best-effort, `[]` on any failure (#792).
    ``ENVGEN_GUARD_TAMPER_GATE=0`` disables.
    """
    try:
        import os as _os1202oj
        if str(_os1202oj.environ.get("ENVGEN_GUARD_TAMPER_GATE", "1")).strip().lower() in (
                "0", "false", "no"):
            return []
        from .backend_audit import framework_guard_tampering_1202lj
    except Exception as exc:
        _gate_absent_792("_guard_tampering_blockers_1202oj", exc, "import")
        return []
    try:
        out = [f"framework auth guard tampered with: {f}"
               for f in (framework_guard_tampering_1202lj(Path(app_root) / "backend") or [])]
        # #1202y9: ...and why the route the lane was opening is refused. Appended to the
        # FIRST finding rather than added as its own entry, so every line still maps to
        # this one check id (#1202tu: a blocker whose prose routes nowhere dispatches
        # nobody) — and appended, not prepended, so the file:line evidence keeps the head
        # of the message (#1202vx).
        if out and hub_registry is not None:
            _why1202y9 = _shape_demoted_publics_1202y9(app_root, hub_registry)
            if _why1202y9:
                out[0] = out[0] + _why1202y9
        return out
    except Exception as exc:
        _gate_absent_792("_guard_tampering_blockers_1202oj", exc, "run")
        return []


def _unscoped_owner_read_blockers(app_root) -> List[str]:
    """#919: a served GET that returns every row of an OWNED table to any authenticated caller.

    The page-level PRIVACY axis, and the last of the three defects this session found by reading
    the delivered app that no gate looked for. #908 was live in r153 -- `GET /api/my-list`
    answering `db.query(MyList).limit(100).all()` beside a POST that 403s a foreign `profile_id`
    -- and it cleared every check in the framework.

    Blocks, like its siblings #173 and #175, and for the same reason: those report a FUNCTIONAL
    defect in the delivered artifact, not a description that drifted. (#909/#910/#918 report
    instead, because a contract describing a different page is not a broken app.) Measured over
    the 153 delivered backends: **159 findings across exactly two endpoints** -- `/api/my-list`
    (79) and `/api/continue-watching` (80), both genuinely per-user, no other path -- so the
    false-positive rate on this corpus is zero. ``ENVGEN_OWNER_READ_GATE=0`` disables.
    """
    try:
        import os as _os
        if str(_os.environ.get("ENVGEN_OWNER_READ_GATE", "")).strip() == "0":
            return []
    except Exception:
        pass
    try:
        from .backend_audit import unscoped_owner_read_findings
    except Exception as exc:
        _gate_absent_792("_unscoped_owner_read_blockers", exc, "import")
        return []
    try:
        return unscoped_owner_read_findings(Path(app_root) / "backend")
    except Exception as exc:
        _gate_absent_792("_unscoped_owner_read_blockers", exc, "run")
        return []


# #1202w: a PLACEHOLDER page must not be a reachable route.
#
# netflix-r25 shipped `NoopVerifierRead.jsx` carrying the framework's own
# "framework-projected page" header — I had blamed the lane for that file and was wrong; a lane
# registered the junk ui_page NAME and the projector dutifully built a page for it. Swept over
# the 97 runs with an App.jsx, four SHIPPED one as a live route:
#
#     instagram run76   DummyToGetRegistryList
#     tiktok r61        ExplorePlaceholderPage, FollowingPlaceholderPage, LivePlaceholderPage
#     tiktok r69        PlaceholderPage
#     tiktok r87        PlaceholderPage
#
# A user navigating there gets a placeholder, which is the user's standing bar exactly: no dead
# UI, no fake data. The name is a far sharper signal than "renders no API call" — that broader
# check flags NotFoundPage, FallbackPage and ComingSoonPage, which are legitimately static, and
# a gate that blocks those is the #566j false-blocker failure this repo has already paid for.
# Verified against the reverse case: NotFoundPage / FallbackPage / ComingSoonPage / ProfilePage
# all pass; PlaceholderPage does not.
_JUNK_PAGE_WORDS_1202W = "noop|dummy|placeholder|todo|fixme|untitled|testpage|foobar|temppage"


# #1202rj: WHOSE MACHINE BUILT THIS. An env is a place an agent is put to work; the moment it
# can tell the place was generated, the evaluation is over. The operator's own identity is the
# sharpest of those tells, and it arrives by a path nobody designed: design-prep transcribes a
# reference screenshot, the screenshot was taken from the operator's own signed-in account, and
# #778 tells the lane to render transcribed `copy` character for character. Measured on this
# corpus: `haibotong7` -- the operator's real handle -- reached the served app in r127, r128,
# r129 and r131, rendered as the signed-in user of a generated TikTok clone.
#
# #1202ri splits chrome copy from data slots so the transcription stops producing it. This is
# the BACKSTOP, because a prompt rule is not enforcement: this same lane already had "never
# ship fake data" while shipping 50 picsum URLs in r130.
#
# Deliberately narrow. It looks for THIS operator's identity, resolved from the build
# environment, not for "names that look personal" -- a seeded persona is supposed to have a
# name, and a detector that cannot tell them apart would block every honest app.
# #1202rm: EVERY PAGE DECLARES NO API, WHILE THE BACKEND HAS A CONTRACT.
#
# `apis_used` is read in 103 places across six modules -- the page projector, the registry, the
# frontend audit, the remediation dispatcher, kickoff and the scaffolder. Several judgements
# are built on it being non-empty: #151's decoy-twin check requires `apis` before it looks at
# what the route renders, the consumer-wiring audit has nothing to reconcile without it, and a
# page's defined->implemented flip stops asking whether its own APIs are referenced.
#
# So a lane that registers every page with `apis_used: []` does not fail those checks -- it
# switches them off, silently and all at once. Measured, and getting worse: r128 7 of 10 pages
# empty, r129 8 of 13, r130 14 of 14, r131 13 of 13. r131 is the run where an unprimed agent
# found nine of twelve pages rendering a mock module (#1202rl); nothing in the framework had
# said a word about a video app whose every page claims to need no data.
#
# The check is a contradiction, not a threshold: business endpoints EXIST in the registry and
# not one page claims to use any. An app with no business endpoints at all is a different
# thing and is not flagged.
# #1202rr: THE PAGE CALLS AN API AND ITS REGISTRATION SAYS IT CALLS NONE.
#
# #1202rm catches the all-empty case, where every page declares nothing and the checks built
# on `apis_used` switch off together. It cannot see the partial one: a page whose own file
# plainly contains `api.get(...)` while its registration carries `apis_used: []`. Everything
# downstream then reasons from a registry that contradicts the code -- #151 skips the page
# (no `apis`), the consumer-wiring audit has nothing to reconcile for it, and its
# implemented-flip stops asking whether its APIs are referenced.
#
# Found by running today's gates across other domains to check they were not tiktok-shaped:
# googlemaps gmrun4, a SUCCESSFUL four-milestone delivery, has 4 pages registered with no APIs
# and 2 of them call one. That run passed every gate. Domain-agnostic by construction -- it
# compares a page's own source against its own registration, and names no product vocabulary.
def _api_client_calls_1202vk(page_text: str, _page_file=None) -> bool:
    """Does this page CALL the app's api client? #1202vk — delegates to the SHARED predicate.

    `#1202rr` recognised `api.get(` / `axios.get(` / `fetch(` / `apiGet(` and nothing else,
    and the framework's own projected frontend uses none of them: it routes every call
    through `services/api.js` named exports. The check built to catch an understated page
    was blind to the shape the framework itself generates. Over the corpus's 508 pages that
    declare `apis_used: []` and have a locatable source file, those patterns catch 118
    across 53 runs and this shape carries 142 more.

    `frontend_audit._has_real_api_call` is that predicate and it already existed, carrying
    three shapes and two scars this file must not re-learn: the direct call `getTasks()`,
    the service-object method `feed.get()` (run v11 false-flagged every page using it), and
    `#1202gk`'s hand-off to a hook, `useApiList(getVideos, [])` (tiktok-r98's ExploreGridPage
    blocked delivery as "a STATIC MOCK"). My first draft of this ticket reimplemented the
    first shape only, WITH a filter restricting it to exports whose body names
    `request`/`fetch`/`axios` — and the corpus showed that filter was simply wrong: r102's
    `getVideos`, r100's `getUser` and r119's `getVideos` all issue requests through
    module-local wrappers (`authed`, `publicRequest`, `authedGet`), so the filter rejected
    real API functions. The shared predicate is a strict superset: measured over the same
    pages, mine caught 123, it caught 142, and mine caught nothing it missed.

    One implementation, because two copies of one rule drift (#1032).
    """
    try:
        from .frontend_audit import _has_real_api_call
    except Exception as exc:
        # #1202ah: a silent False makes a CRASHED probe read as a page that calls nothing,
        # the one answer indistinguishable from a pass. Once per process.
        try:
            from .message_format import warn_once_1201
            warn_once_1201("_api_client_calls_1202vk", "the api-client call probe", exc)
        except Exception:
            pass
        return False
    try:
        return bool(_has_real_api_call(page_text))
    except Exception as exc:
        try:
            from .message_format import warn_once_1201
            warn_once_1201("_api_client_calls_1202vk", "the api-client call probe", exc)
        except Exception:
            pass
        return False


def _page_api_declaration_drift_1202rr(hub_registry, app_root) -> List[str]:
    """Pages whose source calls an API the registration does not list. `[]` on failure.

    #1202y1: WAS "while their registration declares none". Only an EMPTY `apis_used`
    triggered, so a page declaring one of its three calls was clean by construction -- and
    that empty-list trigger is why #1202wd refused to backfill from its own reader ("a
    half-resolved list written into the registry would silence it while the contradiction
    stood"). Comparing against the SOURCE removes the coupling: filling can no longer buy
    silence. 99 corpus runs hold a page whose non-empty `apis_used` understates its source
    -- the worst holds 14 pages over 53 endpoints, a recent one 5 over 15 -- and none of it
    was visible here.

    The reverse direction (declared but not called) is NOT flagged: a lane may register the
    contract it is about to consume, and Phase A does exactly that. Only code-says-yes /
    registry-says-no is a contradiction the registry loses information by.
    `ENVGEN_PAGE_API_DRIFT_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_PAGE_API_DRIFT_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        import re as _re
        rh = getattr(hub_registry, "registryhub", None)
        if rh is None or not hasattr(rh, "list_ui_pages"):
            return []
        pages = {k: v for k, v in (rh.list_ui_pages() or {}).items()
                 if k != "_meta" and isinstance(v, dict)}
        if not pages:
            return []
        src = Path(app_root) / "frontend" / "src"
        if not src.is_dir():
            return []
        call = _re.compile(r"\b(?:await\s+)?(?:api|axios)\s*\.\s*"
                           r"(?:get|post|put|patch|delete)\s*\(|\bfetch\s*\(|"
                           r"\b(?:apiGet|apiPost|apiPut|apiDelete)\s*\(")
        def _norm1202y1(a: Any) -> str:
            return _re.sub(r"\{[^}]*\}", "{}", str(a)).rstrip("/")

        drift = []
        for name, rec in sorted(pages.items()):
            # #1202y1: WAS `if rec.get("apis_used"): continue` -- the check only ever looked
            # at pages declaring NOTHING, so a page declaring ONE of its three calls was
            # clean by construction. That is also why #1202wd refused to backfill from its
            # own reader ("a half-resolved list written into the registry would silence it
            # while the contradiction stood"): with an empty-list trigger, any fill silences
            # it. Comparing the registry against the SOURCE removes that coupling -- a
            # partial list is still reported, so filling can never buy silence.
            #
            # Measured over the corpus: 99 runs hold a page whose `apis_used` is non-empty
            # and whose source calls MORE -- the worst 14 pages over 53 endpoints, two recent
            # ones 5/15 and 4/10 -- none of it visible to this check before.
            #
            # ONE DIRECTION ONLY. `page_api_endpoints_1202wd` does not traverse custom hooks
            # (one corpus page routes its calls through a `useCatalog` hook, so the reader
            # sees none of them), so `declared - source` is routinely non-empty and must NEVER
            # fire. `source - declared` is the safe direction: the reader missing a call makes
            # this check silent, not wrong.
            _decl1202y1 = {_norm1202y1(a) for a in (rec.get("apis_used") or [])
                           if isinstance(a, str)}
            comp = str(rec.get("component") or "")
            if not comp:
                continue
            for cand in (src / "pages" / f"{comp}.jsx", src / "components" / f"{comp}.jsx",
                         src / "pages" / f"{comp}.tsx"):
                if not cand.is_file():
                    continue
                try:
                    _txt1202vk = cand.read_text(encoding="utf-8", errors="ignore")
                    # #1202y4: ASK THE RESOLVER EVEN WHEN THIS FILE SHOWS NO CALL.
                    #
                    # #1202y1 changed what this compares (the registry against the source,
                    # not against the empty list) and left the ENTRY condition below as it
                    # was: the PAGE'S OWN text had to look like a call before the resolver
                    # was consulted at all. For the empty-declaration case that was fine.
                    # For understatement it is the wrong question -- what matters is whether
                    # the component TREE reaches more than the registry lists, which is
                    # exactly what `page_api_endpoints_1202wd` answers.
                    #
                    # Caught on a live run: a 19-line SignupPage that renders four default
                    # imports and calls nothing itself. The resolver reaches three endpoints
                    # through it and the registration names a fourth that is not among them,
                    # and this check returned nothing at all. Corpus: 46 runs hold a page the
                    # entry condition turns away while the resolver reaches endpoints the
                    # registry lacks -- one run 10 pages, two others 8 pages each whose
                    # single worst page is short by 11 and 12 endpoints.
                    #
                    # The unresolved-and-empty case still needs the own-call signal: with no
                    # endpoints resolved and nothing declared, "this page calls something"
                    # is the only evidence there is.
                    _eps1202y4 = []
                    try:
                        from .frontend_audit import page_api_endpoints_1202wd as _r1202y4
                        _eps1202y4 = _r1202y4(app_root, comp) or []
                    except Exception as _exc1202y4:
                        _gate_absent_792("page_api_endpoints_1202wd", _exc1202y4, "run")
                    _own1202y4 = bool(call.search(_txt1202vk)
                                      or _api_client_calls_1202vk(_txt1202vk, cand))
                    if _eps1202y4 or _own1202y4:
                        # #1202wd: NAME THE ENDPOINTS. This blocker fired 93 times across
                        # r135/r136/r137 saying a page "calls an API" and never which one, so
                        # the remediation asked the lane to work out what the framework had
                        # just measured. `page_api_endpoints_1202wd` follows the two kinds of
                        # delegation these frontends use -- component imports and intra-module
                        # export hand-offs -- and resolves 128 of the corpus's 260 flagged
                        # pages (49%) across 89 runs. It NEVER backfills: `apis_used` staying
                        # empty is what keeps this check firing, and a half-resolved list
                        # written into the registry would silence it while the contradiction
                        # stood. Reporting only, so a page it cannot resolve reads exactly as
                        # it did before.
                        # #1202y4: one read, taken above -- a second call would walk
                        # the same tree again for the same answer (#1032). The failure that
                        # the old try/except here reported is now reported at that one read,
                        # so an empty list still tells "unresolvable" apart from "broken"
                        # (#883); leaving a bodiless try/except behind would say nothing.
                        _eps1202wd = _eps1202y4
                        # #1202y1: what the SOURCE has that the REGISTRY lacks.
                        _miss1202y1 = [e for e in _eps1202wd
                                       if _norm1202y1(e) not in _decl1202y1]
                        if _miss1202y1:
                            _shown1202wd = _miss1202y1[:4]
                            _tail1202wd = ("" if len(_miss1202y1) <= 4
                                           else " +%d more" % (len(_miss1202y1) - 4))
                            # The entry stays SHORT on purpose: #1202tu's ratchet treats any
                            # literal over 30 chars in this module as a blocker sentence and
                            # demands it route to an owner. This is a list ITEM; the routable
                            # sentence is the one returned below. "unlisted" is also the
                            # accurate word -- the number is what the registry LACKS, not what
                            # the page calls.
                            drift.append("%s (%s) unlisted %d: %s%s" % (
                                name, cand.name, len(_miss1202y1),
                                ", ".join(_shown1202wd), _tail1202wd))
                        elif _eps1202wd:
                            pass        # the registry already lists everything the source calls
                        elif not _decl1202y1 and _own1202y4:
                            # The reader resolved nothing AND the page declares nothing: the
                            # old unresolved-and-empty case, reported exactly as before. A page
                            # that DECLARES something and that the reader cannot resolve is
                            # left alone -- firing there would be the hook blind spot guessing.
                            # #1202y4: and it still needs the OWN-call signal, because with no
                            # endpoints resolved that is the only evidence the page calls at all.
                            drift.append("%s (%s)" % (name, cand.name))
                except Exception:
                    pass
                break
        if not drift:
            return []
        return ["%d registered ui_page(s) understate `apis_used` while their own source calls "
                "an API: %s. Everything downstream then reasons from a registry that "
                "contradicts the code — #151 skips the page for having no `apis`, the "
                "consumer-wiring audit has nothing to reconcile, and the implemented-flip "
                "stops asking whether its endpoints are referenced. Register the endpoints "
                "each page actually calls."
                % (len(drift), join_capped(drift, total=len(drift), cap=6))]
    except Exception as exc:
        _gate_absent_792("_page_api_declaration_drift_1202rr", exc, "run")
        return []


def _component_key_1202vf(name) -> str:
    """One spelling for a ui_component, whichever of its three names you arrived by.

    #1202vf. A component carries a hub key (`shell_header`), an id
    (`component:ui:shell_header`) and a code name (`ShellHeader`), and pages reference the
    code name. Validated against a real run's hubs: indexing all three resolves 50 of the
    51 component references its pages make.

    #1202vl: the camel->snake rule is `RegistryHub._ui_snake`, which is the function that
    MINTS these keys. The first draft rolled its own `(?<!^)(?=[A-Z])` -- the exact rule
    #1079 documents as wrong, because it splits before EVERY capital and turns an acronym
    like `APIKeyPanel` into `a_p_i_key_panel` instead of `api_key_panel`. Measured over the
    corpus's 5904 page->component references it differs on 203, and the effective-API
    totals come out IDENTICAL (4160 both ways) -- because that draft applied its own rule
    to BOTH the index and the lookup, so the mangling cancelled. That symmetry is an
    accident of these two call sites, not a property of the rule, and the next caller that
    matches a hub key directly would not have it. Use the minting function.
    """
    try:
        from .registryhub import RegistryHub
        return RegistryHub._ui_snake(str(name or "").strip().split(":")[-1])
    except Exception:
        return str(name or "").strip().split(":")[-1].lower().replace("-", "_")


def effective_page_apis_1202vf(page, components) -> set:
    """The endpoints a page consumes: its OWN `apis_used` plus those of the ui_components
    it declares, followed transitively through each component's `children`.

    #1202vf. This is the shape the frontend prompt MANDATES -- "a component OWNS the API
    calls it makes (apis_used) ... Declare each API on the component where the call
    actually lives, don't pile every API onto the page" -- so a page that composes is
    SUPPOSED to declare none of its own.
    """
    own = set(page.get("apis_used") or []) if isinstance(page, dict) else set()
    index = {}
    for key, rec in (components or {}).items():
        if not isinstance(rec, dict):
            continue
        for spelling in (key, rec.get("id"), rec.get("component")):
            if spelling:
                index.setdefault(_component_key_1202vf(spelling), rec)
    seen, stack = set(), [_component_key_1202vf(c)
                          for c in ((page.get("components") or []) if isinstance(page, dict) else [])]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        rec = index.get(cur)
        if not rec:
            continue
        own |= set(rec.get("apis_used") or [])
        stack.extend(_component_key_1202vf(c) for c in (rec.get("children") or []))
    return own


def _no_page_declares_an_api_1202rm(hub_registry) -> List[str]:
    """Registered pages when the backend has a contract and none of them declares an API.

    Static; `[]` on any failure. `ENVGEN_PAGE_API_DECLARATION_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_PAGE_API_DECLARATION_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        rh = getattr(hub_registry, "registryhub", None)
        if rh is None or not hasattr(rh, "list_ui_pages"):
            return []
        pages = rh.list_ui_pages() or {}
        pages = {k: v for k, v in pages.items()
                 if k != "_meta" and isinstance(v, dict)}
        if not pages:
            return []
        declared = [k for k, v in pages.items() if (v.get("apis_used") or [])]
        if declared:
            return []                     # at least one page names an endpoint
        # #1202vf: A PAGE THAT COMPOSES IS SUPPOSED TO DECLARE NOTHING OF ITS OWN.
        #
        # The frontend prompt's UI MODEL is explicit: "a component OWNS the API calls it
        # makes (apis_used) ... Declare each API on the component where the call actually
        # lives -- don't pile every API onto the page." This check read ui_pages only, so a
        # lane that followed that instruction EXACTLY was told, in the same run, to do the
        # thing the instruction forbids: "Declare, on each page, the endpoints it actually
        # calls." tiktok-r133 is that run -- 17 pages each declaring `apis_used: []` while
        # listing their components, 3 of which carry the APIs (`feed_data_provider` ->
        # `GET /api/feed`, `comments_panel`, `login_modal`) -- and it sat in 211 of its 268
        # gate snapshots. r123 (20 of 23 pages) and r109 (11 of 11) have the same shape and
        # predate this check. A lane cannot satisfy two contradictory framework
        # instructions, so this one yields: it is the one that is wrong about the model.
        _comps = {}
        try:
            if hasattr(rh, "list_ui_components"):
                _comps = {k: v for k, v in (rh.list_ui_components() or {}).items()
                          if k != "_meta" and isinstance(v, dict)}
        except Exception as _exc_1202vf:
            # #883: an empty default here is FAIL-CLOSED -- with no components read, no page
            # has effective APIs and the original blocker below still fires -- but a reader
            # must be able to tell "this lane declared nowhere" from "the component walk
            # could not run", because only the first is lane work.
            _gate_absent_792("_no_page_declares_an_api_1202rm/list_ui_components",
                             _exc_1202vf, "blocking as if no component declared one")
            _comps = {}
        _via_components = sorted(k for k, v in pages.items()
                                 if effective_page_apis_1202vf(v, _comps))
        if _via_components:
            # Never silently: the page-level readers (#151's decoy-twin check, the
            # consumer-wiring audit and `audit_ui_page`'s API criterion) still read
            # `page["apis_used"]` alone and do NOT walk the component tree, so for these
            # pages that criterion is still vacuous -- r133 flipped all 17 to `implemented`
            # without it. That is a FRAMEWORK gap in those readers, not lane work, and
            # blocking delivery over it dispatches a lane that cannot fix it (#1202tm).
            _LOG_700.warning(
                "#1202vf %d of %d registered ui_page(s) declare `apis_used: []` but DO "
                "consume endpoints through the ui_components they declare (%s) -- the "
                "frontend prompt requires exactly that, so this is not a lane defect and "
                "delivery is not blocked on it. #1202zy: the follow-up this used to name is "
                "DONE -- #1202vg folded the effective set into `audit_ui_page`'s reachability "
                "probe (measured over 155 runs: 605 pages gained a criterion that was vacuous "
                "and exactly 2 flipped, against 20 wrong flips if it were fed in wholesale). "
                "The two readers that still take `page['apis_used']` raw are raw ON PURPOSE: "
                "#918's closure probe is report-only and out of `ok`, and #728 asks whether "
                "the page's OWN declaration crosses another route, which a shared component's "
                "endpoints would make true of every page.",
                len(_via_components), len(pages),
                join_capped(_via_components, total=len(_via_components), cap=6))
            return []
        # Only a contradiction when there IS a contract to consume.
        # #1202rm: the method is get_endpoints, not list_endpoints. The first draft guessed,
        # the AttributeError landed in the outer except, and the gate returned [] on every
        # run -- passing r130 and r131, the two it was written for. Verified against the real
        # object, not from memory.
        _get = getattr(rh, "get_endpoints", None) or getattr(rh, "list_endpoints", None)
        if _get is None:
            return []
        eps = _get() or {}
        # `kind` alone is not enough: a registration that omits it leaves an empty string,
        # and the fixed surface (/health, /auth/*, /oauth/*, the tenant control plane) is then
        # counted as business. A regression test registering only /health and /auth/register
        # caught this -- two control-plane routes read as "a contract with 2 business
        # endpoints". The PATH is the reliable signal, so both are applied.
        _fixed = ("/health", "/auth/", "/oauth/", "/.well-known/", "/api/v1/tenants",
                  "/api/v1/reset", "/api/v1/admin/")
        business = []
        for _k, _e in ((eps.items() if isinstance(eps, dict) else
                        ((str(x.get("path") or ""), x) for x in eps if isinstance(x, dict)))):
            if not isinstance(_e, dict):
                continue
            # #1203fy: the same wrong key as the IMPLEMENTATION PROGRESS nudge, and a third
            # hand-written copy of the kind list. `kind` at the top level occurs 0 times in
            # 5747 corpus endpoints -- the tag lives in `metadata.kind` -- so this clause has
            # never excluded anything either, and the comment above is why nothing broke: the
            # `_fixed` PATH net catches the surface this was meant to catch. Replayed over
            # every run directory, the `len(business) < 2` verdict flips in 0 runs, so this is
            # a correctness alignment with no behaviour change today; it is made anyway because
            # the next reader of `kind` should find one convention, not two.
            if _endpoint_kind_1203fy(_e) in _FIXED_ENDPOINT_KINDS_1203FY:
                continue
            _path = str(_e.get("path") or _k or "")
            if any(_f in _path for _f in _fixed):
                continue
            business.append(_e)
        if len(business) < 2:
            return []
        return ["all %d registered ui_page(s) declare `apis_used: []` while the contract "
                "carries %d business endpoint(s). An app whose every page needs no data is "
                "not a thing this contract describes, and the emptiness is not inert: "
                "`apis_used` is what #151's decoy-twin check, the consumer-wiring audit and "
                "the page implemented-flip all read, so an all-empty registration turns those "
                "checks OFF rather than failing them. Declare, on each page, the endpoints it "
                "actually calls." % (len(pages), len(business))]
    except Exception as exc:
        _gate_absent_792("_no_page_declares_an_api_1202rm", exc, "run")
        return []


# #1202rq: ROUTES NOBODY CAN REACH.
#
# `deliverability_ui_page_unwired` asks whether a declared page got a route. Nothing asked the
# other half: whether anything in the app can NAVIGATE to that route. tiktok-r131 wired 12
# routes and shipped ZERO navigation affordances -- no <a>, no <Link>, no navigate() anywhere
# in src. Every page existed and only the address bar could reach it. An unprimed agent hit
# exactly this: "nothing in the app is a real link -- creator names and avatars are not
# clickable, which is why there's no path to a profile."
#
# It is not the normal state and the corpus says so: r129 has 16 navigation sites, r130 has 46,
# r131 has 0. A threshold would be arbitrary; zero-against-many is not.
def _unreachable_routes_1202rq(app_root) -> List[str]:
    """Routed pages with no navigation affordance anywhere in the frontend. `[]` on failure.

    Deliberately the ZERO case only. A page reachable solely from one other page is a design
    choice; an app where nothing is clickable is a build that was never wired together.
    `ENVGEN_ROUTE_REACHABILITY_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_ROUTE_REACHABILITY_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        import re as _re
        src = Path(app_root) / "frontend" / "src"
        app_jsx = src / "App.jsx"
        if not src.is_dir() or not app_jsx.is_file():
            return []
        routes = _re.findall(r"""<Route\s[^>]*\bpath\s*=\s*['"]([^'"]+)['"]""",
                             app_jsx.read_text(encoding="utf-8", errors="ignore"))
        routes = [r for r in routes if r not in ("*", "/")]
        if len(routes) < 3:
            return []                     # too small to conclude anything
        nav = 0
        for f in src.rglob("*.jsx"):
            if "node_modules" in f.parts:
                continue
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            nav += len(_re.findall(r"<a\s|<Link\s|useNavigate\s*\(|\bnavigate\s*\(", t))
        if nav:
            return []
        return ["App.jsx routes %d page(s) and the frontend contains NO navigation affordance "
                "at all — no <a>, no <Link>, no navigate() anywhere under src. Every page "
                "exists and only the address bar can reach it, so a user (or an agent) "
                "browsing the app can never leave the landing route. The corpus shows this is "
                "not the normal shape: sibling runs carry 16 and 46 such sites. Wire the nav "
                "rail, and make the names and avatars that stand for a record link to it."
                % len(routes)]
    except Exception as exc:
        _gate_absent_792("_unreachable_routes_1202rq", exc, "run")
        return []


# #1202sb: A THIRD PARTY'S EMAIL ADDRESS, PUBLISHED BY A HAND-WRITTEN ROUTE.
#
# tiktok-r126, live and unauthenticated: `GET /api/explore` embeds `author.email` --
# `bts_official_bighit@example.com` -- in every item. An unprimed judge browsing the app
# reported it without being asked to look for anything of the kind.
#
# The framework already forbids exactly this. `#1202jb`'s `_PRIVATE_ACTOR_COLS_1202JB` is the
# denylist of columns an actor row must not show to anyone who is not that actor, and every
# PROJECTED read path applies it. `custom_routes.py` is hand-written, so it applies to nothing:
# r126 selects `u."email" AS author_email` in a join and puts it straight in the response.
# One fact, many emitters -- so this reads the same list rather than carrying a copy.
#
# Narrow twice. The alias must name a THIRD PARTY (`author_`, `host_`, `creator_`), never the
# caller (`my_`, `own_`, `self_`), because /auth/me returning your own address is correct. And
# the statement must JOIN, because a row fetched by the caller's own id is the caller's row.
# 3 of the 170 corpus backends hit it -- r123, r126 and r129, the last of which delivered two
# milestones with this in it.
_SELF_PREFIXES_1202SB = frozenset((
    "my", "own", "self", "me", "current", "your", "caller", "viewer", "requester"))


def _third_party_private_columns_1202sb(app_root) -> List[str]:
    """Hand-written backend routes that publish another actor's private column. `[]` on failure.

    `ENVGEN_PRIVATE_COLUMN_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_PRIVATE_COLUMN_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        import re as _re
        from .route_projector import _PRIVATE_ACTOR_COLS_1202JB as _private
        backend = Path(app_root) / "backend"
        if not backend.is_dir():
            return []
        cols = "|".join(sorted(_re.escape(c) for c in _private))
        pat = _re.compile(r"\b(?:%s)\b\s*[\"']?\s*\)?\s+AS\s+[\"']?(\w+)_(%s)\b"
                          % (cols, cols), _re.I)
        hits: List[str] = []
        for f in sorted(backend.rglob("*.py")):
            # models.py declares the columns; seed_data.py loads them; schemas.py is shape.
            # The leak is a READ PATH choosing to emit one.
            if f.name in ("models.py", "seed_data.py", "schemas.py"):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in pat.finditer(text):
                if m.group(1).lower() in _SELF_PREFIXES_1202SB:
                    continue
                if not _re.search(r"\bJOIN\b", text[max(0, m.start() - 900):m.end() + 200],
                                  _re.I):
                    continue  # the caller's own row, fetched by their own id
                hits.append("%s: %s" % (f.name, m.group(0).strip()))
        if not hits:
            return []
        return ["%d hand-written read path(s) publish another actor's private column: %s. "
                "The projected read paths cannot do this -- #1202jb's denylist stops them -- "
                "but custom_routes.py is outside that rule, so r126 served every visitor "
                "`author.email` on a public GET /api/explore. Drop the column from the SELECT "
                "and from the response; a product does not publish its users' addresses, and "
                "an agent reading the API learns an address no screen ever shows."
                % (len(hits), join_capped(hits))]
    except Exception as exc:
        _gate_absent_792("_third_party_private_columns_1202sb", exc, "run")
        return []


def _routes_that_ignore_their_parameter_1202rz(app_root) -> List[str]:
    """A frontend that routes `/video/:id` but never reads a route parameter. `[]` on failure.

    tiktok-r126, observed by an unprimed judge that was only asked to find the most-commented
    video: `/video/21`, `/video/24` and `/video/32` all rendered video 1. The page never called
    a per-video endpoint -- it called `GET /api/feed?limit=12` and rendered `items[0]`. Every
    item beyond the first was unreachable through the UI, and the judge had to fall back to the
    API to finish an ordinary browsing task.

    ZERO case only, the same discipline as `#1202rq`: one page that happens to ignore its
    parameter can be a deliberate redirect, and proving it per-page needs the component
    resolution that made my first detector fire on code fragments. But a frontend that declares
    parameterised routes and contains NO `useParams` / `match.params` / `router.query` anywhere
    has no way to read one, so every such route is decorative by construction.

    6 of the 137 corpus frontends that declare a parameterised route are in this state --
    r115, r128, r131, r46, r54, r85. `ENVGEN_ROUTE_PARAM_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_ROUTE_PARAM_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        import re as _re
        src = Path(app_root) / "frontend" / "src"
        if not src.is_dir():
            return []
        routes: List[str] = []
        body = []
        for f in src.rglob("*"):
            if f.suffix not in (".jsx", ".js", ".tsx", ".ts") or "node_modules" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            body.append(text)
            routes += [r for r in _re.findall(
                r"""<Route\b[^>]*\bpath\s*=\s*["'{`]([^"'`}]+)""", text) if ":" in r]
        # One list, one count (#1034). The first draft counted `routes` -- which holds one
        # entry per FILE the route appears in -- while printing the deduped set, and
        # join_capped's second positional is `total`, not a cap: the message said
        # "1 parameterised page(s) (/video/:video_id/comments (+3 more not shown))".
        routes = sorted(set(routes))
        if not routes or not body:
            return []
        joined = "\n".join(body)
        if _re.search(r"\buseParams\b|\bmatch\.params\b|\buseRouteMatch\b"
                      r"|router\.query|\bprops\.params\b|\bparams\.\w+", joined):
            return []
        return ["the frontend routes %d parameterised page(s) (%s) and NEVER reads a route "
                "parameter — no useParams, no match.params, no router.query anywhere under "
                "src. Each of those pages therefore renders the same thing whatever id is in "
                "the address, which is what r126 shipped: /video/21, /video/24 and /video/32 "
                "all showed video 1, because the page called GET /api/feed and rendered "
                "items[0]. Every record past the first is unreachable through the UI. Read the "
                "parameter and fetch THAT record."
                % (len(routes), join_capped(routes))]
    except Exception as exc:
        _gate_absent_792("_routes_that_ignore_their_parameter_1202rz", exc, "run")
        return []


# #1202rs: THE RESERVED DOCUMENTATION DOMAIN, SEEDED AS REAL PEOPLE'S ADDRESSES.
#
# `example.com` is RFC 2606's reserved documentation domain. No product's user has an address
# there, so a seeded `alice@example.com` tells any agent reading the database that the people
# are invented. It is the single most recurrent realism tell in this corpus and nothing has
# ever checked it: 8 of 8 SUCCESSFUL instagram deliveries carry it, 41 addresses in all, and
# no other deterministic tell (picsum, John Doe, lorem, +1-555) appears in any of them.
#
# It also reproduces on demand: in a controlled A/B this session, the arm WITHOUT the realism
# contract seeded 8 `@example.com` addresses and the arm with it seeded none. The contract
# works on this and a prompt rule is not enforcement, which is what this gate is for.
#
# Narrow: the RFC-reserved names plus the two hosts that mean "not a real place". A product's
# own invented domain is NOT flagged -- `@acme-video.com` is what a clone's users should have.
_RESERVED_EMAIL_DOMAINS_1202RS = (
    "@example.com", "@example.org", "@example.net", "@example.edu",
    "@test.com", "@test.example", "@invalid", "@localhost",
)


def _reserved_email_domain_blockers_1202rs(app_root) -> List[str]:
    """Seeded addresses on a reserved documentation domain. `[]` on any failure.

    Scans what SHIPS -- the seed the app loads and the frontend source -- not tests or docs.
    `ENVGEN_RESERVED_EMAIL_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_RESERVED_EMAIL_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        import re as _re
        app = Path(app_root)
        pat = _re.compile("|".join(_re.escape(d) for d in _RESERVED_EMAIL_DOMAINS_1202RS),
                          _re.I)
        hits: List[str] = []
        for root in (app / "backend", app / "frontend" / "src"):
            if not root.is_dir():
                continue
            for f in root.rglob("*"):
                if (not f.is_file() or "node_modules" in f.parts
                        or f.suffix.lower() not in (".json", ".py", ".js", ".jsx",
                                                    ".ts", ".tsx")):
                    continue
                try:
                    n = len(pat.findall(f.read_text(encoding="utf-8", errors="ignore")))
                except Exception:
                    continue
                if n:
                    hits.append("%s (%d)" % (f.relative_to(app).as_posix(), n))
        if not hits:
            return []
        return ["%d served file(s) carry addresses on a RESERVED documentation domain: %s. "
                "`example.com` and its siblings are reserved by RFC 2606 precisely so that "
                "nothing real uses them, so a seeded `alice@example.com` tells any agent "
                "reading this database that its people are invented — and it is the most "
                "recurrent tell in this corpus, present in 8 of 8 successful deliveries. Give "
                "the seeded people addresses on THIS product's own domain."
                % (len(hits), join_capped(hits, total=len(hits), cap=6))]
    except Exception as exc:
        _gate_absent_792("_reserved_email_domain_blockers_1202rs", exc, "run")
        return []


def _operator_identity_1202rj() -> List[str]:
    """Identity tokens belonging to whoever is running the build. Never raises; [] when unknown.

    Sources are the build environment itself: the OS user, and git's configured identity. The
    email's LOCAL-PART matters as much as the whole address -- r127's leak was the bare handle
    `haibotong7`, never the address.
    """
    import subprocess
    out: List[str] = []
    try:
        for val in (os.environ.get("USER"), os.environ.get("LOGNAME")):
            if val and len(str(val)) >= 4:
                out.append(str(val).strip())
    except Exception:
        pass
    for arg in ("user.email", "user.name"):
        try:
            r = subprocess.run(["git", "config", "--get", arg], capture_output=True,
                               text=True, timeout=5)
            v = (r.stdout or "").strip()
            if not v:
                continue
            if "@" in v:
                local = v.split("@", 1)[0].strip()
                if len(local) >= 4:
                    out.append(local)
            elif len(v) >= 4 and " " not in v:
                out.append(v)
        except Exception:
            continue
    # de-duplicate, longest first so a compound handle is reported over its own prefix
    return sorted({t for t in out if t}, key=len, reverse=True)


def _identity_outside_comments_1202rk(suffix: str, text: str, token: str):
    """True when `token` reaches a browser, False when it is comment-only, None when the
    check itself failed.

    Crude on purpose: strip `//`, `/* */` and `#` comments, then look again. A string
    containing `//` (a URL) survives as code, which is the safe direction -- this may call a
    comment live, never the reverse.

    #1202be: the first draft returned True on exception, "the conservative direction". It was
    conservative for the VERDICT and wrong for the READER: a crashed check then read as "this
    file renders the operator's handle", and the lane goes looking for a render that may not
    exist. #1202ah then caught the replacement for the opposite sin -- a silent empty return.
    Both ratchets point at the same exit: SAY SO. The caller labels the None apart AND the
    failure is announced, so neither the reader nor the log is left guessing.
    """
    try:
        import re as _re
        body = text
        if suffix in (".js", ".jsx", ".ts", ".tsx", ".css"):
            body = _re.sub(r"/\*.*?\*/", " ", body, flags=_re.S)
            body = _re.sub(r"(?m)^\s*//.*$", " ", body)
        elif suffix == ".py":
            body = _re.sub(r"(?m)^\s*#.*$", " ", body)
        return token in body
    except Exception as exc:
        from .message_format import warn_once_1201
        warn_once_1201(
            "identity_outside_comments_1202rk",
            "cannot tell a comment from code while reporting a build-identity hit, so the "
            "gate says the file CARRIES the token without saying whether a visitor sees it",
            exc)
        return None


def _operator_identity_blockers_1202rj(app_root) -> List[str]:
    """Served files that carry the operator's own identity. Static; `[]` on any failure.

    Scans what SHIPS -- the frontend source and the seed the app loads -- not the build
    metadata under design/, which never reaches a browser (r30 and r16 carry the build PATH
    there and that is not a leak, which is why this walks app/ alone).
    `ENVGEN_OPERATOR_IDENTITY_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_OPERATOR_IDENTITY_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        tokens = _operator_identity_1202rj()
        if not tokens:
            return []
        app = Path(app_root)
        hits: List[str] = []
        roots = [app / "frontend" / "src", app / "backend"]
        for root in roots:
            if not root.is_dir():
                continue
            for f in root.rglob("*"):
                if not f.is_file() or "node_modules" in f.parts:
                    continue
                if f.suffix.lower() not in (".js", ".jsx", ".ts", ".tsx", ".json", ".py",
                                            ".html", ".css"):
                    continue
                try:
                    txt = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for tok in tokens:
                    if tok not in txt:
                        continue
                    # #1202rk: a comment is not a render, and saying it is sends the lane
                    # looking for something no visitor can see. It is still reported -- a
                    # build identity in a comment is a dev trace (and usually the fossil of a
                    # literal that WAS rendered until someone bound it) -- but under its own
                    # description, so the reader knows which thing they are looking at.
                    _live = _identity_outside_comments_1202rk(f.suffix.lower(), txt, tok)
                    _label = ("carries (could not tell comment from code)" if _live is None
                              else "RENDERS" if _live else "mentions (comment only)")
                    hits.append("%s %s %r" % (
                        f.relative_to(app).as_posix(), _label, tok))
                    break
        if not hits:
            return []
        _live_n = sum(1 for h in hits if " RENDERS " in h)
        return ["%d served file(s) carry the identity of the account that BUILT this env"
                "%s: %s. The reference "
                "screenshot was captured from that account and its handle was transcribed as "
                "component copy (#1202ri splits chrome from data slots upstream). Bind the "
                "value to the API and seed a person from THIS product's world instead."
                % (len(hits),
                   (", and %d of them RENDER it to visitors" % _live_n) if _live_n
                   else " (in comments only -- a dev trace, and usually the fossil of a "
                        "literal that was rendered until someone bound it)",
                   join_capped(hits, total=len(hits), cap=5, sep="; "))]
    except Exception as exc:
        _gate_absent_792("_operator_identity_blockers_1202rj", exc, "run")
        return []


# #1203fy: the kind lives under `metadata` (0 of 5747 corpus endpoints carry a top-level
# `kind`), and the fixed surface has ONE canonical list. `lifecycle` carries both and states
# the rule: "Six modules re-listed this surface and all six omitted the same three. Imported,
# not re-listed." Imported lazily with an explicit empty-set fallback rather than a silent one,
# so a broken import degrades to "no kind exemption" -- the pre-#1203fy behaviour -- and says so.
_FIXED_ENDPOINT_KINDS_1203FY: frozenset = frozenset()
try:
    from .kickoff.contract import FIXED_ENDPOINT_KINDS as _FIXED_ENDPOINT_KINDS_1203FY
except Exception as _exc_1203fy_kinds:  # pragma: no cover - import-safety guard
    _gate_absent_792("_FIXED_ENDPOINT_KINDS_1203FY", _exc_1203fy_kinds, "run")


def _endpoint_kind_1203fy(rec: Any) -> str:
    """The endpoint's kind wherever it landed. Delegates to `lifecycle.endpoint_kind`."""
    try:
        from .lifecycle import endpoint_kind as _ek
        return _ek(rec)
    except Exception:
        if not isinstance(rec, dict):
            return ""
        md = rec.get("metadata")
        return str((md or {}).get("kind") if isinstance(md, dict) else ""
                   or rec.get("kind") or "").strip().lower()


def _parked_probe_routes_1202y7(app_root) -> List[str]:
    """Routes the app SERVES with a path segment starting `__`. `[]` on failure.

    r140 delivered `GET /__noop_orchestrator_probe__`, and the lane's own docstring says why
    it exists: "DB-backed readiness probe used by delivery validation ... so code-truth can
    distinguish it from a static placeholder". Asked to prove its endpoints were not static
    placeholders, the lane's answer was a PUBLIC, UNAUTHENTICATED route running
    `SELECT COUNT(*)` over four business tables -- and then shipped it. r80's `/__list__`
    says the same thing one step more plainly: "re-implemented here so provider flips to
    'backend' and the business-endpoint audit sees a real handler."

    The framework already knows lanes park these. `seed_audit` carries the note (#1202du,
    corrected by #1202dw: "an AGENT parks them, the framework does not emit them") and
    answers it with `if str(name).startswith("__"): continue` -- an EXEMPTION, so its own
    audit stops tripping over them. Exempting a thing from a check is not the same as
    keeping it out of the product, and the exemption was written for the smaller surface:
    7 of 179 runs park a `__` TABLE, 36 park a `__` ROUTE.

    Measured over the 179 generated backends with the same reader this calls
    (`served_routes`, so the verdict and the evidence cannot disagree -- #1032): 36 runs,
    20%, 25 distinct paths, and rising with the corpus -- 0 of 83 in July, 10 of 31 in
    August, 25 of 65 in September, r140 included. EVERY path found begins `/__`, and no
    `__`-prefixed route in the corpus is one the app needed: the widest name is `/__list__`,
    which re-implements a framework audit endpoint. So the predicate is the framework's own
    convention read back, not a new rule invented here.

    Every path found begins `/__`, but the test below is ANY segment: measured, the two
    rules catch the same 36 runs, so the wider one costs nothing today and does not quietly
    depend on the parking staying at the root.

    ZERO framework-emitted routes use the prefix, which is what makes this safe to block on:
    the projector names business paths, and `seed_audit`'s note states the framework does not
    emit these. `ENVGEN_PARKED_ROUTE_GATE=0` disables.
    """
    if str(os.environ.get("ENVGEN_PARKED_ROUTE_GATE", "1")).strip().lower() in (
            "0", "false", "off", "no"):
        return []
    try:
        from .backend_audit import served_routes
        backend = Path(app_root) / "backend"
        if not backend.is_dir():
            return []
        hits: List[str] = []
        for method, path in sorted(served_routes(backend)):
            # ANY segment, not just the first. Measured, the two rules are the same
            # today -- 36 runs either way, and no corpus path carries `__` anywhere but
            # at the front -- so this costs nothing and does not depend on the parking
            # staying at the root. `/api/__noop__` is the same artefact one prefix in.
            if any(p.startswith("__") for p in str(path).split("/") if p):
                hits.append("%s %s" % (method, path))
        if not hits:
            return []
        # #1202vx: the evidence gets the budget, the explanation is appended after it --
        # prepending the sentence would let the prose eat the cap and leave the lane with
        # fewer routes named than the count claims.
        return ["%d served route(s) exist only to satisfy a framework check and would ship "
                "with the product: %s. A path beginning `__` is this framework's own "
                "convention for its machinery, so a visitor reading the app's OpenAPI sees "
                "the builder's scaffolding; the r140 instance was public, unauthenticated "
                "and counted rows in four business tables. "
                # #1203fz: NAME THE ACTION THAT ACTUALLY CLEARS THIS. The line used to read
                # "Delete the handler AND its registry entry", and half of that is impossible:
                # the lane's tool surface has `registryhub_register_endpoint` and
                # `registryhub_deprecate_endpoint` and NO delete/unregister tool for an
                # endpoint. r164's backend notebook says it three times -- "No direct
                # unregister tool is available", "RegistryHub retains deprecated historical
                # `__` endpoint entries because no delete tool is available" -- and once it
                # believed the instruction over the gate: "the blocking state was registry
                # contract presence; changed RegistryHub endpoint status to removed". It is
                # not: this detector reads `served_routes(backend)`, which is CODE.
                #
                # Measured over every run directory: 14 probes across 8 runs (r121, r125, r123,
                # r164, r114, r120, netflix-r6, netflix-r24) sit retired in the registry with
                # the handler still in the source -- the half-repair this sentence invites,
                # each one still blocking. 57 across 48 runs did it the other way and cleared.
                "DELETING THE HANDLER is what clears this check -- it reads the routes your "
                "backend SERVES, not the registry. There is no tool that deletes an endpoint "
                "registration, and `registryhub_deprecate_endpoint` does NOT clear this: a "
                "deprecated entry whose handler is still in the source still ships the route. "
                "Leaving the registration behind is fine. If a framework task pushed you to "
                "add it, that was #1203fy (fixed): the check wanting data is asking about the "
                "BUSINESS endpoints -- make one of those read its data instead."
                % (len(hits), join_capped(hits, total=len(hits), cap=5, sep="; "))]
    except Exception as exc:
        _gate_absent_792("_parked_probe_routes_1202y7", exc, "run")
        return []


def _placeholder_route_blockers_1202w(app_root) -> List[str]:
    """Routed pages whose NAME says they are placeholders. Static; `[]` on any failure.

    `re` is imported here on purpose: this module has no module-level `re`, and a pattern
    compiled at import time would have made the whole gate module fail to import — which
    compiles clean and dies at runtime, the shape this session keeps finding.
    """
    try:
        import re as _re1202w
        app = Path(app_root) / "frontend" / "src" / "App.jsx"
        if not app.is_file():
            return []
        src = app.read_text(encoding="utf-8")
        routed = sorted({m.group(1)
                         for m in _re1202w.finditer(r"element=\{\s*<(\w+)", src)})
        bad = [c for c in routed
               if _re1202w.search(_JUNK_PAGE_WORDS_1202W, c, _re1202w.I)]
        if not bad:
            return []
        return ["App.jsx routes %d placeholder page(s) — %s. A route a user can reach must "
                "render the real thing; four runs of the corpus shipped one of these live. "
                "Either build the page or remove its route and its ui_page registration."
                % (len(bad), ", ".join(bad))]
    except Exception as exc:
        _gate_absent_792("_placeholder_route_blockers_1202w", exc, "run")
        return []


def _invented_field_blockers(app_root) -> List[str]:
    """#175 (gmrun9): frontend member-field fallbacks to FABRICATED display literals
    (``place.rating || '4.5'`` / ``? place.name : 'HI Point Montara Lighthouse'``) render
    invented data whenever the field is absent (often ALWAYS — gmrun9's `place.reviews`
    drifted from the model's `review_count`). The user's no-placeholder/mock bar; #170's
    prompt rule was ignored so this ENFORCES it. Static, best-effort ``[]``.
    ``ENVGEN_INVENTED_FIELD_GATE=0`` disables."""
    try:
        from .frontend_audit import invented_field_fallback_blockers
    except Exception as exc:
        _gate_absent_792("_invented_field_blockers", exc, "run")
        return []
    try:
        _fsrc = Path(app_root) / "frontend" / "src"
        # #524 (netflix r94): HEAL-THEN-CHECK at the deliver-tail. The deterministic
        # fabricated-fallback heal (repair_fabricated_fallbacks) previously ran ONLY in the
        # build-time heal pipeline; a lane that authors `x || 'Literal'` fallbacks LATE (into
        # the deliver-tail) then goes DARK (r94: frontend lane unresponsive — the SOUND gate
        # rejected the SAME 5 lines 48x → infinite deliver_project loop, never delivered)
        # never got healed → permanent rejection. The heal shares the checker's classifier
        # and is a provable SUPERSET, so running it HERE first makes `heal → check = 0 flagged
        # BY CONSTRUCTION` at the GATE, not just at build — independent of the (possibly dark)
        # lane. Rewrites `x || 'Literal'` → `(x ?? '—')` (honest empty), so the SOUND checker
        # is left completely untouched — we make the CODE compliant, we do not relax the gate.
        # Best-effort; never raises.
        try:
            from .frontend_audit import repair_fabricated_fallbacks
            repair_fabricated_fallbacks(_fsrc)
        except Exception as _rep770:
            # #770: A REPAIR THAT FAILS SILENTLY REPORTS ITS OWN SYMPTOM. The very next line is
            # the blocker check this repair exists to clear, so a throw here means the gate
            # blocks and nothing says the framework already tried and could not. The lane is
            # then handed a blocker it cannot reconcile with the code in front of it. #769's
            # class one layer up: the reason was caught and dropped at the `except`.
            _LOG_700.warning(
                "#770 auto-repair repair_fabricated_fallbacks failed (%s: %s) — the blocker check below may now "
                "report the very defect this was meant to clear, so read it as a CONSEQUENCE "
                "before dispatching a lane at it.",
                type(_rep770).__name__, str(_rep770)[:160])
        return invented_field_fallback_blockers(_fsrc)
    except Exception as exc:
        _gate_absent_792("_invented_field_blockers", exc, "run")
        return []


def _seed_summary(hub_registry, project_dir=None) -> Dict[str, Any]:
    try:
        from .seed_audit import audit_seed_data
    except Exception:
        # #1203d3: the audit could not run at all — the loudest unmeasured state there is.
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0,
                "examined": 0, "candidates": 0, "measured": False,
                "registered_source_1203d3": "the seed audit did not run"}
    try:
        # #956: hand the audit a path so it can count ROWS in the running database instead of
        # reading `list_seed_registrations()`, which holds 0 records corpus-wide. Passing None
        # (or an unreachable DB) leaves the old behaviour byte-for-byte.
        report = audit_seed_data(hub_registry, project_dir)
    except Exception:
        # #1203d3: the audit could not run at all — the loudest unmeasured state there is.
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0,
                "examined": 0, "candidates": 0, "measured": False,
                "registered_source_1203d3": "the seed audit did not run"}
    schema_hub = getattr(hub_registry, "schema_hub", None)
    total_tables = len((schema_hub.list_tables() if schema_hub else {}) or {})
    registered = len((schema_hub.list_seed_registrations() if schema_hub else {}) or {})
    missing = sum(1 for f in report.flagged_tables if f.get("reason") == "missing_seed")
    flagged = len(report.flagged_tables)
    # #1168: carry the referential finding out with the density one. Reported, never a
    # blocker — the seed audit's verdict is deliberately unchanged (#956/#1023d), and a
    # false seed blocker wedges a run (#566j). It rides here because this dict is what the
    # gate report prints, so a seed whose rows point at nothing stops being invisible.
    _orph = getattr(report, "orphan_fk_rows", None) or {}
    out = {"tables": total_tables, "registered": registered,
           "missing": missing, "flagged": flagged,
           # #1203d3: SAY WHETHER ANYTHING WAS LOOKED AT. `flagged`/`missing` are counts over
           # `report.flagged_tables`, and an audit that inspected nothing produces an empty one
           # — identical on the wire to an audit that inspected everything and found nothing.
           # #1023d put `measured`/`examined`/`candidates` on the report for this, #1203c1
           # carried them into `list_seed_issues`, and this — the dict the GATE REPORT prints —
           # was the third reader still dropping them (#1202lf).
           #
           # `registered` is left alone on purpose: it reads `list_seed_registrations()`, which
           # #956 calls "0 records corpus-wide" (measured: 0 in 2312 of 2312 gate records across
           # 52 runs), and #1023d states the real repair counts rows at gate time and stays
           # open. Naming the source is honest; swapping in `examined` (0 in 145 of 147 runs)
           # would just move the zero.
           "examined": getattr(report, "examined", 0),
           "candidates": getattr(report, "candidates", 0),
           "measured": bool(getattr(report, "measured", False)),
           "registered_source_1203d3": "list_seed_registrations() — this project never writes "
                                       "it (#956); a 0 here says nothing about the database",
           # #1202ow: which tables, and why — the task body could only say "N table(s)".
           "flagged_tables": [{"table": f.get("table"), "reason": f.get("reason")}
                              for f in (report.flagged_tables or [])][:20]}
    if _orph:
        out["orphan_fk_rows"] = dict(_orph)
        out["orphan_fk_total"] = int(sum(_orph.values()))
    return out


_DEGRADED_FLOW_COVERAGE = {
    "required": [], "passed": [], "failed": [], "missing": [],
    "source": "degraded", "is_clean": True, "degraded": True,
}


def _root_spec_entities_1202gl(hub_registry) -> list:
    """#1202gl -- the reference spec's entities, for the note above. Best-effort: an empty
    list simply drops the extra sentence, never blocks."""
    # The real HubRegistry exposes `base_dir` and nothing else path-like — the first cut of
    # this guessed output_dir/root/base_root/project_dir, found none of them, and returned []
    # on every production call: the sentence below never once fired. Third time this batch
    # (#1202gd's unimported names, #1202fw's self.logger), so this one is anchored on the
    # attribute the class actually defines and walks UP to the project root, because
    # `base_dir` points at `<project>/shared` where the hubs live.
    try:
        _b = getattr(hub_registry, "base_dir", None)
        _cands = []
        if _b:
            _bp = Path(str(_b))
            _cands = [_bp, _bp.parent, _bp.parent.parent]
        for _r in _cands:
            _p = Path(_r) / "design" / "reference_spec.json"
            if _p.is_file():
                return json.loads(_p.read_text(encoding="utf-8")).get("entities") or []
    except Exception as _e1202gl:
        # #883/#1201: an empty list here silently drops the one sentence that stops the
        # lane trading the 401 for an unscoped-read blocker and back again. Losing it is
        # not "nothing declared" -- it is the reassurance going missing, so say so.
        from .message_format import warn_once_1201
        warn_once_1201("deliverability.root_spec_entities_1202gl",
                       "the public-collection reassurance (#1202gl) — the contract note will "
                       "tell a lane to declare the read public without saying the "
                       "unscoped-read audit exempts it, which is the revert loop r98 ran",
                       _e1202gl)
        return []
    return []                      # no spec on disk: nothing declared, not a fault


def _auth_wedge_note_1202fr(hub_registry, failed_flows) -> str:
    """#1202fr -- name the CONTRACT reason a failed UI flow 401s.

    `#320` already names this class in backend_skeleton: an explicit ``auth_required:
    false`` is "the lane's deliberate 'this read is public' declaration (r88/r89's
    PUBLIC-FEED WEDGE)". The declaration exists; what is missing is anything that says the
    wedge has happened. In tiktok-r96 the backend lane set ``auth_required: true`` on
    ``GET /api/videos`` — the only feed endpoint — and the framework projected it
    faithfully, so the logged-out landing page could never render:

        ui_flow:fyp_feed_logged_out  "/ loads but GET /api/videos returns 401 while logged out"
        ui_flow:fyp_feed_page        same
        ui_flow:settings_more_menu   "/more calls protected GET /api/users/... while logged out (401)"

    4 of that run's 12 failing flows, rediscovered by browser walk each time, reported as
    "the page did not work" — and the route is FRAMEWORK-PROJECTED, so the lane cannot fix
    it in code; only the contract can change. Nothing pointed at the contract.

    This REPORTS, it never blocks: an app whose entry point is a login screen legitimately
    serves an authenticated feed, and deciding that from a route shape would be a guess.
    The note is attached only to flows that ALREADY failed, so the evidence comes from the
    run, not from a policy about what an app should be.
    """
    try:
        reg = getattr(hub_registry, "registryhub", None)
        wanted = {str(f) for f in (failed_flows or [])}
        if reg is None or not wanted:
            return ""
        pages = reg.list_ui_pages() or {}
        endpoints = reg.get_endpoints() or {}
    except Exception as exc:
        _gate_absent_792("_auth_wedge_note_1202fr", exc, "run")
        return ""

    def _needs_auth(ep) -> bool:
        # #1202hi: the CONTRACT's verdict, not "any copy says True". `metadata` is a mirror
        # taken at registration and never updated, so a lane that declared the read public
        # (`schema.auth_required = False`, the copy #1202ga showed it actually writes) still
        # has `metadata.auth_required = True` -- 220 of the 1518 two-copy endpoints in the
        # corpus. Reading any-says-True reports those pages as auth-wedged AFTER the lane
        # fixed them and after the projector (also #1202hi) started serving them public,
        # which is the "chase a blocker that is already resolved" loop #1202gl describes.
        from .route_projector import _stated_auth_1202hi
        return _stated_auth_1202hi(ep) is True

    authed = set()
    for key, ep in (endpoints.items() if isinstance(endpoints, dict) else []):
        if not _needs_auth(ep):
            continue
        authed.add(str(key))
        if isinstance(ep, dict) and ep.get("method") and ep.get("path"):
            authed.add(f"{ep['method']} {ep['path']}")

    hits = []
    for key, pg in (pages.items() if isinstance(pages, dict) else []):
        if not isinstance(pg, dict):
            continue
        name = str(pg.get("name") or key)
        if name not in wanted:
            continue
        # #1202qk: an identity probe (`GET /auth/me`) answering 401 IS the logged-out answer; the
        # page must treat it as "no user". tiktok-r127's note told the lanes to declare
        # `/auth/me` auth_required=false - advice that would publish a "who am I" endpoint.
        bad = [str(a) for a in (pg.get("apis_used") or [])
               if str(a) in authed and not _identity_probe_1202qk(str(a))]
        if bad:
            hits.append(f"{name} -> {bad[0]}")
    if not hits:
        return ""
    # #1114/#1023: report the CONDITION, do not assert the verdict. A flow that
    # authenticates first never sees the 401, so this is what the contract says an
    # anonymous visitor would get -- evidence for the reader, not a diagnosis.
    # #1202gl: SAY THAT THE OTHER GATE WILL NOT BITE. Told only "declare auth_required
    # false", a lane does it, watches `unscoped owner read: returns every row of X to ANY
    # caller` appear, and reverts -- trading one blocker for another and landing back on the
    # 401 it started from. tiktok-r98 went round that loop: the contract was made public
    # after this note, then set back to auth_required=true.
    #
    # #1202gd's exemption already resolves it, but silently: when the materials declare the
    # collection public, the unscoped-read audit exempts a public read of it. The lane has
    # no way to know that from the blocker alone, so the note has to say it.
    # No inner guard: `_root_spec_entities_1202gl` already fails soft AND audibly, and a
    # second silent except here would only hide a real fault behind a missing sentence
    # (#883's shape, which its ratchet caught on the first draft of this).
    _pub1202gl = ""
    _spec = _root_spec_entities_1202gl(hub_registry)
    _named = {t.split("->")[0].strip() for t in hits}
    _tables = sorted({str(e.get("name") or "") for e in _spec
                      if isinstance(e, Mapping)
                      and str(e.get("visibility") or "").strip().lower() == "public"})
    if _tables:
        _pub1202gl = (
            " The materials already declare "
            + join_capped(_tables, len(_tables), cap=4, sep=", ")
            + " as PUBLIC content, so making the contract match does NOT trade this for "
              "an unscoped-owner-read blocker — that audit exempts a public read the "
              "materials and the contract agree on (#1202gd), PROVIDED the table is not "
              "marked `owner_scoped_reads` (#1202hm moved the corroborating signal there "
              "from `auth_required`, so setting that flag is what would re-block it).")
    # #1202zr: A WRITE IS NOT A READ THAT IS MEANT TO BE PUBLIC.
    #
    # #1202qk already carved one hole in this advice for the same reason -- "tiktok-r127's note
    # told the lanes to declare `/auth/me` auth_required=false: advice that would publish a
    # 'who am I' endpoint". The method is the other hole. r136 and r138 were told, verbatim,
    # that `fyp_feed_logged_out -> POST /api/videos/{video_id}/like` should be fixed by
    # declaring `auth_required=false` "for a read that is meant to be public", and a lane that
    # does that lets any anonymous visitor like and comment.
    #
    # MEASURED over every Contract note in the corpus: 390 named endpoints, 86 of them writes
    # (78 POST, 8 DELETE) across 6 runs including r136 and r138. By distinct note: 35 of 45 are
    # read-only and keep their sentence byte for byte, 9 are write-only, 1 is mixed.
    #
    # The materials sentence is withheld from a write too -- "the materials declare videos as
    # PUBLIC content" is about who may READ those rows, and appending it to a write would
    # argue for exactly the change that must not be made.
    _writes1202zr = [h for h in hits if _hit_is_write_1202zr(h)]
    _reads1202zr = [h for h in hits if not _hit_is_write_1202zr(h)]
    _out1202zr = (" Contract note — these failing flows declare an endpoint the contract marks "
                  "auth_required, which returns 401 to an anonymous visitor: "
                  + join_capped(hits, len(hits), cap=4, sep="; ") + ".")
    if _reads1202zr:
        _out1202zr += (" If the flow is meant to run logged out, the route is "
                       "framework-projected so it is fixed in the CONTRACT rather than the "
                       "page: declare auth_required=false for a read that is meant to be "
                       "public (#320)." + _pub1202gl)
    if _writes1202zr:
        _out1202zr += (" But "
                       + join_capped(_writes1202zr, len(_writes1202zr), cap=4, sep="; ")
                       + " name a WRITE, and a write is not a read that is meant to be "
                         "public: publishing it would let any anonymous visitor perform the "
                         "action. Nothing in the CONTRACT fixes this one — either the flow "
                         "must sign in before it reaches that step, or it should not declare "
                         "that endpoint at all if it is meant to run logged out.")
    return _out1202zr



_WRITE_METHODS_1202ZR = ("POST", "PUT", "PATCH", "DELETE")


def _hit_is_write_1202zr(hit: str) -> bool:
    """Does this `"<flow> -> <api>"` hit name a write?

    `apis_used` entries are written by the lane and the corpus shows both `"POST /api/x"` and a
    bare `"/api/x"`. A hit with no method reads as a READ, which is what the note has always
    assumed -- so an unparseable entry keeps today's advice rather than getting the new sentence
    on a guess.
    """
    # No try/except: #1202ah's ratchet caught the first draft's `except Exception: return False`
    # and it was right twice over -- a silent swallow makes a crash read as "not a write", and
    # nothing here can raise. `str(hit or "")` is total, `split("->", 1)` always yields at least
    # one element, and `split(None, 1)[0]` is only reached when the remainder is non-empty.
    _tail = str(hit or "").split("->", 1)[-1].strip()
    _first = _tail.split(None, 1)[0].upper() if _tail else ""
    return _first in _WRITE_METHODS_1202ZR

_IDENTITY_PROBE_1202QK = re.compile(
    r"^(?:GET\s+)?/(?:api/)?(?:v\d+/)?(?:auth/|users/|user/|account/)?(?:me|whoami|session)/?$",
    re.I)


def _identity_probe_1202qk(api: str) -> bool:
    """`GET /auth/me`, `/api/users/me`, `/session`: endpoints whose 401 means "not signed in"."""
    return bool(_IDENTITY_PROBE_1202QK.match(str(api or "").strip()))


def _flow_coverage_summary(hub_registry, app_root) -> Tuple[Dict[str, Any], List[str]]:
    """Wrap ``flow_coverage.compute_flow_coverage`` so an import or
    runtime fault never propagates into the deliverability gate.

    Returns ``(report_dict, blocker_strings)``.

    ``app_root`` is no longer read — WorkHub is the source of truth —
    but the param stays for backward-compat with the autonomous gate's
    call site. The degraded-path return carries ``"source": "degraded"``
    and ``"degraded": True`` so operators can distinguish a broken
    gate from "design didn't opt in".
    """
    try:
        from .flow_coverage import compute_flow_coverage
    except Exception:
        return dict(_DEGRADED_FLOW_COVERAGE), []

    try:
        report = compute_flow_coverage(hub_registry, app_root)
    except Exception:
        return dict(_DEGRADED_FLOW_COVERAGE), []

    blockers: List[str] = []
    # Anchor the prefix so a flow whose NAME happens to contain
    # "missing" / "failed" (e.g. ``recover_missing_password``) can't
    # collide with the canonicalization elif-chain in
    # ``orchestrator._validate_delivery_gate``. The chain matches on
    # the FULL anchored substrings ``ui flow(s) missing`` and
    # ``ui flow(s) failed:`` — both unique to their direction even
    # after the flow names are appended verbatim.
    if report.missing:
        blockers.append(
            f"{len(report.missing)} critical UI flow(s) missing "
            f"`validation:ui_flow` records: "
            + join_capped(report.missing, len(report.missing), cap=10, sep=", ")
        )
    if report.failed:
        blockers.append(
            f"{len(report.failed)} critical UI flow(s) failed: "
            + join_capped(report.failed, len(report.failed), cap=10, sep=", ")
            # #1202fr: append the contract reason when there is one. The anchored prefix
            # above is what orchestrator._validate_delivery_gate canonicalises on, and this
            # text is added AFTER the names and contains neither anchor phrase.
            + _auth_wedge_note_1202fr(hub_registry, report.failed)
        )
    if report.source == "critical_flows_invalid":
        # Designer wrote ``critical_flows: [...]`` but every entry was
        # unparseable (missing both ``name`` and ``id``). Without
        # this blocker the gate would silently fall through to page
        # derivation and the designer's bug would never surface.
        blockers.append(
            "Frontend kickoff `critical_flows[]` is present but every "
            "entry is unparseable (missing `name`/`id`)."
        )
    return report.to_dict(), blockers


_SAID_958: Dict[str, bool] = {}


def _visual_summary(hub_registry) -> Dict[str, int]:
    gate = getattr(hub_registry, "gate_registry", None)
    if gate is None or not hasattr(gate, "list_critical_visual_reviews"):
        return {"critical_total": 0, "approved": 0,
                "pending": 0, "needs_revision": 0}
    critical = gate.list_critical_visual_reviews() or []
    approved = sum(1 for p in critical if p.get("status") == "approved")
    pending = sum(1 for p in critical
                  if p.get("status") in ("pending", "reviewing"))
    needs_rev = sum(1 for p in critical if p.get("status") == "needs_revision")
    return {"critical_total": len(critical), "approved": approved,
            "pending": pending, "needs_revision": needs_rev}


def compute_deliverability(hub_registry, app_root,
                            session_start_ts: float = 0.0) -> DeliverabilityReport:
    blockers: List[str] = []

    runhub = getattr(hub_registry, "runhub", None)
    last_run = None
    run_within_session = False
    if runhub is not None and hasattr(runhub, "last_successful_run_since"):
        last_run = runhub.last_successful_run_since(session_start_ts)
        run_within_session = last_run is not None

    if not run_within_session:
        blockers.append(
            "no successful RunHub run since session start "
            "(call run_start(...) and ensure fail_count=0 before deliver)")

    ep_counts = _probe_counts(last_run.get("probes") if last_run else [])
    mcp_counts = _probe_counts(last_run.get("mcp_probes") if last_run else [])
    if last_run:   # #1203e4: say WHOSE evidence this is, and which run it was
        ep_counts["source_1203e4"] = _probe_source_1203e4(last_run)
        ep_counts["run_id_1203e4"] = str(last_run.get("id") or "")
    # #1203e7: and read the NEWEST evidence, not only the newest FLATTERING evidence. The two
    # terms are different questions: `last_run` answers "did a clean run happen this session",
    # which must keep using `last_successful_run_since`; a 5xx is about what the app does NOW.
    _5xx1203e7: List[str] = []
    try:
        _unread1203e7: List[str] = []
        _5xx1203e7 = _server_error_probes_1203e7(
            runhub.list_runs(limit=200), since_ts=float(session_start_ts or 0.0),
            unreadable=_unread1203e7)
        if _unread1203e7:      # #883: say what could not be read instead of counting it clean
            ep_counts["unreadable_probe_records_1203e7"] = _unread1203e7[:10]
    except Exception as _e7exc:
        # #883's ratchet: an empty default here READS AS CLEAN, so it must announce itself or it
        # is a fallback that masks a failure. Both channels, because they answer different
        # readers: `_swallowed_790` is the gate's own "this check did not run, the release is
        # unverified on that axis" ledger, `warn_once_1201` the once-per-process operator line.
        try:
            from .delivery_gate import _swallowed_790
            _swallowed_790("deliverability.server_errors_1203e7", _e7exc,
                           "no 5xx found (NOT evidence that none exist)")
        except Exception:
            pass
        from .message_format import warn_once_1201    # #940: function-local, as every other
        warn_once_1201("compute_deliverability.server_errors_1203e7",   # use in this file is
                       "the 5xx-probe blocker #1203e7", _e7exc)
    # #1203e8: and say what the writers the gate did NOT read found, so the ledger stops showing
    # one writer's answer as though it were the only one. Records, never blocks.
    try:
        _other1203e8 = _other_writers_failures_1203e8(
            runhub.list_runs(limit=200), str((last_run or {}).get("id") or ""),
            since_ts=float(session_start_ts or 0.0))
        if _other1203e8:
            ep_counts["other_writer_failures_1203e8"] = _other1203e8[:12]
    except Exception as _e8exc:
        from .message_format import warn_once_1201 as _w1203e8
        _w1203e8("compute_deliverability.other_writers_1203e8",
                 "the other-writer probe summary #1203e8", _e8exc)
    if _5xx1203e7:
        ep_counts["server_errors_1203e7"] = list(_5xx1203e7)
        # #1202tu's ratchet: a blocker that can decline delivery must dispatch somebody. The
        # phrase "failed endpoint probe(s)" is deliberate -- `_deliverability_check_token` already
        # maps it to `deliverability_failed_endpoint_probes`, the token minted for the blocker
        # that could never fire. Reviving that token beats minting a second name for one fact
        # (#1032), and `_GATE_OWNER` now carries the body that tells the backend what to do.
        blockers.append(
            "%d failed endpoint probe(s) answering 5xx (newest result from the probe that saw "
            "it): %s — a server error is never a correct answer to a probe, and this does not "
            "clear by re-running. An anonymous probe getting 5xx where an authenticated one gets "
            "200 is a handler that crashes with no user context instead of answering 401; both "
            "readings are real and neither cancels the other."
            % (len(_5xx1203e7), join_capped(_5xx1203e7, len(_5xx1203e7), cap=6, sep=", ")))
    if ep_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {ep_counts['failed']} failed endpoint probe(s)")
    if mcp_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {mcp_counts['failed']} failed MCP probe(s)")

    # A deterministically functionally-validated WORKING app — a successful
    # in-session RunHub run with zero failed endpoint/MCP probes — is deliverable.
    # The gates below (coverage "dead artifacts", un-reviewed visual, missing
    # ui_flow) then become WARNINGS, not hard blockers: an automated agent
    # pipeline must not block delivery FOREVER on review/coverage/UI-test steps a
    # drifting reviewer/verifier LLM never performs — AND the coverage audit
    # false-flags spine tables (tenants/users/oauth_*), build config (eslint/
    # postcss) and support modules (oauth_routes/schemas) as "dead" even on a
    # provably-working app (smoke #14: 17 "dead" artifacts, all real+used). HARD
    # gates still block: no run / failed probes / MISSING seed / visual
    # NEEDS_REVISION (an explicit FAIL) / story evidence.
    # #1203d6: ask for EVIDENCE, not for the absence of bad news. This flag downgrades the
    # dead-artifact, visual and ui_flow blockers from hard to warning, and it used to be
    # satisfied by `failed == 0` alone -- which a run that skipped every endpoint satisfies by
    # construction. Measured over the gate ledgers: 146 of 532 `deliverable` verdicts (27%, 9
    # runs) had `endpoint_probes` all-skipped, 47 of them in r149. `passed` and `skipped` were
    # already being counted one function up; neither was ever read (#1202wk: the fact that only
    # reaches a log). The counts already reach `delivery_gate.jsonl`, so the missing piece was
    # never reporting -- it was that nothing ACTED on them. #1203d6's planner change above is
    # the root-cause fix; this is the ratchet that stops a future skip rule from quietly buying
    # the relaxations back.
    functionally_validated = (
        run_within_session
        and probed_something_1203d6(ep_counts)      # #1203d6
        and ep_counts.get("failed", 0) == 0
        and mcp_counts.get("failed", 0) == 0
    )
    # UI-facing gates (visual / ui_flow) may downgrade only when the app is functionally
    # validated AND (#193, default-ON) at least one UI/browser/test-user record
    # passed — so a backend-only-validated, blank-UI app no longer waives them.
    ui_validated = functionally_validated and (
        _has_passing_ui_evidence(hub_registry) if _require_ui_evidence() else True)

    coverage = _coverage_summary(hub_registry, app_root)
    if not coverage.get("is_clean", True) and not functionally_validated:
        dead = coverage.get("dead_count_by_kind") or {}
        total = sum(dead.values()) if dead else 0
        # #1042: the KINDS were summed away. "7 dead artifact(s)" cannot be acted on and
        # cannot even be routed — `endpoints`/`tables`/`mcp_tools` are backend work while
        # `files`/`pages_without_files` are frontend, and the reader was told neither. The
        # breakdown is already computed one function up; only the sum was ever printed.
        _kinds = ", ".join(f"{k}={v}" for k, v in sorted(dead.items()) if v)
        # #1086: and the NAMES — see _dead_artifact_names_1086. Capped by the same helper
        # `_flow_coverage_summary` uses, which declares the remainder.
        _names = coverage.get("dead_names") or []
        blockers.append(
            f"{total} dead artifact(s) (Cutover 19 gate)"
            + (f" — {_kinds}" if _kinds else "")
            + (f": {join_capped(_names, len(_names), cap=10, sep=', ')}" if _names else ""))

    # ui_page HARD wiring gate (B1, 2026-06-12). A declared ui_page whose route
    # isn't wired in App.jsx, or whose component file is absent, ships a page
    # that won't open — yet api_smoke (the basis of functionally_validated)
    # probes only the BACKEND and never opens a frontend page. So unlike the
    # coverage/seed/visual gates above, this is NOT relaxed on a functionally-
    # validated app: it's a deterministic code fact (route literal present in
    # App.jsx? component file on disk?), low-false-positive, and self-clearing
    # once the lane wires the page — never a permanent block.
    blockers.extend(_ui_page_wiring_blockers(hub_registry, app_root))

    # ROUTED-FALLBACK sweep (#223). The registry-driven gate above only sees
    # REGISTERED ui_pages; the heal projector also fills dangling route-wired
    # imports the lane never registered, and the lane strips markers (#222).
    # Code-truth scan of App.jsx-wired components: a generic-fallback body
    # (content fingerprint) blocks delivery regardless of registration. Like
    # the gates above, NOT relaxed on functionally_validated (api_smoke never
    # opens a page); self-clearing once the page is authored.
    if os.environ.get("ENVGEN_FALLBACK_PAGE_GATE", "1") not in ("0", "false", "no"):
        try:
            from .frontend_audit import routed_fallback_page_blockers
            blockers.extend(routed_fallback_page_blockers(
                Path(app_root) / "frontend" / "src"))
        except Exception:
            pass

    # DEAD-NAV-LINK gate (#238, tiktok r27 M1 runtime-verified): the app's own
    # Profile+Upload nav <Link>s resolved to no App.jsx route → 404 on click.
    # NOT relaxed on functionally_validated (api_smoke never clicks a nav link);
    # deterministic code fact, conservative (literal absolute targets only),
    # self-clearing once the lane wires the route or fixes the link. Env escape
    # hatch for the opt-5 false-block lesson.
    if os.environ.get("ENVGEN_DEAD_NAV_GATE", "1") not in ("0", "false", "no"):
        try:
            from .frontend_audit import (
                dead_nav_link_blockers, reference_screen_routes)
            # #354: a dead link to a screen the REFERENCE shows must be authored,
            # not deleted — app_root is <output>/app, so the design dir is its parent.
            blockers.extend(dead_nav_link_blockers(
                Path(app_root) / "frontend" / "src",
                reference_routes=reference_screen_routes(Path(app_root).parent)))
        except Exception:
            pass

    # #1202qn: a failed request answered with hard-coded data (see frontend_audit).
    if app_root and os.environ.get("ENVGEN_MASKED_FAILURE_GATE", "1") not in ("0", "false", "no"):
        from .frontend_audit import masked_api_failure_blockers_1202qn
        blockers.extend(masked_api_failure_blockers_1202qn(Path(app_root) / "frontend" / "src"))
        # #1202rl: the sibling shape #1202qn structurally cannot see -- a page that renders a
        # hardcoded data module and never calls the server at all, so nothing fails and
        # nothing is masked. Found by an unprimed agent doing an ordinary task, not by a scan.
        from .frontend_audit import static_twin_blockers_1202rl
        blockers.extend(static_twin_blockers_1202rl(Path(app_root) / "frontend" / "src"))

    # BARE-FETCH-NO-TOKEN gate (#154, gmrun4 root cause). Like the ui_page gate
    # above, NOT relaxed on a functionally-validated app: api_smoke probes the
    # backend with a FRAMEWORK-minted token, so a frontend that never attaches
    # the user's token 401s at runtime while every functional check stays green
    # (gmrun4: delivered 4 milestones, browser showed a login wall). Static,
    # low-false-positive (literal '/api/' URLs only, public endpoints and any
    # auth evidence excused), self-clearing once the lane wires the token.
    blockers.extend(_bare_fetch_blockers(app_root))

    # PLACEHOLDER-STUB backend handler gate (#173, gmrun9). A GET route that returns a
    # hardcoded empty collection with no DB read renders a permanently-empty page — the
    # backend twin of a mock frontend. Static AST on the served backend tree, self-clearing
    # once the handler queries the real table.
    blockers.extend(_stub_handler_blockers(app_root))

    # UNSCOPED OWNER READ gate (#919). A served GET that returns every row of a table
    # owned via a recognised owner column, to any authenticated caller -- the shape
    # #908 shipped live in r153 while every other gate stayed green. Uses the SAME
    # ownership decision the projector uses to emit the filter, so the gate and the
    # generator cannot disagree about what is private.
    blockers.extend(_unscoped_owner_read_blockers(app_root))
    blockers.extend(_auth_override_blockers_1202s(app_root))
    blockers.extend(_guard_tampering_blockers_1202oj(app_root, hub_registry))   # #1202oj/#1202y9

    # FABRICATED member-field fallback gate (#175, gmrun9). The frontend renders
    # `place.rating || '4.5'` / `? place.name : 'HI Point Montara Lighthouse'` — invented data
    # shown whenever the real field is absent (often always, on a field-name drift). Static
    # scan of the frontend JSX, self-clearing once the fake literal is removed.
    blockers.extend(_invented_field_blockers(app_root))
    blockers.extend(_placeholder_route_blockers_1202w(app_root))
    blockers.extend(_operator_identity_blockers_1202rj(app_root))
    blockers.extend(_parked_probe_routes_1202y7(app_root))
    blockers.extend(_reserved_email_domain_blockers_1202rs(app_root))
    blockers.extend(_no_page_declares_an_api_1202rm(hub_registry))
    blockers.extend(_unreachable_routes_1202rq(app_root))
    blockers.extend(_routes_that_ignore_their_parameter_1202rz(app_root))
    blockers.extend(_third_party_private_columns_1202sb(app_root))
    blockers.extend(_page_api_declaration_drift_1202rr(hub_registry, app_root))

    # Seed gate: the backend drifts on seed-data registration (the same
    # bookkeeping-the-LLM-never-does class as ui_flow/visual). On a functionally-
    # validated app the api_smoke already proved the business tables WORK
    # (register mints a user row; the smoke inserts + reads notes), so a missing /
    # low-row seed REGISTRATION is a WARNING, not a hard blocker. It still blocks
    # when the app is NOT functionally validated.
    seed = _seed_summary(hub_registry, app_root)
    if seed.get("missing", 0) > 0 and not functionally_validated:
        # #1203c5: NAME THEM. `_seed_summary` already carries `flagged_tables` -- #1202ow put
        # it there because "the task body could only say 'N table(s)'" -- and this sentence,
        # which is what the gate ledger records and the lane reads, stayed on the count. Over
        # every gate ledger it fires 191 times in 22 runs and names a table ZERO times, while
        # in the SAME record `dead_artifacts` lists its files and `business_chain_failing`
        # gives the step and the 400 body. One reader fixed is worse than none (#1202lf): the
        # count made the gap look like a design choice.
        _seednames_1203c5 = [
            "%s (%s)" % (t.get("table"), t.get("reason"))
            for t in (seed.get("flagged_tables") or [])
            if isinstance(t, dict) and t.get("reason") == "missing_seed" and t.get("table")]
        blockers.append(
            f"{seed['missing']} table(s) missing seed registration (Cutover 21 gate)"
            + (": " + join_capped(_seednames_1203c5, len(_seednames_1203c5), cap=8)
               if _seednames_1203c5 else ""))
    if seed.get("flagged", 0) > seed.get("missing", 0) and not functionally_validated:
        # additional flagged are placeholder_content or low_row_count
        extra = seed["flagged"] - seed.get("missing", 0)
        blockers.append(
            f"{extra} table(s) with low row count or placeholder seed (Cutover 21 gate)")

    # AUTHORED-SEED gate (outlook run-33, 2026-07-02) — NOT waived by functional
    # validation: the registration checks above audit hub BOOKKEEPING and are relaxed
    # once api_smoke passes, so a run whose lane never authored app/backend/
    # seed_data.json shipped the bland framework-fallback seed as "SUCCESS" — while the
    # spec's bar is domain-REALISTIC populated screens ("a dozen realistic emails …
    # populated on first load"). The file is guaranteed to EXIST (empty {}) by the
    # build-infra writers, so absent-or-empty means the lane hasn't authored data yet;
    # the remediation dispatch + deliver guard then drive it to (run-31 proved the lane
    # CAN author it). Clears the moment a non-empty valid JSON lands.
    try:
        import json as _json
        # #324 (r92/r93 M1 wedge — dominant per-run sink, found independently by the backend
        # AND orchestrator trajectory reviewers): the authored-seed check reads the INTEGRATION
        # tree, but the backend commits its populated seed_data.json to its OWN lane worktree.
        # #322's reconcile_integration_seed ran only at the two terminal MERGE sites, never
        # before THIS read — so every deliverability poll re-read the {} placeholder and reported
        # "authored seed missing" while a valid seed sat in the worktree; the gate could clear
        # ONLY by force-delivering (which triggered the merge). Reconcile the lane-authored seed
        # onto integration BEFORE reading, so the first poll reflects committed lane work.
        # Idempotent + best-effort: #322 never clobbers a populated integration seed, never raises.
        try:
            from .heal_pipeline import reconcile_integration_seed
            reconcile_integration_seed(Path(app_root).parent)
        except Exception:
            pass
        # #470: also (re)stage the framework's REAL dataset seed (design/dataset →
        # app/backend/seed_dataset.json) BEFORE the authored-seed read. r46 (closest-ever
        # delivery: seed 261 rows, api_smoke 13/13, ui_flow 10/10) fired 'authored seed
        # missing' PURELY because neither seed_data.json NOR seed_dataset.json had reached
        # the gate's tree at check time — even though the gate ALREADY merges seed_dataset
        # (below) and _ensure_seed_dataset stages it at skeleton-gen; the early staging just
        # hadn't landed on the gate's app_root yet. Staging it here (idempotent regen from
        # design/dataset, best-effort, no-op without design/dataset → zero regression) makes
        # the gate see the real rows on the FIRST poll, so the seed-timing blocker stops
        # firing spuriously — collapsing the remediation whack-a-mole that starved r46's
        # delivery convergence. Generalizable to every app/env.
        try:
            from .backend_skeleton import _ensure_seed_dataset
            _ensure_seed_dataset(Path(app_root) / "backend", Path(app_root).parent)
        except Exception:
            pass
        _seed_path = Path(app_root) / "backend" / "seed_data.json"
        _data = {}
        if _seed_path.exists():
            try:
                _data = _json.loads(_seed_path.read_text(encoding="utf-8"))
                if not isinstance(_data, dict):
                    _data = {}
            except Exception:
                _data = {}
        # #473 SEED-VISIBILITY RACE (2026-08-04, r46/r47/r49 chronic no-convergence): the
        # gate reads the WORKING-TREE seed_data.json, but on some ticks that file is
        # transiently EMPTY while the REAL seed is COMMITTED to integration HEAD (r49:
        # 223 rows committed 07:17:48; the backend even force-resynced it 3× as the gate
        # kept firing 'authored seed missing' → 22 deliver_project / 0 release). reconcile_
        # integration_seed only scans worktree WORKING files (also transiently empty) and
        # NEVER reads the committed HEAD, so it no-op'd. FIX: when the working-tree seed is
        # empty, restore it from the committed integration HEAD — the tree the delivery
        # SNAPSHOT/docker image actually ships — so the gate reflects true shipped state AND
        # the working tree is repaired for the build. Activates ONLY in the empty case
        # (never regresses a populated seed), no-ops when HEAD is also empty (genuine
        # missing → still blocks correctly). Best-effort, read-only wrt real data.
        if not any(isinstance(v, list) and v for v in _data.values()):
            try:
                import subprocess as _sp
                _r = _sp.run(
                    ["git", "show", "HEAD:app/backend/seed_data.json"],
                    cwd=str(Path(app_root).parent), capture_output=True, text=True, timeout=15)
                if _r.returncode == 0 and _r.stdout.strip():
                    _head = _json.loads(_r.stdout)
                    if isinstance(_head, dict) and any(
                            isinstance(v, list) and v for v in _head.values()):
                        _data = _head
                        try:  # repair the working tree so the docker build ships the seed
                            # #1202ts: seed_data.json is LANE-OWNED by the same frozenset that
                            # makes custom_routes.py lane-owned, and "empty" here means empty of
                            # ROWS, not of bytes -- a contract with tables declared and no rows
                            # is ~33 bytes, which #1202cw treats as occupied and refuses. So the
                            # overwrite declares the ticket that argued for it, and the census
                            # that run_budget.json carries can finally see it.
                            from .path_routed_workspace import (
                                framework_write_1202cw as _fw_write_1202cw)
                            _seed_path.parent.mkdir(parents=True, exist_ok=True)
                            _fw_write_1202cw(
                                _seed_path, _json.dumps(_head, indent=2) + "\n",
                                clobber_ok="#1068: the working-tree seed is empty of rows and "
                                           "the committed integration HEAD is what the delivery "
                                           "snapshot ships")
                        except Exception as _repair_exc_1068:
                            # #1068: the VERDICT above is already decided from HEAD — the tree
                            # the delivery snapshot ships — so a failed repair does not change
                            # it. What it does change is the WORKING TREE the local docker
                            # build reads: the gate says the seed is present while the file on
                            # disk is still the empty placeholder. That divergence used to
                            # leave no trace at all. Once per process; verdict untouched.
                            if not _SEED_REPAIR_FAILED_1068["said"]:
                                _SEED_REPAIR_FAILED_1068["said"] = True
                                _LOG_700.warning(
                                    "#1068 seed working-tree repair FAILED (%s: %s). The gate "
                                    "reads the seed from integration HEAD and is unaffected, "
                                    "but %s still holds the empty placeholder — a build that "
                                    "reads the working tree ships no seed. Logged once.",
                                    type(_repair_exc_1068).__name__,
                                    str(_repair_exc_1068)[:160], _seed_path)
            except Exception:
                pass
        # F2: the framework-owned seed_dataset.json (design-prep REAL data the loader
        # merges into the DB) counts toward BOTH the authored check and the quality
        # row-floor — a run whose real rows live there must not trip the gate just
        # because the lane's seed_data.json is thin. Merged view; dataset tables win.
        _real = {}
        try:
            _ds_path = Path(app_root) / "backend" / "seed_dataset.json"
            if _ds_path.exists():
                _rd = _json.loads(_ds_path.read_text(encoding="utf-8"))
                if isinstance(_rd, dict):
                    _real = _rd
        except Exception:
            _real = {}
        _data = {**_data, **{k: v for k, v in _real.items() if isinstance(v, list) and v}}
        _authored = any(isinstance(v, list) and v for v in _data.values())
        if not _authored:
            blockers.append(
                "authored seed missing: app/backend/seed_data.json is absent or empty — "
                "the app would ship the bland framework-fallback seed. Author domain-"
                "realistic rows (users + every business table, FK-valid, believable "
                "subjects/bodies/timestamps) in app/backend/seed_data.json.")
        elif os.environ.get("ENVGEN_SEED_QUALITY_GATE", "1") not in ("0", "off", "false"):
            # Fix #54 — the seed exists; is it GOOD? #41 only proves non-empty,
            # so a 2-row token seed shipped as "SUCCESS" while the bar is
            # populated, realistic list screens (info density = the top visual
            # lever). Same non-waivable family as #41 (content quality is
            # exactly what functional validation does NOT prove); conservative
            # signals only (see audit_authored_seed) + recomputed each tick so
            # a rewritten seed self-clears.
            try:
                from .seed_audit import audit_authored_seed
                _issues = audit_authored_seed(_data)
            except Exception as _sa_exc:
                # #881: this handler was BARE — no log, no record. A seed audit that raised
                # produced `[]`, which is byte-identical to "the seed is fine", and the gate
                # shipped on it.
                #
                # ★ #792 is in THIS FILE and exists for exactly this ("a delivery GATE that cannot
                # load must not read as a delivery gate that PASSED"). It wired the two audit
                # imports above and did not reach this one — the same miss #879 found for #790,
                # which swept `delivery_gate.py` and left the orchestrator's page-build detect
                # behind. **Both sweeps left a decision-driving swallow inside a file they swept.**
                _gate_absent_792("authored_seed_quality", _sa_exc, "audit")
                _issues = []
            if _issues:
                blockers.append(
                    "authored seed quality: " + "; ".join(_issues)
                    + " — rewrite app/backend/seed_data.json (keep it FK-valid).")
            # #1203ga: and CHECK the "keep it FK-valid" the line above asks for. #1168 audits
            # the same property from the live database, which #1039 records as essentially
            # never available -- `orphan_fk_rows` reaches the hub output of 3 corpus runs. The
            # file is on disk the whole time: 247 dangling references across 10 runs, 4 of them
            # delivered. Reported, not blocking, which is #1168's stated policy for this exact
            # property ("evidence for the lane", #566j: a false seed blocker wedges a run).
            try:
                from .seed_audit import orphan_fk_rows_in_authored_seed_1203ga
                _orph1203ga = orphan_fk_rows_in_authored_seed_1203ga(_data)
                if _orph1203ga:
                    _n1203ga = sum(_orph1203ga.values())
                    _log1203ga = logging.getLogger(__name__)
                    _log1203ga.warning(
                        "#1203ga the authored seed has %d row(s) whose foreign key points at a "
                        "row that is NOT in seed_data.json: %s. The seed blocker above already "
                        "says \"keep it FK-valid\" and nothing checked it; #1168 asks the same "
                        "question of the live database, which is almost never up. netflix-r32 "
                        "shipped title_genres/my_list/ratings/continue_watching all pointing at "
                        "titles 7-12 while `titles` holds 1-6. Reported, not blocking.",
                        _n1203ga,
                        # #1034: a count must not sit beside a SILENT cut. `join_capped`
                        # declares what it left out; `[:8]` did not, and that ratchet caught it.
                        join_capped(["%s=%d" % (k, v) for k, v in sorted(_orph1203ga.items())],
                                    total=len(_orph1203ga), cap=8))
            except Exception as _e1203ga:
                _gate_absent_792("authored_seed_orphan_fk_1203ga", _e1203ga, "audit")
    except Exception:
        pass

    visual = _visual_summary(hub_registry)
    # #958: this gate has never been able to fire. `list_critical_visual_reviews()` filters the
    # ui_pages store for `kind == "visual_review"`, and across 154 runs all 2405 ui_page records
    # carry `kind == "ui_page"` — not one visual_review has ever been created. Both blockers below
    # are `> 0` tests on a value that is structurally 0, so Cutover 20 blocks nothing, and its
    # all-zero line in the deliverability report reads as "reviews done" rather than "none exist".
    #
    # Not repaired here: making it fire requires deciding WHO creates a visual_review page and
    # WHEN, which is workflow design, not a fix. Said out loud instead (#956/#957's disposition).
    if not visual.get("critical_total") and not _SAID_958.get("x"):
        _SAID_958["x"] = True
        logging.getLogger(__name__).info(
            "Cutover 20 (critical visual reviews) inspected 0 records — no ui_page with "
            "kind='visual_review' exists, and none has in any run of the corpus. Its zeros below "
            "mean NOT PRESENT, not approved (#958).")
    if visual.get("pending", 0) > 0 and not ui_validated:
        blockers.append(
            f"{visual['pending']} critical visual review(s) pending (Cutover 20 gate)")
    if visual.get("needs_revision", 0) > 0:
        blockers.append(
            f"{visual['needs_revision']} critical visual review(s) need revision")

    # Flow-coverage gate. For each critical UI flow declared in the frontend
    # kickoff section the verifier must drive a real browser test (navigate +
    # interaction) and write a passing ``validation:ui_flow:<name>`` record.
    # ui_flow is browser-driven UI testing the verifier LLM reliably drifts on
    # (smoke #14: 5 declared flows, 0 records) — same class as the visual review
    # gate. So a MISSING ui_flow record is a WARNING on a functionally-validated
    # app (passing api_smoke RunHub run); it still blocks when NOT validated. (A
    # FAILED ui_flow — recorded but not passing — is surfaced by the api_smoke
    # probe path; this only relaxes the never-ran case.)
    # ui_flow gate (intentional PR-7 functional-UI-testing gate). A MISSING
    # (never-ran) ui_flow record is the verifier-drift case — the verifier LLM
    # reliably will not drive the browser (every smoke: declared flows, 0 records).
    # On a deterministically functionally-validated app (passing in-session
    # api_smoke RunHub run, 0 failed probes) a MISSING record is therefore a
    # WARNING, not a hard blocker — same principle as the visual review gate. A
    # FAILED ui_flow (recorded but not passing) or an INVALID critical-flow
    # declaration is a real defect and ALWAYS blocks; so does MISSING when the app
    # is NOT functionally validated. Key on the ANCHORED phrase "ui flow(s)
    # missing" (NOT the bare word "missing") so a flow NAMED e.g.
    # recover_missing_password and the invalid-declaration blocker
    # ("missing `name`/`id`") are NOT suppressed.
    flow_coverage, flow_blockers = _flow_coverage_summary(hub_registry, app_root)
    if ui_validated:
        flow_blockers = [b for b in flow_blockers if "ui flow(s) missing" not in b.lower()]
    blockers.extend(flow_blockers)

    # Phase 3 story-gate hook (commit c9a81e22 + 763b408f). At
    # phase>=3.0 the story_hub.evaluate_story_gate walks each
    # registered story's evidence_targets, dispatches by namespace
    # prefix to canonical-writer-reading resolvers, and reports any
    # unresolved targets as per-story blockers. With zero registered
    # stories the gate returns ok=True trivially (vacuous), so the
    # hook is a no-op when story_hub hasn't been adopted by the
    # current pipeline run. Empty-actor system-bootstrap paths are
    # already exempt (the gate compares evidence, not actor).
    try:
        if hasattr(hub_registry, "story_hub"):
            persisted = (
                hub_registry.story_hub.stores.stories.value()
                if (hub_registry.story_hub.stores is not None
                    and hasattr(hub_registry.story_hub.stores, "stories"))
                else {}
            )
            stories_list = [
                v for v in persisted.values()
                if isinstance(v, dict) and v.get("id")
            ]
            verdict_gate = hub_registry.story_hub.evaluate_story_gate(
                stories_list, reg=hub_registry,
            )
            for s in verdict_gate.get("stories") or []:
                if s.get("status") != "delivered":
                    sid = s.get("id", "?")
                    for b in (s.get("blockers") or []):
                        blockers.append(f"story[{sid}] {b}")
    except Exception:
        # Story-gate hook is best-effort — runs that don't use
        # story_hub fall through. Don't fail delivery for hook
        # plumbing errors; the regular blockers list is authoritative.
        pass

    verdict = "deliverable" if not blockers else "blocked"
    return DeliverabilityReport(
        last_successful_run=last_run,
        run_within_session=run_within_session,
        endpoint_probes=ep_counts,
        mcp_probes=mcp_counts,
        coverage=coverage,
        seed_data=seed,
        visual_reviews=visual,
        flow_coverage=flow_coverage,
        blockers=blockers,
        verdict=verdict,
    )


__all__ = ["DeliverabilityReport", "compute_deliverability"]
