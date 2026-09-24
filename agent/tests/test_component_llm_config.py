"""FEATURE (user-requested 2026-07-09): per-stage/per-component MODEL configuration.

The whole pipeline ran on ONE global LLMConfig: every agent (core residents +
dynamic spawns) received the orchestrator's single LLM instance
(agent_spawn_service.create_agent(llm=orch.llm)), and the non-agent call sites
(visual judge, design-prep enrichment) used orch.llm too. This feature lets each
component run a different model:

  * agents_config.yaml, per profile:      profiles.<name>.llm: {model:, provider:}
  * agents_config.yaml, non-agent sites:  component_models: {visual_judge: {...}}
  * env override (highest precedence):    ENVGEN_MODEL_<COMPONENT> /
                                          ENVGEN_PROVIDER_<COMPONENT>
                                          (component uppercased, e.g.
                                          ENVGEN_MODEL_FRONTEND,
                                          ENVGEN_MODEL_VISUAL_JUDGE)

resolve_component_llm_config(component, base, cfg) returns the base object
UNCHANGED (identity) when no override applies — callers can cheaply detect "no
new client needed". get_component_llm(orch, component) caches one LLM instance
per resolved (provider, model), so profiles sharing an override share a client.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from utils.config import LLMConfig, LLMProvider  # noqa: E402
from multi_agent.runtime.llm_overrides import (  # noqa: E402
    resolve_component_llm_config, get_component_llm)


def _base():
    return LLMConfig(provider=LLMProvider.GOOGLE,
                     model_name="gemini-3.1-pro-preview-customtools",
                     api_key="k", max_tokens=8192)


def test_no_override_returns_same_object(monkeypatch):
    monkeypatch.delenv("ENVGEN_MODEL_FRONTEND", raising=False)
    base = _base()
    out = resolve_component_llm_config("frontend", base, {})
    assert out is base                                  # identity: no new client


def test_yaml_profile_llm_block(monkeypatch):
    monkeypatch.delenv("ENVGEN_MODEL_FRONTEND", raising=False)
    cfg = {"profiles": {"frontend": {"llm": {"model": "gemini-3.1-flash"}}}}
    out = resolve_component_llm_config("frontend", _base(), cfg)
    assert out.model_name == "gemini-3.1-flash"
    assert out.provider == LLMProvider.GOOGLE           # provider inherited
    assert out.api_key == "k"                           # key/base inherited


def test_component_models_section_for_nonagent_sites(monkeypatch):
    monkeypatch.delenv("ENVGEN_MODEL_VISUAL_JUDGE", raising=False)
    cfg = {"component_models": {"visual_judge": {"model": "gemini-3.1-pro-preview"}}}
    out = resolve_component_llm_config("visual_judge", _base(), cfg)
    assert out.model_name == "gemini-3.1-pro-preview"


def test_env_override_beats_yaml(monkeypatch):
    monkeypatch.setenv("ENVGEN_MODEL_FRONTEND", "env-model")
    cfg = {"profiles": {"frontend": {"llm": {"model": "yaml-model"}}}}
    out = resolve_component_llm_config("frontend", _base(), cfg)
    assert out.model_name == "env-model"


def test_provider_override_and_bad_provider_ignored(monkeypatch):
    monkeypatch.setenv("ENVGEN_MODEL_BACKEND", "gpt-5")
    monkeypatch.setenv("ENVGEN_PROVIDER_BACKEND", "openai")
    out = resolve_component_llm_config("backend", _base(), {})
    assert out.provider == LLMProvider.OPENAI and out.model_name == "gpt-5"
    monkeypatch.setenv("ENVGEN_PROVIDER_BACKEND", "not-a-provider")
    out2 = resolve_component_llm_config("backend", _base(), {})
    assert out2.provider == LLMProvider.GOOGLE          # bad provider → keep base
    assert out2.model_name == "gpt-5"                   # model still applies


def test_base_never_mutated(monkeypatch):
    monkeypatch.setenv("ENVGEN_MODEL_VERIFIER", "other")
    base = _base()
    resolve_component_llm_config("verifier", base, {})
    assert base.model_name == "gemini-3.1-pro-preview-customtools"


class _Orch:
    def __init__(self, cfg):
        import types
        self.llm = types.SimpleNamespace(config=_base())
        self._agents_yaml_cfg = cfg


def test_component_llm_cache(monkeypatch):
    monkeypatch.delenv("ENVGEN_MODEL_FRONTEND", raising=False)
    monkeypatch.delenv("ENVGEN_MODEL_BACKEND", raising=False)
    cfg = {"profiles": {"frontend": {"llm": {"model": "m-a"}},
                        "backend": {"llm": {"model": "m-a"}},
                        "verifier": {}}}
    o = _Orch(cfg)
    # patch the LLM constructor so no real client is built
    import multi_agent.runtime.llm_overrides as lo
    made = []
    class _FakeLLM:
        def __init__(self, config):
            self.config = config
            made.append(config.model_name)
    monkeypatch.setattr(lo, "LLM", _FakeLLM)
    fe = get_component_llm(o, "frontend")
    be = get_component_llm(o, "backend")
    ve = get_component_llm(o, "verifier")
    assert fe is be                                     # same override → shared client
    assert ve is o.llm                                  # no override → the global LLM
    assert made == ["m-a"]                              # exactly one client built
    assert get_component_llm(o, "frontend") is fe       # cached


def test_wired_into_spawn_service_judge_and_enrich():
    import inspect
    from multi_agent import agent_spawn_service as sp
    assert "get_component_llm" in inspect.getsource(sp)          # every agent spawn
    from multi_agent import orchestrator as om
    src = open(om.__file__, encoding="utf-8").read()
    # design_enrich + milestone_plan + reference_compile ride the orchestrator
    for comp in ("design_enrich", "milestone_plan", "reference_compile"):
        assert comp in src, comp
    assert "get_component_llm" in src
    from multi_agent.runtime import visual_fidelity as vf
    assert "visual_judge" in inspect.getsource(vf)               # the visual judge
    from multi_agent.runtime import heal_pipeline as hp
    assert "test_user_judge" in inspect.getsource(hp)            # test-user judge
