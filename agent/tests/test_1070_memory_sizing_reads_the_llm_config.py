"""#1070 — the model-sized memory budget has never once been applied.

MemoryBank sizes the in-context digest and notebook as a fraction of the model's
working budget when it is told the model, and falls back to fixed FLOORS when it
is not:

    _DIGEST_CHARS   = 16000        _DIGEST_BUDGET_FRACTION   = 0.06
    _NOTEBOOK_CHARS = 6000         _NOTEBOOK_BUDGET_FRACTION = 0.025

base.py passes one:

    MemoryBank(..., model=getattr(self.config, "model_name", None))

but `self.config` is an `AgentConfig`, and AgentConfig has no `model_name`. Its
fields are agent_id / agent_name / agent_type / description / version / llm /
execution / ... — the model name lives one level down, on `config.llm`
(`LLMConfig.model_name`), which is also where base.py's own logging reads it from
(`self.llm.config.model_name`, line ~944).

So the getattr default fires every time, `model` is always None, and every agent
runs on the floors. On the model these runs use:

    digest    intended 147,000 chars   actual 16,000   9.2x smaller
    notebook  intended  61,250 chars   actual  6,000  10.2x smaller

The sibling call sites in agent_interaction_tools.py already pass a real model, so
this is the one path left — and it is the agent's OWN memory bank, the one that
matters.

The extraction is a pure function so the path can be tested without standing up an
agent.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.base import _memory_model_name_1070 as _model  # noqa: E402


def _cfg(model=None, with_llm=True):
    llm = types.SimpleNamespace(model_name=model) if with_llm else None
    return types.SimpleNamespace(llm=llm)


class ItReadsTheLlmSubConfig(unittest.TestCase):

    def test_the_real_agent_config_shape_resolves(self):
        self.assertEqual(_model(_cfg("claude-4-7-opus-vertex-genai"), None),
                         "claude-4-7-opus-vertex-genai")

    def test_a_config_without_model_name_on_itself_is_not_the_test(self):
        """AgentConfig has no `model_name` attribute at all — that was the bug."""
        cfg = _cfg("gpt-5-2-genai")
        self.assertFalse(hasattr(cfg, "model_name"))
        self.assertEqual(_model(cfg, None), "gpt-5-2-genai")


class ItFallsBackToTheLlmClient(unittest.TestCase):

    def test_the_llm_clients_own_config_is_the_second_source(self):
        llm = types.SimpleNamespace(config=types.SimpleNamespace(model_name="gemini-3-5-flash-genai"))
        self.assertEqual(_model(_cfg(None), llm), "gemini-3-5-flash-genai")

    def test_config_wins_over_the_client(self):
        llm = types.SimpleNamespace(config=types.SimpleNamespace(model_name="other"))
        self.assertEqual(_model(_cfg("primary"), llm), "primary")


class ItNeverRaises(unittest.TestCase):
    """This runs in __init__; a throw here would take the agent down."""

    def test_missing_everything_is_none(self):
        self.assertIsNone(_model(None, None))
        self.assertIsNone(_model(_cfg(None, with_llm=False), None))
        self.assertIsNone(_model(types.SimpleNamespace(), types.SimpleNamespace()))

    def test_a_blank_name_is_none_not_empty_string(self):
        self.assertIsNone(_model(_cfg(""), None))
        self.assertIsNone(_model(_cfg("   "), None))


class TheBudgetActuallyMovesWithIt(unittest.TestCase):
    """Non-vacuity: threading the name has to change the numbers."""

    def test_a_known_model_lifts_both_budgets_off_the_floor(self):
        from memory.memory_bank import MemoryBank, _DIGEST_CHARS, _NOTEBOOK_CHARS
        import tempfile
        root = Path(tempfile.mkdtemp())
        floor = MemoryBank(root_dir=root, memory_dir=root / "a")._resolve_char_budgets()
        sized = MemoryBank(root_dir=root, memory_dir=root / "b",
                           model="claude-4-7-opus-vertex-genai")._resolve_char_budgets()
        self.assertEqual(floor, (_DIGEST_CHARS, _NOTEBOOK_CHARS))
        self.assertGreater(sized[0], floor[0] * 5)
        self.assertGreater(sized[1], floor[1] * 5)


if __name__ == "__main__":
    unittest.main()
