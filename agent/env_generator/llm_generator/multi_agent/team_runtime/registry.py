"""Runtime registry support for dynamic agent management."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .models import AgentLifecycle, AgentRuntimeKind


class RuntimeRegistrySupport:
    # #681: THE HOST-CLASS CONTRACT, DECLARED. This is a MIXIN — the names below are
    # supplied by the class it is mixed into, so a checker reading this file alone reports
    # every use as a missing attribute. That was 990 of 2218 diagnostics (45%), the single
    # largest class, and it buried real ones: the same sweep found #658 and a dangling
    # WorkHub annotation under it. Annotation-only, under TYPE_CHECKING — no runtime effect.
    if TYPE_CHECKING:
        _agent_ledger: Any
        def _is_success_findings(self, *a: Any, **k: Any) -> Any: ...
        _logger: Any
        def _recommended_action_from_error_code(self, *a: Any, **k: Any) -> Any: ...
        _spawned_agents: Any

    def _normalize_tool_names(self, tool_names: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        seen: Set[str] = set()
        for name in tool_names or []:
            if not isinstance(name, str):
                continue
            cleaned = name.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    def _register_agent_ledger(
        self,
        agent_id: str,
        *,
        requested_type: str,
        config_profile: str,
        parent_id: Optional[str],
        role: Optional[str],
        write_scopes: Optional[List[str]] = None,
        runtime_kind: str = AgentRuntimeKind.EPHEMERAL.value,
        lifecycle: str = AgentLifecycle.READY.value,
        metadata: Optional[Dict[str, Any]] = None,
        team_id: Optional[str] = None,
        team_member_id: Optional[str] = None,
    ) -> None:
        existing = self._agent_ledger.get(agent_id, {})
        registered_at = existing.get("registered_at") or datetime.now().isoformat()
        runtime_metadata = dict(existing.get("metadata") or {})
        runtime_metadata.update(metadata or {})
        self._agent_ledger[agent_id] = {
            "agent_id": agent_id,
            "requested_type": requested_type,
            "config_profile": config_profile,
            "parent_id": parent_id,
            "role": role,
            "write_scopes": list(write_scopes or []),
            "runtime_kind": runtime_kind,
            "resident": runtime_kind == AgentRuntimeKind.RESIDENT.value,
            "lifecycle": lifecycle,
            "spawn_origin": runtime_metadata.get("spawn_origin"),
            "metadata": runtime_metadata,
            "team_id": team_id,
            "team_member_id": team_member_id,
            "registered_at": registered_at,
            "updated_at": datetime.now().isoformat(),
            "status": "active",
        }

    def register_runtime_agent(
        self,
        *,
        agent_id: str,
        requested_type: str,
        config_profile: str,
        parent_id: Optional[str],
        role: Optional[str],
        write_scopes: Optional[List[str]] = None,
        runtime_kind: str = AgentRuntimeKind.EPHEMERAL.value,
        lifecycle: str = AgentLifecycle.READY.value,
        metadata: Optional[Dict[str, Any]] = None,
        team_id: Optional[str] = None,
        team_member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register or update one runtime agent in the unified registry."""
        self._register_agent_ledger(
            agent_id,
            requested_type=requested_type,
            config_profile=config_profile,
            parent_id=parent_id,
            role=role,
            write_scopes=write_scopes,
            runtime_kind=runtime_kind,
            lifecycle=lifecycle,
            metadata=metadata,
            team_id=team_id,
            team_member_id=team_member_id,
        )
        return dict(self._agent_ledger[agent_id])

    def set_runtime_agent_lifecycle(self, agent_id: str, lifecycle: str) -> None:
        """Update lifecycle for a registered runtime agent."""
        record = self._agent_ledger.get(agent_id)
        if not record:
            return
        record["lifecycle"] = lifecycle
        if lifecycle == AgentLifecycle.TERMINATED.value:
            record["status"] = "terminated"
            record["terminated_at"] = datetime.now().isoformat()
        else:
            record["status"] = "active"
        record["updated_at"] = datetime.now().isoformat()

    async def wait_for_runtime_agent(
        self,
        *,
        agent_id: str,
        timeout: float = 300.0,
        wait_for_result: bool = True,
    ) -> Dict[str, Any]:
        """Wait for one spawned runtime to finish and return normalized completion data."""
        spawned = self._spawned_agents.get(agent_id)
        if not spawned:
            raise ValueError(f"Runtime agent '{agent_id}' not found")

        if spawned.task_done_event:
            await asyncio.wait_for(spawned.task_done_event.wait(), timeout=timeout)
        elif spawned.lifecycle not in {AgentLifecycle.IDLE, AgentLifecycle.TERMINATED}:
            raise RuntimeError(f"Runtime agent '{agent_id}' missing completion event")

        if wait_for_result and spawned.result_done_event:
            try:
                await asyncio.wait_for(
                    spawned.result_done_event.wait(),
                    timeout=min(5.0, max(1.0, timeout)),
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "Result message not received after task completion for %s",
                    agent_id,
                )

        findings = spawned.findings or {"status": "completed"}
        success = self._is_success_findings(findings)
        return {
            "agent_id": agent_id,
            "success": success,
            "lifecycle": spawned.lifecycle.value,
            "agent_type": spawned.agent_type,
            "parent_id": spawned.parent_id,
            "role": spawned.role,
            "model": spawned.model,
            "task": spawned.task,
            "findings": findings,
            "recommended_action": (
                findings.get("recommended_action")
                or self._recommended_action_from_error_code(findings.get("error_code"))
            )
            if not success
            else None,
        }

    def _is_active_team_member_agent(self, agent_id: Optional[str]) -> bool:
        """Return True when agent_id is an active spawned member of a managed team."""
        if not agent_id:
            return False
        record = self._agent_ledger.get(agent_id) or {}
        return bool(
            record
            and record.get("status") == "active"
            and record.get("team_id")
            and record.get("team_member_id")
        )

    def _mark_agent_ledger_terminated(self, agent_id: str) -> None:
        self.set_runtime_agent_lifecycle(agent_id, AgentLifecycle.TERMINATED.value)

    def get_agent_registry_snapshot(self) -> Dict[str, Any]:
        return self.get_runtime_registry_snapshot()

    def list_runtime_agents(self, *, include_terminated: bool = True) -> List[Dict[str, Any]]:
        """List all registered runtime agents across resident and ephemeral lifecycles."""
        records = list(self._agent_ledger.values())
        if not include_terminated:
            records = [r for r in records if r.get("status") == "active"]
        return records

    def get_active_runtime_agents(self) -> List[Dict[str, Any]]:
        """Return currently active runtime agents from the unified registry."""
        return self.list_runtime_agents(include_terminated=False)

    def get_runtime_registry_snapshot(self) -> Dict[str, Any]:
        """Return unified runtime registry snapshot for resident + ephemeral agents."""
        records = self.list_runtime_agents(include_terminated=True)
        active_records = [r for r in records if r.get("status") == "active"]
        by_kind = {
            AgentRuntimeKind.RESIDENT.value: len(
                [r for r in records if r.get("runtime_kind") == AgentRuntimeKind.RESIDENT.value]
            ),
            AgentRuntimeKind.EPHEMERAL.value: len(
                [r for r in records if r.get("runtime_kind") == AgentRuntimeKind.EPHEMERAL.value]
            ),
        }
        return {
            "total_records": len(records),
            "active_records": len(active_records),
            "by_runtime_kind": by_kind,
            "records": records,
        }
