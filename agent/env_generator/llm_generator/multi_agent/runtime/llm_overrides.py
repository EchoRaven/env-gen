"""Per-stage / per-component MODEL configuration (user-requested, 2026-07-09).

The pipeline historically ran every component on ONE global LLMConfig: all agents
(core residents + dynamic spawns) received the orchestrator's single ``LLM``
instance via ``agent_spawn_service.create_agent(llm=orch.llm)``, and the
non-agent call sites (visual judge, design-prep enrichment) used ``orch.llm``
too. This module adds a small, deterministic override layer so each component
can run a different model:

Config surface (precedence high → low):
  1. env: ``ENVGEN_MODEL_<COMPONENT>`` / ``ENVGEN_PROVIDER_<COMPONENT>``
     (component name uppercased, non-alnum → ``_``; e.g. ``ENVGEN_MODEL_FRONTEND``,
     ``ENVGEN_MODEL_VISUAL_JUDGE``) — run-scoped control, no yaml edit needed.
  2. agents_config.yaml, per agent profile::

         profiles:
           frontend:
             llm:
               model: gemini-3.1-flash     # optional
               provider: google            # optional (defaults to the global)

  3. agents_config.yaml, non-agent components (framework call sites)::

         component_models:
           visual_judge:  {model: ...}
           design_enrich: {model: ...}

Known non-agent component names: ``visual_judge`` (the visual-fidelity judge),
``design_enrich`` (design-prep single-shot enrichment). Agent components use the
profile key (orchestrator / backend / frontend / verifier / design_analyst /
debugger / knowledge / ...).

Everything inherits from the global config (api_key/api_base/timeouts/...) —
only ``model_name`` and ``provider`` are overridable. When NOTHING applies, the
resolver returns the base object by IDENTITY so callers can skip building a new
client; ``get_component_llm`` caches one LLM instance per resolved
(provider, model) pair so components sharing an override share a client.
Best-effort throughout: a broken override must never break a run — fall back to
the global.
"""

import dataclasses
import os
import re
from typing import Any, Mapping, Optional

from utils.config import LLMConfig, LLMProvider
from utils.llm import LLM

__all__ = ["resolve_component_llm_config", "get_component_llm"]


def _env_key(component: str, prefix: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9]", "_", str(component)).upper()


def _yaml_override(component: str, cfg: Optional[Mapping]) -> Mapping:
    """The profile ``llm:`` block or the ``component_models:`` entry, else {}."""
    if not isinstance(cfg, Mapping):
        return {}
    try:
        prof = (cfg.get("profiles") or {}).get(component)
        if isinstance(prof, Mapping):
            blk = prof.get("llm")
            if isinstance(blk, Mapping):
                return blk
        blk = (cfg.get("component_models") or {}).get(component)
        if isinstance(blk, Mapping):
            return blk
    except Exception:
        pass
    return {}


def resolve_component_llm_config(
    component: str, base: LLMConfig, cfg: Optional[Mapping],
) -> LLMConfig:
    """Resolve the effective LLMConfig for ``component``. Returns ``base`` BY
    IDENTITY when no override applies. Never raises; never mutates ``base``."""
    try:
        blk = _yaml_override(component, cfg)
        model = (os.environ.get(_env_key(component, "ENVGEN_MODEL_"))
                 or blk.get("model") or blk.get("model_name") or "").strip()
        provider_s = (os.environ.get(_env_key(component, "ENVGEN_PROVIDER_"))
                      or blk.get("provider") or "").strip()
        if not model and not provider_s:
            return base
        provider = base.provider
        if provider_s:
            try:
                provider = LLMProvider(provider_s.lower())
            except Exception:
                provider = base.provider  # bad provider string → keep the global
        if (model or base.model_name) == base.model_name and provider == base.provider:
            return base
        return dataclasses.replace(
            base, model_name=model or base.model_name, provider=provider)
    except Exception:
        return base


def get_component_llm(orch: Any, component: str):
    """The LLM instance ``component`` should use: the orchestrator's global
    ``orch.llm`` when no override applies, else a cached per-(provider, model)
    ``LLM`` built from the global config with the override applied. The yaml
    config is read from ``orch._agents_yaml_cfg`` when the orchestrator has it
    (set at boot; absent → env-only overrides still work). Never raises."""
    try:
        base_llm = orch.llm
        base_cfg = getattr(base_llm, "config", None)
        if base_cfg is None:
            return base_llm
        cfg = getattr(orch, "_agents_yaml_cfg", None)
        if cfg is None:
            try:  # the same cached loader every agent profile uses
                from ..agents.configurable_agent import load_config
                cfg = load_config()
            except Exception:
                cfg = None
        resolved = resolve_component_llm_config(component, base_cfg, cfg)
        if resolved is base_cfg:
            return base_llm
        cache = getattr(orch, "_component_llms", None)
        if cache is None:
            cache = {}
            try:
                orch._component_llms = cache
            except Exception:
                pass
        key = (getattr(resolved.provider, "value", str(resolved.provider)),
               resolved.model_name)
        inst = cache.get(key)
        if inst is None:
            inst = LLM(resolved)
            cache[key] = inst
            try:
                orch._logger.warning(
                    "Component '%s' runs on its OWN model: %s/%s "
                    "(per-component model config).",
                    component, key[0], key[1])
            except Exception:
                pass
        return inst
    except Exception:
        return getattr(orch, "llm", None)
