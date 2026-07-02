"""Milestone registry — milestones as FIRST-CLASS managed state.

A run is a sequence of MILESTONES (build phases). They used to live only as an
in-memory list in the orchestrator + a buried workhub ``milestone_plan`` decision,
so neither the orchestrator agent nor the monitor could INSPECT or MODIFY them
through the normal tool surface. This makes them first-class: a queryable,
persistent store the orchestrator drives via dedicated ``milestone_*`` tools at
kickoff (add / update / remove a FUTURE phase, set the current phase's detailed
detail). DELIVERED milestones are FROZEN — the orchestrator may only re-scope the
not-yet-started ones.

Record shape (keyed by a stable ``id``):
  {id, index (1-based order), name, version, description_slice, detail,
   detail_authored, acceptance: [...],
   status: "pending" | "active" | "delivered"}

``description_slice`` = the rough phase scope (from plan_milestones at run start).
``detail``           = the DETAILED current-phase detail the orchestrator authors at
                        kickoff (what to build THIS phase, acceptance, what's frozen).
``detail_authored``  = True once the kickoff-detail TURN has COMPLETED for this phase
                        (set on turn finalization, NOT on the first store write) — the
                        main-loop poll resolves on this flag so it never races a
                        half-finished detail.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .json_store import JsonStore

_log = logging.getLogger(__name__)

# Statuses a structural edit (update/remove/re-scope) may NOT touch.
_FROZEN_STATUSES = {"delivered"}
_VALID_STATUSES = {"pending", "active", "delivered"}


class MilestoneRegistry:
    """Persistent, tool-drivable milestone roadmap. Shares the hub store dir."""

    def __init__(self, store_dir: Path, eventhub: Any = None) -> None:
        self._store = JsonStore(Path(store_dir) / "milestones.json")
        self._eventhub = eventhub

    # ---- internal helpers ----------------------------------------------------
    def _all(self) -> Dict[str, Dict[str, Any]]:
        return {k: v for k, v in (self._store.value() or {}).items()
                if k != "_meta" and isinstance(v, dict)}

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._eventhub is None:
            return
        try:
            self._eventhub.publish_event(
                source_hub="milestones", event_type=event_type,
                payload=payload, recipients=[], priority="low")
        except Exception:
            pass  # best-effort; the store is the source of truth

    def _reindex(self, recs: List[Dict[str, Any]]) -> None:
        """Renumber ``index`` 1..N by current order and persist the whole set.

        Reads/writes ONLY via the ``m`` MapView the mutator receives — never call
        back into ``self._store`` / ``self._all()`` here (JsonStore.update already
        holds the file lock; re-entering it self-deadlocks on a second flock fd)."""
        def _mut(m):
            for k in list(m.value().keys()):
                m.delete(k)
            for i, r in enumerate(recs, start=1):
                rr = {**r, "index": i}
                m.set(rr["id"], rr, "milestones")
            return m
        self._store.update(_mut, change_info={"agent": "milestones"})

    @staticmethod
    def _norm(index: int, spec: Dict[str, Any]) -> Dict[str, Any]:
        st = str(spec.get("status") or "pending")
        return {
            "id": str(spec.get("id") or f"ms_{uuid.uuid4().hex[:8]}"),
            "index": int(index),
            "name": str(spec.get("name") or f"M{index}").strip(),
            "version": str(spec.get("version") or f"1.{index}.0").strip(),
            "description_slice": str(spec.get("description_slice") or "").strip(),
            "detail": str(spec.get("detail") or "").strip(),
            "detail_authored": bool(spec.get("detail_authored")),
            "acceptance": [str(a) for a in (spec.get("acceptance") or [])
                           if str(a).strip()],
            "status": st if st in _VALID_STATUSES else "pending",
        }

    # ---- reads ---------------------------------------------------------------
    def list_milestones(self) -> List[Dict[str, Any]]:
        return sorted(self._all().values(), key=lambda r: r.get("index", 0))

    def get(self, milestone_id: str) -> Optional[Dict[str, Any]]:
        rec = self._all().get(str(milestone_id))
        return dict(rec) if isinstance(rec, dict) else None

    def get_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        for r in self.list_milestones():
            if r.get("index") == int(index):
                return r
        return None

    def _resolve(self, ref: Any) -> Optional[Dict[str, Any]]:
        """Resolve a milestone by id (str) or 1-based index (int / digit str)."""
        if ref is None:
            return None
        s = str(ref).strip()
        rec = self.get(s)
        if rec:
            return rec
        if s.isdigit():
            return self.get_by_index(int(s))
        return None

    def get_current(self) -> Optional[Dict[str, Any]]:
        """The ``active`` milestone, else the first ``pending`` one."""
        ms = self.list_milestones()
        for r in ms:
            if r.get("status") == "active":
                return r
        for r in ms:
            if r.get("status") == "pending":
                return r
        return None

    def empty(self) -> bool:
        return not self._all()

    # ---- bulk seed (run start) ----------------------------------------------
    def set_roadmap(self, milestones: List[Dict[str, Any]],
                    agent: str = "") -> List[Dict[str, Any]]:
        """Seed the roadmap from plan_milestones at run start. Preserves any
        already-DELIVERED milestones (idempotent on resume); replaces the rest."""
        delivered = [r for r in self.list_milestones()
                     if r.get("status") in _FROZEN_STATUSES]
        kept = {r["index"]: r for r in delivered}
        merged: List[Dict[str, Any]] = []
        seen = set(kept.keys())
        for i, spec in enumerate(milestones, start=1):
            if i in kept:
                merged.append(kept[i])
            else:
                merged.append(self._norm(i, spec))
            seen.discard(i)
        # carry any delivered milestone whose index exceeded the new list length
        for idx in sorted(seen):
            merged.append(kept[idx])
        merged.sort(key=lambda r: r.get("index", 0))
        self._reindex(merged)
        self._emit("milestone_roadmap_set", {"count": len(merged)})
        return self.list_milestones()

    # ---- mutations (orchestrator milestone_* tools) --------------------------
    def add(self, *, name: str = "", version: str = "",
            description_slice: str = "", acceptance: Optional[List[str]] = None,
            after_index: Optional[int] = None, agent: str = "") -> Dict[str, Any]:
        """Insert a NEW (pending) milestone. Default: append at the end. With
        ``after_index``, insert right after that phase (later phases shift down)."""
        recs = self.list_milestones()
        spec = {"name": name, "version": version,
                "description_slice": description_slice, "acceptance": acceptance,
                "status": "pending"}
        new = self._norm(len(recs) + 1, spec)
        if after_index is None:
            recs.append(new)
        else:
            pos = max(0, min(len(recs), int(after_index)))  # 0..N
            # insert after the milestone whose index == after_index
            insert_at = next((i + 1 for i, r in enumerate(recs)
                              if r.get("index") == int(after_index)), pos)
            recs.insert(insert_at, new)
        self._reindex(recs)
        self._emit("milestone_added", {"id": new["id"], "name": new["name"]})
        return self.get(new["id"]) or new

    def update(self, ref: Any, *, name: Optional[str] = None,
               version: Optional[str] = None,
               description_slice: Optional[str] = None,
               acceptance: Optional[List[str]] = None,
               agent: str = "") -> Dict[str, Any]:
        """Re-scope a NOT-delivered milestone. Delivered phases are frozen."""
        rec = self._resolve(ref)
        if not rec:
            return {"error": f"milestone not found: {ref}"}
        if rec.get("status") in _FROZEN_STATUSES:
            return {"error": f"milestone {rec['id']} is delivered (frozen) — cannot modify"}
        upd = dict(rec)
        if name is not None:
            upd["name"] = str(name).strip()
        if version is not None:
            upd["version"] = str(version).strip()
        if description_slice is not None:
            upd["description_slice"] = str(description_slice).strip()
        if acceptance is not None:
            upd["acceptance"] = [str(a) for a in acceptance if str(a).strip()]
        self._store.set(upd["id"], upd, agent or "orchestrator")
        self._emit("milestone_updated", {"id": upd["id"]})
        return upd

    def remove(self, ref: Any, agent: str = "") -> Dict[str, Any]:
        """Remove a NOT-delivered/-active milestone; remaining phases reindex."""
        rec = self._resolve(ref)
        if not rec:
            return {"error": f"milestone not found: {ref}"}
        if rec.get("status") in _FROZEN_STATUSES or rec.get("status") == "active":
            return {"error": f"milestone {rec['id']} is {rec.get('status')} — cannot remove"}
        recs = [r for r in self.list_milestones() if r["id"] != rec["id"]]
        self._reindex(recs)
        self._emit("milestone_removed", {"id": rec["id"]})
        return {"removed": rec["id"]}

    def set_detail(self, ref: Any, detail: str, agent: str = "") -> Dict[str, Any]:
        """Set the DETAILED detail for a milestone (the orchestrator's per-phase plan).

        RACE GUARD (2026-06-25): once the kickoff-detail TURN has COMPLETED for this
        phase (``detail_authored == True``), refuse to OVERWRITE — the orchestrator
        MAIN resident loop independently re-authored the detail AFTER the kickoff turn
        finalized, clobbering the turn's authored detail with a re-run. The first
        finalized write wins; a later write to an already-authored phase is logged and
        dropped (the record is returned unchanged)."""
        rec = self._resolve(ref)
        if not rec:
            return {"error": f"milestone not found: {ref}"}
        if rec.get("detail_authored"):
            _log.info(
                "milestone M%s detail already authored; not overwriting",
                rec.get("index"))
            return rec
        _detail = str(detail or "").strip()
        upd = {**rec, "detail": _detail}
        # RESOLVE-ON-CONTENT (2026-06-25): mark detail_authored on the FIRST NON-EMPTY
        # write, so the main-loop poll (is_detail_authored) resolves the moment a real
        # detail exists — NOT only when the whole handler turn finishes. V28 wedge: the
        # orchestrator DID author the detail (set_detail succeeded) but its turn then
        # dawdled past the 240s poll (gemini MALFORMED re-rolls + extra milestone_list
        # steps), so detail_authored (marked in the handler finally) never tripped in
        # time and the detail fell back to the rough slice despite being authored. The
        # no-overwrite guard above still suppresses the resident loop's re-author (first
        # COMPLETE write wins; the prompt mandates a single set_detail then finish).
        if _detail:
            upd["detail_authored"] = True
        self._store.set(upd["id"], upd, agent or "orchestrator")
        self._emit("milestone_detail_set", {"id": upd["id"], "chars": len(_detail)})
        return upd

    def mark_detail_authored(self, ref: Any, agent: str = "") -> Dict[str, Any]:
        """Mark this phase's kickoff-detail TURN as COMPLETE (``detail_authored=True``).

        Called from the kickoff-detail handler's FINALLY block on turn completion (NOT
        on the first store write), so the main-loop poll resolves on turn COMPLETION
        rather than racing a half-finished detail. Uses the same MapView-free mutator
        pattern as the other simple mutators (``set_detail``/``mark_status``) — reads
        via ``_resolve`` then a single ``self._store.set``; does NOT re-enter the store
        lock."""
        rec = self._resolve(ref)
        if not rec:
            return {"error": f"milestone not found: {ref}"}
        upd = {**rec, "detail_authored": True}
        self._store.set(upd["id"], upd, agent or "orchestrator")
        return upd

    def is_detail_authored(self, ref: Any) -> bool:
        """True once the kickoff-detail turn for this phase has COMPLETED."""
        rec = self._resolve(ref)
        return bool(rec.get("detail_authored")) if isinstance(rec, dict) else False

    def mark_status(self, ref: Any, status: str, agent: str = "") -> Dict[str, Any]:
        rec = self._resolve(ref)
        if not rec:
            return {"error": f"milestone not found: {ref}"}
        if status not in _VALID_STATUSES:
            return {"error": f"invalid status: {status}"}
        upd = {**rec, "status": status}
        self._store.set(upd["id"], upd, agent or "orchestrator")
        self._emit("milestone_status", {"id": upd["id"], "status": status})
        return upd

    def snapshot(self) -> Dict[str, Any]:
        return {"milestones": self.list_milestones()}
