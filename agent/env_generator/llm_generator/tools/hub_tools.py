"""Tools for the four collaboration hubs: CodeHub, WorkHub, RegistryHub, EventHub."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from ._base import BaseTool, ToolResult, create_tool_param
from multi_agent.hub_tool_surface import HUB_NAMES, known_hub, writes_for_hub


def _attach_plantool_after_claim(agent_id: str, task_id: str, hub_result: Any) -> None:
    """Bind the calling agent's PlanTool to a successfully-claimed
    task. Best-effort — never raises (deferred import avoids cycle)."""
    if not isinstance(hub_result, dict) or hub_result.get("error"):
        return
    try:
        from .reasoning_tools import PlanTool
        PlanTool.get_instance(agent_id).attach_to_task(task_id)
    except Exception:
        pass


def _detach_plantool_on_terminal(agent_id: str, hub_result: Any) -> None:
    """Unbind the calling agent's PlanTool after a successful
    complete/fail/cancel. Best-effort — never raises."""
    if not isinstance(hub_result, dict) or hub_result.get("error"):
        return
    try:
        from .reasoning_tools import PlanTool
        PlanTool.get_instance(agent_id).detach_from_task()
    except Exception:
        pass


def _coerce_dict_param(value, name: str = "value"):
    """Accept ``value`` as a dict OR a JSON string; return a dict or a
    ToolResult error. Agents commonly JSON-encode dict-typed params (e.g.
    ``schema='{"a":1}'``), which causes the downstream "'str' object is not a
    mapping" error in hub services. This helper coerces them up-front so all
    hub-write tools tolerate both shapes."""
    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return {}
        try:
            import json as _json
            parsed = _json.loads(s)
        except Exception:
            # #658: `ToolResult(error=...)` — `error` IS NOT A FIELD. ToolResult carries
            # success/data/error_message/execution_time/metadata, so every one of these three
            # raised `TypeError: ToolResult.__init__() got an unexpected keyword argument
            # 'error'`. The callers are written correctly ("if isinstance(coerced, ToolResult):
            # return coerced") — the object they check for could simply never be built, so the
            # whole validation-error path was dead and an agent that passed a malformed
            # `decision`/`schema` got a raw TypeError instead of this message.
            # `.fail()` also fixes a second bug hiding behind the first: `success` DEFAULTS TO
            # TRUE, so even had `error=` existed the caller would have returned a SUCCESS result
            # carrying an error string.
            return ToolResult.fail(
                f"{name} must be a JSON object (dict). Got an unparseable string: {s[:120]}")
        if not isinstance(parsed, dict):
            return ToolResult.fail(
                f"{name} must be a JSON object (dict). Got JSON-{type(parsed).__name__}.")
        return parsed
    return ToolResult.fail(f"{name} must be a JSON object (dict). Got {type(value).__name__}.")


def _impl_artifact_expectation_668(rec) -> str:
    """#668: what the code-truth audit is actually looking for, from the record already in hand.

    The denial above told the lane to "BUILD the real page/component/table" and stopped there —
    generic advice for a check with entirely specific criteria. The registry record it had
    ALREADY fetched to read `status` carries them: a ui_page knows its `path`, `component`,
    `route`, `apis_used` and required child `components`; a ui_component knows its `component`
    name and APIs; a table knows its columns.

    Measured over the 249 run logs: 2576 denials across 80 runs, median 20 per run, 456 in the
    worst, and the SAME task refused up to 146 times (impl.component.title_detail_modal x146,
    impl.component.hero_billboard x120, impl.page.browse_home x120). A lane retrying one task
    146 times against a correct message is a lane that believes it is finished and cannot see
    what the audit disagrees about.

    Additive and best-effort: returns "" when the record says nothing, so the message is never
    worse than before. No product literals — every key here is framework schema.
    """
    if not isinstance(rec, dict):
        return ""
    bits = []
    try:
        path = str(rec.get("path") or "").strip()
        comp = str(rec.get("component") or "").strip()
        route = str(rec.get("route") or "").strip()
        if path:
            bits.append(f"file `{path}`")
        if comp:
            bits.append(f"a component named `{comp}`")
        if route:
            bits.append(f"reachable at route `{route}`")
        for key, label in (("apis_used", "calling"), ("components", "containing")):
            val = rec.get(key)
            if isinstance(val, str):
                val = val.strip()
                if val.startswith("["):
                    try:
                        import ast as _ast
                        val = _ast.literal_eval(val)
                    except Exception:
                        val = [val]
                else:
                    val = [val] if val else []
            if isinstance(val, (list, tuple)) and val:
                items = ", ".join(f"`{x}`" for x in list(val)[:6] if str(x).strip())
                if items:
                    bits.append(f"{label} {items}")
        cols = ((rec.get("schema") or {}) if isinstance(rec.get("schema"), dict) else {})
        names = [str((c or {}).get("name")) for c in (cols.get("columns") or [])
                 if isinstance(c, dict) and c.get("name")]
        if names:
            bits.append("with columns " + ", ".join(f"`{n}`" for n in names[:8]))
    except Exception:
        return ""
    if not bits:
        return ""
    return (" WHAT THE AUDIT IS LOOKING FOR (from the registry record): "
            + "; ".join(bits)
            + ". If you believe this already exists, the audit disagrees about one of those "
              "specifics — check the exact name/path/route before retrying, because retrying "
              "the completion cannot change the artifact's status.")


def _finalize_hub_tools(tool_classes):
    """Backfill abstract members for HubTool subclasses that define _run only."""
    import asyncio as _asyncio

    async def _default_execute(tool, **kwargs):
        run_fn = getattr(tool, "_run", None)
        if not callable(run_fn):
            return ToolResult(success=False, error_message=f"Tool has no _run")
        try:
            result = await run_fn(**kwargs)
            return result if isinstance(result, ToolResult) else ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))

    def _default_tool_definition(tool):
        return create_tool_param(
            name=getattr(tool, "NAME", tool.__class__.__name__.lower()),
            description=getattr(tool, "DESCRIPTION", ""),
            parameters=getattr(tool, "PARAMETERS", {"type": "object", "properties": {}}),
            required=[],
        )

    for tool_class in tool_classes:
        if "tool_definition" not in tool_class.__dict__:
            setattr(tool_class, "tool_definition", property(_default_tool_definition))
        if "execute" not in tool_class.__dict__:
            setattr(tool_class, "execute", _default_execute)
        if hasattr(tool_class, "__abstractmethods__"):
            tool_class.__abstractmethods__ = frozenset()


_TERMINAL_ACK_FIELD_LIMIT = 600   # #605: per-field size above which a terminal ack elides


def _elide_large_fields(rec, hint, limit=_TERMINAL_ACK_FIELD_LIMIT):
    """Return ``rec`` with any oversized field replaced by a size + how-to-fetch marker.

    Shared by #605 (a terminal task ack) and #606 (a document LISTING). Field-by-field on
    purpose: every small field a downstream reader might want survives untouched, an error
    result passes through verbatim, and an unserializable value can never crash the caller.
    """
    if not isinstance(rec, Mapping) or rec.get("error"):
        return rec
    out = {}
    for k, v in rec.items():
        try:
            n = len(v) if isinstance(v, str) else len(json.dumps(v, default=str))
        except Exception:
            n = 0
        out[k] = v if n <= limit else f"[{n} chars omitted — {hint}]"
    return out


def _meeting_hint_608(page, meeting_id):
    """#608 — the elision hint for a meeting page: how many decisions it now holds and
    where to read them."""
    n = len((((page or {}).get("metadata") or {}).get("decisions")) or [])
    return (f"the meeting page now holds {n} decisions — read them with "
            f"workhub_get_document(document_id='{(page or {}).get('id', meeting_id)}')")

class HubTool(BaseTool):
    def __init__(self, agent_id: str = "", hub_workspace: Any = None):
        super().__init__(name=getattr(self, "NAME", self.__class__.__name__.lower()), category="hub")
        self._agent_id = agent_id
        self._hubs = hub_workspace

    def set_agent(self, agent) -> None:
        self._agent_id = getattr(agent, "agent_id", self._agent_id)
        # Use _hubs (HubRegistry) directly
        hubs = getattr(agent, "_hubs", None)
        if hubs is not None:
            self._hubs = hubs


class FocusHubTool(HubTool):
    """Move the agent's attention to a hub, unlocking that hub's action tools.

    Intrinsic tool (added to every agent's baseline pool). Read tools for all hubs
    stay available regardless of focus — only WRITE tools are focus-gated. See
    multi_agent/hub_tool_surface.py and the hub-focus filter in
    agents/runtime/step_pipeline/action.py.
    """

    NAME = "focus_hub"
    DESCRIPTION = (
        "Move your attention to one hub so that hub's ACTION (write) tools become "
        "available. Hubs: codehub (code/branches/PRs/releases), workhub "
        "(tasks/plans/pages/decisions), registryhub (endpoints/tables/contracts/MCP), "
        "eventhub (notifications/threads/subscriptions), runhub (app run sessions). "
        "Read tools for EVERY hub and cross-hub awareness stay available regardless "
        "of focus — you only need to focus before you WRITE. Re-call to switch hubs."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "hub": {
                "type": "string",
                "enum": list(HUB_NAMES),
                "description": "Which hub to move your attention to.",
            },
        },
        "required": ["hub"],
    }

    def __init__(self, agent_id: str = "", hub_workspace: Any = None):
        super().__init__(agent_id=agent_id, hub_workspace=hub_workspace)
        self._agent = None

    def set_agent(self, agent) -> None:
        super().set_agent(agent)
        self._agent = agent

    async def _run(self, hub: str) -> ToolResult:
        hub = (hub or "").strip().lower()
        if not known_hub(hub):
            return ToolResult(
                success=False,
                error_message=f"Unknown hub '{hub}'. Choose one of: {', '.join(HUB_NAMES)}.",
            )
        if self._agent is not None:
            setattr(self._agent, "_focus_hub", hub)
            logger = getattr(self._agent, "_logger", None)
            if logger is not None:
                logger.info(f"[{getattr(self._agent, 'agent_id', '?')}] focus_hub -> {hub}")
        return ToolResult(data={
            "focused_hub": hub,
            "action_tools_now_available": sorted(writes_for_hub(hub)),
            "note": "Read tools for all hubs remain available; re-call focus_hub to switch.",
        })


class CodeHubCommitTool(HubTool):
    NAME = "codehub_commit"
    DESCRIPTION = (
        "Commit staged or specified files to this agent's own worktree branch in CodeHub. "
        "Runs real git add + git commit; appends an [agent: <id>] trailer to the message."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message."},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific files to stage. Omit to stage all changes.",
            },
        },
        "required": ["message"],
    }

    async def _run(self, message: str, files: Optional[list] = None) -> ToolResult:
        return ToolResult(data=self._hubs.codehub.commit(self._agent_id, message, files=files))


class CodeHubRegisterRepoTool(HubTool):
    NAME = "codehub_register_repo"
    DESCRIPTION = "Register this agent's local repo/worktree with CodeHub."
    PARAMETERS = {"type": "object", "properties": {"worktree_path": {"type": "string"}, "repo_id": {"type": "string"}}, "required": ["worktree_path"]}

    async def _run(self, worktree_path: str, repo_id: str = "main") -> ToolResult:
        return ToolResult(data=self._hubs.codehub.register_agent_repo(self._agent_id, worktree_path, repo_id=repo_id))


class CodeHubRecordCommitTool(HubTool):
    NAME = "codehub_record_commit"
    DESCRIPTION = "Record a commit on an agent branch in CodeHub metadata."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}},
            "diff_summary": {"type": "string"},
            "commit_hash": {"type": "string"},
            "repo_id": {"type": "string"},
        },
        "required": ["branch", "files", "diff_summary"],
    }

    async def _run(self, branch: str, files: list, diff_summary: str, commit_hash: Optional[str] = None, repo_id: str = "main") -> ToolResult:
        return ToolResult(data=self._hubs.codehub.record_commit(self._agent_id, branch, files, diff_summary, commit_hash=commit_hash, repo_id=repo_id))


class CodeHubOpenPRTool(HubTool):
    NAME = "codehub_open_pr"
    DESCRIPTION = (
        "Open a GitHub-like pull request into CodeHub main. "
        "`linked_tasks` is REQUIRED (must be non-empty, all IDs must exist in WorkHub). "
        "At least 2 distinct reviewers are required (excluding the PR author); "
        "orchestrator is auto-injected if the author is not orchestrator and the count is short. "
        "Optional: `linked_apis` (must be registered in RegistryHub), "
        "`linked_pages` (WorkHub page IDs), `linked_consumers` (RegistryHub consumer keys)."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string"},
            "target": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "string"}},
            "linked_tasks": {"type": "array", "items": {"type": "string"}, "description": "Required. WorkHub task IDs addressed by this PR."},
            "linked_apis": {"type": "array", "items": {"type": "string"}},
            "linked_pages": {"type": "array", "items": {"type": "string"}, "description": "WorkHub page IDs related to this PR."},
            "linked_consumers": {"type": "array", "items": {"type": "string"}, "description": "RegistryHub consumer keys (file:agent pairs) referenced by this PR."},
            "title": {"type": "string"},
            "description": {"type": "string", "description": "Optional PR body (summary of what changed and why)."},
        },
        "required": ["branch", "linked_tasks"],
    }

    async def _run(self, branch: str, linked_tasks: list, target: str = "main", reviewers: Optional[list] = None, linked_apis: Optional[list] = None, linked_pages: Optional[list] = None, linked_consumers: Optional[list] = None, title: str = "", description: str = "") -> ToolResult:
        result = self._hubs.codehub.open_pull_request(
            branch, target=target,
            reviewers=reviewers or [],
            linked_tasks=linked_tasks or [],
            linked_apis=linked_apis or [],
            linked_pages=linked_pages or [],
            linked_consumers=linked_consumers or [],
            title=title, description=description, author=self._agent_id,
        )
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"], data=result)
        return ToolResult(data=result)


class CodeHubRecordCheckTool(HubTool):
    NAME = "codehub_record_check"
    DESCRIPTION = (
        "Record a build / validation / artifact check against a CodeHub PR "
        "(or against pr_id='main' for repo-level checks). The orchestrator "
        "delivery gate reads these to verify build:* and validation:* "
        "evidence is present before accepting deliver_project. "
        "Authorship: caller must be in {orchestrator, pr.checks_authorized, "
        "pr.reviewers} OR the PR must not yet exist (orphan-check "
        "back-compat). Status conventions: 'success' / 'failure' / "
        "'recorded' / 'in_progress'. Use names like 'build:sql_syntax', "
        "'build:docker_build', 'build:npm_install', 'build:backend_start', "
        "'validation:api_smoke', 'validation:ui_smoke', "
        "'validation:ui_flow:<flow_name>', 'validation:release_readiness'."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {
                "type": "string",
                "description": (
                    "CodeHub PR id (e.g. 'pr_42') or 'main' for "
                    "repo-level / pre-PR checks recorded against the "
                    "integration branch."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Check name, e.g. 'build:sql_syntax' or "
                    "'validation:api_smoke'. Use the colon-prefixed form "
                    "the orchestrator delivery gate reads."
                ),
            },
            "status": {
                "type": "string",
                "description": "One of: success, failure, recorded, in_progress",
            },
            "evidence": {
                "type": "object",
                "description": (
                    "Free-form mapping with check output, links to logs, "
                    "step counts, etc. Persisted verbatim for audit."
                ),
            },
        },
        "required": ["pr_id", "name", "status"],
    }

    async def _run(
        self,
        pr_id: str,
        name: str,
        status: str,
        evidence: Optional[dict] = None,
    ) -> ToolResult:
        result = self._hubs.codehub.record_check(
            pr_id=pr_id,
            name=name,
            status=status,
            evidence=evidence or {},
            agent=self._agent_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return ToolResult(
                success=False,
                error_message=str(result.get("error")),
                data=result,
            )
        return ToolResult(data=result)


class CodeHubReviewPRTool(HubTool):
    NAME = "codehub_review_pr"
    DESCRIPTION = (
        "Submit a CodeHub PR review (approve / request_changes / comment). "
        "Supply `inline_comments` to leave file:line-bound comments on specific code lines. "
        "For state='approve', you MUST supply at least one inline_comment (citing a real "
        "diff line) AND at least one considered_alternatives entry (an approach you "
        "evaluated and chose not to recommend). Empty approve = rejected."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string"},
            "state": {"type": "string", "enum": ["approve", "request_changes", "comment"]},
            "comments": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Free-form summary comments (overall feedback).",
            },
            "inline_comments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "description": "Path relative to repo root."},
                        "line": {"type": "integer", "description": "1-indexed line number."},
                        "body": {"type": "string"},
                    },
                    "required": ["file", "line", "body"],
                },
                "description": "Structured comments bound to specific file:line locations. "
                               "Required (>=1) when state='approve'.",
            },
            "considered_alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Alternative approaches you evaluated and chose not to recommend, "
                               "with a short reason. Required (>=1 non-empty entry) when "
                               "state='approve'.",
            },
        },
        "required": ["pr_id", "state"],
    }

    async def _run(self, pr_id: str, state: str, comments: Optional[list] = None,
                   inline_comments: Optional[list] = None,
                   considered_alternatives: Optional[list] = None) -> ToolResult:
        result = self._hubs.codehub.submit_review(
            pr_id, self._agent_id, state,
            comments=comments or [],
            inline_comments=inline_comments or [],
            considered_alternatives=considered_alternatives or [],
        )
        if isinstance(result, dict) and "error" in result:
            return ToolResult(success=False, error_message=result["error"], data=result)
        return ToolResult(data=result)


class CodeHubListInlineCommentsTool(HubTool):
    NAME = "codehub_list_inline_comments"
    DESCRIPTION = "List all inline (file:line-bound) comments left on a CodeHub PR, optionally filtered by file."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string"},
            "file": {"type": "string", "description": "Optional file-path filter."},
        },
        "required": ["pr_id"],
    }

    async def _run(self, pr_id: str, file: Optional[str] = None) -> ToolResult:
        return ToolResult(data={
            "inline_comments": self._hubs.codehub.list_inline_comments(pr_id, file=file),
        })


class CodeHubSuggestReviewersTool(HubTool):
    NAME = "codehub_suggest_reviewers"
    DESCRIPTION = (
        "Suggest the top-k reviewer candidates for a CodeHub PR based on API consumers, "
        "recent committers, and plan attendees. Always call this before codehub_open_pr to "
        "identify at least 2 suitable reviewers. Returns {\"suggestions\": [{agent, score, reasons}, ...]}."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "The branch being submitted as a PR."},
            "linked_apis": {"type": "array", "items": {"type": "string"}, "description": "RegistryHub endpoint IDs touched by this PR."},
            "linked_tasks": {"type": "array", "items": {"type": "string"}, "description": "WorkHub task IDs linked to this PR."},
            "k": {"type": "integer", "description": "Maximum number of suggestions to return (default 3)."},
        },
        "required": ["branch"],
    }

    async def _run(self, branch: str, linked_apis: Optional[list] = None, linked_tasks: Optional[list] = None, k: int = 3) -> ToolResult:
        suggestions = self._hubs.codehub.suggest_reviewers(
            branch, linked_apis=linked_apis or [], linked_tasks=linked_tasks or [],
            author=self._agent_id, k=k,
        )
        return ToolResult(data={"suggestions": suggestions})


class CodeHubForceMergeTool(HubTool):
    NAME = "codehub_force_merge"
    DESCRIPTION = (
        "ORCHESTRATOR ONLY. Force-merge a CodeHub PR, bypassing the verifier premerge gate. "
        "Requires a substantive reason (>= 20 characters) for the audit trail. "
        "Emits an urgent pr_force_merged event to all reviewers. "
        "Use only in exceptional circumstances (e.g., production outage hotfix)."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string", "description": "ID of the PR to force-merge."},
            "reason": {"type": "string", "description": "Substantive justification for bypassing the gate (>= 20 chars)."},
        },
        "required": ["pr_id", "reason"],
    }

    async def _run(self, pr_id: str, reason: str) -> ToolResult:
        result = self._hubs.codehub.force_merge_pull_request(pr_id, reason, agent=self._agent_id)
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"], data=result)
        return ToolResult(data=result)


class CodeHubMergePRTool(HubTool):
    NAME = "codehub_merge_pr"
    DESCRIPTION = "Merge a ready CodeHub PR into main."
    PARAMETERS = {"type": "object", "properties": {"pr_id": {"type": "string"}, "strategy": {"type": "string"}}, "required": ["pr_id"]}

    async def _run(self, pr_id: str, strategy: str = "squash") -> ToolResult:
        return ToolResult(data=self._hubs.codehub.merge_pull_request(pr_id, strategy=strategy, agent=self._agent_id))


class CodeHubRevertCommitTool(HubTool):
    """Revert a commit on a branch (default: ``integration``) by adding
    an inverse commit. Safe history op — does not rewrite published
    history. Use to undo a bad merge / a broken auto-commit.
    """

    NAME = "codehub_revert_commit"
    DESCRIPTION = (
        "Revert a commit on a branch (default ``integration``). Adds an "
        "inverse commit so existing pulls don't break. Use this when an "
        "agent's auto-committed work introduced a regression and the "
        "fastest recovery is to back it out, then re-do correctly."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "commit_sha": {
                "type": "string",
                "description": "SHA (full or short) of the commit to revert.",
            },
            "branch": {
                "type": "string",
                "description": "Branch the commit lives on (default ``integration``).",
            },
        },
        "required": ["commit_sha"],
    }

    async def _run(self, commit_sha: str, branch: str = "integration") -> ToolResult:
        from multi_agent.agents.runtime.auto_commit import revert_commit_on_branch
        repo_root = getattr(self._hubs.codehub, "repo_root", None)
        if repo_root is None:
            return ToolResult(success=False, error_message="codehub.repo_root not available")
        ok, info = revert_commit_on_branch(
            repo_root=repo_root, branch=branch, commit_sha=commit_sha,
            actor=str(self._agent_id),
        )
        if not ok:
            return ToolResult(success=False, error_message=info)
        return ToolResult(data={"reverted": commit_sha, "new_head": info, "branch": branch})


class CodeHubResolveMergeConflictTool(HubTool):
    """Resolve a previously-reported ``merge_conflict`` between an agent's
    branch and the ``integration`` branch by re-attempting the merge with
    a strategy option (``-X theirs`` / ``-X ours``).

    Typical use: orchestrator receives a ``merge_conflict`` urgent
    event with payload ``{"agent": "...", "source_branch": "agent/X",
    "target_branch": "integration", "detail": "..."}``. Orchestrator
    inspects the situation (optionally via ``codehub_get_diff``) and
    calls this tool with ``strategy="agent"`` (incoming wins) or
    ``strategy="integration"`` (existing wins).
    """

    NAME = "codehub_resolve_merge_conflict"
    DESCRIPTION = (
        "Re-attempt a merge of an agent's branch into ``integration`` with "
        "a strategy option after a ``merge_conflict`` event. Use "
        "``strategy='agent'`` when the agent's incoming work should win "
        "(default reasoning: the agent is the one who triggered the merge "
        "and has the freshest changes). Use ``strategy='integration'`` "
        "when the existing integration version has already been validated "
        "and the new agent should defer."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "agent_branch": {
                "type": "string",
                "description": "Source branch (e.g. ``agent/backend``).",
            },
            "strategy": {
                "type": "string",
                "enum": ["agent", "integration"],
                "description": "Which side wins on conflict.",
            },
            "main_branch": {
                "type": "string",
                "description": "Target branch (default ``integration``).",
            },
        },
        "required": ["agent_branch", "strategy"],
    }

    async def _run(self, agent_branch: str, strategy: str, main_branch: str = "integration") -> ToolResult:
        from multi_agent.agents.runtime.auto_commit import resolve_merge_conflict_via_strategy
        repo_root = getattr(self._hubs.codehub, "repo_root", None)
        if repo_root is None:
            return ToolResult(success=False, error_message="codehub.repo_root not available")
        # Derive agent_id from the branch name for commit author attribution.
        agent_id = agent_branch.split("/", 1)[-1] if "/" in agent_branch else agent_branch
        ok, info = resolve_merge_conflict_via_strategy(
            repo_root=repo_root,
            agent_branch=agent_branch,
            main_branch=main_branch,
            strategy=strategy,
            agent_id=agent_id,
        )
        if not ok:
            return ToolResult(success=False, error_message=info)
        return ToolResult(data={"resolved": True, "head": info, "strategy": strategy})


class CodeHubCreateReleaseTool(HubTool):
    NAME = "codehub_create_release"
    DESCRIPTION = (
        "Create a release tag from CodeHub main (orchestrator-only). A release is "
        "GATED: it requires a successful RunHub run on record — the app must compose-up, "
        "the frontend must pass its healthcheck (renders), and every endpoint/MCP probe "
        "must pass (status=completed, 0 failures). Run `run_start(...)` and ensure it "
        "passes before cutting a release."
    )
    PARAMETERS = {"type": "object", "properties": {"tag": {"type": "string"}, "source": {"type": "string"}, "notes": {"type": "string"}}, "required": ["tag"]}

    async def _run(self, tag: str, source: str = "main", notes: str = "") -> ToolResult:
        # Hard gate: a release must have a passing render + functional check.
        runhub = getattr(self._hubs, "runhub", None)
        ok_run = None
        if runhub is not None and hasattr(runhub, "last_successful_run_since"):
            try:
                ok_run = runhub.last_successful_run_since(0.0)
            except Exception:
                ok_run = None
        if not ok_run:
            return ToolResult(
                success=False,
                error_message=(
                    "Release blocked — no successful run on record. A release requires a "
                    "RunHub run with status=completed and 0 failures (frontend healthcheck "
                    "passed + all endpoint/MCP probes passed). Call run_start(...) first and "
                    "ensure it passes, then retry."
                ),
            )
        return ToolResult(data=self._hubs.codehub.create_release(tag, source=source, notes=notes, agent=self._agent_id))


class WorkHubCreateDocumentTool(HubTool):
    NAME = "workhub_create_document"
    DESCRIPTION = (
        "Create a Notion-like WorkHub coordination document (kickoff/meeting/"
        "retro/project/general notes). NOTE: this is NOT a UI page — UI pages "
        "are registered via registryhub_register_ui_page into RegistryHub."
    )
    PARAMETERS = {"type": "object", "properties": {"title": {"type": "string"}, "parent": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]}

    async def _run(self, title: str, parent: Optional[str] = None, attendees: Optional[list] = None) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.create_document(title, parent=parent, attendees=attendees or [], agent=self._agent_id))


class WorkHubUpdatePageTool(HubTool):
    NAME = "registryhub_register_ui_page"
    DESCRIPTION = (
        "Register a UI page into RegistryHub (kind='ui_page'), keyed by ``name`` — "
        "the spec-to-file mapping (path/components/reference). NOTE: you cannot "
        "set status='implemented' — the FRAMEWORK audits the code (component "
        "exists + route wired + declared APIs called + controls bound) and flips "
        "the status itself; agent-supplied 'implemented' is downgraded to "
        "'defined'. Check your lifecycle status via registryhub_list_ui_pages."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Logical page name (e.g. 'Login', 'HomeFeed')"},
            "path": {"type": "string", "description": "Relative source path (e.g. 'frontend/src/pages/Login.jsx')"},
            "status": {"type": "string", "enum": ["defined", "deprecated"], "default": "defined"},
            "components": {"type": "array", "items": {"type": "string"}, "description": "Optional component names this page renders"},
            "reference_image": {"type": "string", "description": "Optional screenshot filename from list_reference_images()"},
            "notes": {"type": "string"},
        },
        "required": ["name"],
    }

    async def _run(
        self,
        name: str,
        path: str = "",
        status: str = "defined",
        components: Optional[list] = None,
        reference_image: str = "",
        notes: str = "",
    ) -> ToolResult:
        data = {"status": status}
        if path:
            data["path"] = path
        if components:
            data["components"] = list(components)
        if reference_image:
            data["reference_image"] = reference_image
        if notes:
            data["notes"] = notes
        return ToolResult(data=self._hubs.workhub.update_ui_page(
            name=name, data=data, agent=self._agent_id,
        ))


class WorkHubTaskTool(HubTool):
    NAME = "workhub_task"

    DESCRIPTION = "Create, claim, claim_all, complete, fail, or cancel a WorkHub task."
    PARAMETERS = {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "claim", "claim_all", "complete", "fail", "cancel"], "description": "claim_all = claim EVERY pending unclaimed task assigned to you in one call (dep-blocked tasks are skipped automatically); no task_id needed."}, "task_id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"}, "assignee": {"type": "string"}, "result": {"type": "object"}, "evidence": {"type": "object"}, "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "default": "P2", "description": "Task priority (P0=urgent, P3=nice-to-have); used only when action=create"}, "reason": {"type": "string", "description": "Why the task failed/was cancelled (action=fail|cancel)"}}, "required": ["action"]}

    # Round 8h+ (Instagram run #4): real LLMs frequently call this single
    # workhub_task tool with action="fail"/"cancel" + a ``reason`` kwarg
    # (conflating it with the sibling workhub_fail_task / workhub_cancel_task
    # tools), which crashed _run with "unexpected keyword argument 'reason'"
    # (22 hard failures in one episode). Accept ``reason`` + route fail/cancel
    # here so the call succeeds; ``**_ignored`` tolerates any other stray kwargs
    # rather than hard-failing a whole step on an extra field.
    async def _run(self, action: str, task_id: Optional[str] = None, title: str = "", description: str = "", assignee: Optional[str] = None, result: Optional[dict] = None, evidence: Optional[dict] = None, priority: str = "P2", reason: str = "", **_ignored) -> ToolResult:
        if action == "create":
            return ToolResult(data=self._hubs.workhub.create_task(title=title, description=description, assignee=assignee, agent=self._agent_id, task_id=task_id, priority=priority))
        if action == "claim":
            hub_result = self._hubs.workhub.claim_task(task_id, self._agent_id)
            _attach_plantool_after_claim(self._agent_id, task_id, hub_result)
            return ToolResult(data=hub_result)
        if action == "claim_all":
            return self._claim_all()
        def _ack(rec):
            """#605 — a TERMINAL action echoes back the task the caller already holds.

            `complete`/`fail`/`cancel` returned the whole record, and a WorkHub task record
            is not small: over the arc's 4736 stored tasks `description` alone is 17.07 MB of
            ~22 MB, with single descriptions up to 102,615 chars (~25k tokens) — the visual
            gate's remediation order inlines all ten screens' fixes into one task. Measured on
            the run logs, `workhub_task` returned 20.76 MB over 379 calls at an average of
            54k chars REGARDLESS of action, and 11.91 MB of that (57%) is complete/fail
            echoing a work order back to the lane that just executed it.

            `claim` keeps the full record — that IS the work order being delivered. Only the
            terminal actions are trimmed, and only field-by-field above a threshold, so every
            small field a downstream reader might want survives untouched. An error result is
            passed through verbatim.
            """
            return _elide_large_fields(
                rec, f"unchanged by this call; re-read with "
                     f"workhub_get_task(task_id='{(rec or {}).get('id', task_id)}')"
                if isinstance(rec, Mapping) else "")

        if action == "complete":
            # CODE-TRUTH GUARD (2026-06-24): a lane may NOT manually 'complete' an
            # impl.* task whose registry artifact is still 'defined' (NOT
            # 'implemented'). impl tasks are AUTO-COMPLETED by the framework's
            # code-truth sync WHEN the audit flips the artifact to 'implemented'; a
            # lane completing one manually (result={}) over an unbuilt / stub
            # artifact FALSE-COMPLETES it. v9 wedge: the frontend bulk-completed 11
            # page + 8 component tasks with result={} while the audit showed them all
            # still 'defined' → 0 pending tasks → never re-woken → run wedged. The
            # framework sync calls workhub.complete_task DIRECTLY (bypassing this
            # tool), so this only catches the lane path. Best-effort + fail-open:
            # blocks ONLY when the artifact is resolvable AND not implemented.
            _blocked_status = None
            _blocked_rec = None
            try:
                _tid = str(task_id or "")
                _rh = getattr(self._hubs, "registryhub", None)
                _amap = None
                _akey = None
                for _pfx, _getter in (
                    ("impl.page.", "list_ui_pages"),
                    ("impl.component.", "list_ui_components"),
                    ("impl.table.", "list_tables"),
                ):
                    if _tid.startswith(_pfx) and _rh is not None and hasattr(_rh, _getter):
                        _amap = getattr(_rh, _getter)() or {}
                        _akey = _tid[len(_pfx):]
                        break
                if _amap is not None and _akey:
                    _rec = _amap.get(_akey)
                    _s = _rec.get("status") if isinstance(_rec, dict) else None
                    if _s and _s != "implemented":
                        _blocked_status = _s
                        _blocked_rec = _rec if isinstance(_rec, dict) else None
            except Exception:
                _blocked_status = None
            if _blocked_status:
                return ToolResult(success=False, error_message=(
                    f"complete denied: impl task '{task_id}' — its artifact is still "
                    f"'{_blocked_status}' (NOT 'implemented') in the registry. impl.* "
                    "tasks are AUTO-COMPLETED by the framework when the code-truth audit "
                    "confirms your code makes the artifact REAL. Do NOT complete them "
                    "manually: BUILD the real page/component/table (a stub or "
                    "placeholder does NOT count — the audit demotes it), and the task "
                    "completes ITSELF when the artifact flips to 'implemented'. Manually "
                    "completing an unbuilt artifact is a false-complete that wedges the "
                    "run (status diverges from code-truth + the task drops off your "
                    "queue so you're never re-woken to finish it)."
                    + _impl_artifact_expectation_668(_blocked_rec)))
            hub_result = self._hubs.workhub.complete_task(task_id, self._agent_id, result=result or {}, evidence=evidence or {})
            _detach_plantool_on_terminal(self._agent_id, hub_result)
            return ToolResult(data=_ack(hub_result))   # #605
        if action in ("fail", "failed"):
            hub_result = self._hubs.workhub.fail_task(task_id, self._agent_id, reason=reason or "")
            _detach_plantool_on_terminal(self._agent_id, hub_result)
            return ToolResult(data=_ack(hub_result))   # #605
        if action in ("cancel", "cancelled", "canceled"):
            hub_result = self._hubs.workhub.cancel_task(task_id, self._agent_id, reason=reason or "")
            _detach_plantool_on_terminal(self._agent_id, hub_result)
            return ToolResult(data=_ack(hub_result))   # #605
        return ToolResult(success=False, error_message=f"Unknown workhub_task action: {action!r}. Valid: create|claim|claim_all|complete|fail|cancel")

    def _claim_all(self) -> ToolResult:
        """Claim EVERY pending, unclaimed task assigned to this agent in a
        single call, skipping dep-blocked ones.

        Why this exists: ``ClaimAssignedTasksPolicy`` blocks ``finish()`` while
        the agent has unclaimed assigned tasks. There was no bulk-claim, so an
        agent with N assigned tasks had to make N individual
        ``workhub_task(action='claim')`` round-trips (the youtube run made 46).
        This collapses them into one.

        Enumeration + dep-blocked filtering MIRROR ``ClaimAssignedTasksPolicy``
        exactly (``_collect_unclaimed_assigned`` / ``_split_dep_blocked``) so the
        tool and the gate agree on what's claimable. Dep-blocked tasks are
        skipped because ``claim_task`` hard-rejects them (service.py:494-503) —
        attempting them is a guaranteed-fail loop. Claiming uses the same path
        the single ``claim`` action uses (``workhub.claim_task`` +
        PlanTool attach).

        Returns a compact summary:
            {"claimed": [ids...], "skipped_dep_blocked": [ids...],
             "failed": [{"task_id":..., "error":...}], "claimed_count": N}
        """
        workhub = getattr(self._hubs, "workhub", None) if self._hubs else None
        if workhub is None:
            return ToolResult(success=False, error_message="No workhub available for claim_all")
        unclaimed = self._collect_unclaimed_assigned(workhub, self._agent_id)
        actionable, dep_blocked = self._split_dep_blocked(workhub, unclaimed)
        claimed: list = []
        failed: list = []
        for task in actionable:
            tid = task.get("id")
            if not tid:
                continue
            hub_result = workhub.claim_task(tid, self._agent_id)
            if isinstance(hub_result, dict) and hub_result.get("error"):
                failed.append({"task_id": tid, "error": hub_result.get("error")})
                continue
            _attach_plantool_after_claim(self._agent_id, tid, hub_result)
            claimed.append(tid)
        return ToolResult(data={
            "claimed": claimed,
            "skipped_dep_blocked": [t.get("id") for t in dep_blocked if t.get("id")],
            "failed": failed,
            "claimed_count": len(claimed),
        })

    @staticmethod
    def _collect_unclaimed_assigned(workhub: Any, agent_id: str) -> list:
        """Pending tasks where assignee==agent_id and claimed_by is empty.

        Mirrors ``ClaimAssignedTasksPolicy._collect_unclaimed_assigned`` (read
        the same ``workhub.stores.tasks`` store; tolerate shape variations and
        return [] on any error)."""
        try:
            stores = getattr(workhub, "stores", None)
            store = getattr(stores, "tasks", None) if stores else None
            if store is None:
                return []
            value = store.value() if hasattr(store, "value") else store
        except Exception:
            return []
        if not isinstance(value, dict):
            return []
        out: list = []
        for task in value.values():
            if not isinstance(task, dict):
                continue
            if task.get("assignee") != agent_id:
                continue
            if task.get("status") != "pending":
                continue
            if task.get("claimed_by"):
                continue
            out.append(task)
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

        def _key(t: dict):
            meta = t.get("metadata") or {}
            prio = meta.get("priority") or meta.get("severity") or "P2"
            return (order.get(prio, 99), t.get("created_at", 0.0))

        out.sort(key=_key)
        return out

    @staticmethod
    def _split_dep_blocked(workhub: Any, tasks: list):
        """Partition ``tasks`` into (actionable, dep_blocked).

        A task is dep-blocked if any of its ``depends_on`` tasks has status
        != 'completed' — matching ``claim_task``'s rejection (service.py:
        494-503) and ``ClaimAssignedTasksPolicy._split_dep_blocked`` exactly."""
        try:
            store = workhub.stores.tasks
            value = store.value() if hasattr(store, "value") else store
        except Exception:
            value = {}
        if not isinstance(value, dict):
            value = {}
        actionable: list = []
        dep_blocked: list = []
        for t in tasks:
            deps = t.get("depends_on") or []
            blocked = False
            for dep_id in deps:
                dep = value.get(dep_id)
                if dep is None or (isinstance(dep, dict) and dep.get("status") != "completed"):
                    blocked = True
                    break
            (dep_blocked if blocked else actionable).append(t)
        return actionable, dep_blocked


class WorkHubFailTaskTool(HubTool):
    NAME = "workhub_fail_task"
    DESCRIPTION = "Mark a claimed WorkHub task as failed with an optional reason."
    PARAMETERS = {"type": "object", "properties": {"task_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["task_id"]}

    async def _run(self, task_id: str, reason: str = "") -> ToolResult:
        hub_result = self._hubs.workhub.fail_task(task_id, self._agent_id, reason=reason)
        _detach_plantool_on_terminal(self._agent_id, hub_result)
        return ToolResult(data=hub_result)


class WorkHubCancelTaskTool(HubTool):
    NAME = "workhub_cancel_task"
    DESCRIPTION = (
        "Cancel a WorkHub task (must not be in a terminal state). "
        "Optionally pass ``reason`` so downstream agents and "
        "post-mortem reviews can see WHY it was cancelled."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "reason": {"type": "string",
                        "description": "Why the task is being cancelled."},
        },
        "required": ["task_id"],
    }

    async def _run(self, task_id: str, reason: str = "") -> ToolResult:
        hub_result = self._hubs.workhub.cancel_task(
            task_id, self._agent_id, reason=reason,
        )
        _detach_plantool_on_terminal(self._agent_id, hub_result)
        return ToolResult(data=hub_result)


class WorkHubGetTaskTool(HubTool):
    NAME = "workhub_get_task"
    DESCRIPTION = "Get a single WorkHub task by its id."
    PARAMETERS = {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}

    async def _run(self, task_id: str) -> ToolResult:
        task = self._hubs.workhub.get_task(task_id)
        if task is None:
            return ToolResult(success=False, error_message=f"Task not found: {task_id}")
        return ToolResult(data=task)


class WorkHubListTasksTool(HubTool):
    NAME = "workhub_list_tasks"
    DESCRIPTION = "List WorkHub tasks, optionally filtered by assignee, status, domain, or plan_id."
    PARAMETERS = {"type": "object", "properties": {"assignee": {"type": "string"}, "status": {"type": "string"}, "domain": {"type": "string"}, "plan_id": {"type": "string"}}}

    # #305 CONTEXT: fields worth keeping in a LIST scan; the heavy content
    # (description/evidence/metadata/result) is dropped and recoverable via
    # workhub_get_task(id).
    _KEEP = ("id", "title", "status", "assignee", "plan_id", "depends_on",
             "priority", "domain", "created_at", "claimed_by")

    @classmethod
    def _compact(cls, t):
        if not isinstance(t, dict):
            return t
        row = {k: t[k] for k in cls._KEEP if k in t}
        md = t.get("metadata")
        if isinstance(md, dict) and md.get("priority") and "priority" not in row:
            row["priority"] = md["priority"]
        return row

    async def _run(self, assignee: Optional[str] = None, status: Optional[str] = None, domain: Optional[str] = None, plan_id: Optional[str] = None) -> ToolResult:
        tasks = self._hubs.workhub.list_tasks(assignee=assignee, status=status, domain=domain, plan_id=plan_id)
        compact = [self._compact(t) for t in tasks] if isinstance(tasks, list) else tasks
        return ToolResult(data={
            "tasks": compact,
            "_detail": "compact list — call workhub_get_task(id) for "
                       "description/evidence/result",
        })


class WorkHubAvailableTasksTool(HubTool):
    NAME = "workhub_available_tasks"
    DESCRIPTION = "List pending WorkHub tasks whose dependencies are all completed (available for the calling agent)."
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data={"tasks": self._hubs.workhub.available_tasks_for(self._agent_id)})


class WorkhubSetPriorityTool(HubTool):
    NAME = "workhub_set_priority"
    DESCRIPTION = "Adjust an existing task's priority (P0|P1|P2|P3)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
        },
        "required": ["task_id", "priority"],
    }

    async def _run(self, task_id: str, priority: str) -> ToolResult:
        actor = self._agent_id or ""
        try:
            updated = self._hubs.workhub.set_task_priority(task_id, priority, agent=actor)
        except ValueError as e:
            return ToolResult(success=False, error_message=str(e))
        return ToolResult(data={"task": updated})


class WorkhubListReadyTool(HubTool):
    NAME = "workhub_list_ready"
    DESCRIPTION = (
        "List pending tasks whose deps are all completed, sorted by "
        "(priority, created_at). Optionally filter by assignee."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {"assignee": {"type": "string"}},
    }

    async def _run(self, assignee: Optional[str] = None) -> ToolResult:
        ready = self._hubs.workhub.list_ready_tasks(assignee=assignee)
        return ToolResult(data={"ready": ready})


class WorkhubListBlockedTool(HubTool):
    NAME = "workhub_list_blocked"
    DESCRIPTION = (
        "List pending tasks waiting on incomplete deps. "
        "Each entry shows which deps block it."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {"assignee": {"type": "string"}},
    }

    async def _run(self, assignee: Optional[str] = None) -> ToolResult:
        blocked = self._hubs.workhub.list_blocked_tasks(assignee=assignee)
        return ToolResult(data={"blocked": blocked})


class WorkHubGetDocumentTool(HubTool):
    NAME = "workhub_get_document"
    DESCRIPTION = "Get a WorkHub coordination document (kickoff/meeting/retro/project) by id, optionally including its blocks."
    PARAMETERS = {"type": "object", "properties": {"document_id": {"type": "string"}, "with_blocks": {"type": "boolean"}}, "required": ["document_id"]}

    async def _run(self, document_id: str, with_blocks: bool = True) -> ToolResult:
        document = self._hubs.workhub.get_document(document_id, with_blocks=with_blocks)
        if document is None:
            return ToolResult(success=False, error_message=f"Document not found: {document_id}")
        return ToolResult(data=document)


class WorkHubListDocumentsTool(HubTool):
    NAME = "workhub_list_documents"
    DESCRIPTION = "List WorkHub coordination documents, optionally filtered by kind or status."
    PARAMETERS = {"type": "object", "properties": {"kind": {"type": "string"}, "status": {"type": "string"}}}

    async def _run(self, kind: Optional[str] = None, status: Optional[str] = None) -> ToolResult:
        # #606 — A LIST TOOL SHOULD RETURN A LISTING. This returned every document's FULL
        # record: `workhub_list_documents` was logged at up to 204,469 chars (~51k tokens) in
        # ONE call, averaging 22.6k. Over the arc's 227 stored documents the `metadata` field
        # alone is 4.60 MB of the 4.69 MB total — the meeting decisions, data models and
        # contracts live there — and a single document reaches 102,405 chars.
        #
        # The content path already exists and is the right one: `workhub_get_document(id)`.
        # Elided field-by-field (the #605 helper), so id/kind/status/title and every other
        # small field are byte-identical and only the bulk is replaced by a size + how to
        # fetch it. Measured on the real store, an id/kind/status/title listing is 99%
        # smaller (4.69 MB -> 0.05 MB).
        docs = self._hubs.workhub.list_documents(kind=kind, status=status)
        if docs is None:            # preserve the store's own container type
            docs = []
        if isinstance(docs, Mapping):
            docs = {k: _elide_large_fields(
                v, f"listing only; fetch with workhub_get_document(document_id='{k}')")
                for k, v in docs.items()}
        elif isinstance(docs, list):
            docs = [_elide_large_fields(
                d, "listing only; fetch with workhub_get_document(document_id="
                   f"'{(d or {}).get('id', '?') if isinstance(d, Mapping) else '?'}')")
                for d in docs]
        return ToolResult(data={"documents": docs})


class WorkHubLinkTaskToPrTool(HubTool):
    NAME = "workhub_link_task_to_pr"
    DESCRIPTION = "Link a WorkHub task to a pull request id."
    PARAMETERS = {"type": "object", "properties": {"task_id": {"type": "string"}, "pr_id": {"type": "string"}}, "required": ["task_id", "pr_id"]}

    async def _run(self, task_id: str, pr_id: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.link_task_to_pr(task_id, pr_id, agent=self._agent_id))


class WorkHubLinkTaskToApisTool(HubTool):
    NAME = "workhub_link_task_to_apis"
    DESCRIPTION = "Link a WorkHub task to one or more API endpoint ids."
    PARAMETERS = {"type": "object", "properties": {"task_id": {"type": "string"}, "endpoint_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["task_id", "endpoint_ids"]}

    async def _run(self, task_id: str, endpoint_ids: list) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.link_task_to_apis(task_id, endpoint_ids, agent=self._agent_id))


class WorkHubUpdateBlockTool(HubTool):
    NAME = "workhub_update_block"
    DESCRIPTION = "Replace the content of an existing WorkHub block."
    PARAMETERS = {"type": "object", "properties": {"block_id": {"type": "string"}, "content": {}}, "required": ["block_id", "content"]}

    async def _run(self, block_id: str, content: Any) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.update_block(block_id, content, agent=self._agent_id))


class WorkHubArchiveDocumentTool(HubTool):
    NAME = "workhub_archive_document"
    DESCRIPTION = "Set a WorkHub document status to 'archived'."
    PARAMETERS = {"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"]}

    async def _run(self, document_id: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.archive_document(document_id, agent=self._agent_id))


class WorkHubRecordDecisionTool(HubTool):
    NAME = "workhub_record_decision"
    DESCRIPTION = "Append a decision block to a WorkHub document and record it in the decisions store."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "title": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "chosen": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["document_id", "title", "options", "chosen", "reason"],
    }

    async def _run(self, document_id: str, title: str, options: list, chosen: str, reason: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.record_decision(document_id, title, options, chosen, reason, agent=self._agent_id))


class WorkHubCommentsForTool(HubTool):
    NAME = "workhub_comments_for"
    DESCRIPTION = "Return all comments for a given WorkHub resource id."
    PARAMETERS = {"type": "object", "properties": {"resource_id": {"type": "string"}}, "required": ["resource_id"]}

    async def _run(self, resource_id: str) -> ToolResult:
        return ToolResult(data={"comments": self._hubs.workhub.comments_for(resource_id)})


class WorkhubCreateMeetingTool(HubTool):
    """Tool wrapper for ``workhub.create_meeting``.

    Caller identity (``agent``) flows from ``self._agent_id`` set by
    ``set_agent`` — never defaulted to a phantom. The underlying service
    raises ``ValueError`` on empty ``agent`` / ``agenda`` / ``attendees``;
    we coerce those into ``ToolResult.fail`` so the LLM-facing surface is
    a clean success/error round-trip.
    """

    NAME = "workhub_create_meeting"
    DESCRIPTION = (
        "Create a kickoff/meeting page (kind defaults to 'kickoff', "
        "status='open') with an agenda and attendee list. Reuses the "
        "page-creation invariants so produced_artifacts and decisions "
        "are tracked on the returned page's metadata."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "agenda": {"type": "string", "description": "Why the meeting was called."},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Non-empty list of agent ids invited as participants.",
            },
            "milestone_index": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Required non-negative milestone anchor: the index "
                    "of the milestone this meeting kicks off. Embedded "
                    "in page.metadata['milestone_index']."
                ),
            },
            "kind": {
                "type": "string",
                "default": "kickoff",
                "description": "Meeting kind; defaults to 'kickoff'.",
            },
            "metadata": {
                "type": "object",
                "description": "Optional caller-supplied metadata merged into page.metadata.",
            },
        },
        "required": ["agenda", "attendees", "milestone_index"],
    }

    async def _run(
        self,
        agenda: str,
        attendees: list,
        milestone_index: int,
        kind: str = "kickoff",
        metadata: Optional[dict] = None,
    ) -> ToolResult:
        try:
            page = self._hubs.workhub.create_meeting(
                agenda=agenda,
                attendees=list(attendees or []),
                milestone_index=milestone_index,
                kind=kind,
                metadata=metadata,
                agent=self._agent_id,
            )
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        if isinstance(page, dict) and page.get("error"):
            return ToolResult.fail(page["error"])
        return ToolResult.ok(data=page)


class WorkhubAddMeetingDecisionTool(HubTool):
    """Tool wrapper for ``workhub.add_meeting_decision``."""

    NAME = "workhub_add_meeting_decision"
    DESCRIPTION = (
        "Append a decision dict to a meeting page's metadata['decisions'] "
        "list. The append is atomic (read-modify-write under a JsonStore "
        "lambda) so concurrent calls cannot clobber each other."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string", "description": "Page id returned by workhub_create_meeting."},
            "decision": {
                "type": "object",
                "description": "Decision payload — must be a non-empty dict. For LARGE payloads prefer decision_file.",
            },
            "decision_file": {
                "type": "string",
                "description": (
                    "Path to a JSON file holding the decision payload (write it "
                    "with the write tool first). USE THIS FOR LARGE SECTIONS: "
                    "long nested-JSON inline arguments are unreliable; a file "
                    "path keeps this call small. Overrides `decision` when both "
                    "are given."
                ),
            },
            "milestone_index": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Optional milestone anchor for the decision row. "
                    "When provided it is persisted on the appended "
                    "decision row as decision['milestone_index'] for "
                    "audit; omit to inherit the meeting's own anchor."
                ),
            },
        },
        "required": ["meeting_id"],
    }

    def _load_decision_file(self, rel: str):
        """Resolve + parse a decision JSON file. Tries the path as given, then
        the calling agent's worktree, then the project root — the agent's write
        tool lands files in its worktree."""
        import json as _json
        from pathlib import Path as _Path
        base = getattr(self._hubs, "base_dir", None)
        candidates = []
        rp = _Path(str(rel))
        if rp.is_absolute():
            candidates.append(rp)
        elif base is not None:
            candidates.append(_Path(base) / "worktrees" / (self._agent_id or "") / rp)
            candidates.append(_Path(base) / rp)
        for cand in candidates:
            try:
                if cand.is_file():
                    return _json.loads(cand.read_text(encoding="utf-8"))
            except Exception as exc:
                return ToolResult.fail(f"decision_file {rel}: unreadable/invalid JSON ({exc})")
        return ToolResult.fail(
            f"decision_file not found: {rel} (searched worktree + project root). "
            "Write it with the write tool first.")

    async def _run(
        self,
        meeting_id: str,
        decision: Any = None,
        decision_file: Optional[str] = None,
        milestone_index: Optional[int] = None,
        agent: Optional[str] = None,  # Round 8h Fix #Q
        **_extra: Any,                # Round 8h Fix #Q
    ) -> ToolResult:
        # Round 8h Fix #Q: real-LLM facilitator prompts include
        # `agent="orchestrator"` in the workhub_add_meeting_decision
        # example. The tool's PARAMETERS schema doesn't expose `agent`
        # (the canonical author is self._agent_id), and a strict
        # signature rejected the kwarg → tool-call FAILED → no
        # facilitator_note ever landed → Fix #D-bis wrote a backup
        # escalate → kickoff aborted (smoke #9-sextodecimus, 2026-06-03
        # 05:35:45; same root cause was visible but uncaught in smoke
        # #9-octavus 2026-06-02 idx 35).
        #
        # Accept the `agent` kwarg defensively and ignore it — the
        # caller-identity is authoritatively self._agent_id (the
        # LLM cannot impersonate). Same forgiving posture for any
        # other stray kwargs the LLM picks up from prompt examples.
        if agent is not None and agent != self._agent_id:
            # Audit-only: log once when the LLM's stated agent doesn't
            # match the runtime identity. Useful for diagnosing prompt
            # drift; never fails the call.
            try:
                self._logger.debug(
                    "workhub_add_meeting_decision ignoring LLM-supplied "
                    "agent=%r (authoritative agent_id=%r).",
                    agent, self._agent_id,
                )
            except AttributeError:
                pass
        if decision_file:
            loaded = self._load_decision_file(decision_file)
            if isinstance(loaded, ToolResult):
                return loaded
            decision = loaded
        if decision is None:
            return ToolResult.fail(
                "workhub_add_meeting_decision needs `decision` (small payloads) "
                "or `decision_file` (large payloads — write the JSON file first).")
        coerced = _coerce_dict_param(decision, "decision")
        if isinstance(coerced, ToolResult):
            return coerced
        # REJECT EMPTY SECTION DRAFTS AT THE TOOL BOUNDARY (2026-06-10): when
        # gemini's long inline JSON gets mangled, what arrives is a shell
        # ({"ui_pages": [], ...} or null-skeletons). Accepting it silently
        # wastes the whole turn — the agent only learns after its loop ends.
        # Failing HERE puts the guidance in the model's face immediately.
        try:
            from multi_agent.runtime.kickoff.section_substance import (
                decision_has_substance, non_contract_keys, has_aux_content)
            _c = coerced or {}
            _sec = _c.get("section") or (_c.get("content") or {}).get("section")
            _content = _c.get("content") if isinstance(_c.get("content"), dict) else _c
            # §5 (env-gated, default-off): reject a frontend section whose
            # reference_image_manifest declares paths the agent never view_image'd this run
            # (authored-from-memory). No-op when no viewed-set/handle or no references. The
            # ToolResult.fail re-prompts the lane in its own loop to view + re-submit.
            import os as _os
            if (_os.environ.get("ENVGEN_ENFORCE_REF_VIEW", "0").lower() in ("1", "true", "yes", "on")
                    and _sec == "frontend" and not _content.get("deferred")):
                from multi_agent.runtime.kickoff.section_substance import unviewed_manifest_paths
                _viewed = getattr(getattr(self, "_agent", None), "_viewed_reference_paths", None)
                _unviewed = unviewed_manifest_paths(_content, _viewed)
                if _unviewed:
                    return ToolResult.fail(
                        f"reference_image_manifest declares paths you did NOT view this run: "
                        f"{_unviewed}. Call view_image('<path>') for EACH manifest entry FIRST "
                        "(use list_reference_images() to discover paths), then re-submit the "
                        "manifest with ONLY paths you actually loaded. If no references exist, "
                        "submit reference_image_manifest={} with a note.")
            if (_sec in ("frontend", "backend", "verifier")
                    and not _content.get("deferred")
                    and not decision_has_substance(_c, _sec)):
                _keys = {"frontend": "ui_pages / screens / user_flows / ui_components",
                         "backend": "endpoints / data_model.tables",
                         "verifier": "predicates"}.get(_sec, "ui_pages / endpoints / predicates")
                _eg = {"frontend": "{'user_flows': [<ONE flow>]}",
                       "backend": "{'endpoints': [<ONE endpoint>]}",
                       "verifier": "{'predicates': [<ONE predicate>]}"}.get(
                           _sec, "{'ui_pages': [<ONE page>]}")
                # WRONG-KEYS (youtube run #13): the lane submitted ONLY non-contract
                # keys (e.g. {'auth_model': 'jwt'} — auth is framework-owned, NOT a
                # section field). The generic "truncated → SUBMIT IN PARTS" guidance
                # below made the backend resend the same auth blob 22×. Steer it to
                # the right keys + tell it auth is framework-owned, instead of
                # implying truncation, so it stops looping.
                _wrong = non_contract_keys(_content, _sec)
                if _wrong:
                    return ToolResult.fail(
                        f"decision for section '{_sec}' carried only NON-CONTRACT "
                        f"keys {_wrong} — these are not part of your kickoff section. "
                        "Auth is FRAMEWORK-OWNED (the generated stack embeds an "
                        "OAuth2 AS minting JWTs) — do NOT declare auth_model/auth; "
                        "the framework supplies it. Declare your real contract "
                        f"({_keys}) via the dedicated kickoff_declare_* tools (e.g. "
                        f"{_eg}). Do NOT re-submit this decision.")
                # AUX-ONLY ACCEPT (2026-06-24): a decision with no buildable substance
                # but carrying legit AUX keys (done_def / feature_inventory /
                # reference_image_manifest / task_tree) MUST be accepted + recorded — the
                # buildable ui_pages/endpoints/predicates arrive via the dedicated
                # kickoff_declare_* tools (separate calls). Without this the aux-only
                # decision hit the hard 'no recognized key' reject below (v11: the
                # frontend's done_def+feature_inventory decision was rejected; the
                # reconcile READS those aux fields, so the reject is a pure regression).
                # The wrong-keys (auth) reject above still fires first.
                if not has_aux_content(_content, _sec):
                    # Mangle detection: a recognized key present as a SCALAR (e.g.
                    # endpoints=-128) means Gemini truncated a large inline payload in
                    # transit — NOT an empty draft. Flag it so the model switches to the
                    # small, mangle-proof dedicated tools instead of resending the blob.
                    _recognized = {"frontend": ("ui_pages", "screens", "user_flows", "ui_components"),
                                   "backend": ("endpoints", "data_model"),
                                   "verifier": ("predicates",)}.get(_sec, ())
                    _mangled = [k for k in _recognized
                                if k in _content and not isinstance(_content.get(k), (list, dict, str))]
                    _mangle_note = (
                        f" ⚠ MANGLED PAYLOAD: {_mangled} arrived as a non-list scalar "
                        f"(e.g. {_content.get(_mangled[0])!r}) — your large inline JSON was "
                        "TRUNCATED in transit. Do NOT resend the big blob: use the dedicated "
                        "kickoff_declare_* tools (ONE small item per call), which never mangle."
                        if _mangled else "")
                    return ToolResult.fail(
                        f"decision for section '{_sec}' has NO non-empty content in any "
                        f"recognized key ({_keys}) — every recognized list was empty/null." + _mangle_note +
                        " If a large inline payload got truncated, SUBMIT IN PARTS: call "
                        "this tool SEVERAL times, each with a SMALL piece (e.g. decision="
                        f"{{'section': '{_sec}', 'content': {_eg}}}); the meeting MERGES "
                        "your pieces. Prefer the dedicated kickoff_declare_* tools (one "
                        "item per call). Or write the full JSON to "
                        f"design/kickoff_{_sec}_section.json and pass decision_file=...")
        except ImportError:
            pass
        try:
            page = self._hubs.workhub.add_meeting_decision(
                meeting_id=meeting_id,
                decision=coerced or {},
                agent=self._agent_id,
                milestone_index=milestone_index,
            )
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        if isinstance(page, dict) and page.get("error"):
            return ToolResult.fail(page["error"])
        # #608 — AN APPEND RETURNED THE WHOLE ACCUMULATED PAGE. Every call handed back the
        # meeting page including `metadata['decisions']`, which this very call had just
        # grown: the Nth append re-serialises all N decisions, so the cost grows with the
        # square of the meeting's length. Over the arc's 58 meeting pages the median ends at
        # 72,879 chars with 62 decisions (max 103 / 102,405 chars). Measured from the run
        # logs, this tool returned 4.80M tokens over 350 calls (avg 13.7k) — for an append
        # whose useful answer is "stored, that's now N".
        #
        # Same #605 helper: meeting_id/title/status and every other small field stay
        # byte-identical; only the accumulated bulk becomes a size + how to read it back.
        return ToolResult.ok(data=_elide_large_fields(page, _meeting_hint_608(page, meeting_id)))


class WorkhubCloseMeetingTool(HubTool):
    """Tool wrapper for ``workhub.close_meeting``."""

    NAME = "workhub_close_meeting"
    DESCRIPTION = (
        "Close a meeting page: flip status to 'closed' and record the "
        "canonical list of artifacts the meeting produced (page ids, "
        "plan ids, decision ids). Symmetric to archive_page but "
        "specialized for meetings."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "produced_artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Artifact ids produced by the meeting (may be empty).",
            },
            "metadata_extra": {
                "type": "object",
                "description": "Optional extra metadata merged into page.metadata at close.",
            },
            "milestone_index": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Optional milestone anchor. When provided it is "
                    "persisted on the closed page's "
                    "metadata['milestone_index'] (overwriting any prior "
                    "value) so an audit-time scan can recover the "
                    "milestone anchor even if create_meeting metadata "
                    "is missing the field."
                ),
            },
        },
        "required": ["meeting_id", "produced_artifacts"],
    }

    async def _run(
        self,
        meeting_id: str,
        produced_artifacts: list,
        metadata_extra: Optional[dict] = None,
        milestone_index: Optional[int] = None,
    ) -> ToolResult:
        try:
            page = self._hubs.workhub.close_meeting(
                meeting_id=meeting_id,
                produced_artifacts=list(produced_artifacts or []),
                metadata_extra=metadata_extra,
                agent=self._agent_id,
                milestone_index=milestone_index,
            )
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        if isinstance(page, dict) and page.get("error"):
            return ToolResult.fail(page["error"])
        # #608: closing echoed the whole accumulated page too — same trim, same reason.
        return ToolResult.ok(data=_elide_large_fields(page, _meeting_hint_608(page, meeting_id)))


class RegistryHubRegisterEndpointTool(HubTool):
    NAME = "registryhub_register_endpoint"
    DESCRIPTION = "Register/update RegistryHub endpoint and schema."
    PARAMETERS = {"type": "object", "properties": {"method": {"type": "string"}, "path": {"type": "string"}, "schema": {
                "type": "object",
                # #732: NAME THE SLOTS THE FRAMEWORK READS, where the model can see them.
                # `schema` was declared as a bare `{"type": "object"}` — the model was asked for
                # "a schema" and had to guess the key names. r148 guessed `query` for query
                # parameters, which is a BETTER word than the one we read, and every consumer
                # (validation_runner, database_scaffold, scaffolder, #708b) reads `request`, so
                # the declaration was stored and invisible for a whole run.
                #
                # Discovering that one synonym at a time does not converge: a different app will
                # guess `params`, `queryParams`, `filters`. #730 folds `query` specifically and
                # #731 warns about unknown keys, but both are netflix-shaped patches on a
                # structural gap — the CONTRACT was never published at the point of the call.
                #
                # These four slot names belong to the framework, not to any app's domain, so
                # naming them here is app-independent by construction and travels with the tool
                # to every future generation. Extra keys stay legal: the model may still invent,
                # it simply no longer has to.
                "description": (
                    "The endpoint's contract. The keys below are the ones the framework READS; "
                    "any other key is stored faithfully but no consumer acts on it."),
                "properties": {
                    "request": {"type": "object", "description":
                                "Parameters the endpoint ACCEPTS. For GET these are the QUERY "
                                "PARAMETERS — declare every filter you implement, e.g. "
                                "{\"kind\": \"string?\", \"genre\": \"string?\", "
                                "\"limit\": \"int?\"}; for POST/PUT/PATCH the body fields. "
                                "A trailing `?` marks optional. A filter you implement and do "
                                "not declare here is invisible to the frontend, to the contract "
                                "audit, and to remediation hints — which is how six catalogue "
                                "routes ended up fetching the same unfiltered list."},
                    "response": {"type": "object", "description":
                                 "Shape of one returned item, {field: type}."},
                    "response_key": {"type": "string", "description":
                                     "Envelope key the payload sits under — `item` for one, "
                                     "`items` for a list."},
                    "auth_required": {"type": "boolean", "description":
                                      "True when the endpoint rejects an unauthenticated call."},
                },
            }, "provider": {"type": "string"}, "status": {"type": "string"}}, "uses": {"type": "array", "items": {"type": "string"}, "description": "endpoints this endpoint's logic builds on, e.g. ['GET /api/items'] — orders implementation and feeds verifier chain design"},
        "required": ["method", "path"]}

    async def _run(self, method: str, path: str, schema=None, provider: str = "", status: str = "defined") -> ToolResult:
        coerced = _coerce_dict_param(schema, "schema")
        if isinstance(coerced, ToolResult):
            return coerced
        return ToolResult(data=self._hubs.registryhub.register_endpoint(method, path, schema=coerced or {}, provider=provider or self._agent_id, agent=self._agent_id, status=status))


class RegistryHubConsumerTool(HubTool):
    NAME = "registryhub_register_consumer"
    DESCRIPTION = (
        "Register an API consumer file. Pass ``pending=true`` to queue "
        "the registration BEFORE the endpoint is registered — useful "
        "during early pipeline scheduling. When the producer later "
        "registers the endpoint, your queued entry is auto-promoted "
        "and you receive an ``endpoint_implemented`` urgent event."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "file_path": {"type": "string"},
            "metadata": {"type": "object"},
            "pending": {
                "type": "boolean",
                "description": (
                    "If true and endpoint not yet registered, queue this "
                    "consumer intent instead of rejecting. Auto-promotes "
                    "when the producer registers the endpoint."
                ),
            },
        },
        "required": ["endpoint_id", "file_path"],
    }

    async def _run(self, endpoint_id: str, file_path: str, metadata: Optional[dict] = None, pending: bool = False) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.register_consumer(
            endpoint_id, file_path, self._agent_id,
            metadata=metadata or {}, pending=pending,
        ))


class RegistryHubCheckEndpointDriftTool(HubTool):
    """Check whether a route file's actual response shape matches the
    response_key declared in the endpoint's registered schema.

    Catches the classic ``backend writes res.json({users: ...}) but
    registered schema says response_key='items'`` drift. Heuristic
    parser covers Express, Flask, FastAPI patterns.
    """

    NAME = "registryhub_check_endpoint_drift"
    DESCRIPTION = (
        "Compare the actual response key used in a route file to the "
        "endpoint's declared schema.response_key. Returns either "
        "``{drift: false}`` or a drift report with expected vs found "
        "keys and a hint. Call this AFTER writing/updating a route "
        "file and BEFORE finalizing the endpoint with "
        "status='implemented'."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "file_path": {
                "type": "string",
                "description": (
                    "Workspace-relative path to the route file. "
                    "Resolved via the agent's workspace."
                ),
            },
        },
        "required": ["endpoint_id", "file_path"],
    }

    async def _run(self, endpoint_id: str, file_path: str) -> ToolResult:
        endpoint = self._hubs.registryhub._endpoints.get(endpoint_id)
        if not endpoint:
            return ToolResult(success=False, error_message=f"endpoint not registered: {endpoint_id}")
        # Read file content via the agent's workspace so per-agent worktree
        # routing (Phase 0) is honored.
        workspace = getattr(self, "_workspace", None) or getattr(
            getattr(self, "agent", None), "workspace", None,
        )
        try:
            from pathlib import Path
            resolved = workspace.resolve(file_path) if workspace else Path(file_path)
            content = Path(resolved).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(success=False, error_message=f"could not read {file_path}: {exc}")

        from multi_agent.runtime.contract_drift import detect_endpoint_drift
        report = detect_endpoint_drift(endpoint=endpoint, file_content=content)
        if report is None:
            return ToolResult(data={"drift": False, "endpoint_id": endpoint_id})
        return ToolResult(data={"drift": True, **report})


class RegistryHubUpdateSchemaTool(HubTool):
    NAME = "registryhub_update_schema"
    DESCRIPTION = "Update request/response schema of an existing RegistryHub endpoint."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string", "description": "Format: 'METHOD /path'"},
            "request": {"type": "object"},
            "response": {"type": "object"},
        },
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str, request: Optional[dict] = None, response: Optional[dict] = None) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.update_schema(
            endpoint_id, request=request, response=response, agent=self._agent_id))


class RegistryHubRegisterVerificationChainTool(HubTool):
    NAME = "registryhub_register_verification_chain"
    DESCRIPTION = (
        "Register ONE verification chain (call once per chain). Chains are "
        "CONTRACT SURFACE: multi-step API journeys YOU design from this app's "
        "registered endpoints + kickoff user_flows (an auth round-trip first, "
        "then each critical flow as create->read-back->cross-user steps). "
        "Step fields: method, path (or endpoint='METHOD /path'), optional "
        "body (use ${rand} for unique values, ${var} to reuse saved ones), "
        "expect (accepted status codes), save (var->dot.path into the JSON "
        "response), auth (var holding the bearer token), headers (a dict of extra request headers — #686; Authorization is ignored here, use auth). Malformed steps are "
        "REJECTED with the reason. run_validation executes every registered "
        "chain (business_chain check) and records pass/fail on the registry.")
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "snake_case chain name"},
            "description": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["name", "steps"],
    }

    async def _run(self, name: str, steps: list, description: str = "") -> ToolResult:
        res = self._hubs.registryhub.register_verification_chain(
            name, steps, description=description, agent=self._agent_id)
        if isinstance(res, dict) and res.get("error"):
            return ToolResult(success=False, error_message=res["error"])
        return ToolResult(data={"registered": name,
                                "steps": len(res.get("steps") or []),
                                "status": res.get("status")})


class RegistryHubUpdateTableSchemaTool(HubTool):
    NAME = "registryhub_update_table_schema"
    DESCRIPTION = (
        "Evolve an existing table's schema on RegistryHub. Breaking changes "
        "(dropped/retyped columns with registered consumers) are DETECTED and "
        "recorded — consumers get a table_breaking_change event. Use this for "
        "schema evolution instead of re-registering the table blind.")
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "table name"},
            "schema": {"type": "object", "description": "the full new schema"},
        },
        "required": ["name", "schema"],
    }

    async def _run(self, name: str, schema: dict) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.update_table_schema(
            name, schema, agent=self._agent_id))


class WorkhubListUiPagesTool(HubTool):
    NAME = "registryhub_list_ui_pages"
    DESCRIPTION = (
        "READ the ui_page registry: each declared page with its route, "
        "component, apis_used and lifecycle status (defined/implemented — the "
        "FRAMEWORK flips status by auditing the code; you cannot set it). Use "
        "to see which pages are still unimplemented and why.")
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.get_ui_pages())


class WorkhubListUiComponentsTool(HubTool):
    NAME = "workhub_list_ui_components"
    DESCRIPTION = (
        "READ the ui_component registry: each declared component with its "
        "code name, apis_used, children and lifecycle status (framework-"
        "audited). A page only reaches implemented when every component it "
        "references is implemented — use this to find the blocker.")
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.get_ui_components())


class RegistryHubListEndpointsTool(HubTool):
    NAME = "registryhub_list_endpoints"
    DESCRIPTION = "List all RegistryHub endpoints, optionally filtered by status or provider."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "provider": {"type": "string"},
        },
    }

    async def _run(self, status: Optional[str] = None, provider: Optional[str] = None) -> ToolResult:
        endpoints = self._hubs.registryhub.get_endpoints()
        if status:
            endpoints = {k: v for k, v in endpoints.items() if v.get("status") == status}
        if provider:
            endpoints = {k: v for k, v in endpoints.items() if v.get("provider") == provider}
        # #303 CONTEXT: return COMPACT rows (id/method/path/status/provider) — the
        # per-endpoint schema+metadata are ~85% of each row, rarely needed in a
        # LIST, and this tool is re-fetched dozens of times per run. Full detail
        # (schema/request/response) stays recoverable via registryhub_get_endpoint(id).
        compact = {
            k: {"id": v.get("id", k), "method": v.get("method"),
                "path": v.get("path"), "status": v.get("status"),
                "provider": v.get("provider")}
            for k, v in endpoints.items() if isinstance(v, dict)
        }
        return ToolResult(data={
            "endpoints": compact,
            "_detail": "compact list — call registryhub_get_endpoint(id) for "
                       "schema/request/response",
        })


class RegistryHubGetEndpointTool(HubTool):
    NAME = "registryhub_get_endpoint"
    DESCRIPTION = "Get a single RegistryHub endpoint by its id (format 'METHOD /path')."
    PARAMETERS = {
        "type": "object",
        "properties": {"endpoint_id": {"type": "string"}},
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str) -> ToolResult:
        # #685: LOOK IT UP THE WAY IT WAS STORED. The store's KEY collapses every path param —
        # `RegistryHub.endpoint_id` rewrites `{id}` to `{}` — while the record's own `path` field
        # keeps the named form. So an agent that reads `POST /api/titles/{id}/rating` off the
        # registry and asks for it back by that exact string got "Endpoint not found", because
        # the key is `POST /api/titles/{}/rating`. It was being asked to know an internal
        # normalisation it is never shown. r145 refused 10 of these, all on that one endpoint.
        #
        # Canonicalising the query through the same helper that built the key makes the two
        # agree. The raw lookup is tried first so an exact key still resolves unchanged.
        _eps = self._hubs.registryhub.get_endpoints()
        endpoint = _eps.get(endpoint_id)
        if endpoint is None:
            try:
                from multi_agent.runtime.registryhub import RegistryHub as _RH
                _parts = str(endpoint_id or "").strip().split(None, 1)
                if len(_parts) == 2:
                    endpoint = _eps.get(_RH.endpoint_id(_parts[0], _parts[1]))
            except Exception:
                endpoint = None
        if not endpoint:
            return ToolResult(success=False, error_message=f"Endpoint not found: {endpoint_id}")
        return ToolResult(data=endpoint)


class RegistryHubGetDependenciesForFileTool(HubTool):
    NAME = "registryhub_get_dependencies_for_file"
    DESCRIPTION = "List API endpoints a specific source file depends on."
    PARAMETERS = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    }

    async def _run(self, file_path: str) -> ToolResult:
        return ToolResult(data={"dependencies": self._hubs.registryhub.get_dependencies_for_file(file_path)})


class RegistryHubGetBreakingChangesTool(HubTool):
    NAME = "registryhub_get_breaking_changes"
    DESCRIPTION = "List recorded RegistryHub breaking changes (newest first)."
    PARAMETERS = {
        "type": "object",
        "properties": {"since_ts": {"type": "number"}},
    }

    async def _run(self, since_ts: Optional[float] = None) -> ToolResult:
        return ToolResult(data={"breaking_changes": self._hubs.registryhub.get_breaking_changes(since_ts=since_ts)})


class RegistryHubRecordContractTestTool(HubTool):
    NAME = "registryhub_record_contract_test"
    DESCRIPTION = "Record a contract test result against an RegistryHub endpoint."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "result": {"type": "object"},
            "evidence": {"type": "object"},
        },
        "required": ["endpoint_id", "result"],
    }

    async def _run(self, endpoint_id: str, result: dict, evidence: Optional[dict] = None) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.record_api_test(
            endpoint_id, result, evidence=evidence or {}, agent=self._agent_id))


class RegistryHubDeprecateEndpointTool(HubTool):
    NAME = "registryhub_deprecate_endpoint"
    DESCRIPTION = "Mark an RegistryHub endpoint as deprecated, optionally pointing to a replacement."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "replacement_id": {"type": "string"},
        },
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str, replacement_id: Optional[str] = None) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.deprecate_endpoint(
            endpoint_id, replacement_id=replacement_id, agent=self._agent_id))


class RegistryHubRequestReviewTool(HubTool):
    NAME = "registryhub_request_review"
    DESCRIPTION = "Request review of an RegistryHub endpoint from named agents."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["endpoint_id", "reviewers"],
    }

    async def _run(self, endpoint_id: str, reviewers: list, reason: str = "") -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.request_api_review(
            endpoint_id, reviewers, agent=self._agent_id, reason=reason))


class RegistryHubSubmitReviewTool(HubTool):
    NAME = "registryhub_submit_review"
    DESCRIPTION = "Submit a decision (approve / request_changes / comment) on a pending RegistryHub review."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "review_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["approve", "request_changes", "comment"]},
            "comments": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["review_id", "decision"],
    }

    async def _run(self, review_id: str, decision: str, comments: Optional[list] = None) -> ToolResult:
        return ToolResult(data=self._hubs.registryhub.submit_api_review(
            review_id, reviewer=self._agent_id, decision=decision, comments=comments or []))


class RegistryHubRegisterTableTool(HubTool):
    NAME = "registryhub_register_table"
    DESCRIPTION = "Register a database table schema (called by database/design agent)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "schema": {"type": "object", "description": "Map column name -> type string"},
            "status": {"type": "string", "enum": ["defined", "implemented", "deprecated"]},
        },
        "required": ["name", "schema"],
    }

    async def _run(self, name: str, schema=None, status: str = "defined") -> ToolResult:
        coerced = _coerce_dict_param(schema, "schema")
        if isinstance(coerced, ToolResult):  # error case
            return coerced
        return ToolResult(data=self._hubs.schema_hub.register_table(
            name=name, schema=coerced or {}, provider=self._agent_id, agent=self._agent_id, status=status))


class RegistryHubListTablesTool(HubTool):
    NAME = "registryhub_list_tables"
    DESCRIPTION = "List registered tables, optionally filtered by provider or status."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            # `status` mirrors registryhub_list_endpoints — the model reasonably
            # assumes the two list tools take the same filters, and called
            # list_tables(status=...) → crash. Accept + apply it (tables carry a
            # status the skeleton flips to 'implemented').
            "status": {"type": "string", "description": "Optional status filter, e.g. 'implemented' / 'defined'."},
        },
    }

    async def _run(self, provider: Optional[str] = None, status: Optional[str] = None) -> ToolResult:
        tables = self._hubs.schema_hub.list_tables(provider=provider)
        if status and isinstance(tables, dict):
            tables = {k: v for k, v in tables.items()
                      if isinstance(v, dict) and v.get("status") == status}
        # #303 CONTEXT: compact rows — keep scalar identity fields + a column
        # COUNT; the full columns/schema (the big nested fields) are recoverable
        # via registryhub_get_table / get_table_breaking_changes. This list is
        # re-fetched many times per run.
        if isinstance(tables, dict):
            compact = {}
            for k, v in tables.items():
                if not isinstance(v, dict):
                    compact[k] = v
                    continue
                row = {f: val for f, val in v.items()
                       if not isinstance(val, (dict, list))}
                cols = v.get("columns")
                if isinstance(cols, (list, dict)):
                    row["columns_count"] = len(cols)
                compact[k] = row
            return ToolResult(data={
                "tables": compact,
                "_detail": "compact list — call registryhub_get_table(id) for "
                           "full columns/schema",
            })
        return ToolResult(data={"tables": tables})


class RegistryHubRegisterTableConsumerTool(HubTool):
    NAME = "registryhub_register_table_consumer"
    DESCRIPTION = "Declare that a file consumes a specific table (used for breaking-change tracking)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "file_path": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["table_name", "file_path"],
    }

    async def _run(self, table_name: str, file_path: str, metadata: Optional[dict] = None) -> ToolResult:
        return ToolResult(data=self._hubs.schema_hub.register_table_consumer(
            table_name=table_name, file_path=file_path, agent=self._agent_id,
            metadata=metadata or {}))


class RegistryHubGetTableBreakingChangesTool(HubTool):
    NAME = "registryhub_get_table_breaking_changes"
    DESCRIPTION = "List recorded table breaking changes (newest first)."
    PARAMETERS = {
        "type": "object",
        "properties": {"since_ts": {"type": "number"}},
    }

    async def _run(self, since_ts: Optional[float] = None) -> ToolResult:
        return ToolResult(data={"breaking_changes": self._hubs.schema_hub.get_table_breaking_changes(since_ts=since_ts)})


class EventHubInboxTool(HubTool):
    NAME = "eventhub_inbox"
    DESCRIPTION = "List or mark durable EventHub inbox messages."
    PARAMETERS = {"type": "object", "properties": {"action": {"type": "string"}, "event_id": {"type": "string"}, "unread_only": {"type": "boolean"}}, "required": ["action"]}

    async def _run(self, action: str, event_id: str = "", unread_only: bool = True) -> ToolResult:
        if action == "list":
            return ToolResult(data={"events": self._hubs.eventhub.list_inbox(self._agent_id, unread_only=unread_only)})
        if action == "mark_read":
            # O14/Phase 4.1: thread caller=agent_id (tool-invoked path).
            # caller == agent → self-mutation, passes the 4.1 identity gate.
            return ToolResult(data=self._hubs.eventhub.mark_read(
                self._agent_id, event_id, caller=self._agent_id,
            ))
        return ToolResult(success=False, error_message=f"Unknown eventhub_inbox action: {action}")


class EventHubSubscribeTool(HubTool):
    NAME = "eventhub_subscribe"
    DESCRIPTION = "Subscribe to events from a specific hub/type with optional filter."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "source_hub": {"type": "string", "description": "registryhub/codehub/workhub/system/*"},
            "event_type": {"type": "string", "description": "Specific event_type or * for all"},
            "filter": {"type": "object", "description": "Optional filter dict"},
            "priority_floor": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            "delivery": {"type": "string", "enum": ["live", "inbox_only"]},
        },
    }

    async def _run(self, source_hub: str = "*", event_type: str = "*",
                   filter: Optional[dict] = None, priority_floor: str = "low",
                   delivery: str = "live") -> ToolResult:
        # O14/Phase 4.1: thread caller=agent_id (tool-invoked path).
        return ToolResult(data=self._hubs.eventhub.subscribe(
            agent=self._agent_id, source_hub=source_hub, event_type=event_type,
            filter=filter, priority_floor=priority_floor, delivery=delivery,
            caller=self._agent_id,
        ))


class EventHubUnsubscribeTool(HubTool):
    NAME = "eventhub_unsubscribe"
    DESCRIPTION = "Cancel an existing EventHub subscription by id."
    PARAMETERS = {
        "type": "object",
        "properties": {"subscription_id": {"type": "string"}},
        "required": ["subscription_id"],
    }

    async def _run(self, subscription_id: str) -> ToolResult:
        # O14/Phase 4.1: thread caller=agent_id (tool-invoked path).
        # The eventhub.unsubscribe gate looks up the row's owning agent
        # and compares; calling-agent unsubscribing its own sub passes.
        removed = self._hubs.eventhub.unsubscribe(
            subscription_id, caller=self._agent_id,
        )
        return ToolResult(data={"removed": removed, "subscription_id": subscription_id})


class EventHubListSubscriptionsTool(HubTool):
    NAME = "eventhub_list_subscriptions"
    DESCRIPTION = "List your active EventHub subscriptions."
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data={"subscriptions": self._hubs.eventhub.get_subscriptions(agent=self._agent_id)})


class EventHubGetThreadTool(HubTool):
    NAME = "eventhub_get_thread"
    DESCRIPTION = "Get all events in a thread (chronological order)."
    PARAMETERS = {
        "type": "object",
        "properties": {"thread_id": {"type": "string"}},
        "required": ["thread_id"],
    }

    async def _run(self, thread_id: str) -> ToolResult:
        return ToolResult(data={"events": self._hubs.eventhub.get_thread(thread_id)})


class EventHubReplyInThreadTool(HubTool):
    NAME = "eventhub_reply_in_thread"
    DESCRIPTION = "Reply in an existing event thread."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "thread_id": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["thread_id", "body"],
    }

    async def _run(self, thread_id: str, body: str) -> ToolResult:
        return ToolResult(data=self._hubs.eventhub.thread_reply(thread_id, self._agent_id, body))


class EventHubMarkAllReadTool(HubTool):
    NAME = "eventhub_mark_all_read"
    DESCRIPTION = "Mark all unread events in your inbox as read; optionally only those before before_ts."
    PARAMETERS = {
        "type": "object",
        "properties": {"before_ts": {"type": "number"}},
    }

    async def _run(self, before_ts: Optional[float] = None) -> ToolResult:
        # O14/Phase 4.1: thread caller=agent_id (tool-invoked path).
        return ToolResult(data={"marked": self._hubs.eventhub.mark_all_read(
            self._agent_id, before_ts=before_ts, caller=self._agent_id,
        )})


class EventHubGetAgentStatusTool(HubTool):
    NAME = "eventhub_get_agent_status"
    DESCRIPTION = "Get the most recent reported status for an agent."
    PARAMETERS = {
        "type": "object",
        "properties": {"agent_id": {"type": "string"}},
        "required": ["agent_id"],
    }

    async def _run(self, agent_id: str) -> ToolResult:
        return ToolResult(data={"status": self._hubs.eventhub.get_agent_status(agent_id)})


class HubSnapshotTool(HubTool):
    NAME = "hub_snapshot"
    DESCRIPTION = "Get a snapshot of CodeHub, WorkHub, RegistryHub, and EventHub."
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data=self._hubs.snapshot())


class CodeHubGetDiffTool(HubTool):
    NAME = "codehub_get_diff"
    DESCRIPTION = "Return the unified diff for a CodeHub PR (head vs target branch). Truncates to max_lines."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string", "description": "PR identifier."},
            "max_lines": {"type": "integer", "description": "Max diff lines to return (default 5000)."},
        },
        "required": ["pr_id"],
    }

    async def _run(self, pr_id: str, max_lines: int = 5000) -> ToolResult:
        return ToolResult(data=self._hubs.codehub.get_diff(pr_id, max_lines=max_lines))


class CodeHubGetBlobTool(HubTool):
    NAME = "codehub_get_blob"
    DESCRIPTION = "Return file content at a specific git commit hash in CodeHub."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "commit_hash": {"type": "string", "description": "Full or abbreviated commit SHA."},
            "path": {"type": "string", "description": "Relative file path within the repo."},
        },
        "required": ["commit_hash", "path"],
    }

    async def _run(self, commit_hash: str, path: str) -> ToolResult:
        try:
            content = self._hubs.codehub.get_blob(commit_hash, path)
            return ToolResult(data={"content": content, "commit": commit_hash, "path": path})
        except Exception as exc:
            return ToolResult(success=False, error_message=str(exc))


class CodeHubGetFileContentTool(HubTool):
    NAME = "codehub_get_file_content"
    DESCRIPTION = "Return the content of a file from the PR's head commit."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string", "description": "PR identifier."},
            "path": {"type": "string", "description": "Relative file path within the repo."},
        },
        "required": ["pr_id", "path"],
    }

    async def _run(self, pr_id: str, path: str) -> ToolResult:
        result = self._hubs.codehub.get_file_content(pr_id, path)
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"])
        return ToolResult(data=result)


class CodeHubListPRsTool(HubTool):
    NAME = "codehub_list_prs"
    DESCRIPTION = "List CodeHub pull requests, optionally filtered by status, author, or reviewer."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by PR status (e.g. 'open', 'merged', 'conflict')."},
            "author": {"type": "string", "description": "Filter by PR author agent id."},
            "reviewer": {"type": "string", "description": "Filter by reviewer agent id."},
        },
    }

    async def _run(self, status: Optional[str] = None, author: Optional[str] = None, reviewer: Optional[str] = None) -> ToolResult:
        return ToolResult(data={"prs": self._hubs.codehub.list_prs(status=status, author=author, reviewer=reviewer)})


class CodeHubListChecksTool(HubTool):
    NAME = "codehub_list_checks"
    DESCRIPTION = "List CI/check records in CodeHub, optionally filtered by pr_id or check name."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string", "description": "Filter by PR identifier."},
            "name": {"type": "string", "description": "Filter by check name (e.g. 'lint', 'tests')."},
        },
    }

    async def _run(self, pr_id: Optional[str] = None, name: Optional[str] = None) -> ToolResult:
        return ToolResult(data={"checks": self._hubs.codehub.list_checks(pr_id=pr_id, name=name)})


class CodeHubResolveConflictTool(HubTool):
    NAME = "codehub_resolve_conflict"
    DESCRIPTION = (
        "Resolve a conflicted CodeHub PR by supplying resolved file contents. "
        "Writes files into the main worktree, stages, commits, and marks the PR as merged."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string", "description": "PR identifier in conflict state."},
            "resolution_files": {
                "type": "object",
                "description": "Map of relative file path → resolved file content.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["pr_id", "resolution_files"],
    }

    async def _run(self, pr_id: str, resolution_files: dict) -> ToolResult:
        result = self._hubs.codehub.resolve_conflict(pr_id, resolution_files, agent=self._agent_id)
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"])
        return ToolResult(data=result)


class WorkHubInviteAttendeeTool(HubTool):
    NAME = "workhub_invite_attendee"
    DESCRIPTION = "Invite an agent as an attendee of a page/plan/task."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "role": {"type": "string", "enum": ["owner", "reviewer", "contributor", "viewer"]},
        },
        "required": ["resource_id", "agent_id"],
    }

    async def _run(self, resource_id: str, agent_id: str, role: str = "viewer") -> ToolResult:
        return ToolResult(data=self._hubs.workhub.invite_attendee(
            resource_id, agent_id, role=role, invited_by=self._agent_id))


class WorkHubRemoveAttendeeTool(HubTool):
    NAME = "workhub_remove_attendee"
    DESCRIPTION = "Remove an agent from attendees of a page/plan/task."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_type": {"type": "string", "enum": ["page", "plan", "task"]},
            "resource_id": {"type": "string"},
            "agent_id": {"type": "string"},
        },
        "required": ["resource_type", "resource_id", "agent_id"],
    }

    async def _run(self, resource_type: str, resource_id: str, agent_id: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.remove_attendee(
            resource_type, resource_id, agent_id, by=self._agent_id))


class WorkHubCommentTool(HubTool):
    NAME = "workhub_comment"
    DESCRIPTION = "Post a comment on a WorkHub resource (page/plan/task) with optional @mentions."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_id": {"type": "string"},
            "body": {"type": "string"},
            "mentions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resource_id", "body"],
    }

    async def _run(self, resource_id: str, body: str, mentions: Optional[list] = None) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.comment(
            resource_id=resource_id, body=body, agent=self._agent_id,
            mentions=mentions or []))


class WorkHubReplyTool(HubTool):
    NAME = "workhub_reply"
    DESCRIPTION = "Reply to a WorkHub comment, optionally @mentioning agents."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "comment_id": {"type": "string"},
            "body": {"type": "string"},
            "mentions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["comment_id", "body"],
    }

    async def _run(self, comment_id: str, body: str, mentions: Optional[list] = None) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.reply(
            comment_id=comment_id, body=body, agent=self._agent_id,
            mentions=mentions or []))


class WorkHubShareImplementationTool(HubTool):
    NAME = "workhub_share_implementation"
    DESCRIPTION = "Share a reusable implementation pattern as a WorkHub knowledge block."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["title", "content"],
    }

    async def _run(self, title: str, content: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.share_implementation(
            title=title, content=content, agent=self._agent_id))


# ---------------------------------------------------------------------------
# KICKOFF PER-ITEM DECLARATION TOOLS (2026-06-11). Measured: gemini emits
# small FLAT-parameter tool calls reliably (6/6) while large nested payloads
# starve (round-16: 18-min reject loop). These tools make chunked authoring a
# first-class CAPABILITY: one item per call, flat typed params, the framework
# assembles the nested section via the meeting's merge semantics
# (_collect_drafts). Same pattern as registryhub_register_endpoint — the most
# reliable authoring path in every run to date.
# ---------------------------------------------------------------------------
class _KickoffDeclareBase(HubTool):
    """Shared: wrap ONE typed item into a single-item section decision."""

    SECTION: str = ""

    def _declare(self, meeting_id: str, content: dict,
                 milestone_index: Optional[int] = None) -> ToolResult:
        decision = {"section": self.SECTION, "kind": "draft_section",
                    "content": {"section": self.SECTION, **content}}
        try:
            page = self._hubs.workhub.add_meeting_decision(
                meeting_id=meeting_id, decision=decision,
                agent=self._agent_id, milestone_index=milestone_index)
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        if isinstance(page, dict) and page.get("error"):
            return ToolResult.fail(page["error"])
        return ToolResult.ok(data={"declared": True, "section": self.SECTION,
                                   "meeting_id": meeting_id})


class KickoffDeclareUiPageTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_ui_page"
    SECTION = "frontend"
    DESCRIPTION = (
        "Declare ONE ui_page of your kickoff frontend section (call once per "
        "page — declarations merge into the section automatically). Flat "
        "params; no nested JSON.")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "id": {"type": "string", "description": "snake_case page id, e.g. home_feed"},
        "route": {"type": "string", "description": "router path, e.g. /feed"},
        "purpose": {"type": "string", "description": "1-2 sentences"},
        "components": {"type": "array", "items": {"type": "string"}, "description":
                       "IDs of REUSABLE child components this page composes (each "
                       "declared via kickoff_declare_ui_component, lives in "
                       "src/components/). Do NOT put the page's ROOT component here "
                       "— that goes in `component` (singular)."},
        "must_have": {"type": "array", "items": {"type": "string"}},
        "component": {"type": "string", "description":
                      "React component name implementing this page, e.g. BoardListPage"},
        "apis_used": {"type": "array", "items": {"type": "string"}, "description":
                      "endpoints this page calls, e.g. ['GET /api/boards', 'POST /api/boards'] "
                      "— drives the page's defined→implemented lifecycle"},
        # #727: HOW TO REACH THE STATE A REFERENCE SHOWS. Measured on r148: of 20 reference
        # screens, 8 have no page at all — account_menu, browse_home_rows, card_hover_preview,
        # card_preview, player_controls, rate_dialog, shows_genres_menu, title_episodes. Every
        # one is an INTERACTION state (an opened menu, a scroll, a hover, a modal, player
        # chrome), reachable only by acting on a page, while the visual capture only navigates.
        # So the gate photographs the base page, scores it against a reference showing the
        # overlay, and the screen can never pass: card_hover_preview BLOCKS in 36 of 54
        # appearances with a maximum of 0.40 against a 0.65 bar.
        #
        # The agent that built the page knows how to reach the state; the gate is guessing. This
        # lets it say so. It does NOT hand over the standard — the gate scores against the
        # orchestrator-side reference original, outside the lane's workspace, so a wrong `reach`
        # produces a capture that misses a fixed target and scores worse. There is no way to win
        # by lying, which is what separates this from #566z's authored expectations.
        #
        # DECLARATION ONLY in this change: nothing consumes `reach` yet and no gate behaviour
        # moves. That is deliberate — item 49 records both failure modes of consuming it early
        # (advisory would silently drop all 8 screens at the measured fill rate; blocking would
        # wedge every run until the lane declares) and the cheapest way to tell those apart is
        # one run that counts ADOPTION with the gate untouched.
        #
        # Flat, per this tool's own convention: a list of "verb:selector" strings, not nested
        # JSON.
        "reference": {"type": "string", "description":
                      "OPTIONAL basename of the reference image this page or state corresponds "
                      "to, e.g. 'card_hover_preview.jpg'. Only needed when it differs from the "
                      "page id — the gate matches by normalised filename otherwise."},
        "reach": {"type": "array", "items": {"type": "string"}, "description":
                  "OPTIONAL steps to perform AFTER navigating to `route` and BEFORE the "
                  "screenshot, so a state that is not its own page can be photographed. Flat "
                  "'verb:selector' strings, in order, e.g. "
                  "['hover:.title-card:first-child'] for a hover preview, "
                  "['click:[data-testid=account-menu]'] for an opened menu, "
                  "['scroll:800'] for a scrolled view. Verbs: hover, click, scroll, wait. "
                  "Declare this for any reference screen that is an INTERACTION state — a menu, "
                  "modal, hover, or scrolled view — because the capture only navigates and will "
                  "otherwise photograph the base page and score it against your overlay."},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "id", "route"]}

    async def _run(self, meeting_id: str, id: str, route: str,
                   purpose: str = "", components: Optional[list] = None,
                   must_have: Optional[list] = None,
                   component: str = "", apis_used: Optional[list] = None,
                   reference: str = "", reach: Optional[list] = None,
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        page = {"id": id, "route": route}
        if purpose: page["purpose"] = purpose
        if components: page["components"] = [str(c) for c in components][:60]
        if must_have: page["must_have"] = [str(m) for m in must_have][:60]
        if component: page["component"] = str(component)
        if apis_used: page["apis_used"] = [str(a) for a in apis_used][:60]
        if reference: page["reference"] = str(reference)
        if reach: page["reach"] = [str(r) for r in reach][:12]
        return self._declare(meeting_id, {"ui_pages": [page]}, milestone_index)


class KickoffDeclareUiComponentTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_ui_component"
    SECTION = "frontend"
    DESCRIPTION = (
        "Declare ONE reusable ui_component of your kickoff frontend section "
        "(call once per component — declarations merge). Components are the "
        "API-OWNING layer: a page lists component ids in its `components`; "
        "each component declares the APIs IT calls and may nest `children`. "
        "Flat params; no nested JSON.")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "id": {"type": "string", "description": "snake_case component id, e.g. card_grid"},
        "component": {"type": "string", "description":
                      "React component name in code, e.g. CardGrid"},
        "kind": {"type": "string", "description":
                 "free-form hint, e.g. nav/list/form/card/detail/composite"},
        "purpose": {"type": "string", "description": "1 sentence"},
        "apis_used": {"type": "array", "items": {"type": "string"}, "description":
                      "endpoints THIS component calls, e.g. ['GET /api/boards']"},
        "children": {"type": "array", "items": {"type": "string"}, "description":
                     "nested component ids this component composes"},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "id"]}

    async def _run(self, meeting_id: str, id: str, component: str = "",
                   kind: str = "", purpose: str = "",
                   apis_used: Optional[list] = None,
                   children: Optional[list] = None,
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        comp = {"id": id}
        if component: comp["component"] = str(component)
        if kind: comp["kind"] = str(kind)
        if purpose: comp["purpose"] = purpose
        if apis_used: comp["apis_used"] = [str(a) for a in apis_used][:60]
        if children: comp["children"] = [str(c) for c in children][:60]
        return self._declare(meeting_id, {"ui_components": [comp]}, milestone_index)


class KickoffDeclareUserFlowTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_user_flow"
    SECTION = "frontend"
    DESCRIPTION = (
        "Declare ONE user_flow of your kickoff frontend section (call once "
        "per flow — declarations merge). Flat params.")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "id": {"type": "string", "description": "snake_case flow id, e.g. flow_auth"},
        "description": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "critical": {"type": "boolean"},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "id", "description"]}

    async def _run(self, meeting_id: str, id: str, description: str,
                   steps: Optional[list] = None, critical: Optional[bool] = None,
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        flow = {"id": id, "description": description}
        if steps: flow["steps"] = [str(x) for x in steps][:60]
        if critical is not None: flow["critical"] = bool(critical)
        return self._declare(meeting_id, {"user_flows": [flow]}, milestone_index)


class KickoffDeclarePredicateTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_predicate"
    SECTION = "verifier"
    DESCRIPTION = (
        "Declare ONE acceptance predicate of your kickoff verifier section "
        "(call once per predicate — declarations merge). Flat params.")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "id": {"type": "string", "description": "snake_case predicate id"},
        "description": {"type": "string", "description": "machine-checkable criterion"},
        "kind": {"type": "string", "description": "e.g. api_smoke / visual / behavioral"},
        "flow_id": {"type": "string", "description": "user_flow this predicate covers"},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "id", "description"]}

    async def _run(self, meeting_id: str, id: str, description: str,
                   kind: str = "", flow_id: str = "",
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        pred = {"id": id, "description": description}
        if kind: pred["kind"] = kind
        if flow_id: pred["flow_id"] = flow_id
        return self._declare(meeting_id, {"predicates": [pred]}, milestone_index)


class KickoffDeclareEndpointTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_endpoint"
    SECTION = "backend"
    DESCRIPTION = (
        "Declare ONE endpoint of your kickoff backend section (call once per "
        "endpoint — declarations merge). Flat params; response_key names the "
        "payload key (item/items).")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "path": {"type": "string", "description": "/api/... or /auth/..."},
        "purpose": {"type": "string"},
        "response_key": {"type": "string", "description": "item or items"},
        "auth_required": {"type": "boolean"},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "method", "path"]}

    async def _run(self, meeting_id: str, method: str, path: str,
                   purpose: str = "", response_key: str = "",
                   auth_required: Optional[bool] = None,
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        ep = {"method": str(method).upper(), "path": path, "id": f"{str(method).upper()} {path}"}
        if purpose: ep["purpose"] = purpose
        if response_key: ep["response_key"] = response_key
        if auth_required is not None: ep["auth_required"] = bool(auth_required)
        return self._declare(meeting_id, {"endpoints": [ep]}, milestone_index)


class KickoffDeclareTableTool(_KickoffDeclareBase):
    NAME = "kickoff_declare_table"
    SECTION = "backend"
    DESCRIPTION = (
        "Declare ONE data_model table of your kickoff backend section (call "
        "once per table — declarations merge). columns: 'name:type' strings, "
        "optionally 'name:type:pk' or 'name:type:fk=users.id'. Set "
        "owner_scoped_reads=true ONLY for a table where EVERY read is PER-USER-"
        "PRIVATE (notes/email/todos/drafts/DMs): the framework scopes every read to "
        "the owner by construction, exactly like writes. ⚠ CRITICAL — do NOT set it "
        "for PUBLIC content that merely HAS an owner (videos/posts/tweets/comments in "
        "a social app): those rows are OWNED but PUBLICLY readable — anyone watches "
        "anyone's feed. Owning a row (you created it) is NOT the same as a private "
        "read. If you ALSO need a 'my X' profile view, keep this table false and add "
        "ONE authenticated GET /api/me/<x> that filters by owner in custom_routes.py — "
        "do NOT flip the whole table private (that force-auths its public feed → the "
        "logged-out feed 401s → the ui_flow gate wedges). Set true only when the table "
        "has NO public view at all. If you DO set it true but the table still has a "
        "PUBLIC read (a feed/explore/public by-id), you MUST declare those specific read "
        "endpoints auth_required=false — that serves them public (all rows, no login) "
        "even on an owner-scoped table; only the authenticated 'my X' endpoint stays "
        "owner-scoped.")
    PARAMETERS = {"type": "object", "properties": {
        "meeting_id": {"type": "string"},
        "name": {"type": "string", "description": "snake_case table name"},
        "columns": {"type": "array", "items": {"type": "string"},
                    "description": "e.g. ['id:text:pk', 'caption:text', 'author_id:int:fk=users.id']"},
        "owner_scoped_reads": {"type": "boolean", "description":
            "true ⇒ per-user-private: reads (list/get/search) are owner-scoped "
            "(each user sees only their own rows). Default false = public reads "
            "(anyone may read any row, e.g. a social feed). Needs an owner FK to "
            "users (e.g. user_id/author_id)."},
        "milestone_index": {"type": "integer", "minimum": 0},
    }, "required": ["meeting_id", "name", "columns"]}

    async def _run(self, meeting_id: str, name: str, columns: list,
                   owner_scoped_reads: Optional[bool] = None,
                   milestone_index: Optional[int] = None,
                   **_extra: Any) -> ToolResult:
        cols = []
        for c in columns or []:
            parts = str(c).split(":")
            col = {"name": parts[0].strip()}
            if len(parts) > 1 and parts[1].strip():
                col["type"] = parts[1].strip()
            for extra in parts[2:]:
                extra = extra.strip()
                if extra == "pk":
                    col["primary_key"] = True
                elif extra.startswith("fk="):
                    col["references"] = extra[3:]
                elif extra == "unique":
                    col["unique"] = True
                elif extra == "nullable":
                    col["nullable"] = True
            cols.append(col)
        table = {"name": name, "columns": cols}
        if owner_scoped_reads is not None:
            table["owner_scoped_reads"] = bool(owner_scoped_reads)
        return self._declare(
            meeting_id, {"data_model": {"tables": [table]}}, milestone_index)



HUB_TOOL_CLASSES = [
    KickoffDeclareUiPageTool,
    KickoffDeclareUiComponentTool,
    RegistryHubUpdateTableSchemaTool,
    RegistryHubRegisterVerificationChainTool,
    WorkhubListUiPagesTool,
    WorkhubListUiComponentsTool,
    KickoffDeclareUserFlowTool,
    KickoffDeclarePredicateTool,
    KickoffDeclareEndpointTool,
    KickoffDeclareTableTool,
    # PR-review ceremony tools are NOT registered (user-approved removal): the
    # review/merge-PR workflow never ran in practice (0 calls across runs) while
    # delivery goes through the integration merge + create_release. The classes
    # remain defined (service layer + direct-construction tests) but agents
    # cannot call them: CodeHubReviewPRTool, CodeHubMergePRTool,
    # RegistryHubRequestReviewTool, RegistryHubSubmitReviewTool.
    # FocusHubTool is no longer registered — hub-focus gating is off by default
    # (step_pipeline/action.py): writes are offered directly; the switching tool
    # only produced focus-thrash (hundreds of wasted LLM turns per run).
    CodeHubCommitTool,
    CodeHubRegisterRepoTool,
    CodeHubRecordCommitTool,
    CodeHubOpenPRTool,
    CodeHubRecordCheckTool,
    CodeHubListInlineCommentsTool,
    CodeHubSuggestReviewersTool,
    CodeHubForceMergeTool,
    CodeHubCreateReleaseTool,
    CodeHubGetDiffTool,
    CodeHubGetBlobTool,
    CodeHubGetFileContentTool,
    CodeHubListPRsTool,
    CodeHubListChecksTool,
    CodeHubResolveConflictTool,
    CodeHubResolveMergeConflictTool,
    CodeHubRevertCommitTool,
    WorkHubCreateDocumentTool,
    WorkHubUpdatePageTool,
    WorkHubTaskTool,
    WorkHubFailTaskTool,
    WorkHubCancelTaskTool,
    WorkHubGetTaskTool,
    WorkHubListTasksTool,
    WorkHubAvailableTasksTool,
    WorkhubSetPriorityTool,
    WorkhubListReadyTool,
    WorkhubListBlockedTool,
    WorkHubGetDocumentTool,
    WorkHubListDocumentsTool,
    WorkHubLinkTaskToPrTool,
    WorkHubLinkTaskToApisTool,
    WorkHubUpdateBlockTool,
    WorkHubArchiveDocumentTool,
    WorkHubRecordDecisionTool,
    WorkHubCommentsForTool,
    WorkhubCreateMeetingTool,
    WorkhubAddMeetingDecisionTool,
    WorkhubCloseMeetingTool,
    WorkHubInviteAttendeeTool,
    WorkHubRemoveAttendeeTool,
    WorkHubCommentTool,
    WorkHubReplyTool,
    WorkHubShareImplementationTool,
    RegistryHubRegisterEndpointTool,
    RegistryHubUpdateSchemaTool,
    RegistryHubListEndpointsTool,
    RegistryHubGetEndpointTool,
    RegistryHubConsumerTool,
    RegistryHubCheckEndpointDriftTool,
    RegistryHubGetDependenciesForFileTool,
    RegistryHubGetBreakingChangesTool,
    RegistryHubRecordContractTestTool,
    RegistryHubDeprecateEndpointTool,
    RegistryHubRegisterTableTool,
    RegistryHubListTablesTool,
    RegistryHubRegisterTableConsumerTool,
    RegistryHubGetTableBreakingChangesTool,
    EventHubInboxTool,
    EventHubSubscribeTool,
    EventHubUnsubscribeTool,
    EventHubListSubscriptionsTool,
    EventHubGetThreadTool,
    EventHubReplyInThreadTool,
    EventHubMarkAllReadTool,
    EventHubGetAgentStatusTool,
    HubSnapshotTool,
]

_finalize_hub_tools(HUB_TOOL_CLASSES)

# Unregistered tool classes (PR-review ceremony + focus_hub): agents cannot call
# them (not in HUB_TOOL_CLASSES → never offered), but they stay CONSTRUCTIBLE —
# the service-contract tests instantiate them directly, and _finalize is what
# attaches the concrete execute/tool_definition adapters.
_UNREGISTERED_HUB_TOOL_CLASSES = [
    FocusHubTool,
    CodeHubReviewPRTool,
    CodeHubMergePRTool,
    RegistryHubRequestReviewTool,
    RegistryHubSubmitReviewTool,
]
_finalize_hub_tools(_UNREGISTERED_HUB_TOOL_CLASSES)


def create_hub_tools(agent_id: str = "", hub_workspace: Any = None, include_names: set[str] | None = None) -> list:
    tools = [cls(agent_id=agent_id, hub_workspace=hub_workspace) for cls in HUB_TOOL_CLASSES]
    if include_names:
        tools = [tool for tool in tools if getattr(tool, "NAME", "") in include_names]
    return tools
