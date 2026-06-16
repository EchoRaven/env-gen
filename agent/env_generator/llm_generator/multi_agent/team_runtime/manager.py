"""Dynamic runtime agent manager extracted from team_protocols."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .contracts import TeamContractSupport
from .lifecycle import TeamLifecycleSupport
from .models import (
    AgentLifecycle,
    AgentRuntimeKind,
    AgentTeam,
    CandidateStatus,
    ParallelReasoningResult,
    Plan,
    PlanStatus,
    PracticeType,
    ReasoningCandidate,
    SpawnedAgent,
    TeamAgentSpec,
    TeamPractice,
)
from .notifications import RuntimeNotificationSupport
from .parallel import ParallelExecutionSupport
from .registry import RuntimeRegistrySupport
from .runtime_control import RuntimeControlSupport


class DynamicAgentManager(
    RuntimeRegistrySupport,
    RuntimeControlSupport,
    RuntimeNotificationSupport,
    TeamContractSupport,
    TeamLifecycleSupport,
    ParallelExecutionSupport,
):
    """
    Manages runtime agent spawning and lifecycle.

    Features:
    - Spawn task-scoped workers on demand with specific tasks/roles
    - Track resident + ephemeral runtime lifecycle
    - Cleanup terminated runtimes
    - Keep resident lanes and task-scoped workers in one runtime registry
    """

    DYNAMIC_TEAM_RULES_RELATIVE_PATH = Path(
        "agent/env_generator/llm_generator/multi_agent/docs/dynamic_team_rules.yaml"
    )
    SUBTASK_CONTRACT_VERSION = "v1"
    STATIC_CORE_AGENT_TYPES = {
        "design", "database", "backend", "frontend",
        "verifier", "knowledge", "orchestrator",
    }

    def __init__(self, orchestrator: Any):
        self._orchestrator = orchestrator
        self._spawned_agents: Dict[str, SpawnedAgent] = {}
        self._agent_ledger: Dict[str, Dict[str, Any]] = {}
        self._agent_teams: Dict[str, AgentTeam] = {}
        self._team_launch_tasks: Dict[str, asyncio.Task] = {}
        self._logger = logging.getLogger("DynamicAgentManager")
        self._spawn_callbacks: List[Callable] = []
        self._terminate_callbacks: List[Callable] = []
        self._result_subscription_id: Optional[str] = None
        self._spawn_events: List[float] = []
        self._failure_events: List[float] = []
        self._success_events: List[float] = []
        self._spawn_window_seconds: float = 120.0
        self._spawn_budget_per_window: int = 24
        self._max_active_per_parent: int = 8
        self._failure_window_seconds: float = 300.0
        self._circuit_min_samples: int = 8
        self._circuit_threshold: float = 0.55
        self._circuit_cooldown_seconds: float = 45.0
        self._circuit_open_until: float = 0.0
        self._completed_subtask_fingerprints: Dict[str, float] = {}
        self._subtask_fingerprint_ttl_seconds: float = 900.0
        self._subtask_task_max_chars: int = 8000
        self._read_mostly_max_parallel: int = 8
        self._write_low_risk_max_parallel: int = 6
        self._write_medium_risk_max_parallel: int = 3
        self._write_high_risk_max_parallel: int = 2
        self._failure_rate_medium_threshold: float = 0.3
        self._failure_rate_high_threshold: float = 0.5
        self._failure_rate_medium_cap: int = 3
        self._failure_rate_high_cap: int = 2
        self._parallel_run_durations: List[float] = []
        self._max_parallel_duration_samples: int = 100
        self._observed_subtasks_total: int = 0
        self._observed_deduped_total: int = 0
        self._observed_contract_rejected_total: int = 0
        self._recommended_actions_total: Dict[str, int] = {}
        self._last_recommended_actions_summary: Dict[str, int] = {}
        self._file_claim_lock = asyncio.Lock()
        self._active_file_claims: Dict[str, Dict[str, Any]] = {}
        self._file_claim_ttl_seconds: float = 1800.0
        self._recent_conflict_notifications: Dict[str, float] = {}
        self._conflict_notification_ttl_seconds: float = 30.0
        self._init_dynamic_team_rules()

        try:
            from utils.message import MessageType

            self._result_subscription_id = self._orchestrator.message_bus.subscribe(
                subscriber_id="dynamic_agent_manager",
                message_types=[MessageType.RESULT, MessageType.ERROR],
                callback=self._on_agent_result_message,
            )
        except Exception as e:
            self._logger.warning(f"Failed to subscribe result tracking: {e}")

    @classmethod
    def _normalize_findings(
        cls,
        *,
        result_data: Any,
        payload: Any,
        success_flag: bool,
        error_message: Optional[str],
    ) -> Dict[str, Any]:
        """Normalize spawned findings into an error_code-first schema."""
        if isinstance(result_data, dict):
            normalized = dict(result_data)
        elif isinstance(payload, dict):
            normalized = dict(payload)
        else:
            normalized = {
                "success": bool(success_flag),
                "result": result_data if result_data is not None else payload,
            }

        explicit_error = normalized.get("error_message") or normalized.get("error")
        code = normalized.get("error_code")
        if error_message:
            explicit_error = error_message
        if explicit_error and not code:
            code = cls._extract_error_code(str(explicit_error), fallback="E_AGENT_ERROR")

        if code:
            normalized["error_code"] = code
            if "recommended_action" not in normalized:
                recommended_action = cls._recommended_action_from_error_code(code)
                if recommended_action:
                    normalized["recommended_action"] = recommended_action
        if explicit_error:
            normalized["error_message"] = str(explicit_error)
            normalized["error"] = str(explicit_error)
            normalized["success"] = False
        elif "success" not in normalized:
            normalized["success"] = bool(success_flag)

        return normalized

    @staticmethod
    def _is_success_findings(findings: Dict[str, Any]) -> bool:
        if not isinstance(findings, dict):
            return False
        if findings.get("error_code") or findings.get("error"):
            return False
        return bool(findings.get("success", True))


__all__ = [
    "DynamicAgentManager",
    "SpawnedAgent",
    "AgentLifecycle",
    "AgentRuntimeKind",
    "TeamAgentSpec",
    "AgentTeam",
    "CandidateStatus",
    "ReasoningCandidate",
    "ParallelReasoningResult",
    "PlanStatus",
    "Plan",
    "PracticeType",
    "TeamPractice",
]
