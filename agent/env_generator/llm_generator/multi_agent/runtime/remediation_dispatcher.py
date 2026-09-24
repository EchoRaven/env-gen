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
from typing import Any, Dict, List, Mapping, Optional, Sequence
from .message_format import join_capped  # #1034

def _matchable_route_1202iy(route):
    """The route as React Router can MATCH it, for text handed to a lane.

    Telling a lane to wire `<Route path="/@:username">` verbatim produces a route that
    compiles to a literal and never fires -- the same dead wiring these instructions exist to
    repair. Same normalisation the projector applies (#1202iy), asked of the one owner rather
    than restated here, so the emitted App.jsx and the advice cannot drift.

    Audible on failure: a silent fallback would leave the advice quietly wrong, which is the
    shape #1201 exists to stop.
    """
    try:
        from .frontend_scaffold import _router_matchable_route_1202iy as _rm
        return _rm(route)
    except Exception as _exc1202iy:
        from .message_format import warn_once_1201
        warn_once_1201("remediation_dispatcher.matchable_route_1202iy",
                       "the React-Router route normalisation (#1202iy) — a lane may be told "
                       "to wire a path that compiles to a literal and never matches",
                       _exc1202iy)
        return route


def _swallowed_1152(where: str, exc: BaseException, defaulting_to: str) -> None:
    """#1152: SAY WHEN A REMEDIATION DETECTOR COULD NOT RUN.

    delivery_gate has had `_swallowed_790` since r148 and uses it 9 times; nothing
    outside that one file does. This module is where the framework decides WHAT TO
    TELL A LANE, and four of its detectors answered a raised exception with `[]` --
    the same value they return when everything is fine. So a broken detector and a
    clean codebase were indistinguishable, and the lane was told nothing either way.
    That is the shape of r4/r7/r9/r10: a run ends 1-3 checks short with no
    remediation ever filed for them.

    Reuse #790's reporter rather than opening a second channel, so a swallowed
    remediation check surfaces in `check_errors_790()` beside the gate's own.
    Never raises.
    """
    try:
        from .delivery_gate import _swallowed_790
        _swallowed_790(where, exc, defaulting_to)
    except Exception:                      # a reporter must never break remediation
        pass


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


def failed_task_owner_1128(task: Any, live_agents: Any = None) -> str:
    """Which agent can actually RESOLVE this failed task -- #1128.

    The `unresolved_failed_tasks` re-wake prescribes exactly two escapes, and WorkHub grants
    them to different agents:

        complete_task -> `claimed_by == agent`
        cancel_task   -> creator, or the orchestrator (unconditionally)

    Routing on `assignee` alone sends the instruction to an agent both guards refuse. Returns
    the agent to address. An older ledger record carrying neither `claimed_by` nor
    `created_by` cannot be judged, so it keeps the pre-#1128 behaviour (the assignee).
    """
    t = task if isinstance(task, dict) else {}
    assignee = str(t.get("assignee") or "").strip()
    claimed_by = str(t.get("claimed_by") or "").strip()
    created_by = str(t.get("created_by") or "").strip()
    if claimed_by in ("None", "null"):
        claimed_by = ""
    if created_by in ("None", "null"):
        created_by = ""
    knowable = bool(claimed_by or created_by)
    can_complete = bool(assignee) and assignee == claimed_by
    can_cancel = bool(assignee) and (assignee == created_by or assignee == "orchestrator")
    _owner = assignee if (assignee and (not knowable or can_complete or can_cancel)) \
        else (created_by or "orchestrator")
    # #1202kk: ...AND THE OWNER HAS TO STILL BE RUNNING.
    #
    # #1128 routes by AUTHORITY, which was the right question and only half of it. tiktok-r114,
    # live: two P0 tasks were the run's ONLY remaining delivery blocker, assigned to `frontend`,
    # misclaimed by `backend`, and created by `browser_test_user_10_page_profile_own_pag` -- a
    # per-page identity the Browser Test-User agent registers for one walkthrough. Neither
    # escape is open to the assignee (not the claimer, not the creator), so the fall-through
    # addressed the URGENT re-wake to that page identity. Its agent log's last line is
    # `finish(...)` at 12:17:49; the tasks were failed at 12:20:01 and the nag was still being
    # re-sent 33 minutes later. Nobody could act, and `unresolved_failed_tasks` blocked the cut.
    #
    # The framework already refuses this shape one hub over: `registryhub.request_review`
    # rejects a reviewer absent from `_live_agents_provider` because "the review request lands
    # in a dead inbox and nobody will action it". Same provider, same reasoning, same answer.
    #
    # The orchestrator is not a consolation prize here: `cancel_task` grants it UNCONDITIONALLY
    # (this function's own docstring says so) and #1127 made `failed` cancellable, so it is the
    # one agent that can always resolve the task.
    #
    # Corpus: 79 of 153 runs create tasks owned by a non-lane identity (1015 tasks). Only the
    # ones that end `failed` are terminal -- broad exposure, rare landing, no second escape.
    #
    # An ABSENT or EMPTY roster means "not known", never "no agent exists" -- the same reading
    # `request_review` takes (`if live is not None and live:`) -- so every existing caller,
    # which passes nothing, keeps the pre-#1202kk answer exactly.
    try:
        _live = set(live_agents) if live_agents else None
    except TypeError:
        _live = None
    if _live and _owner not in _live:
        return "orchestrator"
    return _owner


def docker_up_host_fault_1202de(detail: Any) -> str:
    """The HOST-level cause named in a `docker_up` failure, or ``""`` when it is the app's.

    Delegates to the visual gate's classifier rather than restating its token list, so the
    two consumers of a compose failure cannot drift into disagreeing about what a host
    fault is — the drift #1202dc's own docstring warns about. Imported lazily: this module
    is on the orchestrator's hot path and visual_fidelity is not.
    """
    d = detail if isinstance(detail, str) else ("" if detail is None else str(detail))
    if not d:
        return ""
    try:
        from .visual_fidelity import _host_fatal_1202de
    except Exception:
        return ""
    return _host_fatal_1202de(d)


def docker_up_owner(detail: Any) -> str:
    """'frontend'/'backend' when the build-failure tail names exactly one
    side's toolchain; 'verifier' (the diagnose-first route) otherwise."""
    # #1043c: narrow explicitly rather than wrapping in `str()`. `detail` is `Any` (it reaches
    # here from a dict), so the coercion is real — but written as `str(detail or "")` a checker
    # reads it as a redundant conversion. An isinstance guard says the same thing and is honest
    # about which case is which.
    d = detail if isinstance(detail, str) else ("" if detail is None else str(detail))
    fe = _FE_BUILD_RE.search(d) is not None
    be = _BE_BUILD_RE.search(d) is not None
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


def suppress_verifier_chain_reauthor(name: str, owner: str, chain_rerun_armed: Any) -> bool:
    # #1043c: `chain_rerun_armed` is annotated `Any`, not `bool`, because its only caller passes
    # `getattr(orch, "_chain_rerun_armed", False)` — an arbitrary attribute no annotation can
    # constrain. The `bool()` below is therefore real narrowing, not the redundant conversion a
    # `bool` annotation made it look like. Same for `docker_up_owner(detail)` above.
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
    # #1043c: `bool()` on the Any operand only, not around the whole expression — same result,
    # and it no longer reads as a redundant conversion of an already-bool comparison chain.
    return (name == "business_chain_failing" and owner == "verifier"
            and bool(chain_rerun_armed))


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


def _canon_endpoint_1135(method, path) -> str:
    """`POST /api/titles/1/rating` and `POST /api/titles/2/rating` are one endpoint.

    Id-looking segments collapse to `{}` — the same shape the endpoint registry already uses
    (`DELETE /api/v1/tenants/{}`), so a sibling that exercised a different row still matches.
    """
    import re as _re
    m = str(method or "?").strip().upper()
    p = str(path or "?").split("?", 1)[0].rstrip("/") or "/"
    segs = []
    for seg in p.split("/"):
        if seg.isdigit() or (seg.startswith("{") and seg.endswith("}")) or len(seg) >= 24:
            segs.append("{}")
        else:
            segs.append(seg)
    return "%s %s" % (m, "/".join(segs) or "/")


def _passing_endpoint_index_1135(chains) -> dict:
    """canonical endpoint -> the PASSING chains whose steps exercised it successfully."""
    idx: dict = {}
    try:
        for name, rec in (chains.items() if isinstance(chains, dict) else []):
            if name == "_meta" or not isinstance(rec, dict):
                continue
            if str(rec.get("status") or "") != "passing":
                continue
            for st in ((rec.get("last_result") or {}).get("steps") or []):
                if not isinstance(st, Mapping) or st.get("ok") is not True:
                    continue
                idx.setdefault(
                    _canon_endpoint_1135(st.get("method"), st.get("path")), set()).add(name)
    except Exception:
        return {}
    return idx


def _step_is_actionable_1202gx(st) -> bool:
    """Is this recorded step something the verifier can and should act on?

    #78 clears the recurring false leak -- a cross-user denial probe that answered 2xx because
    it ran under a stale/owner-colliding token -- by re-running it with a guaranteed-fresh
    intruder. When that intruder is DENIED it marks the row `kind="skipped"` and rewrites the
    note to say so, but leaves `ok=False`. #798 built the "fix THESE" list on `ok` alone, so
    every row #78 had just cleared came back as work.

    r100: four chains carried one (PUT /api/videos/42, 46, 47, 50), all already re-verified as
    DENIED, all listed in the remediation the verifier was holding while `business_chain_failing`
    was the run's last blocker. Those chains' own `broken` lists were 0 -- so this misdirects
    attention rather than failing a gate, and it does it on the one check that mattered.

    Narrow on purpose (#647): only the rows #78 itself cleared, identified by the note it
    writes. A step skipped for any OTHER reason is still unexplained and still reported --
    swallowing those would hide the starvation class #188 exists to surface.
    """
    if not isinstance(st, Mapping):
        return False
    if st.get("ok") is True:
        return False
    if (str(st.get("kind") or "") == "skipped"
            and "re-verified with a FRESH intruder" in str(st.get("note") or "")):
        return False
    return True


def contract_and_surface_annotations_1202ld(orch) -> str:
    """#1202ld: the gate computed these and NOTHING read them.

    `#1202kr` (contract says public / a chain demands a denial), `#1202ky` (contract says
    public / the materials call the table owner-private) and `#1202lb` (several failing chains
    are one endpoint) all append to the `detail` string that
    `_validate_delivery_gate` returns for `business_chain_failing`.

    That string reaches nobody. `dispatch_gate_level_checks(self, failed_checks)` says so in
    its own comment -- "the gate-level failed_checks carry names only" -- and the lane-facing
    task body is built HERE, from the static `_GATE_OWNER` template plus `_extra`. Measured
    across 310 run logs and every workhub_tasks.json in the corpus, the base text of that
    detail -- "verification chain(s) have NOT passed" -- appears ZERO times, and so do all
    three annotations. #1202kr has been dead this way since it shipped.

    tiktok-r119 is the proof that they compute correctly and still say nothing: replaying
    #1202ky against its final ledger names `GET /api/messages`, `GET /api/notifications` and
    `GET /api/video_saves`, while `CONTRACT/MATERIALS DISAGREEMENT` appears nowhere in its log
    or its tasks.

    So they move to the channel #799 already established for exactly this -- "two more entries
    in this table told the lane to go and find something the framework already computes".
    """
    try:
        from .delivery_gate import (_contract_materials_disagreement_1202ky,
                                    _contract_denial_contradictions_1202kr,
                                    _failing_surface_1202lb)
        hubs = getattr(orch, "hubs", None)
        rh = getattr(hubs, "registryhub", None)
        if rh is None:
            return ""
        chains = rh.get_verification_chains() or {}
        authored = [v for k, v in chains.items()
                    if k != "_meta" and isinstance(v, dict)]
        if not authored:
            return ""
        parts = []
        for _fn in (_contract_denial_contradictions_1202kr,
                    _contract_materials_disagreement_1202ky):
            try:
                parts.append(_fn(rh, authored, hubs) or "")
            except Exception:
                pass
        try:
            parts.append(_failing_surface_1202lb(authored) or "")
        except Exception:
            pass
        body = "".join(p for p in parts if p).strip()
        return ("\n\n" + body) if body else ""
    except Exception as _e1202ld:
        from .message_format import warn_once_1201
        warn_once_1201("remediation_dispatcher.contract_surface_1202ld",
                       "the contract/materials and shared-endpoint annotations do not reach "
                       "the business_chain_failing task, so the lane sees the generic text only",
                       _e1202ld)
        return ""


# --- #1202ss: the gate-repair task TITLE names the failing INSTANCE ------------------
# Every branch below spends real effort computing WHICH chain / page / flow / endpoint
# failed, and puts it in the task BODY. The TITLE stayed the check's category name, and
# the title is what the lane, the workhub listing and `#794`'s de-duplication all read
# first. Measured over the 36 runs since `#1202gz` collapsed same-title remediation:
# `Make business_chain pass (blocks delivery)` hid 126 distinct instances across 22 runs,
# `Re-verify the failing UI evidence records (blocks delivery)` 53 across 20. `#1202sr`
# fixed the breaking-change title one row at a time; this does the whole table at the one
# site that files the task, so a check nobody has hit yet is covered too.
_TITLE_INSTANCE_CAP_1202SS = 3


def _instance_name_1202ss(item: Any) -> str:
    """The INSTANCE name at the head of one remediation detail line, or '' (#1202ss).

    Deliberately refuses anything that does not LOOK like a name: the same `_extra` lists
    also carry `#811`'s "… and N more" continuation and, for some checks, whole sentences
    of prose. A title reading `Make business_chain pass: frontend calls an authed API via`
    is worse than the generic one, so an unrecognised head yields '' and the title is left
    alone.
    """
    if item is None:
        return ""                       # `str(None)` would title the task "None"
    s = " ".join(str(item).split())
    if not s or s.startswith(("\u2026", "...", "\u26a0")):
        return ""
    s = s.split(" -> ", 1)[0].strip()   # `<chain> -> step '...': GET /x returned 422`
    if not s or len(s) > 48 or len(s.split(" ")) > 2:
        return ""
    return s


def _instanced_gate_title_1202ss(base_title: str, instances: Optional[Sequence[Any]]) -> str:
    """``base_title`` with the failing instances appended, or unchanged (#1202ss).

    The base title is kept as a PREFIX: `_gate_still_fails_on_1202pg` (workhub) matches it
    by substring, and `#794`'s open-task lookup matches it by prefix — both keep working.
    """
    names: List[str] = []
    for it in (instances or ()):
        n = _instance_name_1202ss(it)
        if n and n not in names:
            names.append(n)
    if not names:
        return base_title
    return "%s: %s" % (base_title, join_capped(names, cap=_TITLE_INSTANCE_CAP_1202SS, sep=", "))


def _ui_flow_records_1202su(orch) -> List[tuple]:
    """Every ui_flow evidence record this run, as ``(flow_name, status)`` (#1202su).

    Same accessor `_ui_evidence_failed_pages` uses — `#1178` proved the getattr-guessed
    alternatives are dead on the real orchestrator."""
    try:
        _results = None
        _getter = getattr(orch, "_get_validation_results", None)
        if callable(_getter):
            _results = _getter(limit=9999)
        if not _results:
            _results = (getattr(orch, "_last_validation_results", None)
                        or getattr(orch, "_validation_results", None))
        out: List[tuple] = []
        for r in (_results or []):
            if not isinstance(r, Mapping):
                continue
            name = str(r.get("name") or r.get("task_id") or "")
            kind = str((r.get("metadata") or {}).get("check") or "")
            if kind != "ui_flow" and ":ui_flow:" not in name:
                continue
            out.append((name.rsplit(":", 1)[-1], str(r.get("status") or "").strip().lower()))
        return out
    except Exception as _exc_1202su:
        _swallowed_1152("_ui_flow_records_1202su", _exc_1202su,
                        "[] = the name-keyed note is omitted")
        return []


def name_keyed_supersede_1202su(orch, failing: Sequence[Any]) -> str:
    """#1202su: say that the evidence store is keyed by the record NAME, or '' .

    `_ui_evidence_breadth_739` keeps the LATEST record per name (`#757`) and only then asks
    whether any is failing, so a failing record is retired by a later record **with the same
    name** — not by a passing walk of the same page under a different one. The remediation
    said "re-run the walk (run_validation)", which is what the verifier does; it then records
    the result under whatever name that walk used, and the failing key is never revisited.

    Measured over the 40 most recent corpus runs (`shared/hubs/codehub_checks.json` +
    `registryhub_ui_pages.json`):
      * 66 failing `validation:ui_flow:*` records in 24 runs; **27 of them (40%) name a flow
        that is not a declared ui_page**, so no walk will ever produce that name again;
      * in **15 of those 24 runs** a ui_flow PASS was recorded AFTER the failure under a
        DIFFERENT name and the failure still stood (r130: 12 passes, the newest 52 s after
        the failure; googlemaps-r16: 11 stuck records; gmrun4 shipped 4 milestones with one);
      * **62 of 66 (93%) carry no `metadata.url`**, which is why `#1202fq`'s route-keyed
        supersede — written for exactly this latch — cannot match them either.
    Three domains (tiktok / netflix / googlemaps), so this is not env-specific.

    Says only what the framework already knows; `''` when there is nothing to say."""
    try:
        names = [str(f).strip() for f in (failing or []) if str(f).strip()]
        if not names:
            return ""
        recs = _ui_flow_records_1202su(orch)
        passed = [n for n, st in recs if st in ("passed", "success", "pass")]
        if not passed:
            return ""
        other = [n for n in dict.fromkeys(passed) if n not in names]
        if not other:
            return ""
        return (
            "\n\n\u2605 THE RECORD IS KEYED BY ITS NAME. `validation:ui_flow:<name>` is "
            "last-write-wins, and the gate keeps only the NEWEST record per name — so %s "
            "stay(s) the newest word on their own key until a record with the SAME name says "
            "otherwise. This run has already recorded %d passing ui_flow record(s) under "
            "OTHER names (%s), and none of them retires the failure(s) above. Re-walk the "
            "named flow and record the result under the SAME name: "
            "codehub_record_check(pr_id='main', name='validation:ui_flow:%s', "
            "status='success', evidence={'metadata': {'check': 'ui_flow', 'flow': '%s', "
            "'url': '<the page URL you walked>'}, ...}). Include that `url` — it is what "
            "lets the gate supersede the record by ROUTE when the next walk names the flow "
            "differently."
            % (join_capped(names, cap=3, sep=", "), len(set(other)),
               join_capped(sorted(set(other)), cap=4, sep=", "), names[0], names[0]))
    except Exception as _exc_su:
        _swallowed_1152("name_keyed_supersede_1202su", _exc_su,
                        "'' = the generic remediation text stands")
        return ""


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
        # #1135: which PASSING chains already exercise the same endpoint? The registry holds
        # this and the task never said it. netflix-local-r2 had 3 failing chains and 2 of them
        # had passing siblings on the exact endpoint their broken step failed on --
        # `continue-watching_page` broke on `POST /api/continue-watching` while
        # `continue_watching_page_basic` passed on it, and `titles_page` broke on
        # `POST /api/titles/1/rating` with THREE passing chains over it. That comparison is
        # the difference between "the app is broken" and "my step's inputs are wrong", and it
        # decided r2: the app answered `{"detail":"profile_id does not belong to the caller"}`
        # -- correct tenant isolation -- to a step that posted another user's profile_id. The
        # verifier held that blocker for 79 minutes and the run aborted on it.
        _pass_idx = _passing_endpoint_index_1135(chains)
        out: List[str] = []
        for name, rec in (chains.items() if isinstance(chains, dict) else []):
            if name == "_meta" or not isinstance(rec, dict):
                continue
            lr = rec.get("last_result") or {}
            for st in (lr.get("steps") or []):
                if not _step_is_actionable_1202gx(st):   # #1202gx
                    continue
                got = st.get("status")
                exp = st.get("expect")
                note = str(st.get("note") or "").strip()
                _sib = [c for c in _pass_idx.get(
                    _canon_endpoint_1135(st.get("method"), st.get("path")), ()) if c != name]
                _sib_txt = ""
                if _sib:
                    _sib_txt = (
                        " ⚠ #1135: %s ALREADY PASS on this same endpoint (%s) — the endpoint "
                        "works, so compare THEIR step inputs against yours before touching the "
                        "backend." % (", ".join(sorted(_sib)[:3]),
                                      _canon_endpoint_1135(st.get("method"), st.get("path"))))
                out.append(
                    "%s -> step %r: %s %s returned %s, expected %s%s%s" % (
                        name, str(st.get("action") or "?"),
                        str(st.get("method") or "?"), str(st.get("path") or "?"),
                        got if got is not None else "no response",
                        exp if exp else "a 2xx",
                        (" — " + note[:160]) if note else "", _sib_txt))
            if not (lr.get("steps") or []):
                for b in (lr.get("broken") or []):
                    out.append("%s -> broken: %s" % (name, str(b)[:200]))
        # #811: say what was dropped. #798 exists because the task told the verifier to go and
        # look up something already written down; a silent cap re-creates that in miniature --
        # the verifier fixes 8 steps, re-runs, and the chain is still red for reasons the task
        # never mentioned. #680's rule ("no silent caps") applied to my own fix from two items
        # ago; the codebase already uses this exact idiom in bare_authed_fetch_blockers.
        if len(out) > 8:
            return out[:8] + ["… and %d more broken step(s) — the same reading applies to each; "
                              "this list is capped to keep the task readable" % (len(out) - 8)]
        return out
    except Exception as _exc_1152:
        _swallowed_1152("_chain_broken_detail_798", _exc_1152, "[] = nothing to remediate")
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
    except Exception as _exc_1152:
        _swallowed_1152("_ui_flow_missing_names", _exc_1152, "[] = nothing to remediate")
        return []


def _ui_evidence_failed_pages(orch) -> List[str]:
    """#982: the PAGES whose UI evidence records say failure.

    `_ui_evidence_breadth_739` already returns `pages_failed` beside the count the gate
    trips on, and #757 added those names for exactly this reason — its comment reads "a gate
    that cannot say WHICH page failed cannot be acted on". The gate computes them; the
    dispatcher had no branch for `validation_ui_evidence_failed` at all, so the verifier got
    generic text. r159 died on this check and its sibling, with both name lists sitting
    computed and unused.

    Best-effort -> [] falls back to the generic body."""
    try:
        _b = globals().get("_ui_evidence_breadth_739")
        if _b is None:
            from .delivery_gate import _ui_evidence_breadth_739 as _b
        # #1178: THIS PRODUCER READ TWO ATTRIBUTES THAT DO NOT EXIST.
        #
        # `_last_validation_results` and `_validation_results` are not on the orchestrator
        # -- it exposes the METHOD `_get_validation_results(limit=...)`, which is what the
        # gate's own consumer calls (orchestrator.py:1117) and whose docstring says "the two
        # readers must agree". Both getattr calls returned None, `_b(None)` reported nothing
        # failing, and this function returned [] on every call since #982 landed.
        #
        # So the ENTIRE named-pages remediation was dead: #982's page list, #1043's
        # auth-root hint, and (as shipped) #1176 and #1177 all hang off this list being
        # non-empty. The dispatcher fell through to the 789-character generic body every
        # time. r17 shows it on both sides of a resume -- task_fa4adc4f11 (original run) and
        # task_f2496728f6 (resume) are both exactly 789 chars, while the gate one line above
        # printed "#1017 validation_ui_evidence_failed on 1 record(s), 1 named page(s):
        # landing_page". The gate could name it; the lane was never told.
        #
        # This is the #1040 shape one layer down: a fix that exists and cannot be reached.
        _results = None
        _getter = getattr(orch, "_get_validation_results", None)
        if callable(_getter):
            _results = _getter(limit=9999)
        if not _results:
            _results = (getattr(orch, "_last_validation_results", None)
                        or getattr(orch, "_validation_results", None))
        report = _b(_results)
        return [str(x) for x in (report or {}).get("pages_failed") or [] if str(x) and str(x) != "?"]
    except Exception as _exc_1152:
        _swallowed_1152("_ui_evidence_failed_pages", _exc_1152, "[] = nothing to remediate")
        return []


# #1043: flows whose NAME says they are the authentication step every other flow depends on.
# Deliberately a small, literal set — a fuzzy match ("anything containing 'log'") would catch
# `login_to_profile_to_browse`, which is a DOWNSTREAM flow, and invert the advice.
_AUTH_ROOT_FLOWS_1043 = frozenset({
    "login", "log_in", "signin", "sign_in", "signup", "sign_up", "register", "auth",
})


def auth_root_among_1043(pages) -> List[str]:
    """The failing flows that ARE the auth step, not merely flows that need auth."""
    out = []
    for p in (pages or []):
        if str(p).strip().lower().replace("-", "_") in _AUTH_ROOT_FLOWS_1043:
            out.append(str(p))
    return out


def _ui_evidence_failed_extra(pages: Sequence[Any]) -> str:
    """#982: name the pages. Mirrors _ui_flow_failed_extra; same reason, other check."""
    # #1043: coerce, as defence in depth. `"\n- ".join(pages)` raises TypeError on a non-str
    # entry; checked, and all three producers (`_ui_evidence_failed_pages`,
    # `_ui_flow_failed_names`, `_ui_flow_missing_names`) already `str()` their output, so this
    # is LATENT rather than a live defect — worth saying plainly instead of overstating it.
    # It is guarded anyway because the consequence is invisible: the raise would be swallowed
    # by the dispatcher's try/except and the lane would quietly receive the GENERIC
    # remediation, which is the exact bug #982 set out to fix, wearing its own fix's face.
    pages = [str(p) for p in (pages or []) if str(p).strip()]
    if not pages:
        return ""
    # #1043: in BOTH runs where this blocker was terminal, the failing set had ONE upstream
    # cause and the rest were downstream of it — r174: six flows, all failing on a single
    # `GET /api/profiles` 401; r175: nine flows where `login` itself failed and the other
    # eight (profile_switch, my_list_add_remove, rating, search, sign_out, detail_to_play,
    # genre_navigation, login_to_profile_to_browse) all require being logged in. A lane handed
    # nine equal-looking items will work them as nine; naming the root turns it into one.
    _root = auth_root_among_1043(pages)
    _hint = ""
    if _root and len(pages) > len(_root):
        _hint = (
            "\n\n★ START WITH `%s`. It is the AUTHENTICATION flow and the other %d failing "
            "flow(s) all run after it, so they are very likely the same defect reported %d "
            "times — fix it first, re-run the walk, and re-read this list before treating the "
            "rest as separate work."
            % ("`, `".join(_root), len(pages) - len(_root), len(pages)))
    return ("\n\nTHE PAGE(S) WHOSE UI EVIDENCE RECORDS FAILURE:\n- " + "\n- ".join(pages) +
            _hint +
            "\n\nThe record exists and says the page is broken, so re-recording it is not "
            "the fix: open each page, reproduce what the record reports, repair it, then "
            "re-run the walk so the record flips."
            "\n\n★ A record can also be STALE: it keeps saying FAILED until a walk overwrites "
            "it, so a flow repaired after the record was written still blocks the gate. r174 "
            "lost 80 minutes to exactly that — all six of its failing records described a "
            "defect that was already fixed (the endpoint returned 200 when probed live). If "
            "the page works when you open it, re-run the walk and move on.")


# ---- #1176 -----------------------------------------------------------------
# r17 (live, 2026-08-30) spent 20 minutes and ~$80 on a loop that could not
# converge, while the framework held both halves of the answer the whole time.
#
# The landing page sits at route "/" and App.jsx -- which the framework
# scaffolds -- leaves it OUTSIDE every auth guard, so the walk opens it logged
# out. The backend lane registered the whole catalogue with
# `metadata.auth_required=True`, and `resolve_endpoint_auth` honours an explicit
# statement over its own (correct) shape default for a public GET, so
# /api/titles/top10 projected with `Depends(get_current_user)`. Two artifacts,
# each self-consistent, and a guaranteed 401 where they meet:
#
#     validation:ui_smoke:landing_page  FAILED
#       "Landing page loaded but emitted GET /api/titles/top10 401 Unauthorized"
#
# The dispatch was already right ("a 4xx from the API is BACKEND") and the
# backend lane did act: it re-registered /api/titles, /api/titles/top10 and
# /api/titles/trending again and again. Every one of those calls re-sent
# `status=implemented` and none touched `auth_required`, which read True before
# the loop and True after it. The lane could reach the lever. Nothing told it
# the lever was there -- so it re-asserted the state it was already in, which
# is what a lane does when the evidence names a symptom and no cause.
#
# WHY THE PUBLIC-ROUTE TEST IS NOT OPTIONAL: without it this text would say
# "make the endpoint public" about a page that is SUPPOSED to be authenticated
# and merely failed to log in -- repairing a red gate by deleting an auth
# boundary. That is #1158's mistake (a fail-open that turned another user's 403
# into a 201) handed over as remediation. So the lever is named only when
# App.jsx itself put the route outside every guard, and even then BOTH legal
# repairs are named -- publish the endpoint, or protect the page -- because
# which one is correct is a question about the product, not about the gate.
#
# It reads files that exist only when the gate has ALREADY failed, and adds
# prose to an existing remediation. A miss costs the old generic text.

# Deliberately NARROWER than frontend_audit's `_ROUTE_WRAPPERS`: that set also
# carries Layout / Suspense / ErrorBoundary, which wrap a route without saying
# anything about auth. Counting `<Layout>` as a guard would silence this
# diagnosis on every app that wraps its pages in a shell -- that is, most.
_AUTH_GUARD_IDENTS_1176 = frozenset({
    "protectedroute", "privateroute", "requireauth", "requireadmin", "authguard",
    "routeguard", "guard", "authroute", "protected", "requiresession", "authonly",
})

# "... emitted GET /api/titles/top10 401 Unauthorized" and the inverted phrasing
# a different verifier turn produces ("401 on GET /api/titles/top10").
_M4XX_A_1176 = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s\"'<>,;)\]]+)\D{0,24}?(401|403)\b")
_M4XX_B_1176 = re.compile(
    r"\b(401|403)\b\D{0,24}?(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s\"'<>,;)\]]+)")


def _norm_path_1176(path: str) -> str:
    """`/api/titles/5` -> `/api/titles/{id}` so a probed URL matches its contract row."""
    out = []
    for seg in str(path or "").split("?")[0].split("/"):
        out.append("{id}" if seg.isdigit() else seg)
    return "/".join(out).rstrip("/") or "/"


def _hub_json_1176(root, filename: str):
    """Best-effort read of one hub file -> {} when absent/unreadable."""
    import json as _json
    try:
        p = Path(root) / "shared" / "hubs" / filename
        if not p.is_file():
            return {}
        return _json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as _exc:
        _swallowed_1152("_hub_json_1176(%s)" % filename, _exc, "{} = no diagnosis")
        return {}


def _walk_records_1176(obj, want):
    """Yield every dict in a hub blob for which `want(d)` is true (shape-agnostic:
    the hubs nest records differently per file and per framework version)."""
    stack = [obj]
    seen = 0
    while stack and seen < 200000:
        cur = stack.pop()
        seen += 1
        if isinstance(cur, dict):
            try:
                if want(cur):
                    yield cur
            except Exception:
                pass
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _route_is_public_1176(app_jsx: str, route: str) -> Optional[bool]:
    """True when App.jsx declares `route` outside every auth guard, False when a
    guard wraps it, None when the route is not found (say nothing rather than guess).

    The span is cut at the NEXT route landmark, never at a fixed byte offset: a
    `<Route>` element carrying a guard plus a lazy import runs well past any
    constant window, and a window that ends early reads as "no guard" -- the exact
    direction that would produce the fail-open advice this helper exists to avoid.
    """
    if not app_jsx or not route:
        return None
    m = re.search(r"<Route\b[^>]*?\bpath\s*=\s*[\"'{]\s*%s\s*[\"'}]" % re.escape(route), app_jsx)
    if m is None:
        return None
    tail = app_jsx[m.start():]
    # Landmark: the next route declaration, or the end of the route table.
    ends = [i for i in (tail.find("<Route", 6), tail.find("</Routes>")) if i > 0]
    span = tail[:min(ends)] if ends else tail
    low = span.lower()
    return not any(("<" + g) in low or (g + " ") in low for g in _AUTH_GUARD_IDENTS_1176)


def auth_contradiction_1176(orch, pages: Sequence[Any]) -> str:
    """Name the contract switch behind a 401/403 on a page that is public by construction."""
    try:
        root = getattr(orch, "output_dir", None)
        if not root:
            return ""
        wanted = {str(p).strip() for p in (pages or []) if str(p).strip()}
        if not wanted:
            return ""

        # 1. The failing UI records for those pages, and the 4xx they name.
        checks = _hub_json_1176(root, "codehub_checks.json")
        hits = {}          # (METHOD, normpath) -> page
        for rec in _walk_records_1176(
                checks,
                lambda d: str(d.get("status", "")).lower() in ("failure", "failed")
                and str(d.get("name", "")).startswith("validation:ui")):
            name = str(rec.get("name", ""))
            page = name.rsplit(":", 1)[-1]
            if page not in wanted:
                continue
            blob = " ".join(str(v) for v in (rec.get("evidence") or {}).values())[:8000]
            for mm in _M4XX_A_1176.finditer(blob):
                hits.setdefault((mm.group(1).upper(), _norm_path_1176(mm.group(2))), page)
            for mm in _M4XX_B_1176.finditer(blob):
                hits.setdefault((mm.group(2).upper(), _norm_path_1176(mm.group(3))), page)
        if not hits:
            return ""

        # 2. What the CONTRACT says about each of those endpoints.
        eps = _hub_json_1176(root, "registryhub_endpoints.json")
        authed = {}
        for rec in _walk_records_1176(eps, lambda d: "path" in d and "method" in d):
            stated = rec.get("auth_required")
            if stated is None:
                # #1202gr: `schema` is what the LANE writes and #1202ga made it win; this
                # reader skipped straight from the top level to the `metadata` mirror, so a
                # lane that had already made the endpoint public still read as authed here.
                _sch = rec.get("schema")
                if isinstance(_sch, Mapping):
                    stated = _sch.get("auth_required")
            if stated is None:
                stated = (rec.get("metadata") or {}).get("auth_required")
            if stated is None:
                continue
            authed[(str(rec.get("method", "")).upper(),
                    _norm_path_1176(rec.get("path")))] = bool(stated)

        # 3. Which route each failing page occupies, and whether App.jsx guards it.
        routes = {}
        for rec in _walk_records_1176(
                _hub_json_1176(root, "registryhub_ui_pages.json"),
                lambda d: d.get("name") and d.get("route")):
            routes.setdefault(str(rec["name"]), str(rec["route"]))
        try:
            app_jsx = (Path(root) / "app" / "frontend" / "src" / "App.jsx").read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            app_jsx = ""

        lines = []
        for (method, path), page in sorted(hits.items()):
            if not authed.get((method, path)):
                continue                       # contract does not demand the token
            if _route_is_public_1176(app_jsx, routes.get(page, "")) is not True:
                continue                       # page is guarded (or unknown) -> stay quiet
            lines.append("- `%s %s` is registered with auth_required=True, and `%s` "
                         "renders at route `%s`, which App.jsx leaves outside every auth "
                         "guard. Logged out, that call can only ever be %s."
                         % (method, path, page, routes.get(page, "?"), "401/403"))
        if not lines:
            return ""
        return (
            "\n\n★ THE CONTRACT, NOT THE HANDLER, IS WHAT REQUIRES THE TOKEN HERE:\n"
            # join_capped declares the cut instead of hiding it (#1034's rule).
            + join_capped(lines, len(lines), cap=6, sep="\n") +
            "\n\nThe handler is PROJECTED from that registration: `resolve_endpoint_auth` "
            "treats an explicit `auth_required` as final, so the projector wrote "
            "`Depends(get_current_user)` because the contract asked it to. Editing the "
            "projected handler in main.py CANNOT fix this -- the next projection rewrites "
            "it -- and re-registering the endpoint with the same metadata changes nothing "
            "(r17 did exactly that, repeatedly, and the flag read True before and after).\n"
            "Pick ONE, by what the product means:\n"
            "  (a) the data is public -> registryhub_register_endpoint the SAME method+path "
            "with metadata.auth_required=False, then re-project and re-run the walk; or\n"
            "  (b) the data is private -> the page must not render logged out: put its route "
            "behind the app's auth guard in App.jsx, or stop it fetching this endpoint "
            "before login.\n"
            "Do NOT publish an endpoint merely to turn the gate green -- a read that leaks "
            "another user's rows is a worse defect than the one you are clearing.")
    except Exception as _exc_1176:
        _swallowed_1152("auth_contradiction_1176", _exc_1176, "'' = generic remediation")
        return ""


# ---- #1177 -----------------------------------------------------------------
# THE MOST COMMON TERMINAL BLOCKER IS A DEADLOCK THE REMEDIATION TEXT CREATES.
#
# `validation_ui_evidence_failed` is "7 of the last 10 declining runs" (#1040) and the
# gate's own note records it as "the ONLY failing check for 85 minutes". r17 (live,
# 2026-08-30) is the same shape, and the cause is three framework statements that cannot
# all be satisfied at once:
#
#   1. `_ui_evidence_breadth_739` pools EVERY failing UI record -- `ui_flow:*` and
#      `ui_smoke:*` alike -- and one failing entry blocks delivery.
#   2. The remediation for the check says: "re-run the walk (run_validation) so the record
#      is rewritten from the CURRENT app ... Do NOT close the gate item by editing the
#      record -- only a fresh walk counts."
#   3. `validation_tools` says, in its own words: "ui_smoke stays the verifier's browser
#      job -- run_validation is api-only and does not probe the UI."
#
# So for a failing `ui_smoke:*` record the prescribed action CANNOT rewrite it, and the
# only action that can is the one the text forbids. r17 ran the prescription and it
# behaved exactly as (3) says:
#
#   03:10:14  verifier records validation:ui_smoke:landing_page = failure   (by hand)
#   03:27:23  "Verification UI evidence re-check complete ... run_validation passed"
#   03:28:01  #1017 validation_ui_evidence_failed on 1 record(s): landing_page
#
# The record still carries its 03:10:14 timestamp. Meanwhile the page's defect was
# genuinely repaired at ~03:20 (the frontend lane removed the landing page's fetch of an
# authed endpoint -- LandingPage.jsx is a 49-line marketing page with no API call), and
# `validation:ui_flow:landing_page` PASSES. The app is fine; the ledger cannot say so.
#
# Worth stating plainly: these per-page ui_smoke records are VOLUNTEERED. r14 delivered
# with zero of them and r13 with a single global `validation:ui_smoke`. A verifier that
# offers extra evidence should not thereby manufacture an unclearable blocker.
#
# The repair is to make the instruction true rather than to weaken the gate. For a
# `ui_smoke` record the verifier's own fresh browser observation IS the walk -- that is
# what (3) means -- so re-recording it FROM A NEW OBSERVATION is the legitimate refresh,
# not the forbidden edit. The prohibition still holds for what it was written about:
# closing an item without re-observing anything.

_UI_SMOKE_PREFIX_1177 = "validation:ui_smoke"


def ui_smoke_refresh_1177(orch, pages: Sequence[Any]) -> str:
    """Correct the refresh instruction for failing records `run_validation` cannot rewrite."""
    try:
        root = getattr(orch, "output_dir", None)
        if not root:
            return ""
        wanted = {str(p).strip() for p in (pages or []) if str(p).strip()}
        if not wanted:
            return ""
        stuck = []
        for rec in _walk_records_1176(
                _hub_json_1176(root, "codehub_checks.json"),
                lambda d: str(d.get("status", "")).lower() in ("failure", "failed")
                and str(d.get("name", "")).startswith(_UI_SMOKE_PREFIX_1177)):
            name = str(rec.get("name", ""))
            if name.rsplit(":", 1)[-1] in wanted and name not in stuck:
                stuck.append(name)
        if not stuck:
            return ""
        return (
            "\n\n★ THESE RECORDS CANNOT BE REWRITTEN BY `run_validation`:\n- "
            + join_capped(sorted(stuck), len(stuck), cap=6, sep="\n- ") +
            "\n\n`run_validation` is API-ONLY — it probes endpoints and records "
            "contract_tests, api_smoke, builds and a RunHub run. It does not drive a "
            "browser, so it never touches a `ui_smoke` record. Re-running it leaves the "
            "failing record at its original timestamp, the gate re-reads the same failure, "
            "and the loop repeats with nothing changed (r17 spent 18 minutes doing exactly "
            "this while the underlying page defect was already repaired).\n"
            "For a `ui_smoke` record YOUR OWN BROWSER OBSERVATION IS THE WALK. So:\n"
            "  1. Open the page in the browser and reproduce what the record claims.\n"
            "  2. If the defect is still there, fix it (or bug_create for the owning lane) "
            "and look again.\n"
            "  3. Once the page is clean IN FRONT OF YOU, codehub_record_check the SAME "
            "check name from that fresh observation, with the evidence you just saw.\n"
            "Step 3 is a re-observation, not a record edit. The 'only a fresh walk counts' "
            "rule above is about `ui_flow` records, which the framework's OWN authenticated "
            "DOM walk rewrites deterministically (#240/#254 — a measured pass outranks an "
            "LLM report of the same flow). No such writer exists for `ui_smoke`: yours is "
            "the only walk it has, which is why re-recording it from a fresh look is the "
            "refresh rather than an edit. What remains forbidden is flipping a check green "
            "without looking at the page: if you cannot state what you observed, the record "
            "stays red.")
    except Exception as _exc_1177:
        _swallowed_1152("ui_smoke_refresh_1177", _exc_1177, "'' = generic remediation")
        return ""


# ---- #1182 -----------------------------------------------------------------
# "THE CONTROL IS NOT THERE" — SAID ABOUT A CONTROL THAT IS THERE AND WORKS.
#
# Twice now a run has been ended by a walk that could not FIND a control, on a page whose
# source declares it and whose flow works when driven by hand:
#
#   r17  ui_flow:signup  "input[name='email'] was not present/interactable; page exposed
#                         app-shell controls instead of signup form."
#        -> the form was complete; the inputs simply carried no `name` (fixed at source
#           by #1179b). Driving it in a real browser: register 201, navigation, no errors.
#
#   r19  ui_flow:search_discovery  "authenticated /search page loaded but no interactable
#                         search/text input exists, so the flow cannot be exercised."
#        -> SearchPage.jsx declares
#             <input className="field" type="search" name="q" placeholder="Search titles,
#                    people, genres" autoFocus aria-label="Search"/>
#           — interactable, labelled, and focused on mount. A probe written as
#           `input[type=text]` misses `type="search"`; nothing about the app is wrong.
#           r19 aborted STUCK on this single record after 18 coordination ticks, at $355.
#
# The framework can settle this without judgement: it HAS the page source. When a failing
# record claims a control is absent, resolve the route it names to the component App.jsx
# renders there, read that file, and — if controls exist — put them in the remediation with
# the attributes needed to select them.
#
# It never contradicts a real defect: the text is emitted only when the file genuinely
# declares a control, and it prescribes RE-LOCATING, not closing the item. A page that
# really has no input yields nothing extra and the generic remediation stands.
#
# Deliberately NOT a gate discount. #739 made failing UI records block for good reasons and
# a record asserting a missing control may yet be right about something (a control rendered
# only after a state the walk never reached). What was missing was the source of truth, not
# the blocking.

# Phrasings a verifier uses when it cannot find a control. Kept literal and narrow: a fuzzy
# match would fire on "no results match your search", which is an app STATE, not a missing
# control, and the advice would then be nonsense.
_ABSENT_1182 = (
    "no interactable", "not present/interactable", "was not present", "not interactable",
    "no search/text input", "could not find", "no input", "does not exist",
)

# A route mentioned in prose ("/search page loaded but ..."). `/api/...` is excluded: the
# record's network errors name endpoints, and an endpoint is not a page route.
_ROUTE_1182 = re.compile(r"(?<![\w/])(/[a-z][a-z0-9/_-]*)")


def _control_tags_1182(page: str):
    """Whole `<input>` / `<textarea>` / `<select>` tags, brace-aware.

    A naive `<input\b[^>]*` stops at the FIRST `>`, and in JSX that is usually inside a
    handler: `onChange={(e)=>setQuery(e.target.value)}`. On r19's SearchPage that truncated
    the tag before `placeholder` and `aria-label` -- losing exactly the attribute a walk
    should be told to select by. So scan to the `>` that closes the tag at brace depth 0.
    """
    out, i, n = [], 0, len(page)
    while len(out) < 24:
        m = re.compile(r"<(?:input|textarea|select)\b").search(page, i)
        if not m:
            break
        j, depth = m.end(), 0
        while j < n:
            c = page[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)
            elif c == ">" and depth == 0:
                break
            j += 1
        out.append(page[m.start():j])
        i = j + 1
    return out


def _controls_from_1182(src: str):
    """The selectable attributes of every control a source file declares."""
    out = []
    for tag in _control_tags_1182(src)[:8]:
        attrs = dict(re.findall(r'([\w-]+)\s*=\s*["\{]([^"\}]{0,40})', tag))
        kept = {k: attrs[k] for k in ("type", "name", "id", "placeholder", "aria-label")
                if k in attrs}
        if kept:
            out.append(kept)
    return out


def _delegated_controls_1202bx(src_dir, page: str):
    """(component, controls) for a control the page RENDERS but does not DECLARE.

    #1182 resolves a route to its page file and reads the controls there. That is blind
    exactly when the page delegates its form to a child -- `SearchPage.jsx` renders
    `<SearchBox/>` and the `<input>` lives in `components/SearchBox.jsx` -- so the diagnosis
    came back empty and the generic remediation stood. Measured over the corpus: 222 of the
    1117 pages that declare no control of their own do render one from a local component,
    across several environments. r35 died on precisely this (delivery gate, ui_flow:search,
    $174) and r19 before it ($355, STUCK after 18 ticks), both times on an app whose input
    was present, labelled and correct.

    The pressure is increasing, not decreasing: #1202at tells lanes to break pages into
    components, so the shape this misses is the shape the framework now asks for.

    One level deep and capped: enough for a page that hands its form to a child, without
    walking a component graph. The child's OWN name is returned because the caller prints
    "<name>.jsx declares N" -- naming the page there would be false.
    """
    seen = 0
    for _, cname in re.findall(
            r"import\s+(\w+)\s+from\s+['\"][^'\"]*?/?(?:components)/(\w+)", page):
        if seen >= 12:
            break
        seen += 1
        f = Path(src_dir) / "components" / f"{cname}.jsx"
        if not f.is_file():
            continue
        try:
            ctrls = _controls_from_1182(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if ctrls:
            return cname, ctrls
    return None, []


def _page_controls_1182(root, route: str):
    """(component, [control-attrs]) for the page App.jsx renders at `route`, or (None, [])."""
    try:
        src_dir = Path(root) / "app" / "frontend" / "src"
        app = (src_dir / "App.jsx").read_text(encoding="utf-8", errors="replace")
        m = re.search(
            r'<Route\b[^>]*?\bpath\s*=\s*["\']%s["\'][^>]*?element=\{(.{0,240}?)\}\s*/?>'
            % re.escape(route), app, re.S)
        if not m:
            return None, []
        # Pick the component that HAS a page file rather than filtering a guard vocabulary:
        # r19's guard is `<Authed>`, which no such list contained, and the first prototype
        # resolved /search to "Authed" and found nothing.
        comp = next((n for n in re.findall(r"<([A-Z][A-Za-z0-9_]*)", m.group(1))
                     if (src_dir / "pages" / f"{n}.jsx").is_file()), None)
        if not comp:
            return None, []
        page = (src_dir / "pages" / f"{comp}.jsx").read_text(encoding="utf-8", errors="replace")
        out = _controls_from_1182(page)
        if out:
            return comp, out
        # #1202bx: the page renders its control from a local component instead of
        # declaring it. Report the CHILD, because the caller names this file as the
        # declaring one.
        child, ctrls = _delegated_controls_1202bx(src_dir, page)
        if ctrls:
            return child, ctrls
        return comp, []
    except Exception as _exc:
        _swallowed_1152("_page_controls_1182", _exc, "(None, []) = no diagnosis")
        return None, []


def control_absence_contradicted_1182(orch, pages) -> str:
    """Answer a record that says a control is missing with the markup that declares it."""
    try:
        root = getattr(orch, "output_dir", None)
        if not root:
            return ""
        wanted = {str(p).strip() for p in (pages or []) if str(p).strip()}
        if not wanted:
            return ""
        lines = []
        for rec in _walk_records_1176(
                _hub_json_1176(root, "codehub_checks.json"),
                lambda d: str(d.get("status", "")).lower() in ("failure", "failed")
                and str(d.get("name", "")).startswith("validation:ui")):
            name = str(rec.get("name", ""))
            if name.rsplit(":", 1)[-1] not in wanted:
                continue
            summary = str((rec.get("evidence") or {}).get("summary") or "")
            low = summary.lower()
            if not any(p in low for p in _ABSENT_1182):
                continue
            for route in _ROUTE_1182.findall(summary):
                if route.startswith("/api") or len(route) < 2:
                    continue
                comp, ctrls = _page_controls_1182(root, route)
                if not ctrls:
                    continue
                # join_capped, not `[:4]`: printing the COUNT beside a silently
                # truncated list is the shape #1034's ratchet exists to catch.
                _shown = [" ".join(f'{k}="{v}"' for k, v in c.items()) for c in ctrls]
                lines.append(
                    "- `%s` says a control is missing at `%s`. %s.jsx declares %d: %s"
                    % (name, route, comp, len(ctrls),
                       join_capped(_shown, len(_shown), cap=4)))
                break
        if not lines:
            return ""
        return (
            "\n\n★ THE PAGE'S SOURCE DECLARES THE CONTROL THIS RECORD CALLS MISSING:\n"
            + join_capped(lines, len(lines), cap=4, sep="\n") +
            "\n\nSo 'not present' is about the SELECTOR, not the app. r19 ended STUCK at $355 "
            "on one such record: the walk reported no search input while SearchPage.jsx had "
            "`<input type=\"search\" name=\"q\" aria-label=\"Search\" autoFocus>` — a probe "
            "written as `input[type=text]` does not match `type=\"search\"`.\n"
            "Re-locate it before concluding anything: prefer the ACCESSIBLE ROLE "
            "(getByRole('textbox'/'searchbox'/'button', {name: ...})), then the aria-label, "
            "then the name= shown above; when you match on `type`, accept text/search/email/"
            "tel/url, not text alone. Then re-run the flow.\n"
            "If the control genuinely does not render — it may appear only after a state your "
            "walk did not reach — say which step you performed and what the page showed, and "
            "bug_create for frontend with that. The record stays red until the flow runs.")
    except Exception as _exc_1182:
        _swallowed_1152("control_absence_contradicted_1182", _exc_1182, "'' = generic")
        return ""


# ---- #1185 -----------------------------------------------------------------
# THE LOGIN PAGE TAKES TWO SUBMITS, AND NOTHING SAYS SO.
#
# #540 gives this design its real login: a single-step flow (email, then password), which is
# what the reference screenshots show. In the generated page that becomes
#
#     const single = true;
#     if (single && step === 0 && !isRegister) { setStep(1); return; }
#     ... {isRegister ? 'Create account' : (single && step === 1 ? 'Sign In' : 'Continue')}
#
# so the FIRST submit issues no request at all — it reveals the password field and relabels
# the button. A walk that fills the email, clicks once and treats itself as logged in is
# anonymous, and the next protected page 401s.
#
# That is exactly r21's terminal record, and the app is fine:
#
#     validation:ui_flow:login_profile_catalog_my_list_flow  FAILED
#       "Live re-walk failed: after login submit, /profiles triggers
#        GET /api/profiles 401 Unauthorized; console/network errors present."
#
# Driven in a real browser against that same stack: fill email -> "Continue" (no request, the
# password field appears) -> fill password -> "Sign In" -> /auth/login 200 -> /api/profiles
# 200 -> /profiles, token in localStorage. The flow works; one submit is half of it.
#
# Present in every netflix run measured (r13, r14, r17-r21: 7 of 7 carry `single = true` and
# the `step === 0` gate), so a walk that does not know this fails the same way in all of
# them. r21 ended FAILED at $295 holding this one record.
#
# Same contract as #1182: speaks only when a record has ALREADY failed AND the page source
# actually shows the gate, and prescribes re-driving, never closing the item.

_AUTH_FAIL_1185 = (
    "401", "unauthorized", "not authenticated", "still on /login", "stayed on /login",
    "after login", "login submit", "not logged in",
)


def _single_step_login_1185(root):
    """(page-file, button-labels) when the app's login page gates its password behind a
    first submit, else (None, ())."""
    try:
        pages = Path(root) / "app" / "frontend" / "src" / "pages"
        if not pages.is_dir():
            return None, ()
        for f in sorted(pages.glob("*ogin*.jsx")) + sorted(pages.glob("*uth*.jsx")):
            src = f.read_text(encoding="utf-8", errors="replace")
            # The gate itself, not merely the word "step": this is the line that makes the
            # first submit a no-op.
            if not re.search(r"step\s*===\s*0[^\n]{0,40}setStep\(\s*1\s*\)", src):
                continue
            labels = re.findall(r"step === 1 \? '([^']+)' : '([^']+)'", src)
            return f.name, (labels[0] if labels else ("Sign In", "Continue"))
        return None, ()
    except Exception as _exc:
        _swallowed_1152("_single_step_login_1185", _exc, "(None, ()) = no diagnosis")
        return None, ()


def two_step_login_1185(orch, pages) -> str:
    """Say that the first submit is not the login, when a record blames auth right after it."""
    try:
        root = getattr(orch, "output_dir", None)
        if not root:
            return ""
        wanted = {str(p).strip() for p in (pages or []) if str(p).strip()}
        if not wanted:
            return ""
        hit = None
        for rec in _walk_records_1176(
                _hub_json_1176(root, "codehub_checks.json"),
                lambda d: str(d.get("status", "")).lower() in ("failure", "failed")
                and str(d.get("name", "")).startswith("validation:ui")):
            name = str(rec.get("name", ""))
            if name.rsplit(":", 1)[-1] not in wanted:
                continue
            blob = " ".join(str(v) for v in (rec.get("evidence") or {}).values()).lower()
            if "login" in blob and any(p in blob for p in _AUTH_FAIL_1185):
                hit = name
                break
        if not hit:
            return ""
        page, labels = _single_step_login_1185(root)
        if not page:
            return ""
        step1, step0 = (labels + ("Sign In", "Continue"))[:2]
        return (
            "\n\n★ THIS APP'S LOGIN TAKES TWO SUBMITS — THE FIRST ONE IS NOT THE LOGIN:\n"
            "- `%s` blames authentication right after a login submit, and %s gates its "
            "password field behind a first submit (#540's single-step flow, which is what "
            "the reference screenshots show).\n"
            "The first click only runs `setStep(1)` — it sends NO request and reveals the "
            "password field, relabelling the button from `%s` to `%s`. Submitting once "
            "leaves you anonymous, so the next protected page returns 401 and the record "
            "reads like a broken login.\n"
            "Drive it as two steps: fill the email, submit (`%s`), then fill the password "
            "that appears and submit again (`%s`). Verified in a real browser against r21's "
            "own stack: /auth/login 200, /api/profiles 200, token stored.\n"
            "If it still fails after BOTH steps, that is a real defect — say which step "
            "broke and what the page showed, and bug_create for the owning lane."
            % (hit, page, step0, step1, step0, step1))
    except Exception as _exc_1185:
        _swallowed_1152("two_step_login_1185", _exc_1185, "'' = generic remediation")
        return ""


def _ui_flow_failed_names(orch) -> List[str]:
    """#981: the flows the gate counts as FAILED — recorded, but not passing.

    `compute_flow_coverage` has always returned `failed` alongside `missing`; only the
    missing branch was ever read. So `deliverability_ui_flow_failed` reached the verifier as
    six words and no instance, while its sibling `_missing` named every flow. r159 spent its
    last hours on exactly that check with the walk's own findings (a blank player page, a
    broken POST /api/continue-watching) sitting unused in the report.

    Same source as the missing branch, and the same reason: recompute rather than trust a
    status the verifier reported about itself (FIX #284, r68). Best-effort -> [] falls back
    to the generic text."""
    try:
        _cfc = globals().get("compute_flow_coverage")
        if _cfc is None:
            from .flow_coverage import compute_flow_coverage as _cfc
        report = _cfc(orch.hubs.registryhub)
        seen: set = set()
        out: List[str] = []
        for f in (getattr(report, "failed", None) or []):
            t = str(f).strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out
    except Exception as _exc_1152:
        _swallowed_1152("_ui_flow_failed_names", _exc_1152, "[] = nothing to remediate")
        return []


def _ui_flow_failed_extra(failed: Sequence[Any]) -> str:
    """#981: name the failing flows. A gate check the lane cannot locate is a gate check it
    cannot clear."""
    # #1043: same latent coercion as `_ui_evidence_failed_extra` — the producer already
    # str()s its output, and a raise here would be swallowed into the generic text.
    failed = [str(x) for x in (failed or []) if str(x).strip()]
    if not failed:
        return ""
    return ("\n\nTHE FLOW(S) RECORDED BUT NOT PASSING (recomputed from the hub, not from "
            "any status previously reported):\n- " + "\n- ".join(failed) +
            "\n\nEach already HAS a record, so re-recording it changes nothing: open the "
            "evidence on the named flow, fix what it reports, then re-run the walk so the "
            "record flips to success.")


def _ui_flow_missing_extra(missing: Sequence[Any]) -> str:
    """The gate-specific remediation body for deliverability_ui_flow_missing. Names the exact
    missing flows and states the contradiction that broke r68 out loud — so a verifier that
    believes it "already recorded" them is forced to re-check the hub instead of re-asserting.
    Empty when nothing is missing, leaving #280's generic text untouched."""
    # #1043: same latent coercion as `_ui_evidence_failed_extra` — the producer already
    # str()s its output, and a raise here would be swallowed into the generic text.
    missing = [str(x) for x in (missing or []) if str(x).strip()]
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
        the failure back to the owner. Best-effort: never raises into the loop.

        ★ #1063 (measured, not a defect): this dispatch has never been exercised.
        Across the 201 kept run logs the "FRONTEND-NAVIGABLE remediation dispatched"
        line appears 0 times — NOT because the guard is wrong. validation_runner's
        `_add("frontend_navigable", ok, detail)` produces exactly this name with
        status "fail", so the lookup below matches by construction. It is that the
        check almost always PASSES, and in the four runs where it failed, docker_up
        had already failed and validation never reached this feedback loop. The path
        is live and untested in production — worth knowing before relying on it.

        The blank-shell condition that DOES reach a lane in practice takes a
        different route: `dispatch_unwired_ui_pages` reads the delivery gate's
        BLOCKER list, sees `deliverability_ui_page_unwired` (320 occurrences), and
        files "Make the declared pages deliverable" — 195 times across 48 logs."""
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
                route = _matchable_route_1202iy(
                    pg.get("route") or pg.get("path") or "?")
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
                # #1004: point at the file the lane CAN write.
                #
                # This said "Wire them in app/backend/main.py". `main.py` is in
                # _BACKEND_FRAMEWORK_OWNED, so `is_framework_owned()` makes the write guard
                # DENY every lane edit to it — the remediation was ordering the backend lane
                # to do the one thing it is structurally forbidden from doing. r162 produced
                # 17 tasks against a single 405 and never fixed it; a lane cannot fix a route
                # in a file it cannot open for writing.
                #
                # `custom_routes.py` is deliberately NOT framework-owned — it is the lane's
                # file, and the framework's own include_router discovery already mounts
                # whatever router it defines. That is where a missing route belongs.
                "registered+implemented endpoints answer 404/405 — the routes are not "
                "actually mounted. Add them to app/backend/custom_routes.py (the file YOUR "
                "lane owns; main.py is framework-owned and your writes to it are denied). "
                "Define the handler on the module-level `router` with the declared method "
                "and path — main.py already discovers and includes that router."),
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
                if not name:
                    # An unnamed failing check cannot be routed, and letting it through keys
                    # `guard` and `_persist` on None — one unnamed check would then share
                    # storm-control state with the next one.
                    continue
                spec = _CHECK_OWNER.get(name)
                if not spec:
                    continue  # covered by a bespoke helper, or not lane-actionable
                if guard.get(name) == milestone:
                    continue  # one dispatch per milestone (storm control)
                owner, title, how = spec
                detail = str(c.get("detail") or "")
                # #1006: do not hand a lane work it is structurally barred from doing.
                #
                # An endpoint that `served_routes()` says main.py MOUNTS, and the smoke
                # cannot reach, is a framework-code defect: main.py is in
                # _BACKEND_FRAMEWORK_OWNED, so the write guard denies every lane edit to it.
                # r162 dispatched 17 tasks against one such endpoint and then died on
                # `unresolved_failed_tasks`, counting its own undeliverable work as the
                # blocker. A lane cannot fix a route in a file it cannot open.
                #
                # Classify and SAY SO. The task still goes out — suppressing it would hide a
                # real failure — but it now opens with the fact that the route is already
                # mounted, so the lane stops trying to add it and the operator sees a
                # framework defect instead of a lane that "cannot fix a 405".
                if name == "business_endpoints_reachable":
                    try:
                        from .backend_audit import unreachable_but_mounted
                        _be = Path(getattr(orch, "output_dir", ".")) / "app" / "backend"
                        _fw = unreachable_but_mounted(
                            _be, [s.strip() for s in detail.split(";") if s.strip()])
                        if _fw:
                            orch._logger.warning(
                                "#1006 FRAMEWORK DEFECT (not a lane bug): %s — main.py already "
                                "mounts these and the app still refuses them. main.py is "
                                "framework-owned; no lane can repair this.", join_capped(_fw, len(_fw), cap=4))
                            detail = (
                                "FRAMEWORK DEFECT — main.py ALREADY MOUNTS these routes and the "
                                "running app still refuses them: " + join_capped(_fw, len(_fw), cap=4) +
                                ". Do NOT try to add them; main.py is framework-owned and your "
                                "writes to it are denied. Report what the running app returns "
                                "(status + Allow header) and move on. || " + detail)
                    except Exception:
                        pass
                # #1002 (instrumentation, not a fix): name the builder of this `detail`.
                #
                # Item 411 records station three of r162's evidence path: the dispatched
                # detail is `METHOD path → status` with no probe note, proven from the
                # artifact — `failed=['business_endpoints_reachable:GET /api/search → 500;
                # …']`. Nine keyword searches failed to find the code that composes it, which
                # is the brute-force reflex rather than a method.
                #
                # A check record cannot say where it came from, but the stack can. One
                # bounded frame list, logged once per check name, turns the next run that
                # fails a business endpoint into the answer. Costs nothing when nobody reads
                # it and removes the guessing entirely.
                try:
                    _seen1002 = getattr(orch, "_detail_origin_seen_1002", None)
                    if _seen1002 is None:
                        _seen1002 = set()
                        orch._detail_origin_seen_1002 = _seen1002
                    if name not in _seen1002:
                        _seen1002.add(name)
                        import traceback as _tb
                        _frames = [f"{f.filename.split('/')[-1]}:{f.lineno}:{f.name}"
                                   for f in _tb.extract_stack()[-8:-1]]
                        orch._logger.info(
                            "#1002 detail-origin for %s: keys=%s via %s",
                            name, sorted(c.keys())[:8], " <- ".join(reversed(_frames)))
                except Exception:
                    pass
                # #978: hand the LANE the salient line, not a blind prefix. r158 told the
                # verifier `docker_up — bcd1251d323e...f732f1bf`: 64 hex characters of
                # container id, because the raw detail begins with one and the dispatch
                # sliced `detail[:160]`. That is the #182 failure exactly, and
                # `_salient_error` was written to end it — this call site simply never
                # used it. The remediation message is the one text whose whole job is
                # telling an agent what to fix.
                try:
                    from .framework_validation import _salient_error as _salient_978
                    detail = _salient_978(detail, cap=600) or detail
                except Exception:
                    pass
                if name == "docker_up":
                    # #1202de: a host fault is not lane-actionable, and asking anyway is
                    # worse than leaving the blocker open. netflix-r43 asked a backend
                    # engineer to fix `pg_wal ... No space left on device`; it churned 45
                    # minutes, then closed the P0 claiming Postgres now runs on a /dev/shm
                    # tmpfs — a change that exists in no commit on any branch and in none
                    # of the seven worktrees. docker_up went green because an operator
                    # reclaimed 136GB, and the verifier's rerun rubber-stamped the
                    # fabrication. Name it, leave the blocker open, wake nobody.
                    _hf1202de = docker_up_host_fault_1202de(detail)
                    if _hf1202de:
                        orch._logger.error(
                            "#1202de HOST FAULT (not a lane bug): `docker_up` failed on "
                            "%r — OPERATOR ACTION required (free the port / reclaim disk "
                            "/ start the daemon). No remediation dispatched: no lane can "
                            "fix this, and one asked to will eventually claim it did. "
                            "Detail: %s", _hf1202de, str(detail)[:200])
                        continue
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
                _wake_1202tc = _create_message(
                    source_agent_id="orchestrator", target_agent_id=owner,
                    content=(
                        f"URGENT: delivery is blocked on `{name}`. Claim task "
                        f"{(task or {}).get('id')} and fix it NOW, then finish. "
                        f"Detail: {detail[:300]}"),
                    msg_type="task_ready", priority="urgent", persist=True,
                    tags=[str(name), "remediation"])
                # #1202tc: the SIBLING emitter of the V29 fix. `dispatch_gate_level_checks`
                # sets this flag when it wakes the verifier, with a documented run loss behind
                # it ("the wake bounced 38x and the run STUCK-ABORTed"); this table routes
                # `docker_up` to the verifier too and never got it. Simulated against the real
                # `agents_config.yaml` policy and the real `_create_message`: this wake is
                # REJECTED every time -- from_agent is right, but the flag is unset, no phase
                # is ever set on these messages, `["docker_up", "remediation"]` misses
                # `accepted_tags`, and the payload carries none of the `payload_keywords`
                # ("blocked" is not "blocker"). 72 of these tasks exist across 49 corpus runs,
                # every one assigned to the verifier.
                #
                # NOT a dead end, and worth saying so: 64 of the 72 ended `completed`, so the
                # verifier reaches the task through its own polling. What the bounce costs is
                # the urgency -- and a log line reading "verifier requires explicit
                # validation-phase trigger", which describes the policy rather than the
                # missing flag, so it reads as correct behaviour.
                if owner == "verifier":
                    _wake_1202tc.metadata["validation_phase"] = True
                await orch.message_bus.send(_wake_1202tc)
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
                route = _matchable_route_1202iy(
                    pg.get("route") or pg.get("path") or "?")
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
                # #1034: was `"; ".join(...)[:200]` — a CHARACTER cut on the joined string,
                # so it could sever a page name mid-word and read as a different page.
                join_capped(blockers, len(blockers), cap=8))
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
                route = _matchable_route_1202iy(
                    pg.get("route") or pg.get("path") or "?")
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

    async def dispatch_never_matching_filters_1148(self) -> None:
        """#1148: tell the backend about a filter no seeded row can satisfy.

        #1139 detects it and stops there — the finding is placed in the gate result
        (`never_matching_filters`) and NOTHING reads that key. It is #1041's shape exactly:
        the evidence exists, the party who can act on it is never told.

        netflix-local-r8 DELIVERED release 1.0.0 carrying one: `/api/titles/top10` filters
        `WHERE t.top10_rank IS NOT NULL`, `models.py` declares the column, and no seed row ever
        sets it — so 1 of its 24 business endpoints can never return data. Measured live on one
        token: trending 24 rows, search 24 rows, top10 **0**.

        A TASK, not a gate check. #1139 deliberately reports rather than blocks, and that stays
        true: a task is worked, a check is a wall, and a new wall cannot be validated without a
        run. The predicate is narrow enough to carry a P0 — it is not "the response was empty"
        (`/api/my-list` is legitimately empty for a fresh user and filters by `user_id`, so it
        is never reported); it is a filter no seeded row could satisfy, which nothing ships on
        purpose. Verified against three delivered artifacts: r8 → top10_rank, r5 → nothing,
        smoke-notes → nothing.
        """
        try:
            orch = self._orch
            out_dir = getattr(orch, "output_dir", None)
            if not out_dir:
                return
            milestone = getattr(orch, "_current_milestone_version", "")
            if getattr(orch, "_nmf1148_dispatched", None) == milestone:
                return
            from .delivery_gate import never_matching_filters_1139 as _nmf
            rows = _nmf(out_dir) or []
            if not rows:
                return
            _lines = []
            for r in rows[:8]:
                if not isinstance(r, dict):
                    continue
                # Field names verified by CALLING never_matching_filters_1139 against a
                # real artifact rather than assumed: the rows carry `column` and `detail`,
                # nothing else. Guessing `table`/`where`/`file` here would have rendered a
                # line of question marks — the fourth field-name miss of this session's
                # lineage (#1029, #1128, #1147), and the first one caught before shipping.
                _col = str(r.get("column") or "?")
                _why = str(r.get("detail") or "").strip()
                _lines.append(f"- `{_col}`: {_why}" if _why else f"- `{_col}`")
            if not _lines:
                return
            orch.hubs.workhub.create_task(
                title="Seed a column the queries filter on (endpoint returns nothing)",
                description=(
                    "A query filters on a column that NO seeded row populates, so the "
                    "endpoint behind it can never return data — the SQL is correct, the "
                    "route is mounted, and the result is permanently empty:\n"
                    + "\n".join(_lines) + "\n\n"
                    "Fix ONE of these, whichever is true: (a) seed the column for the rows "
                    "that should qualify (usually the right answer — a top-N/featured flag "
                    "needs values), or (b) drop the filter if every row qualifies, or (c) "
                    "delete the endpoint if the product does not have that surface. Do NOT "
                    "leave it as is: netflix-local-r8 shipped release 1.0.0 with exactly this "
                    "and 1 of its 24 business endpoints served an empty list forever."),
                assignee="backend",
                agent="orchestrator",
                priority="P0",
            )
            orch._nmf1148_dispatched = milestone
            # #1034: a printed count may not sit beside a silently truncated list, and the
            # rows carry `column`, not `table` — the same field the task body above uses. Both
            # were wrong on this line and both were caught by the repo's own guards rather
            # than by review.
            orch._logger.warning(
                "#1148 filed a P0: %d column(s) are filtered on but never seeded — %s",
                len(rows),
                join_capped(
                    [str(r.get("column")) for r in rows if isinstance(r, dict)],
                    len(rows), sep=", "))
        except Exception as _exc:
            try:
                self._orch._logger.debug("#1148 dispatch skipped: %s", _exc)
            except Exception:
                pass

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
            # #1202ou: the two auth-tampering blockers, routed. The gate-level check carries
            # its name only, so this body names the patterns to delete.
            "deliverability_guard_tampering": (
                "backend", "Remove the code that rewrites the framework's auth guard (blocks delivery)",
                "app/backend/custom_routes.py (or seed_data.py) edits the framework's own auth "
                "guard: it assigns or removes entries of `app.router.routes`, or names "
                "`_FW_PUBLIC_API_1202KH` / `_FW_PUBLIC_RE_1202KH` / `_fw_contract_public_1202kh`. "
                "That publishes routes the contract keeps private — anonymous callers then read "
                "other users' rows, and the verifier's denial chains fail on exactly those "
                "paths. Delete every such line (grep the file for those names). To make an "
                "endpoint public, change its CONTRACT (`auth_required: false` on a table the "
                "materials call public) and let the framework project it — never edit the "
                "guard."),
            "deliverability_auth_override": (
                "backend", "Stop reassigning a framework auth primitive (blocks delivery)",
                "app/backend/custom_routes.py reassigns an authentication primitive the "
                "framework owns (e.g. `verify_user_password`, `get_current_user`). /auth/login "
                "and /auth/register are framework-owned, so any override desynchronises login "
                "from the tokens every other route checks. Delete the reassignment; if login "
                "behaviour is wrong, report it as a framework defect instead."),
            # #1202sw: the placeholder-route blocker, routed. The component name in the gate's
            # prose is the instance, and #983 now replays it beside this body because the token
            # is stable. FRONTEND owns it: both repairs are edits to the page and its route.
            "deliverability_placeholder_route": (
                "frontend", "Replace the placeholder page behind a live route (blocks delivery)",
                "App.jsx routes a component whose own NAME says it is not a real page "
                "(placeholder / dummy / noop / todo / untitled). A route a user can reach must "
                "render the real thing — this is the standing bar: no dead UI, no fake data. "
                "For EACH component named below, either BUILD the real page (its reference "
                "layout under design/, real fields from its endpoint, real controls) or REMOVE "
                "the route from App.jsx AND deregister its ui_page, so nothing routes to it. "
                "Renaming the component does not fix it — the page behind the route is what "
                "the user sees."),
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
            "deliverability_seed_quality": (
                # #1199: the generic sibling of the row above, and the last check in the
                # recent corpus that reaches `if not spec: uncovered.append(name); continue`
                # — where nothing is dispatched and the run logs "NO remediation owner".
                # #1040 is what that costs when it lands on a common blocker: 26 runs, on the
                # most frequent one, with a working fix sitting unreachable behind the lookup.
                #
                # Measured before adding, and time-sliced (frequency alone ranks already-fixed
                # gaps first): across r20-r26 exactly ONE gate tick logged no owner, and it
                # was this check. The historical 157 hits on `deliverability_dead_artifacts`
                # are all from before its row was added.
                #
                # Owner matches its sibling for the same reason: the seed file is the
                # backend's artifact, and this branch fires on the same file's content
                # ("low row count" / "placeholder seed" rather than the authored-seed audit).
                "backend", "Raise the seeded data to realistic density (blocks delivery)",
                "the database seed is too thin or too placeholder-shaped to populate the "
                "screens: a low row count, or values built from marker words rather than "
                "domain content. Rewrite the seed with domain-REALISTIC rows — enough that "
                "list screens look like the references, believable names/subjects/timestamps, "
                "mixed states, FK-valid ids — then re-run run_validation."),
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
            "deliverability_critical_visuals_pending": (
                # #1187: this check BLOCKS and had no owner. Measured: it declined a delivery
                # alongside three other checks and the very next log line read "Delivery
                # declined on gate check(s) with NO remediation owner ... ['deliverability_
                # critical_visuals_pending']" -- the #1040 shape, one check to the side.
                #
                # `_visual_summary` counts ui_page records whose status is `pending` or
                # `reviewing`, and the gate blocks on that only when the UI is not otherwise
                # validated. `submit_visual_review` is locked to the verifier, so the verifier
                # is the only agent who can move one -- which is exactly why a missing owner
                # left it unmovable.
                #
                # ★ #958 measured that NO ui_page with kind='visual_review' exists in any run
                # of the corpus, so a nonzero `pending` here usually means a page was
                # registered with a review status nobody intends to fulfil, rather than that
                # a real review is owed. Both readings are given, because only the verifier
                # can tell them apart by looking.
                "verifier", "Resolve the pending critical visual review(s) (blocks delivery)",
                "one or more CRITICAL ui_page records sit at status `pending`/`reviewing`, so "
                "the visual-review gate cannot pass and the UI is not otherwise validated. "
                "`submit_visual_review` is yours alone -- no other lane can clear these. For "
                "each pending page: open it, compare it against its reference screenshot, and "
                "submit_visual_review with `approved` or `needs_revision` (with what to change, "
                "which routes to the frontend lane). If the page is NOT a visual-review "
                "subject at all -- #958 measured that no run has ever carried a ui_page with "
                "kind='visual_review' -- then the review status is the defect: re-register the "
                "page with its real kind so the gate stops counting it. Do NOT leave it "
                "pending: nothing else in the pipeline can move a record only you can write."),
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
            "deliverability_masked_api_failure": (
                # #1202qn: the frontend lane wrote the catch that substitutes hard-coded data.
                "frontend", "Stop masking failed API requests with hard-coded data (blocks delivery)",
                "a request's failure is answered with a hard-coded list/record (a fallback, mock or "
                "sample copied from the design), so the page renders invented content and nobody "
                "sees the failure. For EACH flagged file:line: delete the substitute data, let the "
                "error reach the page as a visible error state, then find and fix why the request "
                "fails (wrong path, missing auth header, contract drift). Do not replace it with "
                "another fallback."),
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
            "deliverability_unscoped_owner_read": (
                # #1202lf: unowned until now — 20 runs declined delivery on it with nothing
                # dispatched. The owner is the BACKEND because the decision is a table-policy
                # one, and the advice deliberately does NOT say "add a filter": measured over
                # the corpus, most of these findings are a PUBLIC table wrongly carrying
                # `owner_scoped_reads` (netflix's `titles`, tiktok's `sounds`/`users`), where
                # filtering would wall the catalogue. #1202gt exists for that exact wording
                # hazard. So both repairs are named and neither is assumed.
                "backend", "Resolve the unscoped owner-read finding (blocks delivery)",
                "the audit found a projected read returning EVERY row of a table the contract "
                "marks owner-scoped. Exactly one of two things is true and only the contract "
                "and the materials can say which. If the rows really are per-user, leave "
                "`owner_scoped_reads` set and let the projector filter them — the finding is "
                "then real and the READ is what must change. If the table is a PUBLIC feed "
                "wrongly carrying that flag, clear `owner_scoped_reads` on the TABLE and make "
                "the materials say `visibility: public`; the audit then exempts it by "
                "construction (#1202gd/#1202hm) and the blocker clears itself. Do NOT add a "
                "filter, a short-circuit or a public-list entry in custom_routes.py: the "
                "projector re-renders from the contract and will overwrite it, and appending "
                "to the framework's public list serves owner-private rows to everyone."),
            "deliverability_empty_param_nav_link": (
                # #1042: the last unmapped token. The route IS declared and wired — the link
                # interpolated an empty id — so this must NOT reuse the dead-nav-link advice,
                # which says to add or repoint a route. The blocker's own prose already says
                # the right thing and arrives with the task via `_gate_blocker_prose_983`.
                "frontend", "Fix the empty interpolated route parameter (blocks delivery)",
                "a nav link builds a parameterised route with an EMPTY parameter (e.g. "
                "`/watch/${title.id}` where `title.id` is undefined), so clicking it lands on "
                "a broken URL. The route itself is DECLARED and WIRED — do NOT add a route or "
                "repoint the link. Fix the VALUE: check the field name the API actually "
                "returns for that id, and do not render the link at all while the id is "
                "missing."),
            # --- #1042: four more checks that declined delivery with nobody dispatched. ---
            # Each is assigned from EVIDENCE the framework already computes, not from a guess:
            # every one of them has remediation text somewhere in the tree that no owner could
            # ever reach. Recent-era rates (r150-r175, 26 runs) are why these four and not the
            # rest: 11/26, 9/26, 8/26, 3/26.
            "completeness_state_entity_no_write": (
                # 11/26. `check_state_entity_no_write` already builds a per-entity
                # `suggested_fix` ("Declare + implement a write endpoint for `X` ... then
                # register it in RegistryHub") and the delivery gate already appends an
                # operator suggestion saying the same. Neither could reach a lane.
                # This is the Continue-Watching write-path class: a table you can READ and
                # never WRITE, which the declared-contract coverage gate cannot see because
                # the write endpoint was never declared in the first place.
                "backend", "Add the missing write endpoint for a state-bearing table "
                           "(blocks delivery)",
                "a state-bearing table (it has mutable columns like progress_seconds / "
                "status / value) has a GET but NO POST/PUT/PATCH — the feature can be READ "
                "and never WRITTEN, so nothing a user does can persist. Declare + implement "
                "the write endpoint on that table's collection, register it in RegistryHub, "
                "then re-run run_validation. The contract-coverage gate cannot catch this for "
                "you: it checks DECLARED endpoints, and this one was never declared."),
            "frontend_code_missing": (
                # 8/26. `app/frontend` contains no files at all — the gate's own operator
                # suggestion is "Generate frontend implementation files under app/frontend".
                "frontend", "Write the frontend implementation files (blocks delivery)",
                "`app/frontend` contains NO files, so there is nothing to build or serve. "
                "Author the pages/components under `app/frontend/src` for the ui_pages you "
                "declared at kickoff (App.jsx routes + one component file per page), not a "
                "placeholder — the visual and ui_flow gates open these routes for real."),
            "deliverability_dead_artifacts": (
                # 9/26. #1042 also fixed the blocker text to name the KINDS, so the
                # per-kind counts now arrive with this task via `_gate_blocker_prose_983`
                # ("WHAT THE GATE ACTUALLY REPORTED"). Owner is backend because
                # endpoints/tables/mcp_tools are the backend-side kinds; the routing sentence
                # handles the frontend ones, mirroring `deliverability_ui_flow_failed`.
                "backend", "Remove or wire up the dead artifacts (blocks delivery)",
                "artifacts are registered but nothing consumes them. The gate now reports the "
                "breakdown by KIND — endpoints / tables / mcp_tools are yours: either wire "
                "each one into a real caller or deprecate it "
                "(registryhub_deprecate_endpoint). If the breakdown names `files` or "
                "`pages_without_files`, those are FRONTEND: bug_create for frontend with the "
                "names rather than deleting their declarations."),
            "deliverability_missing_seed": (
                # 3/26, and newly meaningful: #1039 made the seed audit count LIVE rows, so
                # this token now fires on a table the database itself reports as empty
                # instead of on a missing hub registration.
                "backend", "Seed the empty business table (blocks delivery)",
                "a business table is EMPTY in the running database, so every screen that "
                "lists it renders blank. Insert realistic rows (mixed states, believable "
                "names/timestamps — not `test`/`item_1` placeholders), then re-run "
                "run_validation. Framework-owned identity/tenancy tables (tenants, users, "
                "oauth_*) are excluded and are not your concern here."),
            "validation_ui_evidence_failed": (
                # #1040 — #280's defect, exactly, one check to the left, five months later.
                #
                # This is the MOST COMMON live blocker (7 of the last 10 declining runs) and it
                # was in neither `_GATE_OWNER` nor `_COVERED_ELSEWHERE`, so every gate tick took
                # the `if not spec: uncovered.append(name); continue` path: 26 runs logged
                # "NO remediation owner" for it and NOTHING was ever dispatched.
                #
                # ★ The reason it went unnoticed for so long is that a fix for it already
                # EXISTS and is unreachable: #982 added a `if name == "validation_ui_evidence_
                # failed":` branch below that builds the named-pages remediation via
                # `_ui_evidence_failed_pages`/`_ui_evidence_failed_extra`. That branch sits
                # AFTER the owner lookup, so the check `continue`s past it every time. Both
                # helpers work; nothing could call them. Adding this row activates #982.
                #
                # r174 is the whole chain in one run: 6 flows failed at 23:51, the gate could
                # not NAME them (#1032, fixed), no owner existed to dispatch to (this), and in
                # the following 80 minutes exactly one UI record was written — none of the six.
                # r175 shows the first half repaired: "#1017 ... 8 record(s), 8 named page(s):
                # detail_to_play; genre_navigation; ..." and then, still, "NO remediation owner".
                #
                # Owner is `verifier` for the same reason both siblings are: it owns the walk
                # that WRITES validation:ui_flow records, so it is the only lane that can make a
                # failing record flip. It bug_creates for whoever owns the underlying defect.
                "verifier", "Re-verify the failing UI evidence records (blocks delivery)",
                "one or more validation:ui_flow records are FAILING, so the UI evidence gate "
                "cannot pass. These are RECORDS, not necessarily live defects: a record stays "
                "failing until a walk overwrites it, so a flow fixed after the record was "
                "written still blocks. For each named page/flow below: re-run the walk "
                "(run_validation) so the record is rewritten from the CURRENT app. If it still "
                "fails, read the recorded reason + console_errors, bug_create for the owning "
                "lane (a JS/render crash or dead control is FRONTEND; a 4xx/5xx from the API is "
                "BACKEND), then re-run once fixed. Do NOT close the gate item by editing the "
                "record — only a fresh walk counts."),
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
            # #1041: handled by the bespoke per-task re-wake below (the owner is the failed
            # TASK's assignee, not a single lane), exactly like incomplete_required_tasks.
            "unresolved_failed_tasks",
            # #1040: `database_sql_missing` has a deterministic framework self-heal (#74:
            # write the SQL from the live schema when the app DB is functional), so it was
            # never a dead end — but it was absent from this set, so 85 runs logged it as
            # having "NO remediation owner". Measured: the self-heal fires in 45 of those 85
            # and the check is still present near the end in only 2. Listing it stops the
            # misreport; it does NOT buy silence, because #1040's wedge detector still fires
            # on a covered-elsewhere check that keeps failing (those 2 are the case it is for).
            "database_sql_missing",
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
            _owned_1040 = 0          # checks that HAVE a remediation owner this tick
            _elsewhere_1040: List[str] = []
            for name in dict.fromkeys(str(r) for r in failed_checks):
                spec = _GATE_OWNER.get(name)
                if not spec:
                    if name not in _COVERED_ELSEWHERE:
                        uncovered.append(name)
                    else:
                        _elsewhere_1040.append(name)
                    continue
                _owned_1040 += 1
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
                _inst: List[Any] = []       # #1202ss: the instances this title will name
                # #799: two more entries in this table told the lane to go and find something the
                # framework already computes — the same defect #798 fixed one row up.
                if name == "business_chain_api_coverage":
                    _unc799 = _uncovered_endpoints_799(orch)
                    if _unc799:
                        _inst = list(_unc799)
                        _extra = ("\n\nTHE UNCOVERED ENDPOINTS (computed by the same check that "
                                  "blocked you — cover THESE):\n- " + "\n- ".join(_unc799))
                elif name == "verification_checklist_not_ready":
                    _red799 = _red_checklist_checks_799(orch)
                    if _red799:
                        _inst = list(_red799)
                        _extra = ("\n\nTHE CHECK(S) THAT ARE NOT GREEN right now:\n- "
                                  + "\n- ".join(_red799))
                if name == "business_chain_failing":
                    # FIX #148: the failing steps answering the projection's #124
                    # action-endpoint stub 404 need a BACKEND route, not a chain
                    # re-author — route the P0 to the lane that can add it.
                    _act = _chain_action_404s(orch)
                    if _act:
                        _inst = list(_act)
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
                            _inst = list(_brk798)
                            _extra = ("\n\nTHE BROKEN STEP(S), from the chain registry's own "
                                      "last_result — fix THESE, do not re-author the chain:\n- "
                                      + "\n- ".join(_brk798))
                    # #1202ld: and the annotations the gate computes for this very check,
                    # which until now were appended to a `detail` string nothing reads.
                    _extra += contract_and_surface_annotations_1202ld(orch)
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
                            _inst = list(_unc)
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
                # #983: last-resort instance naming. Every bespoke branch below exists
                # because someone hit that check and noticed the lane was told nothing;
                # #981 and #982 were two of those, days apart, for sibling checks. This
                # covers the ones nobody has hit yet — the gate already derived the token
                # FROM prose that names the page or flow, so replay that prose when no
                # branch has set something better. Set first so a bespoke branch overrides.
                try:
                    _prose = (getattr(orch, "_gate_blocker_prose_983", None) or {}).get(name) or []
                    # #1202sv: FALLBACK, not override. #983's own comment says "Set first so a
                    # bespoke branch overrides" -- but it sits BELOW two branches that set
                    # `_extra` (#154's bare_authed_fetch call sites, #799's uncovered
                    # endpoints), so position cannot deliver what it promises. Harmless today
                    # only by luck: the one check where both fire (deliverability_bare_authed_
                    # fetch) reads its prose from `frontend_audit.bare_authed_fetch_blockers`
                    # on BOTH paths, so the two strings are the same function's output. The
                    # next bespoke branch added above this line would have been silently
                    # replaced. Guard by emptiness, which holds wherever the block sits.
                    if _prose and not _extra:
                        _extra = ("\n\nWHAT THE GATE ACTUALLY REPORTED:\n- "
                                  + "\n- ".join(str(x) for x in _prose[:8]))
                except Exception:
                    pass
                if name == "validation_ui_evidence_failed":
                    # #982: the other half of r159's terminal pair. Same shape as #981.
                    _fp = _ui_evidence_failed_pages(orch)
                    if _fp:
                        _inst = list(_fp)
                        # #1176: append the contract-vs-public-route diagnosis when the
                        # failing record names a 401/403. Empty string when it does not
                        # apply, so the #982 text is unchanged in every other case.
                        _extra = (_ui_evidence_failed_extra(_fp) + auth_contradiction_1176(orch, _fp)
                                  # #1177: and correct the refresh instruction for any
                                  # failing ui_smoke record, which run_validation cannot rewrite.
                                  + ui_smoke_refresh_1177(orch, _fp)
                                  # #1182: and answer any 'control is missing' claim with the markup.
                                  + control_absence_contradicted_1182(orch, _fp)
                                  # #1185: and say when a login needs two submits.
                                  + two_step_login_1185(orch, _fp)
                                  # #1202su: and say that a pass under another name does
                                  # not retire this record.
                                  + name_keyed_supersede_1202su(orch, _fp))
                if name == "deliverability_ui_flow_failed":
                    # #981: the sibling branch below has named its instances since FIX #284;
                    # this one never did, so the verifier was handed the check name alone.
                    _ff = _ui_flow_failed_names(orch)
                    if _ff:
                        _inst = list(_ff)
                        # #1176: same 401/403 diagnosis, other check -- a failing ui_flow
                        # record carries the same evidence shape. Silent when the flow name
                        # does not resolve to a declared ui_page route.
                        _extra = (_ui_flow_failed_extra(_ff) + auth_contradiction_1176(orch, _ff)
                                  + control_absence_contradicted_1182(orch, _ff)
                                  # Symmetry: the other three diagnoses are wired to BOTH
                                  # branches and #1177's absence here was an oversight, not a
                                  # decision. It self-gates on a failing ui_smoke record, so it
                                  # is silent when this branch's flows are the only failures.
                                  + ui_smoke_refresh_1177(orch, _ff)
                                  + two_step_login_1185(orch, _ff)
                                  + name_keyed_supersede_1202su(orch, _ff))
                if name == "deliverability_ui_flow_missing":
                    # FIX #284: hand the verifier the EXACT missing flow names + the
                    # contradiction that broke r68 (it broadcast "already recorded" for
                    # flows the hub never held). Generic #280 text gave a drifting verifier
                    # nothing to refute; the specific names + "re-read the hub" do.
                    _mf = _ui_flow_missing_names(orch)
                    if _mf:
                        _inst = list(_mf)
                        _extra = _ui_flow_missing_extra(_mf)
                # #794: re-dispatch NAGS; it must not clone the task. The decline counter
                # deliberately re-dispatches a still-failing check every few minutes, and each
                # pass used to create a NEW P0 — r130 accumulated 13 copies of "Make
                # business_chain pass" ~4 min apart with the last FIVE simultaneously
                # `in_progress`. Cost: `incomplete_required_tasks` (a delivery blocker count)
                # inflates with clones of one problem, and an agent can claim copy #9 while
                # #10-13 sit unclaimed looking like unstarted work. The nag itself is kept —
                # only the duplicate row goes. Present in 8 of the last 22 corpus runs.
                # #1202ss: name the instance in the title. Kept as a PREFIX of the base so
                # `#794`'s open-task lookup (prefix, below) and `_gate_still_fails_on_1202pg`
                # (substring) both still match — and so a re-dispatch whose instance set has
                # CHANGED re-wakes the existing task instead of filing r130's 13th clone.
                _base_title_1202ss = title
                title = _instanced_gate_title_1202ss(title, _inst)
                _open794 = None
                try:
                    for _t in (orch.hubs.workhub.list_tasks() or []):
                        if (isinstance(_t, Mapping)
                                and str(_t.get("title")).startswith(_base_title_1202ss)
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
                        # #800: #794 made the re-dispatch re-wake an EXISTING task instead of
                        # cloning it — but this message still said "Claim task X", and on that
                        # path the task is typically already `in_progress` and already held by
                        # this very agent. Telling an owner to claim what it holds is an
                        # instruction it cannot follow, on the wake it reads FIRST; and it hides
                        # the one fact that matters on a re-dispatch, which is that the work it
                        # already did has not cleared the check. Same class as #798/#799 one
                        # layer out: the system knew, and did not say.
                        (f"URGENT: delivery is STILL blocked on the `{name}` gate check — the "
                         f"work on task {(task or {}).get('id')}, which you already hold, has "
                         f"not cleared it. Re-read the task body (it names the failing "
                         f"instance), fix it NOW, then finish.")
                        if _open794 is not None else
                        (f"URGENT: delivery is blocked on the `{name}` gate check. Claim "
                         f"task {(task or {}).get('id')} and fix it NOW, then finish.")),
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
                            _ids = join_capped([str(t.get("id")) for t in _ts],
                                               len(_ts), cap=8, sep=", ")
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
            # #1041: `unresolved_failed_tasks` — the sibling of the block above, and the
            # fastest-growing wedge in the corpus. It was in NEITHER table, so a FAILED task
            # blocked delivery with nobody told:
            #
            #     r1  - r149    0 of 149 runs      <- never fired
            #     r150- r175   13 of  26 runs      <- half of them
            #
            # The check's own comment already says who can clear it and how: *"Clearing it is
            # cheap and in the lane's hands: complete the task, or cancel it if it was wrong.
            # That is the same escape any structural blocker already has."* Nothing said that
            # to the lane. r174's terminal pair was this check plus
            # validation_ui_evidence_failed — both unowned, so the run declined for 80 minutes
            # with nothing dispatched.
            #
            # Not a `_GATE_OWNER` row: like `incomplete_required_tasks`, the owner is per-TASK
            # (its own assignee), not per-check, so it needs the same bespoke re-wake rather
            # than a single lane name. The tasks already exist — no new task is created.
            if "unresolved_failed_tasks" in failed_checks:
                _ftn = "unresolved_failed_tasks"
                _fire = True
                if guard.get(_ftn) == milestone:
                    _persist[_ftn] = _persist.get(_ftn, 0) + 1
                    _fire = (_persist[_ftn] % _GATECHECK_REFIRE == 0)
                else:
                    _persist[_ftn] = 0
                if _fire:
                    try:
                        from .delivery_gate import unresolved_bug_tasks_743 as _ubt
                        _granted = set()
                        try:
                            _granted = orch._all_registered_tool_names() or set()
                        except Exception:
                            _granted = set()
                        _b743 = _ubt(orch.hubs, getattr(orch, "output_dir", None),
                                     _granted) or {}
                        # #1033: a fail_reason naming a tool we KNOW is granted is checkably
                        # false. Quote that back — a blocker resting on a falsehood should be
                        # re-attempted, not accepted.
                        # ★ Field names verified by DUMPING a real record, not assumed: the
                        # `failed` entries key on `id` and carry the text under `reason`
                        # (not `fail_reason` — that is the WorkHub task's spelling, which the
                        # collector renames), and contradictions key on `id` too. The first
                        # draft of this handler guessed all three and would have re-woken
                        # nobody while logging that it had nobody to wake.
                        _contra = {str(c.get("id")): c
                                   for c in (_b743.get("contradicted_tool_claims") or [])}
                        # #1050: the mirror set — reasons that are TRUE and name a
                        # framework-owned artifact. Re-dispatch cannot help these (no lane can
                        # mount framework source), so the nag must carry the ONE action that
                        # actually resolves them instead of asking for a retry that will fail
                        # identically. r179 re-woke the debugger 10x for one such task.
                        _fwown = {str(c.get("id")): c
                                  for c in (_b743.get("framework_owned_failed") or [])}
                        # #1128: ROUTE BY AUTHORITY, NOT BY LABEL. The message below
                        # prescribes exactly two escapes -- COMPLETE it or CANCEL it -- and
                        # WorkHub grants them to different agents: complete_task requires
                        # `claimed_by == agent`, cancel_task requires creator-or-orchestrator.
                        # An assignee who is neither is being told to do two things the
                        # authorization guards will both refuse, and 18% of the corpus's
                        # failed-with-assignee tasks are exactly that (see the collector).
                        # Those go to the orchestrator, which created them and -- since #1127
                        # made `failed` cancellable -- can now actually clear them.
                        _by_assignee = {}
                        for _t in (_b743.get("failed") or []):
                            _t = _t or {}
                            _a = str(_t.get("assignee") or "").strip()
                            # #1202kk: the orchestrator's own roster -- the same object
                            # `attach_live_agents_provider` hands the hubs -- so an owner that
                            # has already finished cannot be handed the only escape.
                            _owner = failed_task_owner_1128(
                                _t, live_agents=list(getattr(orch, "_agents", None) or ()))
                            if _owner != _a:
                                # Nobody else can move it: the assignee is neither claimer nor
                                # creator, so both prescribed escapes would be refused.
                                _t = dict(_t)
                                _t["_powerless_assignee_1128"] = _a or "<unassigned>"
                            _by_assignee.setdefault(_owner, []).append(_t)
                        for _a, _ts in _by_assignee.items():
                            _lines = []
                            for _t in _ts[:6]:
                                _tid = str(_t.get("id"))
                                _why = str(_t.get("reason") or "<no reason recorded>")
                                _note = ""
                                if _tid in _contra:
                                    _note = (" ⚠ THIS REASON IS CHECKABLY FALSE: it says the "
                                             "tool `%s` is unavailable, and that tool IS in "
                                             "your granted surface — call it and retry (#1033)."
                                             % _contra[_tid].get("tool"))
                                if _tid in _fwown:
                                    _note += (
                                        " ⚠ THE FRAMEWORK AGREES with this reason (#1050): "
                                        "'%s' is framework-owned and is not reachable from any "
                                        "lane worktree, so retrying will fail identically. Do "
                                        "NOT retry — CANCEL this task with that reason. The "
                                        "underlying defect is the framework's to fix, and "
                                        "cancelling is what unblocks the cut."
                                        % _fwown[_tid].get("marker"))
                                if _t.get("_powerless_assignee_1128"):
                                    # #1128: it is not this agent's own abandoned work.
                                    _note += (
                                        " ⚠ ROUTED TO YOU (#1128): this task is assigned to "
                                        "`%s`, but it was never claimed, so that agent can "
                                        "neither complete it (not the claimer) nor cancel it "
                                        "(not the creator) — both guards refuse. You created "
                                        "it, so YOU are the only agent who can resolve it: "
                                        "cancel it if it no longer holds, or re-create it as a "
                                        "fresh pending task someone can claim."
                                        % _t.get("_powerless_assignee_1128"))
                                _lines.append("%s: %s%s" % (_tid, _why[:300], _note))
                            _wmsg = _create_message(
                                source_agent_id="orchestrator", target_agent_id=_a,
                                content=(
                                    f"URGENT: delivery is BLOCKED by {len(_ts)} task(s) you "
                                    f"marked FAILED. A failed task blocks the cut until it is "
                                    f"resolved, and you have two ways to resolve it: COMPLETE "
                                    f"it (retry — conditions may have changed since you gave "
                                    f"up), or CANCEL it if the task itself was wrong or is no "
                                    f"longer needed. Leaving it failed is not an option; it "
                                    f"stops the release.\n\n- "
                                    + "\n- ".join(_lines)),
                                msg_type="task_ready", priority="urgent", persist=True,
                                tags=[_ftn, "remediation"])
                            if _a == "verifier":
                                _wmsg.metadata["validation_phase"] = True
                            await orch.message_bus.send(_wmsg)
                        if _by_assignee:
                            guard[_ftn] = milestone
                            _persist[_ftn] = 0
                            _owned_1040 += 1   # something WAS dispatched — not a wedge
                            orch._logger.warning(
                                "#1041 FAILED-TASK remediation re-woke %d assignee(s) over %d "
                                "task(s)%s: %s", len(_by_assignee),
                                sum(len(v) for v in _by_assignee.values()),
                                (" (%d resting on a checkably false reason)" % len(_contra))
                                if _contra else "",
                                join_capped(sorted(_by_assignee), len(_by_assignee), sep=", "))
                        else:
                            orch._logger.warning(
                                "#1041 unresolved_failed_tasks is blocking but NO failed task "
                                "carries an assignee, so there is nobody to re-wake — the "
                                "orchestrator must re-assign or cancel these itself.")
                    except Exception as _e1041:
                        orch._logger.warning(
                            "#1041 failed-task remediation could not run (%s: %s) — the "
                            "blocker stands with nobody dispatched",
                            type(_e1041).__name__, _e1041)
            # Dedup to once-per-CHANGE (mirrors #45) — _maybe_framework_deliver runs every
            # ≤60s loop, so an undeduped log would spam while the same checks persist.
            _uncov = sorted(uncovered)
            if _uncov and _uncov != getattr(orch, "_gatecheck_uncovered_last", None):
                orch._gatecheck_uncovered_last = _uncov
                orch._logger.warning(
                    "Delivery declined on gate check(s) with NO remediation owner "
                    "(needs a fix at source or an owner mapping): %s", _uncov)
            # #1040 WEDGE DETECTOR: an unowned check is survivable while some OTHER failing
            # check still has an owner — that one gets dispatched and the run moves. When
            # EVERY failing check is unowned, nothing is dispatched at all and the decline
            # cannot clear by any action the framework will take. The run then declines every
            # tick until the wall clock, which is not a stall to diagnose but a dead end.
            #
            # r174 is exactly this and it is why it burned 80 minutes: its terminal set was
            # ['unresolved_failed_tasks', 'validation_ui_evidence_failed'] and BOTH were
            # unowned. Nothing said so — the line above reports the unowned names, and reads
            # as informational, without the one fact that makes it terminal.
            #
            # ★ `_COVERED_ELSEWHERE` is NOT treated as protective here, only as less urgent.
            # "Another mechanism owns it" is a claim about intent, and a self-heal that is not
            # firing looks exactly like one that is. Measured on `database_sql_missing`: it is
            # reported unowned in 85 runs, #74's self-heal fires in 45, and it is still present
            # near the end in 2 — so the covering mechanism works ~98% of the time and fails
            # occasionally, which is precisely the case a wedge detector exists to catch. A
            # covered-elsewhere-only decline therefore still wedges, just with a longer fuse so
            # the self-heal gets its ticks first.
            _stuck = (_uncov or _elsewhere_1040) and not _owned_1040
            if _stuck:
                _n = getattr(orch, "_gatecheck_wedged_ticks_1040", 0) + 1
                orch._gatecheck_wedged_ticks_1040 = _n
                _fuse = 1 if _uncov else 10
                if _n == _fuse or (_n > _fuse and _n % 5 == 0):
                    orch._logger.error(
                        "#1040 DELIVERY IS WEDGED: NONE of the %d failing gate check(s) was "
                        "dispatched to a lane, so this decline cannot clear by itself "
                        "(%d consecutive tick(s)). No owner: %s.%s This needs an owner in "
                        "_GATE_OWNER, an entry in _COVERED_ELSEWHERE with a reason, or a fix at "
                        "the check's source — the run will otherwise decline until the wall "
                        "clock.",
                        len(_uncov) + len(_elsewhere_1040), _n,
                        join_capped(_uncov, len(_uncov)) or "<none>",
                        (" Claimed covered elsewhere but STILL FAILING after %d tick(s), so "
                         "whatever owns them is not clearing them: %s."
                         % (_n, join_capped(_elsewhere_1040, len(_elsewhere_1040))))
                        if _elsewhere_1040 else "")
            else:
                orch._gatecheck_wedged_ticks_1040 = 0
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
