"""Human↔agent chat bridge — connects the Env Forge backend to a LIVE
generation's agents via the engine's EventHub.

The legacy ``live_monitor_server`` reaches the agents through
``HubRegistry(workspace).human_console``. We deliberately do NOT build a full
``HubRegistry`` here: its ``__init__`` runs schema backfills/migrations that
MUTATE the live JSON stores (risky to trigger from the read-mostly Env Forge
backend while a generation is actively writing those same stores). Instead we
construct the LIGHTEST safe surface ``HumanConsole`` needs:

  * an ``EventHub`` over ``<generated_dir>/shared/hubs`` (its ``__init__`` only
    opens the 4 ``eventhub_*.json`` stores + ensures they exist — no migrations)
  * a tiny ``hubs`` namespace exposing ``.eventhub`` (all HumanConsole reads)

The engine package is importable as ``env_generator.llm_generator.*`` once the
engine root (``<repo>/agent``) is on ``sys.path`` — it is added lazily on first
use so importing this module never drags the engine in.

``from_user`` identity: the engine's ``EventHub.publish_human_message`` REJECTS
the legacy ``"human_user"`` placeholder (and empty) at phase>=4.7 — it needs the
project's real 甲方 identity so agents address replies correctly. We pass the
authed admin's ``user_id`` (e.g. the JWT ``sub`` or the dev-mode ``dev-user``),
which the gate accepts. A caller with no real id gets a clear 4xx, never a 500.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import List, Optional

# Engine package root: <repo>/agent (this file is <repo>/app/chat_bridge.py).
_ENGINE_ROOT = str(Path(__file__).resolve().parents[1] / "agent")


def _ensure_engine_on_path() -> None:
    if _ENGINE_ROOT not in sys.path:
        sys.path.insert(0, _ENGINE_ROOT)


class ChatBridgeError(Exception):
    """Raised for caller-facing chat errors (mapped to a 4xx by the API layer)."""


def human_console(generated_dir: str, default_user_id: str = ""):
    """Build a ``HumanConsole`` over a generated env's EventHub.

    Uses the light construction (EventHub only — no HubRegistry migrations).
    Raises ``ChatBridgeError`` if the env's hub dir is missing.
    """
    if not generated_dir:
        raise ChatBridgeError("environment has no generated tree yet")
    hub_dir = Path(generated_dir) / "shared" / "hubs"
    if not hub_dir.is_dir():
        raise ChatBridgeError("environment hub store not found (generation not started?)")

    _ensure_engine_on_path()
    # Imported lazily so the engine is only loaded when chat is actually used.
    from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub
    from env_generator.llm_generator.multi_agent.runtime.human_console import HumanConsole

    eventhub = EventHub(hub_dir)
    hubs = types.SimpleNamespace(eventhub=eventhub)
    return HumanConsole(hubs, default_user_id=default_user_id or None)


def _existing_thread(console, thread_id: Optional[str]) -> bool:
    """True if ``thread_id`` names an existing EventHub thread."""
    if not thread_id or thread_id == "main":
        return False
    try:
        return console._eventhub._threads.get(thread_id) is not None
    except Exception:
        return False


def send(
    generated_dir: str,
    *,
    content: str,
    recipients: List[str],
    thread_id: str,
    from_user: str,
) -> dict:
    """Dispatch a human message to the LIVE agents via the EventHub.

    Starts a new conversation when ``thread_id`` is empty/"main"/unknown,
    otherwise posts into the existing thread. Returns the frontend chat shape
    (``{id, thread_id, sender, recipients, content, created_at}``) for the
    human message just published.
    """
    if not (content or "").strip():
        raise ChatBridgeError("message content must be non-empty")
    if not from_user or not from_user.strip():
        raise ChatBridgeError(
            "no human identity available to address the agents — sign in or set "
            "ENVGEN_HUMAN_USER_ID"
        )
    console = human_console(generated_dir, default_user_id=from_user)
    recips = [r for r in (recipients or []) if r]

    if _existing_thread(console, thread_id):
        try:
            event = console.send_message(
                thread_id=thread_id,
                text=content,
                target_agents=recips or None,
                from_user=from_user,
            )
        except ValueError as e:
            raise ChatBridgeError(str(e))
        tid = thread_id
    else:
        if not recips:
            raise ChatBridgeError("select at least one agent to start a conversation")
        try:
            conv = console.start_conversation(
                target_agents=recips,
                text=content,
                from_user=from_user,
            )
        except ValueError as e:
            raise ChatBridgeError(str(e))
        tid = conv["thread_id"]
        # The summary dict doesn't carry the event id; fetch the just-published
        # message from the transcript so we return its real id + timestamp.
        msgs = console.list_messages(tid)
        event = msgs[-1] if msgs else {"message_id": tid, "created_at": conv.get("first_message_at", 0.0)}

    return {
        "id": event.get("message_id") or event.get("id") or "",
        "thread_id": tid,
        "sender": from_user,
        "recipients": recips,
        "content": content,
        "created_at": _iso(event.get("created_at")),
    }


def list_messages(generated_dir: str, *, thread_id: Optional[str] = None,
                  default_user_id: str = "") -> List[dict]:
    """Return chat messages (human + agent replies) for an env, mapped to the
    frontend shape and ordered by time.

    With ``thread_id`` set, returns just that thread; otherwise flattens across
    every human-agent conversation in the env.
    """
    console = human_console(generated_dir, default_user_id=default_user_id)
    if thread_id and thread_id != "main":
        try:
            raw = console.list_messages(thread_id)
        except ValueError:
            return []
        out = [_msg_to_dict(console, m, thread_id) for m in raw]
        for m in out:
            m.pop("_ts", None)
        return out

    out: List[dict] = []
    for conv in console.list_conversations():
        tid = conv.get("thread_id")
        if not tid:
            continue
        try:
            for m in console.list_messages(tid):
                out.append(_msg_to_dict(console, m, tid))
        except ValueError:
            continue
    out.sort(key=lambda m: m["_ts"])
    for m in out:
        m.pop("_ts", None)
    return out


def _human_author(console, message_id: str) -> str:
    """Resolve the real ``from_user`` for a human message from the raw event
    payload (HumanConsole.list_messages doesn't surface it). Falls back to the
    "user" sentinel so the UI can still distinguish the human's own bubbles."""
    try:
        ev = (console._eventhub._events.value() or {}).get(message_id) or {}
        return (ev.get("payload") or {}).get("from_user") or "user"
    except Exception:
        return "user"


def _msg_to_dict(console, m: dict, thread_id: str) -> dict:
    """Map a HumanConsole message to the frontend chat shape.

    Human messages carry source_hub="human_user"; the real author lives in the
    payload's ``from_user`` (resolved via ``_human_author``). Agent replies
    carry ``reply_from`` (the author agent id) — use it as the sender so the UI
    labels the bubble.
    """
    if m.get("event_type") == "human_message":
        sender = _human_author(console, m.get("message_id", ""))
    else:
        sender = m.get("reply_from") or m.get("source") or "agent"
    return {
        "id": m.get("message_id", ""),
        "thread_id": thread_id,
        "sender": sender,
        "recipients": list(m.get("to") or []),
        "content": m.get("text", ""),
        "created_at": _iso(m.get("created_at")),
        "_ts": float(m.get("created_at") or 0.0),
    }


def _iso(ts) -> str:
    from datetime import datetime, timezone
    try:
        if isinstance(ts, (int, float)) and ts:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        pass
    return ""
