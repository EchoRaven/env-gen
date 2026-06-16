"""Parallel execution metrics and runtime summaries."""

import time
from datetime import datetime
from typing import Any, Callable, Dict, List

from ..models import AgentLifecycle, SpawnedAgent


class ParallelMetricsSupport:
    def _prune_metrics(self) -> None:
        now = time.time()
        self._spawn_events = [t for t in self._spawn_events if now - t <= self._spawn_window_seconds]
        self._failure_events = [t for t in self._failure_events if now - t <= self._failure_window_seconds]
        self._success_events = [t for t in self._success_events if now - t <= self._failure_window_seconds]
        self._completed_subtask_fingerprints = {
            fp: ts
            for fp, ts in self._completed_subtask_fingerprints.items()
            if now - ts <= self._subtask_fingerprint_ttl_seconds
        }

    def _record_subtask_outcome(self, success: bool) -> None:
        now = time.time()
        if success:
            self._success_events.append(now)
        else:
            self._failure_events.append(now)
        self._prune_metrics()

    def _record_parallel_observability(
        self,
        *,
        total_subtasks: int,
        deduped_count: int,
        contract_rejected_count: int,
        duration_seconds: float,
        recommended_actions_summary: Dict[str, int],
    ) -> None:
        self._observed_subtasks_total += max(0, int(total_subtasks))
        self._observed_deduped_total += max(0, int(deduped_count))
        self._observed_contract_rejected_total += max(0, int(contract_rejected_count))
        self._parallel_run_durations.append(float(max(0.0, duration_seconds)))
        if len(self._parallel_run_durations) > self._max_parallel_duration_samples:
            self._parallel_run_durations = self._parallel_run_durations[-self._max_parallel_duration_samples :]

        self._last_recommended_actions_summary = dict(recommended_actions_summary or {})
        for action, count in (recommended_actions_summary or {}).items():
            if not action:
                continue
            self._recommended_actions_total[action] = self._recommended_actions_total.get(action, 0) + int(count)

    def _recent_failure_rate(self) -> float:
        self._prune_metrics()
        failures = len(self._failure_events)
        successes = len(self._success_events)
        total = failures + successes
        if total <= 0:
            return 0.0
        return failures / total

    def _available_spawn_budget(self) -> int:
        self._prune_metrics()
        return max(0, self._spawn_budget_per_window - len(self._spawn_events))

    def get_spawned_agents(self) -> List[SpawnedAgent]:
        """Get all spawned agents."""
        return list(self._spawned_agents.values())

    def get_active_agents(self) -> List[SpawnedAgent]:
        """Get only active (non-terminated) agents."""
        return [
            a for a in self._spawned_agents.values()
            if a.lifecycle not in (AgentLifecycle.TERMINATED, AgentLifecycle.SHUTTING_DOWN)
        ]

    def get_team_health_summary(self) -> Dict[str, Any]:
        """Return lightweight operational health snapshot for dynamic collaboration."""
        self._prune_metrics()
        now = time.time()
        circuit_open = now < self._circuit_open_until
        circuit_remaining_seconds = max(0.0, self._circuit_open_until - now)
        active_agents = self.get_active_agents()
        active_runtime_agents = self.get_active_runtime_agents()
        runtime_snapshot = self.get_runtime_registry_snapshot()
        total_observed = max(1, self._observed_subtasks_total)
        avg_parallel_duration = (
            sum(self._parallel_run_durations) / len(self._parallel_run_durations)
            if self._parallel_run_durations
            else 0.0
        )
        return {
            "timestamp": datetime.now().isoformat(),
            "active_agents": len(active_runtime_agents),
            "active_ephemeral_agents": len(active_agents),
            "total_spawned_agents": len(self._spawned_agents),
            "total_runtime_agents": runtime_snapshot["total_records"],
            "runtime_registry": {
                "active_records": runtime_snapshot["active_records"],
                "by_runtime_kind": runtime_snapshot["by_runtime_kind"],
            },
            "recent_failure_rate": round(self._recent_failure_rate(), 3),
            "recent_success_count": len(self._success_events),
            "recent_failure_count": len(self._failure_events),
            "spawn_budget": {
                "remaining": self._available_spawn_budget(),
                "limit_per_window": self._spawn_budget_per_window,
                "window_seconds": self._spawn_window_seconds,
            },
            "circuit_breaker": {
                "open": circuit_open,
                "cooldown_remaining_seconds": round(circuit_remaining_seconds, 1),
                "threshold": self._circuit_threshold,
                "min_samples": self._circuit_min_samples,
            },
            "dedup": {
                "cached_fingerprints": len(self._completed_subtask_fingerprints),
                "observed_deduped_total": self._observed_deduped_total,
                "observed_subtasks_total": self._observed_subtasks_total,
                "observed_dedup_rate": round(self._observed_deduped_total / total_observed, 3),
            },
            "contract_validation": {
                "observed_rejected_total": self._observed_contract_rejected_total,
                "observed_rejected_rate": round(self._observed_contract_rejected_total / total_observed, 3),
                "task_max_chars": self._subtask_task_max_chars,
            },
            "parallel_runtime": {
                "recent_run_count": len(self._parallel_run_durations),
                "avg_duration_seconds": round(avg_parallel_duration, 3),
            },
            "recommended_actions": {
                "last_summary": self._last_recommended_actions_summary,
                "totals": self._recommended_actions_total,
            },
        }

    def on_spawn(self, callback: Callable) -> None:
        """Register callback for agent spawn."""
        self._spawn_callbacks.append(callback)

    def on_terminate(self, callback: Callable) -> None:
        """Register callback for agent termination."""
        self._terminate_callbacks.append(callback)

    async def cleanup_all(self) -> int:
        """Terminate all spawned agents."""
        count = 0
        for agent_id in list(self._spawned_agents.keys()):
            if await self.terminate_runtime_agent(agent_id, wait=False):
                count += 1
        return count
