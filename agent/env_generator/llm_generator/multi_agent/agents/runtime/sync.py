from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.message import BaseMessage, MessageHeader, MessagePriority, MessageType


class AgentSync:
    async def _process_pending_notifications(
        self,
        *,
        flush_bus: bool = True,
        flush_knowledge: bool = True,
    ) -> None:
        """Flush queued notifications/knowledge at controlled sync points."""
        pending = getattr(self, "_pending_notifications", None)
        if flush_bus and pending:
            for bus, msg in pending:
                try:
                    await bus.send(msg)
                    target = msg.header.target_agent_id
                    msg_type = msg.metadata.get("msg_type", "notification")
                    self._logger.info(f"[{self.agent_id}] Sent {msg_type} to {target}")
                except Exception as e:
                    self._logger.error(f"[{self.agent_id}] Failed to send notification: {e}")
            self._pending_notifications = []

        if flush_knowledge:
            await self._process_knowledge_shares()

    async def _process_knowledge_shares(self) -> None:
        """Process outgoing knowledge shares queued by memory tools."""
        if hasattr(self, "memory"):
            outgoing = self.memory.get_outgoing_knowledge()
            if not outgoing:
                return

            bus = getattr(self, "_external_bus", None) or getattr(self, "_message_bus", None)
            if not bus:
                return

            from uuid import uuid4

            for share in outgoing:
                knowledge = share.get("knowledge", {})
                for target in share.get("targets", []):
                    try:
                        header = MessageHeader(
                            message_id=str(uuid4()),
                            source_agent_id=self.agent_id,
                            target_agent_id=target,
                            priority=MessagePriority.NORMAL,
                        )
                        msg = BaseMessage(
                            header=header,
                            message_type=MessageType.INFO,
                            payload=f"[Knowledge Share] {knowledge.get('content', '')}",
                            metadata={
                                "msg_type": "knowledge",
                                "category": knowledge.get("category", "general"),
                                "tags": [knowledge.get("category", "general"), "knowledge_share"],
                                "persist": True,
                                "read": False,
                            },
                        )
                        await bus.send(msg)
                        self._logger.debug(f"[{self.agent_id}] Shared knowledge to {target}")
                    except Exception as e:
                        self._logger.error(f"[{self.agent_id}] Knowledge share to {target} failed: {e}")

        pending_shares = getattr(self, "_pending_knowledge_shares", None)
        if pending_shares:
            bus = getattr(self, "_external_bus", None) or getattr(self, "_message_bus", None)
            if bus:
                from uuid import uuid4

                for share in pending_shares:
                    target = share.get("target")
                    content = share.get("content", "")
                    category = share.get("category", "general")
                    importance = share.get("importance", "normal")
                    try:
                        priority = {
                            "low": MessagePriority.LOW,
                            "normal": MessagePriority.NORMAL,
                            "high": MessagePriority.HIGH,
                        }.get(importance, MessagePriority.NORMAL)
                        header = MessageHeader(
                            message_id=str(uuid4()),
                            source_agent_id=self.agent_id,
                            target_agent_id=target,
                            priority=priority,
                        )
                        msg = BaseMessage(
                            header=header,
                            message_type=MessageType.INFO,
                            payload=f"[{category.upper()}] {content}",
                            metadata={
                                "msg_type": "knowledge",
                                "category": category,
                                "tags": [category, "knowledge_share"],
                                "persist": True,
                                "read": False,
                            },
                        )
                        await bus.send(msg)
                        self._logger.debug(f"[{self.agent_id}] Shared knowledge to {target}")
                    except Exception as e:
                        self._logger.error(f"[{self.agent_id}] Knowledge share to {target} failed: {e}")
            self._pending_knowledge_shares = []

        pending_learning = getattr(self, "_pending_learning_submissions", None)
        if pending_learning:
            bus = getattr(self, "_external_bus", None) or getattr(self, "_message_bus", None)
            if bus:
                from uuid import uuid4

                for submission in pending_learning:
                    try:
                        importance = submission.get("importance", "normal")
                        priority = {
                            "low": MessagePriority.LOW,
                            "normal": MessagePriority.NORMAL,
                            "high": MessagePriority.HIGH,
                        }.get(importance, MessagePriority.NORMAL)

                        title = str(submission.get("title", "")).strip()
                        summary = str(submission.get("summary", "")).strip()
                        content = str(submission.get("content", "")).strip()
                        storage_hint = str(submission.get("storage_hint", "auto")).strip() or "auto"
                        tags = [str(tag).strip() for tag in (submission.get("tags") or []) if str(tag).strip()]

                        payload = (
                            "[LEARNING_SUBMISSION]\n"
                            f"title: {title}\n"
                            f"storage_hint: {storage_hint}\n"
                            f"summary: {summary}\n"
                            f"tags: {', '.join(tags)}\n\n"
                            f"{content}"
                        )

                        header = MessageHeader(
                            message_id=str(uuid4()),
                            source_agent_id=self.agent_id,
                            target_agent_id="knowledge",
                            priority=priority,
                        )
                        msg = BaseMessage(
                            header=header,
                            message_type=MessageType.INFO,
                            payload=payload,
                            metadata={
                                "msg_type": "learning_submission",
                                "storage_hint": storage_hint,
                                "title": title,
                                "summary": summary,
                                "tags": tags + ["learning_submission"],
                                "persist": True,
                                "read": False,
                            },
                        )
                        await bus.send(msg)
                        self._logger.debug(f"[{self.agent_id}] Submitted learning candidate to knowledge: {title}")
                    except Exception as e:
                        self._logger.error(f"[{self.agent_id}] Learning submission failed: {e}")
            self._pending_learning_submissions = []

    def _build_interrupt_prompt(self) -> Optional[str]:
        """Build a prompt from queued interrupt messages."""
        if not self._interrupt_messages:
            return None

        parts = ["## Incoming Messages (URGENT - Address Before Continuing)\n"]
        for msg in self._interrupt_messages:
            msg_type = msg.get("type", "info")
            from_agent = msg.get("from", "unknown")
            content = msg.get("content", "")
            priority = msg.get("priority", "normal")
            tags = msg.get("tags", [])
            if msg_type == "issue":
                parts.append(f"**BUG REPORT from {from_agent}** (priority: {priority})")
                parts.append(f"Issue: {content}")
                parts.append("ACTION: Fix this issue immediately, then continue your current task.\n")
            elif msg_type == "task_ready":
                parts.append(f"**TASK NOTIFICATION from {from_agent}** (priority: {priority})")
                parts.append(f"Message: {content}")
                if "task_ready" in tags:
                    parts.append("ACTION: Upstream work is complete. Start your implementation now.\n")
                else:
                    parts.append("\n")
            elif msg_type == "question":
                parts.append(f"**QUESTION from {from_agent}** (priority: {priority})")
                parts.append(f"Question: {content}")
                parts.append("ACTION: Answer this question using send_message(), then continue your task.\n")
            else:
                parts.append(f"**{msg_type.upper()} from {from_agent}** (priority: {priority})")
                parts.append(f"Content: {content}\n")

        parts.append("---\nProcess these messages, then continue with your current work.")
        return "\n".join(parts)

    def _build_inbox_status_snapshot(self, limit: int = 12) -> Dict[str, Any]:
        """Return a structured snapshot of unread mailbox state for this step."""
        inbox = list(getattr(self, "_subscription_inbox", []) or [])
        unread = [msg for msg in inbox if not msg.get("read", False)]
        by_type: Dict[str, int] = {}
        for msg in unread:
            msg_type = str(msg.get("type", "info") or "info").lower()
            by_type[msg_type] = by_type.get(msg_type, 0) + 1
        # 2026-06-02 v3 re-pilot fix (4th truncation site discovered):
        # the prior 280-char preview slice convinced agents the inbox
        # was truncated even when check_inbox returned full content.
        # Per user 2026-06-01/02 directive ("不要截断"), the preview
        # carries the full content. Agents that want a summary view
        # can still read this; the call to check_inbox is no longer
        # the only way to get full content.
        preview = [
            {
                "id": msg.get("id"),
                "from": msg.get("from", "unknown"),
                "type": msg.get("type", "info"),
                "priority": msg.get("priority", "normal"),
                "content": str(msg.get("content", "")),
            }
            for msg in unread[:limit]
        ]
        return {
            "total": len(inbox),
            "unread": len(unread),
            "by_type": by_type,
            "preview": preview,
        }

    def _build_inbox_status_prompt(self, snapshot: Dict[str, Any]) -> Optional[str]:
        """Format a prompt-visible mailbox summary."""
        unread = int(snapshot.get("unread", 0))
        preview = snapshot.get("preview", []) or []
        if unread <= 0 and not preview:
            return None
        parts = ["## Inbox Status", f"Unread messages: {unread}"]
        by_type = snapshot.get("by_type", {}) or {}
        if by_type:
            typed = ", ".join(f"{key}={value}" for key, value in sorted(by_type.items()))
            parts.append(f"By type: {typed}")
        if preview:
            parts.append("Recent unread messages:")
            for item in preview:
                parts.append(
                    f"- [{item.get('type')}/{item.get('priority')}] from {item.get('from')}: {item.get('content')}"
                )
        return "\n".join(parts)

    def _build_runtime_team_status_snapshot(
        self,
        runtime_limit: int = 8,
        team_limit: int = 6,
    ) -> Dict[str, Any]:
        """Return a structured snapshot of runtimes and managed teams owned by this agent."""
        manager = getattr(self, "_agent_manager", None)
        owner_id = getattr(self, "agent_id", None) or getattr(self, "_agent_id", None)
        if not manager or not owner_id:
            return {}

        runtime_records = []
        try:
            runtime_records = manager.list_runtime_agents(include_terminated=True)
        except Exception:
            runtime_records = []

        owned_runtimes = [
            record
            for record in runtime_records
            if record.get("parent_id") == owner_id
            and record.get("runtime_kind") == "ephemeral"
        ]
        owned_runtimes.sort(
            key=lambda item: item.get("updated_at") or item.get("registered_at") or "",
            reverse=True,
        )
        runtime_lifecycle_counts: Dict[str, int] = {}
        runtime_status_counts: Dict[str, int] = {}
        for record in owned_runtimes:
            lifecycle = str(record.get("lifecycle", "unknown") or "unknown")
            runtime_lifecycle_counts[lifecycle] = runtime_lifecycle_counts.get(lifecycle, 0) + 1
            status = str(record.get("status", "unknown") or "unknown")
            runtime_status_counts[status] = runtime_status_counts.get(status, 0) + 1
        runtime_preview = [
            {
                "agent_id": record.get("agent_id"),
                "requested_type": record.get("requested_type"),
                "config_profile": record.get("config_profile"),
                "role": record.get("role"),
                "lifecycle": record.get("lifecycle"),
                "status": record.get("status"),
                "team_id": record.get("team_id"),
                "team_member_id": record.get("team_member_id"),
            }
            for record in owned_runtimes[:runtime_limit]
        ]
        owned_runtime_ids = {
            str(record.get("agent_id"))
            for record in owned_runtimes
            if str(record.get("agent_id", "")).strip()
        }

        teams = []
        try:
            teams = manager.list_agent_teams()
        except Exception:
            teams = []
        owned_teams = [team for team in teams if team.get("parent_id") == owner_id]
        owned_teams.sort(
            key=lambda item: item.get("launched_at") or item.get("created_at") or "",
            reverse=True,
        )
        team_status_counts: Dict[str, int] = {}
        team_preview: List[Dict[str, Any]] = []
        for team in owned_teams:
            status = str(team.get("status", "unknown") or "unknown")
            team_status_counts[status] = team_status_counts.get(status, 0) + 1
        for team in owned_teams[:team_limit]:
            team_id = str(team.get("team_id", "") or "").strip()
            detailed = team
            if team_id:
                try:
                    detailed = manager.get_agent_team_status(team_id=team_id)
                except Exception:
                    detailed = team
            member_states = detailed.get("member_states", {}) or {}
            member_state_counts: Dict[str, int] = {}
            for state in member_states.values():
                key = str(state or "unknown")
                member_state_counts[key] = member_state_counts.get(key, 0) + 1
            team_preview.append(
                {
                    "team_id": detailed.get("team_id"),
                    "status": detailed.get("status"),
                    "launch_task_active": detailed.get("launch_task_active", False),
                    "active_members": detailed.get("active_members", 0),
                    "total_members": len(detailed.get("members", {}) or {}),
                    "member_state_counts": member_state_counts,
                }
            )
        owned_team_ids = {
            str(team.get("team_id"))
            for team in owned_teams
            if str(team.get("team_id", "")).strip()
        }

        inbox = list(getattr(self, "_subscription_inbox", []) or [])
        unread_background_runtime_updates: List[Dict[str, Any]] = []
        unread_background_team_updates: List[Dict[str, Any]] = []
        for msg in inbox:
            if msg.get("read", False):
                continue
            source_id = str(msg.get("from", "") or "").strip()
            msg_type = str(msg.get("type", "") or "").strip().lower()
            metadata = msg.get("metadata", {}) or {}
            if source_id in owned_runtime_ids and msg_type in {"result", "error"}:
                unread_background_runtime_updates.append(
                    {
                        "agent_id": source_id,
                        "type": msg_type,
                        "priority": msg.get("priority"),
                        "content": str(msg.get("content", "")),  # 2026-06-02: no truncation (see preview comment above)
                    }
                )
                continue
            if (
                source_id == "dynamic_agent_manager"
                and str(metadata.get("msg_type", "") or "").strip().lower() == "team_update"
            ):
                team_id = str(metadata.get("team_id", "") or "").strip()
                if team_id and team_id in owned_team_ids:
                    unread_background_team_updates.append(
                        {
                            "team_id": team_id,
                            "event": metadata.get("event"),
                            "team_status": metadata.get("team_status"),
                            "priority": msg.get("priority"),
                            "content": str(msg.get("content", "")),  # 2026-06-02: no truncation (see preview comment above)
                        }
                    )

        if not owned_runtimes and not owned_teams:
            return {}
        return {
            "owner_agent_id": owner_id,
            "spawned_runtime_count": len(owned_runtimes),
            "active_spawned_runtime_count": runtime_status_counts.get("active", 0),
            "spawned_runtime_lifecycle_counts": runtime_lifecycle_counts,
            "spawned_runtime_status_counts": runtime_status_counts,
            "spawned_runtime_preview": runtime_preview,
            "unread_background_runtime_update_count": len(unread_background_runtime_updates),
            "unread_background_runtime_updates": unread_background_runtime_updates[:runtime_limit],
            "managed_team_count": len(owned_teams),
            "managed_team_status_counts": team_status_counts,
            "managed_team_preview": team_preview,
            "unread_background_team_update_count": len(unread_background_team_updates),
            "unread_background_team_updates": unread_background_team_updates[:team_limit],
        }

    def _build_runtime_team_status_prompt(self, snapshot: Dict[str, Any]) -> Optional[str]:
        """Format a prompt-visible summary of spawned runtimes and managed teams."""
        if not snapshot:
            return None

        runtime_count = int(snapshot.get("spawned_runtime_count", 0))
        team_count = int(snapshot.get("managed_team_count", 0))
        if runtime_count <= 0 and team_count <= 0:
            return None

        parts = ["## Runtime / Team Status"]
        unread_runtime_updates = snapshot.get("unread_background_runtime_updates", []) or []
        unread_team_updates = snapshot.get("unread_background_team_updates", []) or []
        if unread_runtime_updates or unread_team_updates:
            parts.append(
                "Pending background completions not yet consumed: "
                f"worker_updates={len(unread_runtime_updates)}, team_updates={len(unread_team_updates)}"
            )
            if unread_runtime_updates:
                parts.append("Unread worker completion messages:")
                for item in unread_runtime_updates:
                    parts.append(
                        f"- {item.get('agent_id')}: type={item.get('type')}, "
                        f"priority={item.get('priority')}, content={item.get('content')}"
                    )
            if unread_team_updates:
                parts.append("Unread team completion messages:")
                for item in unread_team_updates:
                    parts.append(
                        f"- {item.get('team_id')}: status={item.get('team_status')}, "
                        f"event={item.get('event')}, priority={item.get('priority')}, "
                        f"content={item.get('content')}"
                    )

        if runtime_count > 0:
            parts.append(
                "Spawned runtimes you own: "
                f"{snapshot.get('active_spawned_runtime_count', 0)} active / {runtime_count} total"
            )
            lifecycle_counts = snapshot.get("spawned_runtime_lifecycle_counts", {}) or {}
            if lifecycle_counts:
                lifecycle_text = ", ".join(
                    f"{key}={value}" for key, value in sorted(lifecycle_counts.items())
                )
                parts.append(f"Runtime lifecycle: {lifecycle_text}")
            preview = snapshot.get("spawned_runtime_preview", []) or []
            if preview:
                parts.append("Recent spawned runtimes:")
                for item in preview:
                    label = item.get("requested_type") or "worker"
                    config = item.get("config_profile") or "default"
                    parts.append(
                        f"- {item.get('agent_id')}: type={label}, profile={config}, "
                        f"lifecycle={item.get('lifecycle')}, status={item.get('status')}, "
                        f"team={item.get('team_id') or 'none'}"
                    )
        else:
            parts.append("Spawned runtimes you own: none")

        if team_count > 0:
            parts.append(f"Managed teams you own: {team_count}")
            team_counts = snapshot.get("managed_team_status_counts", {}) or {}
            if team_counts:
                team_text = ", ".join(f"{key}={value}" for key, value in sorted(team_counts.items()))
                parts.append(f"Team status: {team_text}")
            preview = snapshot.get("managed_team_preview", []) or []
            if preview:
                parts.append("Current managed teams:")
                for item in preview:
                    member_counts = item.get("member_state_counts", {}) or {}
                    member_text = ", ".join(
                        f"{key}={value}" for key, value in sorted(member_counts.items())
                    ) or "none"
                    parts.append(
                        f"- {item.get('team_id')}: status={item.get('status')}, "
                        f"active_members={item.get('active_members')}/{item.get('total_members')}, "
                        f"launch_task_active={item.get('launch_task_active')}, member_states={member_text}"
                    )
        else:
            parts.append("Managed teams you own: none")

        parts.append(
            "Use this snapshot before deciding whether to spawn new agents, reuse existing ones, "
            "or monitor/pause/resume/terminate a managed team."
        )
        return "\n".join(parts)

    def _summarize_plan_gaps(self, plan_indexes: Dict[str, Any]) -> List[Dict[str, Any]]:
        gaps: List[Dict[str, Any]] = []
        for agent_id, plan in (plan_indexes or {}).items():
            if not isinstance(plan, dict) or not plan.get("has_plan"):
                continue
            stages = plan.get("stages", {}) or {}
            pending = 0
            blocked = 0
            in_progress = 0
            for stage in stages.values():
                if not isinstance(stage, dict):
                    continue
                for task in (stage.get("tasks", {}) or {}).values():
                    if not isinstance(task, dict):
                        continue
                    status = str(task.get("status") or "pending")
                    pending += status == "pending"
                    blocked += status == "blocked"
                    in_progress += status == "in_progress"
            acceptance = plan.get("acceptance_summary", {}) or {}
            unresolved = int(acceptance.get("unresolved", 0) or 0)
            if pending or blocked or in_progress or unresolved:
                gaps.append(
                    {
                        "agent": agent_id,
                        "current_stage": plan.get("current_stage_id"),
                        "pending": pending,
                        "in_progress": in_progress,
                        "blocked": blocked,
                        "unresolved_acceptance": unresolved,
                    }
                )
        return gaps[:10]

    async def _collect_eventhub_catchup_summary(self) -> List[Dict[str, Any]]:
        """Return unread EventHub inbox items for this agent (catch-up on first step).

        Reads the EventHub inbox for the current agent and returns all unread
        events, newest-first.  This is intended to be called once per agent
        lifecycle, gated by ``_first_step_catchup_done``.
        """
        try:
            # Use _hubs (HubRegistry) for inbox catchup
            _hubs = getattr(self, "_hubs", None)
            eventhub = getattr(_hubs, "eventhub", None)
            if eventhub is None:
                return []
            agent_id = getattr(self, "agent_id", None) or getattr(self, "_agent_id", None)
            if not agent_id:
                return []
            return eventhub.list_inbox(agent_id, unread_only=True)
        except Exception:
            return []

    def _build_eventhub_catchup_prompt(self, events: List[Dict[str, Any]]) -> Optional[str]:
        """Format a prompt-visible EventHub catch-up summary."""
        if not events:
            return None
        parts = [
            "## EventHub Catch-up",
            f"You have {len(events)} unread event(s) that arrived while you were offline:",
        ]
        for evt in events[:12]:
            payload_preview = str(evt.get("payload") or {})[:120]
            parts.append(
                f"- [{evt.get('event_type')} from {evt.get('source_hub')} priority={evt.get('priority')}]"
                f" id={evt.get('id')} {payload_preview}"
            )
        if len(events) > 12:
            parts.append(f"  ... and {len(events) - 12} more. Use eventhub_list_inbox to see all.")
        parts.append(
            "Review these events and act on any that are relevant to your current task."
        )
        return "\n".join(parts)

