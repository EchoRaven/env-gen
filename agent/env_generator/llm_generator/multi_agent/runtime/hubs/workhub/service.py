from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...eventhub import EventHub
from ... import bug_schema
from .stores import WorkHubStores


class WorkHub:
    """Notion/Jira-like workspace for docs, plans, tasks, attendees, and comments."""

    def __init__(self, hub_dir: Path, eventhub: EventHub | None = None):
        self.hub_dir = Path(hub_dir)
        self.eventhub = eventhub
        self.stores = WorkHubStores.create(self.hub_dir)
        self.stores.ensure_documents()
        # ui_page migration (A1→A3, 2026-06-12): the contract layer for
        # ui_pages moved to registryhub, which is now the SOLE OWNER. WorkHub's
        # update_ui_page/update_ui_component/get_ui_pages/get_ui_components are
        # thin delegates to it (A3) — the handle is MANDATORY for those four
        # methods (they raise RuntimeError if it is None). HubRegistry injects
        # it right after both hubs construct.
        self._registryhub = None
        # PR 3 (hub-responsibility-split plan, rank 3) moved the
        # design / visual / retro / coverage gate methods OUT of
        # WorkHub entirely — see ``multi_agent/runtime/gate_registry.py``.
        # GateRegistry shares ``self.stores.pages`` by reference
        # (HubRegistry passes the handle at init), so persistence
        # stays unified. No thin-delegate layer remains here.

    def attach_registryhub(self, registryhub) -> None:
        """Reverse handle for the ui_page contract layer. As of A3 the
        RegistryHub is the SOLE OWNER of ui_pages/ui_components, so this handle
        is MANDATORY: ``update_ui_page``/``update_ui_component``/``get_ui_pages``
        /``get_ui_components`` delegate to it and raise RuntimeError if it is
        absent. Symmetric to ``registryhub.attach_workhub``; HubRegistry wires
        both right after the hubs construct."""
        self._registryhub = registryhub

    def _emit(self, event_type: str, payload: dict, recipients: Optional[List[str]] = None, priority: str = "normal") -> None:
        if self.eventhub:
            # Phase 4.1c: caller="workhub" → owner-equals admit.
            self.eventhub.publish_event(
                "workhub", event_type, payload,
                recipients=recipients or [], priority=priority,
                caller="workhub",
            )

    # Cutover 23: task priority levels (P0 = highest urgency)
    _VALID_PRIORITIES = ("P0", "P1", "P2", "P3")
    _PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

    def create_page(self, title: str, parent: str = None, attendees: Optional[List[str]] = None, agent: str = "",
                    kind: str = "general", metadata: Optional[dict] = None) -> dict:
        """Create a coordination document (kind=kickoff/meeting/retro/project/general).

        NOTE: not a UI page — UI pages live in RegistryHub. (Method name kept
        as ``create_page`` for snapshot/resume compat; the agent-facing tool is
        ``workhub_create_document``.)
        """
        actor = agent or "workhub"
        now = time.time()
        page_id = f"page_{uuid.uuid4().hex[:10]}"
        default_status = "draft" if kind == "design" else "active"
        page = {
            "id": page_id,
            "title": title,
            "parent": parent,
            "attendees": attendees or [],
            "kind": kind,
            "status": default_status,
            "metadata": metadata or {},
            "created_by": agent,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.pages.update(lambda m: m.set(page_id, page, actor), change_info={"agent": actor})
        for attendee in attendees or []:
            self.invite_attendee(page_id, attendee, role="viewer", invited_by=agent)
        self._emit("page_created", page, recipients=attendees or [])
        return page

    # ------------------------------------------------------------------
    # PR 3 (hub-responsibility-split plan, rank 3) retired these gate
    # methods to ``multi_agent/runtime/gate_registry.py``. Q2 condition
    # ("zero in-tree callers, then drop") was met: every runtime + test
    # call site was migrated to ``hubs.gate_registry.X(...)`` in this
    # same PR, and ``tests/test_workflow_policies_gate_lint_guard.py``
    # fails the build if a new ``workhub.<retired_name>(...)`` is added.
    # Retired methods:
    #   * Design lookup: get_design_page (PR 3 -> GateRegistry; the
    #     submit_design_for_review / submit_design_review /
    #     list_pending_design_reviews surface was further retired
    #     on 2026-06-02 — design approval is now decided in the
    #     orchestrator-hosted kickoff meeting, see runtime/kickoff/),
    #     is_design_approved (re-audit §7.3 dead).
    #   * Visual lifecycle: register_visual_review_task,
    #     get_visual_review, list_pending_visual_reviews,
    #     list_critical_visual_reviews, submit_visual_review,
    #     is_visual_approved (also re-audit §7.3 dead).
    #   * Retro lifecycle: list_retros, get_latest_retro_for_generation.
    #   * Coverage allowlist: list_coverage_allowlist,
    #     mark_path_intentionally_dead.
    # ------------------------------------------------------------------

    def append_block(self, page_id: str, block: dict, agent: str = "") -> dict:
        if page_id not in self.stores.pages.value():
            return {"error": f"Page not found: {page_id}"}
        actor = agent or "workhub"
        now = time.time()
        block_id = block.get("id") or f"block_{uuid.uuid4().hex[:10]}"
        # Compute ord: use provided value, or max existing ord + 1024
        if "ord" in block:
            ord_val = block["ord"]
        else:
            existing_ords = [
                b.get("ord", 0)
                for b in self.stores.blocks.value().values()
                if b.get("page_id") == page_id
            ]
            ord_val = (max(existing_ords) if existing_ords else 0) + 1024
        payload = {
            "id": block_id,
            "page_id": page_id,
            "ord": ord_val,
            "type": block.get("type", "text"),
            "content": block.get("content", ""),
            "metadata": block.get("metadata", {}),
            "created_by": agent,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.blocks.update(lambda m: m.set(block_id, payload, actor), change_info={"agent": actor})
        self._emit("block_appended", payload, recipients=self.stores.pages.value().get(page_id, {}).get("attendees", []))
        return payload

    # Plan-store methods retired. Canonical home for per-task plan
    # is ``task.plan`` — see ``claim_task(plan=...)`` and
    # ``update_task_plan``.

    def create_task(
        self,
        title: str,
        description: str = "",
        assignee: str = None,
        plan_id: str = None,
        depends_on: Optional[List[str]] = None,
        agent: str = "",
        task_id: str = None,
        **metadata: Any,
    ) -> dict:
        # Cutover 23: priority validation (defaults to P2, must be one of P0-P3)
        priority = metadata.pop("priority", "P2")
        if priority not in self._VALID_PRIORITIES:
            return {"error": f"invalid priority {priority!r}, must be one of {self._VALID_PRIORITIES}"}
        metadata["priority"] = priority
        actor = agent or "workhub"
        now = time.time()
        task_id = task_id or f"task_{uuid.uuid4().hex[:10]}"
        task = {
            "id": task_id,
            "plan_id": plan_id,
            "title": title,
            "description": description,
            "assignee": assignee,
            "depends_on": depends_on or [],
            "status": "pending",
            "claimed_by": None,
            "claimed_at": None,
            "result": None,
            "metadata": metadata or {},
            "created_by": agent,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.tasks.update(lambda m: m.set(task_id, task, actor), change_info={"agent": actor})
        self._emit("task_created", task, recipients=[assignee] if assignee else [], priority="high" if assignee else "normal")
        return task

    def claim_task(self, task_id: str, agent: str, plan: Optional[dict] = None) -> dict:
        """Claim a pending task. Optional ``plan=`` attaches the agent's
        PlanTool snapshot to the task as a ``task.plan`` subfield."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        if task.get("status") != "pending":
            return {"error": "Task is not pending", "status": task.get("status"), "claimed_by": task.get("claimed_by")}
        if task.get("assignee") and task.get("assignee") != agent:
            return {"error": f"Task assigned to {task.get('assignee')}"}
        # Refuse claim if any dep isn't completed.
        for dep_id in (task.get("depends_on") or []):
            dep = self.stores.tasks.get(dep_id)
            if dep is None:
                return {"error": f"task blocked: depends_on references missing task: {dep_id!r}"}
            if dep.get("status") != "completed":
                return {"error": f"task blocked: dep {dep_id!r} status={dep.get('status')!r} (must be 'completed')"}
        now = time.time()
        claim_token = f"{agent}:{now}:0"
        updated = dict(task)
        updated["status"] = "in_progress"
        updated["claimed_by"] = agent
        updated["claimed_at"] = now
        updated["claim_token"] = claim_token
        if plan is not None:
            updated["plan"] = dict(plan)
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent), change_info={"agent": agent})
        verified = self.stores.tasks.get(task_id) or {}
        if verified.get("claimed_by") != agent or verified.get("claim_token") != claim_token:
            return {"error": "Claim lost during write-verify", "winner": verified.get("claimed_by")}
        self._emit("task_claimed", verified, recipients=[])
        return verified

    def update_task_plan(self, task_id: str, plan: dict, agent: str) -> dict:
        """Re-flush PlanTool snapshot to ``task.plan`` for an
        already-claimed task. Only the current claimer can flush —
        prevents cross-agent plan stomping."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        if task.get("claimed_by") != agent:
            return {
                "error": "Only claimer can update task plan",
                "claimed_by": task.get("claimed_by"),
            }
        if task.get("status") in {"completed", "failed", "cancelled"}:
            # Terminal — don't overwrite the final-state plan snapshot.
            return {
                "error": f"Cannot update plan on terminal task: {task.get('status')}",
                "status": task.get("status"),
            }
        now = time.time()
        updated = dict(task)
        updated["plan"] = dict(plan or {})
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.tasks.update(
            lambda m: m.set(task_id, updated, agent),
            change_info={"agent": agent},
        )
        return updated

    def complete_task(self, task_id: str, agent: str, result: dict = None, evidence: dict = None) -> dict:
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        if task.get("claimed_by") != agent:
            return {"error": "Only claimer can complete task", "claimed_by": task.get("claimed_by")}
        # COMPLETION INTEGRITY (2026-06-23): 'complete' asserts the work PASSED.
        # A result that explicitly signals a FAILED check (passed=False /
        # verdict=fail) must NOT be recorded as 'completed' — that hides a
        # failure as done and lets the assignee walk away instead of routing it
        # for a fix (live v7: the verifier, DENIED 'fail' on orchestrator-created
        # validate.ui_flow tasks, false-completed them with result.passed=False,
        # suppressing the real "frontend is fallback pages" defect). Framework
        # syncs complete with evidence only (no failing result), so this only
        # ever catches a lane false-completing a failed check. GENERAL invariant.
        _res = result if isinstance(result, dict) else {}
        _passed = _res.get("passed")
        _verdict = str(_res.get("verdict") or "").strip().lower()
        if _passed is False or _verdict in {"fail", "failed", "error"}:
            creator = str(task.get("created_by") or "") or "orchestrator"
            return {"error": (
                f"complete denied: result signals a FAILED check "
                f"(passed={_passed!r}, verdict={_verdict or 'n/a'}). 'complete' "
                "means the work PASSED — recording a failure as 'completed' hides "
                "it. Route the failure instead: send_message the task's creator "
                f"'{creator}' with the blocker, or bug_create → debugger for a "
                "product defect. Re-complete only once it actually passes.")}
        now = time.time()
        updated = dict(task)
        updated["status"] = "completed"
        updated["completed_at"] = now
        updated["result"] = result or {}
        updated["evidence"] = evidence or {}
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent), change_info={"agent": agent})
        self._emit("task_completed", updated, recipients=[])
        return updated

    def fail_task(self, task_id: str, agent: str, reason: str = "",
                  force: bool = False) -> dict:
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        # TASK-COMPLETION DISCIPLINE (2026-06-10, user policy): every agent
        # must COMPLETE its tasks. An agent that cannot complete one — or
        # thinks the task itself is wrong — contacts the CREATOR (send_message
        # with the blocker); only the creator/orchestrator terminates it.
        # ``force=True`` is FRAMEWORK-ONLY (idle circuit breaker).
        creator = str(task.get("created_by") or "")
        if not force and agent not in ("orchestrator", creator):
            return {"error": (
                f"fail denied: task {task_id} was created by "
                f"'{creator or 'unknown'}'. You must COMPLETE your tasks; if "
                "you are blocked or believe the task is wrong, send_message "
                f"'{creator or 'orchestrator'}' explaining the blocker — the "
                "creator decides whether to cancel it.")}
        if task.get("claimed_by") not in (agent, None) and not force and agent != "orchestrator":
            return {"error": "Only claimer/creator/orchestrator can fail task",
                    "claimed_by": task.get("claimed_by")}
        now = time.time()
        updated = dict(task)
        updated["status"] = "failed"
        updated["failed_at"] = now
        updated["fail_reason"] = reason
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent), change_info={"agent": agent})
        self._emit("task_failed", updated, recipients=[])
        return updated

    def cancel_task(self, task_id: str, agent: str, reason: str = "",
                    force: bool = False) -> dict:
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        if task.get("status") in {"completed", "failed", "cancelled"}:
            return {"error": f"Cannot cancel task in terminal state: {task.get('status')}"}
        # AUTHORIZATION (2026-06-10): only the task's creator or the
        # orchestrator may CANCEL. Live instagram run: backend bulk-cancelled
        # all 31 orchestrator-dispatched impl.* tasks ("Kickoff phase only…")
        # — the dispatch PLAN for the next phase — leaving the run with no
        # work items. An assignee that cannot do its task uses fail_task
        # (with a reason) instead; cancellation is a plan-owner decision.
        # ``force=True`` is FRAMEWORK-ONLY (idle circuit breaker / policy
        # remediation); the LLM-facing tool never passes it. COMPLETION
        # DISCIPLINE (tightened 2026-06-11): even the CLAIMER may not cancel a
        # task someone else created — live: frontend cancelled its own claimed
        # impl tasks citing hallucinated missing tools instead of contacting
        # the creator. Termination is the CREATOR'S (or orchestrator's) call.
        creator = str(task.get("created_by") or "")
        if not force and agent not in ("orchestrator", creator):
            return {"error": (
                f"cancel denied: task {task_id} was created by "
                f"'{creator or 'unknown'}' — only its creator or the "
                "orchestrator may cancel it. You must COMPLETE your tasks; "
                "if you are blocked or believe the task is wrong, "
                f"send_message '{creator or 'orchestrator'}' explaining why — "
                "the creator decides whether to cancel.")}
        # Cancellation is never silent: the event below is pushed to the
        # orchestrator (subscription, high priority), so a reason is
        # mandatory for agent-initiated cancels — it IS the notification.
        if not force and agent != "orchestrator" and not str(reason or "").strip():
            return {"error": (
                "cancel denied: a reason is required — the cancellation is "
                "reported to the orchestrator and the reason is the report. "
                "Re-call with reason=<why this task should not be done>.")}
        now = time.time()
        updated = dict(task)
        updated["status"] = "cancelled"
        updated["cancelled_at"] = now
        if reason:
            updated["cancel_reason"] = reason
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent), change_info={"agent": agent})
        self._emit("task_cancelled", updated, recipients=[], priority="high")
        return updated

    # ------------------------------------------------------------------
    # Cross-hub sync: RegistryHub/SchemaHub status='implemented' →
    # WorkHub impl_endpoint/impl_table task completed. Best-effort,
    # idempotent, never raises.
    # ------------------------------------------------------------------

    def _sync_complete_impl_task(
        self,
        task: dict,
        agent: str,
    ) -> Optional[dict]:
        """Drive ``task`` to status='completed' on behalf of ``agent``.

        State-machine compliant: claims pending tasks first, then
        completes. No-op for terminal states. Always best-effort —
        never raises (the calling RegistryHub registration must succeed
        even if the sync fails)."""
        tid = task.get("id")
        if not tid:
            return None
        status = task.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return None  # idempotent: already terminal
        try:
            if status == "pending":
                # Claim AS the assignee (mechanism #50): the sync carries
                # by-construction truth; an assignee-mismatch refusal left
                # impl.page.* stuck pending exactly like the claimed_by
                # refusal left impl.table.* stuck in_progress (#43).
                agent = task.get("assignee") or agent
                claimed = self.claim_task(tid, agent)
                if isinstance(claimed, dict) and claimed.get("error"):
                    # Dep-blocked — leave it alone.
                    return None
            elif status == "in_progress":
                claimed_by = task.get("claimed_by")
                if claimed_by and claimed_by != agent:
                    # Mechanism #43: the sync carries BY-CONSTRUCTION truth
                    # (the artifact exists on disk) — who claimed the task is
                    # irrelevant to whether it is done. Refusing here left
                    # impl.table.* stuck in_progress forever (round 32: every
                    # endpoint task dep-blocked behind impl.table.users → a
                    # 17-task cancel cascade). Complete it on the CLAIMER's
                    # behalf; the evidence stamps the sync as the source.
                    agent = claimed_by
                if not claimed_by:
                    # Edge case: in_progress without claimed_by (shouldn't
                    # happen via claim_task path). Re-claim to satisfy
                    # complete_task's claimer check.
                    claimed = self.claim_task(tid, agent)
                    if isinstance(claimed, dict) and claimed.get("error"):
                        return None
            else:
                # Unknown status — be conservative.
                return None
            return self.complete_task(
                tid, agent,
                evidence={
                    "source": "registryhub_sync",
                    "reason": "auto-completed by cross-hub sync on registryhub status=implemented",
                },
            )
        except Exception:
            return None

    # Match by canonical task_id. The kickoff write path flattens
    # ``schema_tolerance``'s task dict through ``create_task(**metadata)``,
    # which keeps only ``kind`` under ``metadata.kind`` and drops the
    # ``endpoint``/``table`` signal fields — so we identify tasks by
    # reproducing ``schema_tolerance._munge_path``.

    @staticmethod
    def _munge_endpoint_id(method: str, path: str) -> str:
        return (
            f"impl.endpoint.{method.lower()}.{path}"
            .replace("/", "_").replace("__", "_").strip("_")
        )

    @staticmethod
    def _task_kind(task: dict) -> str:
        # post-kickoff write path puts kind under metadata
        meta = task.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("kind"):
            return str(meta.get("kind"))
        # legacy / direct-write path puts kind at top level
        return str(task.get("kind") or "")

    def sync_impl_endpoint_completed(
        self, method: str, path: str, agent: str,
    ) -> Optional[dict]:
        """When RegistryHub.register_endpoint flips an endpoint to
        ``status='implemented'``, find the matching kickoff-created
        ``implement_endpoint`` task and drive it to ``completed``."""
        method_u = (method or "").upper().strip()
        path_s = (path or "").strip()
        if not method_u or not path_s:
            return None
        base_id = self._munge_endpoint_id(method_u, path_s)
        # Direct lookup by canonical id (covers the no-collision case,
        # which is the overwhelming majority — same path is rarely
        # munge-collided with a different one).
        try:
            task = self.stores.tasks.get(base_id)
        except Exception:
            task = None
        if isinstance(task, dict) and self._task_kind(task) == "implement_endpoint":
            return self._sync_complete_impl_task(task, agent)
        # Fallback: scan for collision-disambiguated ids
        # ``impl.endpoint.<m>.<p>__2``, ``__3``, ... (schema_tolerance
        # disambiguation suffix). Rare path; only triggers when two
        # distinct (method, path) pairs munge to the same base id.
        try:
            all_tasks = self.stores.tasks.value() or {}
        except Exception:
            return None
        prefix = base_id + "__"
        for tid, t in all_tasks.items():
            if not isinstance(t, dict):
                continue
            if not tid.startswith(prefix):
                continue
            if self._task_kind(t) != "implement_endpoint":
                continue
            return self._sync_complete_impl_task(t, agent)
        return None

    def sync_impl_table_completed(
        self, name: str, agent: str,
    ) -> Optional[dict]:
        """When SchemaHub.register_table flips a table to
        ``status='implemented'``, find the matching kickoff-created
        ``implement_table`` task and drive it to ``completed``."""
        name_s = (name or "").strip()
        if not name_s:
            return None
        tid = f"impl.table.{name_s}"
        try:
            task = self.stores.tasks.get(tid)
        except Exception:
            return None
        if isinstance(task, dict) and self._task_kind(task) == "implement_table":
            return self._sync_complete_impl_task(task, agent)
        return None

    def sync_impl_page_completed(
        self, name: str, agent: str,
    ) -> Optional[dict]:
        """When RegistryHub.register_ui_page flips a ui_page to
        ``status='implemented'``, find the matching kickoff-created
        ``implement_page`` task and drive it to ``completed``. A3 moved this
        cascade out of the (now thin-delegate) workhub.update_ui_page into
        RegistryHub, which calls this helper — symmetric to
        ``sync_impl_table_completed``."""
        name_s = (name or "").strip()
        if not name_s:
            return None
        tid = f"impl.page.{name_s}"
        try:
            task = self.stores.tasks.get(tid)
        except Exception:
            return None
        if isinstance(task, dict) and self._task_kind(task) == "implement_page":
            return self._sync_complete_impl_task(task, agent)
        return None

    def sync_impl_component_completed(
        self, name: str, agent: str,
    ) -> Optional[dict]:
        """When RegistryHub.register_ui_component flips a ui_component to
        ``status='implemented'``, find the matching kickoff-created
        ``implement_component`` task and drive it to ``completed``. A3 moved
        this cascade out of workhub.update_ui_component into RegistryHub."""
        name_s = (name or "").strip()
        if not name_s:
            return None
        tid = f"impl.component.{name_s}"
        try:
            task = self.stores.tasks.get(tid)
        except Exception:
            return None
        if isinstance(task, dict) and self._task_kind(task) == "implement_component":
            return self._sync_complete_impl_task(task, agent)
        return None

    # ------------------------------------------------------------------
    # Task 3: read accessors
    # ------------------------------------------------------------------

    # Sourced from the canonical schema (multi_agent/runtime/bug_schema.py)
    # so bug_tools.py and this hub can never drift on field names or
    # state values. PR 2 of the hub-responsibility-split plan.
    _OPEN_BUG_STATES = bug_schema.OPEN_STATES
    _SEVERITY_RANK = bug_schema.SEVERITY_RANK

    def _iter_bug_tasks(self):
        for task in (self.stores.tasks.value() or {}).values():
            meta = task.get("metadata") or {}
            if meta.get("kind") == bug_schema.KIND:
                yield task

    def list_open_bugs(self) -> list:
        """Return bugs whose lifecycle state is not closed/escalated, sorted P0-first then oldest-first."""
        bugs = [
            t for t in self._iter_bug_tasks()
            if (t.get("metadata") or {}).get("bug_state", "open") in self._OPEN_BUG_STATES
        ]
        bugs.sort(key=lambda t: (
            self._SEVERITY_RANK.get((t.get("metadata") or {}).get("severity", "P3"), 99),
            t.get("created_at", 0.0),
        ))
        return bugs

    def list_bugs_assigned_to(self, agent: str) -> list:
        return [t for t in self.list_open_bugs() if t.get("assignee") == agent]

    _VALID_BUG_STATES = bug_schema.VALID_STATES

    def _load_bug_or_raise(self, task_id: str) -> dict:
        task = self.stores.tasks.get(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        meta = task.get("metadata") or {}
        if meta.get("kind") != bug_schema.KIND:
            raise ValueError(f"task {task_id} is not a bug (kind={meta.get('kind')!r})")
        return task

    def update_bug_state(self, task_id: str, new_state: str, agent: str,
                         note: str = "", assignee: str = None,
                         status: str = None,
                         **metadata_updates) -> dict:
        if new_state not in self._VALID_BUG_STATES:
            raise ValueError(f"invalid bug state: {new_state!r}")
        task = self._load_bug_or_raise(task_id)
        updated = dict(task)
        meta = dict(updated.get("metadata") or {})
        meta["bug_state"] = new_state
        meta.setdefault("triage_history", []).append({
            "at": time.time(),
            "by": agent,
            "action": new_state,
            "note": note,
        })
        for k, v in metadata_updates.items():
            meta[k] = v
        updated["metadata"] = meta
        if assignee is not None:
            updated["assignee"] = assignee
        # Optionally flip the underlying task status in the SAME write (e.g. close_bug
        # sets status="completed" so downstream task queries see it) — avoids a 2nd set.
        if status is not None:
            updated["status"] = status
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent),
                                  change_info={"agent": agent})
        self._emit("bug_state_changed", updated,
                    recipients=[updated["assignee"]] if updated.get("assignee") else [],
                    priority="high")
        return updated

    def close_bug(self, task_id: str, agent: str, fix_evidence: dict = None) -> dict:
        # Single write: mark closed + flip status to completed atomically.
        return self.update_bug_state(task_id, "closed", agent=agent,
                                     note="fix verified",
                                     status="completed",
                                     fix_evidence=fix_evidence or {})

    def escalate_bug(self, task_id: str, agent: str, reason: str) -> dict:
        return self.update_bug_state(task_id, "escalated", agent=agent,
                                      note=reason, escalation_reason=reason)

    def set_task_priority(self, task_id: str, priority: str, agent: str) -> dict:
        """Update a task's priority (P0..P3) through the service API + emit an event.

        Canonical mutation path so tools never poke stores.tasks directly.
        """
        if priority not in ("P0", "P1", "P2", "P3"):
            raise ValueError(f"invalid priority: {priority!r}")
        task = self.stores.tasks.value().get(task_id)
        if not task:
            raise ValueError(f"task {task_id} does not exist")
        updated = dict(task)
        meta = dict(updated.get("metadata") or {})
        meta["priority"] = priority
        updated["metadata"] = meta
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent),
                                  change_info={"agent": agent})
        self._emit("task_updated", updated,
                   recipients=[updated["assignee"]] if updated.get("assignee") else [])
        return updated

    def get_task(self, task_id: str) -> Optional[dict]:
        """Return the task dict for task_id, or None if not found."""
        return self.stores.tasks.value().get(task_id)

    # ------------------------------------------------------------------
    # Cutover 23: priority + dependency-aware schedulers
    # ------------------------------------------------------------------

    def list_ready_tasks(self, assignee: str = None) -> list:
        """Pending tasks whose deps are all completed, sorted (priority_rank, created_at)."""
        out = []
        all_tasks = self.stores.tasks.value() or {}
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            if assignee is not None and task.get("assignee") != assignee:
                continue
            blockers = [d for d in (task.get("depends_on") or [])
                        if (all_tasks.get(d) or {}).get("status") != "completed"]
            if not blockers:
                out.append(task)
        out.sort(key=lambda t: (
            self._PRIORITY_RANK.get((t.get("metadata") or {}).get("priority", "P2"), 99),
            t.get("created_at", 0.0),
        ))
        return out

    def list_blocked_tasks(self, assignee: str = None) -> list:
        """Pending tasks with at least one incomplete dep."""
        out = []
        all_tasks = self.stores.tasks.value() or {}
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            if assignee is not None and task.get("assignee") != assignee:
                continue
            blockers = [d for d in (task.get("depends_on") or [])
                        if (all_tasks.get(d) or {}).get("status") != "completed"]
            if blockers:
                out.append(task)
        out.sort(key=lambda t: (
            self._PRIORITY_RANK.get((t.get("metadata") or {}).get("priority", "P2"), 99),
            t.get("created_at", 0.0),
        ))
        return out

    def get_blockers_for(self, task_id: str) -> list:
        """Return list of incomplete dep tasks for the given task ([] if ready)."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return []
        out = []
        for dep_id in (task.get("depends_on") or []):
            dep = self.stores.tasks.get(dep_id)
            if dep and dep.get("status") != "completed":
                out.append(dep)
        return out

    def get_blocked_by(self, task_id: str) -> list:
        """Reverse lookup: tasks whose depends_on includes task_id."""
        out = []
        for task in (self.stores.tasks.value() or {}).values():
            if task_id in (task.get("depends_on") or []):
                out.append(task)
        return out

    def list_tasks(
        self,
        assignee: str = None,
        status: str = None,
        domain: str = None,
        plan_id: str = None,
    ) -> List[dict]:
        """Return tasks filtered by the given criteria (all optional)."""
        tasks = list(self.stores.tasks.value().values())
        if assignee is not None:
            tasks = [t for t in tasks if t.get("assignee") == assignee]
        if status is not None:
            tasks = [t for t in tasks if t.get("status") == status]
        if domain is not None:
            tasks = [t for t in tasks if t.get("domain") == domain]
        if plan_id is not None:
            tasks = [t for t in tasks if t.get("plan_id") == plan_id]
        return tasks

    def available_tasks_for(self, agent: str) -> List[dict]:
        """Return pending tasks whose dependencies are all completed.

        Excludes tasks in non-pending states and tasks with any depends_on
        task that has not yet reached 'completed' status.
        """
        all_tasks = self.stores.tasks.value()
        result = []
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            deps = task.get("depends_on") or []
            deps_met = all(
                all_tasks.get(dep_id, {}).get("status") == "completed"
                for dep_id in deps
            )
            if deps_met:
                result.append(task)
        return result

    def list_stale_tasks(
        self,
        stale_seconds_pending: float = 900.0,    # 15 min unclaimed
        stale_seconds_in_progress: float = 1800.0,  # 30 min claimed-no-progress
        now_ts: Optional[float] = None,
    ) -> List[dict]:
        """Return tasks that look stuck — either unclaimed for too long
        OR claimed but with no status update in too long.

        Lets the orchestrator detect "design hasn't moved in 30 min"
        without polling per-agent state. Each returned entry adds a
        ``stale_reason`` and ``age_seconds`` for routing decisions.

        ``now_ts`` is injectable for tests.
        """
        now = float(now_ts) if now_ts is not None else time.time()
        out: List[dict] = []
        for task in self.stores.tasks.value().values():
            status = task.get("status")
            if status not in {"pending", "in_progress"}:
                continue
            assignee = task.get("assignee")
            if not assignee:
                # An unassigned pending task isn't an agent's fault — orchestrator
                # is still routing. Skip; "unrouted" is a different problem.
                continue
            created_at = float(task.get("created_at") or 0.0)
            if created_at <= 0:
                # Malformed / pre-instrumentation task — can't compute
                # age. Skip rather than flag everything as ancient.
                continue
            if status == "pending":
                age = now - created_at
                # Negative age = clock skew (created_at in the future).
                # Treat as "not stale yet" rather than wraparound.
                if age < stale_seconds_pending:
                    continue
                out.append({
                    **task,
                    "stale_reason": "unclaimed",
                    "age_seconds": int(age),
                })
                continue
            # in_progress: measure since last update (claim or any write).
            updated_at = float(
                task.get("_updated_at")
                or task.get("claimed_at")
                or created_at
                or 0.0
            )
            if updated_at <= 0:
                continue
            age = now - updated_at
            if age < stale_seconds_in_progress:
                continue
            out.append({
                **task,
                "stale_reason": "no_progress",
                "age_seconds": int(age),
            })
        return out

    def invite_attendee(self, resource_id: str, agent_id: str, role: str = "viewer", invited_by: str = "") -> dict:
        actor = invited_by or "workhub"
        now = time.time()
        key = f"{resource_id}:{agent_id}"
        attendee = {"id": key, "resource_id": resource_id, "agent_id": agent_id, "role": role, "invited_by": invited_by, "created_at": now}
        self.stores.attendees.update(lambda m: m.set(key, attendee, actor), change_info={"agent": actor})
        self._emit("attendee_invited", attendee, recipients=[agent_id], priority="normal")
        return attendee

    def comment(self, resource_id: str, body: str, agent: str = "", mentions: Optional[List[str]] = None) -> dict:
        actor = agent or "workhub"
        now = time.time()
        comment_id = f"comment_{uuid.uuid4().hex[:10]}"
        payload = {"id": comment_id, "resource_id": resource_id, "body": body, "agent": agent, "mentions": mentions or [], "created_at": now}
        self.stores.comments.update(lambda m: m.set(comment_id, payload, actor), change_info={"agent": actor})
        self._emit("comment_created", payload, recipients=mentions or [])
        return payload

    # ------------------------------------------------------------------
    # Task 4: page/plan accessors + cross-hub link methods
    # ------------------------------------------------------------------

    def get_page(self, page_id: str, with_blocks: bool = True) -> Optional[dict]:
        """Return the page dict, optionally including its blocks list."""
        page = self.stores.pages.value().get(page_id)
        if page is None:
            return None
        page = dict(page)
        if with_blocks:
            blocks = [
                b for b in self.stores.blocks.value().values()
                if b.get("page_id") == page_id
            ]
            blocks.sort(key=lambda b: b.get("ord", 0))
            page["blocks"] = blocks
        return page

    def list_pages(self, kind: str = None, status: str = None) -> List[dict]:
        """Return pages filtered by kind and/or status."""
        pages = list(self.stores.pages.value().values())
        if kind is not None:
            pages = [p for p in pages if p.get("kind") == kind]
        if status is not None:
            pages = [p for p in pages if p.get("status") == status]
        return pages

    def link_task_to_pr(self, task_id: str, pr_id: str, agent: str = "") -> dict:
        """Set linked_pr on a task."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        actor = agent or "workhub"
        now = time.time()
        updated = dict(task)
        updated["linked_pr"] = pr_id
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.tasks.update(lambda m: m.set(task_id, updated, actor), change_info={"agent": actor})
        self._emit("task_linked_pr", {"task_id": task_id, "pr_id": pr_id}, recipients=[])
        return updated

    def link_task_to_apis(self, task_id: str, endpoint_ids: List[str], agent: str = "") -> dict:
        """Set (or extend) linked_apis on a task."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        actor = agent or "workhub"
        now = time.time()
        updated = dict(task)
        existing = list(updated.get("linked_apis") or [])
        for eid in endpoint_ids:
            if eid not in existing:
                existing.append(eid)
        updated["linked_apis"] = existing
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.tasks.update(lambda m: m.set(task_id, updated, actor), change_info={"agent": actor})
        self._emit("task_linked_apis", {"task_id": task_id, "endpoint_ids": endpoint_ids}, recipients=[])
        return updated

    def comments_for(self, resource_id: str) -> List[dict]:
        """Return all comments for the given resource_id."""
        return [
            c for c in self.stores.comments.value().values()
            if c.get("resource_id") == resource_id
        ]

    # ------------------------------------------------------------------
    # Task 5: block edit + archive_page
    # ------------------------------------------------------------------

    def update_block(self, block_id: str, content: Any, agent: str = "") -> dict:
        """Replace the content of an existing block (LWW)."""
        block = self.stores.blocks.value().get(block_id)
        if block is None:
            return {"error": f"Block not found: {block_id}"}
        actor = agent or "workhub"
        now = time.time()
        updated = dict(block)
        updated["content"] = content
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.blocks.update(lambda m: m.set(block_id, updated, actor), change_info={"agent": actor})
        page_id = updated.get("page_id", "")
        recipients = self.stores.pages.value().get(page_id, {}).get("attendees", [])
        self._emit("block_updated", updated, recipients=recipients)
        return updated

    def insert_block_after(
        self,
        page_id: str,
        after_block_id: str,
        block: dict,
        agent: str = "",
    ) -> dict:
        """Insert a new block immediately after after_block_id (midpoint ord).

        If after_block_id is not found, appends at the end (max_ord + 1024).
        Returns error if page_id is unknown.
        """
        pages = self.stores.pages.value()
        if page_id not in pages:
            return {"error": f"Page not found: {page_id}"}

        # Collect all blocks for this page sorted by ord
        page_blocks = sorted(
            [b for b in self.stores.blocks.value().values() if b.get("page_id") == page_id],
            key=lambda b: b.get("ord", 0),
        )

        after_ord: Optional[int] = None
        next_ord: Optional[int] = None

        for i, b in enumerate(page_blocks):
            if b["id"] == after_block_id:
                after_ord = b.get("ord", (i + 1) * 1024)
                if i + 1 < len(page_blocks):
                    next_ord = page_blocks[i + 1].get("ord", after_ord + 2048)
                break

        if after_ord is None:
            # after_block_id not found: append at end
            max_ord = max((b.get("ord", 0) for b in page_blocks), default=0)
            new_ord = max_ord + 1024
        else:
            if next_ord is None:
                new_ord = after_ord + 1024
            else:
                new_ord = (after_ord + next_ord) // 2

        actor = agent or "workhub"
        now = time.time()
        block_id = block.get("id") or f"block_{uuid.uuid4().hex[:10]}"
        payload = {
            "id": block_id,
            "page_id": page_id,
            "ord": new_ord,
            "type": block.get("type", "text"),
            "content": block.get("content", ""),
            "metadata": block.get("metadata", {}),
            "created_by": agent,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.blocks.update(lambda m: m.set(block_id, payload, actor), change_info={"agent": actor})
        recipients = pages.get(page_id, {}).get("attendees", [])
        self._emit("block_inserted", payload, recipients=recipients)
        return payload

    def archive_page(self, page_id: str, agent: str = "") -> dict:
        """Set page status to 'archived'."""
        page = self.stores.pages.value().get(page_id)
        if page is None:
            return {"error": f"Page not found: {page_id}"}
        actor = agent or "workhub"
        now = time.time()
        updated = dict(page)
        updated["status"] = "archived"
        updated["_updated_by"] = agent
        updated["_updated_at"] = now
        self.stores.pages.update(lambda m: m.set(page_id, updated, actor), change_info={"agent": actor})
        self._emit("page_archived", updated, recipients=updated.get("attendees", []))
        return updated

    # ------------------------------------------------------------------
    # Comment thread, reactions, remove_attendee, record_decision
    # ------------------------------------------------------------------

    def reply(self, comment_id: str, body: str, agent: str = "", mentions: Optional[List[str]] = None) -> dict:
        """Reply to an existing comment, inheriting its resource_id."""
        parent = self.stores.comments.value().get(comment_id)
        if parent is None:
            return {"error": f"Comment not found: {comment_id}"}
        resource_id = parent.get("resource_id", "")
        actor = agent or "workhub"
        now = time.time()
        reply_id = f"comment_{uuid.uuid4().hex[:10]}"
        payload = {
            "id": reply_id,
            "resource_id": resource_id,
            "parent_id": comment_id,
            "body": body,
            "agent": agent,
            "mentions": mentions or [],
            "created_at": now,
        }
        self.stores.comments.update(lambda m: m.set(reply_id, payload, actor), change_info={"agent": actor})
        self._emit("comment_replied", payload, recipients=mentions or [])
        return payload

    def react(self, comment_id: str, reaction: str, agent: str) -> dict:
        """Store a reaction to a comment (LWW keyed {comment_id}:{agent})."""
        actor = agent or "workhub"
        now = time.time()
        key = f"{comment_id}:{agent}"
        payload = {
            "id": key,
            "comment_id": comment_id,
            "reaction": reaction,
            "agent": agent,
            "created_at": now,
        }
        self.stores.reactions.update(lambda m: m.set(key, payload, actor), change_info={"agent": actor})
        self._emit("comment_reacted", payload, recipients=[])
        return payload

    def remove_attendee(self, resource_type: str, resource_id: str, agent_id: str, by: str) -> dict:
        """Soft-delete an attendee record via composite key."""
        key = f"{resource_id}:{agent_id}"
        existing = self.stores.attendees.value().get(key, {})
        actor = by or "workhub"
        now = time.time()
        updated = {
            **existing,
            "id": key,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "agent_id": agent_id,
            "_removed": True,
            "_removed_by": by,
            "_removed_at": now,
        }
        self.stores.attendees.update(lambda m: m.set(key, updated, actor), change_info={"agent": actor})
        self._emit("attendee_removed", updated, recipients=[agent_id])
        return updated

    # ------------------------------------------------------------------
    # Phase C M1: Kickoff meeting primitives (create_meeting,
    # add_meeting_decision, close_meeting). Per docs/plan_kickoff_refactor.md
    # §217-225 and docs/pipeline_supervision_charter.md §5. Each method
    # follows the closed-by-construction store-update pattern:
    #   stores.<X>.update(lambda m: m.set(id, payload, actor),
    #                     change_info={"agent": actor})
    # then ``self._emit(...)``. Identities are caller-injected (no phantom
    # defaults); empty values raise ValueError per charter no-fallback rule.
    # ------------------------------------------------------------------

    def create_meeting(
        self,
        agenda: str,
        attendees: List[str],
        milestone_index: int,
        kind: str = "kickoff",
        metadata: Optional[dict] = None,
        agent: str = "",
    ) -> dict:
        """Create a meeting document (default kind='kickoff', status='open').

        NOT a delegate of ``create_page``: meetings differ in three
        meeting-specific ways that justify the inline construction here
        (charter §8 "delete don't shim" — duplicating one short page-dict
        literal beats forking ``create_page``'s signature to thread
        meeting-only knobs through it):
            * Attendees join with ``role='participant'`` (vs page's
              ``'viewer'`` default) since meeting attendees are active
              participants, not passive readers.
            * Default ``status`` is ``'open'`` for kind in
              ('kickoff', 'meeting') — these are live-while-running, not
              ``'active'`` long-lived docs nor ``'draft'`` design pages.
            * Emits ``meeting_created`` (NOT ``page_created``) so
              meeting-specific subscribers (e.g. milestone tracker) can
              react without re-filtering page-created on kind.
        Agenda + attendees + ``milestone_index`` + caller-supplied
        metadata are merged into ``page.metadata`` so the canonical
        record of *why* the meeting was called lives next to its
        produced artifacts after close.

        Identity + input discipline (charter §no-back-compat):
            * ``agenda`` must be non-empty.
            * ``attendees`` must be a non-empty list.
            * ``milestone_index`` must be a non-negative int (the
              kickoff protocol requires every meeting to be anchored to
              the milestone it kicks off — no orphan meetings).
            * ``agent`` must be non-empty (caller must inject the
              actor — no fallback identity).
        Raises ``ValueError`` if any required value is missing/empty
        or ``milestone_index`` is not a non-negative int.
        """
        if not agenda:
            raise ValueError("create_meeting requires non-empty agenda")
        if not attendees:
            raise ValueError("create_meeting requires non-empty attendees")
        # Defunct-lane guard: `design` was merged into frontend and `database` into
        # backend — neither is a live agent. Drop them so a hallucinated roster can
        # never create a meeting that invites/notifies a lane that no longer exists
        # (the dead-attendee bug). Real lanes: backend / frontend / verifier.
        attendees = [a for a in attendees
                     if str(a).strip().lower() not in {"design", "database"}]
        if not attendees:
            raise ValueError(
                "create_meeting attendees were all defunct lanes (design/database); "
                "real lanes are backend/frontend/verifier")
        if not agent:
            raise ValueError("create_meeting requires non-empty agent")
        if not isinstance(milestone_index, int) or isinstance(milestone_index, bool):
            raise ValueError(
                "create_meeting requires int milestone_index"
            )
        if milestone_index < 0:
            raise ValueError(
                "create_meeting requires non-negative milestone_index"
            )
        merged_metadata: dict = {
            **(metadata or {}),
            "agenda": agenda,
            "attendees": list(attendees),
            "milestone_index": milestone_index,
            "decisions": [],
            "produced_artifacts": [],
            "phase": "open",
        }
        now = time.time()
        page_id = f"page_{uuid.uuid4().hex[:10]}"
        default_status = "open" if kind in ("kickoff", "meeting") else (
            "draft" if kind == "design" else "active"
        )
        page = {
            "id": page_id,
            "title": agenda,
            "parent": None,
            "attendees": list(attendees),
            "kind": kind,
            "status": default_status,
            "metadata": merged_metadata,
            "created_by": agent,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self.stores.pages.update(
            lambda m: m.set(page_id, page, agent),
            change_info={"agent": agent},
        )
        for attendee in attendees:
            self.invite_attendee(page_id, attendee, role="participant", invited_by=agent)
        self._emit("meeting_created", page, recipients=list(attendees))
        return page

    def add_meeting_decision(
        self,
        meeting_id: str,
        decision: dict,
        agent: str = "",
        milestone_index: Optional[int] = None,
    ) -> dict:
        """Append a decision dict to meeting.metadata['decisions'] (atomic).

        The append happens inside the JsonStore ``update`` lambda so the
        whole read-modify-write executes against the live in-store value
        at commit time — concurrent ``add_meeting_decision`` calls cannot
        clobber each other (mirrors the LWW-via-lambda pattern used by
        every other write helper in this module).

        Identity + input discipline:
            * ``meeting_id`` must reference an existing page (returns an
              ``{'error': ...}`` dict otherwise — mirrors archive_page).
            * ``decision`` must be a non-empty dict.
            * ``agent`` must be non-empty.
            * ``milestone_index`` is optional; when provided it MUST be
              a non-negative int and is persisted on the appended
              decision row as ``decision_entry['milestone_index']`` for
              audit (caller may omit when the decision is anchored to
              the meeting's own milestone — the meeting already carries
              ``milestone_index`` in its metadata).
        Raises ``ValueError`` for empty agent / decision or a malformed
        ``milestone_index``.
        """
        if not agent:
            raise ValueError("add_meeting_decision requires non-empty agent")
        if not decision or not isinstance(decision, dict):
            raise ValueError("add_meeting_decision requires non-empty dict decision")
        if milestone_index is not None:
            if (
                not isinstance(milestone_index, int)
                or isinstance(milestone_index, bool)
                or milestone_index < 0
            ):
                raise ValueError(
                    "add_meeting_decision milestone_index must be a non-negative int"
                )
        if meeting_id not in self.stores.pages.value():
            return {"error": f"Meeting not found: {meeting_id}"}
        now = time.time()
        decision_entry = {
            **decision,
            "recorded_by": agent,
            "recorded_at": now,
        }
        if milestone_index is not None:
            decision_entry["milestone_index"] = milestone_index

        def _mutate(m):
            current = m.get(meeting_id)
            if current is None:
                return m
            updated = dict(current)
            meta = dict(updated.get("metadata") or {})
            decisions = list(meta.get("decisions") or [])
            decisions.append(decision_entry)
            meta["decisions"] = decisions
            updated["metadata"] = meta
            updated["_updated_by"] = agent
            updated["_updated_at"] = now
            return m.set(meeting_id, updated, agent)

        self.stores.pages.update(_mutate, change_info={"agent": agent})
        page_after = self.stores.pages.value().get(meeting_id) or {}
        # Deliver via SUBSCRIPTION, not an all-attendees broadcast. The ONLY
        # consumer of meeting_decision_added is the orchestrator (kickoff synthesis
        # trigger — its lone subscriber, agent_subscriptions.py). The other
        # attendees authored their OWN decisions and wake on kickoff phase/revision
        # requests, never on each other's decisions — so broadcasting to all
        # attendees just floods every lane's inbox (run v11: 84 decisions × 4
        # attendees = 336 inbox items, 252 of them pure noise). recipients=[] lets
        # publish_event fan out to subscribers only (the orchestrator). The
        # decisions themselves remain on the meeting page for anyone who queries it.
        self._emit(
            "meeting_decision_added",
            {"meeting_id": meeting_id, "decision": decision_entry},
            recipients=[],
        )
        return page_after

    def close_meeting(
        self,
        meeting_id: str,
        produced_artifacts: List[str],
        metadata_extra: Optional[dict] = None,
        agent: str = "",
        milestone_index: Optional[int] = None,
    ) -> dict:
        """Close a meeting document: flip status to 'closed', record artifacts.

        Symmetric to ``archive_page`` but specialized for meetings: stores
        the canonical list of artifacts the meeting produced (page ids,
        plan ids, decision ids, etc) on ``metadata['produced_artifacts']``
        so downstream tasks can reference them without re-scanning the
        decisions list. Emits ``meeting_closed`` (NOT ``kickoff_complete``
        — the kickoff-complete event is the kickoff orchestrator's
        responsibility, not the bare ``close_meeting`` primitive).

        Identity + input discipline:
            * ``meeting_id`` must reference an existing page (returns
              ``{'error': ...}`` dict otherwise).
            * ``produced_artifacts`` must be a list (may be empty — a
              meeting that closes with no artifacts is a real,
              recordable outcome, not an error).
            * ``agent`` must be non-empty.
            * ``milestone_index`` is optional; when provided it MUST be
              a non-negative int and is persisted on the closed page's
              ``metadata['milestone_index']`` (overwriting any prior
              value) so an audit-time scan of closed meetings can
              recover the milestone anchor even if the original
              ``create_meeting`` metadata is missing the field.
        Raises ``ValueError`` for empty agent, non-list artifacts, or a
        malformed ``milestone_index``.
        """
        if not agent:
            raise ValueError("close_meeting requires non-empty agent")
        if not isinstance(produced_artifacts, list):
            raise ValueError("close_meeting requires list produced_artifacts")
        if milestone_index is not None:
            if (
                not isinstance(milestone_index, int)
                or isinstance(milestone_index, bool)
                or milestone_index < 0
            ):
                raise ValueError(
                    "close_meeting milestone_index must be a non-negative int"
                )
        if meeting_id not in self.stores.pages.value():
            return {"error": f"Meeting not found: {meeting_id}"}
        now = time.time()
        artifacts_snapshot = list(produced_artifacts)
        extras = dict(metadata_extra or {})
        if milestone_index is not None:
            extras["milestone_index"] = milestone_index

        def _mutate(m):
            current = m.get(meeting_id)
            if current is None:
                return m
            updated = dict(current)
            meta = dict(updated.get("metadata") or {})
            meta.update(extras)
            meta["produced_artifacts"] = artifacts_snapshot
            meta["phase"] = "closed"
            updated["metadata"] = meta
            updated["status"] = "closed"
            updated["closed_at"] = now
            updated["closed_by"] = agent
            updated["_updated_by"] = agent
            updated["_updated_at"] = now
            return m.set(meeting_id, updated, agent)

        self.stores.pages.update(_mutate, change_info={"agent": agent})
        page_after = self.stores.pages.value().get(meeting_id) or {}
        self._emit(
            "meeting_closed",
            {
                "meeting_id": meeting_id,
                "produced_artifacts": artifacts_snapshot,
                "page": page_after,
            },
            recipients=page_after.get("attendees", []),
        )
        return page_after

    def record_decision(self, page_id: str, title: str, options: list, chosen: str, reason: str, agent: str = "") -> dict:
        """Append a decision block to the document (page_id) and record in decisions store."""
        if page_id not in self.stores.pages.value():
            return {"error": f"Page not found: {page_id}"}
        content = {"title": title, "options": options, "chosen": chosen, "reason": reason}
        block = self.append_block(page_id, {"type": "decision", "content": content}, agent=agent)
        actor = agent or "workhub"
        now = time.time()
        decision_id = f"decision_{uuid.uuid4().hex[:10]}"
        decision = {
            "id": decision_id,
            "page_id": page_id,
            "block_id": block.get("id"),
            "title": title,
            "options": options,
            "chosen": chosen,
            "reason": reason,
            "agent": agent,
            "created_at": now,
        }
        self.stores.decisions.update(lambda m: m.set(decision_id, decision, actor), change_info={"agent": actor})
        self._emit("decision_recorded", decision, recipients=[])
        return decision

    # ------------------------------------------------------------------
    # UI Page helpers
    # ------------------------------------------------------------------

    def update_ui_page(self, name: str, data: dict, agent: str = "") -> dict:
        """Thin delegate to ``RegistryHub.register_ui_page`` (A3, 2026-06-12).

        The RegistryHub is now the SOLE OWNER of ui_pages — workhub no longer
        stores them. The snake-normalize, the implemented→defined lifecycle
        downgrade (mechanism #54), the impl.page.<name> cascade (mechanism #50),
        and the event emit all live in ``register_ui_page`` now. This method
        just unpacks the flat ``data`` dict into that method's kwargs; any
        remaining keys (e.g. ``reference_image``/``notes``) ride through as
        ``**metadata`` onto the contract record."""
        if self._registryhub is None:
            raise RuntimeError(
                "WorkHub.update_ui_page requires an attached RegistryHub")
        data = dict(data or {})
        return self._registryhub.register_ui_page(
            name,
            route=data.pop("route", ""),
            component=data.pop("component", ""),
            apis_used=data.pop("apis_used", None),
            components=data.pop("components", None),
            path=data.pop("path", ""),
            status=data.pop("status", "defined"),
            agent=agent,
            **{k: v for k, v in data.items() if not str(k).startswith("_")},
        )

    def update_ui_component(self, name: str, data: dict, agent: str = "") -> dict:
        """Thin delegate to ``RegistryHub.register_ui_component`` (A3). The
        RegistryHub owns ui_components; workhub no longer stores them.
        Mechanism #52 (user design): pages USE components, components CALL
        APIs — the component is the API-owning layer; the page rolls up."""
        if self._registryhub is None:
            raise RuntimeError(
                "WorkHub.update_ui_component requires an attached RegistryHub")
        data = dict(data or {})
        return self._registryhub.register_ui_component(
            name,
            component=data.pop("component", ""),
            apis_used=data.pop("apis_used", None),
            status=data.pop("status", "defined"),
            agent=agent,
            **{k: v for k, v in data.items() if not str(k).startswith("_")},
        )

    def get_ui_components(self) -> Dict[str, dict]:
        """Thin delegate to ``RegistryHub.list_ui_components`` (A3)."""
        if self._registryhub is None:
            raise RuntimeError(
                "WorkHub.get_ui_components requires an attached RegistryHub")
        return self._registryhub.list_ui_components()

    def get_ui_pages(self) -> Dict[str, dict]:
        """Thin delegate to ``RegistryHub.list_ui_pages`` (A3)."""
        if self._registryhub is None:
            raise RuntimeError(
                "WorkHub.get_ui_pages requires an attached RegistryHub")
        return self._registryhub.list_ui_pages()

    # ------------------------------------------------------------------
    # Project helpers
    # ------------------------------------------------------------------

    def set_project_info(self, name: str, description: str = "", agent: str = "") -> dict:
        """Upsert a project page."""
        page_id = f"page:project:{name}"
        actor = agent or "workhub"
        now = time.time()
        existing = self.stores.pages.get(page_id)
        payload = {
            **(existing or {}),
            "id": page_id,
            "title": name,
            "kind": "project",
            "parent": None,
            "status": (existing or {}).get("status") or "active",
            "description": description,
            "attendees": (existing or {}).get("attendees") or [],
            "_updated_by": agent,
            "_updated_at": now,
        }
        if existing is None:
            payload["created_by"] = agent
            payload["created_at"] = now
        self.stores.pages.update(lambda m: m.set(page_id, payload, actor), change_info={"agent": actor})
        self._emit("project_info_set", payload, recipients=[])
        return payload

    def set_project_phase(self, name: str, phase: str, agent: str = "", reason: str = "") -> dict:
        """Append a project_phase block to the project page, auto-creating if needed."""
        page_id = f"page:project:{name}"
        if not self.stores.pages.get(page_id):
            self.set_project_info(name, agent=agent)
        return self.append_block(page_id, {
            "type": "project_phase",
            "content": {"phase": phase, "reason": reason},
        }, agent=agent)

    def get_project_status(self, name: str = None) -> dict:
        """Return the most-recently-updated project page with its latest phase."""
        pages = [p for p in self.stores.pages.value().values() if p.get("kind") == "project"]
        if name is not None:
            pages = [p for p in pages if p.get("title") == name]
        if not pages:
            return {}
        pages.sort(key=lambda p: p.get("_updated_at", 0), reverse=True)
        page = pages[0]
        blocks = [
            b for b in self.stores.blocks.value().values()
            if b.get("page_id") == page["id"] and b.get("type") == "project_phase"
        ]
        blocks.sort(key=lambda b: b.get("_updated_at", 0), reverse=True)
        latest_phase = (blocks[0]["content"] if blocks else {}) or {}
        return {**page, "phase": latest_phase.get("phase"), "phase_reason": latest_phase.get("reason")}

    # ------------------------------------------------------------------
    # Knowledge / share_implementation helpers
    # ------------------------------------------------------------------

    def share_implementation(self, title: str, content: str, agent: str = "", **metadata) -> dict:
        """Append a knowledge block to the shared knowledge page."""
        page_id = "page:knowledge"
        actor = agent or "workhub"
        now = time.time()
        if not self.stores.pages.get(page_id):
            self.stores.pages.update(lambda m: m.set(page_id, {
                "id": page_id,
                "title": "Knowledge",
                "kind": "knowledge",
                "parent": None,
                "status": "active",
                "attendees": [],
                "created_by": agent,
                "created_at": now,
                "_updated_by": agent,
                "_updated_at": now,
            }, actor), change_info={"agent": actor})
        return self.append_block(page_id, {
            "type": "knowledge",
            "content": {"title": title, "body": content, **metadata},
        }, agent=agent)

    def get_shared_implementations(self, since_ts: float = None) -> list:
        """Return knowledge blocks, optionally filtered by timestamp."""
        blocks = [
            b for b in self.stores.blocks.value().values()
            if b.get("page_id") == "page:knowledge" and b.get("type") == "knowledge"
        ]
        if since_ts is not None:
            blocks = [b for b in blocks if b.get("_updated_at", 0) >= since_ts]
        blocks.sort(key=lambda b: b.get("_updated_at", 0), reverse=True)
        return blocks

    def get_versions(self) -> Dict[str, int]:
        return self.stores.versions()

    def snapshot(self) -> Dict[str, Any]:
        return self.stores.snapshot()
