"""
Observer handler registry for configurable observer agents.

Keep observer-specific behavior out of ConfigurableAgent so new observer roles can
be added via config + module registration rather than agent-specific conditionals.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


class BaseObserverHandler:
    """Base observer handler interface."""

    def __init__(self, interval_seconds: float = 5.0):
        self.interval_seconds = float(interval_seconds)

    async def on_tick(self, agent: Any) -> None:
        raise NotImplementedError


class KnowledgeObserverHandler(BaseObserverHandler):
    """Knowledge curation observer: extract knowledge and promote reusable skills."""

    def __init__(self, interval_seconds: float = 30.0):
        super().__init__(interval_seconds=interval_seconds)
        self._knowledge_seen_signatures: List[str] = []
        self._knowledge_seen_set = set()
        self._skill_candidate_counts: Dict[str, int] = {}
        self._skill_seen_signatures: List[str] = []
        self._skill_seen_set = set()

    async def on_tick(self, agent: Any) -> None:
        check_inbox_tool = agent._tool_instances.get("check_inbox")
        query_tool = agent._tool_instances.get("query_knowledge")
        store_tool = agent._tool_instances.get("store_knowledge")
        get_skill_tool = agent._tool_instances.get("get_skill")
        upsert_skill_tool = agent._tool_instances.get("upsert_skill")
        if not check_inbox_tool or not query_tool or not store_tool:
            return

        inbox_result = check_inbox_tool.execute(limit=20, clear=True)
        if not getattr(inbox_result, "success", False):
            return

        messages = (inbox_result.data or {}).get("messages", []) or []
        if messages:
            agent._logger.debug(f"[{agent.agent_id}] Observer tick: {len(messages)} messages in inbox")

        stored_count = 0
        for msg in messages:
            if stored_count >= 3:
                break

            content = str(msg.get("content", "") or "").strip()
            if len(content) < 50:
                continue

            signature = str(msg.get("id") or hashlib.sha256(content.encode("utf-8")).hexdigest())
            if signature in self._knowledge_seen_set:
                continue
            self._remember_knowledge_signature(signature)

            msg_type = str(msg.get("type", "") or "").lower()
            text_lower = content.lower()
            metadata = msg.get("metadata", {}) if isinstance(msg, dict) else {}

            handled_learning_submission = await self._ingest_learning_submission(
                agent=agent,
                from_agent=str(msg.get("from", "unknown") or "unknown"),
                msg_type=msg_type,
                content=content,
                metadata=metadata if isinstance(metadata, dict) else {},
                query_tool=query_tool,
                store_tool=store_tool,
                get_skill_tool=get_skill_tool,
                upsert_skill_tool=upsert_skill_tool,
                signature=signature,
            )
            if handled_learning_submission:
                continue

            if msg_type not in {"issue", "warning", "complete", "update", "error"} and not any(
                k in text_lower for k in ("failed", "error", "fix", "resolved", "blocked", "solution")
            ):
                continue

            title = content.splitlines()[0][:120] or "Agent activity insight"
            query_result = await query_tool.execute(query=title, limit=1)
            found = bool((getattr(query_result, "data", {}) or {}).get("found"))
            if found:
                continue

            category = "issue_solution" if any(k in text_lower for k in ("error", "failed", "fix", "resolved")) else "best_practice"
            severity = "high" if msg_type in {"error", "issue"} else "medium"
            from_agent = str(msg.get("from", "unknown") or "unknown")
            tags = ["observer", from_agent, msg_type or "message"]
            await store_tool.execute(
                title=f"{from_agent}: {title}",
                category=category,
                problem=f"Observed message from {from_agent} ({msg_type or 'message'})",
                solution=content[:1800],
                tags=tags,
                severity=severity,
            )
            stored_count += 1
            agent._logger.info(
                f"[{agent.agent_id}] Stored knowledge: {category} from {from_agent} ({msg_type})"
            )

            if get_skill_tool and upsert_skill_tool:
                candidate = self._extract_skill_candidate(
                    from_agent=from_agent,
                    msg_type=msg_type,
                    content=content,
                    tags=msg.get("tags", []) or [],
                    signature=signature,
                )
                if candidate:
                    await self._maybe_promote_skill_candidate(
                        agent=agent,
                        candidate=candidate,
                        get_skill_tool=get_skill_tool,
                        upsert_skill_tool=upsert_skill_tool,
                    )

    def _remember_knowledge_signature(self, signature: str) -> None:
        self._knowledge_seen_set.add(signature)
        self._knowledge_seen_signatures.append(signature)
        if len(self._knowledge_seen_signatures) > 2000:
            old = self._knowledge_seen_signatures.pop(0)
            self._knowledge_seen_set.discard(old)

    def _remember_skill_signature(self, signature: str) -> None:
        self._skill_seen_set.add(signature)
        self._skill_seen_signatures.append(signature)
        if len(self._skill_seen_signatures) > 2000:
            old = self._skill_seen_signatures.pop(0)
            self._skill_seen_set.discard(old)

    @staticmethod
    def _slugify_skill_name(text: str, fallback: str = "workflow-playbook") -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        normalized = re.sub(r"-{2,}", "-", normalized)
        if not normalized:
            return fallback
        words = [part for part in normalized.split("-") if part]
        return "-".join(words[:6]) or fallback

    def _extract_skill_candidate(
        self,
        *,
        from_agent: str,
        msg_type: str,
        content: str,
        tags: List[str],
        signature: str,
    ) -> Optional[Dict[str, Any]]:
        if signature in self._skill_seen_set:
            return None

        text = (content or "").strip()
        if len(text) < 140:
            return None

        lower = text.lower()
        explicit_markers = (
            "playbook",
            "runbook",
            "checklist",
            "procedure",
            "workflow",
            "next time",
            "always do this",
        )
        weak_markers = (
            "step 1",
            "steps:",
            "1.",
            "2.",
            "remember to",
            "before you",
        )
        explicit = any(marker in lower for marker in explicit_markers) or any(
            "skill" in str(tag).lower() for tag in (tags or [])
        )
        recurring_hint = explicit or any(marker in lower for marker in weak_markers)
        if not recurring_hint:
            return None

        title_line = text.splitlines()[0].strip(" -:#")[:120] or "Workflow Playbook"
        base_name = self._slugify_skill_name(f"{from_agent} {title_line}")
        name = base_name if any(k in base_name for k in ("playbook", "checklist", "workflow", "runbook")) else f"{base_name}-playbook"
        summary = title_line[:140]
        instructions = (
            f"# {title_line}\n\n"
            f"Source agent: `{from_agent}`\n\n"
            f"Use this procedure when handling similar `{msg_type or 'workflow'}` situations.\n\n"
            f"{text[:2400]}"
        ).strip()
        return {
            "name": name,
            "summary": summary,
            "instructions": instructions,
            "explicit": explicit,
            "signature": signature,
        }

    async def _maybe_promote_skill_candidate(
        self,
        *,
        agent: Any,
        candidate: Dict[str, Any],
        get_skill_tool: Any,
        upsert_skill_tool: Any,
    ) -> None:
        skill_name = str(candidate.get("name") or "").strip()
        if not skill_name:
            return

        seen_count = self._skill_candidate_counts.get(skill_name, 0) + 1
        self._skill_candidate_counts[skill_name] = seen_count

        should_write = bool(candidate.get("explicit")) or seen_count >= 2
        if not should_write:
            return

        existing = await get_skill_tool.execute(name=skill_name)
        found_existing = bool((getattr(existing, "data", {}) or {}).get("found"))
        await upsert_skill_tool.execute(
            name=skill_name,
            summary=candidate["summary"],
            instructions=candidate["instructions"],
            scope="project-agent",
            append=found_existing,
        )
        self._remember_skill_signature(candidate["signature"])
        agent._logger.info(
            "[%s] Auto-promoted skill: %s (existing=%s, count=%s)",
            agent.agent_id,
            skill_name,
            found_existing,
            seen_count,
        )

    @staticmethod
    def _parse_learning_submission(
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        raw = str(content or "").strip()
        result = {
            "title": str(metadata.get("title", "")).strip(),
            "summary": str(metadata.get("summary", "")).strip(),
            "storage_hint": str(metadata.get("storage_hint", "auto")).strip() or "auto",
            "tags": [str(tag).strip() for tag in (metadata.get("tags") or []) if str(tag).strip()],
            "content": raw,
        }
        if not raw.startswith("[LEARNING_SUBMISSION]"):
            return result

        body = raw[len("[LEARNING_SUBMISSION]"):].lstrip()
        header_lines: List[str] = []
        content_lines: List[str] = []
        in_body = False
        for line in body.splitlines():
            if not in_body and ":" in line:
                header_lines.append(line)
                continue
            if not in_body and not line.strip():
                in_body = True
                continue
            in_body = True
            content_lines.append(line)

        parsed_headers: Dict[str, str] = {}
        for line in header_lines:
            key, value = line.split(":", 1)
            parsed_headers[key.strip().lower()] = value.strip()

        if parsed_headers.get("title"):
            result["title"] = parsed_headers["title"]
        if parsed_headers.get("summary"):
            result["summary"] = parsed_headers["summary"]
        if parsed_headers.get("storage_hint"):
            result["storage_hint"] = parsed_headers["storage_hint"]
        if parsed_headers.get("tags"):
            extra_tags = [part.strip() for part in parsed_headers["tags"].split(",") if part.strip()]
            result["tags"] = list(dict.fromkeys(result["tags"] + extra_tags))
        parsed_content = "\n".join(content_lines).strip()
        if parsed_content:
            result["content"] = parsed_content
        return result

    async def _ingest_learning_submission(
        self,
        *,
        agent: Any,
        from_agent: str,
        msg_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]],
        query_tool: Any,
        store_tool: Any,
        get_skill_tool: Any,
        upsert_skill_tool: Any,
        signature: str,
    ) -> bool:
        metadata = metadata or {}
        tags = [str(tag).strip() for tag in (metadata.get("tags") or []) if str(tag).strip()]
        if msg_type != "learning_submission" and "learning_submission" not in tags:
            return False

        submission = self._parse_learning_submission(content, metadata)
        title = submission["title"] or f"{from_agent} learning submission"
        summary = submission["summary"] or title
        body = submission["content"] or ""
        storage_hint = str(submission["storage_hint"] or "auto").lower()
        submission_tags = list(dict.fromkeys((submission.get("tags") or []) + [from_agent, "learning_submission"]))

        if storage_hint == "knowledge":
            query_result = await query_tool.execute(query=title, limit=1)
            found = bool((getattr(query_result, "data", {}) or {}).get("found"))
            if not found:
                await store_tool.execute(
                    title=f"{from_agent}: {title}",
                    category="best_practice",
                    problem=f"Learning submission from {from_agent}",
                    solution=body[:1800],
                    tags=submission_tags,
                    severity="medium",
                )
            self._remember_skill_signature(signature)
            return True

        if storage_hint == "skill" and get_skill_tool and upsert_skill_tool:
            skill_name = self._slugify_skill_name(title, fallback=f"{from_agent}-playbook")
            existing = await get_skill_tool.execute(name=skill_name)
            found_existing = bool((getattr(existing, "data", {}) or {}).get("found"))
            await upsert_skill_tool.execute(
                name=skill_name,
                summary=summary,
                instructions=body or summary,
                scope="project-agent",
                append=found_existing,
            )
            self._remember_skill_signature(signature)
            return True

        if get_skill_tool and upsert_skill_tool:
            candidate = self._extract_skill_candidate(
                from_agent=from_agent,
                msg_type=msg_type,
                content=body or content,
                tags=submission_tags,
                signature=signature,
            )
            if candidate:
                candidate["summary"] = summary or candidate["summary"]
                await self._maybe_promote_skill_candidate(
                    agent=agent,
                    candidate=candidate,
                    get_skill_tool=get_skill_tool,
                    upsert_skill_tool=upsert_skill_tool,
                )
                return True

        query_result = await query_tool.execute(query=title, limit=1)
        found = bool((getattr(query_result, "data", {}) or {}).get("found"))
        if not found:
            await store_tool.execute(
                title=f"{from_agent}: {title}",
                category="best_practice",
                problem=f"Learning submission from {from_agent}",
                solution=(body or content)[:1800],
                tags=submission_tags,
                severity="medium",
            )
        self._remember_skill_signature(signature)
        return True


def create_observer_handler(name: Optional[str], *, flags: Optional[Dict[str, Any]] = None) -> Optional[BaseObserverHandler]:
    """Resolve an observer handler from config."""
    normalized = str(name or "").strip().lower()
    flags = flags or {}
    interval = float(flags.get("observer_tick_interval_s", 5))
    if normalized in {"", "none"}:
        return None
    if normalized == "knowledge_curator":
        return KnowledgeObserverHandler(interval_seconds=interval or 30.0)
    raise ValueError(f"Unknown observer handler: {name}")
