"""PROPOSAL #26 — framework-decision notices (anti-thrash).

When the FRAMEWORK supersedes a lane's work — resolves a merge/pull conflict by
ownership (keeps the contract-generated skeleton over the lane's edit) or regenerates
a scaffolded file — the lane must be TOLD, or it re-edits the framework's decision and
the framework re-applies it (thrash). This emits a single ``framework_decision`` event
to the affected lane.

CRITICAL (the #25 reviewer's blocking correction): the no-wakeup guarantee comes from
the lane's ``delivery="inbox_only"`` subscription (agent_subscriptions.INBOX_ONLY_
SUBSCRIPTIONS), NOT from priority. priority stays ``"normal"``; the bridge excludes
inbox_only-subscribed agents from live wakeup targets, so the note lands in the inbox
and is surfaced at the lane's next hub_pulse — it never triggers a resident wakeup
(which would reintroduce the churn #24 removed). The event MUST be registered ONLY in
INBOX_ONLY_SUBSCRIPTIONS and kept at priority="normal".
"""

from __future__ import annotations

from typing import Any, List, Optional

FRAMEWORK_DECISION_EVENT = "framework_decision"

# Where each lane should put hand-authored logic (so the message can redirect it off
# the framework-owned files it just superseded). Mirrors auto_commit._OWNERSHIP intent.
_LANE_DEST = {
    "backend": "custom_routes.py (the one lane-owned backend file)",
    "frontend": "your page components under app/frontend/src/pages/ + their routes in App.jsx",
}


def _conflict_message(lane: str, paths: List[str]) -> str:
    dest = _LANE_DEST.get(lane, "your lane-owned files")
    shown = ", ".join(paths[:6]) + ("…" if len(paths) > 6 else "")
    return (
        f"FRAMEWORK SUPERSEDED YOUR EDIT(S): {shown}. These are framework-owned files "
        f"— the framework regenerates them from the registered contract, so a git "
        f"conflict was just resolved in the framework's favor. Do NOT re-edit them; "
        f"put your hand-written logic in {dest} instead. If a route/behavior is wrong, "
        f"fix the CONTRACT (register/update the endpoint or table), not the generated file."
    )


def _scaffold_message(lane: str, paths: List[str]) -> str:
    shown = ", ".join(paths[:6]) + ("…" if len(paths) > 6 else "")
    return (
        f"FRAMEWORK REGENERATED: {shown}. The framework (re)built these from the "
        f"contract. Pull + build ON TOP of them; do not recreate or fight them — change "
        f"the contract if the generated result is wrong."
    )


def build_message(kind: str, lane: str, paths: List[str]) -> str:
    if kind == "conflict_resolved":
        return _conflict_message(lane, paths)
    if kind == "framework_scaffolded":
        return _scaffold_message(lane, paths)
    return f"framework_decision({kind}): {', '.join(paths)}"


def emit_framework_decision(
    eventhub: Any,
    *,
    lane: str,
    kind: str,
    paths: List[str],
    caller: str = "registryhub",
) -> bool:
    """Emit ONE framework_decision event to ``lane`` (inbox_only → no wakeup).

    Returns True if published. Best-effort: never raises into the merge/heal loop.
    No-op when there is nothing to report (empty ``paths``) or no eventhub."""
    if eventhub is None or not paths:
        return False
    try:
        eventhub.publish_event(
            "registryhub",                 # already gate-admitted source_hub
            FRAMEWORK_DECISION_EVENT,
            {"kind": kind, "lane": lane, "paths": list(paths),
             "message": build_message(kind, lane, paths)},
            recipients=[lane],
            priority="normal",             # NOT urgent — no-wakeup is via inbox_only sub
            caller=caller,
        )
        return True
    except Exception:
        return False
