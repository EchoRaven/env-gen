"""Record skill consults at the universal tool-execution chokepoint.

Called from ``AgentTooling._execute_tool`` after every tool call. When the
tool was ``get_skill`` and it found the skill, the canonical skill name is
added to ``agent._consulted_skills`` (read by ``SkillConsultGate``) and a
``skill_consulted`` event is published for observability.

Best-effort: never raises into the tool path. This is the L3a substrate of
the skill-mandatory-trigger design (docs/superpowers/plans/2026-06-03-
skill-mandatory-trigger.md).
"""

from __future__ import annotations

from typing import Any, Dict


def record_skill_consult(agent: Any, tool_name: str, tool_args: Dict, result: Any) -> None:
    if tool_name != "get_skill":
        return
    if not getattr(result, "success", False):
        return
    data = getattr(result, "data", None) or {}
    if not data.get("found"):
        return
    skill = data.get("skill") or {}
    name = str(skill.get("name") or (tool_args or {}).get("name") or "").strip()
    if not name:
        return

    consulted = getattr(agent, "_consulted_skills", None)
    if consulted is None:
        consulted = set()
        setattr(agent, "_consulted_skills", consulted)
    consulted.add(name)

    hubs = getattr(agent, "_hubs", None)
    if hubs is None or not hasattr(hubs, "eventhub"):
        return
    try:
        hubs.eventhub.publish_event(
            source_hub=agent.agent_id,
            event_type="skill_consulted",
            payload={"agent": agent.agent_id, "skill": name},
            recipients=[],
            priority="normal",
        )
    except Exception:
        try:
            agent._logger.debug(f"[{agent.agent_id}] skill_consulted emit failed")
        except Exception:
            pass
