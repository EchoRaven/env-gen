r"""#1027: the stage one line below hub_pulse never got hub_pulse's dedup.

`hub_pulse` appends its block ONLY when it changed, and says why in full:

    Inject ONLY when the pulse CHANGED since the last step. The pulse is re-collected every
    step but is identical while a lane is heads-down building; re-appending the same block
    each step bloated context (prior pulse is still in the conversation) and read as
    'forced task enumeration every step' (v10).

`runtime_team_status`, the very next stage, has the same shape — rebuilt every step from a
snapshot, body dominated by stable counts — and had **no dedup and no `_last_...` tracker
anywhere in the tree**. The defect its sibling documents and fixes was sitting unfixed one
stage later.

★ CURRENTLY LATENT, and that is worth stating rather than overselling the find:
`_build_runtime_team_status_prompt` returns None unless the agent owns a spawned runtime or a
managed team. Nothing spawns in the netflix workload — "Runtime / Team Status" appears **0
times in r172 and r173**, and `launch_agent_team` is invoked in **0 of 298 run logs**. So this
restores the symmetry at no behavioural cost while the stage stays silent, and prevents a
documented context-bloat mode the moment spawning is used.

--- and the diagnostics that pointed here -----------------------------------------------------

The IDE reported 8 errors on this file. SEVEN were #681's mixin false-positive class: names
supplied by the host class (`multi_agent/agents/base.py` + `agents/runtime/sync.py`) that a
checker reading this file alone calls missing. #681 declared a host-class contract under
TYPE_CHECKING for exactly that reason, and **the block had drifted** — seven names added since
were never declared.

#681's own argument is that this noise BURIES real findings (it cites #658 and a dangling
WorkHub annotation found underneath). It did so again: the 8th diagnostic was real —
`resolve_ctx_working_chars(_model)` with `_model: Any | None` against a `str` parameter, while
the function's first line is `if not model: return default`. The annotation was narrower than
the implementation. Fixed at the definition, not the call site, because every caller reaches
it with an optional.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import step_runner as sr
from utils.model_limits import resolve_context_window, resolve_ctx_working_chars


def _src():
    return inspect.getsource(sr)


def _stage_block(name):
    s = _src()
    i = s.index(f'if _stage_enabled("{name}"):')
    return s[i:s.index("_mark_stage(", i)]


# --- the dedup, and its symmetry with hub_pulse -------------------------------------------------

def test_runtime_team_status_dedups_before_appending():
    b = _stage_block("runtime_team_status")
    assert "_last_runtime_team_status_prompt" in b
    assert "messages.append" in b


def test_it_records_what_it_appended():
    """A dedup that never stores the value it compared against is a no-op that looks correct."""
    b = _stage_block("runtime_team_status")
    i = b.index("messages.append")
    assert "self._last_runtime_team_status_prompt = runtime_team_status_prompt" in b[i:]


def test_the_tracker_is_reset_per_wake_like_hub_pulse():
    """hub_pulse resets each wake so the FIRST block of a fresh wake always renders
    (orientation) and dedups only within the wake. The sibling must match."""
    s = _src()
    i = s.index("self._last_hub_pulse_prompt = None")
    j = s.index("self._last_runtime_team_status_prompt = None")
    assert abs(i - j) < 400, "the two per-wake resets must live together or they will drift again"


def test_the_two_sibling_stages_now_agree():
    """★ The actual defect was an asymmetry. Pin it as a PAIR — a per-stage test would have
    passed on the broken one for as long as it existed."""
    for stage, var in (("hub_pulse", "_last_hub_pulse_prompt"),
                       ("runtime_team_status", "_last_runtime_team_status_prompt")):
        b = _stage_block(stage)
        assert var in b, f"{stage} lost its dedup"
        assert "!=" in b, f"{stage} appends without comparing"


def test_the_prompt_still_reaches_the_downstream_stage():
    """Dedup governs the APPEND only. `retrieve_context` receives the prompt either way, which
    is how hub_pulse behaves — suppressing it there would be a behaviour change, not a fix."""
    s = _src()
    assert "runtime_team_status_prompt=runtime_team_status_prompt" in s
    assert "hub_pulse_prompt=hub_pulse_prompt" in s


def test_the_latency_of_the_find_is_recorded():
    d = " ".join((__doc__ or "").split())
    assert "0 times in r172 and r173" in d, "the blast radius must travel with the fix"
    assert "0 of 298 run logs" in d


# --- #681's contract block, which had drifted ----------------------------------------------------

_HOST_NAMES = ("KNOWLEDGE_FETCH_TOOL_NAMES", "KNOWLEDGE_STORE_TOOL_NAMES",
               "_build_interrupt_prompt", "_collect_eventhub_catchup_summary",
               "_build_eventhub_catchup_prompt", "_build_runtime_team_status_snapshot",
               "_build_runtime_team_status_prompt")


def test_every_host_name_used_here_is_declared():
    s = _src()
    i = s.index("if TYPE_CHECKING:")
    block = s[i:s.index("def _stamp_step_activity", i)]
    for n in _HOST_NAMES:
        assert n in block, f"{n} is used but not declared — #681's noise class returns"


def test_the_declared_names_really_exist_on_the_host():
    """★ A declaration is a promise, not a silencer. If one of these is NOT actually provided,
    declaring it converts a true 'missing attribute' into silence — which is worse than the
    noise it removes."""
    from env_generator.llm_generator.multi_agent.agents import base
    from env_generator.llm_generator.multi_agent.agents.runtime import sync
    for n in _HOST_NAMES:
        assert hasattr(base.EnvGenAgent, n) or hasattr(sync.AgentSync, n), (
            f"{n} is declared in the contract block but no host class provides it")


# --- the real diagnostic the noise was hiding -----------------------------------------------------

@pytest.mark.parametrize("fn", [resolve_context_window, resolve_ctx_working_chars])
def test_the_model_parameter_admits_None(fn):
    """`step_runner` calls these with
    `getattr(getattr(self, "config", None), "model_name", None)`. The body's first line is
    `if not model: return default`, so None was always supported — only the annotation said
    otherwise, and that was the one TRUE error buried under seven false ones."""
    ann = inspect.signature(fn).parameters["model"].annotation
    assert "None" in str(ann), f"{fn.__name__} still annotates model as non-optional: {ann}"


@pytest.mark.parametrize("value", [None, "", "unknown-model"])
def test_it_returns_the_safe_default_for_an_unknown_model(value):
    assert resolve_ctx_working_chars(value) > 0


def test_a_known_model_still_resolves():
    assert resolve_ctx_working_chars("gpt-5-6-sol-genai-responses") == 666400


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
