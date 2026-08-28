"""#1141: "Prefer one tool call per step" was a constant; it is now a hyperparameter.

Measured over eight netflix runs: 85.9% of turns issue exactly ONE tool call, mean 1.32, and
the mean is FLAT across every run (r3 1.34, r5 1.41, r8 1.43, r9 1.34) — a ceiling set by the
instruction, not by the work. Each turn re-sends 54-65K tokens at 6.3s mean latency, so r9
spent 8185 calls (14.3 hours of LLM time) on 3714 tool calls.

The stated rationale — "the smallest unit of work that produces a hub-observable change" — is
real for a MUTATING call and empty for a read: a read produces no hub change, and ~48% of every
run's calls are reads (r9: workhub_list_tasks 619, workhub_task 540, registry reads 299).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.agents.base import (  # noqa: E402
    _max_tools_per_step_1141, _tool_batch_policy_1141,
)

PROMPTS = LLM_DIR / "multi_agent" / "prompts"


class _Env(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.pop("ENVGEN_MAX_TOOLS_PER_STEP", None)

    def tearDown(self):
        os.environ.pop("ENVGEN_MAX_TOOLS_PER_STEP", None)
        if self._prev is not None:
            os.environ["ENVGEN_MAX_TOOLS_PER_STEP"] = self._prev


class TheDefaultNoLongerForbidsBatching(_Env):

    def test_unset_means_unlimited(self):
        self.assertEqual(_max_tools_per_step_1141(), 0)
        self.assertIn("no cap", _tool_batch_policy_1141())

    def test_the_policy_asks_for_independent_calls_together(self):
        p = _tool_batch_policy_1141()
        self.assertIn("INDEPENDENT", p)
        self.assertIn("ONE step", p)

    def test_the_hub_observability_rule_survives_for_writes(self):
        """The rationale was always about writes; it must not be lost."""
        p = _tool_batch_policy_1141()
        self.assertIn("MUTATING", p)
        self.assertIn("hub-observable", p)


class TheCapIsConfigurable(_Env):

    def test_a_number_caps_the_step(self):
        os.environ["ENVGEN_MAX_TOOLS_PER_STEP"] = "5"
        self.assertEqual(_max_tools_per_step_1141(), 5)
        self.assertIn("At most 5", _tool_batch_policy_1141())

    def test_zero_and_negative_mean_unlimited(self):
        for v in ("0", "-3"):
            os.environ["ENVGEN_MAX_TOOLS_PER_STEP"] = v
            self.assertEqual(_max_tools_per_step_1141(), 0)

    def test_junk_falls_back_to_unlimited_and_does_not_raise(self):
        for v in ("abc", "", "3.7", "١٢"):
            os.environ["ENVGEN_MAX_TOOLS_PER_STEP"] = v
            self.assertEqual(_max_tools_per_step_1141(), 0, v)


class ThePromptsNoLongerHardcodeIt(unittest.TestCase):

    def test_no_prompt_still_says_prefer_one_tool_call(self):
        hits = []
        for f in PROMPTS.rglob("*.j2"):
            t = f.read_text(encoding="utf-8", errors="replace")
            if "one tool call per step" in t.lower():
                hits.append(f.name)
        self.assertEqual(hits, [], f"still hardcoded in: {hits}")

    def test_exactly_one_template_owns_the_policy(self):
        """#1141b: one owner, appended by the shared macro, so every lane gets it.

        The first shape put the policy in three files as the OVERRIDE DEFAULT, which meant
        the 11 prompts that override `action` never saw it — one lane out of six.
        """
        rendered = [f for f in PROMPTS.rglob("*.j2")
                    if "tool_batch_policy" in f.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual([f.name for f in rendered], ["agent_definition_v3.j2"])

    def test_every_use_carries_a_fallback(self):
        """A bare Environment (tests/vision_tools build their own) leaves the global
        undefined, and Jinja renders undefined as an EMPTY STRING — the step contract would
        silently lose its action text. `default(..., true)` makes that impossible."""
        for f in PROMPTS.rglob("*.j2"):
            t = f.read_text(encoding="utf-8", errors="replace")
            if "tool_batch_policy" not in t:
                continue
            for line in t.splitlines():
                if "tool_batch_policy" in line:
                    self.assertIn("default(", line, f"{f.name}: {line.strip()[:90]}")

    def test_a_bare_environment_still_renders_real_guidance(self):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(str(PROMPTS)))
        out = env.from_string(
            "{{ tool_batch_policy | default('INDEPENDENT calls together', true) }}").render()
        self.assertTrue(out.strip())
        self.assertNotEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()


class AnOverrideMustNotSwallowThePolicy(unittest.TestCase):
    """#1141b: 11 of 13 agent prompts override `action` with lane-specific text.

    While the policy was the override's DEFAULT, only the two frontend files ever saw it —
    backend, verifier, orchestrator and debugger replaced it wholesale. That is why r10's
    full-run batching moved 1.34 -> 1.40 while a 30-minute window had looked like 2.38: the
    instruction reached one lane out of six.
    """

    def _render(self, overrides):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(str(PROMPTS)),
                          trim_blocks=True, lstrip_blocks=True)
        return env.from_string(
            "{% import 'agents/shared/agent_definition_v3.j2' as d %}"
            "{{ d.agent_prompt_v3(id='x', name='X', mandate='m',"
            " step_contract_overrides=OV) }}".replace("OV", repr(overrides))).render()

    def test_a_lane_override_still_carries_the_batching_rule(self):
        out = self._render({"action": "Register endpoints and write custom_routes."})
        assert "Register endpoints" in out
        self.assertIn("INDEPENDENT tool calls together in ONE step", out)

    def test_no_override_still_carries_it(self):
        self.assertIn("INDEPENDENT tool calls together in ONE step", self._render({}))

    def test_the_frontend_files_no_longer_duplicate_it(self):
        for f in ("v3/frontend_agent.j2", "v4/frontend_agent.j2"):
            t = (PROMPTS / f).read_text(encoding="utf-8")
            self.assertNotIn("tool_batch_policy", t,
                             f"{f}: the macro appends it now; an inline copy would double up")
