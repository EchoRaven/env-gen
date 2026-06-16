"""
Deterministic task suite executor for Task Runner.

Executes tasks from tasks/tasks.yaml without relying on LLM interpretation.
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from .runtime_tools import TestAPITool
from .browser import PLAYWRIGHT_AVAILABLE, create_browser_tools


logger = logging.getLogger("task_suite_executor")


class ExecuteTaskSuiteTool(BaseTool):
    """Execute tasks/tasks.yaml deterministically and persist structured results."""

    NAME = "execute_task_suite"
    DESCRIPTION = """Execute task suite deterministically from YAML.

This tool:
- loads tasks from tasks/tasks.yaml
- executes actions in deterministic order
- saves per-task JSON results to tasks/execution_results/
- records each result to hub validation store (if hub available)
- routes failures to retry/remediation via hub handle_validation_failure
"""

    def __init__(self, workspace, agent_id: str = "", include_browser: bool = True):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        self.workspace = workspace
        self._agent_id = agent_id
        self._hubs = None  # Injected via set_agent() from HubRegistry
        self._test_api = TestAPITool()
        self._browser_tools: Dict[str, BaseTool] = {}

        if include_browser and PLAYWRIGHT_AVAILABLE:
            try:
                for tool in create_browser_tools(workspace.base_root):
                    self._browser_tools[tool.name] = tool
            except Exception as e:
                logger.warning("Failed to initialize browser tools for suite executor: %s", e)

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "suite_path": {
                        "type": "string",
                        "description": "Path to suite YAML (default: tasks/tasks.yaml)",
                    },
                    "only_task_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional allowlist of task ids",
                    },
                    "stop_on_failure": {
                        "type": "boolean",
                        "description": "Stop immediately when one task fails (default: false)",
                    },
                    "persist_results": {
                        "type": "boolean",
                        "description": "Write JSON result files under tasks/execution_results (default: true)",
                    },
                    "max_auto_retries": {
                        "type": "integer",
                        "description": "Retry budget passed to handle_validation_failure (default: 1)",
                    },
                    "validate_only": {
                        "type": "boolean",
                        "description": "Validate task suite schema/actions only, do not execute (default: false)",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Alias of validate_only for planning stage (default: false)",
                    },
                    "action_timeout_seconds": {
                        "type": "number",
                        "description": "Per-action timeout in seconds (default: 30)",
                    },
                    "task_timeout_seconds": {
                        "type": "number",
                        "description": "Per-task timeout in seconds (default: 300)",
                    },
                    "action_retry_count": {
                        "type": "integer",
                        "description": "Retries for retryable action failures (default: 1)",
                    },
                    "action_retry_backoff_ms": {
                        "type": "integer",
                        "description": "Backoff milliseconds between retries (default: 250)",
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "Max number of tasks to execute concurrently (default: 1)",
                    },
                    "parallel_by_domain": {
                        "type": "boolean",
                        "description": "When concurrent, serialize tasks per conflict domain (default: true)",
                    },
                },
            },
        )

    async def execute(
        self,
        suite_path: str = "tasks/tasks.yaml",
        only_task_ids: Optional[List[str]] = None,
        stop_on_failure: bool = False,
        persist_results: bool = True,
        max_auto_retries: int = 1,
        validate_only: bool = False,
        dry_run: bool = False,
        action_timeout_seconds: float = 30.0,
        task_timeout_seconds: float = 300.0,
        action_retry_count: int = 1,
        action_retry_backoff_ms: int = 250,
        max_concurrent: int = 1,
        parallel_by_domain: bool = True,
    ) -> ToolResult:
        suite_file = self.workspace.resolve(suite_path)
        if not suite_file.exists():
            return ToolResult.fail(f"Task suite not found: {suite_path}")

        try:
            raw = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            return ToolResult.fail(
                "Failed to parse task suite YAML: "
                f"{e}. "
                "Common fix: quote any scalar value containing ':' "
                "(example: name: \"API smoke: health\")."
            )

        tasks = self._normalize_tasks(raw)
        if only_task_ids:
            allow = set(only_task_ids)
            tasks = [t for t in tasks if str(t.get("id", "")) in allow]
        validation = self._validate_task_suite(tasks)

        if not tasks:
            return ToolResult.ok(
                {
                    "suite_path": str(suite_file),
                    "executed": 0,
                    "by_status": {},
                    "message": "No executable tasks found.",
                }
            )

        if validate_only or dry_run:
            return ToolResult.ok(
                {
                    "suite_path": str(suite_file),
                    "mode": "dry_run" if dry_run else "validate_only",
                    "valid": validation.get("valid", False),
                    "validation": validation,
                    "would_execute": len(tasks),
                }
            )

        if not validation.get("valid", False):
            return ToolResult(
                success=False,
                error_message="Task suite validation failed. Use validate_only=true for details.",
                data={
                    "suite_path": str(suite_file),
                    "validation": validation,
                },
            )

        started_at = time.time()
        by_status: Dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        task_reports = await self._execute_task_batch(
            tasks=tasks,
            persist_results=persist_results,
            max_auto_retries=max_auto_retries,
            action_timeout_seconds=action_timeout_seconds,
            task_timeout_seconds=task_timeout_seconds,
            action_retry_count=action_retry_count,
            action_retry_backoff_ms=action_retry_backoff_ms,
            stop_on_failure=stop_on_failure,
            max_concurrent=max_concurrent,
            parallel_by_domain=parallel_by_domain,
        )

        for report in task_reports:
            by_status[report["status"]] = by_status.get(report["status"], 0) + 1

        elapsed = round(time.time() - started_at, 3)
        overall_success = by_status.get("failed", 0) == 0 and by_status.get("error", 0) == 0

        summary = {
            "suite_path": str(suite_file),
            "executed": len(task_reports),
            "elapsed_seconds": elapsed,
            "overall_success": overall_success,
            "by_status": by_status,
            "effective_max_concurrent": max(1, int(max_concurrent or 1)),
            "validation": validation,
            "tasks": [
                {
                    "task_id": r.get("task_id"),
                    "status": r.get("status"),
                    "error_code": r.get("error_code"),
                    "execution_mode": r.get("execution_mode"),
                    "duration_seconds": r.get("duration_seconds"),
                    "result_file": r.get("result_file"),
                }
                for r in task_reports
            ],
        }
        return ToolResult.ok(summary)

    async def _execute_task_batch(
        self,
        tasks: List[Dict[str, Any]],
        persist_results: bool,
        max_auto_retries: int,
        action_timeout_seconds: float,
        task_timeout_seconds: float,
        action_retry_count: int,
        action_retry_backoff_ms: int,
        stop_on_failure: bool,
        max_concurrent: int,
        parallel_by_domain: bool,
    ) -> List[Dict[str, Any]]:
        effective_max = max(1, int(max_concurrent or 1))
        if effective_max == 1:
            reports: List[Dict[str, Any]] = []
            for task in tasks:
                task_id = str(task.get("id") or f"task_{int(time.time() * 1000)}")
                coro = self._execute_single_task(
                    task=task,
                    persist_results=persist_results,
                    max_auto_retries=max_auto_retries,
                    action_timeout_seconds=action_timeout_seconds,
                    task_timeout_seconds=task_timeout_seconds,
                    action_retry_count=action_retry_count,
                    action_retry_backoff_ms=action_retry_backoff_ms,
                )
                report = await self._run_with_task_timeout(
                    coro,
                    task,
                    task_id,
                    task_timeout_seconds,
                    max_auto_retries,
                )
                reports.append(report)
                if stop_on_failure and report["status"] in {"failed", "error"}:
                    break
            return reports

        semaphore = asyncio.Semaphore(effective_max)
        stop_event = asyncio.Event()
        domain_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        indexed_reports: List[Tuple[int, Dict[str, Any]]] = []

        async def _run_one(index: int, task: Dict[str, Any]) -> None:
            if stop_event.is_set():
                return
            domain_key = self._task_conflict_domain(task) if parallel_by_domain else "__any__"
            lock = domain_locks[domain_key]
            async with semaphore:
                async with lock:
                    if stop_event.is_set():
                        return
                    task_id = str(task.get("id") or f"task_{int(time.time() * 1000)}")
                    coro = self._execute_single_task(
                        task=task,
                        persist_results=persist_results,
                        max_auto_retries=max_auto_retries,
                        action_timeout_seconds=action_timeout_seconds,
                        task_timeout_seconds=task_timeout_seconds,
                        action_retry_count=action_retry_count,
                        action_retry_backoff_ms=action_retry_backoff_ms,
                    )
                    report = await self._run_with_task_timeout(
                        coro,
                        task,
                        task_id,
                        task_timeout_seconds,
                        max_auto_retries,
                    )
                    indexed_reports.append((index, report))
                    if stop_on_failure and report["status"] in {"failed", "error"}:
                        stop_event.set()

        await asyncio.gather(*[_run_one(i, t) for i, t in enumerate(tasks)])
        indexed_reports.sort(key=lambda x: x[0])
        return [r for _, r in indexed_reports]

    async def _run_with_task_timeout(
        self,
        coro,
        task: Dict[str, Any],
        task_id: str,
        task_timeout_seconds: float,
        max_auto_retries: int,
    ) -> Dict[str, Any]:
        if task_timeout_seconds and task_timeout_seconds > 0:
            try:
                return await asyncio.wait_for(coro, timeout=float(task_timeout_seconds))
            except asyncio.TimeoutError:
                summary = f"Task timeout after {task_timeout_seconds}s"
                report = {
                    "task_id": task_id,
                    "name": task.get("name", ""),
                    "status": "error",
                    "error_code": "E_TASK_TIMEOUT",
                    "summary": summary,
                    "execution_mode": str(task.get("execution_mode", "auto")).lower(),
                    "actions_executed": 0,
                    "duration_seconds": float(task_timeout_seconds),
                    "trace": [],
                    "remediation_suggestions": [
                        "Task exceeded timeout; split it into smaller tasks or increase task_timeout_seconds."
                    ],
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
                self._record_validation_result(
                    task=task,
                    task_id=task_id,
                    status="error",
                    summary=summary,
                    execution_mode=report["execution_mode"],
                    duration_seconds=float(task_timeout_seconds),
                    artifacts=[],
                    evidence={"error_code": "E_TASK_TIMEOUT"},
                )
                self._handle_validation_failure(
                    task=task,
                    task_id=task_id,
                    summary=summary,
                    action_trace=[],
                    max_auto_retries=max_auto_retries,
                )
                return report
        return await coro

    def _normalize_tasks(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks = raw.get("tasks", [])
        if isinstance(tasks, dict):
            normalized: List[Dict[str, Any]] = []
            for task_id, value in tasks.items():
                if isinstance(value, dict):
                    merged = dict(value)
                    merged.setdefault("id", task_id)
                    normalized.append(merged)
            return normalized
        if isinstance(tasks, list):
            return [t for t in tasks if isinstance(t, dict)]
        return []

    async def _execute_single_task(
        self,
        task: Dict[str, Any],
        persist_results: bool,
        max_auto_retries: int,
        action_timeout_seconds: float,
        task_timeout_seconds: float,
        action_retry_count: int,
        action_retry_backoff_ms: int,
    ) -> Dict[str, Any]:
        task_id = str(task.get("id") or f"task_{int(time.time() * 1000)}")
        execution_mode = str(task.get("execution_mode", "auto")).lower()
        started = time.time()

        action_trace: List[Dict[str, Any]] = []
        artifacts: List[str] = []
        status = "passed"
        state_path: List[str] = []
        summary = "Task executed successfully."
        remediation_suggestions: List[str] = []

        try:
            if isinstance(task.get("actions"), list):
                status, summary = await self._execute_actions_list(
                    task_id=task_id,
                    actions=task.get("actions", []),
                    execution_mode=execution_mode,
                    action_trace=action_trace,
                    artifacts=artifacts,
                    action_timeout_seconds=action_timeout_seconds,
                    action_retry_count=action_retry_count,
                    action_retry_backoff_ms=action_retry_backoff_ms,
                )
            elif isinstance(task.get("states"), dict):
                status, summary, state_path = await self._execute_state_machine(
                    task_id=task_id,
                    task=task,
                    execution_mode=execution_mode,
                    action_trace=action_trace,
                    artifacts=artifacts,
                    action_timeout_seconds=action_timeout_seconds,
                    action_retry_count=action_retry_count,
                    action_retry_backoff_ms=action_retry_backoff_ms,
                )
            else:
                status = "skipped"
                summary = "No executable actions found in task definition."

            if status in {"failed", "error"}:
                remediation_suggestions = self._build_remediation_suggestions(
                    task=task,
                    summary=summary,
                    action_trace=action_trace,
                )

            duration = round(time.time() - started, 3)
            report = {
                "task_id": task_id,
                "name": task.get("name", ""),
                "status": status,
                "error_code": self._task_error_code(status=status, action_trace=action_trace),
                "summary": summary,
                "execution_mode": execution_mode,
                "state_path": state_path,
                "actions_executed": len(action_trace),
                "duration_seconds": duration,
                "artifacts": artifacts,
                "trace": action_trace,
                "remediation_suggestions": remediation_suggestions,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

            result_file = None
            if persist_results:
                result_file = self._persist_task_report(task_id, report)
                report["result_file"] = result_file
                artifacts = [result_file] + artifacts
                report["artifacts"] = artifacts

            self._record_validation_result(
                task=task,
                task_id=task_id,
                status=status,
                summary=summary,
                execution_mode=execution_mode,
                duration_seconds=duration,
                artifacts=artifacts,
                evidence={
                    "actions_executed": len(action_trace),
                    "state_path": state_path,
                    "trace_tail": action_trace[-3:],
                    "remediation_suggestions": remediation_suggestions,
                },
            )

            if status in {"failed", "error"}:
                self._handle_validation_failure(
                    task=task,
                    task_id=task_id,
                    summary=summary,
                    action_trace=action_trace,
                    max_auto_retries=max_auto_retries,
                )

            return report

        except Exception as e:
            duration = round(time.time() - started, 3)
            error_msg = str(e)
            report = {
                "task_id": task_id,
                "name": task.get("name", ""),
                "status": "error",
                "error_code": "E_TASK_EXCEPTION",
                "summary": f"Task execution crashed: {error_msg}",
                "execution_mode": execution_mode,
                "actions_executed": len(action_trace),
                "duration_seconds": duration,
                "trace": action_trace,
                "remediation_suggestions": self._build_remediation_suggestions(
                    task=task,
                    summary=error_msg,
                    action_trace=action_trace,
                ),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            if persist_results:
                report["result_file"] = self._persist_task_report(task_id, report)
                report["artifacts"] = [report["result_file"]]

            self._record_validation_result(
                task=task,
                task_id=task_id,
                status="error",
                summary=report["summary"],
                execution_mode=execution_mode,
                duration_seconds=duration,
                artifacts=report.get("artifacts", []),
                evidence={
                    "trace_tail": action_trace[-3:],
                    "remediation_suggestions": report.get("remediation_suggestions", []),
                },
            )
            self._handle_validation_failure(
                task=task,
                task_id=task_id,
                summary=report["summary"],
                action_trace=action_trace,
                max_auto_retries=max_auto_retries,
            )
            return report

    async def _execute_actions_list(
        self,
        task_id: str,
        actions: List[Dict[str, Any]],
        execution_mode: str,
        action_trace: List[Dict[str, Any]],
        artifacts: List[str],
        action_timeout_seconds: float,
        action_retry_count: int,
        action_retry_backoff_ms: int,
    ) -> Tuple[str, str]:
        if not actions:
            return "skipped", "No actions found in task.actions."
        for idx, action in enumerate(actions, start=1):
            step_result = await self._execute_action(
                task_id=task_id,
                action=action,
                idx=idx,
                execution_mode=execution_mode,
                action_timeout_seconds=action_timeout_seconds,
                action_retry_count=action_retry_count,
                action_retry_backoff_ms=action_retry_backoff_ms,
            )
            action_trace.append(step_result)
            if step_result.get("artifact"):
                artifacts.append(step_result["artifact"])
            if not step_result.get("success", False):
                return "failed", f"Action {idx} failed: {step_result.get('error', 'unknown error')}"
        return "passed", "Task executed successfully."

    async def _execute_state_machine(
        self,
        task_id: str,
        task: Dict[str, Any],
        execution_mode: str,
        action_trace: List[Dict[str, Any]],
        artifacts: List[str],
        action_timeout_seconds: float,
        action_retry_count: int,
        action_retry_backoff_ms: int,
    ) -> Tuple[str, str, List[str]]:
        states = task.get("states", {}) or {}
        transitions = task.get("transitions", []) or []
        if not states:
            return "skipped", "State machine has no states.", []

        current = task.get("initial_state") or next(iter(states.keys()))
        max_steps = int(task.get("max_steps", 50) or 50)
        state_path: List[str] = []
        action_index = 0
        visited_count: Dict[str, int] = {}
        status = "passed"
        summary = "Task executed successfully."
        previous_state_result: Dict[str, Any] = {"success": True}

        for _ in range(max_steps):
            if current not in states:
                status = "error"
                summary = f"State '{current}' not found in states."
                break

            state_path.append(current)
            visited_count[current] = visited_count.get(current, 0) + 1
            if visited_count[current] > 3:
                status = "failed"
                summary = f"Detected potential state loop at '{current}'."
                break

            state = states[current] or {}
            state_type = str(state.get("type", "")).lower()
            state_actions = state.get("actions", [])
            state_success = True
            last_step: Dict[str, Any] = {"success": True}

            if isinstance(state_actions, list):
                for action in state_actions:
                    if not isinstance(action, dict):
                        continue
                    action_index += 1
                    step_result = await self._execute_action(
                        task_id=task_id,
                        action=action,
                        idx=action_index,
                        execution_mode=execution_mode,
                        action_timeout_seconds=action_timeout_seconds,
                        action_retry_count=action_retry_count,
                        action_retry_backoff_ms=action_retry_backoff_ms,
                    )
                    action_trace.append(step_result)
                    last_step = step_result
                    if step_result.get("artifact"):
                        artifacts.append(step_result["artifact"])
                    if not step_result.get("success", False):
                        state_success = False
                        status = "failed"
                        summary = f"State '{current}' action failed: {step_result.get('error', 'unknown error')}"
                        break

            state_result = {
                "success": state_success,
                "state": current,
                "state_type": state_type,
                "last_step": last_step,
                "previous_state": previous_state_result,
            }
            previous_state_result = state_result

            if state_type == "terminal":
                terminal_result = (state.get("metadata") or {}).get("result")
                if isinstance(terminal_result, str) and terminal_result.lower() == "failure":
                    status = "failed"
                    if summary == "Task executed successfully.":
                        summary = f"Reached terminal failure state '{current}'."
                break

            outgoing = [t for t in transitions if isinstance(t, dict) and t.get("from") == current]
            if not outgoing:
                if status == "passed":
                    summary = f"No outgoing transition from state '{current}'."
                break

            next_transition = self._select_next_transition(outgoing, state_result)
            if not next_transition:
                if status == "passed":
                    status = "failed"
                    summary = f"No transition condition matched from state '{current}'."
                break

            next_state = next_transition.get("to")
            if not next_state:
                status = "error"
                summary = f"Transition from '{current}' missing target state."
                break
            current = next_state

        return status, summary, state_path

    async def _execute_action(
        self,
        task_id: str,
        action: Dict[str, Any],
        idx: int,
        execution_mode: str,
        action_timeout_seconds: float,
        action_retry_count: int,
        action_retry_backoff_ms: int,
    ) -> Dict[str, Any]:
        action_type = str(action.get("type", "")).strip()
        params = action.get("params") if isinstance(action.get("params"), dict) else {}

        if not action_type:
            return {
                "index": idx,
                "action_type": action_type,
                "success": False,
                "error": "Missing action.type",
                "error_code": "E_ACTION_INVALID",
            }

        attempts = max(1, int(action_retry_count or 1))
        backoff_s = max(0.0, int(action_retry_backoff_ms or 0) / 1000.0)
        last_result: Dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            try:
                if action_timeout_seconds and action_timeout_seconds > 0:
                    inner = self._execute_action_once(task_id, idx, action_type, params, execution_mode)
                    result = await asyncio.wait_for(inner, timeout=float(action_timeout_seconds))
                else:
                    result = await self._execute_action_once(task_id, idx, action_type, params, execution_mode)
            except asyncio.TimeoutError:
                result = {
                    "success": False,
                    "error": f"Action timeout after {action_timeout_seconds}s",
                    "error_code": "E_ACTION_TIMEOUT",
                }
            except Exception as e:
                result = {"success": False, "error": str(e), "error_code": "E_ACTION_EXCEPTION"}

            result["attempt"] = attempt
            last_result = result
            if result.get("success"):
                return {"index": idx, "action_type": action_type, **result}

            error_code = str(result.get("error_code", ""))
            if attempt >= attempts or not self._is_retryable_failure_code(error_code):
                return {"index": idx, "action_type": action_type, **result}
            if backoff_s > 0:
                await asyncio.sleep(backoff_s)

        return {"index": idx, "action_type": action_type, **last_result}

    async def _execute_action_once(
        self,
        task_id: str,
        idx: int,
        action_type: str,
        params: Dict[str, Any],
        execution_mode: str,
    ) -> Dict[str, Any]:
        if action_type in {"api_call", "request", "assert_api"}:
            return await asyncio.to_thread(self._exec_api_action, action_type, params)

        if execution_mode == "api" and action_type not in {"api_call", "request", "assert_api"}:
            return {
                "success": False,
                "error": f"Non-API action '{action_type}' in execution_mode=api",
                "error_code": "E_ACTION_MODE_MISMATCH",
            }

        return await self._exec_browser_action(task_id=task_id, idx=idx, action_type=action_type, params=params)

    def _exec_api_action(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        method = str(params.get("method", "GET")).upper()
        url = params.get("url")
        path = params.get("path")
        if not url:
            if not path:
                return {"success": False, "error": "api_call requires url or path", "error_code": "E_API_INVALID_INPUT"}
            if str(path).startswith("http://") or str(path).startswith("https://"):
                url = path
            else:
                url = f"http://localhost:8000{path if str(path).startswith('/') else '/' + str(path)}"

        headers = params.get("headers") if isinstance(params.get("headers"), dict) else None
        body_obj = params.get("body")
        body = None
        if body_obj is not None:
            body = body_obj if isinstance(body_obj, str) else json.dumps(body_obj, ensure_ascii=False)

        tool_result = self._test_api.execute(method=method, url=str(url), body=body, headers=headers)
        status = None
        response_text = ""
        if isinstance(tool_result.data, dict):
            status = tool_result.data.get("status")
            response_text = str(tool_result.data.get("response", ""))

        if not tool_result.success:
            status_int = int(status) if isinstance(status, int) else None
            error_code = "E_API_REQUEST_FAILED"
            if status_int is not None and 500 <= status_int <= 599:
                error_code = "E_API_5XX"
            elif status_int is not None and 400 <= status_int <= 499:
                error_code = "E_API_4XX"
            elif "connection" in str(tool_result.error_message or "").lower():
                error_code = "E_API_CONNECTION"
            return {
                "success": False,
                "error": tool_result.error_message or "API request failed",
                "error_code": error_code,
                "status": status,
                "response": response_text,
            }

        if action_type == "assert_api":
            ok, assert_err = self._assert_api_result(params=params, status=status, response_text=response_text)
            if not ok:
                return {
                    "success": False,
                    "error": assert_err,
                    "error_code": "E_API_ASSERTION_FAILED",
                    "status": status,
                    "response": response_text,
                }

        return {
            "success": True,
            "error_code": "OK",
            "status": status,
            "response_preview": response_text[:500],
        }

    def _assert_api_result(self, params: Dict[str, Any], status: Optional[int], response_text: str) -> Tuple[bool, str]:
        expected_status = params.get("expected_status")
        if expected_status is None:
            expected = params.get("expected")
            if isinstance(expected, dict):
                expected_status = expected.get("status")

        if expected_status is not None and int(status or -1) != int(expected_status):
            return False, f"Expected status {expected_status}, got {status}"

        expected_contains = params.get("expected_contains")
        if expected_contains is None:
            expected = params.get("expected")
            if isinstance(expected, dict):
                expected_contains = expected.get("contains")

        if isinstance(expected_contains, str):
            expected_contains = [expected_contains]
        if isinstance(expected_contains, list):
            for token in expected_contains:
                if str(token) not in response_text:
                    return False, f"Response missing expected token: {token}"

        return True, ""

    async def _exec_browser_action(self, task_id: str, idx: int, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._browser_tools:
            return {
                "success": False,
                "error": "Browser tools unavailable (Playwright not installed or disabled).",
                "error_code": "E_UI_BROWSER_UNAVAILABLE",
            }

        if action_type == "navigate":
            url = params.get("url")
            if not url:
                return {"success": False, "error": "navigate requires params.url", "error_code": "E_UI_INVALID_INPUT"}
            if str(url).startswith("/"):
                url = f"http://localhost:3000{url}"
            return await self._run_browser_tool("browser_navigate", {"url": url})

        if action_type == "click":
            payload = self._pick_keys(params, ["selector", "text", "testid", "aria_label", "role", "name", "timeout", "retry"])
            return await self._run_browser_tool("browser_click", payload)

        if action_type in {"type", "fill", "browser_type"}:
            selector = params.get("selector")
            value = params.get("text", params.get("value", ""))
            if not selector:
                return {"success": False, "error": "type/fill requires params.selector", "error_code": "E_UI_INVALID_INPUT"}
            return await self._run_browser_tool("browser_fill", {"selector": selector, "value": str(value)})

        if action_type == "wait":
            # Supports either selector wait or pure sleep.
            selector = params.get("selector")
            if selector:
                payload = self._pick_keys(params, ["selector", "state", "timeout"])
                return await self._run_browser_tool("browser_wait", payload)
            sleep_ms = int(params.get("ms", params.get("duration", 500)))
            await asyncio.sleep(max(0, sleep_ms) / 1000.0)
            return {"success": True, "data": f"slept {sleep_ms}ms"}

        if action_type == "scroll":
            payload = self._pick_keys(params, ["direction", "pixels", "selector"])
            return await self._run_browser_tool("browser_scroll", payload)

        if action_type in {"key", "press_key"}:
            key = params.get("key")
            if not key:
                return {"success": False, "error": "press_key requires params.key", "error_code": "E_UI_INVALID_INPUT"}
            return await self._run_browser_tool("browser_press_key", {"key": str(key)})

        if action_type == "screenshot":
            save_path = params.get("save_path")
            if not save_path:
                save_path = f"tasks/execution_results/screenshots/{task_id}_{idx}.png"
            result = await self._run_browser_tool(
                "browser_screenshot",
                {"full_page": bool(params.get("full_page", False)), "save_path": save_path},
            )
            if result.get("success") and isinstance(result.get("data"), dict):
                result["artifact"] = result["data"].get("saved_to")
            return result

        if action_type in {"ui", "browser"}:
            nested = params.get("action")
            if isinstance(nested, str):
                nested_params = dict(params)
                nested_params.pop("action", None)
                return await self._exec_browser_action(task_id=task_id, idx=idx, action_type=nested, params=nested_params)

        return {
            "success": False,
            "error": f"Unsupported browser action type: {action_type}",
            "error_code": "E_ACTION_UNSUPPORTED",
        }

    async def _run_browser_tool(self, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool = self._browser_tools.get(tool_name)
        if not tool:
            return {"success": False, "error": f"Missing browser tool: {tool_name}"}
        res = await tool.execute(**payload)
        data = res.data if isinstance(res.data, (dict, list, str, int, float, bool, type(None))) else str(res.data)
        error_code = "OK" if res.success else self._infer_browser_error_code(str(res.error_message or ""))
        return {"success": res.success, "error": res.error_message, "error_code": error_code, "data": data}

    def _select_next_transition(self, outgoing: List[Dict[str, Any]], state_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for tr in outgoing:
            if "condition" not in tr:
                return tr
        for tr in outgoing:
            if self._condition_matches(tr.get("condition"), state_result):
                return tr
        return None

    def _condition_matches(self, condition: Any, state_result: Dict[str, Any]) -> bool:
        if condition is None:
            return True
        if isinstance(condition, str):
            key = condition.strip().lower()
            if key in {"success", "on_success", "passed"}:
                return bool(state_result.get("success"))
            if key in {"failure", "on_failure", "failed"}:
                return not bool(state_result.get("success"))
            if key in {"always", "any"}:
                return True
            return False
        if not isinstance(condition, dict):
            return False

        cond_type = str(condition.get("type", "")).strip().lower()
        last_step = state_result.get("last_step") or {}
        response_preview = str(last_step.get("response_preview", ""))
        err = str(last_step.get("error", ""))

        if cond_type in {"always", "any"}:
            return True
        if cond_type in {"on_success", "success"}:
            return bool(state_result.get("success"))
        if cond_type in {"on_failure", "failure"}:
            return not bool(state_result.get("success"))
        if cond_type in {"status_equals", "http_status_equals"}:
            expected = condition.get("value", condition.get("status"))
            actual = last_step.get("status")
            return str(actual) == str(expected)
        if cond_type == "status_in":
            expected = condition.get("value", condition.get("statuses", []))
            return last_step.get("status") in (expected if isinstance(expected, list) else [])
        if cond_type == "response_contains":
            token = str(condition.get("value", condition.get("token", "")))
            return bool(token) and token in response_preview
        if cond_type == "error_contains":
            token = str(condition.get("value", condition.get("token", "")))
            return bool(token) and token.lower() in err.lower()
        if cond_type == "action_type":
            return str(last_step.get("action_type", "")).lower() == str(condition.get("value", "")).lower()
        return False

    def _task_conflict_domain(self, task: Dict[str, Any]) -> str:
        domain = str(task.get("domain", "")).strip().lower()
        if domain:
            return domain
        mode = str(task.get("execution_mode", "auto")).strip().lower()
        if mode in {"browser", "hybrid"}:
            # Browser manager is shared singleton; avoid concurrent UI tasks by default.
            return "ui_shared"
        if mode == "api":
            return "api"
        return "general"

    def _build_remediation_suggestions(
        self,
        task: Dict[str, Any],
        summary: str,
        action_trace: List[Dict[str, Any]],
    ) -> List[str]:
        latest_error = ""
        if action_trace:
            for step in reversed(action_trace):
                err = step.get("error")
                if err:
                    latest_error = str(err)
                    break
        text = f"{summary}\n{latest_error}".lower()
        hints: List[str] = []

        if ("connection refused" in text) or ("failed to establish a new connection" in text):
            hints.append("Backend may not be running; check service startup and API base URL.")
        if ("expected status" in text) or re.search(r"http error:\s*4\d\d", text):
            hints.append("Verify auth/session state and endpoint contract; inspect request body and headers.")
        if ("http error: 5" in text) or ("internal server error" in text):
            hints.append("Investigate backend exception path and database dependencies for this endpoint.")
        if ("selector" in text) or ("strict mode violation" in text) or ("no page open" in text):
            hints.append("Frontend selector likely unstable; prefer data-testid and ensure page routing is correct.")
        if ("playwright" in text) or ("browser tools unavailable" in text):
            hints.append("Ensure Playwright is installed and browser runtime is available before UI tasks.")
        if ("no transition condition matched" in text) or ("state loop" in text):
            hints.append("Review task state machine transitions and condition definitions for determinism.")
        if not hints:
            hints.append("Inspect task trace in tasks/execution_results and reproduce locally with same inputs.")
        # De-duplicate while preserving order.
        seen = set()
        unique: List[str] = []
        for h in hints:
            if h not in seen:
                seen.add(h)
                unique.append(h)
        return unique

    def _infer_browser_error_code(self, error_message: str) -> str:
        text = (error_message or "").lower()
        if "timeout" in text:
            return "E_UI_TIMEOUT"
        if "selector" in text or "strict mode violation" in text:
            return "E_UI_SELECTOR_NOT_FOUND"
        if "no page open" in text:
            return "E_UI_PAGE_NOT_OPEN"
        return "E_UI_ACTION_FAILED"

    def _is_retryable_failure_code(self, error_code: str) -> bool:
        return error_code in {
            "E_ACTION_TIMEOUT",
            "E_UI_TIMEOUT",
            "E_API_CONNECTION",
            "E_API_5XX",
            "E_API_REQUEST_FAILED",
        }

    def _task_error_code(self, status: str, action_trace: List[Dict[str, Any]]) -> str:
        if status == "passed":
            return "OK"
        if status == "skipped":
            return "E_TASK_SKIPPED"
        for step in reversed(action_trace or []):
            code = step.get("error_code")
            if code:
                return str(code)
        return "E_TASK_FAILED"

    def _validate_task_suite(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        supported_types = {
            "api_call",
            "request",
            "assert_api",
            "navigate",
            "click",
            "type",
            "fill",
            "browser_type",
            "wait",
            "scroll",
            "key",
            "press_key",
            "screenshot",
            "ui",
            "browser",
        }

        for i, task in enumerate(tasks):
            task_id = str(task.get("id") or f"index_{i}")
            mode = str(task.get("execution_mode", "auto")).lower()
            if mode not in {"browser", "api", "hybrid", "auto"}:
                issues.append({"task_id": task_id, "code": "E_TASK_INVALID_MODE", "message": f"Unsupported execution_mode: {mode}"})

            has_actions = isinstance(task.get("actions"), list)
            has_states = isinstance(task.get("states"), dict)
            if not has_actions and not has_states:
                issues.append({"task_id": task_id, "code": "E_TASK_EMPTY", "message": "Task has neither actions nor states."})
                continue

            if has_actions:
                self._validate_actions(task_id, task.get("actions", []), mode, supported_types, issues)
            if has_states:
                states = task.get("states", {}) or {}
                if task.get("initial_state") and task.get("initial_state") not in states:
                    issues.append({
                        "task_id": task_id,
                        "code": "E_STATE_INITIAL_MISSING",
                        "message": f"initial_state '{task.get('initial_state')}' not found in states",
                    })
                for state_name, state in states.items():
                    actions = (state or {}).get("actions", [])
                    if isinstance(actions, list):
                        self._validate_actions(task_id, actions, mode, supported_types, issues, state_name=state_name)

        return {"valid": len(issues) == 0, "issues": issues}

    def _validate_actions(
        self,
        task_id: str,
        actions: List[Dict[str, Any]],
        mode: str,
        supported_types: set,
        issues: List[Dict[str, Any]],
        state_name: Optional[str] = None,
    ) -> None:
        for idx, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                issues.append({
                    "task_id": task_id,
                    "state": state_name,
                    "index": idx,
                    "code": "E_ACTION_INVALID",
                    "message": "Action is not an object.",
                })
                continue
            action_type = str(action.get("type", "")).strip()
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            if not action_type:
                issues.append({
                    "task_id": task_id,
                    "state": state_name,
                    "index": idx,
                    "code": "E_ACTION_INVALID",
                    "message": "Missing action.type",
                })
                continue
            if action_type not in supported_types:
                issues.append({
                    "task_id": task_id,
                    "state": state_name,
                    "index": idx,
                    "code": "E_ACTION_UNSUPPORTED",
                    "message": f"Unsupported action.type: {action_type}",
                })
            if mode == "api" and action_type not in {"api_call", "request", "assert_api"}:
                issues.append({
                    "task_id": task_id,
                    "state": state_name,
                    "index": idx,
                    "code": "E_ACTION_MODE_MISMATCH",
                    "message": f"Non-API action '{action_type}' in execution_mode=api",
                })
            if action_type in {"api_call", "request", "assert_api"} and not (params.get("url") or params.get("path")):
                issues.append({
                    "task_id": task_id,
                    "state": state_name,
                    "index": idx,
                    "code": "E_API_INVALID_INPUT",
                    "message": "api action requires params.url or params.path",
                })

    def _record_validation_result(
        self,
        task: Dict[str, Any],
        task_id: str,
        status: str,
        summary: str,
        execution_mode: str,
        duration_seconds: float,
        artifacts: List[str],
        evidence: Dict[str, Any],
    ) -> None:
        if not self._hubs:
            return
        try:
            self._hubs.record_validation_result(
                task_id=task_id,
                status=status,
                agent=self._agent_id,
                summary=summary,
                execution_mode=execution_mode,
                duration_seconds=duration_seconds,
                artifacts=artifacts or [],
                evidence=evidence or {},
                metadata={
                    "check": self._infer_check_type(task_id=task_id, task=task),
                    "domain_hint": task.get("domain"),
                    "error_code": self._task_error_code(status=status, action_trace=evidence.get("trace_tail", [])),
                },
            )
        except Exception as e:
            logger.warning("record_validation_result failed for %s: %s", task_id, e)

    def _handle_validation_failure(
        self,
        task: Dict[str, Any],
        task_id: str,
        summary: str,
        action_trace: List[Dict[str, Any]],
        max_auto_retries: int,
    ) -> None:
        if not self._hubs:
            return
        try:
            domain_hint = self._infer_domain_from_failure(task=task, summary=summary, action_trace=action_trace)
            self._hubs.handle_validation_failure(
                validation_task_id=task_id,
                publisher=self._agent_id,
                domain=domain_hint,
                max_auto_retries=max_auto_retries,
                priority="high",
            )
        except Exception as e:
            logger.warning("handle_validation_failure failed for %s: %s", task_id, e)

    def _persist_task_report(self, task_id: str, report: Dict[str, Any]) -> str:
        out_dir = self.workspace.resolve("tasks/execution_results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{task_id}.json"
        out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            return str(out_file.relative_to(self.workspace.base_root))
        except Exception:
            return str(out_file)

    def _infer_check_type(self, task_id: str, task: Dict[str, Any]) -> str:
        metadata = task.get("metadata")
        if isinstance(metadata, dict) and metadata.get("check"):
            return str(metadata["check"])
        lowered = task_id.lower()
        if "api_smoke" in lowered:
            return "api_smoke"
        if "ui_smoke" in lowered:
            return "ui_smoke"
        return "task"

    def _infer_domain_from_failure(
        self,
        task: Dict[str, Any],
        summary: str,
        action_trace: List[Dict[str, Any]],
    ) -> str:
        explicit = str(task.get("domain", "")).strip().lower()
        if explicit:
            return explicit

        mode = str(task.get("execution_mode", "")).strip().lower()
        if mode == "browser":
            return "frontend"
        if mode == "api":
            return "backend"

        latest_error = ""
        for step in reversed(action_trace):
            if step.get("error"):
                latest_error = str(step.get("error"))
                break
        text = f"{summary}\n{latest_error}".lower()

        if any(k in text for k in ["selector", "dom", "playwright", "browser", "visible", "click failed"]):
            return "frontend"
        if any(k in text for k in ["http error", "status", "endpoint", "/api", "connection refused", "timeout"]):
            return "backend"
        if any(k in text for k in ["sql", "database", "relation", "sqlite", "postgres"]):
            return "database"
        return "any"

    def _pick_keys(self, payload: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
        return {k: payload[k] for k in keys if k in payload and payload[k] is not None}

