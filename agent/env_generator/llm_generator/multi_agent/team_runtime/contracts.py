"""File-contract and conflict reporting support for dynamic agent management."""

import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from .models import AgentTeam, TeamAgentSpec


class TeamContractSupport:
    @staticmethod
    def _extract_string_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",")]
            return [p for p in parts if p]
        if isinstance(value, list):
            out: List[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
            return out
        return []

    @staticmethod
    def _validate_file_contract_context_shape(context: Dict[str, Any]) -> Optional[str]:
        """Validate file-contract keys in member context."""
        if not isinstance(context, dict):
            return "context must be an object"
        for key in ("owned_files", "forbidden_files"):
            if key in context and not isinstance(context.get(key), (str, list)):
                return f"context.{key} must be string or list[string]"
        nested = context.get("file_contract")
        if nested is not None:
            if not isinstance(nested, dict):
                return "context.file_contract must be an object"
            for key in ("owned_files", "forbidden_files"):
                if key in nested and not isinstance(nested.get(key), (str, list)):
                    return f"context.file_contract.{key} must be string or list[string]"
        return None

    def _collect_member_file_contract(self, spec: TeamAgentSpec) -> Tuple[List[str], List[str]]:
        """
        Collect normalized ownership/forbidden file claims from team member context.
        Supports both direct and nested keys:
        - owned_files / forbidden_files
        - file_contract.owned_files / file_contract.forbidden_files
        """
        ctx = spec.context if isinstance(spec.context, dict) else {}
        direct_owned = self._extract_string_list(ctx.get("owned_files"))
        direct_forbidden = self._extract_string_list(ctx.get("forbidden_files"))
        file_contract = ctx.get("file_contract") if isinstance(ctx.get("file_contract"), dict) else {}
        nested_owned = self._extract_string_list(file_contract.get("owned_files"))
        nested_forbidden = self._extract_string_list(file_contract.get("forbidden_files"))
        owned_raw = direct_owned + nested_owned
        forbidden_raw = direct_forbidden + nested_forbidden

        owned: List[str] = []
        forbidden: List[str] = []
        owned_seen: Set[str] = set()
        forbidden_seen: Set[str] = set()
        for raw in owned_raw:
            normalized = self._normalize_declared_file_path(raw)
            if normalized and normalized not in owned_seen:
                owned_seen.add(normalized)
                owned.append(normalized)
        for raw in forbidden_raw:
            normalized = self._normalize_declared_file_path(raw)
            if normalized and normalized not in forbidden_seen:
                forbidden_seen.add(normalized)
                forbidden.append(normalized)
        return owned, forbidden

    def _validate_team_member_file_ownership(self, team: AgentTeam) -> Dict[str, Any]:
        """
        Validate ownership contracts before team launch.
        Returns structured conflict report (empty lists means valid).
        """
        owners_by_file: Dict[str, List[str]] = {}
        self_conflicts: List[Dict[str, Any]] = []

        for member_id, spec in team.members.items():
            owned_files, forbidden_files = self._collect_member_file_contract(spec)
            forbidden_set = set(forbidden_files)
            overlap = sorted(set(owned_files) & forbidden_set)
            if overlap:
                self_conflicts.append(
                    {
                        "member_id": member_id,
                        "conflicting_files": overlap,
                    }
                )
            for path in owned_files:
                owners_by_file.setdefault(path, []).append(member_id)

        duplicate_owners: List[Dict[str, Any]] = []
        for path, owners in owners_by_file.items():
            if len(owners) > 1:
                duplicate_owners.append({"file": path, "owners": sorted(owners)})

        return {
            "duplicate_owners": sorted(duplicate_owners, key=lambda x: x["file"]),
            "self_conflicts": sorted(self_conflicts, key=lambda x: x["member_id"]),
        }

    def _report_team_conflict_to_hub(
        self,
        *,
        conflict_type: str,
        team_id: str,
        parent_id: Optional[str],
        details: Dict[str, Any],
        severity: str = "error",
    ) -> None:
        """
        Publish team/file conflicts into HubRegistry for cross-agent observability.
        Best-effort only; never breaks execution flow.
        """
        hubs = getattr(self._orchestrator, "hubs", None)
        if hubs is None:
            return
        try:
            recommended_fix = self._build_conflict_recommended_fix(
                conflict_type=conflict_type,
                team_id=team_id,
                parent_id=parent_id,
                details=details,
            )
            event = {
                "type": conflict_type,
                "severity": severity,
                "team_id": team_id,
                "parent_id": parent_id,
                "details": details,
                "recommended_fix": recommended_fix,
                "reported_at": datetime.now().isoformat(),
                "source": "dynamic_agent_manager",
            }
            owner_key = (parent_id or f"team:{team_id}" or "dynamic_agent_manager").strip() or "dynamic_agent_manager"
            try:
                existing_statuses = hubs.eventhub.get_all_agent_statuses()
            except Exception:
                existing_statuses = {}
            merged_status = dict(existing_statuses.get(owner_key) or {})
            history = merged_status.get("team_conflicts")
            if not isinstance(history, list):
                history = []
            history.append(event)
            merged_status["team_conflicts"] = history[-20:]
            merged_status["last_team_conflict"] = event
            merged_status["team_conflict_count"] = len(merged_status["team_conflicts"])
            try:
                hubs.eventhub.record_agent_status(owner_key, merged_status)
            except Exception:
                pass

            if hasattr(hubs, "publish_task"):
                task_id = f"team_conflict_{team_id}_{int(time.time() * 1000)}_{uuid4().hex[:6]}"
                hubs.publish_task(
                    task_id,
                    {
                        "type": "team_conflict",
                        "status": "open",
                        "team_id": team_id,
                        "parent_id": parent_id,
                        "conflict_type": conflict_type,
                        "severity": severity,
                        "details": details,
                        "recommended_fix": recommended_fix,
                    },
                    agent="dynamic_agent_manager",
                )
            self._schedule_conflict_replan_notification(
                conflict_type=conflict_type,
                team_id=team_id,
                parent_id=parent_id,
                details=details,
                recommended_fix=recommended_fix,
            )
        except Exception as e:
            self._logger.debug(f"Failed to report team conflict to hub: {e}")

    @staticmethod
    def _recommended_action_from_conflict_type(conflict_type: str) -> str:
        if conflict_type in {"launch_contract_conflict"}:
            return "fix_team_member_file_contract_then_relaunch"
        if conflict_type in {"parallel_preclaim_conflict", "profiled_preclaim_conflict"}:
            return "rebalance_subtasks_by_file_then_rerun_parallel"
        if conflict_type in {"parallel_runtime_claim_conflict", "profiled_runtime_claim_conflict"}:
            return "pause_conflicting_workers_and_split_file_ownership"
        return "inspect_conflict_and_replan"

    def _build_conflict_recommended_fix(
        self,
        *,
        conflict_type: str,
        team_id: str,
        parent_id: Optional[str],
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build actionable, machine-readable conflict recovery guidance."""
        steps: List[str] = [
            "Ensure each writable file has exactly one owner.",
            "Move shared files to integration-only ownership (single integrator).",
            "Relaunch only blocked/failed subtasks after repartition.",
        ]
        file_reassignment: List[Dict[str, Any]] = []

        duplicate_owners = details.get("duplicate_owners") if isinstance(details, dict) else None
        if isinstance(duplicate_owners, list):
            for item in duplicate_owners:
                if not isinstance(item, dict):
                    continue
                file_path = item.get("file")
                owners = item.get("owners") or []
                if isinstance(file_path, str) and isinstance(owners, list) and owners:
                    file_reassignment.append(
                        {
                            "file": file_path,
                            "proposed_owner": owners[0],
                            "remove_from": [o for o in owners[1:] if isinstance(o, str)],
                        }
                    )

        blocked = details.get("blocked") if isinstance(details, dict) else None
        if isinstance(blocked, dict):
            for idx, meta in blocked.items():
                if not isinstance(meta, dict):
                    continue
                conflicts = meta.get("conflicts") or []
                if not isinstance(conflicts, list):
                    continue
                for c in conflicts:
                    if not isinstance(c, dict):
                        continue
                    fp = c.get("file")
                    owner_idx = c.get("owned_by_subtask_index")
                    if isinstance(fp, str):
                        file_reassignment.append(
                            {
                                "file": fp,
                                "proposed_owner_subtask_index": owner_idx,
                                "blocked_subtask_index": idx,
                            }
                        )

        return {
            "strategy": "single_writer_per_file",
            "recommended_action": self._recommended_action_from_conflict_type(conflict_type),
            "team_id": team_id,
            "parent_id": parent_id,
            "steps": steps,
            "file_reassignment": file_reassignment[:50],
        }

    def _schedule_conflict_replan_notification(
        self,
        *,
        conflict_type: str,
        team_id: str,
        parent_id: Optional[str],
        details: Dict[str, Any],
        recommended_fix: Dict[str, Any],
    ) -> None:
        """Best-effort async notification to parent agent for immediate replanning."""
        if not parent_id:
            return
        bus = getattr(self._orchestrator, "message_bus", None)
        if bus is None:
            return
        try:
            details_fingerprint = hashlib.sha1(
                json.dumps(details, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            notify_key = f"{parent_id}:{conflict_type}:{team_id}:{details_fingerprint}"
            now = time.time()
            self._recent_conflict_notifications = {
                k: ts
                for k, ts in self._recent_conflict_notifications.items()
                if now - ts <= self._conflict_notification_ttl_seconds
            }
            last_ts = self._recent_conflict_notifications.get(notify_key)
            if last_ts and (now - last_ts) <= self._conflict_notification_ttl_seconds:
                return
            self._recent_conflict_notifications[notify_key] = now

            from utils.message import BaseMessage, MessageHeader, MessagePriority, MessageType

            async def _notify() -> None:
                msg = BaseMessage(
                    message_type=MessageType.TASK,
                    header=MessageHeader(
                        source_agent_id="dynamic_agent_manager",
                        target_agent_id=parent_id,
                        priority=MessagePriority.HIGH,
                    ),
                    payload={
                        "type": "team_conflict_replan_request",
                        "team_id": team_id,
                        "conflict_type": conflict_type,
                        "details": details,
                        "recommended_fix": recommended_fix,
                        "instruction": (
                            "Replan now: enforce single-writer ownership, split overlapping files, "
                            "and relaunch only blocked/failed subtasks."
                        ),
                    },
                )
                await bus.send(msg)

            loop = asyncio.get_running_loop()
            loop.create_task(_notify())
        except Exception as e:
            self._logger.debug(f"Failed to schedule conflict replan notification: {e}")
