"""GateRegistry — design / visual review / retro / coverage allowlist
lifecycle, lifted out of ``WorkHub`` per the hub-responsibility-split
plan (`docs/hub_responsibility_split_plan.md`, PR 3, rank 3).

Plain-module pattern (per plan §6 Q4): not a Hub (no stores ownership,
no event framework, no snapshot/subscription wiring). Mutates the
``pages`` store that WorkHub already owns, so persistence stays
unified and there is no second source of truth. Emits the same
``workhub``-source events as before via the eventhub passed at init.

What lives here (LIVE methods, per re-audit §7.3):
  * **Design page lookup** — `get_design_page` (read-only; the
    design-submit-for-review surface was retired in favor of the
    orchestrator-hosted kickoff meeting flow — see
    `runtime/kickoff/` and `docs/pipeline_supervision_charter.md`
    §kickoff).
  * **Visual review lifecycle** — `register_visual_review_task`,
    `get_visual_review`, `list_pending_visual_reviews`,
    `list_critical_visual_reviews`, `submit_visual_review`.
  * **Retro lifecycle** — `list_retros`,
    `get_latest_retro_for_generation`.
  * **Coverage allowlist** — `list_coverage_allowlist`,
    `mark_path_intentionally_dead`.

What is INTENTIONALLY OMITTED (per re-audit §7.3 dead-helper
inventory):
  * `is_design_approved` / `is_visual_approved` (single-page
    predicates). They had zero non-test callers in the live
    runtime; the production design-approval gate happens via the
    ``design_get_status`` TOOL reading ``page.get("status")``
    directly, and the production visual-approval gate is
    ``DeliverProjectTool`` consuming
    ``list_critical_visual_reviews`` via the
    ``list_unapproved_critical`` aggregator. Carrying the dead
    predicates into GateRegistry would re-encode the
    landed-but-dead state the re-audit closed. They are removed
    from the WorkHub surface as part of PR 3 (Phase E).

Why "Q4 plain module" not "promote to Hub":
  Multiple consumers do NOT want shared stores/events on the
  combined domain — each sub-job has its own data shape, and the
  pages store is already managed by WorkHub. Hubs are reserved
  for domains where stores/event-streams need to be co-owned;
  this is a behavior boundary, not a data boundary.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional


class GateRegistry:
    """Owns design + visual + retro + coverage gate state via the
    page store. See module docstring for scope rationale."""

    # ------------------------------------------------------------------
    # Validation constants — kept here (not in WorkHub) because their
    # only readers are the gate methods below. WorkHub no longer needs
    # them once PR 3 lands.
    # ------------------------------------------------------------------
    _VALID_VISUAL_REVIEW_STATES = {"approve", "needs_revision", "comment"}
    _CRITICAL_SIMILARITY_FLOOR = 0.75
    _MIN_DEVIATIONS_FOR_APPROVE = 3
    _MIN_SUMMARY_LEN_FOR_APPROVE = 20
    _COVERAGE_ALLOWLIST_TITLE = "Coverage allowlist"

    def __init__(
        self,
        *,
        pages_store: Any,
        create_page_fn: Any,
        eventhub: Any = None,
    ) -> None:
        """``pages_store`` is the JsonStore-backed dict-like that
        WorkHub uses (``WorkHub.stores.documents``).
        ``create_page_fn`` is ``WorkHub.create_document`` — we route
        document creation through it so default kind/status conventions
        and the document_created event stay centralised on WorkHub.
        ``eventhub`` is the same handle WorkHub uses for emission;
        events stay tagged ``source_hub='workhub'`` for downstream
        listener compatibility during the delegate window."""
        self._pages = pages_store
        self._create_page = create_page_fn
        self._eventhub = eventhub

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _emit(
        self,
        event_type: str,
        payload: dict,
        recipients: Optional[List[str]] = None,
        priority: str = "normal",
    ) -> None:
        if self._eventhub:
            # ``source_hub='workhub'`` preserves the event vocabulary
            # downstream listeners already subscribe to — this is the
            # same naming WorkHub used pre-PR-3.
            # Phase 4.1c: caller="gate_registry" against source_hub="workhub"
            # is the cross-hub authorship pattern, admitted via
            # PHASE_4_1C_PUBLISH_SENTINELS["workhub"].
            self._eventhub.publish_event(
                "workhub", event_type, payload,
                recipients=recipients or [], priority=priority,
                caller="gate_registry",
            )

    def _pages_value(self) -> Dict[str, dict]:
        return self._pages.value() or {}

    # ==================================================================
    # Design page lookup (read-only)
    # ==================================================================
    # The submit_design_for_review / submit_design_review /
    # list_pending_design_reviews surface was retired on 2026-06-02.
    # Design approval is now decided in the orchestrator-hosted kickoff
    # meeting (see ``runtime/kickoff/`` and charter §kickoff);
    # ``get_design_page`` remains so downstream agents can read the page
    # status via the ``design_get_status`` tool.
    def get_design_page(self, page_id: str) -> Optional[dict]:
        page = self._pages_value().get(page_id)
        if not page or page.get("kind") != "design":
            return None
        return page

    # ==================================================================
    # Visual review lifecycle
    # ==================================================================
    def register_visual_review_task(
        self,
        route: str,
        screenshot_path: str,
        reference_path: str,
        critical: bool = False,
        agent: str = "",
    ) -> dict:
        page = self._create_page(
            title=f"Visual review: {route}",
            agent=agent or "frontend",
            kind="visual_review",
            attendees=["verifier"],
            metadata={
                "route": route,
                "screenshot_path": screenshot_path,
                "reference_path": reference_path,
                "critical": bool(critical),
                "review_history": [],
            },
        )
        # ``create_page`` assigns default_status "active" for non-design
        # kinds; the visual_review lifecycle starts at "pending".
        page_id = page["id"]
        actor = agent or "frontend"
        updated = dict(page)
        updated["status"] = "pending"
        updated["_updated_by"] = actor
        updated["_updated_at"] = time.time()
        self._pages.update(
            lambda m: m.set(page_id, updated, actor),
            change_info={"agent": actor},
        )
        return updated

    def get_visual_review(self, page_id: str) -> Optional[dict]:
        page = self._pages_value().get(page_id)
        if not page or page.get("kind") != "visual_review":
            return None
        return page

    def list_pending_visual_reviews(self) -> List[dict]:
        return [
            p for p in self._pages_value().values()
            if p.get("kind") == "visual_review"
            and p.get("status") in ("pending", "reviewing")
        ]

    def list_critical_visual_reviews(self) -> List[dict]:
        return [
            p for p in self._pages_value().values()
            if p.get("kind") == "visual_review"
            and (p.get("metadata") or {}).get("critical") is True
        ]

    def list_visual_reviews(
        self, route: Optional[str] = None,
    ) -> List[dict]:
        """Return every visual_review page (any status), optionally
        filtered to a single ``metadata.route``.

        Phase 3.9 (Path B): the ``visual:<route>`` story-gate resolver
        in story_hub reads this — it needs to see approved + rejected
        + pending pages alike, so it can map them to
        pass / fail / evidence_pending.
        """
        out = [
            p for p in self._pages_value().values()
            if p.get("kind") == "visual_review"
        ]
        if route is not None:
            out = [
                p for p in out
                if (p.get("metadata") or {}).get("route") == route
            ]
        return out

    def submit_visual_review(
        self,
        page_id: str,
        reviewer: str,
        state: str,
        similarity_score: Optional[float] = None,
        deviations: Optional[List[dict]] = None,
        summary: str = "",
    ) -> dict:
        # Review-verdict authorship lock: visual review verdicts
        # (state=approve + similarity_score) feed the delivery gate's
        # visual evaluation. Only the verifier lane may author them
        # (verifier absorbed the visual_reviewer role as part of the
        # 2026-06-02 roster reduction). register_visual_review_task
        # remains ungated — it doesn't carry a trust-bearing verdict.
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="submit_visual_review",
            agent=reviewer,
            provider=None,
            allowed_set={"verifier"},
            target_label="gate_registry.submit_visual_review",
            error_extra=(
                "visual review verdicts are authored by the "
                "verifier lane only."
            ),
        )
        page = self.get_visual_review(page_id)
        if not page:
            return {"error": f"visual_review page not found: {page_id}"}
        if state not in self._VALID_VISUAL_REVIEW_STATES:
            return {"error": f"invalid state: {state!r}"}

        if state == "approve":
            if (not isinstance(similarity_score, (int, float))
                    or isinstance(similarity_score, bool)):
                return {"error": "similarity_score required (number in [0,1])"}
            if similarity_score < 0.0 or similarity_score > 1.0:
                return {"error": (
                    f"similarity_score must be in [0,1], got {similarity_score}"
                )}
            substantive = []
            for d in (deviations or []):
                if not isinstance(d, dict):
                    continue
                aspect = (d.get("aspect") or "").strip()
                expected = (d.get("expected") or "").strip()
                actual = (d.get("actual") or "").strip()
                severity = (d.get("severity") or "").strip()
                if aspect and expected and actual and severity:
                    substantive.append({
                        "aspect": aspect, "expected": expected,
                        "actual": actual, "severity": severity,
                    })
            if len(substantive) < self._MIN_DEVIATIONS_FOR_APPROVE:
                return {"error": (
                    f"approve requires at least "
                    f"{self._MIN_DEVIATIONS_FOR_APPROVE} substantive "
                    f"deviations each with non-empty "
                    f"aspect/expected/actual/severity"
                )}
            if (not isinstance(summary, str)
                    or len(summary.strip()) < self._MIN_SUMMARY_LEN_FOR_APPROVE):
                return {"error": (
                    f"summary must be >= "
                    f"{self._MIN_SUMMARY_LEN_FOR_APPROVE} chars "
                    f"(no rubber-stamp approvals)"
                )}
            critical = (page.get("metadata") or {}).get("critical") is True
            if critical and similarity_score < self._CRITICAL_SIMILARITY_FLOOR:
                return {"error": (
                    f"critical route requires similarity_score >= "
                    f"{self._CRITICAL_SIMILARITY_FLOOR} for approve "
                    f"(got {similarity_score})"
                )}
            deviations = substantive
        elif state == "needs_revision":
            if not (deviations or []):
                return {"error": "needs_revision requires at least 1 deviation"}

        review_id = f"vrev_{uuid.uuid4().hex[:10]}"
        now = time.time()
        review = {
            "review_id": review_id, "at": now, "by": reviewer,
            "state": state,
            "similarity_score": (
                float(similarity_score)
                if isinstance(similarity_score, (int, float))
                and not isinstance(similarity_score, bool)
                else None
            ),
            "deviations": deviations or [],
            "summary": summary,
        }

        updated = dict(page)
        meta = dict(updated.get("metadata") or {})
        history = list(meta.get("review_history") or [])
        history.append(review)
        meta["review_history"] = history
        updated["metadata"] = meta

        if state == "approve":
            updated["status"] = "approved"
        elif state == "needs_revision":
            updated["status"] = "needs_revision"
        # comment: no transition

        updated["_updated_by"] = reviewer
        updated["_updated_at"] = now
        self._pages.update(
            lambda m: m.set(page_id, updated, reviewer),
            change_info={"agent": reviewer},
        )
        self._emit(
            f"visual_review_{state}", updated,
            recipients=updated.get("attendees", []) or [],
            priority="high",
        )
        return updated

    # ==================================================================
    # Retro lifecycle (read-side; submit_retro lives in retro_tools.py)
    # ==================================================================
    def list_retros(self) -> List[dict]:
        return [
            p for p in self._pages_value().values()
            if p.get("kind") == "retro"
        ]

    def get_latest_retro_for_generation(
        self, generation_id: Any,
    ) -> Optional[dict]:
        matches = [
            p for p in self.list_retros()
            if (p.get("metadata") or {}).get("generation_id") == generation_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda p: p.get("created_at", 0.0))

    # ==================================================================
    # Coverage allowlist (whitelisted intentionally-dead paths)
    # ==================================================================
    def _get_or_create_allowlist_page(
        self, agent: str = "orchestrator",
    ) -> dict:
        for page in self._pages_value().values():
            if page.get("kind") == "coverage_allowlist":
                return page
        return self._create_page(
            title=self._COVERAGE_ALLOWLIST_TITLE,
            agent=agent, kind="coverage_allowlist",
            metadata={"entries": []},
        )

    def list_coverage_allowlist(self) -> list:
        page = next(
            (p for p in self._pages_value().values()
             if p.get("kind") == "coverage_allowlist"),
            None,
        )
        if page is None:
            return []
        return list((page.get("metadata") or {}).get("entries") or [])

    def mark_path_intentionally_dead(
        self,
        path: str,
        reason: str,
        agent: str = "orchestrator",
    ) -> dict:
        if not isinstance(path, str) or not path.strip():
            return {"error": "path must be non-empty"}
        if not isinstance(reason, str) or not reason.strip():
            return {"error": "reason must be non-empty"}
        # Verdict-authoring: declares that a coverage path doesn't need
        # test evidence (the orchestrator's authoritative "skip this"
        # call). Other agents cannot bypass coverage gates via this
        # method. coverage_tools bundle restricts callers to orchestrator
        # profile (defense-in-depth).
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="mark_path_intentionally_dead",
            agent=agent,
            provider=None,
            allowed_set={"orchestrator"},
            target_label="gate_registry.mark_path_intentionally_dead",
            error_extra=(
                "orchestrator is the sole authoritative voice for "
                "declaring a path as intentionally dead."
            ),
        )
        page = self._get_or_create_allowlist_page(agent=agent)
        entry = {
            "path": path, "reason": reason, "added_by": agent,
            "added_at": time.time(),
        }
        updated = dict(page)
        meta = dict(updated.get("metadata") or {})
        entries = list(meta.get("entries") or [])
        entries.append(entry)
        meta["entries"] = entries
        updated["metadata"] = meta
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        actor = agent or "workhub"
        self._pages.update(
            lambda m: m.set(page["id"], updated, actor),
            change_info={"agent": actor},
        )
        return entry


__all__ = ["GateRegistry"]
