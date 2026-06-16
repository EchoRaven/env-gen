"""
Configurable Agent - Generic agent loaded from config

All agents are just: prompt template + tools + settings
This class handles all the logic - specific agents just need config.
"""

import asyncio
import copy
import logging
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from pathlib import Path
import time

import yaml

from .base import EnvGenAgent, ProcessingState
from ..observer_handlers import create_observer_handler
from ..skill_loader import (
    build_available_skills_prompt,
    resolve_agent_skill_allowlist,
)
from ..tool_surface import build_profile_tool_audit, validate_profile_tool_configuration
from ..runtime.reasoning_effort import normalize_effort
from ..workflow_policies import create_workflow_policies
from utils.config import AgentConfig, ExecutionConfig
from utils.llm import LLM

if TYPE_CHECKING:
    from ..workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

# Config file location
CONFIG_PATH = Path(__file__).parent / "agents_config.yaml"

# Cache for loaded config
_config_cache: Optional[Dict] = None


def load_config() -> Dict[str, Any]:
    """Load and cache agents configuration."""
    global _config_cache
    if _config_cache is None:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"Agent config not found: {CONFIG_PATH}")
        with open(CONFIG_PATH, 'r') as f:
            _config_cache = yaml.safe_load(f)
        if not _config_cache:
            raise ValueError("Agent config is empty")
        if not isinstance(_config_cache.get("profiles"), dict) or not _config_cache["profiles"]:
            raise ValueError("Agent config must define non-empty 'profiles'")
        if not isinstance(_config_cache.get("resident_lanes"), dict) or not _config_cache["resident_lanes"]:
            raise ValueError("Agent config must define non-empty 'resident_lanes'")
        if not isinstance(_config_cache.get("resident_workflow"), dict):
            raise ValueError("Agent config must define 'resident_workflow'")
        profiles = _get_profiles(_config_cache)
        validation_errors: List[str] = []
        for profile_id, profile_cfg in profiles.items():
            validation_errors.extend(
                validate_profile_tool_configuration(
                    profile_id,
                    tool_categories=profile_cfg.get("tool_categories", []),
                    tool_bundle_ids=profile_cfg.get("tool_bundles", []),
                )
            )
        if validation_errors:
            raise ValueError("Invalid tool surface config:\n- " + "\n- ".join(validation_errors))
        _config_cache["tool_surface_audit"] = build_profile_tool_audit(profiles)
    return _config_cache


def _get_profiles(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return configured profile definitions."""
    return config["profiles"]


def resolve_agent_profile_id(agent_id: str) -> str:
    """Resolve a runtime lane/profile id to its backing profile id."""
    config = load_config()
    profiles = _get_profiles(config)
    if agent_id in profiles:
        return agent_id
    raise ValueError(f"Agent/profile '{agent_id}' not found in config")


def get_agent_config(agent_id: str) -> Dict[str, Any]:
    """Get config for a specific agent or profile id."""
    config = load_config()
    profiles = _get_profiles(config)
    resolved_profile_id = resolve_agent_profile_id(agent_id)
    agent_cfg = profiles.get(resolved_profile_id)
    if not agent_cfg:
        raise ValueError(f"Agent '{agent_id}' not found in config")
    return copy.deepcopy(agent_cfg)


def list_available_agents() -> List[str]:
    """List all available profile IDs."""
    config = load_config()
    return list(_get_profiles(config).keys())


def _merge_skill_names(base: Optional[List[str]], inherited: Optional[List[str]]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for source in (base or []), (inherited or []):
        for skill_name in source:
            cleaned = str(skill_name or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            merged.append(cleaned)
    return merged


def get_resident_lane_specs() -> List[Dict[str, Any]]:
    """Return resident orchestrator-owned lane specs from config."""
    config = load_config()
    resident_lanes = config["resident_lanes"]
    specs: List[Dict[str, Any]] = []
    for lane_id, lane_cfg in resident_lanes.items():
        lane_cfg = lane_cfg or {}
        specs.append(
            {
                "agent_id": lane_id,
                "profile_id": str(lane_cfg.get("profile") or lane_id),
                "resident": bool(lane_cfg.get("resident", True)),
                "description": lane_cfg.get("description", ""),
            }
        )
    return specs


class ConfigurableAgent(EnvGenAgent):
    """
    Generic agent that loads behavior from config.
    
    All agent-specific behavior comes from:
    1. Jinja2 templates (system prompt, task prompt)
    2. Tool categories
    3. Config flags
    4. Optional skill allowlists
    
    No need for subclasses - just config.
    """
    
    def __init__(
        self,
        agent_id: str,
        llm: LLM,
        workspace_manager: "WorkspaceManager",
        config_override: Dict[str, Any] = None,
    ):
        # Support _config_key override for spawned runtime agents.
        # e.g., agent_id="api_debugger_abc123" but config resolves to "analysis_worker"
        config_key = agent_id
        role = None
        custom_name = None
        permission_parent_id = None
        write_scopes = None
        inherited_tool_categories = None
        tool_profile_agent_type = None
        include_vision_override = None
        requested_agent_type = None
        skills_override = None
        inherit_parent_skills = False
        inherited_skills = None
        if config_override:
            config_key = config_override.pop("_config_key", agent_id)
            role = config_override.pop("_role", None)
            custom_name = config_override.pop("_custom_name", None)
            permission_parent_id = config_override.pop("_permission_parent_id", None)
            write_scopes = config_override.pop("_write_scopes", None)
            inherited_tool_categories = config_override.pop("_inherited_tool_categories", None)
            tool_profile_agent_type = config_override.pop("_tool_profile_agent_type", None)
            include_vision_override = config_override.pop("_include_vision", None)
            requested_agent_type = config_override.pop("_requested_agent_type", None)
            skills_override = config_override.pop("_skills", None)
            inherit_parent_skills = bool(config_override.pop("_inherit_parent_skills", False))
            inherited_skills = config_override.pop("_inherited_skills", None)
        
        # Load config using config_key (may be different from agent_id)
        agent_cfg = get_agent_config(config_key)
        root_cfg = load_config()
        
        # Apply remaining overrides
        if config_override:
            agent_cfg = {**agent_cfg, **config_override}
        
        # Store for prompt customization
        self._config_key = config_key
        self._spawn_role = role
        self._custom_name = custom_name
        self._permission_parent_id = permission_parent_id
        self._write_scopes = list(write_scopes or [])
        self._tool_profile_agent_type = tool_profile_agent_type or config_key
        self._requested_agent_type = requested_agent_type or agent_id
        
        # Set class attributes before parent init
        self.agent_id = agent_id  # Keep the unique ID
        # Use custom name if provided
        self.agent_name = custom_name or agent_cfg.get("name", f"{agent_id.title()} Agent")
        if role and not custom_name:
            self.agent_name = f"{self.agent_name} ({role})"
        self.allowed_tool_categories = inherited_tool_categories or agent_cfg.get("tool_categories", ["file", "reasoning"])
        # Per-profile gpt-5 reasoning_effort default (unset -> "medium"); resolved per-call
        # against the live reasoning_effort.json (live_monitor-adjustable) in runtime/reasoning_effort.
        self.reasoning_effort = normalize_effort(agent_cfg.get("reasoning_effort"))
        
        # Store config
        self._agent_cfg = agent_cfg
        self._prompt_cfg = agent_cfg.get("prompts", {})
        self._flags = agent_cfg.get("flags", {})
        self._tool_bundle_ids = list(agent_cfg.get("tool_bundles") or [])
        self._allow_tools = list(agent_cfg.get("allow_tools") or [])
        self._deny_tools = list(agent_cfg.get("deny_tools") or [])
        # Per-stage tool allowlist (PR3 generic lever). Maps stage_name →
        # iterable of tool names that the LLM may see during that stage.
        # Stages not listed fall back to the default ranker (unchanged).
        # This replaces "DO NOT call X during stage Y" prose rules with
        # engine-side filtering — the LLM only sees the tools the stage
        # allows, so it can't call the wrong one.
        raw_allowlist = agent_cfg.get("stage_tool_allowlist") or {}
        self._stage_tool_allowlist: Dict[str, frozenset] = {
            str(stage): frozenset(str(t) for t in (tools or []))
            for stage, tools in raw_allowlist.items()
        }
        # PR3.2 — per-(stage, tool) precondition guard. Maps
        # stage_name → {tool_name → precondition_id} where precondition_id
        # resolves via multi_agent/agents/runtime/preconditions.
        # PRECONDITION_REGISTRY. Unknown ids fail-closed at construction
        # (no silent fallthrough at dispatch). Replaces "do not call X
        # until Y" prose with engine-enforced sequence checks; the LLM
        # sees the precondition's error message as a normal tool failure
        # and corrects in-context.
        raw_preconds = agent_cfg.get("stage_tool_preconditions") or {}
        self._stage_tool_preconditions: Dict[str, Dict[str, str]] = {}
        if raw_preconds:
            from .runtime.preconditions import PRECONDITION_REGISTRY
            unknown_ids: set = set()
            for stage, tools_map in raw_preconds.items():
                if not tools_map:
                    continue
                stage_dict: Dict[str, str] = {}
                for tool, pre_id in tools_map.items():
                    pre_id_str = str(pre_id)
                    if pre_id_str not in PRECONDITION_REGISTRY:
                        unknown_ids.add(pre_id_str)
                    stage_dict[str(tool)] = pre_id_str
                if stage_dict:
                    self._stage_tool_preconditions[str(stage)] = stage_dict
            if unknown_ids:
                raise ValueError(
                    f"agent {agent_id}: stage_tool_preconditions references unknown id(s) "
                    f"{sorted(unknown_ids)}. Register them in "
                    f"multi_agent/agents/runtime/preconditions.PRECONDITION_REGISTRY "
                    f"or fix the yaml typo."
                )
        self._workflow_policies = create_workflow_policies(agent_cfg)
        self._execution_pipeline_cfg = {
            **(root_cfg.get("execution_pipeline_defaults", {}) or {}),
            **(agent_cfg.get("execution_pipeline", {}) or {}),
        }
        workspace_root = getattr(workspace_manager, "base_dir", Path("."))
        if skills_override is not None:
            requested_skill_names = (
                _merge_skill_names(skills_override, inherited_skills)
                if inherit_parent_skills
                else list(skills_override)
            )
        else:
            requested_skill_names = (
                _merge_skill_names(agent_cfg.get("skills"), inherited_skills)
                if inherit_parent_skills
                else agent_cfg.get("skills")
            )
        self._skills = resolve_agent_skill_allowlist(
            workspace_root=workspace_root,
            root_defaults=root_cfg.get("skill_defaults"),
            profile_skills=requested_skill_names,
        )
        
        # Validate prompt config
        if not self._prompt_cfg.get("template"):
            raise ValueError(f"Agent '{agent_id}' missing 'prompts.template' in config")
        if not self._prompt_cfg.get("system_macro"):
            raise ValueError(f"Agent '{agent_id}' missing 'prompts.system_macro' in config")
        
        # Build AgentConfig
        exec_config = ExecutionConfig(
            task_timeout=agent_cfg.get("timeout", 1800),
            max_retries=2,
        )
        config = AgentConfig(
            agent_id=agent_id,
            agent_name=self.agent_name,
            execution=exec_config,
        )
        
        # Initialize parent
        include_vision = include_vision_override if include_vision_override is not None else agent_cfg.get("include_vision", False)
        super().__init__(
            config=config,
            llm=llm,
            workspace_manager=workspace_manager,
            include_vision=include_vision,
        )
        self._execution_pipeline_config = self._execution_pipeline_cfg
        self.set_step_reminders(self._execution_pipeline_cfg.get("step_reminders") or [])
        
        # Observer mode flag
        self._is_observer = self._flags.get("observer", False)
        self._auto_start = bool(self._flags.get("auto_start", True))
        self._listen_all = bool(self._flags.get("listen_all", False))
        self._listen_all_subscription_id: Optional[str] = None
        self._observer_last_tick = 0.0
        self._observer_handler = create_observer_handler(
            self._flags.get("observer_handler"),
            flags=self._flags,
        )
        self._observer_tick_interval_s = (
            getattr(self._observer_handler, "interval_seconds", None)
            or float(self._flags.get("observer_tick_interval_s", 5))
        )
        # Per-agent cap on the agentic loop for inbound task_ready events.
        # Default (2000) preserves prior behavior for worker lanes that need
        # many steps to implement. Wake-driven agents (knowledge) should set
        # this LOW (e.g. 5) so that an overly-eager LLM that ignores the
        # system prompt's "single trigger -> single action" wake_contract is
        # still hard-bounded.
        # Observed in Val #3 (2026-05-31): haiku-4-5 Knowledge Agent chained
        # 11 steps in a single task_ready wake despite v3 wake_contract
        # mandating single-action. The system prompt was correct; the
        # runtime ceiling was the missing belt-and-suspenders.
        self._max_steps_per_task_ready = int(self._flags.get("max_steps_per_task_ready", 2000))

        logger.info(f"Created ConfigurableAgent: {agent_id} (observer={self._is_observer})")
    
    def _get_context_vars(self) -> Dict[str, Any]:
        """Get context variables for template rendering."""
        # Agents perceive workspace root as ``.`` — never leak the host's
        # absolute base_dir into the system prompt (the tool surface
        # routes relative paths through the routing table).
        ctx = {
            "workspace_dir": ".",
        }

        # Add role for spawned workers / runtime agents.
        if hasattr(self, '_spawn_role') and self._spawn_role:
            ctx["role"] = self._spawn_role

        requested_agent_type = getattr(self, "_requested_agent_type", None)
        if requested_agent_type:
            ctx["requested_agent_type"] = requested_agent_type
            ctx["spawned_agent_type"] = requested_agent_type

        # Add vars from gen_context
        if self.gen_context:
            var_names = self._prompt_cfg.get("context_vars", [])
            for var in var_names:
                if hasattr(self.gen_context, var):
                    ctx[var] = getattr(self.gen_context, var)

        return ctx
    
    def _get_system_prompt(self) -> str:
        """Get system prompt from j2 template."""
        template = self._prompt_cfg["template"]
        macro = self._prompt_cfg["system_macro"]
        ctx = self._get_context_vars()
        
        prompt = self.render_macro(template, macro, **ctx)
        if not prompt:
            raise RuntimeError(f"Failed to render system prompt: {template}::{macro}")
        # Show the agent EVERY skill the workspace knows about (not just its
        # profile allowlist) so it can discover and ``get_skill`` siblings on
        # demand. The profile.skills set is annotated as the agent's primary
        # skills so the model knows what its role uses most. Bodies stay
        # behind ``get_skill`` — Claude-Code / OpenClaw model.
        try:
            from ..skill_loader import discover_workspace_skills
            workspace_root = self.workspace.base_dir if self.workspace else Path(".")
            all_skills = list(discover_workspace_skills(workspace_root).values())
            primary_names = [s.name for s in self._skills]
            skills_prompt = build_available_skills_prompt(all_skills, primary_names=primary_names)
        except Exception as exc:
            # Never fail prompt assembly because of skill discovery.
            logger.debug(f"skill catalog skipped for {self.agent_id}: {exc}")
            skills_prompt = build_available_skills_prompt(self._skills)
        if skills_prompt:
            prompt = f"{prompt}\n\n{skills_prompt}"
        return prompt
    
    def _build_task_prompt(self, task: Dict) -> str:
        """Build task prompt from j2 template."""
        description = task.get("description", "")
        
        # If specific task description, use generic handling
        if description and not task.get("raw_requirements"):
            return self._build_generic_task_prompt(description)
        
        # Check for specific task types used by the coordinating lane
        task_macros = self._prompt_cfg.get("task_macros", {})
        template = self._prompt_cfg["template"]
        ctx = self._get_context_vars()
        
        # Full workflow kickoff (resident orchestrator lane with raw_requirements)
        if task.get("raw_requirements") and "full" in task_macros:
            ctx["raw_requirements"] = task["raw_requirements"]
            prompt = self.render_macro(template, task_macros["full"], **ctx)
            if prompt:
                return prompt
        
        # Testing task
        if task.get("workflow") == "test" and "test" in task_macros:
            ctx["description"] = description
            prompt = self.render_macro(template, task_macros["test"], **ctx)
            if prompt:
                return prompt
        
        # Default task macro
        macro = self._prompt_cfg.get("task_macro")
        if macro:
            prompt = self.render_macro(template, macro, **ctx)
            if prompt:
                return prompt
        
        # Use generic task prompt for description-based tasks
        return self._build_generic_task_prompt(description or "Complete your assigned task.")
    
    def _build_generic_task_prompt(self, description: str) -> str:
        """Build generic task prompt for specific instructions."""
        return f"""## Task

{description}

## Instructions

1. Use read() to examine relevant existing files when you need context
2. If the task is to create a missing file, do not read it first just to confirm absence
3. Analyze what needs to be done
4. Make changes with write(), edit(), or apply_patch()
5. Use lint() to verify syntax
6. Call finish() when done

Start now."""
    
    async def run_loop(self):
        """Run agent loop - handles both normal and observer modes."""
        if self._is_observer:
            if not self._auto_start:
                logger.info(f"[{self.agent_id}] observer auto_start=false; running in idle observer mode")
            await self._run_observer_loop()
        else:
            await super().run_loop()
    
    async def _run_observer_loop(self):
        """Observer mode - continuous background monitoring."""
        if not await self.initialize():
            self._logger.error(f"[{self.agent_id}] Failed to initialize")
            self._ready_event.set()
            return

        if not await self.start():
            self._logger.error(f"[{self.agent_id}] Failed to start")
            self._ready_event.set()
            return

        self._ready_event.set()
        self._logger.info(f"[{self.agent_id}] Observer started")

        # May 29 audit fix (workflow w241o5bwn): the observer ran for
        # 18 hours emitting 4601 plan_updated events (~9/min) on the
        # knowledge agent after every implementation lane stalled.
        # Audit root_cause_2: max_steps_per_task_ready caps a single
        # wake but NOT the outer observer/listen_all driver above it.
        # Fix: idle-backoff — once N consecutive ticks complete with
        # NO inbound activity (nothing in inbox + no agent_status
        # change), back off the sleep so the runaway emits sub-second
        # rather than tens of times per minute.
        idle_streak = 0
        # Continuous monitoring loop
        while not self._shutdown_requested and self._running:
            try:
                inbound = await self._observer_tick()
                if inbound:
                    idle_streak = 0
                else:
                    idle_streak += 1
                # Exponential backoff capped at the configured ceiling
                # (default 60s) — break the 9-emits/min runaway pattern.
                base_sleep = 1.0
                if idle_streak < 5:
                    sleep_s = base_sleep
                else:
                    # 1s → 2s → 4s → 8s → 16s → 30s ceiling.
                    sleep_s = min(
                        2.0 ** min(idle_streak - 4, 6),
                        float(getattr(self, "_observer_idle_max_sleep_s", 30.0)),
                    )
                await asyncio.sleep(sleep_s)
            except Exception as e:
                self._logger.error(f"[{self.agent_id}] Observer error: {e}")
                await asyncio.sleep(5)

        await self.stop()
        await self.cleanup()
        self._logger.info(f"[{self.agent_id}] Observer stopped")

    async def _observer_tick(self) -> bool:
        """Observer-specific background work for configurable agents.

        Returns True if the tick observed inbound activity (inbox
        items, hub changes, or executed a run_one_step). False means
        the tick was a no-op — used by the outer loop to drive the
        idle-backoff that caps the May 29 runaway-loop pattern.
        """
        if not self._auto_start:
            return False

        # Optional global listening on MessageBus (consume config flag).
        self._ensure_listen_all_subscription()

        now = time.time()
        if now - self._observer_last_tick < self._observer_tick_interval_s:
            return False  # rate-limited, but not "inbound activity"
        self._observer_last_tick = now
        await self.run_one_step(
            system_prompt=self._compose_system_prompt(),
            initial_prompt=(
                "Run one observer step. First report inbox/subscription state, then inspect hub changes, "
                "plan the next observer action, retrieve any needed knowledge/skills/tools, perform bounded action, "
                "sync hub if needed, and finish with knowledge sync."
            ),
            observer_handler=self._observer_handler,
        )
        return True

    def _ensure_listen_all_subscription(self) -> None:
        """Subscribe observer to all bus messages when listen_all=true."""
        if not self._listen_all or self._listen_all_subscription_id:
            return
        bus = getattr(self, "_external_bus", None)
        if not bus:
            return

        async def _on_message(message):
            msg_type = message.metadata.get("msg_type", message.message_type.value)
            inbox_msg = {
                "id": message.header.message_id,
                "from": message.header.source_agent_id,
                "type": msg_type,
                "content": message.payload if isinstance(message.payload, str) else str(message.payload),
                "tags": message.metadata.get("tags", []),
                "metadata": dict(message.metadata or {}),
                "priority": message.header.priority.name.lower(),
                "persist": message.metadata.get("persist", False),
                "read": False,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            inbox = getattr(self, "_subscription_inbox", None)
            if inbox is None:
                self._subscription_inbox = []
                inbox = self._subscription_inbox
            inbox.append(inbox_msg)

        self._listen_all_subscription_id = bus.subscribe(
            subscriber_id=self.agent_id,
            message_types=None,  # listen all
            async_callback=_on_message,
            priority=1,
        )
        self._logger.info(f"[{self.agent_id}] listen_all subscription enabled")

def create_agent(
    agent_id: str,
    llm: LLM,
    workspace_manager: "WorkspaceManager",
    config_override: Dict[str, Any] = None,
) -> ConfigurableAgent:
    """
    Create an agent from config.
    
    Args:
        agent_id: Agent ID (e.g., "backend", "frontend", "knowledge")
        llm: LLM instance
        workspace_manager: Workspace manager
        config_override: Optional config overrides
        
    Returns:
        ConfigurableAgent instance
        
    Raises:
        ValueError: If agent not found in config
    """
    return ConfigurableAgent(
        agent_id=agent_id,
        llm=llm,
        workspace_manager=workspace_manager,
        config_override=config_override,
    )


