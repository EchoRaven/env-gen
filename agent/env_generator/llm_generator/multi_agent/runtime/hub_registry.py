"""
HubRegistry — the single runtime handle for multi-agent collaboration.

Composes the four collaboration hubs:
  - registryhub   (RegistryHub)   — API contracts, tables
  - codehub  (CodeHub)  — git worktree, PR checks, diffs
  - eventhub (EventHub) — agent status, inbox, pub/sub bridge
  - workhub  (WorkHub)  — tasks, plans, documents (kickoff/meeting/retro/project), decisions — UI pages live in RegistryHub

Usage:
    hubs = HubRegistry(base_dir, message_bus=bus)
    hubs.codehub.ensure_repo()
    hubs.registryhub.register_endpoint("GET", "/api/feed", ...)
    hubs.eventhub.get_all_agent_statuses()
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .project import (
    ProjectMetadata,
    load_project_metadata,
    save_project_metadata,
    now_ts,
)

# FIX #193 — canonical validation-record vocabulary. Writers historically passed
# whatever status string the calling agent used ('success'/'failure'/...), while
# every reader compares against 'passed'/'failed' — so real records (verified on
# instagram run80's archive) were invisible to the UI-evidence/flow/retry
# consumers. Unknown strings pass through unchanged (never guess).
_VALIDATION_STATUS_CANON = {
    "success": "passed", "passed": "passed", "pass": "passed", "ok": "passed",
    "failure": "failed", "failed": "failed", "fail": "failed",
    "skipped": "skipped", "skip": "skipped",
    "error": "error",
}


def _canon_validation_status(status: Any) -> str:
    try:
        s = str(status or "error").strip().lower()
    except Exception:
        return "error"
    return _VALIDATION_STATUS_CANON.get(s, s or "error")


# #254: provenance marker for a MEASURED runtime result (the framework's own browser walk /
# smoke probe) as opposed to an LLM agent's reported opinion. Writers set it inside
# ``metadata``; it lands flattened into the persisted evidence.
DETERMINISTIC_EVIDENCE_KEY = "deterministic_runtime_evidence"


def _is_deterministic_evidence(ev: Any) -> bool:
    if not isinstance(ev, dict):
        return False
    if ev.get(DETERMINISTIC_EVIDENCE_KEY):
        return True
    nested = ev.get("metadata")
    return isinstance(nested, dict) and bool(nested.get(DETERMINISTIC_EVIDENCE_KEY))


def _flatten_validation_metadata(ev: dict) -> dict:
    """Reader-side metadata shape: evidence minus the reserved envelope keys,
    with a NESTED evidence['metadata'] dict merged in (setdefault — explicit
    top-level keys win). Callers routinely put the check kind at
    evidence.metadata.check; readers expect metadata.check."""
    md = {k: v for k, v in (ev or {}).items()
          if k not in ("summary", "execution_mode", "duration_seconds", "artifacts")}
    nested = md.pop("metadata", None)
    if isinstance(nested, dict):
        for k, v in nested.items():
            md.setdefault(k, v)
    return md


class HubRegistry:
    """
    Thin aggregator for the four collaboration hubs.

    Exposes .registryhub, .codehub, .eventhub, .workhub plus .snapshot() and
    .get_versions().

    Disk layout: per-base-dir JSON files live under ``shared/hubs/`` (renamed
    from ``shared/crdt/`` in Cutover 9). Existing ``shared/crdt/`` directories
    are auto-migrated on first init.
    """

    def __init__(
        self,
        base_dir: Path,
        message_bus: Any = None,
        *,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        project_description: Optional[str] = None,
        human_user_id: Optional[str] = None,
    ):
        from .registryhub import RegistryHub
        from .codehub import CodeHub
        from .eventhub import EventHub
        from .hubs.runhub import RunHub
        from .workhub import WorkHub

        self.base_dir = Path(base_dir)
        self._store_dir = self._resolve_hub_dir(self.base_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        # ---- Project metadata (Cutover 26) ----
        # Existing workspace: reuse metadata as-is (kwargs do NOT clobber).
        # New workspace: create metadata from kwargs (or defaults).
        existing = load_project_metadata(self.base_dir)
        if existing is None:
            now = now_ts()
            self._project = ProjectMetadata(
                id=project_id or f"proj_{uuid.uuid4().hex[:12]}",
                name=project_name or self.base_dir.name or "Unnamed Project",
                description=project_description or "",
                created_at=now,
                last_active_at=now,
                status="active",
            )
            save_project_metadata(self.base_dir, self._project)
        else:
            self._project = existing
            # Always bump last_active_at on construction so resume is observable.
            self._project.last_active_at = now_ts()
            save_project_metadata(self.base_dir, self._project)

        self.eventhub = EventHub(self._store_dir)
        self.codehub = CodeHub(self.base_dir, self._store_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self._store_dir, eventhub=self.eventhub)
        # RENAMED 2026-06-11 (user decision, full sweep, no back-compat):
        # the CONTRACT REGISTRY hub — endpoints, tables, consumers, contract
        # tests, examples, breaking changes; MCP registry rides alongside.
        self.registryhub = RegistryHub(self._store_dir, eventhub=self.eventhub)
        self.registryhub.attach_workhub(self.workhub)
        # A1→A3 (2026-06-12): reverse handle so WorkHub can delegate its
        # ui_page/ui_component methods to the registryhub contract layer (the
        # SOLE OWNER as of A3 — workhub no longer stores ui_pages). MANDATORY:
        # workhub.update_ui_page/get_ui_pages raise without it. Must run after
        # registryhub constructs.
        self.workhub.attach_registryhub(self.registryhub)
        # Backfill any ui_pages that pre-date A1 (resume of an old run from a
        # legacy workhub_pages.json) so the registryhub read path sees them.
        # No-op on a fresh post-A3 run (workhub stores no ui_pages).
        self.registryhub.backfill_ui_pages_from_workhub()
        self.codehub.attach_workhub(self.workhub)
        self.codehub.attach_registryhub(self.registryhub)
        self.runhub = RunHub(self._store_dir, eventhub=self.eventhub)
        self.runhub.attach_registryhub(self.registryhub)

        # PR 3 / 4 / 5 of the hub-responsibility-split plan
        # (``docs/hub_responsibility_split_plan.md``, ranks 3-5):
        # the design / visual / retro / coverage gate lifecycles,
        # MCP server-tool-consumer registry, and table / seed /
        # table-consumer methods moved out of WorkHub + RegistryHub into
        # plain modules (Q4). Each module shares the relevant store
        # by reference — single source of truth. The hubs no longer
        # carry the method surfaces; callers go through these
        # registries directly. ``RunHub`` reads MCP state so its
        # ``attach_mcp_registry`` setter stays.
        from .gate_registry import GateRegistry
        self.gate_registry = GateRegistry(
            pages_store=self.workhub.stores.documents,
            create_page_fn=self.workhub.create_document,
            eventhub=self.eventhub,
        )
        from .mcp_registry import MCPRegistry
        self.mcp_registry = MCPRegistry(
            registry_store=self.registryhub._mcp_registry,
            eventhub=self.eventhub,
        )
        self.runhub.attach_mcp_registry(self.mcp_registry)
        # Milestones as FIRST-CLASS managed state (2026-06-24): a persistent,
        # tool-drivable roadmap (vs the old in-memory list + buried decision). The
        # orchestrator adds/updates/removes FUTURE phases + sets the current phase's
        # detailed brief via milestone_* tools at kickoff; delivered phases frozen.
        from .milestone_registry import MilestoneRegistry
        self.milestones = MilestoneRegistry(self._store_dir, eventhub=self.eventhub)
        # Table/schema methods live on RegistryHub directly (backend owns the API
        # and DB schema together). ``schema_hub`` is the semantic accessor name
        # for table/schema operations (``schema_hub.register_table`` reads more
        # naturally than ``registryhub.register_table``); it points at the same hub.
        self.schema_hub = self.registryhub

        # Phase 3 story-gate handle. Lifted from Phase 0.3 INERT
        # scaffolding to ACTIVE mechanism in commit c9a81e22. Owns its
        # own JsonStore-backed `stories` table via StoryHubStores
        # (mirror of RunHubStores), so register_story persists the
        # canonical record + emits the story_registered event when an
        # orchestrator/product/planner lane authors.
        from .hubs.story_hub import StoryHubStores
        from .story_hub import StoryHub
        story_hub_stores = StoryHubStores.create(self._store_dir / "story_hub")
        story_hub_stores.ensure_documents()
        self.story_hub = StoryHub(
            stores=story_hub_stores, eventhub=self.eventhub,
        )

        from .human_console import HumanConsole
        # Phase 4.7-slim Path A: propagate the project's 甲方 identity
        # into HumanConsole. Resolution order: explicit kwarg → env var
        # (handled inside HumanConsole.__init__) → "human_user" legacy
        # default. At phase>=4.7 the legacy default is rejected by
        # EventHub.publish_human_message.
        self.human_console = HumanConsole(self, default_user_id=human_user_id)

        self.bridge: Optional[Any] = None
        if message_bus is not None:
            from .hubs.eventhub.bridge import MessageBusBridge
            self.bridge = MessageBusBridge(message_bus, self.eventhub)
            self.eventhub.add_bridge(self.bridge)

        # The CURRENT run's generation id. Stays ``None`` until the
        # orchestrator calls ``attach_generation_id`` at run start. Any
        # consumer that needs to scope state to "this run" (retros,
        # circuit-breaker counters, run-locked gates) reads this. We do
        # NOT default it to ``time.time()`` — that produces a new id on
        # every read and is exactly the subtle bug the reviewer caught
        # in the retro gate.
        self.generation_id: Optional[str] = None

    def attach_generation_id(self, generation_id: Any) -> None:
        """Pin the current run's generation id so any consumer (gates,
        policies, tools) can scope state to this run. Called once at
        orchestrator startup. Subsequent calls overwrite — useful if a
        single process hosts multiple runs serially.

        Semantics of "generation":
          A generation is bound to ONE Orchestrator instance. A
          ``--resume`` constructs a fresh Orchestrator → fresh
          generation_id → retros from the original run do NOT carry
          over. Operators should expect to file a retro per actual
          delivery, including resumed runs.
        """
        self.generation_id = str(generation_id) if generation_id is not None else None

    def attach_live_agents_provider(self, provider) -> None:
        """Wire a zero-arg callable that returns currently-active agent
        ids. Forwards to RegistryHub so review-request lifecycle gates can
        validate that an invited reviewer is actually running. Safe to
        call at any time; later calls overwrite earlier ones."""
        self.registryhub.attach_live_agents_provider(provider)

    @staticmethod
    def _resolve_hub_dir(base_dir: Path) -> Path:
        """Return shared/hubs/, migrating from shared/crdt/ if needed."""
        new_dir = base_dir / "shared" / "hubs"
        old_dir = base_dir / "shared" / "crdt"
        if old_dir.exists() and not new_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            old_dir.rename(new_dir)
        return new_dir

    @property
    def hubs(self) -> "HubRegistry":
        """Self-reference so that legacy code using registry.hubs.X still works."""
        return self

    def get_versions(self) -> Dict[str, int]:
        versions: Dict[str, int] = {}
        versions.update(self.eventhub.get_versions())
        versions.update(self.codehub.get_versions())
        versions.update(self.workhub.get_versions())
        versions.update(self.registryhub.get_versions())
        versions.update(self.runhub.get_versions())
        return versions

    def snapshot(self) -> Dict[str, Any]:
        return {
            "codehub": self.codehub.snapshot(),
            "workhub": self.workhub.snapshot(),
            "registryhub": self.registryhub.snapshot(),
            "eventhub": self.eventhub.snapshot(),
            "runhub": self.runhub.snapshot(),
            "milestones": self.milestones.snapshot(),
        }

    # ------------------------------------------------------------------
    # Project metadata (Cutover 26)
    # ------------------------------------------------------------------

    @property
    def project_metadata(self) -> ProjectMetadata:
        return self._project

    def touch(self) -> None:
        """Bump last_active_at. Call after major phase transitions."""
        self._project.last_active_at = now_ts()
        save_project_metadata(self.base_dir, self._project)

    def set_project_status(self, status: str) -> None:
        """Update project status. Raises ValueError if status is unknown."""
        if status not in {"active", "paused", "completed", "failed", "archived"}:
            raise ValueError(f"unknown project status: {status!r}")
        self._project.status = status
        self._project.last_active_at = now_ts()
        save_project_metadata(self.base_dir, self._project)

    # ------------------------------------------------------------------
    # Convenience delegation methods (replaces CRDTValidationMixin)
    # ------------------------------------------------------------------

    def get_tables(self) -> Dict[str, Any]:
        """Return all tables from RegistryHub (compat delegation)."""
        return self.schema_hub.list_tables() or {}

    def update_table(self, name: str, data: dict, agent: str = "") -> dict:
        """Register or update a table via RegistryHub (compat delegation)."""
        data = dict(data or {})
        provider = data.pop("provider", "") or ""
        status = data.pop("status", "defined") or "defined"
        schema = data.pop("schema", None)
        columns = data.get("columns")
        if schema is None and columns is not None:
            schema = {"columns": columns}
        try:
            return self.schema_hub.register_table(
                name=name,
                schema=schema,
                provider=provider,
                agent=agent,
                status=status,
                **{k: v for k, v in data.items() if not k.startswith("_")},
            )
        except Exception:
            return data

    def record_validation_result(
        self,
        task_id: str,
        status: str,
        agent: str,
        summary: str = "",
        execution_mode: str = "auto",
        duration_seconds: Optional[float] = None,
        artifacts: Optional[list] = None,
        evidence: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Record a validation result via CodeHub.checks.

        FIX #254 (r51, live): the store is last-write-wins, so an LLM agent's
        evidence-free ``failure`` silently ERASED the framework's measured PASS.
        r51's authenticated walk rendered 8/8 pages cleanly and recorded 8 deterministic
        rows; within 33s the verifier overwrote 7 with rows whose whole evidence was
        ``{"flow": "<name>"}``, and the run aborted 117 min later on ui_flow_failed with
        a WORKING app. Provenance decides, not recency: a deterministic runtime record
        may be superseded only by another deterministic runtime record. The heal pipeline
        re-emits those every cycle, so genuine breakage still lands and recovery is never
        blocked; two non-deterministic writes stay last-write-wins."""
        _name = f"validation:{task_id}"
        _canon = _canon_validation_status(status)
        _incoming_det = _is_deterministic_evidence(evidence) or _is_deterministic_evidence(metadata)
        if _canon != "passed" and not _incoming_det:
            try:
                for _c in self.codehub.list_checks():
                    if _c.get("name") != _name:
                        continue
                    if (_canon_validation_status(_c.get("status")) == "passed"
                            and _is_deterministic_evidence(_c.get("evidence"))):
                        _log = getattr(self, "_logger", None)
                        if _log is not None:
                            _log.warning(
                                "#254: refused to downgrade %s to '%s' from %s — the standing "
                                "record is DETERMINISTIC runtime evidence and the incoming one "
                                "is not; only another measured result may supersede it.",
                                _name, _canon, agent)
                        return {"task_id": task_id, "status": "passed",
                                "summary": summary, "downgrade_rejected": True}
                    break
            except Exception:
                pass  # fail-open: never block a write because the store could not be read
        self.codehub.record_check(
            pr_id="main",
            name=_name,
            status=_canon,
            evidence={
                "summary": summary,
                "execution_mode": execution_mode,
                "duration_seconds": duration_seconds,
                "artifacts": artifacts or [],
                **(evidence or {}),
                **(metadata or {}),
            },
            agent=agent,
        )
        return {"task_id": task_id, "status": status, "summary": summary}

    def _validation_checks_from_codehub(self) -> list:
        try:
            checks = self.codehub.list_checks()
            return [c for c in checks if c.get("name", "").startswith("validation:")]
        except Exception:
            return []

    def get_validation_results(self, status: Optional[str] = None, agent: Optional[str] = None, limit: int = 100) -> list:
        """Return validation results from CodeHub.checks.

        FIX #193 (instagram run80 archive, verified): writers pass status
        vocabulary VERBATIM ('success' from the agent tool calls) and often nest
        the check kind under evidence['metadata'] — while every reader compares
        status=='passed' and reads metadata.get('check'). ui_flow records were
        therefore INVISIBLE to _has_passing_ui_evidence / flow_coverage / the
        retry decider / remediation-task creation, and the UI gates cleared only
        via the functionally_validated waiver. Normalize ONCE here (canonical
        status vocabulary + nested-metadata flatten) so every consumer sees the
        canonical shape."""
        checks = self._validation_checks_from_codehub()
        results = []
        for check in checks:
            ev = check.get("evidence", {}) or {}
            task_id = check.get("name", "").removeprefix("validation:")
            record = {
                "task_id": task_id,
                "name": check.get("name", ""),
                "status": _canon_validation_status(check.get("status", "error")),
                "summary": ev.get("summary", ""),
                "execution_mode": ev.get("execution_mode", "auto"),
                "metadata": _flatten_validation_metadata(ev),
                "recorded_by": check.get("agent", ""),
                "recorded_at": check.get("updated_at", 0),
                "pr_id": check.get("pr_id", "main"),
            }
            # #236 (tiktok r26, live): the check NAME already fully determines the
            # kind and target (validation:ui_flow:<flow>) but readers only trusted
            # metadata.check/.flow — the verifier recorded 35 SUCCESS ui_flow checks
            # with bare evidence and every one was INVISIBLE to flow_coverage, so
            # deliverability_ui_flow_missing held a fully-green run to the 122-min
            # no-convergence abort. Derive the missing fields from the name — the
            # other half of the #193 writer/reader normalization.
            _parts = str(check.get("name", "")).split(":", 2)
            if len(_parts) >= 2 and _parts[0] == "validation" and _parts[1]:
                record["metadata"].setdefault("check", _parts[1])
                if len(_parts) == 3 and _parts[2]:
                    record["metadata"].setdefault("flow", _parts[2])
            if status and record["status"] != status:
                continue
            if agent and record["recorded_by"] != agent:
                continue
            results.append(record)
        results.sort(key=lambda r: r.get("recorded_at", 0), reverse=True)
        return results[:max(1, int(limit))]

    def get_validation_summary(self) -> dict:
        """Return summary statistics over CodeHub validation checks."""
        records = self.get_validation_results(limit=1000)
        by_status: Dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        by_mode: Dict[str, int] = {}
        for r in records:
            s = r.get("status", "error")
            by_status[s] = by_status.get(s, 0) + 1
            m = r.get("execution_mode", "auto")
            by_mode[m] = by_mode.get(m, 0) + 1
        all_passed = len(records) > 0 and by_status.get("failed", 0) == 0 and by_status.get("error", 0) == 0
        return {
            "total": len(records),
            "by_status": by_status,
            "by_execution_mode": by_mode,
            "all_passed": all_passed,
            "recent_results": records[:10],
        }

    def create_dev_task_from_validation_failure(
        self,
        validation_task_id: str,
        publisher: str,
        domain: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        assign_to: Optional[str] = None,
        priority: str = "P1",
    ) -> dict:
        """Create a remediation dev task from a failed validation result."""
        import hashlib
        results = self.get_validation_results()
        validation = next((r for r in results if r.get("task_id") == validation_task_id), None)
        if not validation:
            return {"error": f"Validation result not found: {validation_task_id}"}
        if validation.get("status") not in {"failed", "error"}:
            return {"error": f"Validation task '{validation_task_id}' is not failed/error", "current_status": validation.get("status")}

        summary = validation.get("summary", "").strip()
        mode = validation.get("execution_mode", "auto")
        domain_val = domain or "any"
        dedupe_key = hashlib.sha256(
            f"{validation_task_id}|{validation.get('status')}|{summary}|{mode}|{domain_val}".encode()
        ).hexdigest()[:12]
        remediation_task_id = f"fix_validation_{validation_task_id}_{dedupe_key}"
        store_key = f"dev:{remediation_task_id}"

        existing = self.workhub.get_task(store_key)
        if isinstance(existing, dict):
            return {**existing, "_deduped": True, "_message": "Reused existing remediation task."}

        task_title = title or f"Fix validation failure: {validation_task_id}"
        task_desc = description or f"Fix {validation_task_id}: {summary or '(no summary)'}"
        return self.workhub.create_task(
            task_id=store_key,
            title=task_title,
            description=task_desc,
            agent=assign_to or publisher,
            domain=domain_val,
            priority=priority,
        )

    def handle_validation_failure(
        self,
        validation_task_id: str,
        publisher: str,
        domain: Optional[str] = None,
        assign_to: Optional[str] = None,
        priority: str = "P1",
        max_auto_retries: int = 1,
    ) -> dict:
        """Decide whether to retry or remediate a failed validation."""
        results = self.get_validation_results()
        validation = next((r for r in results if r.get("task_id") == validation_task_id), None)
        if not validation:
            return {"error": f"Validation result not found: {validation_task_id}"}
        if validation.get("status") not in {"failed", "error"}:
            return {"error": f"Validation task '{validation_task_id}' is not failed/error"}

        metadata = validation.get("metadata", {}) or {}
        check_type = metadata.get("check")
        smoke_checks = {"api_smoke", "api_health", "ui_smoke", "ui_page_reachable"}
        retries_used = int(metadata.get("auto_retry_attempts", 0) or 0)

        if check_type in smoke_checks and retries_used < max(0, int(max_auto_retries)):
            # Update retry count in CodeHub evidence.
            # Phase 4.6 expansion Step A (per docs/phantom_runtime_registry.md):
            # this is a system-driven auto-retry — the original code
            # used agent=publisher (whoever emitted validation_failed),
            # which would have broken Phase 4.6.1's record_check gate
            # because publisher could be any agent. Empty-actor
            # fallthrough is correct here: the retry is hub-side
            # bookkeeping, not an agent-authored verdict, and the
            # original publisher's identity is preserved in the prior
            # ch record (we only update auto_retry_attempts/decision).
            checks = self._validation_checks_from_codehub()
            for ch in checks:
                if ch.get("name") == f"validation:{validation_task_id}":
                    merged_ev = {**(ch.get("evidence") or {}), "auto_retry_attempts": retries_used + 1, "auto_retry_decision": "retry"}
                    self.codehub.record_check(
                        pr_id="main",
                        name=f"validation:{validation_task_id}",
                        status=ch.get("status", "failed"),
                        evidence=merged_ev,
                        agent="",
                    )
                    break
            return {
                "action": "retry",
                "validation_task_id": validation_task_id,
                "check": check_type,
                "retries_used": retries_used + 1,
                "max_auto_retries": max_auto_retries,
            }

        remediation = self.create_dev_task_from_validation_failure(
            validation_task_id=validation_task_id,
            publisher=publisher,
            domain=domain,
            assign_to=assign_to,
            priority=priority,
        )
        if "error" in remediation:
            return remediation
        return {
            "action": "remediate",
            "validation_task_id": validation_task_id,
            "dev_task": remediation,
        }
