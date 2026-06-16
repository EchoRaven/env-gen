from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .json_store import JsonStore


def _events_retention_cap() -> int:
    """Max number of events retained in the EventHub events store.

    Event-store efficiency (#6): the events store is append-only and
    JsonStore rewrites the WHOLE file on every publish, so unbounded
    growth makes publishing O(n^2) (a partial youtube run hit 2316
    events / 3.75 MB). We bound the store with a generous ring-buffer
    cap: when publishing would exceed the cap, the oldest NON-pinned
    events are evicted first. The cap is high enough never to harm
    coordination (recent events / unread inbox items are what agents
    actually read) but keeps the worst case bounded.

    Configurable via ``ENVGEN_EVENTHUB_MAX_EVENTS`` (env var). A value
    <= 0 disables eviction.
    """
    raw = os.environ.get("ENVGEN_EVENTHUB_MAX_EVENTS")
    if raw is None or raw.strip() == "":
        return EVENTHUB_DEFAULT_MAX_EVENTS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return EVENTHUB_DEFAULT_MAX_EVENTS


# Generous default: a few thousand events is far more than any healthy
# coordination window needs, yet bounds the O(n^2) full-file rewrite.
EVENTHUB_DEFAULT_MAX_EVENTS = 5000


def _normalize_actor(value: Optional[str]) -> str:
    """O14 / Phase 4.1 — canonical actor-name normalization used by both
    the change_info writer and the identity-gate compare."""
    return (value or "").strip().lower()


def _eventhub_change_info(agent: str, caller: Optional[str]) -> Dict[str, Any]:
    """Build the change_info dict for an EventHub mutation.

    O14: encode the caller-identity threading convention in one place
    so all 6 mutation methods share it. Empty/None caller falls through
    (matches the empty-actor idiom used by every shipped gate); a
    non-empty caller is normalized via ``.strip().lower()`` and
    persisted as ``meta['last_caller']`` for Phase 4.1+ identity gates
    to read. The ``last_modified_by`` field (the actor) is preserved
    unchanged — downstream readers' contracts are honored.
    """
    info: Dict[str, Any] = {"agent": agent}
    normalized = _normalize_actor(caller)
    if normalized:
        info["last_caller"] = normalized
    return info


# Service-sentinel callers explicitly authorized to mutate any agent's
# EventHub state. Used by service-initiated reaping paths (e.g. the
# agent_spawn_service terminating a worker reaps that worker's
# subscriptions). Adds attributable bookkeeping (meta['last_caller']
# records the service name) while preserving the owner-equals gate
# for agent-to-agent mutations. Audit: this set must stay small +
# documented; new entries require a comment explaining the privileged
# semantic the sentinel claims.
PHASE_4_1_SERVICE_CALLERS = frozenset({
    "agent_spawn_service",  # service-initiated reap on worker termination
    "messagebus_bridge",    # bridge.py marks events delivered after push
})


# Phase 4.1c publish-side source_hub authorship map. Per-hub allowlist
# of "cross-hub authorship" sentinels that may legitimately publish
# events declaring a DIFFERENT hub's name as ``source_hub`` (e.g.
# schema_hub emits under registryhub vocab because schema is a sub-domain
# of api). Owner-equals (caller == source_hub) is allowed unconditionally
# and does NOT need an entry here. Empty-caller fallthrough is also
# preserved (un-threaded callsites pass).
#
# Legacy phantom source_hubs (`system`, `messagebus`, `verifier`, `ui`)
# carry an empty sentinel set: they admit only via empty-caller
# fallthrough. Per user 2026-06-01 directive: Step A ships the gate
# WITHOUT migrating these to real hubs — migration is a follow-up
# cleanup PR. The empty sentinel set means "no cross-hub caller is
# explicitly admitted; un-threaded callsites pass via fallthrough".
PHASE_4_1C_PUBLISH_SENTINELS: Dict[str, frozenset] = {
    # registryhub vocab: schema_hub + mcp_registry legitimately emit under
    # registryhub source because schema + mcp are sub-domains of api.
    "registryhub":     frozenset({"schema_hub", "mcp_registry"}),
    # workhub vocab: gate_registry was lifted out of WorkHub by PR 3 of
    # the hub-responsibility-split plan but kept emitting under workhub
    # source for downstream-listener compat.
    "workhub":    frozenset({"gate_registry"}),
    # human_user vocab: live_monitor stamps from_user via session cookie
    # (Phase 4.7-slim Path C, dab6aa26) and messagebus_bridge re-publishes
    # human messages from the cross-process bus.
    "human_user": frozenset({"live_monitor", "messagebus_bridge"}),
    # eventhub: internal trampoline → empty-caller fallthrough only.
    "eventhub":   frozenset(),
    # Legacy phantom source_hubs — DEFERRED migration per Path B discipline
    # (user 2026-06-01 directive: ship Step A, defer the 4 phantom
    # migrations). These admit via empty-caller fallthrough only;
    # un-threaded callsites pass, explicitly-threaded callers must wait
    # for the migration PR that picks a real source_hub for each.
    "system":     frozenset(),
    "messagebus": frozenset(),
    "verifier":   frozenset(),
    "ui":         frozenset(),
}


def _source_hub_authorship_gate(
    method_name: str, source_hub: Optional[str], caller: Optional[str]
) -> None:
    """Publish-side source_hub authorship gate.

    An EventHub publish call that declares a non-empty ``caller`` may
    only publish events whose ``source_hub`` is one of:
      1. ``source_hub == caller`` (owner-equals)
      2. ``caller`` in PHASE_4_1C_PUBLISH_SENTINELS[source_hub]
         (per-hub cross-hub authorship allowlist)

    Empty-caller fallthrough preserved (un-threaded callsites).
    """
    normalized_caller = _normalize_actor(caller)
    if not normalized_caller:
        return  # empty-actor fallthrough
    normalized_hub = _normalize_actor(source_hub)
    if normalized_caller == normalized_hub:
        return  # owner-equals
    allowlist = PHASE_4_1C_PUBLISH_SENTINELS.get(normalized_hub, frozenset())
    if normalized_caller in allowlist:
        return  # cross-hub authorship sentinel
    raise PermissionError(
        f"EventHub.{method_name}: caller={normalized_caller!r} may not "
        f"publish events declaring source_hub={normalized_hub!r}. "
        f"Allowlist for source_hub={normalized_hub!r}: {sorted(allowlist)}. "
        f"To pass, either flip your caller= kwarg to "
        f"caller={normalized_hub!r}, OR (if this is legitimate cross-hub "
        f"authorship) add {normalized_caller!r} to "
        f"PHASE_4_1C_PUBLISH_SENTINELS[{normalized_hub!r}] in eventhub.py."
    )


def _subscription_identity_gate(
    method_name: str, agent: str, caller: Optional[str]
) -> None:
    """Cross-agent mutation prevention for EventHub subscription/inbox ops.

    An EventHub mutation that declares a non-empty ``caller`` may ONLY
    target the same actor (caller == agent), unless the caller is a
    documented service sentinel. Empty-actor fallthrough preserved.
    """
    normalized_caller = _normalize_actor(caller)
    if not normalized_caller:
        return  # empty-actor fallthrough
    if normalized_caller in PHASE_4_1_SERVICE_CALLERS:
        return  # service sentinel
    normalized_agent = _normalize_actor(agent)
    if normalized_caller == normalized_agent:
        return  # self-mutation allowed
    raise PermissionError(
        f"EventHub.{method_name}: caller={normalized_caller!r} cannot "
        f"mutate agent={normalized_agent!r}'s subscription/inbox. Only the "
        f"owning agent (or empty-actor system paths via caller=None) may "
        f"mutate."
    )


class EventHub:
    """Gmail-like durable event, thread, subscription, and inbox hub."""

    def __init__(self, hub_dir: Path):
        self.hub_dir = Path(hub_dir)
        self._bridges: List[Any] = []
        self._events = JsonStore(self.hub_dir / "eventhub_events.json")
        self._threads = JsonStore(self.hub_dir / "eventhub_threads.json")
        self._subscriptions = JsonStore(self.hub_dir / "eventhub_subscriptions.json")
        self._inboxes = JsonStore(self.hub_dir / "eventhub_inboxes.json")
        self.ensure_documents()

    def ensure_documents(self) -> None:
        for store in [self._events, self._threads, self._subscriptions, self._inboxes]:
            store.update(lambda m: m, change_info={"system": "ensure_eventhub_document"})

    def add_bridge(self, bridge) -> None:
        """Append a delivery bridge.

        All attached bridges receive every published event. Bridges may be
        synchronous or expose an async ``deliver`` coroutine — the runtime
        will dispatch appropriately based on the active event loop.

        Args:
            bridge: Any object with a ``deliver(event)`` method. ``None`` is
                silently ignored to keep call sites simple.
        """
        if bridge is None:
            return
        self._bridges.append(bridge)

    # Priority rank: higher number = higher priority
    # Cutover 27: "human_user" is the top tier — messages from a real human
    # interrupt any agent's current work regardless of priority_floor.
    _PRIORITY_RANK: Dict[str, int] = {"low": 0, "normal": 1, "high": 2, "critical": 3, "human_user": 4}

    def publish_event(
        self,
        source_hub: str,
        event_type: str,
        payload: dict,
        recipients: Optional[List[str]] = None,
        priority: str = "normal",
        thread_id: Optional[str] = None,
        caller: Optional[str] = None,
    ) -> dict:
        # Phase 4.1c publish-side source_hub authorship gate.
        # Empty-caller fallthrough for un-threaded callsites; owner-
        # equals (caller == source_hub) and per-hub sentinel allowlist
        # admit. See _source_hub_authorship_gate above.
        _source_hub_authorship_gate("publish_event", source_hub, caller)
        # Gather explicit recipients
        explicit = set(recipients or [])

        # Fan-out: add subscription-matched agents
        event_rank = self._PRIORITY_RANK.get(priority, 1)
        for sub in self.get_subscriptions():
            sub_source = sub.get("source_hub", "*")
            sub_type = sub.get("event_type", "*")
            floor_rank = self._PRIORITY_RANK.get(sub.get("priority_floor", "low"), 0)
            if sub_source != "*" and sub_source != source_hub:
                continue
            if sub_type != "*" and sub_type != event_type:
                continue
            if event_rank < floor_rank:
                continue
            explicit.add(sub["agent"])

        recipients = sorted(explicit)
        actor = source_hub or "eventhub"
        now = time.time()
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        thread_id = thread_id or f"thread_{event_id}"
        event = {
            "id": event_id,
            "thread_id": thread_id,
            "source_hub": source_hub,
            "event_type": event_type,
            "payload": payload or {},
            "recipients": recipients,
            "priority": priority,
            "created_at": now,
            "_updated_by": source_hub,
            "_updated_at": now,
        }
        self._events.update(
            lambda m: self._set_and_prune_events(m, event_id, event, actor),
            change_info={"agent": actor},
        )
        thread = self._threads.get(thread_id) or {
            "id": thread_id,
            "event_ids": [],
            "participants": [],
            "created_at": now,
        }
        thread["event_ids"] = list(dict.fromkeys([*thread.get("event_ids", []), event_id]))
        thread["participants"] = sorted(set([*thread.get("participants", []), *recipients]))
        thread["updated_at"] = now
        self._threads.update(lambda m: m.set(thread_id, thread, actor), change_info={"agent": actor})
        for agent in recipients:
            inbox = self._inboxes.get(agent) or {"agent": agent, "items": {}}
            inbox.setdefault("items", {})[event_id] = {
                "event_id": event_id,
                "thread_id": thread_id,
                "read": False,
                "delivered": False,
                "priority": priority,
                "received_at": now,
            }
            self._inboxes.update(lambda m: m.set(agent, inbox, actor), change_info={"agent": actor})

        # Best-effort bridge delivery (sync or async context). Each bridge is
        # isolated: an exception from one must not prevent another from
        # receiving the event. ``asyncio.get_running_loop()`` returns the
        # running loop if called from a coroutine; otherwise raises
        # RuntimeError. In threaded HTTP-handler contexts (e.g. SSE) there is
        # no running loop, so we fall through to synchronous delivery.
        for bridge in list(self._bridges):
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    if asyncio.iscoroutinefunction(bridge.deliver):
                        asyncio.ensure_future(bridge.deliver(event))
                    else:
                        async def _run_bridge(_b=bridge, _ev=event):
                            _b.deliver(_ev)
                        asyncio.ensure_future(_run_bridge())
                else:
                    bridge.deliver(event)
            except Exception:
                pass  # best-effort: never let bridge errors block publish

        return event

    @staticmethod
    def _set_and_prune_events(view, event_id: str, event: dict, actor: str):
        """Set the new event, then evict oldest NON-pinned events past the cap.

        Event-store efficiency (#6): bounded ring-buffer retention applied
        inside the same atomic JsonStore write that adds the event, so the
        full-file rewrite never serializes more than ``cap`` events.
        Eviction order is oldest-``created_at`` first; events flagged
        ``pinned`` (or ``payload['pinned']``) are never evicted — coordination
        anchors can opt out. A cap <= 0 disables eviction entirely.
        """
        view.set(event_id, event, actor)
        cap = _events_retention_cap()
        if cap <= 0:
            return view
        data = view.value()
        if len(data) <= cap:
            return view

        def _is_pinned(ev: dict) -> bool:
            if not isinstance(ev, dict):
                return False
            return bool(ev.get("pinned") or (ev.get("payload") or {}).get("pinned"))

        evictable = [
            (eid, ev) for eid, ev in data.items() if not _is_pinned(ev)
        ]
        # Oldest first; fall back to id for stable ordering on ties.
        evictable.sort(key=lambda kv: (kv[1].get("created_at", 0) if isinstance(kv[1], dict) else 0, kv[0]))
        overflow = len(data) - cap
        for eid, _ev in evictable[:overflow]:
            if eid == event_id:
                continue  # never evict the event we just published
            view.delete(eid, actor)
        return view

    # ------------------------------------------------------------------
    # Phase 0.3 INERT anchor — Phase 2 frontend->backend handshake.
    # ------------------------------------------------------------------
    # The Phase 2 plan (docs/progressive_elaboration_refactor.md §2,
    # lines ~1232-1233) introduces a typed ``api_requirement`` channel
    # so the frontend can request a new endpoint shape from backend
    # WITHOUT writing directly to spec.api.json. Today there is no
    # such channel — the method is installed empty so the dispatch
    # surface is committed by Phase 0.3 and the Phase 2 mechanism PR
    # only has to fill in the body.
    def publish_api_requirement(
        self,
        *,
        flow_id: str,
        needed_data_shape: dict,
        agent: str,
        caller: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[dict]:
        """Phase 2 frontend->backend contract-requirement channel.

        Pre-Phase-2 (default unset OR phase < 2.0): no-op, returns
        ``None`` (legacy path = direct spec write by design).

        Phase 2 active (>=2.0): publishes a typed ``api_requirement``
        EventHub event targeted at the backend lane. Backend reads the
        requirement, designs the endpoint, writes spec.api.json,
        publishes a contract_published event back. Frontend subscribes
        to contract_published to learn the resulting endpoint shape.

        Args:
            flow_id: unique identifier for this requirement (typically a
                UI flow name from spec.ui.json critical_flows). Used to
                correlate api_requirement <-> contract_published.
            needed_data_shape: dict describing the data the frontend
                needs (e.g. {"resource": "posts", "fields": ["id",
                "title", "author.name"], "filtering": "by_author"}).
            agent: the publishing agent id (typically 'frontend').
            **kwargs: optional fields rolled into the event payload —
                e.g. priority, source_page, target_endpoint_hint.

        Returns:
            The published event dict.
        """
        # Publish a typed api_requirement event to the backend lane.
        # The api_requirement payload format is the CONTRACT between
        # frontend and backend for this channel.
        payload = {
            "flow_id": flow_id,
            "needed_data_shape": needed_data_shape,
            "agent": agent,
            **kwargs,
        }
        return self.publish_event(
            source_hub="eventhub",
            event_type="api_requirement",
            payload=payload,
            recipients=["backend"],
            priority=kwargs.get("priority", "normal"),
            caller=caller,
        )

    # ------------------------------------------------------------------
    # Task 2: Reshaped subscribe (spec 6-arg signature)
    # ------------------------------------------------------------------

    def subscribe(
        self,
        agent: str,
        source_hub: str = "*",
        event_type: str = "*",
        filter: Optional[dict] = None,
        priority_floor: str = "low",
        delivery: str = "live",
        *,
        caller: Optional[str] = None,
    ) -> dict:
        """Register a subscription matching the spec model.

        Args:
            agent: The subscribing agent id.
            source_hub: Hub to listen to; ``"*"`` means all hubs.
            event_type: Event type to listen for; ``"*"`` means all types.
            filter: Optional dict of payload-level filters.
            priority_floor: Minimum priority to trigger delivery.
            delivery: ``"live"`` (push via bridge) or ``"inbox_only"``.
            caller: O14 — opt-in identity of the AGENT that triggered
                this mutation (vs ``agent``, which is the OWNER of the
                subscription being written). Phase 4.1+ subscription
                identity gate compares ``caller`` to ``agent`` and
                rejects cross-agent mutations. ``caller=None`` is the
                empty-actor convention used by every shipped gate:
                fall through to the existing actor-derived path. Pre-
                Phase-4.1 behavior is byte-identical regardless of
                whether ``caller`` is threaded.

        Returns:
            The persisted Subscription dict.
        """
        _subscription_identity_gate("subscribe", agent, caller)
        now = time.time()
        sub_id = f"{agent}:{source_hub}:{event_type}"
        sub = {
            "id": sub_id,
            "agent": agent,
            "source_hub": source_hub,
            "event_type": event_type,
            "filter": filter,
            "priority_floor": priority_floor,
            "delivery": delivery,
            "created_at": now,
            "_updated_by": agent,
            "_updated_at": now,
        }
        self._subscriptions.update(
            lambda m: m.set(sub_id, sub, agent),
            change_info=_eventhub_change_info(agent, caller),
        )
        return sub

    # ------------------------------------------------------------------
    # Task 3: unsubscribe + get_subscriptions
    # ------------------------------------------------------------------

    def unsubscribe(
        self, subscription_id: str, *, caller: Optional[str] = None
    ) -> bool:
        """Soft-delete a subscription via a JsonStore _removed marker.

        Args:
            subscription_id: The ``id`` field of the subscription to remove.
            caller: O14 — see ``subscribe`` docstring. ``None``
                falls through; non-empty value persisted as
                ``meta['last_caller']``.

        Returns:
            ``True`` if the subscription existed and was marked removed,
            ``False`` if no such subscription was found.
        """
        subs = self._subscriptions.value()
        sub = subs.get(subscription_id)
        if not sub:
            return False
        actor = sub.get("agent", "eventhub")
        # Phase 4.1: gate AFTER lookup so we can check caller against
        # the actual subscription owner (actor), not just the row id.
        _subscription_identity_gate("unsubscribe", actor, caller)
        now = time.time()
        sub = dict(sub)
        sub["_removed"] = True
        sub["_updated_at"] = now
        self._subscriptions.update(
            lambda m: m.set(subscription_id, sub, actor),
            change_info=_eventhub_change_info(actor, caller),
        )
        return True

    def unsubscribe_all(self, agent: str, *, caller: Optional[str] = None) -> int:
        """Soft-delete every active subscription owned by ``agent``.

        Called by the spawn service when an agent is terminated so the
        subscriptions table doesn't grow forever with rows for
        long-gone workers. Returns the count removed.

        ``caller`` (O14) is forwarded into each ``unsubscribe`` call so
        the service-initiated reap is attributable.
        """
        _subscription_identity_gate("unsubscribe_all", agent, caller)
        count = 0
        for sub in self.get_subscriptions(agent=agent):
            sid = sub.get("id")
            if sid and self.unsubscribe(sid, caller=caller):
                count += 1
        return count

    def get_subscriptions(self, agent: Optional[str] = None) -> List[dict]:
        """Return active (not removed) subscriptions, optionally filtered by agent.

        Args:
            agent: If provided, return only this agent's subscriptions.

        Returns:
            List of active Subscription dicts.
        """
        subs = self._subscriptions.value()
        result = [
            s for s in subs.values()
            if not s.get("_removed")
            and (agent is None or s.get("agent") == agent)
        ]
        return result

    # ------------------------------------------------------------------
    # Cutover 27: Human-agent conversation surface
    # ------------------------------------------------------------------

    def publish_human_message(
        self,
        text: str,
        target_agents: List[str],
        thread_id: Optional[str] = None,
        from_user: str = "human_user",
        caller: Optional[str] = None,
    ) -> dict:
        """Publish a top-priority message from a real human user to one or more agents.

        Always uses priority="human_user" and event_type="human_message".
        Recipients = the target agents + the synthetic "human_user" inbox so the
        UI can re-read the message in the conversation transcript.

        Phase 4.7-slim Path A (commit-pending, the "human" runtime
        bridge): at phase>=4.7 the ``from_user`` MUST be non-phantom
        — the project must know its 甲方 (who the real human user is)
        so receiving agents can address replies correctly. The legacy
        ``"human_user"`` literal default is rejected at phase>=4.7
        because agents reading ``payload.from_user="human_user"`` have
        no way to know which actual user sent the message in a
        multi-user setup. Long-term Path C will derive from_user from
        live_monitor session/auth (cookie → user_id translation).
        """
        if not text or not text.strip():
            raise ValueError("human message text must be non-empty")
        if not target_agents:
            raise ValueError("publish_human_message requires at least one target agent")
        # Reject phantom from_user — agents reading payload.from_user
        # need a real human identity (the project's 甲方), not the
        # "human_user" placeholder.
        normalized = (from_user or "").strip().lower()
        if not normalized or normalized == "human_user":
            raise PermissionError(
                f"EventHub.publish_human_message: requires from_user to "
                f"be a non-phantom human user identity. Got "
                f"from_user={from_user!r}. Configure via "
                f"ENVGEN_HUMAN_USER_ID env var when starting the "
                f"pipeline, or pass from_user='<user_id>' explicitly."
            )
        return self.publish_event(
            source_hub="human_user",
            event_type="human_message",
            payload={"text": text, "from_user": from_user, "to": list(target_agents)},
            recipients=list(target_agents),
            caller=caller,
            priority="human_user",
            thread_id=thread_id,
        )

    def publish_agent_reply(
        self,
        thread_id: str,
        agent: str,
        text: str,
        caller: Optional[str] = None,
    ) -> dict:
        """Publish an agent's reply into an existing human conversation thread.

        Replies inherit the thread's participants so the human (via the
        "human_user" inbox) and any other agents involved both see it.
        """
        if not text or not text.strip():
            raise ValueError("agent reply text must be non-empty")
        thread = self._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        # Reply audience: every prior participant + the human inbox.
        prior = set(thread.get("participants") or [])
        prior.add("human_user")
        prior.discard(agent)  # don't echo to the speaker
        return self.publish_event(
            source_hub=agent,
            event_type="agent_reply",
            payload={"text": text, "reply_from": agent},
            recipients=sorted(prior),
            priority="high",          # replies are high but not human_user
            thread_id=thread_id,
            # Phase 4.1c: by default, the publishing agent IS the
            # source_hub (owner-equals). When caller= is threaded by an
            # outer wrapper (e.g. service-mediated reply), let it pass
            # through; otherwise default to agent for self-publish.
            caller=caller if caller is not None else agent,
        )

    def list_conversations(
        self,
        participant: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        """Return human-agent conversation summaries.

        A "conversation" is any thread whose first event has
        source_hub="human_user". Returned dicts:
            {thread_id, participants, message_count, last_message_at,
             last_message_text, last_message_source, status}
        Sorted by last_message_at descending.
        """
        threads = self._threads.value() or {}
        events = self._events.value() or {}
        out = []
        for tid, thread in threads.items():
            event_ids = thread.get("event_ids") or []
            if not event_ids:
                continue
            first = events.get(event_ids[0])
            if not first or first.get("source_hub") != "human_user":
                continue
            if participant is not None and participant not in (thread.get("participants") or []):
                continue
            last = events.get(event_ids[-1]) or {}
            convo_status = thread.get("status", "open")
            if status is not None and convo_status != status:
                continue
            out.append({
                "thread_id": tid,
                "participants": list(thread.get("participants") or []),
                "message_count": len(event_ids),
                "last_message_at": last.get("created_at", 0.0),
                "last_message_text": (last.get("payload") or {}).get("text", ""),
                "last_message_source": last.get("source_hub", ""),
                "status": convo_status,
                "created_at": thread.get("created_at", 0.0),
            })
        out.sort(key=lambda c: c["last_message_at"], reverse=True)
        return out

    def subscribe_to_human_messages(self, agent: str) -> dict:
        """Convenience: subscribe `agent` to every human_message at the human_user floor.

        Useful for the orchestrator and observability agents that want to see
        all human chatter, not just messages explicitly addressed to them.
        """
        return self.subscribe(
            agent=agent,
            source_hub="human_user",
            event_type="human_message",
            priority_floor="human_user",
            delivery="live",
        )

    # ------------------------------------------------------------------
    # Existing inbox methods
    # ------------------------------------------------------------------

    def list_inbox(self, agent: str, unread_only: bool = True) -> List[dict]:
        inbox = self._inboxes.value().get(agent) or {"items": {}}
        events = self._events.value()
        out = []
        for item in (inbox.get("items") or {}).values():
            if unread_only and item.get("read"):
                continue
            event = events.get(item.get("event_id"))
            if event:
                out.append({**event, "inbox": item})
        out.sort(key=lambda e: e.get("created_at", 0), reverse=True)
        return out

    def mark_read(
        self, agent: str, event_id: str, *, caller: Optional[str] = None
    ) -> dict:
        """Mark an inbox item read. ``caller`` (O14) — see ``subscribe``."""
        _subscription_identity_gate("mark_read", agent, caller)
        now = time.time()
        inbox = self._inboxes.get(agent) or {"agent": agent, "items": {}}
        item = (inbox.get("items") or {}).get(event_id)
        if not item:
            return {"error": f"Event not found in inbox: {event_id}"}
        item["read"] = True
        item["read_at"] = now
        inbox["items"][event_id] = item
        self._inboxes.update(
            lambda m: m.set(agent, inbox, agent),
            change_info=_eventhub_change_info(agent, caller),
        )
        return item

    # ------------------------------------------------------------------
    # Task 4: mark_delivered / mark_all_read / get_event / get_thread
    # ------------------------------------------------------------------

    def mark_delivered(
        self, agent: str, event_id: str, *, caller: Optional[str] = None
    ) -> dict:
        """Flip delivered=True / delivered_at on an inbox item (not read).

        Called by the MessageBusBridge after successfully pushing to the agent.

        Args:
            agent: The recipient agent id.
            event_id: The event that was delivered.
            caller: O14 — see ``subscribe`` docstring.

        Returns:
            The updated inbox item dict, or a dict with ``"error"`` key if not found.
        """
        _subscription_identity_gate("mark_delivered", agent, caller)
        now = time.time()
        inbox = self._inboxes.get(agent) or {"agent": agent, "items": {}}
        item = (inbox.get("items") or {}).get(event_id)
        if not item:
            return {"error": f"Event not found in inbox: {event_id}"}
        item["delivered"] = True
        item["delivered_at"] = now
        # read stays unchanged
        inbox["items"][event_id] = item
        self._inboxes.update(
            lambda m: m.set(agent, inbox, agent),
            change_info=_eventhub_change_info(agent, caller),
        )
        return item

    def mark_all_read(
        self,
        agent: str,
        before_ts: Optional[float] = None,
        *,
        caller: Optional[str] = None,
    ) -> int:
        """Mark all unread inbox items as read, optionally bounded by timestamp.

        Args:
            agent: The agent whose inbox to update.
            before_ts: If provided, only mark items with ``received_at < before_ts``.
            caller: O14 — see ``subscribe`` docstring.

        Returns:
            The count of items that were flipped to read.
        """
        _subscription_identity_gate("mark_all_read", agent, caller)
        now = time.time()
        inbox = self._inboxes.get(agent) or {"agent": agent, "items": {}}
        items = inbox.get("items") or {}
        count = 0
        for event_id, item in items.items():
            if item.get("read"):
                continue
            if before_ts is not None and item.get("received_at", 0) >= before_ts:
                continue
            item["read"] = True
            item["read_at"] = now
            items[event_id] = item
            count += 1
        if count:
            inbox["items"] = items
            self._inboxes.update(
                lambda m: m.set(agent, inbox, agent),
                change_info=_eventhub_change_info(agent, caller),
            )
        return count

    def prune_read_inbox(
        self,
        agent: str,
        older_than_seconds: float = 86400.0,
        keep_min: int = 50,
        now_ts: Optional[float] = None,
        *,
        caller: Optional[str] = None,
    ) -> int:
        """Evict already-read inbox items older than ``older_than_seconds``.

        Long sessions accumulate thousands of read events that the pulse
        already capped from view but that still grow the JSON store.
        Eviction targets only items the agent has explicitly marked
        ``read=True`` — unread items are never removed (data loss).

        ``keep_min`` is a floor on how many read items we keep even if
        the threshold says evict — handy for "recently read" lookbacks.

        ``caller`` (Phase 4.1b sibling to the 6-method identity gate):
        empty-actor / None falls through; non-empty actor that isn't
        the inbox owner (and isn't a privileged service sentinel) is
        rejected at phase>=4.1. Same owner-equals idiom as the 6
        primary methods.

        Returns the count of evicted entries.
        """
        _subscription_identity_gate("prune_read_inbox", agent, caller)
        now = float(now_ts) if now_ts is not None else time.time()
        inbox = self._inboxes.get(agent) or {"agent": agent, "items": {}}
        items: Dict[str, Any] = dict(inbox.get("items") or {})
        # Sort read items by read_at desc; protect the newest keep_min.
        read_items = [
            (eid, it) for eid, it in items.items() if it.get("read")
        ]
        read_items.sort(key=lambda kv: float(kv[1].get("read_at") or 0), reverse=True)
        protected = {eid for eid, _ in read_items[:keep_min]}
        evicted = 0
        for eid, it in read_items:
            if eid in protected:
                continue
            read_at = float(it.get("read_at") or 0)
            if read_at <= 0:
                continue  # malformed timestamp — leave alone
            if now - read_at < older_than_seconds:
                continue
            items.pop(eid, None)
            evicted += 1
        if evicted:
            inbox["items"] = items
            # Phase 4.1b: thread caller into change_info so
            # last_caller is attributable even though the actor stays
            # = inbox owner. The "system" key is preserved for
            # backward-compat with the existing reader contract.
            change_info: Dict[str, Any] = {"agent": agent, "system": "prune_read_inbox"}
            normalized = _normalize_actor(caller)
            if normalized:
                change_info["last_caller"] = normalized
            self._inboxes.update(lambda m: m.set(agent, inbox, agent),
                                  change_info=change_info)
        return evicted

    def get_event(self, event_id: str) -> Optional[dict]:
        """Retrieve a single event by id.

        Args:
            event_id: The event's ``id`` field.

        Returns:
            The event dict, or ``None`` if not found.
        """
        return self._events.get(event_id)

    def get_thread(self, thread_id: str) -> List[dict]:
        """Return all events in a thread in chronological order.

        Args:
            thread_id: The thread identifier.

        Returns:
            List of event dicts sorted by ``created_at`` ascending.
        """
        thread = self._threads.get(thread_id)
        if not thread:
            return []
        events = self._events.value()
        result = [
            events[eid]
            for eid in thread.get("event_ids", [])
            if eid in events
        ]
        result.sort(key=lambda e: e.get("created_at", 0))
        return result

    def thread_reply(self, thread_id: str, agent: str, body: str) -> dict:
        return self.publish_event(
            source_hub="eventhub",
            event_type="thread_reply",
            payload={"body": body, "from": agent},
            recipients=[],
            thread_id=thread_id,
        )

    # ------------------------------------------------------------------
    # Human chat mini-loop helpers (Task 1)
    # ------------------------------------------------------------------

    def get_thread_transcript(self, thread_id: str) -> List[dict]:
        """Return thread events shaped for LLM consumption.

        Each entry is ``{role, speaker, text, ts}`` where ``role`` is
        ``"user"`` for ``human_message`` events and ``"assistant"`` for
        ``agent_reply`` events. Other event types (status pings,
        chat_step pings, etc.) are skipped — this is the surface
        designed for prompt injection / compression, not a generic
        event log.
        """
        transcript: List[dict] = []
        for ev in self.get_thread(thread_id):
            etype = ev.get("event_type")
            payload = ev.get("payload") or {}
            text = (payload.get("text") or "").strip()
            if not text:
                continue
            if etype == "human_message":
                transcript.append({
                    "role": "user",
                    "speaker": payload.get("from_user", "human_user"),
                    "text": text,
                    "ts": ev.get("created_at", 0),
                })
            elif etype == "agent_reply":
                transcript.append({
                    "role": "assistant",
                    "speaker": payload.get("reply_from") or ev.get("source_hub", "?"),
                    "text": text,
                    "ts": ev.get("created_at", 0),
                })
        return transcript

    def update_thread_summary(
        self,
        thread_id: str,
        summary: str,
        summary_until_ts: float,
    ) -> dict:
        """Persist a rolling summary onto the thread document.

        ``summary_until_ts`` marks the cutoff: events with
        ``created_at <= summary_until_ts`` are considered captured by
        the summary; only events newer than this need to be replayed
        verbatim or re-summarized later.

        Atomic via ``_threads.update(lambda m: m.set(...))`` — same
        pattern every other thread mutation in this module uses
        (``publish_event`` for event_ids appends, ``mark_resolved`` for
        status flips). A naive ``get → modify → set`` would race against
        a concurrent ``publish_event`` appending an event_id between
        our read and write, silently dropping that event from the thread.
        """
        import time
        # Pre-check existence so the caller still gets a clear error
        # rather than a silent no-op when the thread doesn't exist.
        existing = self._threads.get(thread_id)
        if not existing:
            raise ValueError(f"thread {thread_id!r} does not exist")
        now = time.time()
        cutoff = float(summary_until_ts)

        def _apply(m):
            current = m.get(thread_id) or {}
            updated = dict(current)
            updated["summary"] = summary
            updated["summary_until_ts"] = cutoff
            updated["summary_updated_at"] = now
            return m.set(thread_id, updated, "eventhub")

        self._threads.update(_apply, change_info={"agent": "eventhub"})
        return self._threads.get(thread_id) or {}

    def estimate_thread_tokens(self, thread_id: str) -> int:
        """Rough token estimate for a thread's transcript (~4 chars/token).

        Used to decide when to trigger compression. Intentionally cheap
        — a real tokenizer is overkill for a threshold check.
        """
        transcript = self.get_thread_transcript(thread_id)
        chars = sum(len(entry.get("text", "")) for entry in transcript)
        return max(1, chars // 4)

    # ------------------------------------------------------------------
    # Phase E: agent_status system-topic helpers
    # ------------------------------------------------------------------

    def record_agent_status(
        self, agent_id: str, status: dict,
        caller: Optional[str] = None,
    ) -> dict:
        """Publish an agent_status event on the system topic.

        Args:
            agent_id: The agent reporting its status.
            status: Arbitrary status dict (status, current_task, …).
            caller: Accepted for signature symmetry with the other
                publish methods, but DELIBERATELY NOT forwarded to the
                publish gate. Reason: source_hub is the legacy phantom
                ``"system"`` (parked migration per Path B discipline,
                see docs/phantom_runtime_registry.md). Threading caller=
                would force a gate rejection at phase>=4.11 since
                ``caller != "system"`` and the sentinel allowlist for
                ``"system"`` is empty by design. The migration PR that
                replaces ``"system"`` with a real source_hub will also
                flip this method to actually propagate caller. Until
                then: agents may pass caller= for forward-compat audit
                but the gate falls through via empty-actor.

        Returns:
            The published event dict.
        """
        return self.publish_event(
            source_hub="system",
            event_type="agent_status",
            payload={"agent_id": agent_id, **(status or {})},
            recipients=[],
            thread_id=f"thread:agent:{agent_id}",
            # caller= deliberately NOT forwarded — see docstring.
            caller=None,
        )

    def get_agent_status(self, agent_id: str):
        """Return the latest agent_status payload for *agent_id*, or None.

        Args:
            agent_id: The agent whose status to retrieve.

        Returns:
            The payload dict of the most-recent agent_status event, or None.
        """
        latest = None
        for evt in self._events.value().values():
            if evt.get("source_hub") != "system" or evt.get("event_type") != "agent_status":
                continue
            if evt.get("payload", {}).get("agent_id") != agent_id:
                continue
            if latest is None or evt.get("created_at", 0) > latest.get("created_at", 0):
                latest = evt
        return latest.get("payload") if latest else None

    def get_all_agent_statuses(self) -> dict:
        """Return a dict keyed by agent_id with the latest status payload per agent.

        Returns:
            Dict mapping agent_id → latest payload dict (plus ``_event_created_at``).
        """
        out: dict = {}
        for evt in self._events.value().values():
            if evt.get("source_hub") != "system" or evt.get("event_type") != "agent_status":
                continue
            aid = (evt.get("payload") or {}).get("agent_id")
            if not aid:
                continue
            prev = out.get(aid)
            if prev is None or evt.get("created_at", 0) > prev.get("_event_created_at", 0):
                out[aid] = {**(evt.get("payload") or {}), "_event_created_at": evt.get("created_at", 0)}
        return out

    def list_events_by_type(self, event_type: str) -> List[dict]:
        return [
            e for e in (self._events.value() or {}).values()
            if e.get("event_type") == event_type
        ]

    def get_versions(self) -> Dict[str, int]:
        return {
            "eventhub_events": self._events.get_version(),
            "eventhub_threads": self._threads.get_version(),
            "eventhub_subscriptions": self._subscriptions.get_version(),
            "eventhub_inboxes": self._inboxes.get_version(),
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "events": self._events.value(),
            "threads": self._threads.value(),
            "subscriptions": self._subscriptions.value(),
            "inboxes": self._inboxes.value(),
        }
