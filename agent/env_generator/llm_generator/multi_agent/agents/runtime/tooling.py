from __future__ import annotations

import asyncio
import difflib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from utils.tool import ToolResult

from ...tool_surface import summarize_tool_surface
from ...tools import Workspace, assemble_tool_pool, create_tool_assembly_context


# Common shell/search tool-name confusions agents reach for when the canonical
# tool isn't obvious — mapped to the real tools, filtered at call time to only
# those the agent actually has granted.
_TOOL_INTENTS = (
    (("bash", "shell", "command", "exec", "run", "cmd", "terminal"),
     ("execute_bash", "execute_ipython", "local_bash")),
    (("search", "grep", "find", "glob", "locate", "lookup"),
     ("grep", "glob", "find_definition", "find_references",
      "list_generated_files", "codehub_get_file_content")),
)


def suggest_tools(tool_name: str, available) -> list:
    """Closest GRANTED tool names for an unknown ``tool_name``.

    Agents otherwise burn rounds guessing variants (observed in the youtube run:
    execute_command / local_bash / shell / run_command for execute_bash). Try a
    fuzzy (typo) match against the agent's available tools first; if none, fall
    back to an intent map (shell / file-search). Only ever returns tools the
    agent actually has, so every suggestion is immediately callable."""
    available = list(available)
    low = tool_name.lower()
    # Intent map FIRST: a curated SEMANTIC mapping must beat a spurious fuzzy
    # hit. `run_command` fuzzy-matched `workhub_comment` (shared 'comm'),
    # preempting the shell intent → the orchestrator was pointed at the wrong
    # tool and burned rounds. Now the shell/search intent leads, with fuzzy
    # (typo) hits appended as secondary so genuine typos still resolve.
    intent_hits: list = []
    for keys, cands in _TOOL_INTENTS:
        if any(k in low for k in keys):
            intent_hits.extend(c for c in cands if c in available and c not in intent_hits)
    fuzzy = difflib.get_close_matches(tool_name, sorted(available), n=3, cutoff=0.6)
    out = intent_hits + [h for h in fuzzy if h not in intent_hits]
    return out[:3]


_TOOL_IO_LOG_THRESHOLD = int(os.environ.get('ENVGEN_TOOL_IO_LOG_CHARS', '20000') or 20000)


# #257: per-tool RESULT-SIZE accounting. r51 measured 456.7M prompt vs 0.9M completion
# tokens — the run's whole cost is prompt — and the uncached share was ~0.8x the per-step
# GROWTH, i.e. the prompt cache is already near-optimal and the spend is simply how much
# NEW text each step appends: 35-51k tokens per step per lane. That is tool OUTPUT, and
# nothing recorded which tool produced it, so there was no way to aim. One line per call
# plus a per-run rollup makes the next run answer it directly. Cheap (a len()), off the
# hot path, and never raises.
_TOOL_IO_TOTALS: Dict[str, list] = {}


def _record_tool_io(agent, tool_name: str, result) -> None:
    try:
        payload = getattr(result, "output", None)
        if payload is None:
            payload = getattr(result, "data", None)
        if payload is None:
            payload = getattr(result, "error_message", "") or ""
        # #262: measure what actually lands in the CONVERSATION. The step pipeline pops
        # ``multimodal_content`` out of the result and injects it as a real image part
        # (where #248 then bounds it), so counting it here credited view_image with 4.6M
        # chars in r54 and pointed the whole reduction effort at a non-problem. An
        # instrument that measures the wrong thing is worse than none: it aims confidently.
        if isinstance(payload, dict) and "multimodal_content" in payload:
            payload = {k: v for k, v in payload.items() if k != "multimodal_content"}
        size = len(payload) if isinstance(payload, str) else len(str(payload))
        row = _TOOL_IO_TOTALS.setdefault(tool_name, [0, 0, 0])
        row[0] += 1
        row[1] += size
        row[2] = max(row[2], size)
        if size >= _TOOL_IO_LOG_THRESHOLD:
            logger = getattr(agent, "_logger", None)
            if logger is not None:
                logger.info("[tool-io] %s returned %s chars (~%sk tokens)",
                            tool_name, f"{size:,}", size // 4000)
    except Exception:
        pass


def tool_io_rollup(top: int = 25) -> str:
    """Human-readable 'where did the prompt tokens come from' table."""
    rows = sorted(_TOOL_IO_TOTALS.items(), key=lambda kv: -kv[1][1])[:top]
    out = ["[tool-io] TOTAL chars returned per tool (calls / total / mean / max):"]
    for name, (n, tot, mx) in rows:
        out.append(f"  {name:34} {n:6}  {tot:12,}  {tot // max(n, 1):9,}  {mx:10,}")
    return "\n".join(out)


def drop_unaccepted_kwargs(fn: Any, tool_args: Dict) -> tuple:
    """(kept, dropped_names) — strip args the callee cannot accept (#360).

    Tools are invoked as `exec_fn(**tool_args)`, so an argument the model
    supplies that the signature does not declare raises
    `TypeError: got an unexpected keyword argument` and the whole call is lost.
    124 such failures across the corpus (34 'uses', 14 'branch', 12 'task_id',
    9 'error', 8 'check', 6 'ref', 4 'metadata' — that last one being agents
    trying to pass metadata to codehub_record_check, which has no such param).

    Same class as #335: an LLM-authored argument list meeting a strict boundary
    unnormalised. Dropping the surplus keeps the call alive and the WARNING
    keeps the mismatch visible. A signature with **kwargs accepts everything, so
    nothing is dropped there; an uninspectable callable is left untouched.
    """
    if not isinstance(tool_args, dict) or not tool_args:
        return tool_args, []
    try:
        import inspect
        sig = inspect.signature(fn)
    except Exception:
        return tool_args, []
    params = sig.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return tool_args, []
    accepted = {p.name for p in params
                if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              inspect.Parameter.KEYWORD_ONLY)}
    dropped = sorted(k for k in tool_args if k not in accepted)
    if not dropped:
        return tool_args, []
    return {k: v for k, v in tool_args.items() if k in accepted}, dropped


def missing_required_args_634(fn: Any, tool_args: Dict) -> list:
    """The declared parameters this call omits — the mirror of #360's surplus (list, sorted).

    #360 handles the argument the callee cannot accept. This is the other half: an argument the
    callee REQUIRES. `exec_fn(**tool_args)` then raises before any of the tool's own code runs,
    and the raw Python text is what the agent gets back:

        submit_retro FAILED (0ms): SubmitRetroTool.execute() missing 3 required
        keyword-only arguments: 'systematic_failures', 'lessons' and ...

    Measured over the 56 run logs: **124 such failures across 5 tools and 19+ runs**
    (submit_retro 106, send_message 8, broadcast 5, ask_agent 1, lint 1). It is pure waste,
    because the tools already carry the answer — `SubmitRetroTool` validates that
    `plan_vs_reality` holds >= 2 dicts with specific keys and returns a teaching message saying
    so. Python rejects the call first, so that message is unreachable exactly when it is needed.

    A signature with **kwargs, or one that cannot be inspected, yields [] — never guess.
    """
    try:
        import inspect
        sig = inspect.signature(fn)
    except Exception:
        return []
    args = tool_args if isinstance(tool_args, dict) else {}
    return sorted(
        p.name for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.name not in ("self", "cls")
        and p.name not in args)


def missing_args_message_634(tool_name: str, missing: list, tool: Any) -> str:
    """Name each missing parameter WITH its declared type and description.

    The point of #634: "missing 3 required keyword-only arguments" names them but says nothing
    about their shape, which is what the caller got wrong. Every tool already publishes that in
    its `PARAMETERS` JSON schema — the same text the model was shown — so quote it back.
    """
    props = {}
    try:
        props = ((getattr(tool, "PARAMETERS", None) or {}).get("properties") or {})
    except Exception:
        props = {}
    lines = []
    for name in missing:
        spec = props.get(name) or {}
        kind = str(spec.get("type") or "").strip()
        desc = str(spec.get("description") or "").strip()
        detail = " — ".join(x for x in (kind, desc) if x)
        lines.append(f"  {name}{': ' + detail if detail else ''}")
    return (f"{tool_name}: missing required argument(s). Supply them and call again:\n"
            + "\n".join(lines))


def _effective_write_identity(agent: Any) -> Optional[str]:
    """The identity a role-write gate must be evaluated against.

    A spawned lane carries an INSTANCE id (``design_analyst_1``,
    ``api_test_user_1_api_smoke``) while ``PathRoutedWorkspace.ROUTING_TABLE``
    grants routes to the PROFILE name (``design_analyst``) by exact string
    match. Gating on the raw instance id therefore fails closed against a route
    the lane genuinely owns — r91/r92 denied 12/12 and 11/11 of the Design
    Analyst's ``decompose_reference`` writes to ``design/component_specs/``,
    so the measure-per-component phase that feeds UI fidelity produced nothing
    (and r93 stopped calling the tool at all).

    A spawned worker may also inherit the permission identity of its spawner,
    which takes precedence over the profile.
    """
    effective = getattr(agent, "agent_id", None)
    permission_parent_id = getattr(agent, "_permission_parent_id", None)
    config_key = getattr(agent, "_config_key", None)
    if permission_parent_id:
        return permission_parent_id
    if config_key:
        return config_key
    return effective


def coerce_tool_args(schema: Any, tool_args: Dict) -> Dict:
    """Coerce LLM-authored args to the types their own JSON-Schema declares.

    Every tool advertises PARAMETERS to the model, but nothing applied it, and an
    OpenAI-compatible gateway routinely emits an integer as "1" or an object as a
    JSON *string*. Two P0s came from exactly that:

    * `codehub_record_check(evidence=...)` is declared `type: object`; a JSON
      STRING was persisted verbatim and every reader of `validation:*` evidence
      then raised `'str' object has no attribute 'get'`. r91 logged
      "framework delivery raised (non-fatal)" 218 times over 4h26m with the whole
      delivery-gate layer dead inside that try block, and finished with no
      delivery. One malformed row poisons the rest of the run.
    * `milestone_index` is declared `integer` but arrived as a string in 502 calls
      (71% of recent kickoff_declare_predicate calls); workhub's strict
      isinstance check rejected every one, and r92's M2 ended with zero declared
      predicates.

    Fail-open by construction: anything that cannot be coerced is returned
    untouched, so this can never turn a working call into a failing one. Only
    keys the schema actually declares are considered.
    """
    if not isinstance(tool_args, dict) or not tool_args:
        return tool_args
    try:
        props = (schema or {}).get("properties")
    except Exception:
        return tool_args
    if not isinstance(props, dict) or not props:
        return tool_args
    out = dict(tool_args)
    for key, value in tool_args.items():
        spec = props.get(key)
        if not isinstance(spec, dict) or value is None:
            continue
        declared = spec.get("type")
        try:
            coerced = _coerce_one(declared, value)
        except Exception:
            continue
        if coerced is not _UNCOERCED:
            out[key] = coerced
    return out


_UNCOERCED = object()


def _coerce_one(declared: Any, value: Any) -> Any:
    """One value against one declared type. Returns ``_UNCOERCED`` to leave it."""
    import json as _json
    if declared == "integer":
        # bool is a subclass of int — a True must stay a True, not become 1.
        if isinstance(value, bool) or isinstance(value, int):
            return _UNCOERCED
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return _UNCOERCED
    if declared == "number":
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return _UNCOERCED
        if isinstance(value, str):
            return float(value.strip())
        return _UNCOERCED
    if declared == "boolean":
        if isinstance(value, bool):
            return _UNCOERCED
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "yes", "1"):
                return True
            if low in ("false", "no", "0"):
                return False
        return _UNCOERCED
    if declared == "object":
        if isinstance(value, dict):
            return _UNCOERCED
        if isinstance(value, str):
            try:
                parsed = _json.loads(value)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
            # A non-object value for a declared object still must not reach a
            # consumer that calls .get()/.items() — wrap rather than persist raw.
            return {"raw": value}
        return _UNCOERCED
    if declared == "array":
        if isinstance(value, (list, tuple)):
            return _UNCOERCED
        if isinstance(value, str):
            try:
                parsed = _json.loads(value)
            except Exception:
                return _UNCOERCED
            if isinstance(parsed, list):
                return parsed
        return _UNCOERCED
    return _UNCOERCED


# #611: the argument keys that identify WHAT a tool acted on, most specific first.
# Ordered so a hub id wins over a generic `name`; at most three are logged.
_TARGET_ARG_KEYS_611 = (
    "task_id", "document_id", "meeting_id", "endpoint_id", "chain_id", "page_id",
    "component_id", "table", "table_name", "bug_id", "pr_id", "run_id",
    "method", "url", "path", "file_path", "action", "resource", "name", "id",
    "status", "kind", "query", "pattern",
)
# credential-shaped keys are redacted — this log lands on disk
_SECRETISH_ARG_RE_611 = re.compile(
    r"pass|secret|token|auth|credential|api_?key|cookie", re.I)

class AgentTooling:
    # #681: THE HOST-CLASS CONTRACT, DECLARED.
    # This is a MIXIN: `agent_id`, `_logger`, `_hubs` and the sibling methods below are
    # supplied by the class it is mixed into (multi_agent/agents/base.py), so a checker
    # reading this file alone reports every use as a missing attribute. That was 990 of
    # the 2218 diagnostics — 45%, the single largest class — and it buried the real ones:
    # the same sweep found #658 (two constructors called with arguments the classes do not
    # have) and a dangling `WorkHub` annotation, both genuine, under that noise.
    # Annotation-only, under TYPE_CHECKING: no runtime effect, no import at runtime.
    if TYPE_CHECKING:
        agent_id: str
        _logger: Any
        _tools: Any
        _tool_instances: Any
        workspace: Any
        base_dir: Any
        llm: Any
        _include_vision: Any
        allowed_tool_categories: Any
        _hubs: Any
        def log_tool_call(self, *a: Any, **k: Any) -> Any: ...

    def _register_env_gen_tools(self):
        """Register environment generation tools based on allowed_tool_categories."""
        include_browser = "browser" in self.allowed_tool_categories
        include_docker = "docker" in self.allowed_tool_categories
        include_vision = self._include_vision or ("vision" in self.allowed_tool_categories)
        # Phase 0: when the agent has a registered worktree (resolved
        # later by ``set_hubs``), build tools against a
        # ``PathRoutedWorkspace`` so ``app/*`` writes go to the agent's
        # OWN worktree while ``design/*``, ``shared/*`` and ``.memory/*``
        # stay rooted at the shared project base. Without a worktree
        # (early init, or stub agents in tests), fall back to the
        # shared base-dir Workspace.
        worktree = getattr(self, "_worktree_dir", None)
        if worktree is not None and self.workspace and hasattr(self.workspace, "base_dir"):
            from ...runtime.path_routed_workspace import PathRoutedWorkspace
            # attempt-6 R1 Residual 1 fix (2026-05-29): pass agent_id
            # EXPLICITLY rather than letting PathRoutedWorkspace infer
            # it from the code_root path string. Inference only works
            # when code_root literally lives at
            # ``<base_root>/worktrees/<agent_id>``; under any
            # non-standard layout the inference falls back to ``None``
            # and the cross-worktree gate previously failed OPEN (see
            # ``_sibling_worktree_owner`` — now also fail-closed when
            # self_agent is None, defense-in-depth).
            workspace_for_tools = PathRoutedWorkspace(
                base_root=self.workspace.base_dir,
                code_root=worktree,
                agent_id=self.agent_id,
            )
        elif self.workspace:
            workspace_for_tools = Workspace(str(self.workspace.base_dir))
        else:
            workspace_for_tools = Workspace(Path.cwd())
        # Re-audit (2026-05-29): _enforce_write_permissions used to
        # consult ``self.workspace`` (the WorkspaceManager, which has
        # no ``is_write_allowed``) so the role-gate was DEAD — every
        # write was silently allowed because ``hasattr(...,
        # "is_write_allowed")`` was always False. The actual
        # routing/permission decision lives on ``workspace_for_tools``
        # (the PathRoutedWorkspace whose ROUTING_TABLE the docstring
        # already refers to). Pin it on the agent so the gate can
        # find it. Fallback to ``self.workspace`` when the routed
        # workspace isn't built yet (early init / stub agents) —
        # ``_enforce_write_permissions`` still returns None there
        # because ``WorkspaceManager.is_write_allowed`` is absent.
        self._routed_workspace = workspace_for_tools

        agent_type_for_tools = getattr(
            self,
            "_tool_profile_agent_type",
            getattr(self, "_config_key", self.agent_id),
        )
        tool_context = create_tool_assembly_context(
            agent_type=agent_type_for_tools,
            agent_id=self.agent_id,
            workspace=workspace_for_tools,
            include_browser=include_browser,
            include_docker=include_docker,
            include_vision=include_vision,
            llm_client=self.llm,
            allowed_tool_categories=self.allowed_tool_categories,
            allow_tools=list(getattr(self, "_allow_tools", []) or []),
            deny_tools=list(getattr(self, "_deny_tools", []) or []),
            assembly_mode="agent",
            tool_profile_id=agent_type_for_tools,
            tool_bundle_ids=list(getattr(self, "_tool_bundle_ids", []) or []),
        )
        agent_tools = assemble_tool_pool(tool_context)

        if not agent_tools:
            self._logger.warning(f"[{self.agent_id}] No tools returned from get_agent_tools")

        for tool_instance in agent_tools:
            try:
                if hasattr(tool_instance, "set_agent"):
                    tool_instance.set_agent(self)
                self._tool_instances[tool_instance.NAME] = tool_instance
                self._tools.register(tool_instance)
            except Exception as e:
                name = getattr(tool_instance, "NAME", "<unknown>")
                self._logger.warning(f"Tool {name} init failed: {e}")
        self._log_tool_surface_summary(source="register")
        self._validate_stage_allowlists_against_pool()

    def _validate_stage_allowlists_against_pool(self) -> None:
        """TOOL-系统 startup cross-validator (2026-06-12): warn on every
        stage_tool_allowlist entry the assembled pool does not grant. Dead
        entries read like granted capabilities ("deliberately generous"
        allowlists) and masked real breakages for weeks — the verifier's
        bug_create (TOOL-C1) and its whole browser toolset among them. Warn,
        don't raise: the agent still runs with the tools it has; the paired
        structural test (test_tool_allowlist_cross_validator) is what keeps
        the shipped config at zero violations."""
        try:
            from ...tool_surface import (
                validate_stage_allowlists, validate_skill_consult_preconditions)
            _profile_id = getattr(self, "_tool_profile_agent_type",
                                  getattr(self, "agent_id", "?"))
            _granted = set(getattr(self, "_tool_instances", {}) or {})
            problems = validate_stage_allowlists(
                _profile_id,
                stage_tool_allowlist=getattr(self, "_stage_tool_allowlist", {}) or {},
                granted_tool_names=_granted,
            )
            # SYS-1 (PROPOSAL #14): a *_consulted precondition instructs the agent to
            # call get_skill — so the profile MUST grant it, else the gate is
            # unsatisfiable and the gated tool loops forever (run #21 / BUG#5).
            problems += validate_skill_consult_preconditions(
                _profile_id,
                stage_tool_preconditions=getattr(self, "_stage_tool_preconditions", {}) or {},
                granted_tool_names=_granted,
            )
            for problem in problems:
                self._logger.warning("%s", problem)
        except Exception as exc:  # never block agent startup on the audit
            self._logger.debug("stage-allowlist validation skipped: %s", exc)

    def _log_tool_surface_summary(self, *, source: str) -> None:
        summary = summarize_tool_surface(getattr(self, "_tool_instances", {}))
        preview = ", ".join(summary["names"][:12])
        self._logger.info(
            "[%s] Tool surface (%s): %s tools; categories=%s; preview=%s",
            self.agent_id,
            source,
            summary["count"],
            summary["by_category"],
            preview,
        )

    def get_tools_for_llm(self) -> List[Dict]:
        """Get tool definitions formatted for LLM."""
        if not hasattr(self._tools, "to_openai_tools"):
            raise RuntimeError(f"[{self.agent_id}] ToolRegistry missing to_openai_tools method")
        return self._tools.to_openai_tools()

    def set_hubs(self, hubs) -> None:
        """Set hub registry handle (HubRegistry) for observation-driven coordination."""
        self._hubs = hubs

        # Phase 0: now that CodeHub is reachable, register this agent's
        # git worktree and re-build the tool pool against a
        # ``PathRoutedWorkspace``. Tools assembled in ``__init__``
        # before hubs were available used the bare shared base; the
        # rebuild routes ``app/*`` writes into the agent's own
        # worktree.
        #
        # Phase 0.2 attempt-5 FIX B (R1 round-4 hole B, 2026-05-29):
        # Registration MUST fail-closed. Previously a registration
        # error (``register_agent_worktree`` raising, or — in legacy
        # call sites — returning ``None``) only logged WARNING and
        # left the tool pool bound to the bare ``Workspace`` built in
        # ``__init__``. That bare workspace does NOT carry the
        # ``ROUTING_TABLE``-driven per-route write gate, so any
        # registration hiccup silently re-opened arbitrary host writes
        # via the same path that ``GenerateSeedSQL`` (see
        # ``data_engine_tools.py:810``: ``self.workspace.root /
        # output_file`` with absolute-path pass-through, NO
        # ``workspace.resolve()`` call) and the other
        # FULLY_AGENT_CONTROLLED tools depend on the
        # ``PathRoutedWorkspace`` containment to lock down.
        #
        # The fix: registration failure raises ``RuntimeError`` so
        # the agent never enters its action loop on a permissive bare
        # ``Workspace``. The whole Phase 0.2 path-containment
        # guarantee depends on the agent running INSIDE
        # ``PathRoutedWorkspace`` — silent degrade is the security
        # regression R1 round-4 hole B flagged.
        # Phase 0.2 attempt-6 HARDENING A (R1 round-5 FIX B residual,
        # 2026-05-29): the previous predicate ``hasattr(hubs, "codehub")``
        # silently SKIPPED registration when hubs lacked a ``codehub``
        # attribute — re-opening exactly the same silent-degrade hole
        # the attempt-5 fix-closed contract was meant to seal. A hubs
        # object without ``codehub`` cannot register the worktree, and
        # proceeding leaves the agent on the bare permissive
        # ``Workspace`` (no ``PathRoutedWorkspace`` containment, R1
        # round-4 hole B regression). Raise instead.
        if hubs is not None and getattr(self, "_worktree_dir", None) is None:
            if not hasattr(hubs, "codehub"):
                try:
                    self._logger.error(
                        "[%s] Hubs object has no 'codehub' attribute. "
                        "Refusing to build tool pool with bare Workspace — "
                        "that would bypass PathRoutedWorkspace containment "
                        "and re-open arbitrary host write (R1 round-5 FIX B "
                        "residual: the hasattr-gated codehub check silently "
                        "skipped registration). Aborting agent.",
                        self.agent_id,
                    )
                except Exception:
                    pass
                raise RuntimeError(
                    f"hubs registry missing 'codehub' attribute for "
                    f"{self.agent_id}; refusing to fall back to "
                    f"permissive bare Workspace (R1 round-5 FIX B "
                    f"residual fail-closed)"
                )
            try:
                wt = hubs.codehub.register_agent_worktree(self.agent_id)
            except Exception as _wt_err:
                try:
                    self._logger.error(
                        "[%s] Agent worktree registration FAILED: %s. "
                        "Refusing to build tool pool with bare Workspace — "
                        "that would bypass PathRoutedWorkspace containment "
                        "and re-open arbitrary host write (R1 round-4 "
                        "hole B). Aborting agent. Operator must investigate "
                        "registration failure.",
                        self.agent_id,
                        _wt_err,
                    )
                except Exception:
                    pass
                raise RuntimeError(
                    f"agent worktree registration failed for {self.agent_id}; "
                    f"refusing to fall back to permissive bare Workspace "
                    f"(R1 round-4 hole B fail-closed): {_wt_err}"
                ) from _wt_err
            if wt is None:
                try:
                    self._logger.error(
                        "[%s] Agent worktree registration returned None. "
                        "Refusing to build tool pool with bare Workspace — "
                        "that would bypass PathRoutedWorkspace containment "
                        "and re-open arbitrary host write (R1 round-4 "
                        "hole B). Aborting agent. Operator must investigate "
                        "registration failure.",
                        self.agent_id,
                    )
                except Exception:
                    pass
                raise RuntimeError(
                    f"agent worktree registration failed for {self.agent_id}; "
                    "refusing to fall back to permissive bare Workspace "
                    "(R1 round-4 hole B fail-closed): register_agent_worktree "
                    "returned None"
                )
            self._worktree_dir = Path(wt)
            # Rebuild the tool pool with the worktree-aware workspace.
            # Clears _tool_instances and the public registry first so the
            # new generation replaces the old. A rebuild failure is
            # ALSO fail-closed — the new generation half-replaced the
            # old, and continuing on a permissive bare Workspace is
            # the same R1 round-4 hole B regression.
            try:
                self._tool_instances = {}
                if hasattr(self._tools, "_tools"):
                    # ToolRegistry exposes ``_tools`` dict; clear it.
                    self._tools._tools.clear()
                self._register_env_gen_tools()
            except Exception as _rebuild_err:
                try:
                    self._logger.error(
                        "[%s] Tool pool rebuild on PathRoutedWorkspace "
                        "FAILED: %s. Refusing to proceed on bare Workspace "
                        "(R1 round-4 hole B fail-closed).",
                        self.agent_id,
                        _rebuild_err,
                    )
                except Exception:
                    pass
                raise RuntimeError(
                    f"tool pool rebuild failed for {self.agent_id}; "
                    f"refusing to fall back to permissive bare Workspace "
                    f"(R1 round-4 hole B fail-closed): {_rebuild_err}"
                ) from _rebuild_err

        for tool in self._tool_instances.values():
            try:
                if hasattr(tool, "set_agent"):
                    tool.set_agent(self)
                else:
                    # Self-gating tools (they call is_write_allowed with their
                    # own _agent_id) must receive the WRITE identity, not the
                    # instance id — otherwise they fail closed on their own route.
                    setattr(tool, "_agent_id", _effective_write_identity(self))
                    # #453: set_team_protocols → inject_team_protocols runs AFTER this
                    # and CLOBBERS _agent_id back to the raw instance id (design_analyst_1)
                    # for message routing — which re-breaks the write gate (design_analyst_1
                    # ∉ the design/ writers set) so decompose_reference's writes to
                    # design/component_specs/*.json get 'write denied by role gate' (r35/r38:
                    # 40 denials/run, dropping the measured per-component specs the analyst
                    # reads back). Stash the WRITE identity under a dedicated attr that
                    # team-injection never touches; self-gating tools prefer it. Generalizable
                    # to any dynamic-suffixed agent's self-gating writes.
                    setattr(tool, "_write_agent_id", _effective_write_identity(self))
                if hasattr(tool, "_hubs"):
                    setattr(tool, "_hubs", hubs)
                # Tools that hold the registry as `hub_registry` (coverage, seed,
                # visual_review, mcp_registry, deliverability, retro) are built with
                # hub_registry=None at assembly time (context.hub_workspace is never
                # set) and have no set_agent/_hubs hook — bind the real registry here.
                if hasattr(tool, "hub_registry"):
                    setattr(tool, "hub_registry", hubs)
            except Exception as e:
                self._logger.debug(
                    f"[{self.agent_id}] Failed to inject hubs into {getattr(tool, 'NAME', type(tool).__name__)}: {e}"
                )

        self._logger.info(f"[{self.agent_id}] Hubs attached")

    def set_team_protocols(
        self,
        agent_manager=None,
        persona_catalog=None,
        plan_decision=None,
        parallel_reasoning=None,
        practice_store=None,
    ) -> None:
        """Set team protocols for advanced collaboration."""
        self._agent_manager = agent_manager
        self._persona_catalog = persona_catalog
        self._plan_decision = plan_decision
        self._parallel_reasoning = parallel_reasoning
        self._practice_store = practice_store

        from ...tools import TEAM_TOOLS_AVAILABLE, inject_team_protocols_to_tools

        if TEAM_TOOLS_AVAILABLE and self._tool_instances:
            inject_team_protocols_to_tools(
                tools=list(self._tool_instances.values()),
                agent_id=self.agent_id,
                agent_manager=agent_manager,
                persona_catalog=persona_catalog,
                plan_decision=plan_decision,
                parallel_reasoning=parallel_reasoning,
                practice_store=practice_store,
            )

        if any([agent_manager, persona_catalog, plan_decision, parallel_reasoning, practice_store]):
            self._logger.info(f"[{self.agent_id}] Team protocols configured")


    def _enforce_write_permissions(self, tool_name: str, tool_args: Dict) -> Optional[ToolResult]:
        """Enforce per-route write scopes via the routed workspace.

        Step 4 FOLD (docs/workspace_root_redesign.md): the
        ``ROUTING_TABLE`` in ``path_routed_workspace.py`` is now the
        single source of truth for which agent may write which prefix.
        Plain ``Workspace`` (test / orchestrator early-init) returns
        ``True`` from ``is_write_allowed`` — no role gate before the
        worktree exists.

        Re-audit fix (2026-05-29): consult
        ``self._routed_workspace`` (the ``PathRoutedWorkspace`` built
        in ``_register_env_gen_tools``) FIRST. The historical code
        read ``self.workspace`` — but that's the bare
        ``WorkspaceManager`` (only owns base_dir + init dirs; has no
        ``is_write_allowed`` method), so ``hasattr(...)`` returned
        False and the gate silently no-op'd every call. Backend
        could write to ``design/``, "read-only" lanes could write
        ``screenshots/`` / ``shared/`` — the entire role-gate was
        landed-but-dead. Fallback to ``self.workspace`` is preserved
        so early-init / stub-agent code paths still degrade to
        "no gate" rather than raising.
        """
        ws = (
            getattr(self, "_routed_workspace", None)
            if hasattr(self, "_routed_workspace")
              and getattr(self, "_routed_workspace", None) is not None
            else None
        )
        if ws is None:
            ws = self.workspace
        if ws is None or not hasattr(ws, "is_write_allowed"):
            return None

        # Effective agent id: a spawned worker may inherit the
        # permission identity of the agent that spawned it (e.g. backend
        # ↔ a backend-flavoured worker). Match the old resolution path.
        effective_agent_id = _effective_write_identity(self)

        write_targets: List[str] = []
        # ``update_json_path`` / ``update_yaml_path`` belong in the
        # gated set: both tools call ``_resolve_workspace_path``
        # (containment only) then ``_atomic_write_text``, bypassing
        # the role-write gate without this gate. A non-owner could
        # otherwise mutate a routed-write file (e.g. ``shared/*.json``)
        # through them. Their write target lives in the ``path``
        # argument (same shape as ``write``/``edit``), so the existing
        # ``file_path``-or-``path`` extraction below covers them
        # without further plumbing. The structural invariant test
        # in ``tests/test_write_gate_invariant.py`` recognises this set
        # as ``GATED_TOOL_NAMES`` and will now turn green for these
        # two tools.
        #
        # Phase 0.2 attempt-4 PHASE 2 FIX A (2026-05-29): add three
        # ``output_path``-class tools that PHASE 1 AUDIT A confirmed
        # are FULLY_AGENT_CONTROLLED writes:
        #   * ``generate_seed_sql`` — the HIGH-severity finding;
        #     ``data_engine_tools.py:810-813`` bypasses
        #     ``workspace.resolve()`` entirely (raw
        #     ``self.workspace.root / output_file`` with absolute-path
        #     pass-through). A traversal-class write equivalent to the
        #     Phase 0.2 RCE — needs the role gate now. Its write
        #     parameter is ``output_file`` (not ``file_path``/``path``),
        #     so add it to the extraction below.
        #   * ``save_image`` — MEDIUM (role-confusion only since
        #     ``workspace.resolve()`` contains escape, but no per-agent
        #     gate). Param is ``path``.
        #   * ``capture_webpage`` — MEDIUM (same shape as save_image).
        #     Param is ``path`` (optional; absent path means the tool
        #     uses a sanitised ``screenshots/<domain>.png`` fallback,
        #     which the gate will still evaluate against the route
        #     once the leaf is extracted — see fallback handling
        #     below).
        if tool_name in {
            "write",
            "delete_file",
            "edit",
            "apply_patch",
            "update_json_path",
            "update_yaml_path",
            "generate_seed_sql",
            "save_image",
            "capture_webpage",
        }:
            path = (
                tool_args.get("file_path")
                or tool_args.get("path")
                or tool_args.get("output_file")
            )
            if path:
                write_targets.append(path)
            if tool_name == "apply_patch":
                patch_text = tool_args.get("patch", "")
                if isinstance(patch_text, str):
                    for line in patch_text.splitlines():
                        if line.startswith("*** Add File: ") or line.startswith("*** Update File: "):
                            patch_path = line.split(": ", 1)[1].strip()
                            if patch_path:
                                write_targets.append(patch_path)
            elif tool_name == "capture_webpage" and not path:
                # CaptureWebpageTool's fallback writes to
                # ``screenshots/<sanitised_domain>.png`` (see
                # image_search_tools.py:698). ``screenshots/`` is a
                # READ-ONLY route in ROUTING_TABLE — so any agent
                # invocation without an explicit ``path`` lands on a
                # universally-denied prefix. Surface that as a write
                # target so the gate fires the correct deny.
                write_targets.append("screenshots/")
        elif tool_name == "copy_reference_image":
            dest = tool_args.get("destination")
            if dest:
                write_targets.append(dest)

        if not write_targets:
            return None

        denied = [p for p in write_targets if not ws.is_write_allowed(p, effective_agent_id)]
        if denied:
            # CLASS B (#36): if any denied path is a framework-OWNED file, say so
            # explicitly — the framework generates + overwrites these from the registered
            # contract, so editing them only creates conflicts + broken builds. Point the
            # lane at its actual authoring surface.
            fw_owned = []
            if hasattr(ws, "is_framework_owned"):
                fw_owned = [p for p in denied if ws.is_framework_owned(p)]
            if fw_owned:
                _tw_hint = ""
                if any("tailwind.config" in str(p) for p in fw_owned):
                    # The pinned tailwind.config imports ./tailwind.theme.js — define your
                    # design tokens THERE instead of editing the locked config.
                    _tw_hint = (
                        " To define theme tokens (the colors/fonts you @apply, e.g. a custom "
                        "`bg-ig-bg`), write `tailwind.theme.js` (frontend-WRITABLE; the pinned "
                        "tailwind.config.js imports it) — e.g. "
                        "`export default { colors: { 'ig-bg': '#000000' } }`. Never @apply a "
                        "class you haven't defined there (it fails the build)."
                    )
                # #678: THE MESSAGE IS GOOD; THE AGENT WAS NOT LISTENING.
                # Unlike the other entries in the wasted-STEPS ranking (#674-#677) this text
                # already names the cause AND the authoring surface — so the fix is not new
                # wording, it is noticing the repeat. Measured over the 249 run logs: 1546
                # framework-owned denials across 133 runs, and 61 (run, file) pairs hit the SAME
                # file 5+ times — worst case 52 attempts on one Dockerfile in a single run. Per
                # #257 each is a whole step re-sending the prompt.
                #
                # #664's lesson applies with one difference worth stating: there the counter had
                # to accumulate across calls to reach its threshold, so instance churn reset it
                # to zero permanently and the escalation fired 4 times in 4928. Here a single
                # surviving instance and two attempts is enough, and if a lane IS respawned the
                # worst case is the base message — exactly today's behaviour. So instance state
                # is sufficient and no store is needed.
                _fw_seen = getattr(self, "_fw_denied_678", None)
                if _fw_seen is None:
                    _fw_seen = {}
                    self._fw_denied_678 = _fw_seen
                _repeat_n = 0
                for _p in fw_owned:
                    _fw_seen[str(_p)] = _fw_seen.get(str(_p), 0) + 1
                    _repeat_n = max(_repeat_n, _fw_seen[str(_p)])
                _escalate_678 = "" if _repeat_n < 2 else (
                    f" ⚠ You have now tried to write {fw_owned} {_repeat_n} times. The answer "
                    "will not change — this path is framework-owned for the whole run and no "
                    "retry, rewording or different tool will make it writable. Stop attempting "
                    "it and make the change through the authoring surface named above, or "
                    "register the contract so the framework regenerates the file."
                )
                # #709: SAY WHICH KIND OF DENIAL THIS IS. `is_framework_owned` matches on the
                # lane prefix plus the BASENAME (path_routed_workspace.py:647), so a path the
                # framework does not generate is refused with a reason that is false for it.
                # Measured over the 253 kept logs: 1576 framework-owned write denials, of which
                # **134 name a path that is not the canonical one** —
                # `app/frontend/src/services/package.json` x98, `app/frontend/src/package.json`
                # x32, bare `package.json` x4. Telling a lane "the framework generates and
                # overwrites this" about a file the framework has never written leaves it
                # nothing to act on, and 98 retries on one path is what that looks like.
                #
                # The refusal itself stays — a nested package.json is not how a Vite app
                # declares dependencies, so denying it is right. Only the reason is corrected,
                # and it now carries the resolution instead of a false statement. Same class as
                # #682/#690: the detection was fine, the text was the cost.
                # Derived from the data that already exists, NOT from a new accessor: the
                # ownership map is (lane-prefix, basenames) and the basename match is
                # DELIBERATE — path_routed_workspace's own comment says it mirrors the conflict
                # resolver so the write guard and the resolver cannot diverge. So the semantics
                # stay; only "is this the canonical location" is inferred, and that is simply
                # whether the file sits directly under the lane prefix (app/frontend/
                # package.json) or nested deeper (app/frontend/src/services/package.json).
                # My first draft called a `framework_owned_paths()` that does not exist, which
                # would have made this whole branch dead — the exact defect class this session
                # has been finding.
                _canon_709 = []
                try:
                    from ...runtime.path_routed_workspace import _framework_owned_routes
                    for _p in (fw_owned or []):
                        _rel = str(_p).replace("\\", "/")
                        for _prefix, _bases in (_framework_owned_routes() or []):
                            if not _rel.startswith(_prefix):
                                continue
                            _tail = _rel[len(_prefix):]
                            if _tail in _bases:        # directly under the prefix == canonical
                                break
                            if _tail.rsplit("/", 1)[-1] in _bases:
                                _canon_709.append(_rel)
                            break
                except Exception:
                    _canon_709 = []
                if _canon_709:
                    _names = ", ".join(_canon_709)
                    return ToolResult(
                        success=False,
                        error_message=(
                            f"Write denied: {_names}. NOT because the framework generates that "
                            f"path — it does not. The name matches a framework-owned file "
                            f"elsewhere in this lane, and a second one here would shadow it. "
                            f"A frontend has ONE package.json, at app/frontend/package.json, "
                            f"and it is framework-owned: add dependencies by registering the "
                            f"contract, not by creating a nested manifest. If you were trying "
                            f"to add a module, a plain .js/.jsx file needs no manifest."),
                        metadata={"framework_owned": False, "shadowing_name": True},
                    )
                return ToolResult(
                    success=False,
                    error_message=(
                        f"Write denied: {fw_owned} are FRAMEWORK-OWNED files. The framework "
                        f"generates + overwrites them deterministically from the registered "
                        f"contract (tables/endpoints/pages) — editing them is discarded and "
                        f"causes merge conflicts. Author your business logic in "
                        f"custom_routes.py (backend) or src/pages/*.jsx + App.jsx (frontend); "
                        f"to change models/schemas/main, register the contract via the "
                        f"registryhub_* tools and the framework regenerates them."
                        + _tw_hint + _escalate_678
                    ),
                )
            # LANE-OWNED application code (app/backend|frontend|database/*) is authored
            # ONLY by the owning lane. A coordinator (orchestrator/debugger) reaching here
            # diagnosed a lane bug and tried to PATCH it — re-route, don't patch (the edit
            # lands in the wrong worktree and conflicts on merge).
            _lane_code = [
                p for p in denied
                if any(str(p).replace("\\", "/").lstrip("/").startswith(pre)
                       for pre in ("app/backend/", "app/frontend/", "app/database/"))
            ]
            if _lane_code:
                return ToolResult(
                    success=False,
                    error_message=(
                        f"Write denied: {_lane_code} is LANE-OWNED code — only the owning "
                        f"lane (backend/frontend/database) authors it. If you diagnosed a "
                        f"bug there, do NOT patch it from here. DISPATCH it: report_issue, "
                        f"or create a remediation task assigned to the owning lane (a new "
                        f"task re-wakes it even when idle), naming the exact file + the fix "
                        f"you found. Coordinators coordinate; lanes build."
                    ),
                )
            return ToolResult(
                success=False,
                error_message=(
                    f"Write permission denied for {self.agent_id}: {denied}. "
                    f"Check ROUTING_TABLE in multi_agent/runtime/path_routed_workspace.py "
                    f"for the route's allowed_writers."
                ),
            )
        return None

    def _enter_team_mode(self, reason: str = "") -> None:
        if self._execution_mode == "team":
            return
        self._execution_mode = "team"
        self._logger.info(
            f"[{self.agent_id}] Execution mode -> team{f' ({reason})' if reason else ''}"
        )

    def _exit_team_mode(self, reason: str = "") -> None:
        if self._execution_mode == "direct":
            return
        self._execution_mode = "direct"
        self._logger.info(
            f"[{self.agent_id}] Execution mode -> direct{f' ({reason})' if reason else ''}"
        )

    def _enforce_stage_preconditions(
        self, tool_name: str, tool_args: Dict
    ) -> Optional[ToolResult]:
        """PR3.2 — per-(stage, tool) precondition guard.

        Replaces "do not call X until Y" prompt prose with engine-side
        enforcement. The agent yaml may declare
        ``stage_tool_preconditions.<stage>.<tool>: <precondition_id>``;
        ``ConfigurableAgent.__init__`` validates ids against the
        registry (fail-closed at construction), so by the time we get
        here every id is resolvable.

        Returning a ``ToolResult`` blocks the call; returning ``None``
        lets it proceed. The block message surfaces to the LLM as a
        normal tool failure, naming the corrective action.
        """
        preconds = getattr(self, "_stage_tool_preconditions", None)
        if not preconds:
            return None
        stage = getattr(self, "_active_stage", None)
        if not stage:
            return None
        # Lookup chain (in priority order):
        #   1. ``"<phase>:<stage>"``  — composite phase-keyed (PR3.1.2 /
        #      Loop B ⑧). Used when ``_active_phase`` is pinned, e.g.
        #      ``"kickoff:action"`` during the orchestrator's kickoff
        #      handlers.
        #   2. ``"<stage>"``           — bare stage name. Matches the
        #      outer pipeline stages (hub_pulse / action / etc.) and
        #      the internal action sub-stages (communicate / edit_code
        #      / run_checks / delegate_team / deliver) when the yaml
        #      keys on them explicitly.
        #   3. ``"action"``            — Smoke #30 (2026-06-04) wedge
        #      cause. When ``finish`` is called from inside the action
        #      loop, ``_active_stage`` is the INTERNAL sub-stage
        #      (``deliver`` typically), not the outer ``action``. A
        #      yaml that keys ``stage_tool_preconditions.action.finish``
        #      would miss without this fallback — backend's 4
        #      'defined' endpoints stayed unprotected. Fall back to
        #      the outer ``action`` whenever the current stage is one
        #      of the action internal sub-stages.
        # Each level is tried in order; the FIRST match wins. Falsy
        # results (empty dict from yaml) fall through to the next
        # level.
        phase = getattr(self, "_active_phase", None)
        action_inner = set(getattr(self, "ACTION_INTERNAL_STAGES", ()) or ())
        stage_map = None
        if phase:
            stage_map = preconds.get(f"{phase}:{stage}") or None
        if not stage_map:
            stage_map = preconds.get(stage) or None
        if not stage_map and stage in action_inner:
            # Sub-stage of the action loop — fall back to the outer
            # "action" key so a single yaml entry covers all five
            # internal sub-stages.
            if phase:
                stage_map = preconds.get(f"{phase}:action") or None
            if not stage_map:
                stage_map = preconds.get("action") or None
        if not stage_map:
            return None
        pre_id = stage_map.get(tool_name)
        if not pre_id:
            return None
        from .preconditions import resolve_precondition
        checker = resolve_precondition(pre_id)
        if checker is None:
            # By construction (ConfigurableAgent validates ids at init)
            # this is unreachable. If it ever fires, an external caller
            # bypassed ConfigurableAgent — surface as a hard error
            # rather than a silent fallthrough.
            raise RuntimeError(
                f"unknown stage_tool_precondition id '{pre_id}' "
                f"reached dispatch for agent={self.agent_id} stage={stage} "
                f"tool={tool_name}"
            )
        err_msg = checker(self, tool_name, tool_args)
        if err_msg is None:
            return None
        return ToolResult(success=False, error_message=err_msg)

    def _enforce_execution_mode(self, tool_name: str) -> Optional[ToolResult]:
        """Enforce execution mode boundaries."""
        if getattr(self, "_active_stage", "action") != "action":
            return None

        is_team_tool = tool_name in self.TEAM_TOOL_NAMES
        if self._execution_mode == "direct":
            if is_team_tool:
                self._enter_team_mode(reason=f"tool={tool_name}")
            return None

        if is_team_tool or tool_name in self.TEAM_MODE_SUPPORT_TOOLS:
            return None

        return ToolResult(
            success=False,
            error_message=(
                f"Tool '{tool_name}' is blocked in team mode. "
                "In team mode, only team orchestration/coordination actions are allowed. "
                "Terminate team work first to return to direct mode."
            ),
        )

    async def _execute_tool(self, tool_name: str, tool_args: Dict) -> ToolResult:
        """Execute a tool and log it."""
        if tool_name in self._tool_instances:
            try:
                # Apply the tool's own declared JSON-Schema types BEFORE the
                # enforcement chain, so permission/precondition checks and the
                # tool body all see well-typed args (#335).
                tool_args = coerce_tool_args(
                    getattr(self._tool_instances[tool_name], "PARAMETERS", None),
                    tool_args,
                )
                mode_error = self._enforce_execution_mode(tool_name)
                if mode_error is not None:
                    self.log_tool_call(tool_name, tool_args, mode_error)
                    return mode_error

                permission_error = self._enforce_write_permissions(tool_name, tool_args)
                if permission_error is not None:
                    self.log_tool_call(tool_name, tool_args, permission_error)
                    return permission_error

                precondition_error = self._enforce_stage_preconditions(tool_name, tool_args)
                if precondition_error is not None:
                    self.log_tool_call(tool_name, tool_args, precondition_error)
                    return precondition_error

                # Human-in-the-loop approval gate: in `ask` mode this PAUSES gated
                # structural actions (task/gate creation) until a human approves in
                # Env Forge; a rejection returns the reviewer's feedback so the agent
                # revises. No-op in `auto` mode (default) — zero overhead otherwise.
                try:
                    from ...runtime.approval import enforce as _enforce_approval
                    approval_block = await _enforce_approval(
                        getattr(self, "_hubs", None), self.agent_id, tool_name, tool_args)
                    if approval_block is not None:
                        self.log_tool_call(tool_name, tool_args, approval_block)
                        return approval_block
                except Exception:
                    pass  # approval is best-effort — never wedge the pipeline on it

                exec_fn = self._tool_instances[tool_name].execute
                # #360: an arg the callee cannot accept would raise TypeError
                # and lose the whole call. Drop it loudly instead.
                tool_args, _dropped_args = drop_unaccepted_kwargs(exec_fn, tool_args)
                if _dropped_args:
                    self._logger.warning(
                        "[%s] %s: dropped unaccepted argument(s) %s — the tool's "
                        "signature does not declare them; check the tool schema "
                        "the model was shown.",
                        self.agent_id, tool_name, _dropped_args)
                # #634: the mirror case. A REQUIRED arg the call omits raises TypeError from
                # Python before the tool's own validator runs, so the agent is told the
                # parameter NAMES and nothing about their shape — 124 times across the corpus,
                # 106 of them one tool retrying. Answer with the schema it was already shown.
                _missing_634 = missing_required_args_634(exec_fn, tool_args)
                if _missing_634:
                    _err_634 = ToolResult(success=False, error_message=missing_args_message_634(
                        tool_name, _missing_634, self._tool_instances[tool_name]))
                    self.log_tool_call(tool_name, tool_args, _err_634)
                    return _err_634
                if asyncio.iscoroutinefunction(exec_fn):
                    result = await exec_fn(**tool_args)
                else:
                    result = await asyncio.to_thread(exec_fn, **tool_args)

                if getattr(result, "success", False) and self._execution_mode == "team":
                    if tool_name in {"terminate_agent_team", "parallel_execute", "finish"}:
                        self._exit_team_mode(reason=f"tool={tool_name}")

                if tool_name == "finish":
                    # #637: count consecutive no-op steps so the twelfth does not look like
                    # the first. #967: the verdict is structural (did any non-finish action
                    # tool run this step?), counted just below — the old prose match was fed
                    # a `reason` argument that `finish` does not have.
                    try:
                        from .hub_pulse import note_finish_637
                        note_finish_637(self, str(tool_args.get("message") or ""))
                    except Exception:
                        pass
                else:
                    # #967: the step did something other than announce it was done.
                    try:
                        self._step_action_tools_637 = int(
                            getattr(self, "_step_action_tools_637", 0)) + 1
                    except Exception:
                        pass
                self.log_tool_call(tool_name, tool_args, result)
                _record_tool_io(self, tool_name, result)
                from .skill_consult import record_skill_consult
                record_skill_consult(self, tool_name, tool_args, result)
                return result
            except Exception as e:
                return ToolResult(success=False, error_message=str(e))
        hits = suggest_tools(tool_name, self._tool_instances.keys())
        msg = f"Unknown tool: {tool_name}."
        msg += f" Did you mean: {', '.join(hits)}?" if hits else " Call only tools listed in your tool schema."
        return ToolResult(success=False, error_message=msg)

    def _log_tool_details(self, tool_name: str, tool_args: Dict) -> None:
        """Enhanced logging for tool calls with detailed content for important tools."""

        def truncate(s: str, max_len: int = 200) -> str:
            s = str(s)
            return s[:max_len] + "..." if len(s) > max_len else s

        if tool_name == "plan":
            action = tool_args.get("action", "create")
            items = tool_args.get("items", [])
            item_text = tool_args.get("item_text", "")
            item_index = tool_args.get("item_index")
            if action == "create":
                self._logger.info(f"[{self.agent_id}] 📋 PLAN CREATE ({len(items)} items):")
                for i, item in enumerate(items[:10]):
                    self._logger.info(f"    [{i}] {truncate(item, 100)}")
                if len(items) > 10:
                    self._logger.info(f"    ... and {len(items) - 10} more items")
            elif action == "add":
                self._logger.info(f"[{self.agent_id}] 📋 PLAN ADD: {items}")
            elif action == "complete":
                self._logger.info(f"[{self.agent_id}] ✅ PLAN COMPLETE: item #{item_index}")
            elif action == "update":
                self._logger.info(f"[{self.agent_id}] 📝 PLAN UPDATE #{item_index}: {truncate(item_text, 100)}")
            elif action == "remove":
                self._logger.info(f"[{self.agent_id}] ❌ PLAN REMOVE: item #{item_index}")
            elif action == "clear":
                self._logger.info(f"[{self.agent_id}] 🗑️ PLAN CLEAR")
            else:
                self._logger.info(f"[{self.agent_id}] 📋 PLAN {action}: {tool_args}")
        elif tool_name == "send_message":
            self._logger.info(
                f"[{self.agent_id}] 📤 SEND_MESSAGE to={tool_args.get('to_agent', '?')} "
                f"type={tool_args.get('msg_type', 'update')} priority={tool_args.get('priority', 'normal')}"
            )
            self._logger.info(f"    Content: {truncate(tool_args.get('content', ''), 200)}")
        elif tool_name == "broadcast":
            self._logger.info(f"[{self.agent_id}] 📢 BROADCAST: {truncate(tool_args.get('message', ''), 200)}")
        elif tool_name == "ask_agent":
            self._logger.info(
                f"[{self.agent_id}] ❓ ASK_AGENT to={tool_args.get('agent_id', '?')}: "
                f"{truncate(tool_args.get('question', ''), 200)}"
            )
        elif tool_name == "check_inbox":
            filters = {k: v for k, v in tool_args.items() if v}
            self._logger.info(f"[{self.agent_id}] 📥 CHECK_INBOX filters={filters if filters else 'none'}")
        elif tool_name == "report_issue":
            self._logger.info(
                f"[{self.agent_id}] 🐛 REPORT_ISSUE to={tool_args.get('assign_to', '?')} "
                f"severity={tool_args.get('severity', 'error')}"
            )
            self._logger.info(f"    Issue: {truncate(tool_args.get('issue', ''), 200)}")
        elif tool_name == "finish":
            self._logger.info(f"[{self.agent_id}] 🏁 FINISH notify={tool_args.get('notify', [])}")
            self._logger.info(f"    Message: {truncate(tool_args.get('message', ''), 200)}")
        elif tool_name == "deliver_project":
            self._logger.info(f"[{self.agent_id}] 🚀 DELIVER_PROJECT: {truncate(tool_args.get('delivery_summary', ''), 200)}")
        elif tool_name == "write":
            path = tool_args.get("file_path", "?")
            self._logger.info(f"[{self.agent_id}] 📝 WRITE: {path} ({len(tool_args.get('content', ''))} chars)")
        elif tool_name == "read":
            self._logger.info(f"[{self.agent_id}] 👁️ READ: {tool_args.get('file_path', '?')}")
        elif tool_name == "edit":
            self._logger.info(f"[{self.agent_id}] ✏️ EDIT: {tool_args.get('file_path', '?')}")
        elif tool_name == "apply_patch":
            self._logger.info(f"[{self.agent_id}] 🩹 APPLY_PATCH")
        elif tool_name == "delete_file":
            self._logger.info(f"[{self.agent_id}] 🗑️ DELETE_FILE: {tool_args.get('file_path', '?')}")
        elif tool_name == "glob":
            self._logger.info(
                f"[{self.agent_id}] 🧭 GLOB: pattern={tool_args.get('pattern', '?')} "
                f"scope={tool_args.get('path', '.')}"
            )
        elif tool_name == "grep":
            self._logger.info(
                f"[{self.agent_id}] 🔎 GREP: pattern={truncate(tool_args.get('pattern', ''), 120)} "
                f"scope={tool_args.get('path', '.')} include={tool_args.get('include', '*')}"
            )
        elif tool_name == "lint":
            self._logger.info(f"[{self.agent_id}] 🔍 LINT: {tool_args.get('path', '?')}")
        elif tool_name in ["docker_build", "docker_up", "docker_down", "docker_logs", "docker_validate"]:
            self._logger.info(
                f"[{self.agent_id}] 🐳 {tool_name.upper()}: service={tool_args.get('service', 'all')} args={tool_args}"
            )
        elif tool_name == "wait":
            self._logger.info(
                f"[{self.agent_id}] ⏳ WAIT: {tool_args.get('seconds', 0)}s - {tool_args.get('reason', '')}"
            )
        elif tool_name == "get_time":
            self._logger.info(f"[{self.agent_id}] 🕐 GET_TIME")
        elif tool_name in {"analyze_image", "view_image"}:
            self._logger.info(
                f"[{self.agent_id}] 🖼️ {tool_name.upper()}: "
                f"{tool_args.get('image_path', tool_args.get('path', '?'))}"
            )
        else:
            # #611 — LOG *WHAT* WAS OPERATED ON, NOT JUST THE ARGUMENT NAMES. This fallback
            # printed `args=['method','url']` — the KEYS only — so the log records that a
            # call happened but never its target. Of the ten highest-volume tools in the arc,
            # NINE land here: workhub_task, workhub_get_task, workhub_add_meeting_decision,
            # list_generated_files, test_api, workhub_list_documents, workhub_get_document,
            # workhub_cancel_task (only check_inbox and read have bespoke branches).
            #
            # It is not a cosmetic gap. It blocked two analyses in this very session: whether
            # an agent re-fetches the SAME task (workhub_get_task, 5.80M tokens over 427
            # calls) and whether it re-hits the SAME tokenless endpoint after being told not
            # to (test_api — the "requires AUTH, a tokenless request is SUPPOSED to be
            # rejected" hint fires 535 times arc-wide, and nothing records which endpoint).
            # It is also, mechanically, part of why the framework's own agents cannot
            # root-cause their runs: the artifact does not say what was touched.
            #
            # Costs nothing the model sees — this is a log line, not context. Values are
            # truncated and credential-shaped keys are redacted, because the log is written
            # to disk and read by humans and agents.
            _t = []
            for _k in _TARGET_ARG_KEYS_611:
                if _k in tool_args and tool_args[_k] not in (None, "", [], {}):
                    _v = tool_args[_k]
                    if _SECRETISH_ARG_RE_611.search(_k):
                        _v = "<redacted>"
                    elif not isinstance(_v, (str, int, float, bool)):
                        # #725: SUMMARISE a structured argument instead of dropping it.
                        # This `continue` is why "what did the lane send?" is unanswerable from a
                        # finished run for exactly the arguments worth asking about. Both times I
                        # needed it this session the value was a dict — `schema` on
                        # registryhub_register_endpoint (item 32's contract mismatch) and
                        # `sample_excerpt` on register_seed_data (item 33) — and both were
                        # skipped silently, leaving only the tool NAME in prose. I then measured
                        # those names and read mention counts as call counts, twice.
                        #
                        # KEYS ONLY, never values — which is what #611 was protecting. Its
                        # `test_a_non_scalar_value_is_skipped_not_dumped` exists to stop a deep
                        # structure being dumped into the line, and a truncated repr would have
                        # broken that for a real reason. The shape is all I ever needed: for
                        # `schema={"request": {"kind": ..., "genre": ...}}` this renders
                        # `schema={request:{kind,genre,language,limit,offset}}` — enough to answer
                        # "were the query params sent at all" without a single value leaving the
                        # argument. One level of nesting, capped, so #611's line-length
                        # discipline holds.
                        try:
                            def _shape725(v, depth=0):
                                if isinstance(v, dict):
                                    if depth >= 1:
                                        return "{…}" if v else "{}"
                                    return "{" + ",".join(
                                        f"{k}:{_shape725(x, depth + 1)}" if isinstance(
                                            x, (dict, list, tuple)) else str(k)
                                        for k, x in list(v.items())[:8]) + "}"
                                if isinstance(v, (list, tuple)):
                                    return f"[{len(v)}]"
                                return ""
                            _sh = _shape725(_v)
                            if _sh:
                                _t.append(f"{_k}={truncate(_sh, 120)}")
                        except Exception:
                            pass
                        continue
                    _t.append(f"{_k}={truncate(str(_v), 120)}")
                if len(_t) >= 3:
                    break
            _tail = " ".join(_t) if _t else f"args={list(tool_args.keys())}"
            self._logger.info(f"[{self.agent_id}] 🔧 {tool_name}: {_tail}")

    def _log_tool_result(self, tool_name: str, result: ToolResult, duration_ms: int) -> None:
        """Log tool execution result with appropriate detail level."""

        def truncate(s: str, max_len: int = 150) -> str:
            s = str(s)
            return s[:max_len] + "..." if len(s) > max_len else s

        status = "✅" if result.success else "❌"
        verbose_result_tools = {
            "check_inbox", "get_time", "db_schema", "list_reference_images"
        }
        quiet_tools = {"write", "read", "edit", "apply_patch", "lint", "wait"}

        if not result.success:
            self._logger.warning(
                f"[{self.agent_id}] {status} {tool_name} FAILED ({duration_ms}ms): "
                f"{truncate(result.error_message or '', 300)}"
            )
        elif tool_name in verbose_result_tools:
            result_preview = truncate(str(result.data), 300) if result.data else "empty"
            self._logger.info(f"[{self.agent_id}] {status} {tool_name} ({duration_ms}ms): {result_preview}")
        elif tool_name == "check_inbox":
            data = result.data
            if isinstance(data, dict):
                msg_count = data.get("count", 0)
                messages = data.get("messages", [])
                if msg_count > 0:
                    self._logger.info(f"[{self.agent_id}] {status} check_inbox ({duration_ms}ms): {msg_count} messages")
                    for msg in messages[:5]:
                        self._logger.info(
                            f"    📩 from={msg.get('from', '?')} type={msg.get('type', '?')}: "
                            f"{truncate(msg.get('content', ''), 100)}"
                        )
                else:
                    self._logger.info(f"[{self.agent_id}] {status} check_inbox ({duration_ms}ms): inbox empty")
            else:
                self._logger.info(f"[{self.agent_id}] {status} check_inbox ({duration_ms}ms): {truncate(str(data), 100)}")
        elif tool_name == "plan":
            if isinstance(result.data, dict) and "plan" in result.data:
                plan_items = result.data.get("plan", [])
                completed = sum(1 for p in plan_items if p.get("completed", False))
                self._logger.info(f"[{self.agent_id}] {status} plan ({duration_ms}ms): {completed}/{len(plan_items)} items complete")
        elif tool_name in quiet_tools:
            self._logger.debug(f"[{self.agent_id}] {status} {tool_name} ({duration_ms}ms)")
        else:
            self._logger.info(f"[{self.agent_id}] {status} {tool_name} ({duration_ms}ms)")

    async def _apply_finish_policies(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Two-pass finish-policy dispatch (PR 2.5-fix-2, 2026-05-29).

        Pass 1 — BOOKKEEPING: every policy whose ``always_runs()``
        returns True is invoked unconditionally; its return value is
        expected to be ``None``. If a bookkeeping policy ever returns
        a non-None outcome, this dispatcher logs an ERROR and
        discards the outcome — preserving the gate-bookkeeping
        separation invariant without crashing a running finish.
        This guarantees the ``LaneIdleCircuitBreakerPolicy`` idle
        counter advances on every finish call regardless of YAML order
        or peer gate outcomes — the structural fix for the recurring
        starvation bug that the previous single-pass first-match-wins
        loop kept silently re-opening every time a new gate landed
        before the breaker.

        Pass 2 — GATES: standard first-match-wins loop, skipping
        already-invoked bookkeeping policies so they aren't double-
        called. The first policy returning a non-None outcome wins.

        Exception handling: a bookkeeping policy that raises is
        logged at WARNING and skipped — a buggy observer must never
        block a finish. A gate that raises is allowed to propagate.
        """
        policies = list(getattr(self, "_workflow_policies", []) or [])
        kwargs = dict(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call=tool_call,
            tool_call_id=tool_call_id,
            messages=messages,
            files_created=files_created,
            files_modified=files_modified,
        )
        bookkept_ids: set = set()
        for policy in policies:
            if not policy.always_runs():
                continue
            bookkept_ids.add(id(policy))
            try:
                outcome = await policy.handle_finish(self, **kwargs)
            except Exception as exc:
                try:
                    self._logger.warning(
                        f"[{getattr(self, 'agent_id', '?')}] bookkeeping "
                        f"policy {type(policy).__name__} raised: {exc} — "
                        "continuing finish dispatch"
                    )
                except Exception:
                    pass
                continue
            if outcome is not None:
                try:
                    self._logger.error(
                        f"[{getattr(self, 'agent_id', '?')}] policy "
                        f"{type(policy).__name__} declares always_runs() "
                        f"but returned a gate outcome {outcome!r}; the "
                        "bookkeeping invariant is broken — outcome will "
                        "be DISCARDED. Either return None or set "
                        "always_runs() -> False."
                    )
                except Exception:
                    pass
        for policy in policies:
            if id(policy) in bookkept_ids:
                continue
            outcome = await policy.handle_finish(self, **kwargs)
            if outcome is not None:
                return outcome
        return None
