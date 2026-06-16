from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def _summarize_step_trace(step_trace: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce a full per-step trace to a small, bounded summary.

    Event-store efficiency (#5): the agent_status heartbeat is an
    append-only event; persisting the full ``step_trace`` (every stage's
    payload/metadata) bloated the store for no consumer. This keeps only a
    handful of scalar fields so the heartbeat stays tiny while still
    surfacing useful liveness signal (step number, which stages ran, and
    the most recent stage). Domain-agnostic — no app/stage specifics.
    """
    if not isinstance(step_trace, dict):
        return {}
    stages = step_trace.get("stages") or {}
    if not isinstance(stages, dict):
        stages = {}
    executed = [name for name, info in stages.items()
                if isinstance(info, dict) and info.get("executed")]
    last_stage = next(reversed(stages), None) if stages else None
    return {
        "step": step_trace.get("step"),
        "stage_count": len(stages),
        "executed_stage_count": len(executed),
        "last_stage": last_stage,
        "mode_after": step_trace.get("mode_after"),
    }


class AgentStepHelperMixin:
    @staticmethod
    def _format_step_reminder_lines(value: Any, indent: str = "") -> List[str]:
        """Render flexible reminder content into readable prompt lines."""
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [f"{indent}{line}" for line in text.splitlines()] if text else []
        if isinstance(value, (list, tuple, set)):
            lines: List[str] = []
            for item in value:
                rendered = AgentStepHelperMixin._format_step_reminder_lines(item, indent=f"{indent}  ")
                if not rendered:
                    continue
                first, *rest = rendered
                lines.append(f"{indent}- {first.strip()}")
                lines.extend(rest)
            return lines
        if isinstance(value, dict):
            lines = []
            for key, item in value.items():
                rendered = AgentStepHelperMixin._format_step_reminder_lines(item, indent=f"{indent}  ")
                if not rendered:
                    continue
                first, *rest = rendered
                lines.append(f"{indent}- {key}: {first.strip()}")
                lines.extend(rest)
            return lines
        return [f"{indent}{str(value)}"]

    def _build_step_reminder_prompt(self) -> Optional[str]:
        """Build a fixed reminder block injected at the start of every step."""
        reminders = list(getattr(self, "_step_reminders", []) or [])
        if not reminders:
            return None

        parts = [
            "## Step Opening Reminders",
            "Review these pinned reminders before doing anything in this step.",
        ]
        for idx, reminder in enumerate(reminders, start=1):
            if isinstance(reminder, str):
                parts.append(f"{idx}. {reminder}")
                continue
            if isinstance(reminder, dict):
                title = str(reminder.get("title") or reminder.get("name") or f"Reminder {idx}").strip()
                content = reminder.get("content", reminder.get("value", reminder.get("items")))
                parts.append(f"{idx}. {title}")
                rendered = self._format_step_reminder_lines(content, indent="   ")
                if rendered:
                    parts.extend(rendered)
                continue
            rendered = self._format_step_reminder_lines(reminder)
            if rendered:
                parts.append(f"{idx}. {rendered[0].strip()}")
                parts.extend(rendered[1:])
        return "\n".join(parts)

    @staticmethod
    def _parse_action_status(text: str) -> Optional[str]:
        """Parse ACTION_STATUS marker from model text."""
        lowered = (text or "").lower()
        for marker in (
            "action_status: stop",
            "action_status: complete",
            "action status: stop",
            "action status: complete",
        ):
            if marker in lowered:
                return "stop"
        for marker in ("action_status: continue", "action status: continue"):
            if marker in lowered:
                return "continue"
        return None

    def _artifact_kind_for_path(self, path: str) -> str:
        normalized = str(path or "").replace("\\", "/")
        suffix = Path(normalized).suffix.lower()
        if normalized.startswith("design/"):
            return "design"
        if "/backend/" in f"/{normalized}" or normalized.startswith("app/backend/"):
            return "backend_code"
        if "/frontend/" in f"/{normalized}" or normalized.startswith("app/frontend/"):
            return "frontend_code"
        if "/database/" in f"/{normalized}" or suffix in {".sql"}:
            return "database_code"
        if suffix in {".json", ".yaml", ".yml"}:
            return "structured_data"
        if suffix in {".md", ".txt"}:
            return "document"
        return "file"

    def _sync_plan_index_to_hub(self, source_action: str) -> bool:
        try:
            from tools.reasoning_tools import PlanTool

            plan_tool = PlanTool.get_instance(getattr(self, "agent_id", "default"))
            if hasattr(plan_tool, "set_agent"):
                plan_tool.set_agent(self)
            if hasattr(plan_tool, "_sync_plan_index"):
                plan_tool._sync_plan_index(source_action=source_action)
                return True
        except Exception as e:
            self._logger.debug(f"[{self.agent_id}] automatic plan hub sync skipped: {e}")
        return False

    def _auto_sync_hub_state(
        self,
        *,
        step: int,
        files_created: List[str],
        files_modified: List[str],
        step_trace: Dict[str, Any],
        status: str,
    ) -> Dict[str, Any]:
        """Synchronize mandatory hub heartbeat state without asking the model."""
        hubs = getattr(self, "_hubs", None)
        if not hubs:
            return {"synced": False, "reason": "hubs_unavailable"}

        synced: Dict[str, Any] = {
            "synced": True,
            "agent_status": False,
            "plan_index": False,
            "artifacts": 0,
        }
        try:
            if hasattr(hubs, "ensure_core_documents"):
                hubs.ensure_core_documents()
        except Exception as e:
            synced["ensure_error"] = str(e)

        try:
            hubs.hubs.eventhub.record_agent_status(
                getattr(self, "agent_id", "unknown"),
                {
                    "status": status,
                    "current_task": getattr(self, "_active_stage", "action"),
                    "focus_hub": getattr(self, "_focus_hub", None),
                    "step": step + 1,
                    "execution_mode": getattr(self, "_execution_mode", "direct"),
                    "processing_state": str(getattr(self, "_processing_state", "")),
                    "files_created": list(dict.fromkeys(files_created))[-20:],
                    "files_modified": list(dict.fromkeys(files_modified))[-20:],
                    # Event-store efficiency (#5): persist only a SMALL summary
                    # of the step trace, never the full trace. The heartbeat is
                    # an append-only event; embedding the whole per-step trace
                    # (largest seen: 45 KB, 99% trace) bloated the store with no
                    # downstream consumer (nothing reads payload["step_trace"]).
                    "step_trace_summary": _summarize_step_trace(step_trace),
                },
            )
            synced["agent_status"] = True
        except Exception as e:
            synced["agent_status_error"] = str(e)

        synced["plan_index"] = self._sync_plan_index_to_hub(source_action=f"auto_{status}")

        # Auto-mark this agent's inbox as read at the end of every step. Messages
        # aren't deleted — only the `read` flag flips — so history is preserved
        # but the unread count stops growing without bound. Without this, agents
        # that call ``check_inbox(clear=False)`` (the LLM commonly does this
        # defensively) pile up hundreds of unread messages, drowning the
        # signal-to-noise ratio for both the agent and the UI.
        try:
            agent_id = getattr(self, "agent_id", None)
            if agent_id and hasattr(hubs, "hubs") and hasattr(hubs.hubs, "eventhub"):
                # O14/Phase 4.1: thread caller=agent_id (self-mutation —
                # agent marking its own inbox read in its step pipeline).
                marked = hubs.hubs.eventhub.mark_all_read(
                    agent_id, caller=agent_id,
                )
                if marked:
                    synced["inbox_marked_read"] = marked
        except Exception as e:
            synced["inbox_mark_read_error"] = str(e)

        seen_paths = set()
        for operation, paths in (("created", files_created), ("modified", files_modified)):
            for path in paths:
                normalized = str(path or "").strip()
                if not normalized or normalized in seen_paths:
                    continue
                seen_paths.add(normalized)
                try:
                    # Phase 4.6.1 prep (Step A): fall back to ""
                    # (empty-actor fallthrough) when this step-pipeline
                    # instance has no bound agent_id, instead of the
                    # literal "unknown" phantom. "unknown" is non-empty
                    # and would be rejected by any future
                    # codehub.record_check allowlist gate; "" passes
                    # through the established empty-actor convention
                    # used by all 21 currently-shipped gates. The
                    # evidence payload preserves the actor string for
                    # the audit trail — only the `agent=` kwarg that
                    # the gate consumes is flipped.
                    agent_id = getattr(self, "agent_id", "")
                    hubs.hubs.codehub.record_check(
                        pr_id="main",
                        name=f"artifact:{normalized}",
                        status="recorded",
                        evidence={
                            "path": normalized,
                            "operation": operation,
                            "kind": self._artifact_kind_for_path(normalized),
                            "agent": agent_id or "unknown",
                            "step": step + 1,
                        },
                        agent=agent_id,
                    )
                    synced["artifacts"] += 1
                except Exception as e:
                    synced.setdefault("artifact_errors", []).append({"path": normalized, "error": str(e)})

        return synced
