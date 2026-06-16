"""Notification support for dynamic agent management."""

from typing import Any, Dict, Optional

from .models import AgentLifecycle


class RuntimeNotificationSupport:
    def _on_agent_result_message(self, message: Any) -> None:
        """Capture result/error messages from spawned agents."""
        try:
            source_id = getattr(getattr(message, "header", None), "source_agent_id", "")
            if not source_id or source_id not in self._spawned_agents:
                return

            spawned = self._spawned_agents[source_id]
            result_data = getattr(message, "result_data", None)
            payload = getattr(message, "payload", None)
            success = getattr(message, "success", True)
            error_message = getattr(message, "error_message", None)

            spawned.findings = self._normalize_findings(
                result_data=result_data,
                payload=payload,
                success_flag=success,
                error_message=error_message,
            )
            spawned.lifecycle = AgentLifecycle.IDLE

            if spawned.result_done_event and not spawned.result_done_event.is_set():
                spawned.result_done_event.set()
            if spawned.task_done_event and not spawned.task_done_event.is_set():
                spawned.task_done_event.set()
        except Exception as e:
            self._logger.debug(f"Result tracking callback failed: {e}")

    async def _notify_parent_team_completion(
        self,
        *,
        parent_id: Optional[str],
        team_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Send one background completion/failure notification for a managed team."""
        if not parent_id:
            return
        bus = getattr(self._orchestrator, "message_bus", None)
        if not bus:
            return

        team_snapshot = self.get_agent_team_status(team_id=team_id)
        member_states = team_snapshot.get("member_states", {}) or {}
        member_state_counts: Dict[str, int] = {}
        for state in member_states.values():
            key = str(state or "unknown")
            member_state_counts[key] = member_state_counts.get(key, 0) + 1

        from utils.message import BaseMessage, MessageHeader, MessagePriority, MessageType

        status_upper = status.upper()
        summary = (
            f"[TEAM {status_upper}] team_id={team_id} status={status} "
            f"active_members={team_snapshot.get('active_members', 0)}/"
            f"{len(team_snapshot.get('members', {}) or {})}"
        )
        if error_message:
            summary = f"{summary} error={error_message}"

        msg = BaseMessage(
            header=MessageHeader(
                source_agent_id="dynamic_agent_manager",
                target_agent_id=parent_id,
                priority=MessagePriority.NORMAL,
            ),
            message_type=MessageType.INFO,
            payload=summary,
            metadata={
                "msg_type": "team_update",
                "event": f"team_{status}",
                "team_id": team_id,
                "team_status": status,
                "member_state_counts": member_state_counts,
                "active_members": team_snapshot.get("active_members", 0),
                "total_members": len(team_snapshot.get("members", {}) or {}),
                "error_message": error_message,
                "persist": True,
                "read": False,
            },
        )
        await bus.send(msg)
