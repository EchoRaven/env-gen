"""MessageBusBridge — live delivery of EventHub events to MessageBus agents."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Set

if TYPE_CHECKING:
    from multi_agent.runtime.eventhub import EventHub
    from utils.communication import MessageBus


class MessageBusBridge:
    """Bridges EventHub publish_event calls to live MessageBus agents.

    After the EventHub writes all inboxes, it calls ``deliver(event)`` on this
    bridge.  For each recipient that is:
    - registered on the bus (i.e., bus.get_agent returns non-None), and
    - **not** subscribed as ``inbox_only``,

    the bridge wraps the event in a BaseMessage and calls
    ``agent.receive_message(msg)`` (awaited when called from an async context).
    It then calls ``eventhub.mark_delivered(agent_id, event_id)`` to flip the
    delivered flag in the inbox.

    Agents that are not found on the bus are counted as ``skipped_offline``.
    Any exception during delivery is captured and added to ``failed``.
    """

    PRIORITY_RANK: Dict[str, int] = {"low": 0, "normal": 1, "high": 2, "critical": 3}

    def __init__(self, bus: "MessageBus", eventhub: "EventHub") -> None:
        self._bus = bus
        self._eventhub = eventhub

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_live_targets(self, event: dict) -> Set[str]:
        """Return the set of agent IDs that should receive a live push.

        Agents with a matching ``inbox_only`` subscription are excluded.
        Explicit recipients without any matching subscription are included.
        """
        source_hub = event.get("source_hub", "*")
        event_type = event.get("event_type", "*")
        priority = event.get("priority", "normal")
        event_rank = self.PRIORITY_RANK.get(priority, 1)

        inbox_only: Set[str] = set()
        for sub in self._eventhub.get_subscriptions():
            if sub.get("delivery") != "inbox_only":
                continue
            # Check if this subscription matches the event
            sub_source = sub.get("source_hub", "*")
            sub_type = sub.get("event_type", "*")
            floor_rank = self.PRIORITY_RANK.get(sub.get("priority_floor", "low"), 0)
            if sub_source != "*" and sub_source != source_hub:
                continue
            if sub_type != "*" and sub_type != event_type:
                continue
            if event_rank < floor_rank:
                continue
            inbox_only.add(sub["agent"])

        recipients = set(event.get("recipients") or [])
        return recipients - inbox_only

    def _to_base_message(self, event: dict, agent_id: str):
        """Wrap an EventHub event dict as a BaseMessage addressed to agent_id."""
        # Deferred imports so bridge.py has no hard dependency on utils at import time
        from utils.message import BaseMessage, MessageHeader, MessageType, MessagePriority  # noqa: PLC0415

        priority_str = event.get("priority", "normal")
        priority_map: Dict[str, "MessagePriority"] = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "critical": MessagePriority.URGENT,
            # Cutover 29: human_user collapses to URGENT for queue prioritization;
            # the urgent-handler dispatches on event_type=="human_message" to route
            # to the dedicated _handle_human_message branch.
            "human_user": MessagePriority.URGENT,
        }
        priority = priority_map.get(priority_str, MessagePriority.NORMAL)

        header = MessageHeader(
            source_agent_id=event.get("source_hub", "eventhub"),
            target_agent_id=agent_id,
            priority=priority,
            correlation_id=event.get("thread_id"),
        )
        metadata = {
            "source_hub": event.get("source_hub"),
            "event_id": event.get("id"),
            "event_type": event.get("event_type"),
            # Round-8d Fix #2-bis: mirror event_type into msg_type at the
            # bridge boundary so live EventHub-delivery produces the same
            # metadata shape as the on-disk undelivered-inbox pickup path
            # (messaging.py:_pickup_undelivered_inbox_events line 295).
            # Without this, _check_and_handle_urgent reads
            # metadata['msg_type'] as empty for every bridge-delivered
            # urgent and every `if msg_type == "..."` dispatch branch
            # (shutdown/question/answer/issue/kickoff_request/task_ready)
            # silently falls through — observed in round-8b and round-8d
            # smokes as bare "Handling urgent " log lines with no kind,
            # and four kickoff attendees deadlocked for 10 min while the
            # driver polled try_synthesize waiting for decisions that
            # could never arrive.
            "msg_type": event.get("event_type"),
            "thread_id": event.get("thread_id"),
            "resource_type": event.get("payload", {}).get("resource_type"),
            "resource_id": event.get("payload", {}).get("resource_id"),
            "links": event.get("payload", {}).get("links", []),
        }
        return BaseMessage(
            header=header,
            message_type=MessageType.STATUS,
            payload=event.get("payload"),
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def deliver(self, event: dict) -> dict:
        """Deliver event to live agents on the MessageBus.

        This method is intentionally synchronous so it works in both sync
        (EventHub.publish_event called outside async loop) and async contexts
        (the caller wraps it as a coroutine via asyncio.ensure_future).

        Returns:
            A dict with keys ``delivered``, ``skipped_offline``, ``failed``.
        """
        import asyncio
        import inspect

        delivered = []
        skipped_offline = []
        failed = []

        targets = self._resolve_live_targets(event)
        event_id = event.get("id", "")

        for agent_id in sorted(targets):
            agent = self._bus.get_agent(agent_id)
            if agent is None:
                skipped_offline.append(agent_id)
                continue
            try:
                msg = self._to_base_message(event, agent_id)
                result = agent.receive_message(msg)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        asyncio.run(result)
                # O14/Phase 4.1: bridge is system-side, mutates the
                # agent's inbox to flip delivered=True. Use the
                # "messagebus_bridge" service sentinel (privileged via
                # PHASE_4_1_SERVICE_CALLERS) so the cross-agent
                # mutation is allowed AND attributable in meta.
                self._eventhub.mark_delivered(
                    agent_id, event_id, caller="messagebus_bridge",
                )
                delivered.append(agent_id)
            except Exception as exc:
                failed.append({"agent_id": agent_id, "error": str(exc)})

        return {"delivered": delivered, "skipped_offline": skipped_offline, "failed": failed}
