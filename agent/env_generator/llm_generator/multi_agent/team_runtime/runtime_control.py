"""Runtime spawning, termination, and governance support."""

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import yaml

from ..agent_spawn_service import AgentSpawnRequest
from .models import AgentLifecycle, SpawnedAgent


class RuntimeControlSupport:
    @staticmethod
    def _cfg_int(raw: Any, key: str, default: int, min_value: Optional[int] = None) -> int:
        try:
            value = int(raw.get(key, default))
        except Exception:
            return default
        if min_value is not None:
            value = max(min_value, value)
        return value

    @staticmethod
    def _cfg_float(raw: Any, key: str, default: float, min_value: Optional[float] = None) -> float:
        try:
            value = float(raw.get(key, default))
        except Exception:
            return default
        if min_value is not None:
            value = max(min_value, value)
        return value

    @staticmethod
    def _slug(value: Optional[str], max_len: int = 20) -> str:
        """Normalize id fragments for safe, readable agent IDs."""
        text = (value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text[:max_len] or "agent"

    def _build_spawn_worker_id(self, worker_type: str, parent_id: Optional[str]) -> str:
        """Build a stable, collision-safe runtime ID."""
        type_part = self._slug(worker_type, max_len=20)
        parent_part = self._slug(parent_id or "root", max_len=16)
        existing_ids: Set[str] = set(self._spawned_agents.keys()) | set(self._orchestrator._agents.keys())

        while True:
            suffix = uuid4().hex[:8]
            candidate = f"worker_{parent_part}_{type_part}_{suffix}"
            if candidate not in existing_ids:
                return candidate

    def _init_dynamic_team_rules(self) -> None:
        """Load dynamic-team governance knobs from YAML with safe defaults."""
        rules_path: Optional[Path] = None
        module_relative = Path(__file__).resolve().parent.parent / "docs" / "dynamic_team_rules.yaml"
        workspace_relative = self.DYNAMIC_TEAM_RULES_RELATIVE_PATH

        for candidate in (module_relative, workspace_relative):
            try:
                if candidate.exists():
                    rules_path = candidate
                    break
            except Exception:
                continue

        if not rules_path:
            return

        try:
            raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
            governance = raw.get("dynamic_team_governance", raw)
            if not isinstance(governance, dict):
                self._logger.warning("dynamic_team_rules.yaml has invalid root type; using defaults")
                return

            self._spawn_window_seconds = self._cfg_float(
                governance, "spawn_window_seconds", self._spawn_window_seconds, min_value=1.0
            )
            self._spawn_budget_per_window = self._cfg_int(
                governance, "spawn_budget_per_window", self._spawn_budget_per_window, min_value=1
            )
            self._max_active_per_parent = self._cfg_int(
                governance, "max_active_per_parent", self._max_active_per_parent, min_value=1
            )
            self._failure_window_seconds = self._cfg_float(
                governance, "failure_window_seconds", self._failure_window_seconds, min_value=5.0
            )
            self._circuit_min_samples = self._cfg_int(
                governance, "circuit_min_samples", self._circuit_min_samples, min_value=1
            )
            self._circuit_threshold = self._cfg_float(
                governance, "circuit_threshold", self._circuit_threshold, min_value=0.0
            )
            self._circuit_threshold = min(1.0, self._circuit_threshold)
            self._circuit_cooldown_seconds = self._cfg_float(
                governance, "circuit_cooldown_seconds", self._circuit_cooldown_seconds, min_value=1.0
            )
            self._subtask_fingerprint_ttl_seconds = self._cfg_float(
                governance,
                "subtask_fingerprint_ttl_seconds",
                self._subtask_fingerprint_ttl_seconds,
                min_value=1.0,
            )
            self._subtask_task_max_chars = self._cfg_int(
                governance, "subtask_task_max_chars", self._subtask_task_max_chars, min_value=100
            )
            self._read_mostly_max_parallel = self._cfg_int(
                governance,
                "read_mostly_max_parallel",
                governance.get("investigator_reviewer_max_parallel", self._read_mostly_max_parallel),
                min_value=1,
            )
            self._write_low_risk_max_parallel = self._cfg_int(
                governance,
                "write_low_risk_max_parallel",
                governance.get("helper_low_risk_max_parallel", self._write_low_risk_max_parallel),
                min_value=1,
            )
            self._write_medium_risk_max_parallel = self._cfg_int(
                governance,
                "write_medium_risk_max_parallel",
                governance.get("helper_medium_risk_max_parallel", self._write_medium_risk_max_parallel),
                min_value=1,
            )
            self._write_high_risk_max_parallel = self._cfg_int(
                governance,
                "write_high_risk_max_parallel",
                governance.get("helper_high_risk_max_parallel", self._write_high_risk_max_parallel),
                min_value=1,
            )
            self._failure_rate_medium_threshold = self._cfg_float(
                governance, "failure_rate_medium_threshold", self._failure_rate_medium_threshold, min_value=0.0
            )
            self._failure_rate_high_threshold = self._cfg_float(
                governance, "failure_rate_high_threshold", self._failure_rate_high_threshold, min_value=0.0
            )
            self._failure_rate_medium_threshold = min(1.0, self._failure_rate_medium_threshold)
            self._failure_rate_high_threshold = min(1.0, self._failure_rate_high_threshold)
            if self._failure_rate_high_threshold < self._failure_rate_medium_threshold:
                self._failure_rate_high_threshold = self._failure_rate_medium_threshold
            self._failure_rate_medium_cap = self._cfg_int(
                governance, "failure_rate_medium_cap", self._failure_rate_medium_cap, min_value=1
            )
            self._failure_rate_high_cap = self._cfg_int(
                governance, "failure_rate_high_cap", self._failure_rate_high_cap, min_value=1
            )

            self._logger.info("Loaded dynamic team governance rules from %s", rules_path)
        except Exception as e:
            self._logger.warning(f"Failed to load dynamic team rules ({rules_path}): {e}")

    def _enforce_spawn_guards(self, parent_id: Optional[str]) -> None:
        now = time.time()
        if now < self._circuit_open_until:
            remaining = int(self._circuit_open_until - now)
            raise RuntimeError(
                f"E_SPAWN_CIRCUIT_OPEN: Spawn circuit breaker active for {remaining}s due to high recent failure rate."
            )

        available = self._available_spawn_budget()
        if available <= 0:
            raise RuntimeError(
                f"E_SPAWN_BUDGET_EXCEEDED: Spawn budget exhausted: "
                f"{self._spawn_budget_per_window}/{self._spawn_window_seconds:.0f}s window."
            )

        if parent_id:
            active_for_parent = sum(
                1
                for a in self._spawned_agents.values()
                if a.parent_id == parent_id
                and a.lifecycle not in (AgentLifecycle.TERMINATED, AgentLifecycle.SHUTTING_DOWN)
            )
            if active_for_parent >= self._max_active_per_parent:
                raise RuntimeError(
                    f"E_PARENT_ACTIVE_CAP_REACHED: Parent '{parent_id}' reached active spawned-agent cap "
                    f"({self._max_active_per_parent})."
                )

    async def spawn_worker(
        self,
        worker_type: str,
        task: str,
        parent_id: Optional[str] = None,
        role: Optional[str] = None,
        model: Optional[str] = None,
        custom_name: Optional[str] = None,
        disabled_tools: Optional[List[str]] = None,
        config_key: Optional[str] = None,
        skills: Optional[List[str]] = None,
        inherit_parent_skills: bool = True,
        write_scopes: Optional[List[str]] = None,
        include_vision: Optional[bool] = None,
        team_id: Optional[str] = None,
        team_member_id: Optional[str] = None,
    ) -> str:
        requested_worker_type = (worker_type or "").strip() or "worker"

        if self._is_active_team_member_agent(parent_id) and not team_id:
            raise ValueError(
                "Nested spawning is not allowed: team members cannot spawn additional workers."
            )

        if parent_id == "orchestrator" and requested_worker_type.lower() in self.STATIC_CORE_AGENT_TYPES:
            raise ValueError(
                f"orchestrator cannot spawn duplicate core static role '{requested_worker_type}'. "
                "Send task_ready to the existing static agent instead."
            )

        self._enforce_spawn_guards(parent_id)
        agent_id = self._build_spawn_worker_id(worker_type=requested_worker_type, parent_id=parent_id)

        spawned = SpawnedAgent(
            agent_id=agent_id,
            agent_type=requested_worker_type,
            parent_id=parent_id,
            task=task,
            role=role or custom_name,
            model=model,
            result_done_event=asyncio.Event(),
        )
        self._spawned_agents[agent_id] = spawned

        try:
            spawn_result = await self._orchestrator.spawn_service.spawn(
                AgentSpawnRequest(
                    agent_id=agent_id,
                    agent_type=requested_worker_type,
                    task=task,
                    parent_id=parent_id,
                    role=role,
                    model=model,
                    custom_name=custom_name,
                    disabled_tools=disabled_tools,
                    write_scopes=write_scopes,
                    config_key=config_key,
                    skills=skills,
                    inherit_parent_skills=inherit_parent_skills,
                    include_vision=include_vision,
                    resident=False,
                    metadata={
                        "spawn_origin": "dynamic_agent_manager",
                        "team_id": team_id,
                        "team_member_id": team_member_id,
                    },
                )
            )

            spawned.lifecycle = AgentLifecycle.READY
            self._spawn_events.append(time.time())
            self._prune_metrics()
            self._logger.info(
                f"Spawned worker: {agent_id} (requested_type={requested_worker_type}, "
                f"config_profile={spawn_result.config_profile}, role={role})"
            )

            if spawn_result.task_done_event:
                if spawned.result_done_event:
                    spawned.result_done_event.clear()
                spawned.task_done_event = spawn_result.task_done_event
                spawned.lifecycle = AgentLifecycle.WORKING
                self.set_runtime_agent_lifecycle(agent_id, AgentLifecycle.WORKING.value)

            for callback in self._spawn_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(spawned)
                    else:
                        callback(spawned)
                except Exception as e:
                    self._logger.error(f"Spawn callback error: {e}")

            return agent_id
        except Exception as e:
            self._logger.error(f"Failed to spawn worker {agent_id}: {e}")
            spawned.lifecycle = AgentLifecycle.TERMINATED
            self._failure_events.append(time.time())
            self._prune_metrics()
            total_recent = len(self._failure_events) + len(self._success_events)
            if total_recent >= self._circuit_min_samples and self._recent_failure_rate() >= self._circuit_threshold:
                self._circuit_open_until = time.time() + self._circuit_cooldown_seconds
                self._logger.warning(
                    "Spawn circuit opened for %.0fs (failure_rate=%.2f)",
                    self._circuit_cooldown_seconds,
                    self._recent_failure_rate(),
                )
            raise

    async def terminate_runtime_agent(self, agent_id: str, wait: bool = True) -> bool:
        """Terminate a spawned runtime worker."""
        if agent_id not in self._spawned_agents:
            self._logger.warning(f"Runtime agent {agent_id} not found in spawned workers")
            return False

        spawned = self._spawned_agents[agent_id]
        spawned.lifecycle = AgentLifecycle.SHUTTING_DOWN

        try:
            terminated = await self._orchestrator.spawn_service.terminate(agent_id, wait=wait)
            if not terminated:
                return False

            spawned.lifecycle = AgentLifecycle.TERMINATED
            self._mark_agent_ledger_terminated(agent_id)
            self._logger.info(f"Terminated runtime agent: {agent_id}")

            for callback in self._terminate_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(spawned)
                    else:
                        callback(spawned)
                except Exception as e:
                    self._logger.error(f"Terminate callback error: {e}")

            return True
        except Exception as e:
            self._logger.error(f"Error terminating runtime agent {agent_id}: {e}")
            return False
