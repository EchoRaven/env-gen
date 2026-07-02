#!/usr/bin/env python3
"""Local monitor server for live generation progress."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import secrets
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import yaml


APP_DIR = Path(__file__).resolve().parent / "live_monitor"
AGENT_LOG_ROOT = Path(__file__).resolve().parents[2] / ".agent_logs"
AGENT_LINE_RE = re.compile(
    r"(?P<time>\d{2}:\d{2}:\d{2}) \[[A-Z]\] Agent\.(?P<agent>.+?)(?: Agent)?: \[(?P<lane>[^\]]+)\](?: \[(?P<stage>[^\]]+)\])? (?P<message>.*)"
)
PATH_RE = re.compile(r"(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)")
PLAN_LINE_RE = re.compile(r"📋 PLAN (?P<action>[A-Za-z_]+): (?P<payload>.*)")
CORE_AGENT_IDS = (
    "orchestrator",
    "design",
    "database",
    "backend",
    "frontend",
    "verifier",
    "knowledge",
)
AGENT_LOG_DIRS = {
    "orchestrator": "Orchestrator Agent",
    "design": "Design Agent",
    "database": "Database Agent",
    "backend": "Backend Lead Agent",
    "frontend": "Frontend Lead Agent",
    "verifier": "Verifier Agent",
    "knowledge": "Knowledge Agent",
}


def _classify_action(message: str) -> str:
    text = message.lower()
    if "🧠 think" in text or "next moves:" in text:
        return "think"
    if "📥 check_inbox" in text or "inbox" in text:
        return "inbox"
    if "📝 write:" in text or "write(" in text:
        return "write"
    if "👁️ read:" in text or "read(" in text:
        return "read"
    if "🔍 lint:" in text or "lint(" in text:
        return "lint"
    if "📤 send_message" in text or "📢 broadcast" in text:
        return "message"
    if "📋 plan" in text or "plan(" in text:
        return "plan"
    if "❌" in text or "failed" in text:
        return "error"
    return "activity"


def _extract_objects(message: str) -> List[dict]:
    seen = set()
    objects: List[dict] = []
    for match in PATH_RE.finditer(message):
        path = match.group("path")
        if path in seen:
            continue
        seen.add(path)
        kind = "file"
        if path.endswith(".json"):
            kind = "spec"
        elif "/" not in path:
            kind = "target"
        objects.append({"kind": kind, "label": path})
    target_match = re.search(r"to=([A-Za-z0-9_-]+)", message)
    if target_match:
        label = target_match.group(1)
        key = f"target:{label}"
        if key not in seen:
            objects.append({"kind": "agent", "label": label})
    return objects[:4]


def _preview_file(path: Path, max_lines: int = 18, max_chars: int = 1800) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    lines = content.splitlines()[:max_lines]
    preview = "\n".join(lines)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "\n..."
    return preview


def _preview_project_file(path: Path) -> Optional[str]:
    """Read generated files fully for the code/spec/database viewer."""
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_literal_eval(value: object) -> object:
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return value
    try:
        return ast.literal_eval(raw)
    except Exception:
        return value


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _parse_read_result_repr(raw: object) -> Optional[dict]:
    """Best-effort parser for legacy Python-dict read results with raw newlines."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if "'file_path'" not in text or "'content'" not in text:
        return None

    def string_field(name: str) -> str:
        match = re.search(rf"['\"]{name}['\"]\s*:\s*['\"](?P<value>.*?)['\"]\s*,", text, re.DOTALL)
        return match.group("value") if match else ""

    def int_field(name: str) -> Optional[int]:
        match = re.search(rf"['\"]{name}['\"]\s*:\s*(?P<value>\d+)", text)
        return int(match.group("value")) if match else None

    content = ""
    content_match = re.search(r"['\"]content['\"]\s*:\s*['\"](?P<value>.*)['\"]\s*\}?\s*$", text, re.DOTALL)
    if content_match:
        content = content_match.group("value")
    content = content.replace("\\n", "\n").replace("\\t", "\t")

    return {
        "file_path": string_field("file_path"),
        "total_lines": int_field("total_lines"),
        "offset": int_field("offset"),
        "limit": int_field("limit"),
        "content": content,
    }


def _normalize_tool_result(tool_name: str, result_raw: object) -> object:
    parsed = _safe_literal_eval(result_raw)
    if isinstance(parsed, str):
        parsed_read = _parse_read_result_repr(parsed)
        if parsed_read:
            return parsed_read
    if isinstance(parsed, dict):
        return parsed
    parsed_read = _parse_read_result_repr(result_raw)
    if parsed_read:
        return parsed_read
    return parsed


def _tool_result_kind(tool_name: str, result_value: object) -> str:
    name = str(tool_name or "").lower()
    if isinstance(result_value, dict) and "file_path" in result_value and "content" in result_value:
        return "file_read"
    if isinstance(result_value, dict) and ("success" in result_value or "error" in result_value):
        return "operation"
    if "plan" in name:
        return "plan"
    if isinstance(result_value, (dict, list)):
        return "structured"
    return "text"


def _parse_tool_call_content(content: str) -> dict:
    raw = str(content or "").strip()
    if not raw or "(" not in raw or not raw.endswith(")"):
        return {"toolName": raw, "args": None, "argsText": raw}
    tool_name, remainder = raw.split("(", 1)
    args_text = remainder[:-1].strip()
    return {
        "toolName": tool_name.strip(),
        "args": _safe_literal_eval(args_text),
        "argsText": args_text,
    }


def _parse_run_timestamp(log_path: Optional[Path]) -> Optional[datetime]:
    if not log_path:
        return None
    match = re.search(r"generation_(\d{8}_\d{6})", log_path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except Exception:
        return None


def _agent_log_root_for(workspace: Optional[Path]) -> Path:
    """Resolve where the per-agent jsonl logs live for a given workspace.

    Preferred: ``<workspace>/.agent_logs/`` — workspace-scoped, isolated
    per project (the new contract). Each project keeps its own action
    history; switching projects no longer surfaces stale tool calls.

    Fallback: ``AGENT_LOG_ROOT`` — the legacy host-wide path. Used when
    the workspace doesn't have its own ``.agent_logs/`` directory yet,
    so old runs (and tests pinned to the legacy path) still surface.
    """
    if workspace is not None:
        candidate = Path(workspace) / ".agent_logs"
        if candidate.exists():
            return candidate
    return AGENT_LOG_ROOT


def _closest_agent_log(
    agent_id: str,
    run_started_at: Optional[datetime],
    log_root: Optional[Path] = None,
) -> Optional[Path]:
    log_dir_name = AGENT_LOG_DIRS.get(agent_id)
    if not log_dir_name:
        return None
    root = log_root if log_root is not None else AGENT_LOG_ROOT
    folder = root / log_dir_name
    if not folder.exists():
        return None
    candidates = sorted(folder.glob("*.jsonl"))
    if not candidates:
        return None
    if run_started_at is None:
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def score(path: Path) -> float:
        try:
            ts = datetime.strptime(path.stem, "%Y%m%d_%H%M%S")
            return abs((ts - run_started_at).total_seconds())
        except Exception:
            return float("inf")

    return min(candidates, key=score)


def _core_owner_for_agent_id(agent_id: str) -> str:
    value = str(agent_id or "")
    for core_id in CORE_AGENT_IDS:
        if value == core_id or value.startswith(f"{core_id}_"):
            return core_id
    return value


def _candidate_agent_log_files(
    run_started_at: Optional[datetime],
    log_root: Optional[Path] = None,
) -> List[Path]:
    root = log_root if log_root is not None else AGENT_LOG_ROOT
    if not root.exists():
        return []
    candidates: List[Path] = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        log_files = sorted(folder.glob("*.jsonl"))
        if not log_files:
            continue
        if run_started_at is None:
            candidates.append(max(log_files, key=lambda p: p.stat().st_mtime))
            continue

        def score(path: Path) -> float:
            try:
                ts = datetime.strptime(path.stem, "%Y%m%d_%H%M%S")
                return abs((ts - run_started_at).total_seconds())
            except Exception:
                return float("inf")

        chosen = min(log_files, key=score)
        if score(chosen) <= 900:
            candidates.append(chosen)
    return candidates


def _dynamic_log_lane_map(log_path: Optional[Path]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not log_path or not log_path.exists():
        return mapping
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                match = AGENT_LINE_RE.search(line)
                if not match:
                    continue
                display_name = str(match.group("agent") or "").strip()
                lane = str(match.group("lane") or "").strip()
                if display_name and lane:
                    mapping[display_name] = lane
    except Exception:
        return mapping
    return mapping


def _dynamic_worker_owner_map(log_path: Optional[Path]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not log_path or not log_path.exists():
        return mapping
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "DynamicAgentManager:" not in line or "Spawned worker:" not in line:
                    continue
                match = re.search(
                    r"Spawned worker:\s+(?P<id>\S+)\s+\(requested_type=[^,\)]+,\s+config_profile=(?P<profile>[^,\)]+),",
                    line,
                )
                if match:
                    mapping[match.group("id")] = _core_owner_for_agent_id(match.group("profile"))
    except Exception:
        return mapping
    return mapping


def _agent_id_from_log_path(log_path: Path, fallback: str) -> str:
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for raw in f:
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                content = str(entry.get("content") or "")
                match = re.search(r"\*\*[^*]+\*\* \(`([^`]+)`\)", content)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return fallback


def _load_recent_tool_calls(log_path: Optional[Path], agent_id: str, limit: Optional[int] = None, owner_agent: Optional[str] = None) -> List[dict]:
    if not log_path or not log_path.exists():
        return []
    records: List[dict] = []
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                if entry.get("event_type") != "tool_call":
                    continue
                parsed = _parse_tool_call_content(str(entry.get("content", "")))
                _md = entry.get("metadata", {}) or {}
                result_raw = _md.get("result")
                result_value = _json_safe(_normalize_tool_result(parsed.get("toolName", ""), result_raw))
                records.append(
                    {
                        "id": f"{agent_id}-{entry.get('timestamp')}-{parsed.get('toolName')}",
                        "timestamp": entry.get("timestamp"),
                        "agent": agent_id,
                        "ownerAgent": owner_agent or _core_owner_for_agent_id(agent_id),
                        "toolName": parsed.get("toolName", ""),
                        "args": _json_safe(parsed.get("args")),
                        "argsText": parsed.get("argsText", ""),
                        "result": result_value,
                        # Authoritative tool-success flag persisted by base_agent.log_tool_call
                        # (None for logs that predate it → consumers fall back). Lets the
                        # monitor show true pass/fail instead of guessing from result shape.
                        "ok": _md.get("ok"),
                        "resultKind": _tool_result_kind(parsed.get("toolName", ""), result_value),
                        "resultText": result_raw if isinstance(result_raw, str) else json.dumps(result_raw, ensure_ascii=False, default=str),
                        "rawContent": entry.get("content", ""),
                    }
                )
    except Exception:
        return []
    # ``limit=None`` => return the full history. The agent-history UI
    # panel previously capped per-agent at 40 and the multi-agent
    # rollup at 140, which made it impossible to see what happened
    # earlier in a long run. Operator feedback: just show everything.
    if limit is None:
        return records
    return records[-limit:]


def _agent_tool_logs(
    log_path: Optional[Path],
    limit_per_agent: Optional[int] = None,
    log_root: Optional[Path] = None,
) -> Dict[str, List[dict]]:
    run_started_at = _parse_run_timestamp(log_path)
    dynamic_lane_by_display = _dynamic_log_lane_map(log_path)
    owner_by_dynamic_id = _dynamic_worker_owner_map(log_path)
    logs: Dict[str, List[dict]] = {}
    for agent_id in CORE_AGENT_IDS:
        agent_log = _closest_agent_log(agent_id, run_started_at, log_root=log_root)
        logs[agent_id] = _load_recent_tool_calls(agent_log, agent_id, limit=limit_per_agent)
    seen_paths = {
        str(path)
        for agent_id in CORE_AGENT_IDS
        for path in [_closest_agent_log(agent_id, run_started_at, log_root=log_root)]
        if path is not None
    }
    for candidate in _candidate_agent_log_files(run_started_at, log_root=log_root):
        if str(candidate) in seen_paths:
            continue
        dynamic_id = dynamic_lane_by_display.get(candidate.parent.name) or _agent_id_from_log_path(candidate, fallback=candidate.parent.name)
        owner = owner_by_dynamic_id.get(dynamic_id) or _core_owner_for_agent_id(dynamic_id)
        if owner not in logs or owner == dynamic_id:
            continue
        calls = _load_recent_tool_calls(candidate, dynamic_id, limit=limit_per_agent, owner_agent=owner)
        if calls:
            logs.setdefault(owner, []).extend(calls)
            logs[owner].sort(key=lambda item: str(item.get("timestamp", "")))
            if limit_per_agent is not None:
                logs[owner] = logs[owner][-limit_per_agent:]
    return logs


def _agent_plan_summary(tool_calls: List[dict]) -> dict:
    lines = []
    for call in tool_calls:
        if str(call.get("toolName", "")).lower() != "plan":
            continue
        args = call.get("args")
        if not isinstance(args, dict):
            continue
        action = str(args.get("action") or "status")
        lines.append(f"📋 PLAN {action}: {repr(args)}")
    return _extract_plan_summary(lines)


def _plan_history(agent_tool_logs: Dict[str, List[dict]], limit: int = 320) -> List[dict]:
    history: List[dict] = []
    for owner_agent, calls in agent_tool_logs.items():
        for index, call in enumerate(calls):
            if str(call.get("toolName", "")).lower() != "plan":
                continue
            args = call.get("args")
            if not isinstance(args, dict):
                continue
            action = str(args.get("action") or "status")
            plan = _extract_plan_summary([f"📋 PLAN {action}: {repr(args)}"])
            title = (
                args.get("plan_name")
                or args.get("name")
                or args.get("stage_name")
                or args.get("task_id")
                or f"{action.replace('_', ' ').title()} plan"
            )
            description = (
                args.get("plan_description")
                or args.get("description")
                or args.get("task_description")
                or args.get("result")
                or ""
            )
            history.append(
                {
                    "id": f"{owner_agent}-{call.get('timestamp')}-{index}",
                    "timestamp": call.get("timestamp"),
                    "agent": owner_agent,
                    "sourceAgent": call.get("agent") or owner_agent,
                    "action": action,
                    "title": str(title),
                    "description": str(description),
                    "stageId": args.get("stage_id"),
                    "taskId": args.get("task_id"),
                    "assignee": args.get("assignee"),
                    "plan": plan,
                    "args": _json_safe(args),
                }
            )
    history.sort(key=lambda item: str(item.get("timestamp", "")))
    return history[-limit:]


def _normalize_targets(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _inferred_inbox_from_sends(agent_id: str, all_tool_logs: Dict[str, List[dict]]) -> List[dict]:
    inferred: List[dict] = []
    for sender, calls in all_tool_logs.items():
        if sender == agent_id:
            continue
        for call in calls:
            tool = str(call.get("toolName", ""))
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            result = call.get("result") if isinstance(call.get("result"), dict) else {}
            timestamp = call.get("timestamp")
            if tool == "send_message":
                targets = _normalize_targets(args.get("to_agent") or args.get("target_agent") or result.get("to"))
                if agent_id not in targets:
                    continue
                inferred.append({
                    "id": result.get("message_id") or f"inferred-{sender}-{timestamp}",
                    "timestamp": timestamp,
                    "from": sender,
                    "type": args.get("msg_type"),
                    "priority": args.get("priority"),
                    "read": None,
                    "source": "inferred_sent",
                    "status": "sent" if result.get("sent", call.get("resultKind") != "error") else "failed",
                    "content": str(args.get("content", ""))[:900],
                })
            elif tool == "broadcast":
                inferred.append({
                    "id": f"inferred-broadcast-{sender}-{timestamp}",
                    "timestamp": timestamp,
                    "from": sender,
                    "type": args.get("msg_type", "broadcast"),
                    "priority": args.get("priority"),
                    "read": None,
                    "source": "inferred_broadcast",
                    "status": "sent" if result.get("sent", True) else "failed",
                    "content": str(args.get("message") or args.get("content") or "")[:900],
                })
    return inferred


def _agent_mailbox(agent_id: str, tool_calls: List[dict], all_tool_logs: Optional[Dict[str, List[dict]]] = None) -> dict:
    inbox: List[dict] = []
    sent: List[dict] = []
    broadcasts: List[dict] = []
    for call in tool_calls:
        tool = str(call.get("toolName", ""))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        result = call.get("result") if isinstance(call.get("result"), dict) else {}
        timestamp = call.get("timestamp")

        if tool == "check_inbox":
            messages = result.get("messages") if isinstance(result.get("messages"), list) else []
            for msg in messages:
                if isinstance(msg, dict):
                    inbox.append({
                        "id": msg.get("id"),
                        "timestamp": timestamp,
                        "from": msg.get("from"),
                        "type": msg.get("type"),
                        "priority": msg.get("priority"),
                        "read": msg.get("read", False),
                        "source": "check_inbox",
                        "content": str(msg.get("content", ""))[:900],
                    })
        elif tool == "send_message":
            target = args.get("to_agent") or args.get("target_agent") or result.get("to")
            sent.append({
                "id": result.get("message_id"),
                "timestamp": timestamp,
                "to": target,
                "type": args.get("msg_type"),
                "priority": args.get("priority"),
                "persist": args.get("persist"),
                "status": "sent" if result.get("sent", call.get("resultKind") != "error") else "failed",
                "content": str(args.get("content", ""))[:900],
            })
        elif tool == "broadcast":
            broadcasts.append({
                "timestamp": timestamp,
                "type": args.get("msg_type", "broadcast"),
                "status": "sent" if result.get("sent", True) else "failed",
                "content": str(args.get("message") or args.get("content") or "")[:900],
            })
    inferred_inbox = _inferred_inbox_from_sends(agent_id, all_tool_logs or {})
    seen_ids = {str(item.get("id")) for item in inbox if item.get("id")}
    for item in inferred_inbox:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen_ids:
            continue
        inbox.append(item)
        if item_id:
            seen_ids.add(item_id)
    inbox.sort(key=lambda item: str(item.get("timestamp", "")))
    return {
        "agent": agent_id,
        "inbox": inbox[-80:],
        "sent": sent[-80:],
        "broadcasts": broadcasts[-40:],
        "counts": {
            "inbox": len(inbox),
            "sent": len(sent),
            "broadcasts": len(broadcasts),
            "unread": sum(1 for item in inbox if not item.get("read")),
        },
    }


def _agent_runtime_summary(agent_id: str, tool_calls: List[dict], topology: dict) -> dict:
    spawn_calls = [
        call for call in tool_calls
        if str(call.get("toolName", "")) in {"spawn_worker", "spawn_agent", "parallel_execute", "create_agent_team", "define_team_agent", "launch_agent_team", "check_agent_team"}
    ]
    owned_workers: Dict[str, dict] = {}
    owned_teams: Dict[str, dict] = {}
    for call in spawn_calls:
        tool = str(call.get("toolName", ""))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        result = call.get("result") if isinstance(call.get("result"), dict) else {}

        if tool == "spawn_worker":
            runtime_id = result.get("agent_id") or result.get("runtime_id") or args.get("custom_name") or args.get("worker_type")
            if runtime_id:
                owned_workers[str(runtime_id)] = {
                    "id": str(runtime_id),
                    "name": str(runtime_id),
                    "label": str(runtime_id).replace("_", " ").replace("-", " ").title(),
                    "status": "completed" if result.get("completion") else "running",
                    "kind": "worker",
                    "requestedType": result.get("worker_type") or args.get("worker_type"),
                    "configProfile": result.get("config_profile") or args.get("config_profile"),
                    "resident": False,
                    "task": result.get("task") or args.get("task"),
                    "owner": agent_id,
                }
        elif tool == "parallel_execute":
            result_agents = result.get("agents") or result.get("results") or []
            if isinstance(result_agents, list):
                for index, item in enumerate(result_agents):
                    if isinstance(item, dict):
                        runtime_id = item.get("agent_id") or item.get("id") or item.get("name") or f"parallel_worker_{index + 1}"
                        owned_workers[str(runtime_id)] = {
                            "id": str(runtime_id),
                            "name": str(runtime_id),
                            "label": str(runtime_id).replace("_", " ").replace("-", " ").title(),
                            "status": item.get("status") or "completed",
                            "kind": "worker",
                            "requestedType": item.get("agent_type") or item.get("config_profile") or "parallel",
                            "configProfile": item.get("config_profile"),
                            "resident": False,
                            "task": item.get("task") or item.get("summary"),
                            "owner": agent_id,
                        }
        elif tool == "create_agent_team":
            team = result.get("team") if isinstance(result.get("team"), dict) else {}
            team_id = args.get("team_id") or team.get("team_id") or team.get("id")
            if team_id:
                owned_teams[str(team_id)] = {
                    "id": str(team_id),
                    "name": str(team_id),
                    "label": str(team_id).replace("_", " ").replace("-", " ").title(),
                    "status": "defined",
                    "kind": "team",
                    "description": args.get("description") or team.get("description"),
                    "owner": agent_id,
                }
        elif tool in {"define_team_agent", "launch_agent_team", "check_agent_team"}:
            team_id = args.get("team_id")
            if team_id:
                record = owned_teams.setdefault(str(team_id), {
                    "id": str(team_id),
                    "name": str(team_id),
                    "label": str(team_id).replace("_", " ").replace("-", " ").title(),
                    "status": "active" if tool == "launch_agent_team" else "defined",
                    "kind": "team",
                    "owner": agent_id,
                })
                if tool == "launch_agent_team":
                    record["status"] = "running"
                elif tool == "check_agent_team":
                    record["status"] = result.get("status") or record.get("status", "active")

    for runtime in topology.get("spawnedAgents", []):
        if runtime.get("owner") != agent_id:
            continue
        runtime_id = str(runtime.get("id") or "")
        if not runtime_id or runtime.get("resident"):
            continue
        record = owned_workers.setdefault(
            runtime_id,
            {
                "id": runtime_id,
                "name": runtime_id,
                "label": runtime_id.replace("_", " ").replace("-", " ").title(),
                "kind": "worker",
                "resident": False,
                "owner": agent_id,
            },
        )
        record.update({key: value for key, value in runtime.items() if value not in (None, "")})

    return {
        "agent": agent_id,
        "spawnedAgents": sorted(owned_workers.values(), key=lambda item: item["name"]),
        "agentTeams": sorted(owned_teams.values(), key=lambda item: item["name"]),
        "toolCalls": spawn_calls[-80:],
    }


def _crdt_document(project_dir: Path) -> dict:
    crdt_dir = project_dir / "shared" / "crdt"
    files: List[dict] = []
    if crdt_dir.exists():
        for path in sorted(crdt_dir.glob("*.json")):
            try:
                content = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                content = _preview_project_file(path)
            files.append({
                "name": path.name,
                "path": str(path.relative_to(project_dir)),
                "size": path.stat().st_size,
                "content": _json_safe(content),
            })
    return {
        "path": str(crdt_dir.relative_to(project_dir)) if crdt_dir.exists() else "shared/crdt",
        "files": files,
        "summary": {
            "files": len(files),
            "bytes": sum(item.get("size", 0) for item in files),
        },
    }


def _memory_bank_state(project_dir: Path) -> dict:
    root = project_dir / "memory-bank"
    file_names = [
        "project_brief.md",
        "tech_context.md",
        "system_patterns.md",
        "active_context.md",
        "progress.md",
    ]
    agents: Dict[str, dict] = {}
    if root.exists():
        for agent_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            files = []
            for name in file_names:
                path = agent_dir / name
                if not path.exists() or not path.is_file():
                    continue
                files.append({
                    "name": name,
                    "key": name.replace(".md", ""),
                    "path": str(path.relative_to(project_dir)),
                    "size": path.stat().st_size,
                    "content": _preview_project_file(path) or "",
                })
            agents[agent_dir.name] = {
                "agent": agent_dir.name,
                "path": str(agent_dir.relative_to(project_dir)),
                "files": files,
                "summary": {
                    "files": len(files),
                    "bytes": sum(item["size"] for item in files),
                },
            }

    # Compatibility for old shared memory-bank layout.
    if not agents and (root / "project_brief.md").exists():
        files = []
        for name in file_names:
            path = root / name
            if path.exists() and path.is_file():
                files.append({
                    "name": name,
                    "key": name.replace(".md", ""),
                    "path": str(path.relative_to(project_dir)),
                    "size": path.stat().st_size,
                    "content": _preview_project_file(path) or "",
                })
        agents["shared"] = {
            "agent": "shared",
            "path": "memory-bank",
            "files": files,
            "summary": {"files": len(files), "bytes": sum(item["size"] for item in files)},
        }

    return {
        "root": "memory-bank",
        "agents": agents,
        "agentOrder": sorted(agents.keys()),
        "summary": {
            "agents": len(agents),
            "files": sum(agent["summary"]["files"] for agent in agents.values()),
            "bytes": sum(agent["summary"]["bytes"] for agent in agents.values()),
        },
    }


def _read_jsonl(path: Path, limit: int = 300) -> List[dict]:
    if not path.exists():
        return []
    items: List[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    items.append(json.loads(raw))
                except Exception:
                    continue
    except Exception:
        return []
    if limit > 0:
        return items[-limit:]
    return items


def _tail_lines(path: Optional[Path], limit: int = 180) -> List[str]:
    if not path or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-limit:]


def _read_lines(path: Optional[Path]) -> List[str]:
    if not path or not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _latest_generation_log(project_dir: Path) -> Optional[Path]:
    log_dir = project_dir / "logs"
    # Glob ``generation*.log`` matches both ``generation.log`` (the file the
    # monitor writes when it spawns a run) AND legacy ``generation_<ts>.log``
    # (created when ``main.py`` is invoked with --log directly). The old
    # underscore-anchored pattern missed the no-suffix form, leaving
    # ``coreAgents`` empty and every agent rendered as idle in the UI even
    # while it was making tool calls.
    candidates = sorted(log_dir.glob("generation*.log"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _event_status(events: List[dict], log_lines: List[str]) -> str:
    for event in reversed(events):
        event_type = str(event.get("type", ""))
        if event_type == "generation_complete":
            return "success" if event.get("data", {}).get("success", True) else "failed"
        if event_type == "generation_error":
            return "failed"
    if any("Generation failed:" in line or "*** ERROR ***" in line for line in log_lines):
        return "failed"
    if events or log_lines:
        return "running"
    return "idle"


def _phase_summary(events: List[dict]) -> List[dict]:
    phases: Dict[str, dict] = {}
    order: List[str] = []
    for event in events:
        event_type = str(event.get("type", ""))
        message = str(event.get("message", "")).strip()
        timestamp = event.get("timestamp")
        if event_type == "phase_start":
            if message not in phases:
                order.append(message)
            phases[message] = {
                "name": message,
                "status": "running",
                "startedAt": timestamp,
                "updatedAt": timestamp,
            }
        elif event_type == "phase_complete":
            if message not in phases:
                order.append(message)
                phases[message] = {"name": message}
            phases[message]["status"] = "completed"
            phases[message]["updatedAt"] = timestamp
    return [phases[name] for name in order]


def _extract_plan_summary(log_lines: List[str]) -> dict:
    plan = {
        "name": "Generation plan",
        "description": "",
        "stages": {},
        "stageOrder": [],
        "totalTasks": 0,
        "completedTasks": 0,
        "progressPercent": 0,
        "hasPlan": False,
    }

    def ensure_stage(stage_id: str, name: Optional[str] = None) -> dict:
        stage_key = str(stage_id or "default").strip() or "default"
        if stage_key not in plan["stages"]:
            plan["stages"][stage_key] = {
                "id": stage_key,
                "name": name or stage_key.replace("_", " ").title(),
                "status": "pending",
                "tasks": {},
                "taskOrder": [],
            }
            plan["stageOrder"].append(stage_key)
        elif name:
            plan["stages"][stage_key]["name"] = name
        return plan["stages"][stage_key]

    for line in log_lines:
        match = PLAN_LINE_RE.search(line)
        if not match:
            continue
        action = match.group("action")
        payload = _safe_literal_eval(match.group("payload"))
        if not isinstance(payload, dict):
            continue
        plan["hasPlan"] = True

        if action == "create":
            plan["name"] = payload.get("plan_name") or payload.get("name") or plan["name"]
            plan["description"] = payload.get("plan_description") or payload.get("description") or ""
            for stage in payload.get("stages") or []:
                if isinstance(stage, dict):
                    ensure_stage(stage.get("id"), stage.get("name"))
        elif action in {"add_stage", "start_stage", "complete_stage"}:
            stage = ensure_stage(payload.get("stage_id"), payload.get("stage_name"))
            if action == "start_stage":
                stage["status"] = "in_progress"
            elif action == "complete_stage":
                stage["status"] = "completed"
        elif action in {"add_task", "assign_task", "start_task", "complete_task", "block_task"}:
            stage = ensure_stage(payload.get("stage_id"))
            task_id = str(payload.get("task_id") or "").strip()
            if not task_id:
                continue
            if task_id not in stage["tasks"]:
                stage["tasks"][task_id] = {
                    "id": task_id,
                    "description": payload.get("task_description") or task_id,
                    "assignee": payload.get("assignee") or "",
                    "status": "pending",
                    "result": "",
                }
                stage["taskOrder"].append(task_id)
            task = stage["tasks"][task_id]
            if payload.get("task_description"):
                task["description"] = payload.get("task_description")
            if payload.get("assignee"):
                task["assignee"] = payload.get("assignee")
            if action == "start_task":
                task["status"] = "in_progress"
            elif action == "complete_task":
                task["status"] = "completed"
                task["result"] = payload.get("result") or ""
            elif action == "block_task":
                task["status"] = "blocked"
                task["result"] = payload.get("result") or ""
        elif action == "status":
            if payload.get("name"):
                plan["name"] = payload.get("name")
            if payload.get("description"):
                plan["description"] = payload.get("description")
            for stage_info in payload.get("stages") or []:
                if not isinstance(stage_info, dict):
                    continue
                stage = ensure_stage(stage_info.get("id"), stage_info.get("name"))
                if stage_info.get("status"):
                    stage["status"] = stage_info.get("status")

    stages = []
    total = 0
    completed = 0
    for stage_id in plan["stageOrder"]:
        stage = plan["stages"][stage_id]
        tasks = [stage["tasks"][task_id] for task_id in stage["taskOrder"]]
        stage_completed = sum(1 for task in tasks if task.get("status") == "completed")
        total += len(tasks)
        completed += stage_completed
        stages.append(
            {
                "id": stage["id"],
                "name": stage["name"],
                "status": stage["status"],
                "tasks": tasks,
                "completedTasks": stage_completed,
                "totalTasks": len(tasks),
            }
        )

    plan["stages"] = stages
    plan["totalTasks"] = total
    plan["completedTasks"] = completed
    plan["progressPercent"] = round(completed / total * 100, 1) if total else 0
    return plan


def _agent_activity(log_lines: List[str], limit: int = 80) -> List[dict]:
    activity: List[dict] = []
    for line in log_lines:
        match = AGENT_LINE_RE.search(line)
        if not match:
            continue
        message = match.group("message").strip()
        if not message:
            continue
        activity.append(
            {
                "timestamp": match.group("time"),
                "agent": match.group("lane"),
                "agentLabel": match.group("agent"),
                "stage": match.group("stage") or "",
                "message": message,
                "actionType": _classify_action(message),
                "objects": _extract_objects(message),
                "status": "failed" if "❌" in message or "FAILED" in message else "ok",
            }
        )
    return activity[-limit:]


def _agent_counts(activity: List[dict]) -> List[dict]:
    counts = defaultdict(int)
    for item in activity:
        counts[item["agent"]] += 1
    return [
        {"agent": agent, "events": total}
        for agent, total in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _core_agent_status(activity: List[dict]) -> List[dict]:
    latest_by_agent: Dict[str, dict] = {}
    counts = defaultdict(int)
    for item in activity:
        agent = item.get("agent")
        if not agent:
            continue
        latest_by_agent[agent] = item
        counts[agent] += 1

    roster: List[dict] = []
    for agent in CORE_AGENT_IDS:
        latest = latest_by_agent.get(agent)
        roster.append(
            {
                "agent": agent,
                "events": counts.get(agent, 0),
                "status": "active" if latest else "idle",
                "lastTimestamp": latest.get("timestamp") if latest else None,
                "lastActionType": latest.get("actionType") if latest else None,
                "lastMessage": latest.get("message") if latest else "Waiting for activity...",
            }
        )
    return roster


def _runtime_topology(log_lines: List[str]) -> dict:
    spawned: Dict[str, dict] = {}
    teams: Dict[str, dict] = {}

    def parse_runtime(raw: str, status: str) -> dict:
        fields = dict(re.findall(r"([A-Za-z_]+)=([^\s]+)", raw))
        runtime_id = fields.get("id") or raw
        requested_type = fields.get("requested_type") or fields.get("type") or ""
        profile = fields.get("config_profile") or fields.get("profile") or ""
        resident = str(fields.get("resident", "")).lower() == "true"
        return {
            "id": runtime_id,
            "name": runtime_id,
            "label": runtime_id.replace("_", " ").replace("-", " ").title(),
            "status": status,
            "kind": "resident" if resident else "worker",
            "requestedType": requested_type,
            "configProfile": profile,
            "resident": resident,
            "owner": _core_owner_for_agent_id(runtime_id),
            "raw": raw,
        }

    for line in log_lines:
        if "AgentSpawnService:" in line and "Terminated agent runtime:" in line:
            raw = line.split("Terminated agent runtime:", 1)[1].strip()
            parsed = parse_runtime(raw, "terminated")
            record = spawned.setdefault(parsed["id"], parsed)
            record["status"] = "terminated"
            for key, value in parsed.items():
                if key in {"status", "owner", "requestedType", "configProfile", "task"}:
                    continue
                if value not in (None, ""):
                    record[key] = value
        elif "AgentSpawnService:" in line and "Spawned agent runtime:" in line:
            raw = line.split("Spawned agent runtime:", 1)[1].strip()
            parsed = parse_runtime(raw, "running")
            record = spawned.setdefault(parsed["id"], parsed)
            record.update(parsed)
        elif "DynamicAgentManager:" in line and "Spawned worker:" in line:
            match = re.search(
                r"Spawned worker:\s+(?P<id>\S+)\s+\(requested_type=(?P<requested>[^,\)]+),\s+config_profile=(?P<profile>[^,\)]+),\s+role=(?P<role>.*?)\)",
                line,
            )
            if match:
                runtime_id = match.group("id")
                owner = _core_owner_for_agent_id(match.group("profile")) or _core_owner_for_agent_id(runtime_id)
                record = spawned.setdefault(
                    runtime_id,
                    {
                        "id": runtime_id,
                        "name": runtime_id,
                        "label": runtime_id.replace("_", " ").replace("-", " ").title(),
                        "kind": "worker",
                        "resident": False,
                    },
                )
                record.update(
                    {
                        "status": record.get("status") or "running",
                        "requestedType": match.group("requested"),
                        "configProfile": match.group("profile"),
                        "task": match.group("role"),
                        "owner": owner,
                    }
                )

        if "create_agent_team" in line or "launch_agent_team" in line or "agent team" in line.lower():
            team_name = "team-runtime"
            record = teams.setdefault(team_name, {"id": team_name, "name": team_name, "label": "Team Runtime", "status": "active", "kind": "team"})
            if "terminate" in line.lower() or "paused" in line.lower():
                record["status"] = "inactive"

    spawned_agents = list(spawned.values())
    return {
        "spawnedAgents": sorted(spawned_agents, key=lambda item: (not item.get("resident"), item["name"])),
        "agentTeams": sorted(teams.values(), key=lambda item: item["name"]),
    }


def _artifact_summary(project_dir: Path) -> List[dict]:
    checks = [
        ("requirements", project_dir / "requirements" / "orchestrator.requirements.json"),
        ("api spec", project_dir / "design" / "spec.api.json"),
        ("database spec", project_dir / "design" / "spec.database.json"),
        ("ui spec", project_dir / "design" / "spec.ui.json"),
        ("frontend app", project_dir / "app" / "frontend"),
        ("backend app", project_dir / "app" / "backend"),
        ("docker", project_dir / "docker" / "docker-compose.yml"),
    ]
    return [
        {
            "label": label,
            "path": str(path.relative_to(project_dir)),
            "exists": path.exists(),
            "preview": _preview_file(path) if path.exists() and path.is_file() else None,
        }
        for label, path in checks
    ]


def _focus_objects(activity: List[dict], limit: int = 8) -> List[dict]:
    items: List[dict] = []
    for entry in reversed(activity):
        for obj in entry.get("objects", []):
            items.append(
                {
                    "agent": entry.get("agent"),
                    "actionType": entry.get("actionType"),
                    "kind": obj.get("kind"),
                    "label": obj.get("label"),
                    "timestamp": entry.get("timestamp"),
                }
            )
    return items[:limit]


def _code_previews(project_dir: Path, artifacts: List[dict], limit: int = 3) -> List[dict]:
    previews: List[dict] = []
    for artifact in artifacts:
        if not artifact.get("exists") or not artifact.get("preview"):
            continue
        previews.append(
            {
                "label": artifact["label"],
                "path": artifact["path"],
                "content": artifact["preview"],
            }
        )
        if len(previews) >= limit:
            break
    return previews


def _project_files(project_dir: Path, limit: int = 80) -> List[dict]:
    """Return generated source, spec, schema, and documentation files for inspection."""
    roots = [
        project_dir / "app" / "frontend" / "src",
        project_dir / "app" / "backend" / "src",
        project_dir / "app" / "database" / "init",
        project_dir / "database",
        project_dir / "design",
    ]
    allowed_suffixes = {
        ".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".sql", ".md", ".yml", ".yaml", ".html"
    }
    files: List[dict] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if len(files) >= limit:
                return files
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            try:
                rel_path = str(path.relative_to(project_dir))
            except Exception:
                rel_path = str(path)
            kind = "spec" if rel_path.startswith("design/") else "code"
            files.append(
                {
                    "path": rel_path,
                    "name": path.name,
                    "kind": kind,
                    "size": path.stat().st_size,
                    "preview": _preview_project_file(path),
                }
            )
    return files


def _first_host_port(port_specs: object) -> Optional[str]:
    if not isinstance(port_specs, list):
        return None
    for spec in port_specs:
        if isinstance(spec, int):
            return str(spec)
        if isinstance(spec, str):
            # Compose accepts "host:container", "ip:host:container", and bare ports.
            parts = [part for part in spec.split(":") if part]
            if len(parts) >= 2:
                candidate = parts[-2]
            elif parts:
                candidate = parts[0]
            else:
                continue
            if candidate.isdigit():
                return candidate
        if isinstance(spec, dict):
            published = spec.get("published") or spec.get("host_port")
            if published:
                return str(published)
    return None


def _preview_url_from_compose(project_dir: Path) -> Optional[str]:
    candidates = [
        project_dir / "docker" / "docker-compose.local.yml",
        project_dir / "docker" / "docker-compose.yml",
        project_dir / "docker" / "docker-compose.dev.yml",
        project_dir / "docker-compose.local.yml",
        project_dir / "docker-compose.yml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            continue
        for preferred in ("frontend", "web", "ui", "client"):
            service = services.get(preferred)
            if isinstance(service, dict):
                port = _first_host_port(service.get("ports"))
                if port:
                    return f"http://127.0.0.1:{port}"
        for name, service in services.items():
            if "front" not in str(name).lower() and str(name).lower() not in {"web", "ui", "client"}:
                continue
            if isinstance(service, dict):
                port = _first_host_port(service.get("ports"))
                if port:
                    return f"http://127.0.0.1:{port}"
    return None


def _runtime_contract(project_dir: Path) -> dict:
    candidates = [
        project_dir / "docker" / "docker-compose.local.yml",
        project_dir / "docker" / "docker-compose.yml",
        project_dir / "docker" / "docker-compose.dev.yml",
        project_dir / "docker-compose.local.yml",
        project_dir / "docker-compose.yml",
    ]
    compose_files = []
    services = {}
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            compose_files.append({"path": str(path.relative_to(project_dir)), "error": str(exc)})
            continue
        raw_services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(raw_services, dict):
            continue
        compose_files.append({"path": str(path.relative_to(project_dir)), "services": sorted(raw_services.keys())})
        for name, service in raw_services.items():
            if not isinstance(service, dict):
                continue
            if name in services:
                continue
            ports = []
            for spec in service.get("ports") or []:
                ports.append({"raw": spec, "host": _first_host_port([spec])})
            services[name] = {
                "compose": str(path.relative_to(project_dir)),
                "image": service.get("image"),
                "build": service.get("build"),
                "ports": ports,
                "environment": service.get("environment") or {},
                "depends_on": service.get("depends_on") or [],
                "command": service.get("command"),
            }
    return {
        "previewUrl": _preview_url(project_dir),
        "composeFiles": compose_files,
        "services": services,
    }


def _preview_url_from_config(project_dir: Path) -> Optional[str]:
    candidates = [
        project_dir / "config.yaml",
        project_dir / "config.yml",
        project_dir / "app" / "config.yaml",
        project_dir / "app" / "config.yml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("preview_url", "previewUrl", "app_url", "appUrl"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        frontend = data.get("frontend")
        if isinstance(frontend, dict):
            for key in ("preview_url", "previewUrl", "url"):
                value = frontend.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            port = frontend.get("host_port") or frontend.get("port")
            if port:
                return f"http://127.0.0.1:{port}"
    return None


def _preview_url(project_dir: Path) -> str:
    configured = os.getenv("MONITOR_PREVIEW_URL") or os.getenv("APP_PREVIEW_URL")
    if configured:
        return configured
    return (
        _preview_url_from_config(project_dir)
        or _preview_url_from_compose(project_dir)
        or "http://127.0.0.1:3000"
    )


def _recent_tool_calls(
    log_path: Optional[Path],
    limit_per_agent: int = 20,
    log_root: Optional[Path] = None,
) -> List[dict]:
    run_started_at = _parse_run_timestamp(log_path)
    events: List[dict] = []
    for agent_id in CORE_AGENT_IDS:
        agent_log = _closest_agent_log(agent_id, run_started_at, log_root=log_root)
        events.extend(_load_recent_tool_calls(agent_log, agent_id, limit=limit_per_agent))
    events.sort(key=lambda item: str(item.get("timestamp", "")))
    return events[-120:]


def build_state(project_dir: Path) -> dict:
    project_dir = project_dir.resolve()
    log_path = _latest_generation_log(project_dir)
    event_path = project_dir / "logs" / "progress_events.jsonl"
    events = _read_jsonl(event_path)
    all_log_lines = _read_lines(log_path)
    log_lines = all_log_lines[-180:]
    activity = _agent_activity(log_lines)
    artifacts = _artifact_summary(project_dir)
    runtime_topology = _runtime_topology(all_log_lines)
    # Per-workspace ``.agent_logs/`` is the new contract: each project
    # owns its own action-history dir, so switching projects doesn't
    # surface stale tool calls from a prior run. Falls back to the
    # legacy host-wide root when the workspace lacks one (e.g. very
    # old workspaces).
    log_root = _agent_log_root_for(project_dir)
    agent_tool_logs = _agent_tool_logs(log_path, log_root=log_root)
    tool_calls = sorted(
        [call for calls in agent_tool_logs.values() for call in calls],
        key=lambda item: str(item.get("timestamp", "")),
    )[-120:]
    agent_workspaces = {
        agent_id: {
            "agent": agent_id,
            "history": [item for item in activity if item.get("agent") == agent_id][-120:],
            "toolCalls": agent_tool_logs.get(agent_id, [])[-120:],
            "plan": _agent_plan_summary(agent_tool_logs.get(agent_id, [])),
            "mailbox": _agent_mailbox(agent_id, agent_tool_logs.get(agent_id, []), agent_tool_logs),
            "runtime": _agent_runtime_summary(agent_id, agent_tool_logs.get(agent_id, []), runtime_topology),
        }
        for agent_id in CORE_AGENT_IDS
    }

    return {
        "projectName": project_dir.name,
        "projectDir": str(project_dir),
        "status": _event_status(events, log_lines),
        "latestLog": str(log_path) if log_path else None,
        "eventLog": str(event_path),
        "phases": _phase_summary(events),
        "planSummary": _extract_plan_summary(log_lines),
        "recentEvents": events[-80:],
        "recentActivity": activity,
        "agentCounts": _agent_counts(activity),
        "coreAgents": _core_agent_status(activity),
        "recentLogLines": log_lines,
        "artifacts": artifacts,
        "runtimeContract": _runtime_contract(project_dir),
        "focusObjects": _focus_objects(activity),
        "codePreviews": _code_previews(project_dir, artifacts),
        "projectFiles": _project_files(project_dir),
        "previewUrl": _preview_url(project_dir),
        "planHistory": _plan_history(agent_tool_logs),
        "spawnedAgents": runtime_topology["spawnedAgents"],
        "agentTeams": runtime_topology["agentTeams"],
        "toolCalls": tool_calls,
        "agentWorkspaces": agent_workspaces,
        # Cutover 28: crdt key kept for back-compat with older UIs; UI uses "hubs" now.
        "crdt": _crdt_document(project_dir),
        "memoryBank": _memory_bank_state(project_dir),
    }


def build_projects_list(workspaces_root: Path) -> dict:
    """List all projects under a workspaces-root for the homepage."""
    from multi_agent.runtime.project import ProjectIndex, load_project_metadata
    if not workspaces_root.exists():
        return {"projects": []}
    idx = ProjectIndex(workspaces_root)
    projects = []
    for md in idx.list():
        workspace = workspaces_root / md.id
        # Fall back to scanning for the actual workspace dir if names differ
        if not workspace.exists():
            for child in workspaces_root.iterdir():
                if not child.is_dir():
                    continue
                m = load_project_metadata(child)
                if m and m.id == md.id:
                    workspace = child
                    break
        projects.append({
            "id": md.id,
            "name": md.name,
            "description": md.description,
            "status": md.status,
            "created_at": md.created_at,
            "last_active_at": md.last_active_at,
            "workspace_path": str(workspace),
        })
    return {"projects": projects}


def _hub_snapshots(workspace: Path) -> dict:
    """Return {hub_name: snapshot} for all five hubs by constructing HubRegistry."""
    from multi_agent.runtime.hub_registry import HubRegistry
    try:
        reg = HubRegistry(workspace)
        return reg.snapshot()
    except Exception as e:
        return {
            "error": f"failed to load hub snapshots: {e}",
            "codehub": {},
            "registryhub": {},
            "workhub": {},
            "eventhub": {},
            "runhub": {},
        }


def _safe_release_tag(tag: str) -> str:
    """Match codehub.create_release's branch-name sanitiser (release-v<safe_tag>)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(tag)).strip("-") or "untagged"


def build_releases_list(workspaces_root: Path, project_id: str) -> dict:
    """Releases cut for a project, newest-first — feeds the Preview version
    switcher. Each release is an immutable ``release-v<tag>`` git branch
    (codehub.create_release), recoverable by its ``branch_sha``; ``snapshots``
    lists any pre-captured page screenshots for the hybrid preview."""
    from multi_agent.runtime.project import ProjectIndex
    idx = ProjectIndex(workspaces_root)
    md, workspace = idx.get(project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}", "releases": []}
    rel_path = Path(workspace) / "shared" / "hubs" / "codehub_releases.json"
    releases: List[dict] = []
    if rel_path.exists():
        try:
            data = json.loads(rel_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        snap_root = Path(workspace) / ".preview_snapshots"
        for tag, r in data.items():
            if tag == "_meta" or not isinstance(r, dict):
                continue
            safe = _safe_release_tag(r.get("tag", tag))
            snap_dir = snap_root / safe
            shots = sorted(p.name for p in snap_dir.glob("*.png")) if snap_dir.exists() else []
            releases.append({
                "tag": r.get("tag", tag),
                "branch": r.get("branch") or f"release-v{safe}",
                "sha": r.get("branch_sha"),
                "notes": r.get("notes"),
                "createdAt": r.get("created_at"),
                "snapshots": shots,
            })
    releases.sort(key=lambda x: x.get("createdAt") or 0, reverse=True)
    return {"releases": releases, "projectId": project_id}


def build_milestones(workspace: Path) -> dict:
    """Milestone roadmap + progress for the Overview strip. Derived from:
    the kickoff meetings' roadmap decision (kind=milestone_plan — agent- or
    user-provided), the per-milestone kickoff meeting pages, and the cut
    releases. Best-effort; absent data → empty list."""
    import re as _re
    hubs_dir = Path(workspace) / "shared" / "hubs"
    plan: list = []
    kickoffs: dict = {}
    try:
        _docs_path = hubs_dir / "workhub_documents.json"
        # page→document rename: prefer the new file; fall back to the legacy
        # ``workhub_pages.json`` for runs that pre-date the rename (or that the
        # hub layer has not yet migrated on this machine).
        if not _docs_path.exists():
            _docs_path = hubs_dir / "workhub_pages.json"
        pages = json.loads(_docs_path.read_text(encoding="utf-8"))
    except Exception:
        pages = {}
    for pid, pg in pages.items():
        if pid == "_meta" or not isinstance(pg, dict):
            continue
        title = str(pg.get("title") or "")
        m = _re.match(r"M(\d+) kickoff", title, _re.IGNORECASE)
        if m:
            kickoffs[int(m.group(1))] = {"page_id": pid,
                                         "status": pg.get("status"),
                                         "title": title}
        for d in ((pg.get("metadata") or {}).get("decisions") or []):
            body = d.get("decision") if isinstance(d.get("decision"), dict) else d
            if not isinstance(body, dict):
                continue
            if str(body.get("kind")) == "milestone_plan" or str(body.get("section")) == "roadmap":
                content = body.get("content") if isinstance(body.get("content"), dict) else body
                cand = content.get("milestones") if isinstance(content, dict) else None
                if isinstance(cand, list) and cand:
                    plan = cand
    released = {}
    try:
        rel = json.loads((hubs_dir / "codehub_releases.json").read_text(encoding="utf-8"))
        for tag, r in rel.items():
            if tag != "_meta" and isinstance(r, dict):
                released[str(r.get("tag", tag))] = r.get("created_at")
    except Exception:
        pass
    out = []
    n = max(len(plan), len(kickoffs) or 0)
    for i in range(1, n + 1):
        entry = plan[i - 1] if i <= len(plan) and isinstance(plan[i - 1], dict) else {}
        version = str(entry.get("version") or f"1.{i - 1}.0")
        name = str(entry.get("name") or f"M{i}")
        ko = kickoffs.get(i)
        if version in released:
            status = "released"
        elif ko:
            status = "active"
        else:
            status = "planned"
        out.append({"index": i, "name": name, "version": version,
                    "status": status, "released_at": released.get(version),
                    "kickoff_page_id": (ko or {}).get("page_id")})
    current = next((m["index"] for m in out if m["status"] == "active"), None)
    return {"milestones": out, "current_index": current,
            "released_count": sum(1 for m in out if m["status"] == "released"),
            "total": len(out),
            "source": "agent_planned" if plan else "kickoff_pages"}


def build_project_state(workspaces_root: Path, project_id: str) -> dict:
    """Per-project dashboard payload."""
    from multi_agent.runtime.project import ProjectIndex
    idx = ProjectIndex(workspaces_root)
    md, workspace = idx.get(project_id)
    if md is None or workspace is None:
        return {"error": f"project not found: {project_id}"}
    state = build_state(workspace)
    state["projectId"] = md.id
    state["projectName"] = md.name
    state["projectStatus"] = md.status
    state["projectDescription"] = md.description
    state["hubs"] = _hub_snapshots(workspace)
    state["milestones"] = build_milestones(workspace)
    # Cutover 36: include runs whose project_id matches so the UI can show
    # "View Logs" buttons. Each entry exposes the minimum needed to render
    # an action pill — full run metadata is available via /api/runs/<id>/status.
    with _RUN_REGISTRY_LOCK:
        project_runs = [
            {
                "run_id": h["run_id"],
                "state": h["state"],
                "started_at": h["started_at"],
                "returncode": h.get("returncode"),
            }
            for h in _RUN_REGISTRY.values()
            if h.get("project_id") == project_id
        ]
    state["active_runs"] = sorted(project_runs, key=lambda r: r["started_at"], reverse=True)
    return state


def _project_workspace(workspaces_root: Path, project_id: str) -> Optional[Path]:
    from multi_agent.runtime.project import ProjectIndex
    _, workspace = ProjectIndex(workspaces_root).get(project_id)
    return workspace


def build_conversations_list(workspaces_root: Path, project_id: str) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}", "conversations": []}
    reg = HubRegistry(workspace)
    return {"conversations": reg.human_console.list_conversations()}


# Cutover 32: cached parsed ``agents_config.yaml`` profiles (server-restart
# invalidates; adequate for the local-only deployment).
_AGENT_PROFILES_CACHE: Optional[List[dict]] = None
_AGENT_PROFILES_CACHE_LOCK = threading.Lock()


def _load_agent_profiles() -> List[dict]:
    """Parse ``multi_agent/agents/agents_config.yaml`` profiles for the chat
    dropdown.

    Returns a list of ``{id, name, description, can_deliver, team_lead}``
    dicts, sorted with team-leads first, then deliverers, then alphabetic.
    Empty list on missing/malformed file. Result is cached after first read.
    """
    global _AGENT_PROFILES_CACHE
    with _AGENT_PROFILES_CACHE_LOCK:
        if _AGENT_PROFILES_CACHE is not None:
            return _AGENT_PROFILES_CACHE
        config_path = (
            Path(__file__).resolve().parent
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        if not config_path.exists():
            _AGENT_PROFILES_CACHE = []
            return _AGENT_PROFILES_CACHE
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            _AGENT_PROFILES_CACHE = []
            return _AGENT_PROFILES_CACHE

        profiles: List[dict] = []
        for agent_id, info in (data.get("profiles") or {}).items():
            if not isinstance(info, dict):
                continue
            flags = info.get("flags") or {}
            profiles.append({
                "id": agent_id,
                "name": info.get("name", agent_id),
                "description": info.get("description", ""),
                "can_deliver": bool(flags.get("can_deliver", False)),
                "team_lead": bool(flags.get("team_lead", False)),
            })
        # Team leads first, then deliverers, then alphabetic.
        profiles.sort(
            key=lambda p: (not p["team_lead"], not p["can_deliver"], p["id"])
        )
        _AGENT_PROFILES_CACHE = profiles
        return _AGENT_PROFILES_CACHE


def build_agents_list(workspaces_root: Path, project_id: str) -> dict:
    """``GET /api/projects/<id>/agents`` payload.

    Validates the project exists, then returns the cached agent profile
    list from ``agents_config.yaml``. Profiles are intentionally project-
    independent today; the project_id check keeps the API symmetric with
    other per-project endpoints and lets future cutovers apply per-project
    visibility flags.
    """
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    return {"agents": _load_agent_profiles()}


def build_messages_list(workspaces_root: Path, project_id: str, thread_id: str) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}", "messages": []}
    reg = HubRegistry(workspace)
    try:
        return {"messages": reg.human_console.list_messages(thread_id)}
    except ValueError as e:
        return {"error": str(e), "messages": []}


def start_conversation_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    reg = HubRegistry(workspace)
    try:
        # Phase 4.7-slim Path C: when an authed session reached
        # _apply_request_user, body["from_user"] is already the
        # session username — pass it through. When unauthed/guest,
        # body.get("from_user") is whatever the body supplied (or
        # None) — pass it through too; HumanConsole then falls back
        # to its Path A chain (ENVGEN_HUMAN_USER_ID env var). The
        # 4.7 gate at eventhub.publish_human_message rejects the
        # literal "human_user" placeholder if all bridges miss.
        return reg.human_console.start_conversation(
            target_agents=body.get("target_agents") or [],
            text=body.get("text") or "",
            from_user=body.get("from_user") or None,
        )
    except ValueError as e:
        return {"error": str(e)}


def send_message_call(workspaces_root: Path, project_id: str, thread_id: str, body: dict) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    reg = HubRegistry(workspace)
    try:
        # Phase 4.7-slim Path C: see start_conversation_call above.
        reg.human_console.send_message(
            thread_id=thread_id,
            text=body.get("text") or "",
            from_user=body.get("from_user") or None,
            target_agents=body.get("target_agents") or None,
        )
        return {"ok": True}
    except ValueError as e:
        return {"error": str(e)}


def delete_conversation_call(workspaces_root: Path, project_id: str, thread_id: str) -> dict:
    """Hide a conversation from the chat list (marks the thread resolved)."""
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    try:
        HubRegistry(workspace).human_console.mark_resolved(thread_id)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Cutover 30: project lifecycle helpers
# ---------------------------------------------------------------------------


def create_project_call(workspaces_root: Path, body: dict) -> dict:
    """POST /api/projects — create a new project workspace.

    Body fields:
      name (required), description (optional), id (optional, else minted)
    """
    from multi_agent.runtime.hub_registry import HubRegistry
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}
    pid = (body.get("id") or "").strip() or None  # let HubRegistry mint one
    description = (body.get("description") or "").strip()
    workspace_name = pid or f"proj_{uuid.uuid4().hex[:8]}"
    workspace = workspaces_root / workspace_name
    if workspace.exists():
        return {"error": f"workspace already exists: {workspace.name}"}
    try:
        workspaces_root.mkdir(parents=True, exist_ok=True)
        reg = HubRegistry(
            workspace,
            project_id=pid or workspace_name,
            project_name=name,
            project_description=description,
        )
        md = reg.project_metadata
        # Cutover 32: broadcast lifecycle event onto the global SSE hub so the
        # homepage learns about the new project without polling.
        _publish_global_event(
            workspaces_root,
            "project_created",
            {"name": md.name, "status": md.status},
            project_id=md.id,
        )
        return {
            "id": md.id,
            "name": md.name,
            "description": md.description,
            "status": md.status,
            "created_at": md.created_at,
            "last_active_at": md.last_active_at,
        }
    except Exception as e:
        return {"error": f"create_project failed: {e}"}


def set_project_status_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/status — change project lifecycle status."""
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    status = (body.get("status") or "").strip()
    try:
        reg = HubRegistry(workspace)
        reg.set_project_status(status)
        md = reg.project_metadata
        # Cutover 32: broadcast status change onto the global SSE hub.
        _publish_global_event(
            workspaces_root,
            "project_status_changed",
            {"status": md.status},
            project_id=md.id,
        )
        return {"id": md.id, "status": md.status, "last_active_at": md.last_active_at}
    except ValueError as e:
        return {"error": str(e)}


def set_reasoning_effort_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/reasoning_effort — set per-lane gpt-5 reasoning_effort live.

    Body: ``{"all": "<effort>"}`` sets every resident lane, or ``{"<lane>": "<effort>", ...}``
    merges per-lane into the existing map. Values are normalized (unknown -> "medium").
    The generation process picks up the change on its next LLM call (it reads
    reasoning_effort.json fresh — see multi_agent/runtime/reasoning_effort.py).
    """
    from multi_agent.runtime.reasoning_effort import (
        read_effort_map,
        write_effort_map,
        normalize_effort,
    )

    _RESIDENT_LANES = ("orchestrator", "backend", "frontend", "verifier", "debugger", "knowledge")
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    current = dict(read_effort_map(workspace))
    if "all" in body:
        eff = normalize_effort(body["all"])
        current = {lane: eff for lane in _RESIDENT_LANES}
    else:
        for lane, eff in body.items():
            if str(lane).startswith("_"):  # skip metadata keys like _requester_role
                continue
            current[str(lane)] = normalize_effort(eff)
    write_effort_map(workspace, current)
    return {"reasoning_effort": current}


def delete_project_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """DELETE /api/projects/<id> — irrevocably remove workspace dir.

    Safety guards (defense in depth):
      1. workspace must resolve INSIDE workspaces_root (no path traversal).
      2. body must include confirm=True.
      3. if body.confirm_name is provided, it must match the stored project name.
         (UI always sends confirm_name; backend tests may omit it.)
    """
    import shutil
    from multi_agent.runtime.hub_registry import HubRegistry

    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}

    # Path-traversal guard: workspace path must be strictly inside workspaces_root.
    try:
        ws_resolved = workspace.resolve()
        root_resolved = Path(workspaces_root).resolve()
        ws_resolved.relative_to(root_resolved)
    except (ValueError, OSError):
        return {"error": "workspace path is outside workspaces_root; refusing to delete"}
    if ws_resolved == root_resolved:
        return {"error": "refusing to delete workspaces_root itself"}

    if not body.get("confirm"):
        return {"error": "delete requires body confirm=true"}

    # Optional name-confirmation (UI sends this to prevent fat-finger deletes).
    confirm_name = body.get("confirm_name")
    if confirm_name is not None:
        try:
            reg = HubRegistry(workspace)
            stored_name = reg.project_metadata.name
        except Exception as e:
            return {"error": f"could not read project metadata: {e}"}
        if confirm_name != stored_name:
            return {
                "error": (
                    f"confirm_name mismatch: expected {stored_name!r}, "
                    f"got {confirm_name!r}"
                )
            }

    # Stop any active run(s) for this project FIRST so the orchestrator doesn't
    # keep running with its workspace yanked out from under it (which would
    # spew file-not-found errors and keep burning API tokens). Also prune the
    # in-memory + persisted run registry so /api/runs doesn't show ghost
    # "running" entries pointing at a deleted workspace.
    stopped_runs: list[str] = []
    with _RUN_REGISTRY_LOCK:
        proj_run_ids = [rid for rid, h in _RUN_REGISTRY.items() if h.get("project_id") == project_id]
        for rid in proj_run_ids:
            handle = _RUN_REGISTRY.get(rid)
            if not handle:
                continue
            popen = handle.get("popen")
            if popen is not None:
                try:
                    if popen.poll() is None:
                        popen.terminate()
                        for _ in range(50):    # up to 5s for graceful shutdown
                            if popen.poll() is not None:
                                break
                            time.sleep(0.1)
                        if popen.poll() is None:
                            popen.kill()
                    handle["state"] = "stopped"
                    handle["returncode"] = popen.poll()
                    stopped_runs.append(rid)
                except Exception:
                    pass
            # Drop the entry — its workspace is about to vanish.
            _RUN_REGISTRY.pop(rid, None)
    if stopped_runs:
        _save_registry(workspaces_root)
    # Drop the cached API key for this project (in-RAM only) so no stale Continue.
    _PROJECT_API_KEYS.pop(project_id, None)

    # Cutover 32: broadcast lifecycle event BEFORE rmtree so any client
    # currently subscribed to the project's per-project SSE stream still
    # gets the deletion notice via the global stream.
    _publish_global_event(
        workspaces_root,
        "project_deleted",
        {"stopped_runs": stopped_runs},
        project_id=project_id,
    )
    try:
        shutil.rmtree(ws_resolved)
        # Cutover 31: drop the cached HubRegistry so a re-created project
        # with the same id (or a fresh ``/state`` request) doesn't read
        # stale in-memory hubs.
        _clear_hub_registry_cache_for_project(workspaces_root, project_id)
        return {"ok": True, "deleted": project_id, "stopped_runs": stopped_runs}
    except Exception as e:
        return {"error": f"rmtree failed: {e}", "stopped_runs": stopped_runs}


# ---------------------------------------------------------------------------
# Cutover 30 Task 3: WorkHub operation endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cutover 31: HubRegistry cache (per project)
#
# Prior to Cutover 31, ``_resolve_hubs`` constructed a fresh ``HubRegistry``
# (and therefore a fresh ``EventHub``) per request. That was fatal for SSE:
# a bridge attached during ``GET /events`` would live on a hub instance
# that no subsequent ``POST`` mutation ever publishes to. The cache below
# keys registries by ``(workspaces_root, project_id)`` so every request for
# the same project shares the same in-memory hub objects.
# ---------------------------------------------------------------------------

_HUB_REGISTRY_CACHE: Dict[Tuple[str, str], object] = {}
_HUB_REGISTRY_CACHE_LOCK = threading.Lock()


def _hub_cache_key(workspaces_root: Path, project_id: str) -> Tuple[str, str]:
    return (str(Path(workspaces_root).resolve()), project_id)


def _clear_hub_registry_cache_for_project(workspaces_root: Path, project_id: str) -> None:
    """Evict the cached HubRegistry (and SSE hub) for a project.

    Called from ``delete_project_call`` so a re-created project with the same
    id (or a fresh ``/state`` request) doesn't read stale in-memory hubs, and
    so subscribed SSE clients on the doomed project don't continue to receive
    events from a phantom hub.
    """
    key = _hub_cache_key(workspaces_root, project_id)
    with _HUB_REGISTRY_CACHE_LOCK:
        _HUB_REGISTRY_CACHE.pop(key, None)
    with _SSE_HUB_CACHE_LOCK:
        _SSE_HUB_CACHE.pop(key, None)


def _resolve_hubs(workspaces_root: Path, project_id: str):
    """Return (HubRegistry, None) for the project, or (None, error_dict).

    The HubRegistry is cached per ``(workspaces_root, project_id)``: every
    caller for the same project receives the same in-memory instance, so
    bridges attached on one request observe events published by every
    subsequent request.
    """
    # Cutover 38: idempotent re-attach of persisted run handles.
    _load_registry(workspaces_root)
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return None, {"error": f"project not found: {project_id}"}
    key = _hub_cache_key(workspaces_root, project_id)
    with _HUB_REGISTRY_CACHE_LOCK:
        reg = _HUB_REGISTRY_CACHE.get(key)
        if reg is None:
            reg = HubRegistry(workspace)
            # Cutover 32: attach a forwarder so every per-project event
            # reaches the workspaces-root-scoped global SSE hub. Done once
            # per HubRegistry (when newly cached) so we never double-bridge.
            global_hub = _get_or_create_global_sse_hub(workspaces_root)
            reg.eventhub.add_bridge(_GlobalForwardBridge(global_hub, project_id))
            _HUB_REGISTRY_CACHE[key] = reg
    return reg, None


# ---------------------------------------------------------------------------
# Cutover 31: SSE hub (per project)
#
# ``_SSEHub`` is a fan-out queue that doubles as an ``EventHub`` delivery
# bridge. Each connected browser owns a bounded ``queue.Queue``; the SSE
# handler thread blocks on ``q.get(timeout=15)`` and ships JSON frames over
# the keep-alive HTTP response. Heartbeats keep idle intermediaries from
# closing the socket; full queues drop events silently (the 30s fallback
# polling loop re-syncs via ``/state``).
# ---------------------------------------------------------------------------


class _SSEHub:
    """Fan-out queue for browser SSE clients (EventHub bridge protocol)."""

    def __init__(self, max_queue: int = 256):
        self._max_queue = max_queue
        self._clients: Dict[str, "queue.Queue"] = {}
        self._lock = threading.Lock()

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def register(self, client_id: str) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._clients[client_id] = q
        return q

    def unregister(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    def broadcast(self, event: dict) -> None:
        with self._lock:
            clients = list(self._clients.values())
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                # Slow client: drop the event. Polling fallback re-syncs.
                pass

    def deliver(self, event: dict) -> None:
        """EventHub bridge protocol: delegate to :meth:`broadcast`."""
        self.broadcast(event)


_SSE_HUB_CACHE: Dict[Tuple[str, str], _SSEHub] = {}
_SSE_HUB_CACHE_LOCK = threading.Lock()


def _get_or_create_sse_hub(workspaces_root: Path, project_id: str) -> Optional[_SSEHub]:
    """Return the cached ``_SSEHub`` for the project, attaching it as an
    EventHub bridge on first creation. Returns ``None`` if the project is
    unknown.
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return None
    key = _hub_cache_key(workspaces_root, project_id)
    with _SSE_HUB_CACHE_LOCK:
        hub = _SSE_HUB_CACHE.get(key)
        if hub is None:
            hub = _SSEHub()
            reg.eventhub.add_bridge(hub)
            _SSE_HUB_CACHE[key] = hub
    return hub


# ---------------------------------------------------------------------------
# Cutover 32: workspaces-root-scoped global SSE hub
#
# The homepage needs push updates for project create/delete/status changes
# (Cutover 31's SSE is per-project). The global hub is a single ``_SSEHub``
# per ``workspaces_root`` that receives:
#   1. Lifecycle events explicitly published by ``create_project_call`` /
#      ``set_project_status_call`` / ``delete_project_call``.
#   2. Every per-project EventHub publish, re-broadcast by a
#      ``_GlobalForwardBridge`` attached when the project's HubRegistry is
#      first cached. Each forwarded event is annotated with ``project_id``
#      so the homepage knows which project to refresh.
# ---------------------------------------------------------------------------


class _GlobalSSEHub(_SSEHub):
    """Workspaces-root-scoped SSE fan-out.

    Mechanically identical to :class:`_SSEHub`; the dedicated subclass keeps
    type signatures self-documenting and gives us a hook to diverge later
    if the global stream grows distinct semantics.
    """


class _GlobalForwardBridge:
    """EventHub bridge that re-broadcasts per-project events onto the global
    SSE hub, annotating each event with ``project_id`` so the homepage knows
    which project triggered it.

    Attached once per HubRegistry (when first cached) so any hub mutation
    is visible to the homepage SSE client without polling.
    """

    def __init__(self, global_hub: _GlobalSSEHub, project_id: str):
        self._hub = global_hub
        self._project_id = project_id

    def deliver(self, event: dict) -> None:
        try:
            self._hub.broadcast({**event, "project_id": self._project_id})
        except Exception:
            # Bridge errors must never break the EventHub publish path.
            pass


_GLOBAL_SSE_HUB_CACHE: Dict[str, _GlobalSSEHub] = {}
_GLOBAL_SSE_HUB_CACHE_LOCK = threading.Lock()


def _global_hub_cache_key(workspaces_root: Path) -> str:
    return str(Path(workspaces_root).resolve())


def _get_or_create_global_sse_hub(workspaces_root: Path) -> _GlobalSSEHub:
    """Return the cached ``_GlobalSSEHub`` for ``workspaces_root``.

    Unlike the per-project hub, this does not attach itself to any EventHub
    directly — lifecycle events are published via :func:`_publish_global_event`
    and per-project events are forwarded by :class:`_GlobalForwardBridge`
    (which :func:`_resolve_hubs` attaches when caching a new HubRegistry).
    """
    key = _global_hub_cache_key(workspaces_root)
    with _GLOBAL_SSE_HUB_CACHE_LOCK:
        hub = _GLOBAL_SSE_HUB_CACHE.get(key)
        if hub is None:
            hub = _GlobalSSEHub()
            _GLOBAL_SSE_HUB_CACHE[key] = hub
    return hub


def _publish_global_event(
    workspaces_root: Path,
    event_type: str,
    payload: dict,
    project_id: Optional[str] = None,
    source_hub: str = "ui",
) -> None:
    """Broadcast a synthetic lifecycle event on the global SSE hub.

    Used by ``create_project_call`` / ``set_project_status_call`` /
    ``delete_project_call`` so the homepage receives push updates without
    polling.
    """
    import time as _time
    hub = _get_or_create_global_sse_hub(workspaces_root)
    hub.broadcast({
        "id": f"evt_global_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "source_hub": source_hub,
        "project_id": project_id,
        "payload": payload or {},
        "created_at": _time.time(),
    })


# ---------------------------------------------------------------------------
# Cutover 34: Run registry — track orchestrator subprocesses
# ---------------------------------------------------------------------------

_RUN_REGISTRY: Dict[str, dict] = {}
_RUN_REGISTRY_LOCK = threading.Lock()
# In-memory only (never persisted to disk or logged): the API key last used to
# launch each project, so the UI "Continue" button can resume without the user
# re-entering it. Cleared on server restart.
_PROJECT_API_KEYS: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Cutover 38: Persistence + reconnect across server restarts
# ---------------------------------------------------------------------------

_LOADED_ROOTS: Set[str] = set()
_LOADED_ROOTS_LOCK = threading.Lock()


class _AttachedRunHandle:
    """Popen-API-compatible shim for a process we no longer own.

    After server restart, our orchestrator subprocesses (started with
    start_new_session=True) survive. We can no longer waitpid on them
    (we're not the parent), but we CAN signal them and check liveness
    via os.kill(pid, 0). `poll()` returns None while alive and 0 when
    the OS reports the pid is gone. The true exit status is unknown
    (so `returncode` stays None even after death).
    """

    def __init__(self, pid: int):
        self.pid = pid
        self._returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self._returncode is not None:
            return self._returncode
        try:
            os.kill(self.pid, 0)
            return None  # still alive
        except ProcessLookupError:
            self._returncode = 0  # we don't know real rc; assume clean
            return 0
        except PermissionError:
            return None  # alive, just not signal-able
        except Exception:
            self._returncode = 0
            return 0

    @property
    def returncode(self) -> Optional[int]:
        return self._returncode

    def terminate(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except Exception:
            pass

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except Exception:
            pass

    def wait(self, timeout: Optional[float] = None) -> int:
        # Poll until dead or timeout
        deadline = time.time() + (timeout if timeout is not None else 30.0)
        while time.time() < deadline:
            if self.poll() is not None:
                return self._returncode or 0
            time.sleep(0.1)
        return self._returncode or 0


def _registry_file(workspaces_root: Path) -> Path:
    return Path(workspaces_root) / ".runs.json"


def _save_registry(workspaces_root: Path) -> None:
    """Persist the in-memory registry (filtered to this workspaces_root) to disk."""
    try:
        Path(workspaces_root).mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    out: Dict[str, dict] = {}
    with _RUN_REGISTRY_LOCK:
        for run_id, h in _RUN_REGISTRY.items():
            if h.get("workspaces_root") and str(h["workspaces_root"]) != str(workspaces_root):
                continue
            popen = h.get("popen")
            pid = getattr(popen, "pid", None) if popen else h.get("pid")
            entry = {k: v for k, v in h.items() if k != "popen"}
            entry["pid"] = pid
            out[run_id] = entry
    tmp_path = _registry_file(workspaces_root).with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(out, indent=2, default=str))
        os.replace(tmp_path, _registry_file(workspaces_root))
    except Exception:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def _load_registry(workspaces_root: Path) -> None:
    """Load persisted registry entries from disk; attach _AttachedRunHandle to live pids.

    Idempotent — a second call for the same workspaces_root is a no-op.
    """
    key = str(Path(workspaces_root).resolve())
    with _LOADED_ROOTS_LOCK:
        if key in _LOADED_ROOTS:
            return
        _LOADED_ROOTS.add(key)
    runs_file = _registry_file(workspaces_root)
    if not runs_file.exists():
        return
    try:
        data = json.loads(runs_file.read_text())
    except Exception:
        return
    with _RUN_REGISTRY_LOCK:
        for run_id, entry in (data or {}).items():
            if run_id in _RUN_REGISTRY:
                continue  # already in memory, prefer it
            pid = entry.get("pid")
            attached = None
            state = entry.get("state", "running")
            returncode = entry.get("returncode")
            if pid:
                attached = _AttachedRunHandle(pid=int(pid))
                if attached.poll() is not None and state == "running":
                    state = "completed"
            _RUN_REGISTRY[run_id] = {
                **entry,
                "popen": attached,
                "state": state,
                "returncode": returncode,
                "workspaces_root": entry.get("workspaces_root") or str(workspaces_root),
            }


# Provider <-> default API-key env var (must match main.py's provider_map).
_PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",  # main.py also accepts GOOGLE_API_KEY
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "local": None,
}


def _project_id_from_name(workspaces_root: Path, name: str) -> str:
    """Derive a filesystem-safe project_id from a human name; append uuid if collision."""
    base = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip()).strip("-").lower()
    if not base:
        base = "project"
    candidate = base
    if (workspaces_root / candidate).exists():
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
    return candidate


def start_run_call(workspaces_root: Path, body: dict) -> dict:
    """Spawn ``main.py`` as a subprocess for a new generation.

    Body fields:
      - name (required): human-readable project name
      - description: optional one-liner
      - model: optional LLM model (default gpt-4)
      - provider: optional, one of openai/google/anthropic/azure/local
      - reference_images: optional list of absolute paths
    Returns: ``{run_id, project_id, log_path}`` or ``{error}``.
    """
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "name required"}
    workspaces_root = Path(workspaces_root)
    workspaces_root.mkdir(parents=True, exist_ok=True)

    project_id = _project_id_from_name(workspaces_root, name)
    workspace = workspaces_root / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "generation.log"

    model = body.get("model") or "gpt-4"
    provider = body.get("provider") or "openai"
    reference_images = body.get("reference_images") or []
    user_api_key = (body.get("api_key") or "").strip()

    # main.py expects --output <dir>/<name>; we set output to workspaces_root
    # and name to project_id so the final output_dir lines up with workspace.
    # Run main.py as a SCRIPT (not `-m env_generator...`): main.py uses bare
    # top-level imports (`from utils...`, `from multi_agent...`), so it must run
    # with the llm_generator dir as sys.path[0]. Passing the absolute script
    # path makes Python put that dir first on sys.path regardless of cwd.
    python_bin = os.environ.get("ENVGEN_PYTHON") or sys.executable
    main_py = str(Path(__file__).parent / "main.py")
    cmd = [
        python_bin, main_py,
        "--name", project_id,
        "--output", str(workspaces_root),
        "--model", model,
        "--provider", provider,
        "--no-fresh",
    ]
    if body.get("description"):
        cmd += ["--description", str(body["description"])]
    if reference_images:
        cmd += ["--reference-images", *[str(p) for p in reference_images]]
    if body.get("verbose"):
        cmd.append("--verbose")

    # Build the per-run environment. A UI-provided key is injected for this run
    # only and takes precedence over any server env var. It is passed via env
    # (never argv), so it is not stored in the run's recorded command or logged.
    api_key_env = _PROVIDER_API_KEY_ENV.get(provider)
    run_env = {**os.environ}
    if user_api_key and api_key_env:
        run_env[api_key_env] = user_api_key
        if provider == "google":
            run_env["GOOGLE_API_KEY"] = user_api_key
    # Remember the key in RAM (only) so a later "Continue" can resume in place.
    if user_api_key:
        _PROJECT_API_KEYS[project_id] = user_api_key

    # Initial run-budget caps from the start form (the orchestrator writes
    # run_budget.json from these, and re-reads it each tick for live raises).
    # Admins get an unlimited budget (this is a testing tool) — the orchestrator
    # then never aborts on budget regardless of the numeric caps.
    if body.get("_requester_role") == "admin":
        run_env["ENVGEN_BUDGET_UNLIMITED"] = "1"
    try:
        if body.get("max_wall_sec") is not None:
            run_env["ENVGEN_MAX_WALLCLOCK_SEC"] = str(max(60.0, float(body["max_wall_sec"])))
        if body.get("max_ticks") is not None:
            run_env["ENVGEN_MAX_TICKS"] = str(max(1, int(body["max_ticks"])))
    except (TypeError, ValueError):
        pass

    # Validate key availability (UI-provided OR server env) before spawning.
    if api_key_env and not (run_env.get(api_key_env) or run_env.get("GEMINI_API_KEY")):
        return {"error": f"missing API key — enter it in the form or set {api_key_env} on the server"}

    # Register the project metadata (project.json) up-front so the UI can open
    # the project and its hubs immediately — without it, ProjectIndex.get()
    # can't find the project and every hub call 404s with "project not found"
    # until the orchestrator subprocess finishes booting. HubRegistry reuses an
    # existing project.json, so the spawned subprocess won't clobber this.
    try:
        from multi_agent.runtime.hub_registry import HubRegistry
        HubRegistry(
            workspace,
            project_id=project_id,
            project_name=name,
            project_description=(body.get("description") or "").strip(),
        )
    except Exception as e:
        return {"error": f"failed to initialize project workspace: {e}"}

    try:
        log_fh = open(log_path, "ab", buffering=0)
    except Exception as e:
        return {"error": f"could not open log: {e}"}

    try:
        popen = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).parent),  # llm_generator/ (main.py's import root)
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=run_env,
        )
    except Exception as e:
        try:
            log_fh.close()
        except Exception:
            pass
        return {"error": f"subprocess.Popen failed: {e}"}

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    handle = {
        "run_id": run_id,
        "project_id": project_id,
        "started_at": time.time(),
        "command": cmd,
        "log_path": str(log_path),
        "popen": popen,
        "state": "running",
        "returncode": None,
        "workspaces_root": str(workspaces_root),
    }
    with _RUN_REGISTRY_LOCK:
        _RUN_REGISTRY[run_id] = handle

    # Publish lifecycle event so UI updates instantly.
    try:
        _publish_global_event(
            workspaces_root,
            "project_run_started",
            {"run_id": run_id, "name": name, "model": model, "provider": provider},
            project_id=project_id,
        )
    except Exception:
        pass

    # Cutover 38: persist registry so the live monitor can re-attach
    # to this subprocess after a server restart.
    _save_registry(workspaces_root)

    return {
        "run_id": run_id,
        "project_id": project_id,
        "log_path": str(log_path),
    }


def continue_run_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """Resume/continue generation for an EXISTING project, in place.

    Relaunches ``main.py`` with ``--no-fresh`` against the same workspace so all
    prior hub state + git history are preserved and the agents pick up from where
    they left off — no restart from zero. Reuses the prior run's model/provider
    when not supplied; the API key must be re-supplied (it is never stored).
    """
    workspaces_root = Path(workspaces_root)
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None or not workspace.exists():
        return {"error": f"project not found: {project_id}"}

    # Refuse to double-run: if a run for this project is still alive, stop first.
    with _RUN_REGISTRY_LOCK:
        for h in _RUN_REGISTRY.values():
            if h.get("project_id") == project_id and h["popen"].poll() is None:
                return {"error": "a run for this project is already active — stop it before continuing"}
        prior = max(
            (h for h in _RUN_REGISTRY.values()
             if h.get("project_id") == project_id and h.get("command")),
            key=lambda h: h.get("started_at", 0), default=None)

    # Recover model/provider: body wins, else the prior run's command.
    model = (body.get("model") or "").strip()
    provider = (body.get("provider") or "").strip()
    if prior and not (model and provider):
        cmd_prev = prior.get("command") or []
        for i, a in enumerate(cmd_prev):
            if a == "--model" and i + 1 < len(cmd_prev) and not model:
                model = cmd_prev[i + 1]
            if a == "--provider" and i + 1 < len(cmd_prev) and not provider:
                provider = cmd_prev[i + 1]
    model = model or "gpt-4"
    provider = provider or "openai"
    # API key: body wins, else the in-RAM key from the project's last launch.
    user_api_key = (body.get("api_key") or "").strip() or _PROJECT_API_KEYS.get(project_id, "")
    if user_api_key:
        _PROJECT_API_KEYS[project_id] = user_api_key

    python_bin = os.environ.get("ENVGEN_PYTHON") or sys.executable
    main_py = str(Path(__file__).parent / "main.py")
    cmd = [
        python_bin, main_py,
        "--name", project_id,
        "--output", str(workspaces_root),
        "--model", model,
        "--provider", provider,
        "--no-fresh",
    ]
    if body.get("verbose", True):
        cmd.append("--verbose")

    api_key_env = _PROVIDER_API_KEY_ENV.get(provider)
    run_env = {**os.environ}
    if user_api_key and api_key_env:
        run_env[api_key_env] = user_api_key
        if provider == "google":
            run_env["GOOGLE_API_KEY"] = user_api_key
    if body.get("_requester_role") == "admin":
        run_env["ENVGEN_BUDGET_UNLIMITED"] = "1"
    try:
        if body.get("max_wall_sec") is not None:
            run_env["ENVGEN_MAX_WALLCLOCK_SEC"] = str(max(60.0, float(body["max_wall_sec"])))
        if body.get("max_ticks") is not None:
            run_env["ENVGEN_MAX_TICKS"] = str(max(1, int(body["max_ticks"])))
    except (TypeError, ValueError):
        pass

    if api_key_env and not (run_env.get(api_key_env) or run_env.get("GEMINI_API_KEY")):
        return {"error": f"missing API key — provide it to continue, or set {api_key_env} on the server"}

    log_path = workspace / "logs" / "generation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_fh = open(log_path, "ab", buffering=0)
    except Exception as e:
        return {"error": f"could not open log: {e}"}
    try:
        popen = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).parent),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=run_env,
        )
    except Exception as e:
        try:
            log_fh.close()
        except Exception:
            pass
        return {"error": f"subprocess.Popen failed: {e}"}

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    handle = {
        "run_id": run_id,
        "project_id": project_id,
        "started_at": time.time(),
        "command": cmd,
        "log_path": str(log_path),
        "popen": popen,
        "state": "running",
        "returncode": None,
        "workspaces_root": str(workspaces_root),
    }
    with _RUN_REGISTRY_LOCK:
        _RUN_REGISTRY[run_id] = handle
    try:
        _publish_global_event(
            workspaces_root, "project_run_started",
            {"run_id": run_id, "name": project_id, "model": model, "provider": provider, "continued": True},
            project_id=project_id,
        )
    except Exception:
        pass
    _save_registry(workspaces_root)
    return {"run_id": run_id, "project_id": project_id, "log_path": str(log_path), "continued": True}


def get_run_status(run_id: str) -> dict:
    with _RUN_REGISTRY_LOCK:
        handle = _RUN_REGISTRY.get(run_id)
    if handle is None:
        return {"error": f"run not found: {run_id}"}
    popen = handle["popen"]
    rc = popen.poll() if popen is not None else None
    if rc is not None and handle["state"] == "running":
        handle["state"] = "completed" if rc == 0 else "failed"
        handle["returncode"] = rc
        # Cutover 38: persist state transition.
        ws = handle.get("workspaces_root")
        if ws:
            _save_registry(Path(ws))
    payload = {
        "run_id": handle["run_id"],
        "project_id": handle["project_id"],
        "state": handle["state"],
        "returncode": handle.get("returncode"),
        "started_at": handle["started_at"],
        "log_path": handle["log_path"],
    }
    # Tail the log (last ~4KB) for quick UI feedback.
    try:
        log_path = Path(handle["log_path"])
        if log_path.exists():
            with log_path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                tail = 4096
                f.seek(max(0, size - tail), 0)
                payload["log_tail"] = f.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return payload


def stop_run_call(run_id: str, body: dict) -> dict:
    if not body.get("confirm"):
        return {"error": "stop requires body confirm=true"}
    with _RUN_REGISTRY_LOCK:
        handle = _RUN_REGISTRY.get(run_id)
    if handle is None:
        return {"error": f"run not found: {run_id}"}
    popen = handle["popen"]
    if popen.poll() is not None:
        return {"ok": True, "already_finished": True}
    try:
        popen.terminate()
        # Wait briefly; if still alive, hard kill.
        for _ in range(50):  # 5s total
            if popen.poll() is not None:
                break
            time.sleep(0.1)
        if popen.poll() is None:
            popen.kill()
        handle["state"] = "stopped"
        handle["returncode"] = popen.poll()
        # Cutover 38: persist state transition.
        ws = handle.get("workspaces_root")
        if ws:
            _save_registry(Path(ws))
        return {"ok": True}
    except Exception as e:
        return {"error": f"stop failed: {e}"}


def list_runs() -> list:
    with _RUN_REGISTRY_LOCK:
        out = []
        for handle in _RUN_REGISTRY.values():
            popen = handle["popen"]
            rc = popen.poll()
            if rc is not None and handle["state"] == "running":
                handle["state"] = "completed" if rc == 0 else "failed"
                handle["returncode"] = rc
            out.append({
                "run_id": handle["run_id"],
                "project_id": handle["project_id"],
                "state": handle["state"],
                "returncode": handle.get("returncode"),
                "started_at": handle["started_at"],
                "log_path": handle["log_path"],
            })
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Cutover 39: User-defined deliverability gates
# ---------------------------------------------------------------------------

def _user_gates_file(workspace: Path) -> Path:
    return Path(workspace) / ".user_gates.json"


def _load_user_gates(workspace: Path) -> list:
    p = _user_gates_file(workspace)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _save_user_gates(workspace: Path, gates: list) -> None:
    p = _user_gates_file(workspace)
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(gates, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def list_user_gates_call(workspaces_root: Path, project_id: str) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    from multi_agent.runtime.user_gates import evaluate_gate
    gates = _load_user_gates(workspace)
    out = []
    for g in gates:
        status = evaluate_gate(g, reg, workspace)
        out.append({**g, "status": status})
    return {"gates": out}


def create_user_gate_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    from multi_agent.runtime.user_gates import validate_gate
    err_msg = validate_gate(body or {})
    if err_msg:
        return {"error": err_msg}
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    now = time.time()
    new_gate = {
        "id": f"gate_{uuid.uuid4().hex[:10]}",
        "name": body.get("name", ""),
        "type": body.get("type"),
        "params": body.get("params") or {},
        "created_at": now,
        "_updated_at": now,
        "created_by": body.get("agent") or "",
    }
    gates.append(new_gate)
    _save_user_gates(workspace, gates)
    return new_gate


def update_user_gate_call(workspaces_root: Path, project_id: str,
                          gate_id: str, body: dict) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    found = False
    for g in gates:
        if g.get("id") == gate_id:
            if "name" in body:
                g["name"] = body["name"]
            if "params" in body:
                g["params"] = body["params"] or {}
            g["_updated_at"] = time.time()
            from multi_agent.runtime.user_gates import validate_gate
            err = validate_gate(g)
            if err:
                return {"error": err}
            found = True
            break
    if not found:
        return {"error": f"gate not found: {gate_id}"}
    _save_user_gates(workspace, gates)
    return {"ok": True, "gate_id": gate_id}


def delete_user_gate_call(workspaces_root: Path, project_id: str, gate_id: str) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    new_gates = [g for g in gates if g.get("id") != gate_id]
    if len(new_gates) == len(gates):
        return {"error": f"gate not found: {gate_id}"}
    _save_user_gates(workspace, new_gates)
    return {"ok": True}


def evaluate_user_gate_call(workspaces_root: Path, project_id: str, gate_id: str) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    target = next((g for g in gates if g.get("id") == gate_id), None)
    if not target:
        return {"error": f"gate not found: {gate_id}"}
    from multi_agent.runtime.user_gates import evaluate_gate
    return evaluate_gate(target, reg, workspace)


# ---------------------------------------------------------------------------
# Cutover 40: Reference materials
# ---------------------------------------------------------------------------

_REFERENCE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_REFERENCE_CATEGORY = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image", ".svg": "image",
    ".py": "python",
    ".yaml": "spec", ".yml": "spec", ".json": "spec",
    ".md": "doc", ".txt": "doc", ".rst": "doc",
    ".csv": "data", ".tsv": "data", ".jsonl": "data", ".ndjson": "data",
}


def _references_dir(workspace: Path) -> Path:
    return Path(workspace) / "references"


def _categorize_file(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _REFERENCE_CATEGORY.get(ext, "other")


def _safe_reference_path(workspace: Path, filename: str) -> Optional[Path]:
    """Return absolute path inside <workspace>/references/, or None if unsafe."""
    name = (filename or "").strip()
    if not name:
        return None
    # Reject any path separators or parent-directory components
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    if ".." in Path(name).parts:
        return None
    refs_dir = _references_dir(workspace)
    target = refs_dir / name
    try:
        # Resolve without requiring the file to exist; resolve the parent
        # which we control, then append the name.
        refs_resolved = refs_dir.resolve()
        target_resolved = (refs_resolved / name).resolve()
        target_resolved.relative_to(refs_resolved)
    except Exception:
        return None
    return target


def _file_preview(path: Path, max_chars: int = 400) -> Optional[str]:
    """Return a short text preview for non-binary files."""
    try:
        if not path.exists() or path.stat().st_size > 1024 * 1024:
            return None
        # Heuristic: skip binary
        with path.open("rb") as f:
            head = f.read(2048)
        if b"\0" in head:
            return None
        try:
            text = head.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text = head.decode("utf-8", errors="replace")
        return text[:max_chars]
    except Exception:
        return None


def _regenerate_references_index(workspace: Path) -> None:
    refs_dir = _references_dir(workspace)
    refs_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for child in refs_dir.iterdir():
        if not child.is_file() or child.name == "INDEX.md":
            continue
        files.append(child)
    files.sort(key=lambda p: p.name)
    lines = [
        "# References Index",
        "",
        "Files in this directory are reference materials provided by the operator.",
        "Agents should read this index to discover available references and consult",
        "the matching file when their task aligns with the reference content.",
        "",
        "| File | Category | Size |",
        "|------|----------|------|",
    ]
    for p in files:
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        lines.append(f"| `{p.name}` | {_categorize_file(p.name)} | {size}B |")
    if not files:
        lines.append("| _(no references yet)_ | | |")
    (refs_dir / "INDEX.md").write_text("\n".join(lines) + "\n")


def list_references_call(workspaces_root: Path, project_id: str) -> dict:
    """List reference materials.

    Returns the UNION of two stores so we never need to duplicate files on disk:
    - ``references/`` — user-uploaded references via the UI.
    - ``screenshots/`` — references the orchestrator copied from CLI/--reference-images.
    Deduped by filename (uploads win on collision).
    """
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    seen: dict[str, dict] = {}
    for d in (_references_dir(workspace), workspace / "screenshots"):
        if not d.exists():
            continue
        for child in sorted(d.iterdir(), key=lambda p: p.name):
            if not child.is_file() or child.name == "INDEX.md":
                continue
            if child.name in seen:
                continue
            try:
                stat = child.stat()
            except Exception:
                continue
            seen[child.name] = {
                "name": child.name,
                "category": _categorize_file(child.name),
                "size": stat.st_size,
                "uploaded_at": stat.st_mtime,
                "preview": _file_preview(child),
            }
    return {"files": list(seen.values())}


def upload_reference_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    import base64 as _b64
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    filename = (body.get("filename") or "").strip()
    target = _safe_reference_path(workspace, filename)
    if target is None:
        return {"error": f"invalid filename: {filename!r}"}
    content_b64 = body.get("content_base64") or ""
    if not content_b64:
        return {"error": "content_base64 required"}
    try:
        raw = _b64.b64decode(content_b64, validate=True)
    except Exception as e:
        return {"error": f"invalid base64: {e}"}
    if len(raw) > _REFERENCE_MAX_BYTES:
        return {"error": f"file size {len(raw)} exceeds cap {_REFERENCE_MAX_BYTES}"}
    refs_dir = _references_dir(workspace)
    refs_dir.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(raw)
    except Exception as e:
        return {"error": f"write failed: {e}"}
    _regenerate_references_index(workspace)
    return {
        "name": target.name,
        "category": _categorize_file(target.name),
        "size": len(raw),
    }


def delete_reference_call(workspaces_root: Path, project_id: str, filename: str) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    target = _safe_reference_path(workspace, filename)
    if target is None or not target.exists():
        return {"error": f"file not found: {filename}"}
    try:
        target.unlink()
    except Exception as e:
        return {"error": f"unlink failed: {e}"}
    _regenerate_references_index(workspace)
    return {"ok": True, "deleted": filename}


# ============================================================================
# Cutover 43.11: Code browser endpoints (GitHub-style repository view)
# ============================================================================

_CODE_HIDE_DIRS = {"shared", "logs", ".git", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".tmp", "worktrees"}
_CODE_HIDE_FILES = {"project.json", ".user_gates.json", ".runs.json", ".DS_Store", ".gitignore", "run_budget.json", ".checkpoint", ".checkpoint.bak"}

# Pseudo-branch shown as the default in the code browser: read the live
# working tree on disk (where agents actually write files) rather than a
# committed git tree. Generated code is usually uncommitted, so without this
# the browser looks empty even though the files exist.
WORKING_TREE_REF = "(working tree)"
_CODE_FILE_MAX_BYTES = 512 * 1024  # 512 KB cap for direct viewer


def _safe_workspace_path(workspace: Path, rel_path: str) -> Optional[Path]:
    """Resolve `rel_path` inside `workspace` safely, rejecting traversal."""
    rel = (rel_path or "").strip().lstrip("/").lstrip("\\")
    if rel == "":
        return workspace
    if ".." in Path(rel).parts:
        return None
    target = workspace / rel
    try:
        resolved = target.resolve()
        ws_resolved = workspace.resolve()
        resolved.relative_to(ws_resolved)
    except Exception:
        return None
    return target


# --- Cutover 43.19: branch-aware code reading via real git -------------------
# In the real env-gen, CodeHub's repo_root IS the workspace dir, with a git repo
# and per-agent worktrees on `agent/<id>` branches. So we can read any branch's
# files with `git ls-tree`/`git show`. When a workspace has no .git (e.g. a flat
# seeded demo), we fall back to the working-tree-on-disk behavior.

def _workspace_has_git(workspace: Path) -> bool:
    return (workspace / ".git").exists()


def _git_run(workspace: Path, *args: str) -> "subprocess.CompletedProcess":
    import subprocess
    return subprocess.run(
        ["git", *args], cwd=str(workspace),
        capture_output=True, text=True, timeout=15,
    )


def _git_safe_rel(rel_path: str) -> Optional[str]:
    """Normalize a repo-relative path, rejecting traversal. '' = repo root."""
    rel = (rel_path or "").strip().lstrip("/").lstrip("\\")
    if rel == "":
        return ""
    if ".." in Path(rel).parts:
        return None
    return rel.replace("\\", "/")


def _git_list_branches(workspace: Path) -> tuple[list[str], Optional[str]]:
    """Return (branch_names, default_branch). Worktree branches included."""
    res = _git_run(workspace, "branch", "--format=%(refname:short)")
    if res.returncode != 0:
        return [], None
    branches = [b.strip() for b in res.stdout.splitlines() if b.strip()]
    # Default branch = the branch with the MOST RECENT commit (where the live
    # code actually is). Early in a run the integration branch (main/master) is
    # near-empty while agents commit on `agent/<id>` branches, so a static
    # main/master default makes the code view look empty. Ranking by commit date
    # auto-surfaces work-in-progress; once work merges to main/master that
    # becomes newest and wins again. main/master only acts as a tie-break.
    default = None
    ranked_res = _git_run(workspace, "for-each-ref", "--sort=-committerdate",
                          "--format=%(refname:short)", "refs/heads/")
    if ranked_res.returncode == 0:
        ranked = [b.strip() for b in ranked_res.stdout.splitlines() if b.strip()]
        if ranked:
            top_date = _git_run(workspace, "log", "-1", "--format=%ct", ranked[0])
            # If main/master shares the newest commit timestamp, prefer it.
            for cand in ("main", "master"):
                if cand in ranked:
                    cand_date = _git_run(workspace, "log", "-1", "--format=%ct", cand)
                    if (cand_date.returncode == 0 and top_date.returncode == 0
                            and cand_date.stdout.strip() == top_date.stdout.strip()):
                        default = cand
                        break
            if default is None:
                default = ranked[0]
    if default is None:
        for cand in ("main", "master"):
            if cand in branches:
                default = cand
                break
    if default is None:
        head = _git_run(workspace, "rev-parse", "--abbrev-ref", "HEAD")
        if head.returncode == 0 and head.stdout.strip() and head.stdout.strip() != "HEAD":
            default = head.stdout.strip()
        elif branches:
            default = branches[0]
    return branches, default


def _git_ls_tree(workspace: Path, branch: str, rel: str) -> Optional[list[dict]]:
    """List entries of `rel` dir at `branch`. Returns None on git error."""
    spec = f"{branch}:{rel}" if rel else branch
    res = _git_run(workspace, "ls-tree", "-l", "--", spec) if False else \
          _git_run(workspace, "ls-tree", "-l", spec)
    if res.returncode != 0:
        return None
    entries: list[dict] = []
    for line in res.stdout.splitlines():
        # format: <mode> <type> <sha>\t<name>  (with -l: <mode> <type> <sha> <size>\t<name>)
        if "\t" not in line:
            continue
        meta, name = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 3:
            continue
        gtype = parts[1]  # blob | tree | commit
        size = 0
        if gtype == "blob" and len(parts) >= 4 and parts[3].isdigit():
            size = int(parts[3])
        name = name.strip()
        if gtype == "tree":
            if name in _CODE_HIDE_DIRS:
                continue
            entries.append({"name": name, "type": "dir", "size": 0, "mtime": None})
        elif gtype == "blob":
            if name in _CODE_HIDE_FILES:
                continue
            entries.append({"name": name, "type": "file", "size": size, "mtime": None})
        # 'commit' entries are submodules — skip
    return entries


def _git_show_file(workspace: Path, branch: str, rel: str) -> Optional[bytes]:
    """Return raw bytes of file `rel` at `branch`, or None if not found/err."""
    import subprocess
    try:
        res = subprocess.run(
            ["git", "show", f"{branch}:{rel}"], cwd=str(workspace),
            capture_output=True, timeout=15,
        )
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def _git_list_all_files(workspace: Path, branch: str) -> Optional[list[dict]]:
    """Flat list of files at `branch` via `git ls-tree -r`. None on error."""
    res = _git_run(workspace, "ls-tree", "-r", "-l", branch)
    if res.returncode != 0:
        return None
    files: list[dict] = []
    for line in res.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        size = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
        path = path.strip()
        base = path.split("/")[-1]
        top = path.split("/")[0]
        if base in _CODE_HIDE_FILES or top in _CODE_HIDE_DIRS:
            continue
        files.append({"path": path, "size": size, "mtime": None})
    return files


def list_code_branches_call(workspaces_root: Path, project_id: str) -> dict:
    """List git branches for the Code-tab branch selector. Empty when the
    workspace isn't a git repo (flat working-tree mode)."""
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    if not _workspace_has_git(workspace):
        return {"branches": [], "default": None, "git": False}
    branches, _default = _git_list_branches(workspace)
    # Surface the live working tree as the default view (that's where agents'
    # generated, usually-uncommitted code lives); list git branches after it
    # for inspecting committed history.
    return {
        "branches": [WORKING_TREE_REF] + branches,
        "default": WORKING_TREE_REF,
        "working_tree_ref": WORKING_TREE_REF,
        "git": True,
    }


def list_code_tree_call(workspaces_root: Path, project_id: str, rel_path: str, branch: Optional[str] = None) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    rel_norm = (rel_path or "").strip("/")

    # --- git-backed read at a specific branch ---
    if branch and branch != WORKING_TREE_REF and _workspace_has_git(workspace):
        safe = _git_safe_rel(rel_path)
        if safe is None:
            return {"error": "invalid path", "path": rel_norm, "entries": []}
        entries = _git_ls_tree(workspace, branch, safe)
        # Only use the git result when it has content; an empty tree (common
        # mid-run, when files are written but not yet committed) falls through
        # to the live working tree below so the user still sees the code.
        if entries:
            entries.sort(key=lambda e: (e["type"] == "file", e["name"].lower()))
            return {
                "path": rel_norm,
                "parent_path": "/".join(rel_norm.split("/")[:-1]) if rel_norm else None,
                "branch": branch,
                "entries": entries,
            }

    # --- working-tree-on-disk view (default) ---
    target = _safe_workspace_path(workspace, rel_path)
    if target is None or not target.exists():
        return {"error": f"path not found: {rel_path}", "path": rel_path, "entries": []}
    if not target.is_dir():
        return {"error": f"not a directory: {rel_path}", "path": rel_path, "entries": []}
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            name = child.name
            # Hide noise
            if child.is_dir() and name in _CODE_HIDE_DIRS:
                continue
            if child.is_file() and name in _CODE_HIDE_FILES:
                continue
            try:
                stat = child.stat()
            except Exception:
                continue
            entries.append({
                "name": name,
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size if child.is_file() else 0,
                "mtime": stat.st_mtime,
            })
    except PermissionError:
        return {"error": "permission denied", "path": rel_path, "entries": []}
    return {
        "path": rel_norm,
        "parent_path": "/".join(rel_norm.split("/")[:-1]) if rel_norm else None,
        "entries": entries,
    }


def list_code_files_call(workspaces_root: Path, project_id: str, branch: Optional[str] = None) -> dict:
    """Flat list of every visible file path in the workspace, for
    'Go to file' fuzzy search. Returns just paths + sizes — no contents."""
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}

    # --- git-backed flat list at a branch (only if it has committed files) ---
    if branch and branch != WORKING_TREE_REF and _workspace_has_git(workspace):
        gfiles = _git_list_all_files(workspace, branch)
        if gfiles:
            return {"files": gfiles[:5000], "truncated": len(gfiles) > 5000, "branch": branch}

    files: list[dict] = []
    # Cap total entries so a giant repo can't blow up the response.
    MAX_FILES = 5000
    def walk(d: Path, rel_prefix: str) -> None:
        if len(files) >= MAX_FILES:
            return
        try:
            children = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except (PermissionError, OSError):
            return
        for child in children:
            if len(files) >= MAX_FILES:
                return
            name = child.name
            if child.is_dir():
                if name in _CODE_HIDE_DIRS:
                    continue
                sub_rel = f"{rel_prefix}{name}/"
                walk(child, sub_rel)
            elif child.is_file():
                if name in _CODE_HIDE_FILES:
                    continue
                try:
                    stat = child.stat()
                except Exception:
                    continue
                files.append({
                    "path": f"{rel_prefix}{name}",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
    walk(workspace, "")
    return {"files": files, "truncated": len(files) >= MAX_FILES}


def read_code_file_call(workspaces_root: Path, project_id: str, rel_path: str, branch: Optional[str] = None) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}

    # --- git-backed read at a specific branch (fall back to disk if absent) ---
    if branch and branch != WORKING_TREE_REF and _workspace_has_git(workspace):
        safe = _git_safe_rel(rel_path)
        if not safe:
            return {"error": f"invalid path: {rel_path}"}
        raw = _git_show_file(workspace, branch, safe)
        if raw is not None:
            size = len(raw)
            if size > _CODE_FILE_MAX_BYTES:
                return {"error": f"file too large ({size} > {_CODE_FILE_MAX_BYTES} bytes)", "size": size, "binary": False}
            if b"\x00" in raw[:2048]:
                return {"path": safe, "size": size, "binary": True, "content": None, "branch": branch}
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            return {"path": safe, "size": size, "lines": text.count("\n") + 1, "binary": False, "content": text, "branch": branch}
        # not committed on this branch -> fall through to the live working tree

    # --- working-tree-on-disk view (default) ---
    target = _safe_workspace_path(workspace, rel_path)
    if target is None or not target.exists():
        return {"error": f"file not found: {rel_path}"}
    if target.is_dir():
        return {"error": f"is a directory, not a file: {rel_path}"}
    try:
        size = target.stat().st_size
    except Exception as e:
        return {"error": f"stat failed: {e}"}
    if size > _CODE_FILE_MAX_BYTES:
        return {"error": f"file too large ({size} > {_CODE_FILE_MAX_BYTES} bytes)", "size": size, "binary": False}
    try:
        raw = target.read_bytes()
    except Exception as e:
        return {"error": f"read failed: {e}"}
    if b"\x00" in raw[:2048]:
        return {"path": rel_path.strip("/"), "size": size, "binary": True, "content": None}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return {
        "path": rel_path.strip("/"),
        "size": size,
        "lines": text.count("\n") + 1,
        "binary": False,
        "content": text,
    }


# ---- Run budget (orchestrator writes run_budget.json; UI reads/raises caps) ----
_RUN_BUDGET_DEFAULTS = {"max_wall_sec": 7200.0, "max_ticks": 240}


def run_budget_call(workspaces_root: Path, project_id: str) -> dict:
    """Return the project's run-budget caps + usage (defaults if no run yet)."""
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    path = workspace / "run_budget.json"
    if not path.exists():
        return {
            "caps": dict(_RUN_BUDGET_DEFAULTS),
            "usage": {"elapsed_sec": 0, "ticks": 0, "status": "idle", "started_at": None, "updated_at": None},
            "present": False,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["present"] = True
        return data
    except Exception as e:
        return {"error": f"could not read run_budget.json: {e}"}


def update_run_budget_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """Raise/adjust the run-budget caps. The running orchestrator re-reads each tick."""
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    path = workspace / "run_budget.json"
    try:
        cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        cur = {}
    caps = dict(cur.get("caps") or _RUN_BUDGET_DEFAULTS)
    if body.get("max_wall_sec") is not None:
        try:
            caps["max_wall_sec"] = max(60.0, float(body["max_wall_sec"]))
        except (TypeError, ValueError):
            return {"error": "max_wall_sec must be a number (seconds)"}
    if body.get("max_ticks") is not None:
        try:
            caps["max_ticks"] = max(1, int(body["max_ticks"]))
        except (TypeError, ValueError):
            return {"error": "max_ticks must be an integer"}
    # Only admins may toggle the unlimited (no-ceiling) budget.
    if body.get("unlimited") is not None:
        if body.get("_requester_role") != "admin":
            return {"error": "only admins can set an unlimited budget"}
        caps["unlimited"] = bool(body["unlimited"])
    cur["caps"] = caps
    cur.setdefault("usage", {"elapsed_sec": 0, "ticks": 0, "status": "idle", "started_at": None, "updated_at": None})
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        return {"error": f"could not write run_budget.json: {e}"}
    return {"ok": True, "caps": caps, "usage": cur.get("usage", {}), "present": True}


def _session_start_ts_for_project(workspace: Path) -> float:
    """Read the orchestrator's session-start timestamp from
    ``<workspace>/run_budget.json::usage.started_at``.

    Reviewer follow-up (2026-05-30): both ``compute_deliverability``
    call sites in the UI deliver path used to pass
    ``session_start_ts=0.0``, which made
    ``runhub.last_successful_run_since(0.0)`` equivalent to "any
    successful run EVER" — so on ``--no-fresh`` workspaces a stale
    historical run could fool the UI into marking the project
    complete (same family as the retro-gate generation-scoping bug
    we fixed three rounds ago, just on the UI path).

    The orchestrator writes ``run_budget.json`` at the top of
    ``run()`` with ``usage.started_at = loop_start`` and updates
    it each tick. Reading it here gives the UI a "this session"
    floor without depending on in-process state. Fallback to 0.0
    (preserve historical behaviour) when:
      * the file doesn't exist (no orchestrator has started yet —
        in which case any successful run can only have come from
        a prior session, but that's true with 0.0 too)
      * the file is malformed
      * ``started_at`` is missing / not a number

    All three fallbacks degrade to the OLD any-historical
    behaviour, so this change can't make any currently-passing
    deliver fail; it only fixes the over-permissive case."""
    path = workspace / "run_budget.json"
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    started_at = ((data or {}).get("usage") or {}).get("started_at")
    if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
        return 0.0
    return float(started_at)


def deliverability_report_call(workspaces_root: Path, project_id: str) -> dict:
    """Read-only deliverability report (no delivery side effects). Cutover 43.27.
    Computes system blockers + appends user-gate failures."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    try:
        from multi_agent.runtime.deliverability import compute_deliverability
        report = compute_deliverability(
            reg, workspace,
            session_start_ts=_session_start_ts_for_project(workspace),
        )
    except Exception as e:
        return {"error": f"compute_deliverability failed: {e}"}
    report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    try:
        from multi_agent.runtime.user_gates import evaluate_gate
        gates = _load_user_gates(workspace)
        gate_results = []
        user_gate_blockers = []
        for g in gates:
            status = evaluate_gate(g, reg, workspace)
            gate_results.append({**g, "status": status})
            if not status.get("passed"):
                user_gate_blockers.append(f"user_gate:{g.get('name', g.get('id'))}: {status.get('message', 'failed')}")
        report_dict["user_gates"] = gate_results
        if user_gate_blockers:
            existing = list(report_dict.get("blockers", []) or [])
            existing.extend(user_gate_blockers)
            report_dict["blockers"] = existing
            verdict = (report_dict.get("verdict") or "").lower()
            if verdict in ("ready", "deliverable"):
                report_dict["verdict"] = "blocked"
    except Exception:
        pass
    return report_dict


def deliver_project_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """Run ``compute_deliverability`` and, if verdict=ready, mark project completed.

    Body fields:
      - ``force_deliver`` (bool): bypass the gate (DESTRUCTIVE; audited).
      - ``agent`` (str): who is invoking (default ``ui_user``).
      - ``reason`` (str): required if ``force_deliver`` is True (>=5 chars).
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err

    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}

    try:
        from multi_agent.runtime.deliverability import compute_deliverability
    except Exception as e:
        return {"error": f"could not import deliverability module: {e}"}

    try:
        report = compute_deliverability(
            reg, workspace,
            session_start_ts=_session_start_ts_for_project(workspace),
        )
    except Exception as e:
        return {"error": f"compute_deliverability failed: {e}"}

    report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report)

    # Cutover 39: append user-gate failures to the blockers list and flip
    # verdict to "blocked" if any user gate fails.
    try:
        from multi_agent.runtime.user_gates import evaluate_gate
        gates = _load_user_gates(workspace)
        user_gate_blockers = []
        for g in gates:
            status = evaluate_gate(g, reg, workspace)
            if not status.get("passed"):
                user_gate_blockers.append(
                    f"user_gate:{g.get('name', g.get('id'))}: "
                    f"{status.get('message', 'failed')}"
                )
        if user_gate_blockers:
            existing = list(report_dict.get("blockers", []) or [])
            existing.extend(user_gate_blockers)
            report_dict["blockers"] = existing
            # Flip verdict from a "ready"-style state to blocked.
            verdict = (report_dict.get("verdict") or "").lower()
            if verdict in ("ready", "deliverable"):
                report_dict["verdict"] = "blocked"
    except Exception:
        # User-gate failure must never crash deliverability; on error
        # fall through with the underlying report unchanged.
        pass

    force = bool(body.get("force_deliver"))
    agent = (body.get("agent") or "").strip()
    reason = (body.get("reason") or "").strip()

    if force:
        if not reason or len(reason) < 5:
            return {"error": "force_deliver requires reason (>=5 chars)", "report": report_dict}
        # Audit: publish a force_deliver event so the override is traceable.
        try:
            reg.eventhub.publish_event(
                source_hub="ui",
                event_type="deliverability_bypass",
                payload={"agent": agent, "reason": reason, "blockers": report_dict.get("blockers", [])},
                recipients=[],
                priority="high",
            )
        except Exception:
            pass
        try:
            reg.set_project_status("completed")
        except Exception as e:
            return {"error": f"set_project_status failed: {e}", "report": report_dict}
        return {"ok": True, "delivered": True, "forced": True, "report": report_dict}

    verdict = (report_dict.get("verdict") or "").lower()
    if verdict in ("ready", "deliverable"):
        try:
            reg.set_project_status("completed")
        except Exception as e:
            return {"error": f"set_project_status failed: {e}", "report": report_dict}
        return {"ok": True, "delivered": True, "forced": False, "report": report_dict}

    # Blocked path
    return {"ok": False, "delivered": False, "report": report_dict}


_WORKHUB_VALID_PRIORITIES = ("P0", "P1", "P2", "P3")


def workhub_create_task_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks — create a WorkHub task."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    title = (body.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}
    return reg.workhub.create_task(
        title=title,
        description=body.get("description") or "",
        assignee=body.get("assignee") or None,
        plan_id=body.get("plan_id") or None,
        depends_on=body.get("depends_on") or [],
        agent=body.get("agent") or "",
        priority=body.get("priority") or "P2",
    )


def workhub_set_priority_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks/<task_id>/priority — update task priority.

    Mutates task metadata.priority in place via the task store; WorkHub does
    not expose a dedicated setter (Cutover 23 created priorities at task-create
    time only).
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    priority = body.get("priority") or ""
    if priority not in _WORKHUB_VALID_PRIORITIES:
        return {"error": f"priority must be one of {_WORKHUB_VALID_PRIORITIES}"}
    task = reg.workhub.get_task(task_id)
    if not task:
        return {"error": f"task not found: {task_id}"}
    updated = dict(task)
    md = dict(updated.get("metadata") or {})
    md["priority"] = priority
    updated["metadata"] = md
    actor = body.get("agent") or ""
    reg.workhub.stores.tasks.update(
        lambda m: m.set(task_id, updated, actor),
        change_info={"agent": actor},
    )
    return updated


def workhub_create_document_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/pages — create a WorkHub coordination document."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    title = (body.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}
    return reg.workhub.create_document(
        title=title,
        kind=body.get("kind") or "general",
        attendees=body.get("attendees") or [],
        agent=body.get("agent") or "",
    )


def workhub_append_block_call(workspaces_root: Path, project_id: str, page_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/pages/<page_id>/blocks — append a block."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    block = {
        "type": (body.get("type") or "text").strip(),
        "content": body.get("content") or "",
        "metadata": body.get("metadata") or {},
    }
    if "id" in body:
        block["id"] = body["id"]
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.append_block(page_id=page_id, block=block, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_update_block_call(workspaces_root: Path, project_id: str, block_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/blocks/<block_id> — replace a block's content."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    if "content" not in body:
        return {"error": "content required"}
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.update_block(block_id=block_id, content=body["content"], agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_insert_block_after_call(workspaces_root: Path, project_id: str, page_id: str,
                                    after_block_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/pages/<page_id>/blocks/<after_id>/after — insert a block."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    block = {
        "type": (body.get("type") or "text").strip(),
        "content": body.get("content") or "",
        "metadata": body.get("metadata") or {},
    }
    if "id" in body:
        block["id"] = body["id"]
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.insert_block_after(
            page_id=page_id,
            after_block_id=after_block_id,
            block=block,
            agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


def workhub_submit_visual_review_call(workspaces_root: Path, project_id: str, page_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/pages/<page_id>/visual_review — submit a visual review."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    # Phase 4.5: same fallthrough-fix as design review HTTP shim above.
    return reg.gate_registry.submit_visual_review(
        page_id=page_id,
        reviewer=body.get("reviewer") or "",
        state=body.get("state") or "",
        similarity_score=body.get("similarity_score"),
        deviations=body.get("deviations") or [],
        summary=body.get("summary") or "",
    )


def workhub_mark_intentionally_dead_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/coverage_allowlist — DESTRUCTIVE: bypass dead-code gate."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    path = (body.get("path") or "").strip()
    reason = (body.get("reason") or "").strip()
    if not path or not reason:
        return {"error": "path and reason are required"}
    # Phase 4.5d shim flip: "ui_user" → "" so the gate gets
    # empty-actor fallthrough rather than a phantom rejection.
    return reg.gate_registry.mark_path_intentionally_dead(
        path=path,
        reason=reason,
        agent=body.get("agent") or "",
    )


# --- Cutover 33 Task 2: WorkHub task lifecycle (claim/complete/fail/cancel) ---


def workhub_claim_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks/<task_id>/claim — claim a pending task."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    agent = (body.get("agent") or "").strip()
    if not agent:
        return {"error": "agent required"}
    try:
        return reg.workhub.claim_task(task_id=task_id, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def workhub_complete_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks/<task_id>/complete — complete an in-progress task."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.complete_task(
            task_id=task_id,
            agent=agent,
            result=body.get("result") or {},
            evidence=body.get("evidence") or {},
        )
    except Exception as e:
        return {"error": str(e)}


def workhub_fail_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks/<task_id>/fail — mark task failed with reason."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        return {"error": "reason must be at least 5 characters"}
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.fail_task(task_id=task_id, agent=agent, reason=reason)
    except Exception as e:
        return {"error": str(e)}


def workhub_cancel_task_call(workspaces_root: Path, project_id: str, task_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/tasks/<task_id>/cancel — cancel a non-terminal task."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    agent = (body.get("agent") or "").strip()
    reason = (body.get("reason") or "").strip() or \
        "cancelled via live monitor (human operator)"
    try:
        return reg.workhub.cancel_task(task_id=task_id, agent=agent, reason=reason)
    except Exception as e:
        return {"error": str(e)}


# --- Cutover 33 Task 3: WorkHub comments + decisions + plans ----------------


def workhub_comment_call(workspaces_root: Path, project_id: str, resource_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/comments/<resource_id> — add a comment to any resource."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    text = (body.get("body") or "").strip()
    if len(text) < 3:
        return {"error": "comment body must be at least 3 characters"}
    agent = (body.get("agent") or "").strip()
    mentions = body.get("mentions") or []
    try:
        return reg.workhub.comment(
            resource_id=resource_id, body=text, agent=agent, mentions=mentions,
        )
    except Exception as e:
        return {"error": str(e)}


def workhub_record_decision_call(workspaces_root: Path, project_id: str, page_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/workhub/pages/<page_id>/decisions — record a decision on a page."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    title = (body.get("title") or "").strip()
    chosen = (body.get("chosen") or "").strip()
    reason = (body.get("reason") or "").strip()
    options = body.get("options") or []
    if not title or not chosen or not reason or not options:
        return {"error": "title, options, chosen, reason all required"}
    agent = (body.get("agent") or "").strip()
    try:
        return reg.workhub.record_decision(
            document_id=page_id, title=title, options=options,
            chosen=chosen, reason=reason, agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


# --- CodeHub operation endpoints --------------------------------------------


def codehub_open_pr_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/codehub/pull_requests — open a pull request."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    branch = (body.get("branch") or "").strip()
    if not branch:
        return {"error": "branch is required"}
    # HTTP shim: pass author through verbatim. Empty author falls
    # through the codehub authorship gates (system / HTTP paths).
    return reg.codehub.open_pull_request(
        branch=branch,
        target=body.get("target") or "main",
        reviewers=body.get("reviewers") or [],
        linked_tasks=body.get("linked_tasks") or [],
        linked_apis=body.get("linked_apis") or [],
        linked_pages=body.get("linked_pages") or [],
        linked_consumers=body.get("linked_consumers") or [],
        title=body.get("title") or "",
        author=body.get("author") or "",
    )


def codehub_submit_review_call(workspaces_root: Path, project_id: str, pr_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/codehub/pull_requests/<pr_id>/reviews — submit a review.

    Cutover 33: accepts ``comments`` (list of strings or {body: ...} dicts) and
    ``inline_comments`` (list of {file, line, body}) from the request body.
    For ``approve``/``request_changes`` states the ``reason`` must be >=20 chars.
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    # Phase 4.6 review-verdict authorship lock: default reviewer to ""
    # so the empty-actor fallthrough handles UI calls without surfacing
    # the phantom "ui_user" default. Mirrors the Phase 4.5 shim flip.
    reviewer = (body.get("reviewer") or "").strip()
    state = (body.get("state") or "comment").strip()
    reason = (body.get("reason") or "").strip()
    inline_comments = body.get("inline_comments") or []
    comments = body.get("comments") or []
    considered_alternatives = body.get("considered_alternatives") or []
    if state in {"request_changes", "approve"} and len(reason) < 20:
        return {"error": "reason must be >=20 chars for request_changes/approve"}
    # Normalize "comments": accept simple [{body}] strings/dicts.
    norm_comments: list = []
    for c in comments:
        if isinstance(c, str) and c.strip():
            norm_comments.append({"body": c.strip()})
        elif isinstance(c, dict) and (c.get("body") or "").strip():
            norm_comments.append(c)
    try:
        return reg.codehub.submit_review(
            pr_id=pr_id,
            reviewer=reviewer,
            state=state,
            comments=norm_comments,
            inline_comments=inline_comments,
            considered_alternatives=considered_alternatives,
        )
    except Exception as e:
        return {"error": str(e)}


def codehub_merge_pr_call(workspaces_root: Path, project_id: str, pr_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/codehub/pull_requests/<pr_id>/merge — merge a PR.

    Phase 0.2 attempt-5 CORRECTION 4 (R1 round-4): hard-pin ``agent`` to
    ``"orchestrator"`` here, mirroring ``codehub_force_merge_pr_call``'s
    pattern at line 3945. The earlier shape forwarded ``body.get("agent")``
    unfiltered, which meant the method-layer role gate (``service.py:518``)
    could be satisfied with an attacker-chosen ``agent`` string in the
    default auth-off posture (``auth_required()`` defaults False). The
    attempt-4 commit message for ``6cb0bf23`` claimed to close that path;
    R1 round-4 correctly noted that claim was overstated until this
    hard-pin existed. Now the method-layer gate is genuinely closed
    across both the tool layer (``hub_tools.py:360`` already pins
    ``agent=self._agent_id``) AND the monitor layer (here).

    Defense-in-depth note: the body's ``agent`` field is still
    accepted as an audit identity (published downstream by
    ``eventhub.publish_event`` in similar paths) — only the value sent
    to ``merge_pull_request`` is hard-pinned.
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    requesting_agent = body.get("agent") or ""
    result = reg.codehub.merge_pull_request(
        pr_id=pr_id,
        strategy=body.get("strategy") or "squash",
        agent="orchestrator",
    )
    # Audit trail — only publish once the underlying op succeeded.
    if isinstance(result, dict) and "error" not in result:
        try:
            reg.eventhub.publish_event(
                source_hub="ui",
                event_type="merge_pr",
                payload={
                    "pr_id": pr_id,
                    "agent": requesting_agent,
                    "strategy": body.get("strategy") or "squash",
                },
                priority="normal",
            )
        except Exception:
            # Audit emission is best-effort; failure must not mask the merge.
            pass
    return result


def codehub_pr_diff_call(workspaces_root: Path, project_id: str, pr_id: str, max_lines: int = 5000) -> dict:
    """GET /api/projects/<id>/codehub/pull_requests/<pr_id>/diff — unified diff
    (head vs target branch). Mirrors the codehub_get_diff agent tool."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    return reg.codehub.get_diff(pr_id, max_lines=max_lines)


def codehub_force_merge_pr_call(workspaces_root: Path, project_id: str, pr_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/codehub/pull_requests/<pr_id>/force_merge.

    DESTRUCTIVE — bypasses the premerge verifier gate. UI safety contract:
      * body MUST contain ``force=true`` (extra confirmation beyond the URL)
      * server forces ``agent='orchestrator'`` (CodeHub requires it)
      * publishes a UI-sourced audit event so the action is traceable
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    if not body.get("force"):
        return {
            "error": "force_required",
            "hint": "Destructive op: include force=true in the body to confirm.",
        }
    requesting_agent = body.get("agent") or ""
    reason = body.get("reason") or ""
    result = reg.codehub.force_merge_pull_request(
        pr_id=pr_id,
        reason=reason,
        agent="orchestrator",
    )
    # Audit trail — only publish once the underlying op succeeded.
    if "error" not in result:
        try:
            reg.eventhub.publish_event(
                source_hub="ui",
                event_type="force_merge_pr",
                payload={
                    "pr_id": pr_id,
                    "agent": requesting_agent,
                    "reason": reason,
                },
                priority="urgent",
            )
        except Exception:
            # Audit emission is best-effort; failure must not mask the merge.
            pass
        result = dict(result)
        result["audit_event_published"] = True
    return result


def codehub_record_check_call(workspaces_root: Path, project_id: str, pr_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/codehub/pull_requests/<pr_id>/checks — record a check."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    name = (body.get("name") or "").strip()
    status = (body.get("status") or "").strip()
    if not name or not status:
        return {"error": "name and status are required"}
    # Phase 4.6 expansion Step A: flip "ui_user" → "" so the future
    # codehub.record_check gate gets empty-actor fallthrough.
    return reg.codehub.record_check(
        pr_id=pr_id,
        name=name,
        status=status,
        evidence=body.get("evidence") or {},
        agent=body.get("agent") or "",
    )


# --- Cutover 30 Task 5: RegistryHub / EventHub / RunHub operation endpoints ------


def registryhub_register_endpoint_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/endpoints — register or update an API endpoint."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    method = (body.get("method") or "").strip()
    path = (body.get("path") or "").strip()
    if not method or not path:
        return {"error": "method and path are required"}
    # Phase 2 ownership gate ({backend}-only at phase>=2.0) REJECTS
    # the legacy "ui_user" phantom default — would break every
    # UI-triggered register_endpoint call at phase>=2.0. Flip to ""
    # for empty-actor fallthrough (the established Step A pattern from
    # 138cb475). The shim never spoofs a real actor; if the operator
    # wants gate-attributed authorship they pass `agent` in the body.
    return reg.registryhub.register_endpoint(
        method=method,
        path=path,
        schema=body.get("schema") or {},
        provider=body.get("provider") or "",
        agent=body.get("agent") or "",
        status=body.get("status") or "defined",
    )


def registryhub_register_table_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/tables — register or update a database table."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}
    # Phase 1 ownership gate ({backend, database_worker} at phase>=1.0)
    # REJECTS the legacy "ui_user" phantom default — would break every
    # UI-triggered register_table call. Flip to empty-actor fallthrough.
    return reg.schema_hub.register_table(
        name=name,
        schema=body.get("schema") or {},
        provider=body.get("provider") or "",
        agent=body.get("agent") or "",
        status=body.get("status") or "defined",
    )


def registryhub_register_consumer_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/consumers — register an endpoint consumer."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    endpoint_id = (body.get("endpoint_id") or "").strip()
    file_path = (body.get("file_path") or "").strip()
    if not endpoint_id or not file_path:
        return {"error": "endpoint_id and file_path are required"}
    # register_consumer is NOT phase-gated today (the wrapper hedges
    # "typically frontend" per the Phase 4.0 design), so the "ui_user"
    # default doesn't break behaviour — but the literal misnames the
    # actor in the persisted record. Flip to empty-actor for
    # consistency with the gated siblings above.
    return reg.registryhub.register_consumer(
        endpoint_id=endpoint_id,
        file_path=file_path,
        agent=body.get("agent") or "",
        metadata=body.get("metadata") or {},
    )


def registryhub_register_mcp_server_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/mcp_servers — register an MCP server."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    # Phase 4 alignment: the production tool wrapper defaults to
    # agent="backend" (see tools/mcp_registry_tools.py), and the
    # Phase 4 role gate ({backend} only) will reject "ui_user". The
    # "ui_user" name was a misnomer for this surface — the live
    # monitor panel exposes a backend-agent action.
    return reg.mcp_registry.register_mcp_server(
        name=(body.get("name") or "").strip(),
        transport=(body.get("transport") or "").strip(),
        endpoint=body.get("endpoint") or "",
        provider=body.get("provider") or "",
        agent=body.get("agent") or "backend",
        status=body.get("status") or "defined",
    )


# --- Cutover 33 Task 4: RegistryHub schema refinements -------------------------


def registryhub_update_endpoint_schema_call(workspaces_root: Path, project_id: str, endpoint_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/endpoints/<endpoint_id>/schema — update endpoint schema."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    request = body.get("request")
    response = body.get("response")
    agent = (body.get("agent") or "").strip()
    try:
        return reg.registryhub.update_schema(
            endpoint_id=endpoint_id, request=request, response=response, agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


def registryhub_deprecate_endpoint_call(workspaces_root: Path, project_id: str, endpoint_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/endpoints/<endpoint_id>/deprecate — mark endpoint deprecated."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    replacement_id = body.get("replacement_id")
    agent = (body.get("agent") or "").strip()
    try:
        return reg.registryhub.deprecate_endpoint(
            endpoint_id=endpoint_id, replacement_id=replacement_id, agent=agent,
        )
    except Exception as e:
        return {"error": str(e)}


def registryhub_update_table_schema_call(workspaces_root: Path, project_id: str, table_name: str, body: dict) -> dict:
    """POST /api/projects/<id>/registryhub/tables/<table_name>/schema — update table schema."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    schema = body.get("schema") or {}
    if not schema:
        return {"error": "schema required"}
    # Phase 1 sibling gate (Phase 4.2 closure) admits only {backend,
    # database_worker} for update_table_schema; "ui_user" was a misnomer
    # — the live monitor panel exposes a backend-agent action.
    agent = (body.get("agent") or "backend").strip()
    try:
        return reg.schema_hub.update_table_schema(name=table_name, schema=schema, agent=agent)
    except Exception as e:
        return {"error": str(e)}


def eventhub_mark_read_call(workspaces_root: Path, project_id: str, agent: str, body: dict) -> dict:
    """POST /api/projects/<id>/eventhub/inbox/<agent>/mark_read — mark a single inbox item read."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    event_id = (body.get("event_id") or "").strip()
    if not event_id:
        return {"error": "event_id is required"}
    # O14/Phase 4.1 design: HTTP shims pass caller=None (empty-actor
    # fallthrough) — the HTTP layer has no native agent identity and
    # the live monitor is operator-facing. If a future design wants
    # request-body-attributed caller, thread `body.get("caller")` here.
    return reg.eventhub.mark_read(agent=agent, event_id=event_id)


def eventhub_mark_all_read_call(workspaces_root: Path, project_id: str, agent: str, body: dict) -> dict:
    """POST /api/projects/<id>/eventhub/inbox/<agent>/mark_all_read — bulk-mark unread items.

    Optional ``before_ts`` body field bounds the operation to items received
    before that timestamp.
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    # O14/Phase 4.1: HTTP shim — caller=None empty-actor fallthrough.
    count = reg.eventhub.mark_all_read(agent=agent, before_ts=body.get("before_ts"))
    return {"marked_count": count}


def eventhub_subscribe_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/eventhub/subscriptions — create a subscription."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    agent = (body.get("agent") or "").strip()
    if not agent:
        return {"error": "agent is required"}
    # O14/Phase 4.1: HTTP shim — caller=None empty-actor fallthrough.
    return reg.eventhub.subscribe(
        agent=agent,
        source_hub=body.get("source_hub") or "*",
        event_type=body.get("event_type") or "*",
        priority_floor=body.get("priority_floor") or "low",
    )


def runhub_record_run_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/runhub/runs — record a new run (no compose/probe orchestration)."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    branch = (body.get("branch") or "").strip()
    generated_dir = (body.get("generated_dir") or "").strip()
    if not branch or not generated_dir:
        return {"error": "branch and generated_dir are required"}
    return reg.runhub.record_run(
        branch=branch,
        generated_dir=generated_dir,
        agent=body.get("agent") or "",
    )


def runhub_update_run_status_call(workspaces_root: Path, project_id: str, run_id: str, body: dict) -> dict:
    """POST /api/projects/<id>/runhub/runs/<run_id>/status — update a run's status and fields."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    status = (body.get("status") or "").strip()
    if not status:
        return {"error": "status is required"}
    extras = {k: v for k, v in body.items() if k not in ("status", "agent")}
    try:
        return reg.runhub.update_run_status(
            run_id=run_id,
            status=status,
            agent=body.get("agent") or "",
            **extras,
        )
    except ValueError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Persistent knowledge + skills admin API
#
# The knowledge agent writes to a host-wide SQLite DB at
# ~/.env-gen/knowledge/knowledge.db so future runs (any project) can reuse the
# lessons. The same data needs to be inspectable + manually curatable from the
# monitor UI; otherwise the bank silently bloats with noise. Skills live in
# multi_agent/bundled_skills/<name>/SKILL.md and are also host-wide.
#
# Endpoints:
#   GET    /api/knowledge[?q=&category=]  -> list (newest first, cap 500)
#   POST   /api/knowledge                 -> create OR update (id optional)
#   DELETE /api/knowledge/<id>            -> hard-delete one entry
#   GET    /api/skills                    -> list bundled skills
#   GET    /api/skills/<name>             -> read SKILL.md
#   PUT    /api/skills/<name>             -> upsert SKILL.md
#   DELETE /api/skills/<name>             -> remove skill dir
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3

_KNOWLEDGE_DB_PATH = Path.home() / ".env-gen" / "knowledge" / "knowledge.db"
_BUNDLED_SKILLS_DIR = Path(__file__).parent / "multi_agent" / "bundled_skills"

# Whitelisted columns the UI may write to. Internal bookkeeping columns
# (search_text, usage_count, last_used, related_ids, …) are NOT writable.
_KNOWLEDGE_EDITABLE = {
    "title", "category", "summary", "content", "problem", "symptoms",
    "root_cause", "solution", "example_code", "wrong_code", "tags",
    "keywords", "severity", "applies_to", "prerequisites", "source",
    "source_url",
}


def _knowledge_db():
    p = _KNOWLEDGE_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = _sqlite3.connect(str(p))
    con.row_factory = _sqlite3.Row
    return con


def list_knowledge_call(query: str = "", category: str = "", limit: int = 500) -> dict:
    if not _KNOWLEDGE_DB_PATH.exists():
        return {"entries": [], "categories": [], "total": 0}
    con = _knowledge_db()
    try:
        sql = ("SELECT id, title, category, severity, summary, problem, solution, "
               "example_code, tags, source, created_at, updated_at, usage_count "
               "FROM knowledge")
        clauses: list = []
        args: list = []
        if (category or "").strip():
            clauses.append("category = ?"); args.append(category.strip())
        if (query or "").strip():
            like = f"%{query.strip()}%"
            clauses.append("(title LIKE ? OR solution LIKE ? OR problem LIKE ? OR tags LIKE ?)")
            args += [like, like, like, like]
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(int(limit or 500), 5000)))
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        cats = [r[0] for r in con.execute(
            "SELECT category, COUNT(*) AS n FROM knowledge GROUP BY category ORDER BY n DESC, category"
        ).fetchall()]
        total = con.execute("SELECT count(*) FROM knowledge").fetchone()[0]
        return {"entries": rows, "categories": cats, "total": total}
    finally:
        con.close()


def upsert_knowledge_call(body: dict) -> dict:
    """Insert when no ``id`` is provided; update the existing row otherwise.

    Only whitelisted columns are accepted. ``created_at`` / ``updated_at`` are
    set automatically; ``id`` is auto-generated for inserts.
    """
    fields = {k: body.get(k) for k in _KNOWLEDGE_EDITABLE if k in body}
    if not (fields.get("title") or "").strip():
        return {"error": "title is required"}
    if not (fields.get("category") or "").strip():
        return {"error": "category is required"}
    if (fields.get("severity") or "").strip() not in {"low", "medium", "high", "critical"}:
        fields["severity"] = "medium"
    con = _knowledge_db()
    try:
        now = time.time()
        existing_id = (body.get("id") or "").strip()
        if existing_id:
            row = con.execute("SELECT id FROM knowledge WHERE id = ?", (existing_id,)).fetchone()
            if not row:
                return {"error": f"knowledge entry not found: {existing_id}"}
            cols = list(fields.keys())
            sets = ", ".join(f"{c} = ?" for c in cols)
            con.execute(f"UPDATE knowledge SET {sets}, updated_at = ? WHERE id = ?",
                        [fields[c] for c in cols] + [now, existing_id])
            con.commit()
            return {"ok": True, "id": existing_id, "updated": True}
        new_id = uuid.uuid4().hex
        cols = ["id"] + list(fields.keys()) + ["created_at", "updated_at", "source"]
        vals = [new_id] + [fields[c] for c in fields.keys()] + [now, now, fields.get("source") or "manual"]
        placeholders = ", ".join("?" for _ in cols)
        con.execute(f"INSERT INTO knowledge ({', '.join(cols)}) VALUES ({placeholders})", vals)
        con.commit()
        return {"ok": True, "id": new_id, "created": True}
    finally:
        con.close()


def delete_knowledge_call(entry_id: str) -> dict:
    if not (entry_id or "").strip():
        return {"error": "id required"}
    if not _KNOWLEDGE_DB_PATH.exists():
        return {"error": "knowledge db not initialised yet"}
    con = _knowledge_db()
    try:
        cur = con.execute("DELETE FROM knowledge WHERE id = ?", (entry_id.strip(),))
        con.commit()
        if cur.rowcount == 0:
            return {"error": f"knowledge entry not found: {entry_id}"}
        try:
            con.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
            con.commit()
        except Exception:
            pass
        return {"ok": True, "deleted": entry_id}
    finally:
        con.close()


# ---- Skills ---------------------------------------------------------------

def _safe_skill_name(name: str):
    """Skill names must be a kebab-ish path segment — reject anything else."""
    n = (name or "").strip()
    if not n or not re.match(r"^[a-z0-9][a-z0-9._-]{0,60}$", n):
        return None
    return n


def _read_skill_metadata(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    meta = {"name": "", "description": ""}
    if not m:
        return meta
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta


def list_skills_call() -> dict:
    base = _BUNDLED_SKILLS_DIR
    out = []
    if not base.exists():
        return {"skills": [], "base_dir": str(base)}
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
            stat = skill_md.stat()
        except Exception:
            continue
        meta = _read_skill_metadata(text)
        out.append({
            "name": d.name,
            "description": meta.get("description", ""),
            "size": stat.st_size,
            "updated_at": stat.st_mtime,
            "lines": text.count("\n") + 1,
        })
    return {"skills": out, "base_dir": str(base)}


def read_skill_call(name: str) -> dict:
    safe = _safe_skill_name(name)
    if not safe:
        return {"error": "invalid skill name"}
    p = _BUNDLED_SKILLS_DIR / safe / "SKILL.md"
    if not p.exists():
        return {"error": f"skill not found: {safe}"}
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e)}
    meta = _read_skill_metadata(text)
    return {
        "name": safe,
        "description": meta.get("description", ""),
        "content": text,
        "size": p.stat().st_size,
        "updated_at": p.stat().st_mtime,
    }


def upsert_skill_call(name: str, body: dict) -> dict:
    safe = _safe_skill_name(name)
    if not safe:
        return {"error": "invalid skill name (a-z, 0-9, ., _, -; up to 60 chars)"}
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return {"error": "content required (full SKILL.md text, including frontmatter)"}
    # Ensure there's a frontmatter; if absent, synthesize a minimal one so the
    # file remains parseable for the loader.
    if not re.match(r"^---\s*\n", content):
        desc = (body.get("description") or "").strip()
        content = f"---\nname: {safe}\ndescription: {desc}\n---\n\n{content}"
    d = _BUNDLED_SKILLS_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    is_new = not p.exists()
    try:
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "name": safe, "created": is_new, "updated": not is_new, "size": p.stat().st_size}


def delete_skill_call(name: str) -> dict:
    safe = _safe_skill_name(name)
    if not safe:
        return {"error": "invalid skill name"}
    d = _BUNDLED_SKILLS_DIR / safe
    if not d.is_dir():
        return {"error": f"skill not found: {safe}"}
    try:
        import shutil
        shutil.rmtree(d)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "deleted": safe}


# ---------------------------------------------------------------------------
# Cutover 35: Auth - shared-token bearer + session cookie
# ---------------------------------------------------------------------------

_SESSIONS: Dict[str, dict] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_COOKIE_NAME = "envgen_session"
_SESSION_TTL_SECONDS = 12 * 60 * 60  # 12h

# User accounts (persisted). Login is OPTIONAL: with no session everyone is the
# "guest" role (normal run budget); logging in as an "admin" unlocks unlimited
# budget. Accounts live in <workspaces_root>/users.json; an admin is seeded on
# first start (its generated password is printed once to the server console).
_USERS_ROOT: Optional[Path] = None
_USERS_LOCK = threading.Lock()
_PW_SALT = "envgen-v1"  # static salt; this is a test tool, not a public service


def _hash_pw(password: str) -> str:
    return hashlib.sha256((_PW_SALT + ":" + (password or "")).encode("utf-8")).hexdigest()


def _users_path() -> Path:
    root = _USERS_ROOT or Path.cwd()
    return Path(root) / "users.json"


def _load_users() -> Dict[str, dict]:
    try:
        data = json.loads(_users_path().read_text(encoding="utf-8"))
        users = data.get("users") if isinstance(data, dict) else None
        return users if isinstance(users, dict) else {}
    except Exception:
        return {}


def _save_users(users: Dict[str, dict]) -> None:
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def seed_admin_account(workspaces_root: Optional[Path]) -> Optional[str]:
    """Ensure an admin account exists. Returns the generated password if newly
    created (so the caller can print it once), else None."""
    global _USERS_ROOT
    _USERS_ROOT = workspaces_root or Path.cwd()
    with _USERS_LOCK:
        users = _load_users()
        if any((u or {}).get("role") == "admin" for u in users.values()):
            return None
        # Allow an explicit seed password via env; else generate a memorable one.
        pw = os.environ.get("ENVGEN_ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(9)
        users["admin"] = {"password_sha256": _hash_pw(pw), "role": "admin"}
        _save_users(users)
        return pw


def auth_required() -> bool:
    """Login is optional (guest allowed). Kept for the /me contract."""
    return bool(os.environ.get("ENVGEN_AUTH_TOKEN", "").strip())


def auth_login_call(body: dict) -> dict:
    """Mint a session if (username, password) match a stored account.

    Backward-compat: if ENVGEN_AUTH_TOKEN is set and the supplied `token`/`password`
    equals it, the user is logged in with the `admin` role.
    """
    username = (body.get("username") or "").strip()
    secret = (body.get("password") or body.get("token") or "").strip()
    if not username:
        return {"error": "username required"}

    role = None
    shared = os.environ.get("ENVGEN_AUTH_TOKEN", "").strip()
    users = _load_users()
    rec = users.get(username)
    if rec and secret and _hash_pw(secret) == rec.get("password_sha256"):
        role = rec.get("role") or "user"
    elif shared and secret == shared:
        role = "admin"
    if role is None:
        return {"error": "invalid username or password"}

    sid = uuid.uuid4().hex
    now = time.time()
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = {"username": username, "role": role, "created_at": now, "last_seen_at": now}
    return {"session_id": sid, "username": username, "role": role}


def auth_logout_call(session_id: str) -> dict:
    with _SESSIONS_LOCK:
        _SESSIONS.pop(session_id, None)
    return {"ok": True}


def check_session_info(session_id: Optional[str]) -> Optional[dict]:
    """Return the session record ({username, role, ...}) if valid + not expired."""
    if not session_id:
        return None
    now = time.time()
    with _SESSIONS_LOCK:
        info = _SESSIONS.get(session_id)
        if not info:
            return None
        if (now - info.get("created_at", 0)) > _SESSION_TTL_SECONDS:
            _SESSIONS.pop(session_id, None)
            return None
        info["last_seen_at"] = now
        return dict(info)


def check_session(session_id: Optional[str]) -> Optional[str]:
    """Return username if session is valid + not expired."""
    info = check_session_info(session_id)
    return info.get("username") if info else None


def _read_session_cookie(headers) -> Optional[str]:
    """Parse the `envgen_session` cookie from request headers."""
    raw = headers.get("Cookie", "")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
        morsel = c.get(_SESSION_COOKIE_NAME)
        return morsel.value if morsel else None
    except Exception:
        return None


class MonitorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, project_dir: Optional[Path] = None,
                 workspaces_root: Optional[Path] = None, **kwargs):
        self._project_dir = project_dir
        self._workspaces_root = workspaces_root
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        """Force revalidation of static assets.

        The UI is served as live, in-browser-compiled JSX/CSS straight off disk
        (no build step). The default static handler only sends ``Last-Modified``,
        so browsers heuristically cache the .jsx/.css and keep showing stale code
        after edits. We add ``Cache-Control: no-cache`` (revalidate every load —
        the existing Last-Modified still lets the server answer 304) for any
        response that hasn't already declared a cache policy. JSON/SSE handlers
        set their own Cache-Control, so they're left untouched.
        """
        try:
            buffered = b"".join(getattr(self, "_headers_buffer", []) or []).lower()
            if b"cache-control" not in buffered:
                self.send_header("Cache-Control", "no-cache")
        except Exception:
            pass
        super().end_headers()

    def _request_username(self) -> Optional[str]:
        """Username for this request, or None if unauthed.

        Returns the username if a valid session cookie is present, regardless
        of whether auth is required. When auth is required and no valid
        username is found, the route handler will short-circuit with 401.
        """
        sid = _read_session_cookie(self.headers)
        return check_session(sid)

    def _request_role(self) -> str:
        """Role for this request: the session's role, else 'guest'."""
        info = check_session_info(_read_session_cookie(self.headers))
        return (info or {}).get("role") or "guest"

    def _apply_request_user(self, body: dict) -> None:
        """Override body['agent'] AND body['from_user'] with the session
        username when authed.

        Cutover 35: When a request carries a valid session cookie, the
        username is forwarded into mutation helpers as the ``agent`` body
        field so audit logs (``created_by`` / ``_updated_by``) reflect the
        real user. No-op when auth is off or no valid session.

        Phase 4.7-slim Path C (2026-06-01): the same authed username
        is ALSO stamped onto ``body["from_user"]`` so the HumanConsole
        publish_human_message endpoints (``start_conversation`` /
        ``send_message``) carry the real session identity into the
        EventHub 4.7 gate at ``eventhub.py:458+``. This is the
        long-term replacement for Path A's process-wide
        ``ENVGEN_HUMAN_USER_ID`` env-var bridge: per-request identity
        for multi-user pipelines. Path A stays as the
        headless/CLI/test fallback — at phase>=4.7 a request that
        reaches HumanConsole without an authed session AND without an
        explicit body ``from_user`` falls back to the env-var bridge;
        if that's also unset, the 4.7 gate rejects with the
        "configure ENVGEN_HUMAN_USER_ID" guidance.

        The session-identity-wins-over-body-supplied-value invariant
        mirrors the existing ``agent``-override semantics — an authed
        user cannot spoof a different identity by passing it in the
        request body, only an unauthed/guest request can carry an
        explicit ``from_user`` (or fall back to the Path A chain).
        """
        if not isinstance(body, dict):
            return
        username = self._request_username()
        if username:
            body["agent"] = username
            body["from_user"] = username

    def _enforce_auth(self) -> bool:
        """Return True if the request is allowed to proceed.

        When auth_required() is False, always True.
        When auth_required() is True, the request must have a valid session
        cookie OR target one of the exempt paths.
        """
        if not auth_required():
            return True
        parsed = urlparse(self.path)
        EXEMPT = {"/api/auth/login", "/api/auth/me", "/api/ping"}
        if parsed.path in EXEMPT:
            return True
        # Static files (CSS/JS/HTML) are served unauthenticated so the login
        # screen can load. Auth gate only applies to /api/ endpoints.
        if not parsed.path.startswith("/api/"):
            return True
        # Allow OPTIONS for preflight (we don't really use CORS but just in case)
        if self.command == "OPTIONS":
            return True
        if self._request_username() is None:
            self._write_json({"error": "unauthorized", "auth_required": True}, status=HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def _write_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Browser polling can abort an in-flight request when the page reloads
            # or a newer /api/state request supersedes the old one.
            return

    def _stream_sse(self, project_id: str) -> None:
        """Stream Server-Sent Events for a project until the client disconnects.

        Each call runs on its own thread (``ThreadingHTTPServer``). The handler
        registers a queue with the per-project ``_SSEHub`` and blocks on
        ``q.get(timeout=15)``: every event is forwarded as a ``data: <json>``
        frame; the timeout sends a heartbeat comment. On any write failure the
        client is unregistered and the loop exits.
        """
        import uuid as _uuid

        if self._workspaces_root is None:
            self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
            return

        sse_hub = _get_or_create_sse_hub(self._workspaces_root, project_id)
        if sse_hub is None:
            self._write_json({"error": f"project not found: {project_id}"}, status=HTTPStatus.NOT_FOUND)
            return

        client_id = f"sse_{_uuid.uuid4().hex[:12]}"
        q = sse_hub.register(client_id)

        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            sse_hub.unregister(client_id)
            return

        try:
            while True:
                try:
                    event = q.get(timeout=15.0)
                except queue.Empty:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break

                slim = {
                    "id": event.get("id"),
                    "event_type": event.get("event_type"),
                    "source_hub": event.get("source_hub"),
                    "thread_id": event.get("thread_id"),
                    "created_at": event.get("created_at"),
                    "recipients": event.get("recipients", []),
                }
                try:
                    data = json.dumps(slim, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            sse_hub.unregister(client_id)

    def _stream_global_sse(self) -> None:
        """Cutover 32: stream the workspaces-root-scoped global SSE feed.

        Mirrors :meth:`_stream_sse` but reads from the ``_GlobalSSEHub`` for
        the current ``workspaces_root``: lifecycle events (project_created /
        _status_changed / _deleted) plus every per-project EventHub event
        (forwarded by ``_GlobalForwardBridge``).
        """
        import uuid as _uuid

        if self._workspaces_root is None:
            self._write_json(
                {"error": "server not in workspaces-root mode"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        hub = _get_or_create_global_sse_hub(self._workspaces_root)
        client_id = f"sse_global_{_uuid.uuid4().hex[:12]}"
        q = hub.register(client_id)

        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            hub.unregister(client_id)
            return

        try:
            while True:
                try:
                    event = q.get(timeout=15.0)
                except queue.Empty:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                slim = {
                    "id": event.get("id"),
                    "event_type": event.get("event_type"),
                    "source_hub": event.get("source_hub"),
                    "project_id": event.get("project_id"),
                    "thread_id": event.get("thread_id"),
                    "created_at": event.get("created_at"),
                    "payload": event.get("payload"),
                }
                try:
                    data = json.dumps(slim, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            hub.unregister(client_id)

    def _stream_run_log(self, run_id: str) -> None:
        """Cutover 36: SSE stream of a run's generation.log.

        Sends an initial snapshot (last 64KB) so users joining mid-run see
        recent context, then tails the file every 200ms for new bytes. Emits
        a final ``data: {"_end": true, "returncode": N}`` event when the
        underlying Popen completes, then closes the stream. Heartbeats every
        15s during quiet periods so proxies don't drop the connection.
        """
        with _RUN_REGISTRY_LOCK:
            handle = _RUN_REGISTRY.get(run_id)
        if handle is None:
            self._write_json({"error": f"run not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
            return

        log_path = Path(handle["log_path"])

        # Send SSE preamble
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

        def emit(payload: dict) -> bool:
            try:
                data = json.dumps(payload, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        # Step 1: send the initial snapshot (last 64KB).
        SNAPSHOT_MAX = 64 * 1024
        initial_bytes = b""
        pos = 0
        if log_path.exists():
            try:
                size = log_path.stat().st_size
                with log_path.open("rb") as f:
                    if size > SNAPSHOT_MAX:
                        f.seek(size - SNAPSHOT_MAX, 0)
                        # Skip partial first line so the snapshot is clean
                        f.readline()
                    initial_bytes = f.read()
                    pos = f.tell()
            except Exception:
                initial_bytes = b""
                pos = 0
        if initial_bytes:
            text = initial_bytes.decode("utf-8", errors="replace")
            if not emit({"chunk": text, "initial": True}):
                return

        # Step 2: tail loop.
        HEARTBEAT_INTERVAL = 15.0
        POLL_INTERVAL = 0.2
        last_heartbeat = time.time()
        while True:
            # Check if run is finished
            with _RUN_REGISTRY_LOCK:
                cur_handle = _RUN_REGISTRY.get(run_id)
            if cur_handle is None:
                break
            popen = cur_handle["popen"]
            rc = popen.poll()
            # Read any new bytes
            new_text = ""
            if log_path.exists():
                try:
                    cur_size = log_path.stat().st_size
                    if cur_size > pos:
                        with log_path.open("rb") as f:
                            f.seek(pos, 0)
                            chunk = f.read(cur_size - pos)
                            pos = f.tell()
                        if chunk:
                            new_text = chunk.decode("utf-8", errors="replace")
                    elif cur_size < pos:
                        # File rotated / truncated; reset
                        pos = 0
                except Exception:
                    pass

            if new_text:
                if not emit({"chunk": new_text}):
                    return
                last_heartbeat = time.time()

            if rc is not None:
                # One last read in case the process flushed after our seek
                try:
                    if log_path.exists():
                        cur_size = log_path.stat().st_size
                        if cur_size > pos:
                            with log_path.open("rb") as f:
                                f.seek(pos, 0)
                                chunk = f.read(cur_size - pos)
                            if chunk:
                                emit({"chunk": chunk.decode("utf-8", errors="replace")})
                except Exception:
                    pass
                emit({"_end": True, "returncode": rc})
                return

            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_heartbeat = time.time()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

            time.sleep(POLL_INTERVAL)

    def do_GET(self) -> None:  # noqa: N802
        if not self._enforce_auth():
            return
        parsed = urlparse(self.path)
        # Cutover 35: auth status endpoint.
        if parsed.path == "/api/auth/me":
            info = check_session_info(_read_session_cookie(self.headers))
            if info is None:
                if auth_required():
                    self._write_json({"error": "unauthorized", "auth_required": True}, status=HTTPStatus.UNAUTHORIZED)
                else:
                    # Login is optional — no session means the guest role.
                    self._write_json({"username": "guest", "role": "guest", "auth_required": False})
            else:
                self._write_json({
                    "username": info.get("username"),
                    "role": info.get("role") or "user",
                    "auth_required": auth_required(),
                })
            return
        if parsed.path == "/api/projects":
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(build_projects_list(self._workspaces_root))
            return
        # Cutover 32: workspaces-root-scoped global SSE feed for the homepage
        # (project lifecycle + cross-project events). Exact-match; placed
        # before the per-project ``/api/projects/<id>/events`` route below.
        if parsed.path == "/api/events":
            self._stream_global_sse()
            return
        # Cutover 31: SSE event stream. MUST be matched before /state because
        # both share the /api/projects/<id>/ prefix.
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/events"):
            pid = parsed.path[len("/api/projects/"):-len("/events")]
            self._stream_sse(pid)
            return
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/state"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            # /api/projects/<id>/state
            pid = parsed.path[len("/api/projects/"):-len("/state")]
            self._write_json(build_project_state(self._workspaces_root, pid))
            return
        # GET /api/projects/<id>/releases — version list for the Preview switcher.
        # Each release is an immutable ``release-v<tag>`` branch, so the UI can
        # show per-version snapshots + a "Launch live" button.
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/releases"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = parsed.path[len("/api/projects/"):-len("/releases")]
            self._write_json(build_releases_list(self._workspaces_root, pid))
            return
        # GET /api/projects/<id>/conversations
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/conversations"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = parsed.path[len("/api/projects/"):-len("/conversations")]
            self._write_json(build_conversations_list(self._workspaces_root, pid))
            return
        # Cutover 32: GET /api/projects/<id>/agents — agents_config.yaml profiles.
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/agents"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = parsed.path[len("/api/projects/"):-len("/agents")]
            self._write_json(build_agents_list(self._workspaces_root, pid))
            return
        # GET /api/projects/<id>/conversations/<tid>/messages
        marker = "/conversations/"
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/messages") and marker in parsed.path:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            head, tail = parsed.path.split(marker, 1)
            pid = head[len("/api/projects/"):]
            tid = tail[: -len("/messages")]
            self._write_json(build_messages_list(self._workspaces_root, pid, tid))
            return
        # Cutover 39: GET /api/projects/<id>/user_gates
        m = re.match(r"^/api/projects/([^/]+)/user_gates$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = unquote(m.group(1))
            self._write_json(list_user_gates_call(self._workspaces_root, pid))
            return
        # Cutover 40: GET /api/projects/<id>/references
        m = re.match(r"^/api/projects/([^/]+)/references$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = unquote(m.group(1))
            self._write_json(list_references_call(self._workspaces_root, pid))
            return
        # Cutover 43.27: GET /api/projects/<id>/references/<filename>/raw — serve
        # a reference file's raw bytes (so the UI can render images, etc.).
        m = re.match(r"^/api/projects/([^/]+)/references/([^/]+)/raw$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = unquote(m.group(1))
            fname = unquote(m.group(2))
            workspace = _project_workspace(self._workspaces_root, pid)
            target = _safe_reference_path(workspace, fname) if workspace else None
            # Fall back to screenshots/ so files copied by the orchestrator
            # (not uploaded via the UI) are also servable by name.
            if workspace and (target is None or not target.exists() or not target.is_file()):
                safe_name = (fname or "").strip()
                if safe_name and "/" not in safe_name and "\\" not in safe_name and ".." not in safe_name:
                    alt = workspace / "screenshots" / safe_name
                    if alt.exists() and alt.is_file():
                        target = alt
            if target is None or not target.exists() or not target.is_file():
                self._write_json({"error": "reference not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                import mimetypes
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                self._write_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        # Cutover 43.27: GET /api/projects/<id>/deliverability — read-only report
        m = re.match(r"^/api/projects/([^/]+)/deliverability$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = unquote(m.group(1))
            self._write_json(deliverability_report_call(self._workspaces_root, pid))
            return
        # GET /api/projects/<id>/run_budget — current run budget caps + usage.
        m = re.match(r"^/api/projects/([^/]+)/run_budget$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(run_budget_call(self._workspaces_root, unquote(m.group(1))))
            return
        # Cutover 43.19: GET /api/projects/<id>/code/branches — git branches for selector
        m = re.match(r"^/api/projects/([^/]+)/code/branches$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = unquote(m.group(1))
            self._write_json(list_code_branches_call(self._workspaces_root, pid))
            return
        # Cutover 43.11/19: GET /api/projects/<id>/code/tree?path=<rel>&branch=<b>
        m = re.match(r"^/api/projects/([^/]+)/code/tree$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            qs = parse_qs(parsed.query)
            pid = unquote(m.group(1))
            rel = (qs.get("path") or [""])[0]
            branch = (qs.get("branch") or [None])[0]
            self._write_json(list_code_tree_call(self._workspaces_root, pid, rel, branch))
            return
        # Cutover 43.11/19: GET /api/projects/<id>/code/file?path=<rel>&branch=<b>
        m = re.match(r"^/api/projects/([^/]+)/code/file$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            qs = parse_qs(parsed.query)
            pid = unquote(m.group(1))
            rel = (qs.get("path") or [""])[0]
            branch = (qs.get("branch") or [None])[0]
            self._write_json(read_code_file_call(self._workspaces_root, pid, rel, branch))
            return
        # Cutover 43.16/19: GET /api/projects/<id>/code/files?branch=<b> — flat list for search
        m = re.match(r"^/api/projects/([^/]+)/code/files$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            qs = parse_qs(parsed.query)
            pid = unquote(m.group(1))
            branch = (qs.get("branch") or [None])[0]
            self._write_json(list_code_files_call(self._workspaces_root, pid, branch))
            return
        # Cutover 43.19: GET /api/projects/<id>/codehub/pull_requests/<pr_id>/diff?max_lines=<n>
        m = re.match(r"^/api/projects/([^/]+)/codehub/pull_requests/([^/]+)/diff$", parsed.path)
        if m:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            qs = parse_qs(parsed.query)
            pid = unquote(m.group(1))
            pr_id = unquote(m.group(2))
            try:
                max_lines = int((qs.get("max_lines") or ["5000"])[0])
            except (ValueError, TypeError):
                max_lines = 5000
            self._write_json(codehub_pr_diff_call(self._workspaces_root, pid, pr_id, max_lines))
            return
        # Cutover 34: orchestrator run status / list
        if parsed.path == "/api/runs":
            self._write_json({"runs": list_runs()})
            return
        # Cutover 36: SSE log stream — match before /status since both share the /api/runs/ prefix.
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/log/stream"):
            run_id = parsed.path[len("/api/runs/"):-len("/log/stream")]
            self._stream_run_log(run_id)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/status"):
            run_id = parsed.path[len("/api/runs/"):-len("/status")]
            self._write_json(get_run_status(run_id))
            return
        if parsed.path == "/api/state":
            payload = build_state(self._project_dir)
            self._write_json(payload)
            return
        if parsed.path == "/api/ping":
            self._write_json({"ok": True})
            return
        # Persistent knowledge + skills (host-wide; not per-project)
        if parsed.path == "/api/knowledge":
            qs = parse_qs(parsed.query)
            self._write_json(list_knowledge_call(
                query=(qs.get("q", [""])[0]),
                category=(qs.get("category", [""])[0]),
                limit=int(qs.get("limit", ["500"])[0] or 500),
            ))
            return
        if parsed.path == "/api/skills":
            self._write_json(list_skills_call())
            return
        m = re.match(r"^/api/skills/([^/]+)$", parsed.path)
        if m:
            self._write_json(read_skill_call(unquote(m.group(1))))
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_POST(self) -> None:  # noqa: N802
        if not self._enforce_auth():
            return
        parsed = urlparse(self.path)
        # Cutover 35: auth routes. These do NOT need workspaces_root and must
        # run before the workspaces-root guard below.
        if parsed.path == "/api/auth/login":
            body = self._read_json_body()
            result = auth_login_call(body)
            if "error" in result:
                self._write_json(result, status=HTTPStatus.UNAUTHORIZED)
                return
            sid = result["session_id"]
            payload = {"username": result["username"], "role": result.get("role", "user")}
            body_bytes = json.dumps(payload).encode("utf-8")
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header(
                    "Set-Cookie",
                    f"{_SESSION_COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={_SESSION_TTL_SECONDS}",
                )
                self.end_headers()
                self.wfile.write(body_bytes)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if parsed.path == "/api/auth/logout":
            sid = _read_session_cookie(self.headers)
            if sid:
                auth_logout_call(sid)
            body_bytes = b'{"ok":true}'
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header(
                    "Set-Cookie",
                    f"{_SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                )
                self.end_headers()
                self.wfile.write(body_bytes)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self._workspaces_root is None:
            self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
            return
        body = self._read_json_body()
        # Cutover 35: forward session username into the mutation body as `agent`.
        self._apply_request_user(body)
        # POST /api/projects — create new project
        if parsed.path == "/api/projects":
            self._write_json(create_project_call(self._workspaces_root, body))
            return
        # POST /api/projects/<id>/status — change lifecycle status
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/status"):
            pid = parsed.path[len("/api/projects/"):-len("/status")]
            self._write_json(set_project_status_call(self._workspaces_root, pid, body))
            return
        # POST /api/projects/<id>/reasoning_effort — set per-lane gpt-5 reasoning_effort (live)
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/reasoning_effort"):
            pid = parsed.path[len("/api/projects/"):-len("/reasoning_effort")]
            self._write_json(set_reasoning_effort_call(self._workspaces_root, pid, body))
            return
        # POST /api/projects/<id>/run_budget — raise/adjust run-budget caps (live).
        m_rb = re.match(r"^/api/projects/([^/]+)/run_budget$", parsed.path)
        if m_rb:
            body["_requester_role"] = self._request_role()
            self._write_json(update_run_budget_call(self._workspaces_root, unquote(m_rb.group(1)), body))
            return
        # Cutover 30 Task 3: WorkHub mutation endpoints
        if parsed.path.startswith("/api/projects/"):
            # Cutover 37 block-editor endpoints (regex match before parts-based dispatch).
            # Insert-after pattern (longer) must be checked before /blocks/<id> update.
            m_insert = re.match(r"^/api/projects/([^/]+)/workhub/pages/([^/]+)/blocks/([^/]+)/after$", parsed.path)
            if m_insert:
                pid = unquote(m_insert.group(1))
                page_id = unquote(m_insert.group(2))
                after_id = unquote(m_insert.group(3))
                self._write_json(workhub_insert_block_after_call(self._workspaces_root, pid, page_id, after_id, body))
                return
            m_append = re.match(r"^/api/projects/([^/]+)/workhub/pages/([^/]+)/blocks$", parsed.path)
            if m_append:
                pid = unquote(m_append.group(1))
                page_id = unquote(m_append.group(2))
                self._write_json(workhub_append_block_call(self._workspaces_root, pid, page_id, body))
                return
            m_update = re.match(r"^/api/projects/([^/]+)/workhub/blocks/([^/]+)$", parsed.path)
            if m_update:
                pid = unquote(m_update.group(1))
                block_id = unquote(m_update.group(2))
                self._write_json(workhub_update_block_call(self._workspaces_root, pid, block_id, body))
                return
            tail = parsed.path[len("/api/projects/"):]
            parts = tail.split("/")
            if len(parts) >= 3 and parts[1] == "workhub":
                pid = parts[0]
                if parts[2] == "tasks" and len(parts) == 3:
                    self._write_json(workhub_create_task_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "tasks" and len(parts) == 5 and parts[4] == "priority":
                    self._write_json(workhub_set_priority_call(self._workspaces_root, pid, parts[3], body))
                    return
                # Cutover 33 Task 2: WorkHub task lifecycle
                if parts[2] == "tasks" and len(parts) == 5 and parts[4] in ("claim", "complete", "fail", "cancel"):
                    handler = {
                        "claim": workhub_claim_task_call,
                        "complete": workhub_complete_task_call,
                        "fail": workhub_fail_task_call,
                        "cancel": workhub_cancel_task_call,
                    }[parts[4]]
                    self._write_json(handler(self._workspaces_root, pid, parts[3], body))
                    return
                if parts[2] == "pages" and len(parts) == 3:
                    self._write_json(workhub_create_document_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "pages" and len(parts) == 5 and parts[4] == "visual_review":
                    self._write_json(workhub_submit_visual_review_call(self._workspaces_root, pid, parts[3], body))
                    return
                if parts[2] == "coverage_allowlist" and len(parts) == 3:
                    self._write_json(workhub_mark_intentionally_dead_call(self._workspaces_root, pid, body))
                    return
                # Cutover 33 Task 3: comments + decisions + plans
                if parts[2] == "comments" and len(parts) == 4:
                    self._write_json(workhub_comment_call(self._workspaces_root, pid, parts[3], body))
                    return
                if parts[2] == "pages" and len(parts) == 5 and parts[4] == "decisions":
                    self._write_json(workhub_record_decision_call(self._workspaces_root, pid, parts[3], body))
                    return
            # CodeHub mutation endpoints
            if len(parts) >= 3 and parts[1] == "codehub":
                pid = parts[0]
                if parts[2] == "pull_requests" and len(parts) == 3:
                    self._write_json(codehub_open_pr_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "pull_requests" and len(parts) == 5:
                    pr_id = parts[3]
                    if parts[4] == "reviews":
                        self._write_json(codehub_submit_review_call(self._workspaces_root, pid, pr_id, body))
                        return
                    if parts[4] == "merge":
                        self._write_json(codehub_merge_pr_call(self._workspaces_root, pid, pr_id, body))
                        return
                    if parts[4] == "force_merge":
                        self._write_json(codehub_force_merge_pr_call(self._workspaces_root, pid, pr_id, body))
                        return
                    if parts[4] == "checks":
                        self._write_json(codehub_record_check_call(self._workspaces_root, pid, pr_id, body))
                        return
            # Cutover 30 Task 5: RegistryHub mutation endpoints
            if len(parts) >= 3 and parts[1] == "registryhub":
                pid = parts[0]
                if parts[2] == "endpoints" and len(parts) == 3:
                    self._write_json(registryhub_register_endpoint_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "tables" and len(parts) == 3:
                    self._write_json(registryhub_register_table_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "consumers" and len(parts) == 3:
                    self._write_json(registryhub_register_consumer_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "mcp_servers" and len(parts) == 3:
                    self._write_json(registryhub_register_mcp_server_call(self._workspaces_root, pid, body))
                    return
            # Cutover 33 Task 4: RegistryHub schema refinements.
            # Endpoint IDs are "METHOD /path" (contain "/"), so use prefix/suffix split.
            if "/registryhub/endpoints/" in parsed.path and parsed.path.endswith("/schema"):
                head, tail = parsed.path.split("/registryhub/endpoints/", 1)
                pid_from_path = head[len("/api/projects/"):]
                eid = unquote(tail[: -len("/schema")])
                self._write_json(registryhub_update_endpoint_schema_call(self._workspaces_root, pid_from_path, eid, body))
                return
            if "/registryhub/endpoints/" in parsed.path and parsed.path.endswith("/deprecate"):
                head, tail = parsed.path.split("/registryhub/endpoints/", 1)
                pid_from_path = head[len("/api/projects/"):]
                eid = unquote(tail[: -len("/deprecate")])
                self._write_json(registryhub_deprecate_endpoint_call(self._workspaces_root, pid_from_path, eid, body))
                return
            if "/registryhub/tables/" in parsed.path and parsed.path.endswith("/schema"):
                head, tail = parsed.path.split("/registryhub/tables/", 1)
                pid_from_path = head[len("/api/projects/"):]
                name = unquote(tail[: -len("/schema")])
                self._write_json(registryhub_update_table_schema_call(self._workspaces_root, pid_from_path, name, body))
                return
            # Cutover 30 Task 5: EventHub mutation endpoints
            if len(parts) >= 3 and parts[1] == "eventhub":
                pid = parts[0]
                if parts[2] == "inbox" and len(parts) == 5 and parts[4] == "mark_read":
                    self._write_json(eventhub_mark_read_call(self._workspaces_root, pid, parts[3], body))
                    return
                if parts[2] == "inbox" and len(parts) == 5 and parts[4] == "mark_all_read":
                    self._write_json(eventhub_mark_all_read_call(self._workspaces_root, pid, parts[3], body))
                    return
                if parts[2] == "subscriptions" and len(parts) == 3:
                    self._write_json(eventhub_subscribe_call(self._workspaces_root, pid, body))
                    return
            # Cutover 30 Task 5: RunHub mutation endpoints
            if len(parts) >= 3 and parts[1] == "runhub":
                pid = parts[0]
                if parts[2] == "runs" and len(parts) == 3:
                    self._write_json(runhub_record_run_call(self._workspaces_root, pid, body))
                    return
                if parts[2] == "runs" and len(parts) == 5 and parts[4] == "status":
                    self._write_json(runhub_update_run_status_call(self._workspaces_root, pid, parts[3], body))
                    return
        # POST /api/projects/<id>/conversations
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/conversations"):
            pid = parsed.path[len("/api/projects/"):-len("/conversations")]
            self._write_json(start_conversation_call(self._workspaces_root, pid, body))
            return
        # POST /api/projects/<id>/conversations/<tid>/messages
        marker = "/conversations/"
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/messages") and marker in parsed.path:
            head, tail = parsed.path.split(marker, 1)
            pid = head[len("/api/projects/"):]
            tid = tail[: -len("/messages")]
            self._write_json(send_message_call(self._workspaces_root, pid, tid, body))
            return
        # Cutover 34: orchestrator run control
        if parsed.path == "/api/runs":
            body["_requester_role"] = self._request_role()
            self._write_json(start_run_call(self._workspaces_root, body))
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/stop"):
            run_id = parsed.path[len("/api/runs/"):-len("/stop")]
            self._write_json(stop_run_call(run_id, body))
            return
        # Continue/resume an existing project in place (--no-fresh relaunch).
        m = re.match(r"^/api/projects/([^/]+)/continue$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            body["_requester_role"] = self._request_role()
            self._write_json(continue_run_call(self._workspaces_root, pid, body))
            return
        # Persistent knowledge: POST upserts (create when no id; update when id).
        if parsed.path == "/api/knowledge":
            self._write_json(upsert_knowledge_call(body))
            return
        # Persistent skills: PUT-like create-or-replace via POST (browsers/UIs
        # find POST easier than PUT for JSON bodies).
        m = re.match(r"^/api/skills/([^/]+)$", parsed.path)
        if m:
            self._write_json(upsert_skill_call(unquote(m.group(1)), body))
            return
        # Cutover 34: deliver project
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/deliver"):
            pid = parsed.path[len("/api/projects/"):-len("/deliver")]
            self._write_json(deliver_project_call(self._workspaces_root, pid, body))
            return
        # Cutover 39: user-gates POST routes.
        # CRITICAL: the ``/evaluate`` suffix MUST be matched BEFORE the bare
        # ``/<gid>`` (update) pattern, otherwise the update regex swallows it.
        m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)/evaluate$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            gid = unquote(m.group(2))
            self._write_json(evaluate_user_gate_call(self._workspaces_root, pid, gid))
            return
        m = re.match(r"^/api/projects/([^/]+)/user_gates$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            self._write_json(create_user_gate_call(self._workspaces_root, pid, body))
            return
        m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            gid = unquote(m.group(2))
            self._write_json(update_user_gate_call(self._workspaces_root, pid, gid, body))
            return
        # Cutover 40: POST /api/projects/<id>/references
        m = re.match(r"^/api/projects/([^/]+)/references$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            self._write_json(upload_reference_call(self._workspaces_root, pid, body))
            return
        self._write_json({"error": "unknown endpoint"}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._enforce_auth():
            return
        if self._workspaces_root is None:
            self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
            return
        parsed = urlparse(self.path)
        body = self._read_json_body()
        # DELETE /api/projects/<id>/conversations/<tid> — hide a chat (mark resolved).
        m = re.match(r"^/api/projects/([^/]+)/conversations/([^/]+)$", parsed.path)
        if m:
            self._write_json(delete_conversation_call(self._workspaces_root, unquote(m.group(1)), unquote(m.group(2))))
            return
        # Persistent knowledge / skills delete (host-wide; not per-project).
        m = re.match(r"^/api/knowledge/([^/]+)$", parsed.path)
        if m:
            self._write_json(delete_knowledge_call(unquote(m.group(1))))
            return
        m = re.match(r"^/api/skills/([^/]+)$", parsed.path)
        if m:
            self._write_json(delete_skill_call(unquote(m.group(1))))
            return
        # Cutover 39: DELETE /api/projects/<id>/user_gates/<gid>
        m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            gid = unquote(m.group(2))
            self._write_json(delete_user_gate_call(self._workspaces_root, pid, gid))
            return
        # Cutover 40: DELETE /api/projects/<id>/references/<filename>
        # Must be matched BEFORE the bare /api/projects/<id> delete below.
        m = re.match(r"^/api/projects/([^/]+)/references/([^/]+)$", parsed.path)
        if m:
            pid = unquote(m.group(1))
            fname = unquote(m.group(2))
            self._write_json(delete_reference_call(self._workspaces_root, pid, fname))
            return
        # DELETE /api/projects/<id>
        if parsed.path.startswith("/api/projects/"):
            tail = parsed.path[len("/api/projects/"):]
            # Only handle the bare <id> form (no sub-resource segments).
            if tail and "/" not in tail:
                self._write_json(delete_project_call(self._workspaces_root, tail, body))
                return
        self._write_json({"error": "unknown endpoint"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


# attempt-6 HARDENING A (R1 round-5 FIX C localhost nit, 2026-05-29):
# ``localhost`` is name-resolved via ``/etc/hosts`` + nsswitch — a
# root-poisoned ``/etc/hosts`` (or an attacker-controlled NSS module)
# can re-point it to a non-loopback address while the bind guard still
# treats the string "localhost" as safe. Pin the literal IP loopback
# set (IPv4 ``127.0.0.1`` and IPv6 ``::1``) so the gate is purely
# string-equality on literal addresses and the resolver cannot
# influence the decision.
_LOOPBACK_HOSTS = ("127.0.0.1", "::1")


def _enforce_bind_guard(host: str) -> None:
    """R1+R2 round-4 condition #2: refuse non-loopback binds without auth.

    The monitor control plane has ~54 ungated ``*_call`` mutations (Phase
    0.2-EXT scope). Binding to a non-loopback address without
    ``ENVGEN_AUTH_TOKEN`` would expose them to remote unauthenticated
    callers. Default loopback (``127.0.0.1``) is safe for the single-user
    local-dev threat model; any other host requires an auth token to be
    set in the environment.

    Exits with status 2 (the conventional argparse-style misuse code) when
    the guard refuses; otherwise returns silently.
    """
    if host in _LOOPBACK_HOSTS:
        return
    if os.environ.get("ENVGEN_AUTH_TOKEN", "").strip():
        return
    sys.stderr.write(
        "REFUSING to bind to %s without authentication.\n"
        "The monitor control plane has ~54 ungated *_call mutations (Phase 0.2-EXT scope; see\n"
        "docs/phase_0_2_gate_validation.md). Binding to a non-loopback address without\n"
        "ENVGEN_AUTH_TOKEN exposes them to remote unauthenticated callers.\n"
        "Options:\n"
        "  (a) Bind to 127.0.0.1 (default) - safe for single-user local development\n"
        "  (b) Set ENVGEN_AUTH_TOKEN=<random> and ensure clients send the cookie\n"
        "  (c) Close the Phase 0.2-EXT monitor-layer items before binding remotely\n"
        % host
    )
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live generation monitor server")
    parser.add_argument("--project-dir", help="Single project directory (legacy mode)")
    parser.add_argument("--workspaces-root", help="Parent dir containing per-project workspaces (multi-project mode)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4210)
    args = parser.parse_args()

    # R1+R2 round-4 condition #2: defensive deployment guard. Must run BEFORE
    # any server socket is opened so a refused bind never reaches accept().
    _enforce_bind_guard(args.host)

    if not args.project_dir and not args.workspaces_root:
        parser.error("must supply either --project-dir or --workspaces-root")

    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    workspaces_root = Path(args.workspaces_root).resolve() if args.workspaces_root else None

    # Seed an admin account (unlimited run budget) on first start. Print the
    # generated password ONCE so it can be captured from the console.
    _seeded_pw = seed_admin_account(workspaces_root)
    if _seeded_pw:
        print("=" * 64, flush=True)
        print("  Admin account created (unlimited run budget):", flush=True)
        print("    username: admin", flush=True)
        print(f"    password: {_seeded_pw}", flush=True)
        print(f"  Stored (hashed) in {_users_path()}", flush=True)
        print("=" * 64, flush=True)

    # Cutover 43.19: eagerly import the runtime modules on the main thread before
    # serving. These are otherwise lazily imported inside request handlers, which
    # run on per-request threads under ThreadingHTTPServer — and concurrent first
    # requests can trip Python's import lock into a _DeadlockError. Warming them
    # here (single-threaded) sidesteps that entirely.
    try:
        import multi_agent.runtime  # noqa: F401
        from multi_agent.runtime.project import ProjectIndex  # noqa: F401
        from multi_agent.runtime.hub_registry import HubRegistry  # noqa: F401
    except Exception as _e:
        print(f"[warn] runtime pre-import failed: {_e}", flush=True)

    # Phase 0.2 RE-FIX C: pin the code_check allowlist path NOW so that any
    # later in-process attacker cannot repoint it via ``os.environ`` (defense
    # in depth on top of the process-isolation trust boundary).
    try:
        from multi_agent.runtime.user_gates import freeze_allowlist_path
        freeze_allowlist_path()
    except Exception as _e:
        print(f"[warn] freeze_allowlist_path failed: {_e}", flush=True)

    handler = partial(
        MonitorHandler,
        directory=str(APP_DIR),
        project_dir=project_dir,
        workspaces_root=workspaces_root,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Live monitor listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
