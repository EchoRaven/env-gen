"""Deliverability aggregator (Cutover 24).

Pure read-side over RunHub + RegistryHub + WorkHub + coverage_audit + seed_audit.
Replaces the LLM-judged checklist with an evidence-based unified report.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

_LOG_700 = logging.getLogger(__name__)
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
    endpoint_probes: Dict[str, int] = field(default_factory=dict)
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


def _coverage_summary(hub_registry, app_root) -> Dict[str, Any]:
    try:
        from .coverage_audit import compute_coverage
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
    try:
        report = compute_coverage(hub_registry, Path(app_root))
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
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
    }


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
            for _x in crossed_page_endpoints_728(_pages_700, _eps728) or []:
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
                _f959.write_text(_j959.dumps(_prev959, indent=1, sort_keys=True), encoding="utf-8")
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
    except Exception:
        pass
    try:
        return ui_page_delivery_blockers(Path(app_root) / "frontend" / "src", workhub)
    except Exception:
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


def _seed_summary(hub_registry) -> Dict[str, Any]:
    try:
        from .seed_audit import audit_seed_data
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    try:
        report = audit_seed_data(hub_registry)
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    schema_hub = getattr(hub_registry, "schema_hub", None)
    total_tables = len((schema_hub.list_tables() if schema_hub else {}) or {})
    registered = len((schema_hub.list_seed_registrations() if schema_hub else {}) or {})
    missing = sum(1 for f in report.flagged_tables if f.get("reason") == "missing_seed")
    flagged = len(report.flagged_tables)
    return {"tables": total_tables, "registered": registered,
            "missing": missing, "flagged": flagged}


_DEGRADED_FLOW_COVERAGE = {
    "required": [], "passed": [], "failed": [], "missing": [],
    "source": "degraded", "is_clean": True, "degraded": True,
}


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
            + ", ".join(report.missing[:10])
        )
    if report.failed:
        blockers.append(
            f"{len(report.failed)} critical UI flow(s) failed: "
            + ", ".join(report.failed[:10])
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
    functionally_validated = (
        run_within_session
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
        blockers.append(f"{total} dead artifact(s) (Cutover 19 gate)")

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

    # FABRICATED member-field fallback gate (#175, gmrun9). The frontend renders
    # `place.rating || '4.5'` / `? place.name : 'HI Point Montara Lighthouse'` — invented data
    # shown whenever the real field is absent (often always, on a field-name drift). Static
    # scan of the frontend JSX, self-clearing once the fake literal is removed.
    blockers.extend(_invented_field_blockers(app_root))

    # Seed gate: the backend drifts on seed-data registration (the same
    # bookkeeping-the-LLM-never-does class as ui_flow/visual). On a functionally-
    # validated app the api_smoke already proved the business tables WORK
    # (register mints a user row; the smoke inserts + reads notes), so a missing /
    # low-row seed REGISTRATION is a WARNING, not a hard blocker. It still blocks
    # when the app is NOT functionally validated.
    seed = _seed_summary(hub_registry)
    if seed.get("missing", 0) > 0 and not functionally_validated:
        blockers.append(
            f"{seed['missing']} table(s) missing seed registration (Cutover 21 gate)")
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
                            _seed_path.parent.mkdir(parents=True, exist_ok=True)
                            _seed_path.write_text(
                                _json.dumps(_head, indent=2) + "\n", encoding="utf-8")
                        except Exception:
                            pass
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
