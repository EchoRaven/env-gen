"""StoryHub — Phase 3 story-gate mechanism.

Phase 3 (docs/progressive_elaboration_refactor.md §Phase 3) introduces
the "story gate" — the quality lever that refuses delivery when any
story slice lacks its evidence chain. A story is a feature slice
linking user requirements to end-to-end runtime evidence
(endpoints + tables + UI flows + probe records + visual reviews).

Per workflow w0dr9wha0 + design notes
``docs/phase_3_mechanism_design_notes_revised.md`` (commit 1fc53c10),
this module ships the mechanism:

- ``register_story`` at phase >= 3.0: actor gate
  ({orchestrator, product, planner}) + returns canonical persisted-
  shape record (without ``_synthetic`` marker). Persistence itself is
  wired in via ``StoryHub(stores=...)`` from hub_registry — when no
  store is attached (the legacy free-function call), the canonical
  record is returned without side effects.
- ``evaluate_story_gate`` at phase >= 3.0: walks each story's
  ``evidence_targets`` list, dispatches by namespace prefix
  (``api_smoke:`` / ``ui_flow:`` / ``table:`` / ``mcp:``) to the
  matching resolver, and aggregates ``ok = all(status == 'delivered')``.
  Unknown namespace prefixes (``visual:`` / ``endpoint_contract:``)
  produce ``unsupported_namespace_v1`` blockers — they're deferred to
  Phase 3.5 / 3.9.

The 4 v1 resolvers read the canonical ``verdict`` field with value
``"pass"`` (NOT ``status == "passed"`` — that was the BLOCKER B1
schema-misread fix the design notes pinned). Reader sources:

- ``api_smoke:<METHOD> <path>`` → RunHub probe records: probe.verdict == "pass"
- ``ui_flow:<flow>``           → record_validation_result rows with metadata.check='ui_flow'
- ``table:<name>``             → SchemaHub.list_tables (table present + not flagged by seed audit)
- ``mcp:<server_name>``        → RunHub mcp_probes: mcp_probe.verdict == "pass"
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

# Allowed-set for register_story actor gate. orchestrator is the
# sole story author today. Earlier drafts reserved "product" / "planner"
# as future lanes; per the 2026-06-02 cleanup discipline (no phantom
# allowlist members), they're dropped — add them back when the lane
# actually exists as a resident_lane.
_REGISTER_STORY_ALLOWED = frozenset({"orchestrator"})


def _resolve_api_smoke(reg: Any, target_key: str) -> str:
    """Resolve ``api_smoke:<METHOD> <path>`` against RunHub probe records.

    Returns 'pass' / 'fail' / 'evidence_pending'. Reads the canonical
    ``verdict`` field per design-notes Blocker 1 fix (NOT ``status``).
    """
    rest = target_key[len("api_smoke:") :].strip()
    parts = rest.split(None, 1)
    if len(parts) != 2:
        return "evidence_pending"
    method, path = parts[0].upper(), parts[1]
    try:
        runs = reg.runhub.get_runs() if hasattr(reg.runhub, "get_runs") else []
    except Exception:
        runs = []
    for run in runs or []:
        for probe in (run.get("probes") or []):
            if (probe.get("method") == method
                    and probe.get("path") == path):
                verdict = probe.get("verdict")
                if verdict == "pass":
                    return "pass"
                if verdict == "fail":
                    return "fail"
    return "evidence_pending"


def _resolve_ui_flow(reg: Any, target_key: str) -> str:
    """Resolve ``ui_flow:<flow>`` against record_validation_result rows."""
    flow = target_key[len("ui_flow:") :].strip()
    if not flow:
        return "evidence_pending"
    try:
        results = reg.get_validation_results(limit=500)
    except Exception:
        results = []
    # #1202ft -- THREE DEFECTS, EACH OF WHICH ALONE MAKES THIS RESOLVER SAY NOTHING.
    #
    # 1. TWO VOCABULARIES CONFLATED. This function's OUTPUT alphabet is
    #    "pass"/"fail"/"evidence_pending"; a validation RECORD's status is never either of
    #    the first two. `get_validation_results` canonicalises to "passed"/"failed" and the
    #    raw store carries "success"/"failure" (#752 counted 1198/310/252 of the three
    #    spellings). So `status == "pass"` could not match a single row, and the resolver
    #    returned "evidence_pending" unconditionally. Measured on tiktok-r96's ledger: 23
    #    ui_flow records, 17 passed and 6 failed, and every flow -- including one that was
    #    never recorded at all -- resolved identically to "evidence_pending". A flow with 17
    #    passing records was indistinguishable from a flow nobody ever ran.
    #    The sibling resolvers are NOT wrong in the same way and show why: _resolve_api_smoke
    #    reads a PROBE's `verdict`, where "pass"/"fail" is the real vocabulary, and its
    #    docstring already says "``verdict`` field ... (NOT ``status``)". This one reads
    #    `status` and kept the comparison that belongs to `verdict`.
    #
    # 2. THE PREDICATE MATCHED ANY ui_flow ROW. `check == "ui_flow" OR flow == flow OR ...`
    #    is true for every ui_flow record in the store, so the FIRST one encountered would
    #    have answered for every flow. It has to be "is a ui_flow record" AND "is about THIS
    #    flow".
    #
    # 3. FIRST-MATCH-WINS. The other two readers of this same store both take the newest
    #    record (#357 in flow_coverage, #757 in delivery_gate) because the store is a
    #    HISTORY. Returning on the first row let a stale failure outrank a later pass.
    #
    # 4. AND, HAVING FIXED THOSE, THE SAME TWO RULES THE OTHER READERS CARRY. This store has
    #    three consumers and each had implemented a different subset -- the shape that cost
    #    #1202fn/#1202fp/#1202fq/#1202fs. Rather than leave a fourth subset here, reuse the
    #    other readers' own functions: #1202fo's route attribution (a re-walk names the
    #    record after the route it browsed, so `/live` passing as `live_page` is evidence
    #    about the page registered there) and #401's staleness (a FAILURE predating the
    #    current build's validation means re-verify, never "passed").
    from .hub_registry import _canon_validation_status as _canon1202ft
    try:
        from .flow_coverage import (_page_name_by_route_1202fo, _route_of_url_1202fo,
                                    _latest_build_validation_time)
        _routes1202ft = _page_name_by_route_1202fo(reg) or {}
        _stale1202ft = float(_latest_build_validation_time(reg) or 0.0)
    except Exception:
        _routes1202ft, _stale1202ft = {}, 0.0
        _route_of_url_1202fo = lambda _u: ""
    _best = None
    _best_at = None
    for r in results or []:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") or {}
        if meta.get("check") != "ui_flow" and not str(
                r.get("name") or "").startswith("validation:ui_flow:"):
            continue
        _same = (meta.get("flow") == flow
                 or str(r.get("name") or "").endswith(f":ui_flow:{flow}"))
        if not _same and _routes1202ft:
            # #1202fo: attribute by the URL the record says it validated.
            _same = _routes1202ft.get(_route_of_url_1202fo(meta.get("url"))) == flow
        if not _same:
            continue
        try:
            _at = float(r.get("recorded_at") or 0) or None
        except (TypeError, ValueError):
            _at = None
        if _best is None or (_at is not None and (_best_at is None or _at >= _best_at)):
            _best, _best_at = r, _at
    if _best is None:
        return "evidence_pending"
    _canon = _canon1202ft(_best.get("status"))
    if _canon == "passed":
        return "pass"
    if _canon in ("failed", "error"):
        # #401: a failure recorded against an EARLIER build is a re-verify, not a verdict.
        # Never the other direction -- a passing record is never aged out.
        if _stale1202ft > 0 and _best_at is not None and _best_at < _stale1202ft:
            return "evidence_pending"
        return "fail"
    return "evidence_pending"


def _resolve_table(reg: Any, target_key: str) -> str:
    """Resolve ``table:<name>`` against SchemaHub.list_tables."""
    name = target_key[len("table:") :].strip()
    if not name:
        return "evidence_pending"
    try:
        tables = reg.schema_hub.list_tables()
    except Exception:
        tables = {}
    if not isinstance(tables, dict):
        return "evidence_pending"
    row = tables.get(name)
    if not row:
        return "evidence_pending"
    # status='defined' or similar canonical state-name indicates seeded.
    if row.get("status") in ("defined", "seeded", "implemented"):
        return "pass"
    return "evidence_pending"


def _resolve_mcp(reg: Any, target_key: str) -> str:
    """Resolve ``mcp:<server_name>`` against RunHub mcp_probes records."""
    server = target_key[len("mcp:") :].strip()
    if not server:
        return "evidence_pending"
    try:
        runs = reg.runhub.get_runs() if hasattr(reg.runhub, "get_runs") else []
    except Exception:
        runs = []
    for run in runs or []:
        for probe in (run.get("mcp_probes") or []):
            if probe.get("server") == server:
                verdict = probe.get("verdict")
                if verdict == "pass":
                    return "pass"
                if verdict == "fail":
                    return "fail"
    return "evidence_pending"


def _resolve_visual(reg: Any, target_key: str) -> str:
    """Resolve ``visual:<route>`` against gate_registry visual_review
    pages (Phase 3.9 Path B).

    Reads ``gate_registry.list_visual_reviews(route=<route>)`` —
    keying by ``metadata.route`` (NOT the opaque page_key, which
    was the original C1 design error per the Phase 3.9 design notes).

    Mapping:
      * status=='approved' + latest approve review.similarity_score
        >= metadata.ssim_threshold (default 0.0)  → "pass"
      * status=='approved' + similarity_score < threshold           → "fail"
      * status=='approved' + similarity_score is None               → "evidence_pending"
        (Phase 3.9 invariant: SSIM-None is pending, NOT failed —
         compute_ssim returns None on import / file / zero-variance
         failure per its documented contract)
      * status=='rejected' / 'needs_revision'                       → "fail"
      * any other status (pending / reviewing / missing)            → "evidence_pending"

    ``submit_visual_review`` is locked to {verifier} only — verifier
    now owns visual fidelity (SSIM cross-check + critical-route
    screenshots) post the 2026-06-02 roster reduction. If a real
    SSIM-based programmatic reviewer component is introduced later,
    widen the allowlist explicitly; do NOT add phantom principals.
    """
    route = target_key[len("visual:") :].strip()
    if not route:
        return "evidence_pending"
    try:
        if not hasattr(reg.gate_registry, "list_visual_reviews"):
            return "evidence_pending"
        pages = reg.gate_registry.list_visual_reviews(route=route)
    except Exception:
        return "evidence_pending"
    if not pages:
        return "evidence_pending"
    # Pick the most recently updated page for this route (multiple
    # pages can exist if the route was re-registered after a fix).
    page = max(pages, key=lambda p: p.get("_updated_at", 0))
    status = page.get("status")
    md = page.get("metadata") or {}
    if status == "approved":
        # Find the latest approve review in history; submit_visual_review
        # appends to review_history without promoting similarity_score
        # to a metadata top-level field.
        history = md.get("review_history") or []
        latest_approve = None
        for review in reversed(history):
            if review.get("state") == "approve":
                latest_approve = review
                break
        if latest_approve is None:
            return "evidence_pending"
        score = latest_approve.get("similarity_score")
        if score is None:
            return "evidence_pending"
        threshold = md.get("ssim_threshold") or 0.0
        try:
            if float(score) < float(threshold):
                return "fail"
        except (TypeError, ValueError):
            return "evidence_pending"
        return "pass"
    if status in ("rejected", "needs_revision"):
        return "fail"
    return "evidence_pending"


def _resolve_endpoint_contract(reg: Any, target_key: str) -> str:
    """Resolve ``endpoint_contract:<endpoint_id>`` against the latest
    registryhub.record_api_test record for the endpoint.

    Phase 3.5 (Path B) ties the endpoint_contract evidence namespace
    to the verdict-field amendment shipped in
    ``registryhub.record_api_test``: each contract-test record now carries
    an explicit top-level ``verdict`` derived from the writer's
    result dict (passed / result / status_code), so the resolver
    does a single non-ambiguous lookup instead of re-deriving from
    multiple possible shapes per call.

    Returns "pass" / "fail" / "evidence_pending". If multiple
    records exist for the same endpoint, the latest one (by
    created_at desc) wins — this is exactly the bug the original
    Candidate C ``results[-1]`` had; the explicit sort closes it.
    """
    endpoint_id = target_key[len("endpoint_contract:") :].strip()
    if not endpoint_id:
        return "evidence_pending"
    try:
        if not hasattr(reg.registryhub, "list_contract_test_results_sorted"):
            return "evidence_pending"
        results = reg.registryhub.list_contract_test_results_sorted(endpoint_id)
    except Exception:
        return "evidence_pending"
    if not results:
        return "evidence_pending"
    latest = results[0]
    verdict = latest.get("verdict")
    if verdict == "pass":
        return "pass"
    if verdict == "fail":
        return "fail"
    return "evidence_pending"


# Resolver registry keyed by namespace prefix. Subclasses / external
# wiring may monkeypatch this for testing-in-isolation.
_DEFAULT_RESOLVERS: Dict[str, Callable[[Any, str], str]] = {
    "api_smoke:": _resolve_api_smoke,
    "ui_flow:": _resolve_ui_flow,
    "table:": _resolve_table,
    "mcp:": _resolve_mcp,
    "endpoint_contract:": _resolve_endpoint_contract,
    "visual:": _resolve_visual,
}


def register_story(
    story_id: str,
    user_intent: str,
    evidence_targets: Optional[List[str]] = None,
    *,
    agent: str = "",
    stores: Any = None,
    eventhub: Any = None,
) -> dict:
    """Register a story (a feature slice from requirements).

    At ``phase >= 3.0``: actor gate restricts to
    ``{orchestrator, product, planner}`` (empty-actor fallthrough
    preserved); the returned record is the canonical persisted shape
    (no ``_synthetic`` marker). If a ``stores`` object is wired
    (typically by ``StoryHub.__init__`` via hub_registry), the record
    is persisted via the JsonStore canonical-writer pattern.

    Args:
        story_id: stable identifier for the story.
        user_intent: one-line description of the user-facing goal.
        evidence_targets: list of artifact IDs that delivery must verify.
        agent: caller identity (gate principal).
        stores: optional StoryHubStores handle for persistence.
        eventhub: optional EventHub for emitting ``story_registered``.

    Returns:
        The persisted (or canonical-shape) story record.
    """
    from ._role_gate import require_allowed_actor
    require_allowed_actor(
        method_name="register_story",
        agent=agent,
        provider=None,
        allowed_set=_REGISTER_STORY_ALLOWED,
        target_label="story_hub.register_story",
        error_extra=(
            "only the documented story-authoring lanes (orchestrator / "
            "product / planner) may register stories."
        ),
    )
    now = time.time()
    record: Dict[str, Any] = {
        "id": story_id,
        "user_intent": user_intent,
        "evidence_targets": list(evidence_targets or []),
        "status": "proposed",
        "agent": agent,
        "created_at": now,
        "_updated_by": agent,
        "_updated_at": now,
    }
    if stores is not None and hasattr(stores, "stories"):
        actor = agent or "story_hub"
        try:
            stores.stories.update(
                lambda m: m.set(story_id, record, actor),
                change_info={"agent": actor},
            )
        except Exception:
            # Persistence failure is non-fatal — the canonical record
            # is still returned to the caller.
            pass
    if eventhub is not None:
        try:
            eventhub.publish_event(
                source_hub="story_hub",
                event_type="story_registered",
                payload={"story_id": story_id, "agent": agent},
                caller="story_hub",
            )
        except Exception:
            pass
    return record


def evaluate_story_gate(
    stories: Optional[List[dict]] = None,
    *,
    reg: Any = None,
    resolvers: Optional[Dict[str, Callable[[Any, str], str]]] = None,
) -> dict:
    """Evaluate the Phase 3 story gate against a list of stories.

    At ``phase >= 3.0``: walks each story's ``evidence_targets``,
    dispatches by namespace prefix (``api_smoke:`` / ``ui_flow:`` /
    ``table:`` / ``mcp:``) to a resolver that reads the canonical
    writer for that namespace. Aggregates ``ok = True`` iff every
    story's status == ``"delivered"`` (computed from evidence resolution,
    not the input ``status`` field).

    Per-story ``blockers`` list captures (a) ``evidence_pending``
    or ``fail`` target_keys, and (b) ``unsupported_namespace_v1`` for
    prefixes outside the v1 vocabulary (``visual:`` / ``endpoint_contract:``
    are deferred to Phase 3.5 / 3.9).

    Pre-Phase-3 baseline: ``{ok: True, stories: []}`` regardless of input.

    Args:
        stories: list of story dicts (typically from register_story).
        reg: HubRegistry instance for resolver lookups (required at
            phase >= 3.0 unless every story has zero evidence_targets).
        resolvers: optional override of namespace→resolver dispatch
            (for tests).

    Returns:
        ``{ok: bool, stories: [{id, status, blockers: [...]}, ...]}``.
    """
    resolvers = resolvers if resolvers is not None else _DEFAULT_RESOLVERS
    out_stories: List[Dict[str, Any]] = []
    aggregate_ok = True
    for story in stories or []:
        sid = story.get("id", "")
        targets = story.get("evidence_targets") or []
        blockers: List[str] = []
        status_per_target: List[str] = []
        for tk in targets:
            tk_str = str(tk).strip()
            resolved = None
            for prefix, fn in resolvers.items():
                if tk_str.startswith(prefix):
                    try:
                        resolved = fn(reg, tk_str)
                    except Exception:
                        resolved = "evidence_pending"
                    break
            if resolved is None:
                blockers.append(f"unsupported_namespace_v1:{tk_str}")
                status_per_target.append("fail")
                continue
            status_per_target.append(resolved)
            if resolved == "fail":
                blockers.append(f"failed:{tk_str}")
            elif resolved == "evidence_pending":
                blockers.append(f"evidence_pending:{tk_str}")
        # Story status: 'delivered' iff every target passed; 'failed'
        # iff any failed; 'evidence_pending' otherwise. Empty
        # evidence_targets list = vacuously delivered.
        if any(s == "fail" for s in status_per_target):
            story_status = "failed"
        elif any(s == "evidence_pending" for s in status_per_target):
            story_status = "evidence_pending"
        else:
            story_status = "delivered"
        if story_status != "delivered":
            aggregate_ok = False
        out_stories.append({
            "id": sid,
            "status": story_status,
            "blockers": blockers,
        })
    return {"ok": aggregate_ok, "stories": out_stories}


class StoryHub:
    """HubRegistry-attached handle for Phase 3 story-gate mechanism.

    Holds optional ``stores`` (StoryHubStores) for persistence + an
    ``eventhub`` for emitting ``story_registered``. Methods delegate
    to module-level functions with these handles threaded through, so
    legacy free-function callers and ``registry.story_hub.*`` callers
    both light up the persistence + emit paths uniformly.
    """

    def __init__(
        self,
        *,
        stores: Any = None,
        eventhub: Any = None,
        resolvers: Optional[Dict[str, Callable[[Any, str], str]]] = None,
    ) -> None:
        self.stores = stores
        self.eventhub = eventhub
        self.resolvers = (
            dict(resolvers) if resolvers is not None
            else dict(_DEFAULT_RESOLVERS)
        )

    def register_story(
        self,
        story_id: str,
        user_intent: str,
        evidence_targets: Optional[List[str]] = None,
        *,
        agent: str = "",
    ) -> dict:
        return register_story(
            story_id, user_intent, evidence_targets,
            agent=agent, stores=self.stores, eventhub=self.eventhub,
        )

    def evaluate_story_gate(
        self,
        stories: Optional[List[dict]] = None,
        *,
        reg: Any = None,
    ) -> dict:
        return evaluate_story_gate(
            stories, reg=reg, resolvers=self.resolvers,
        )


__all__ = [
    "register_story",
    "evaluate_story_gate",
    "StoryHub",
    "_REGISTER_STORY_ALLOWED",
    "_DEFAULT_RESOLVERS",
]
