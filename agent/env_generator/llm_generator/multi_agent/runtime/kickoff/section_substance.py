"""Substance check for kickoff section decisions — shared by the agent-side
corrective loop (messaging) and the facilitator's phase gate (facilitate).

gemini exhibits three authoring failure shapes: MALFORMED tool calls (dropped),
empty shells ({"ui_pages": []}), and null-placeholder skeletons
([null, null, ...]). All three must read as NOT AUTHORED — otherwise they
satisfy existence checks and starve the synthesis (live 2026-06-10: the
meeting finalized on five empty frontend decisions two seconds before the
corrective turn could land a real one)."""

from __future__ import annotations

from typing import Any, Mapping

_META_KEYS = ("section", "kind", "recorded_by", "agent", "recorded_at",
              "milestone_index", "round")


def real_items(seq: Any) -> int:
    """Count NON-EMPTY mapping entries (null-placeholder skeletons count 0)."""
    if not isinstance(seq, (list, tuple)):
        return 0
    return sum(1 for x in seq if isinstance(x, Mapping) and x)


def section_has_substance(content: Any, section: str) -> bool:
    if not isinstance(content, Mapping):
        return False
    if content.get("deferred"):
        return False
    if section == "frontend":
        return bool(real_items(content.get("ui_pages"))
                    or real_items(content.get("screens")))
    if section == "backend":
        dm = content.get("data_model")
        return bool(real_items(content.get("endpoints"))
                    or (isinstance(dm, Mapping) and real_items(dm.get("tables"))))
    if section == "verifier":
        return bool(real_items(content.get("predicates")))
    return True


def decision_has_substance(decision: Any, section: str) -> bool:
    """Both decision shapes: {"section","content":{...}} and flat."""
    if not isinstance(decision, Mapping):
        return False
    if section_has_substance(decision.get("content"), section):
        return True
    flat = {k: v for k, v in decision.items() if k not in _META_KEYS}
    return section_has_substance(flat, section)


def decision_advances_phase(decision: Any, section: str) -> bool:
    """May this decision advance the kickoff phase for its section?
    YES for substantive content, YES for an explicit deferred stub (the
    terminal advance-anyway marker after corrective turns are exhausted),
    NO for empty shells / null skeletons (the author is still being
    corrected — the meeting must wait)."""
    if not isinstance(decision, Mapping):
        return False
    content = decision.get("content")
    if isinstance(content, Mapping) and content.get("deferred"):
        return True
    if decision.get("deferred"):
        return True
    return decision_has_substance(decision, section)
