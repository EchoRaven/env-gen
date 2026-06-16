"""_handle_human_message rewritten as bounded mini-loop with tools (Task 4)."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from utils.message import BaseMessage, MessageHeader, MessageType, MessagePriority  # noqa: E402


def _reset_event_loop():
    """``asyncio.run`` closes the current loop and leaves the thread
    without one. Subsequent tests calling ``asyncio.get_event_loop()``
    then raise ``RuntimeError``. Reset so the next test gets a fresh
    loop without inheriting a closed one."""
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


def _make_human_message(thread_id: str, text: str = "please continue working"):
    header = MessageHeader(
        source_agent_id="human_user",
        target_agent_id="design",
        priority=MessagePriority.URGENT,
        correlation_id=thread_id,
    )
    return BaseMessage(
        header=header,
        message_type=MessageType.STATUS,
        payload={"text": text, "from_user": "haibotong"},
        metadata={"event_type": "human_message", "thread_id": thread_id},
    )


class TestHumanMessageMiniLoop(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_mini_loop_called_with_max_steps_5_and_text(self):
        """_handle_human_message must delegate to _run_chat_mini_loop with max_steps=5."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            seen = {}

            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()
                _chat_mode_thread_id = None
                def _get_system_prompt(self): return "BASE"
                async def _run_chat_mini_loop(self, user_text, thread_id, max_steps):
                    seen["user_text"] = user_text
                    seen["thread_id"] = thread_id
                    seen["max_steps"] = max_steps
                    seen["chat_mode_flag"] = self._chat_mode_thread_id
                    return "I claimed T-3; starting now."

            from multi_agent.agents.base import EnvGenAgent
            msg = _make_human_message(tid, text="please claim a task")
            asyncio.run(EnvGenAgent._handle_human_message(Stub(), msg))

            self.assertEqual(seen["max_steps"], 5)
            self.assertEqual(seen["user_text"], "please claim a task")
            self.assertEqual(seen["thread_id"], tid)
            # _chat_mode_thread_id MUST be set before the loop runs
            self.assertEqual(seen["chat_mode_flag"], tid)

    def test_mini_loop_result_published_as_agent_reply(self):
        """The text returned by _run_chat_mini_loop becomes the agent_reply payload."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p2", project_name="P2")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()
                _chat_mode_thread_id = None
                def _get_system_prompt(self): return "BASE"
                async def _run_chat_mini_loop(self, user_text, thread_id, max_steps):
                    return "Claimed T-3; on it."

            from multi_agent.agents.base import EnvGenAgent
            msg = _make_human_message(tid)
            asyncio.run(EnvGenAgent._handle_human_message(Stub(), msg))

            transcript = reg.eventhub.get_thread_transcript(tid)
            assistants = [e for e in transcript if e["role"] == "assistant"]
            self.assertEqual(len(assistants), 1)
            self.assertEqual(assistants[0]["text"], "Claimed T-3; on it.")
            self.assertEqual(assistants[0]["speaker"], "design")

    def test_chat_mode_flag_cleared_after_loop(self):
        """_chat_mode_thread_id must be reset to None after the loop finishes."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p3", project_name="P3")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()
                _chat_mode_thread_id = None
                def _get_system_prompt(self): return "BASE"
                async def _run_chat_mini_loop(self, user_text, thread_id, max_steps):
                    return "ok"

            from multi_agent.agents.base import EnvGenAgent
            stub = Stub()
            asyncio.run(EnvGenAgent._handle_human_message(stub, _make_human_message(tid)))
            self.assertIsNone(stub._chat_mode_thread_id)

    def test_chat_mode_flag_cleared_even_on_loop_exception(self):
        """Loop exceptions must not leave the flag stuck."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p4", project_name="P4")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()
                _chat_mode_thread_id = None
                def _get_system_prompt(self): return "BASE"
                async def _run_chat_mini_loop(self, user_text, thread_id, max_steps):
                    raise RuntimeError("mini-loop kaboom")

            from multi_agent.agents.base import EnvGenAgent
            stub = Stub()
            asyncio.run(EnvGenAgent._handle_human_message(stub, _make_human_message(tid)))
            self.assertIsNone(stub._chat_mode_thread_id)

            # An apology reply should still be published
            transcript = reg.eventhub.get_thread_transcript(tid)
            assistants = [e for e in transcript if e["role"] == "assistant"]
            self.assertEqual(len(assistants), 1)
            self.assertIn("kaboom", assistants[0]["text"].lower() + "")  # truthy substring
            # text contains the error or an apology
            text = assistants[0]["text"].lower()
            self.assertTrue("error" in text or "fail" in text or "unable" in text or "kaboom" in text)

    def test_missing_thread_id_logs_and_returns_no_publish(self):
        """Empty thread_id: just warn + return; no LLM, no publish."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p5", project_name="P5")

            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()
                _chat_mode_thread_id = None
                def _get_system_prompt(self): return "BASE"
                async def _run_chat_mini_loop(self, user_text, thread_id, max_steps):
                    raise AssertionError("mini-loop must not be called")

            from multi_agent.agents.base import EnvGenAgent
            header = MessageHeader(source_agent_id="human_user", target_agent_id="design",
                                  priority=MessagePriority.URGENT, correlation_id=None)
            msg = BaseMessage(
                header=header, message_type=MessageType.STATUS,
                payload={"text": "x"},
                metadata={"event_type": "human_message", "thread_id": ""},
            )
            asyncio.run(EnvGenAgent._handle_human_message(Stub(), msg))


class TestChatSystemPromptHasNoToolBan(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_chat_mode_system_prompt_has_no_tool_ban(self):
        """Sanity: the mini-loop's chat-mode system prompt suffix must
        NOT forbid tool use (the whole point of Phase 4 was killing the
        'Do not call any tools' ban from the old single-shot handler).

        Verified by directly inspecting the source of ``_run_chat_mini_loop``
        — the string this test guards against would have appeared in the
        chat_system block construction. Inspecting source instead of
        running the loop avoids the swallowed-AttributeError trap where
        a stub's missing attribute makes the original assertion run
        against an empty string and trivially pass.
        """
        import inspect
        from multi_agent.agents.base import EnvGenAgent
        source = inspect.getsource(EnvGenAgent._run_chat_mini_loop)
        # The banned phrase from the OLD single-shot handler.
        self.assertNotIn("Do not call any tools", source)
        # Positive check: the rewritten chat-mode preamble grants
        # tool access. Source has the prompt split across f-string
        # concatenated lines, so we look for distinctive fragments
        # rather than a contiguous span.
        self.assertIn("You may", source)
        self.assertIn("call any of your tools", source)
        self.assertIn("=== Chat mode ===", source)


class TestMiniLoopTracksFileWrites(unittest.TestCase):
    """Mini-loop must track file writes locally so finish-policies see
    real evidence. Without this, HubConsistencyPolicy.handle_finish is
    handed files_created=[] / files_modified=[] and silently no-ops
    even when the agent wrote a dozen route files mid-chat."""

    def tearDown(self):
        _reset_event_loop()

    def test_mini_loop_passes_written_files_to_finish_policies(self):
        import asyncio
        from unittest.mock import MagicMock
        from multi_agent.runtime.hub_registry import HubRegistry

        seen = {"files_created": None, "files_modified": None}

        async def capture_policies(self, *, files_created, files_modified, **_kw):
            seen["files_created"] = list(files_created)
            seen["files_modified"] = list(files_modified)
            return None  # don't intercept; let finish proceed

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")

            tool_call_sequence = iter([
                # round 1: write a route file
                ("write", {"file_path": "app/backend/src/routes/auth.js", "content": "x"}, "tc1"),
                # round 2: edit a second file then finish
                ("edit", {"file_path": "app/backend/src/routes/users.js", "old_string": "a", "new_string": "b"}, "tc2"),
                ("finish", {"message": "done"}, "tc3"),
            ])
            tool_index = {"i": 0}

            class Stub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _logger = MagicMock()
                _workflow_policies = []
                workspace = MagicMock()
                _apply_finish_policies = capture_policies

                async def _execute_tool(self, name, args):
                    class R:
                        success = True
                        data = "ok"
                        error_message = None
                    return R()

                def _normalize_tool_call(self, tc, step):
                    # Just dispatch the next pre-baked call in sequence.
                    i = tool_index["i"]
                    tool_index["i"] += 1
                    return tool_call_sequence_list[i]

                def _build_tool_schema_map(self):
                    return {}

                def _emit_chat_step(self, **kw):
                    return None

                async def call_with_retry(self, fn, *a, **k):
                    return await fn(*a, **k)

            stub = Stub()
            tool_call_sequence_list = [
                ("write", {"file_path": "app/backend/src/routes/auth.js"}, "tc1"),
                ("edit", {"file_path": "app/backend/src/routes/users.js"}, "tc2"),
                ("finish", {"message": "done"}, "tc3"),
            ]

            # Stub LLM: returns one tool_call per round, then finish.
            tool_calls_by_round = [[object()], [object()], [object()]]

            class FakeResp:
                content = ""
                def __init__(self, tcs):
                    self.tool_calls = tcs

            class FakeLLM:
                def __init__(self):
                    self.round = 0
                async def chat_messages(self, messages, tools=None, **_kw):
                    r = FakeResp(tool_calls_by_round[self.round])
                    self.round += 1
                    return r

            stub.llm = FakeLLM()

            from multi_agent.agents.base import EnvGenAgent
            asyncio.run(EnvGenAgent._run_chat_mini_loop(
                stub, user_text="please add routes", thread_id="t1", max_steps=5,
            ))

            self.assertIsNotNone(seen["files_created"], "policy must have been called")
            self.assertIn("app/backend/src/routes/auth.js", seen["files_created"])
            self.assertIn("app/backend/src/routes/users.js", seen["files_modified"])


class TestMiniLoopFinishHonorsHubConsistencyGate(unittest.TestCase):
    """Critical: when the LLM emits finish() inside the chat mini-loop, it
    must NOT short-circuit the configured workflow_policies (e.g. the
    HubConsistencyPolicy). Otherwise chat becomes a back-door around the
    very gate Phase A installs.
    """

    def tearDown(self):
        _reset_event_loop()

    def test_finish_inside_mini_loop_routes_through_policies(self):
        import asyncio
        from unittest.mock import MagicMock
        from multi_agent.workflow_policies import HubConsistencyPolicy
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            policy = HubConsistencyPolicy(
                expect_hub_kinds=["registryhub_endpoints"],
                file_patterns=["routes/"],
            )

            captured = {"policy_called": False, "tool_name_seen": None}

            class Stub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _logger = MagicMock()
                _workflow_policies = [policy]
                workspace = None

                # Required surface for the mini-loop / _apply_finish_policies.
                async def _execute_tool(self, name, args):
                    raise AssertionError("finish path should be intercepted before _execute_tool")

            stub = Stub()

            # Exercise the policy contract directly: a finish tool_call
            # against a state where the agent wrote a route file but did
            # NOT register the endpoint must surface a clear "register
            # first" blocker. The integration test below verifies the
            # mini-loop actually invokes this path.
            messages: list = []
            outcome = asyncio.run(policy.handle_finish(
                stub,
                tool_name="finish",
                tool_args={"message": "I'm done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=["app/backend/src/routes/auth.js"],
                files_modified=[],
            ))
            # The gate must report continue + leave a clear blocker in messages.
            self.assertEqual(outcome, {"action": "continue"})
            self.assertTrue(any("registryhub_register_endpoint" in str(m.content) for m in messages))

    def test_finish_in_mini_loop_actually_invokes_policies(self):
        """Higher-bar: the mini-loop's finish-handling code path must call
        _apply_finish_policies before returning the finish text."""
        import asyncio
        from unittest.mock import MagicMock
        from multi_agent.runtime.hub_registry import HubRegistry
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p2", project_name="P2")

            policy_calls = {"count": 0}

            async def fake_policies(self, *, tool_name, **_kw):
                policy_calls["count"] += 1
                # First time the gate blocks → continue; second time pass.
                if policy_calls["count"] == 1:
                    return {"action": "continue"}
                return None

            class Stub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _logger = MagicMock()
                _workflow_policies = []
                workspace = MagicMock()
                # Provide the helper the mini-loop should call.
                _apply_finish_policies = fake_policies
                # Required for the post-policy default-path fall-through.
                async def _execute_tool(self, name, args):
                    class R:
                        success = True
                        data = "ok"
                        error_message = None
                    return R()

                def _normalize_tool_call(self, tc, step):
                    return ("finish", {"message": "done"}, "tc1")

                def _build_tool_schema_map(self):
                    return {}

                async def call_with_retry(self, fn, *a, **k):
                    # The mini-loop wraps the chat_messages call through
                    # call_with_retry; for the test we just dispatch.
                    return await fn(*a, **k)

                def _emit_chat_step(self, **kw):
                    # The real method publishes via EventHub; for this
                    # policy-flow test we just no-op.
                    return None

            from multi_agent.agents.base import EnvGenAgent
            # Drive the mini-loop just enough to hit the finish branch.
            # Stub out the LLM to return a single tool_call=finish, no text.
            stub = Stub()
            class FakeResp:
                content = ""
                tool_calls = [object()]  # one fake tool call
            class FakeLLM:
                async def chat_messages(self, messages, tools=None, **_kw):
                    return FakeResp()
            stub.llm = FakeLLM()

            # The real method is async; run it.
            reply = asyncio.run(EnvGenAgent._run_chat_mini_loop(
                stub, user_text="please finish", thread_id="t1", max_steps=2,
            ))
            self.assertGreaterEqual(
                policy_calls["count"], 1,
                "mini-loop must call _apply_finish_policies on a finish tool_call",
            )


if __name__ == "__main__":
    unittest.main()
