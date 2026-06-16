"""Memory-redesign #2: deliver_project / report_completion must be
gated on at least one submit_retro for the current run, otherwise
``submit_retro`` stays at 0 calls forever (the run ends right when
the LLM would have called it).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import RetroBeforeDeliverPolicy  # noqa: E402


class _StubAgent:
    def __init__(self, hubs):
        self.agent_id = "orchestrator"
        self._agent_id = "orchestrator"
        self._hubs = hubs
        self._logger = MagicMock()


def _run(tool_name, hubs, agent=None, args=None):
    pol = RetroBeforeDeliverPolicy()
    msgs = []
    outcome = asyncio.run(pol.handle_finish(
        agent or _StubAgent(hubs),
        tool_name=tool_name,
        tool_args=args or {"status": "done"},
        tool_call=MagicMock(),
        tool_call_id="tc",
        messages=msgs,
        files_created=[],
        files_modified=[],
    ))
    return outcome, msgs


class GateBlocksDeliverWhenNoRetro(unittest.TestCase):
    def test_deliver_project_without_retro_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            outcome, msgs = _run("deliver_project", hubs)
            self.assertEqual(outcome, {"action": "continue"})
            self.assertEqual(len(msgs), 3, "Expect assistant-toolcall + tool-block + user-follow-up")
            self.assertIn("submit_retro", str(msgs[1].content))

    def test_report_completion_without_retro_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            outcome, msgs = _run("report_completion", hubs)
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("submit_retro", str(msgs[1].content))

    def test_block_message_includes_template(self):
        """Block text must show the schema so the agent doesn't waste
        a round figuring it out."""
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            _, msgs = _run("deliver_project", hubs)
            block = str(msgs[1].content)
            for required in ("plan_vs_reality", "root_causes",
                              "decisions", "follow_ups", "title="):
                self.assertIn(required, block, f"Missing template field: {required}")


class GatePassesAfterRetroFiled(unittest.TestCase):
    def _seed_retro(self, hubs, page_id="retro:r1", generation_id=None):
        meta = {"generation_id": generation_id} if generation_id else {}
        hubs.workhub.stores.pages.update(
            lambda m: m.set(page_id,
                             {"id": page_id, "kind": "retro",
                              "title": "First retro",
                              "metadata": meta,
                              "created_at": 1.0},
                             "orchestrator"),
            change_info={"agent": "orchestrator"},
        )

    def test_gate_passes_when_retro_for_current_generation_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            hubs.attach_generation_id("gen_current")
            self._seed_retro(hubs, generation_id="gen_current")
            outcome, msgs = _run("deliver_project", hubs)
            self.assertIsNone(outcome)
            self.assertEqual(msgs, [])

    def test_gate_blocks_when_only_prior_generations_retros_exist(self):
        """Reviewer's bug: in --no-fresh runs, a prior run's retro would
        silently satisfy the gate. After the fix, only the current
        generation's retro counts."""
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            hubs.attach_generation_id("gen_current")
            # Prior run left a retro on disk.
            self._seed_retro(hubs, page_id="retro:r_old",
                              generation_id="gen_previous")
            outcome, msgs = _run("deliver_project", hubs)
            self.assertEqual(outcome, {"action": "continue"},
                              "Cross-generation retro must NOT satisfy "
                              "this run's gate.")
            block = str(msgs[1].content)
            self.assertIn("gen_current", block,
                           "Block message must mention the current "
                           "generation so the agent knows the scope.")

    def test_gate_falls_back_to_any_retro_when_gen_id_unset(self):
        """Defensive fallback so an unwired registry doesn't crash
        finish. Emits a warning so the degraded check is visible."""
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            # No attach_generation_id call — simulates unwired registry.
            self._seed_retro(hubs, generation_id="gen_anything")
            agent = _StubAgent(hubs)
            outcome, _msgs = _run("deliver_project", hubs, agent=agent)
            self.assertIsNone(outcome,
                              "Fallback must accept any-retro when gen_id is None")
            agent._logger.warning.assert_called()


class GateIgnoresNonDeliverTools(unittest.TestCase):
    """Other ``finish``-like tools (the plain ``finish``,
    ``send_message``, ``report_progress``) must not be gated."""

    def test_finish_is_not_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            outcome, msgs = _run("finish", hubs)
            self.assertIsNone(outcome)
            self.assertEqual(msgs, [])

    def test_report_progress_is_not_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            outcome, msgs = _run("report_progress", hubs)
            self.assertIsNone(outcome)
            self.assertEqual(msgs, [])


class GenerationIdSemantics(unittest.TestCase):
    """Pin the documented semantics so future tweaks don't accidentally
    break the scoping contract.

    Two invariants:
      * ``HubRegistry.generation_id`` defaults to None — no
        ``time.time()`` fallback that would re-bug the gate.
      * Two HubRegistry instances over the same workspace get
        DIFFERENT generation ids when attached separately, because
        scoping is per Orchestrator instance, not per workspace.
        This is the ``--resume`` semantics the docstring describes.
    """

    def test_default_generation_id_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            self.assertIsNone(hubs.generation_id,
                              "must default to None — no time.time() fallback "
                              "(see reviewer's bug report on the retro gate)")

    def test_resumed_orchestrator_gets_fresh_generation_id(self):
        """Two HubRegistry instances built over the same workspace —
        simulating a --resume — must NOT share a generation id
        derived from workspace state. Each gets its own pinned uuid."""
        import uuid as _uuid
        with tempfile.TemporaryDirectory() as tmp:
            hubs_a = HubRegistry(Path(tmp))
            hubs_a.attach_generation_id(f"gen_{_uuid.uuid4().hex[:12]}")
            hubs_b = HubRegistry(Path(tmp))
            hubs_b.attach_generation_id(f"gen_{_uuid.uuid4().hex[:12]}")
            self.assertNotEqual(hubs_a.generation_id, hubs_b.generation_id,
                                "Each Orchestrator instance must get its own "
                                "generation id — resumed runs must NOT inherit "
                                "the original run's id, otherwise the retro "
                                "gate would auto-pass on resume.")


class FactoryWiring(unittest.TestCase):
    def test_yaml_factory_constructs(self):
        from multi_agent.workflow_policies import create_workflow_policies
        cfg = {"workflow_policies": [{"kind": "retro_before_deliver"}]}
        policies = create_workflow_policies(cfg)
        matching = [p for p in policies if isinstance(p, RetroBeforeDeliverPolicy)]
        self.assertEqual(len(matching), 1)

    def test_orchestrator_yaml_enables_the_gate(self):
        """The yaml must wire it onto the orchestrator profile —
        without that the policy class exists but the gate never fires."""
        import yaml
        cfg = yaml.safe_load(
            (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml").read_text()
        )
        orch = cfg["profiles"]["orchestrator"]
        kinds = [p.get("kind") for p in orch.get("workflow_policies") or []]
        self.assertIn("retro_before_deliver", kinds,
                       "orchestrator profile must enable the retro gate")


if __name__ == "__main__":
    unittest.main()
