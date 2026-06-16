"""Parallel subtask contract, error, and fingerprint helpers."""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional


class ParallelContractSupport:
    def _validate_subtask_contract(self, subtask: Dict[str, Any], *, custom_mode: bool = False) -> Optional[str]:
        """Validate child task contract and return field-path error if invalid."""
        if not isinstance(subtask, dict):
            return "contract error at '$': expected object"

        version = subtask.get("contract_version", self.SUBTASK_CONTRACT_VERSION)
        if not isinstance(version, str):
            return "contract error at 'contract_version': expected string"
        if version != self.SUBTASK_CONTRACT_VERSION:
            return (
                f"contract error at 'contract_version': unsupported version '{version}', "
                f"expected '{self.SUBTASK_CONTRACT_VERSION}'"
            )

        error = self._validate_string_field(
            subtask, "task", max_length=self._subtask_task_max_chars, required=True, non_empty=True
        )
        if error:
            return error

        error = self._validate_object_field(subtask, "context", required=False)
        if error:
            return error
        error = self._validate_string_field(subtask, "role", required=False, non_empty=False)
        if error:
            return error
        error = self._validate_string_list_field(subtask, "files", required=False, non_empty_items=True)
        if error:
            return error

        if custom_mode:
            error = self._validate_object_field(subtask, "agent_definition", required=False)
            if error:
                return error
            agent_def = subtask.get("agent_definition", {})
            if agent_def is None:
                agent_def = {}
            if not isinstance(agent_def, dict):
                return "contract error at 'agent_definition': expected object"
            error = self._validate_string_field(
                agent_def, "name", required=False, non_empty=True, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_field(
                agent_def, "role", required=False, non_empty=False, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_list_field(
                agent_def, "capabilities", required=False, non_empty_items=True, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_field(
                agent_def, "agent_type", required=False, non_empty=True, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_field(
                agent_def, "config_profile", required=False, non_empty=True, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_list_field(
                agent_def, "disabled_tools", required=False, non_empty_items=True, prefix="agent_definition"
            )
            if error:
                return error
            error = self._validate_string_list_field(
                agent_def, "write_scopes", required=False, non_empty_items=True, prefix="agent_definition"
            )
            if error:
                return error

        return None

    @staticmethod
    def _validate_object_field(
        payload: Dict[str, Any],
        key: str,
        *,
        required: bool,
    ) -> Optional[str]:
        if key not in payload or payload.get(key) is None:
            if required:
                return f"contract error at '{key}': required field missing"
            return None
        if not isinstance(payload.get(key), dict):
            return f"contract error at '{key}': expected object"
        return None

    @staticmethod
    def _validate_string_field(
        payload: Dict[str, Any],
        key: str,
        *,
        required: bool,
        non_empty: bool = False,
        max_length: Optional[int] = None,
        prefix: Optional[str] = None,
    ) -> Optional[str]:
        path = f"{prefix}.{key}" if prefix else key
        if key not in payload or payload.get(key) is None:
            if required:
                return f"contract error at '{path}': required field missing"
            return None
        value = payload.get(key)
        if not isinstance(value, str):
            return f"contract error at '{path}': expected string"
        if non_empty and not value.strip():
            return f"contract error at '{path}': must be non-empty"
        if max_length is not None and len(value) > max_length:
            return f"contract error at '{path}': max length is {max_length}"
        return None

    @staticmethod
    def _validate_string_list_field(
        payload: Dict[str, Any],
        key: str,
        *,
        required: bool,
        non_empty_items: bool = False,
        prefix: Optional[str] = None,
    ) -> Optional[str]:
        path = f"{prefix}.{key}" if prefix else key
        if key not in payload or payload.get(key) is None:
            if required:
                return f"contract error at '{path}': required field missing"
            return None
        value = payload.get(key)
        if not isinstance(value, list):
            return f"contract error at '{path}': expected array"
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                return f"contract error at '{path}[{idx}]': expected string"
            if non_empty_items and not item.strip():
                return f"contract error at '{path}[{idx}]': must be non-empty"
        return None

    def _subtask_fingerprint(
        self,
        subtask: Dict[str, Any],
        *,
        parent_id: str,
        agent_type: str,
        custom_mode: bool = False,
    ) -> str:
        """Create stable fingerprint for idempotency/dedup."""
        canonical = {
            "mode": "custom" if custom_mode else "standard",
            "parent_id": parent_id,
            "agent_type": agent_type,
            "task": subtask.get("task", ""),
            "context": subtask.get("context", {}),
            "role": subtask.get("role"),
            "files": sorted(subtask.get("files", []) or []),
            "agent_definition": subtask.get("agent_definition", {}) if custom_mode else {},
        }
        payload = json.dumps(canonical, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _record_completed_subtask(self, fingerprint: str) -> None:
        self._completed_subtask_fingerprints[fingerprint] = time.time()
        self._prune_metrics()

    @staticmethod
    def _extract_error_code(message: Optional[str], fallback: str = "E_AGENT_ERROR") -> str:
        if not message:
            return fallback
        text = str(message).strip()
        if text.startswith("E_"):
            code = text.split(":", 1)[0].strip()
            if code:
                return code
        return fallback

    @classmethod
    def _error_payload(
        cls,
        *,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "success": False,
            "error_code": code,
            "error_message": message,
            "error": message,
        }
        recommended_action = cls._recommended_action_from_error_code(code)
        if recommended_action:
            payload["recommended_action"] = recommended_action
        if details:
            payload["error_details"] = details
        return payload

    @staticmethod
    def _recommended_action_from_error_code(code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        mapping = {
            "E_CHILD_TASK_CONTRACT": "fix_payload_and_revalidate",
            "E_SPAWN_BUDGET_EXCEEDED": "wait_cooldown_or_split_batch",
            "E_SPAWN_CIRCUIT_OPEN": "wait_cooldown_or_split_batch",
            "E_PARENT_ACTIVE_CAP_REACHED": "wait_for_children_or_reduce_fanout",
            "E_AGENT_TIMEOUT": "retry_once_with_lower_concurrency",
            "E_AGENT_NO_COMPLETION_EVENT": "retry_once_and_check_runtime_health",
            "E_AGENT_EXECUTION": "route_to_domain_owner_with_diagnostics",
            "E_AGENT_ERROR": "route_to_domain_owner_with_diagnostics",
            "E_NOT_EXECUTED": "resolve_upstream_blockers_then_rerun",
            "E_FILE_CLAIM_CONFLICT": "split_file_ownership_then_rerun",
        }
        return mapping.get(code, "inspect_error_and_route_owner")

    @classmethod
    def _recommended_actions_summary(cls, result_items: List[Dict[str, Any]]) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for item in result_items:
            if not isinstance(item, dict):
                continue
            action = item.get("recommended_action")
            if not action:
                continue
            summary[action] = summary.get(action, 0) + 1
        return summary
