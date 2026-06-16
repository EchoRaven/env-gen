"""
HumanConsole — user-facing API for human-agent conversations.

Composes EventHub conversation primitives into a chat-like surface for
the UI (Cutover 28) and CLI. A `HubRegistry` exposes `.human_console`
post-construction (see hub_registry.py).

Phase 4.7-slim Path A (the 甲方 awareness bridge): HumanConsole
captures the project's *actual* human user identity at construction
time and uses it as the default ``from_user`` for every message it
emits. Agents reading ``payload.from_user`` then see the real user
ID rather than the legacy "human_user" placeholder, so replies
address the correct person in multi-user setups.

The user id is sourced (in order):
  1. ``default_user_id`` kwarg at __init__
  2. ``ENVGEN_HUMAN_USER_ID`` env var
  3. ``"human_user"`` literal (backward-compat default, rejected by
     EventHub.publish_human_message at phase>=4.7)

Long-term Path C replaces this with session-derived identity from
live_monitor cookie/auth (cookie → user_id translation).
"""

from __future__ import annotations

import os
import time
from typing import List, Optional


class HumanConsole:
    """User-facing wrapper around EventHub human-message helpers."""

    def __init__(self, hubs, default_user_id: Optional[str] = None):
        self._hubs = hubs
        self._eventhub = hubs.eventhub
        # Resolution order: explicit kwarg → env var → "" (no default).
        # An empty default is fine at init time; the EventHub gate
        # rejects publishing with a phantom from_user when the call
        # actually runs.
        self._default_user_id = (
            default_user_id
            or os.environ.get("ENVGEN_HUMAN_USER_ID")
            or ""
        ).strip()

    @property
    def default_user_id(self) -> str:
        """The 甲方 identity used as default ``from_user`` for new messages."""
        return self._default_user_id

    def start_conversation(
        self,
        target_agents: List[str],
        text: str,
        from_user: Optional[str] = None,
    ) -> dict:
        """Begin a new human-agent conversation. Returns a summary dict.

        If ``from_user`` is None, falls back to the console's
        ``default_user_id`` (set at HubRegistry init via the
        ``ENVGEN_HUMAN_USER_ID`` env var or kwarg).
        """
        event = self._eventhub.publish_human_message(
            text=text,
            target_agents=target_agents,
            from_user=from_user or self._default_user_id,
        )
        return {
            "thread_id": event["thread_id"],
            "participants": sorted(set(target_agents)),
            "first_message_text": text,
            "first_message_at": event["created_at"],
        }

    def send_message(
        self,
        thread_id: str,
        text: str,
        from_user: Optional[str] = None,
        target_agents: Optional[List[str]] = None,
    ) -> dict:
        """Send another human message into an existing conversation.

        If ``target_agents`` is given (e.g. from @mentions in the UI), the
        message is routed only to those agents (must be current participants).
        Otherwise it goes to every agent participant.
        """
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        # Re-derive target agents from existing thread participants minus the human.
        participants = [a for a in (thread.get("participants") or []) if a != "human_user"]
        if not participants:
            raise ValueError(f"thread {thread_id!r} has no agent participants")
        if target_agents:
            targets = [a for a in target_agents if a in participants]
            if not targets:
                raise ValueError("none of the @mentioned agents are in this conversation")
        else:
            targets = participants
        return self._eventhub.publish_human_message(
            text=text,
            target_agents=targets,
            thread_id=thread_id,
            from_user=from_user or self._default_user_id,
        )

    def list_conversations(
        self,
        participant: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        return self._eventhub.list_conversations(participant=participant, status=status)

    # Event types that belong in the chat transcript:
    #   * ``human_message`` — what the user typed
    #   * ``agent_reply``   — the agent's primary reply to the user
    #   * ``thread_reply``  — secondary text replies from agents (the
    #                          ``eventhub_reply_in_thread`` tool emits
    #                          these; they ARE conversational and must
    #                          render alongside ``agent_reply``)
    # All other event types (``agent_chat_step`` tool-call progress
    # pings, ``agent_status`` heartbeats, etc.) are filtered out —
    # they belong on the live SSE channel, not the persisted transcript.
    _CHAT_MESSAGE_EVENT_TYPES = {"human_message", "agent_reply", "thread_reply"}

    def list_messages(self, thread_id: str) -> List[dict]:
        """Return chronological message list for a thread.

        Each message: {message_id, source, text, created_at, event_type}.

        Only ``human_message`` and ``agent_reply`` events surface here.
        Other events that travel on the same thread (e.g.
        ``agent_chat_step`` tool-call progress pings) are excluded —
        they render under the typing-dot indicator via the SSE stream,
        not as standalone empty chat bubbles.
        """
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        events = self._eventhub._events.value() or {}
        out = []
        for eid in thread.get("event_ids") or []:
            ev = events.get(eid)
            if not ev:
                continue
            if ev.get("event_type") not in self._CHAT_MESSAGE_EVENT_TYPES:
                continue
            payload = ev.get("payload") or {}
            out.append({
                "message_id": eid,
                "source": ev.get("source_hub", ""),
                "text": payload.get("text", ""),
                "created_at": ev.get("created_at", 0.0),
                "event_type": ev.get("event_type", ""),
                "to": payload.get("to") or [],            # directed recipients (@mentions)
                "reply_from": payload.get("reply_from"),   # agent_reply author
            })
        out.sort(key=lambda m: m["created_at"])
        return out

    def mark_resolved(self, thread_id: str) -> None:
        """Mark a conversation as resolved (UI can hide it from the active list)."""
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        thread = dict(thread)
        thread["status"] = "resolved"
        thread["updated_at"] = time.time()
        self._eventhub._threads.update(
            lambda m: m.set(thread_id, thread, "human_user"),
            change_info={"agent": "human_user"},
        )
