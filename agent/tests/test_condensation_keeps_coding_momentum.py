"""Condensation must preserve a coding lane's ability to KEEP IMPLEMENTING.

Background: the message-condensation handoff used to be reflective ("[SMART
CONTEXT SUMMARY]" + a markdown recap) and collapsed the most-recent file-write
into a one-line "wrote X to path". After the first condensation a coding lane
lost its concrete code anchor and its forward intent, dropping into
reflect/re-plan mode (looping on memory-bank bookkeeping) instead of writing the
next handler. The redesign makes the handoff forward-directive, pins the
most-recent code-writing tool pair verbatim, and surfaces the remaining work.

These tests pin that behavior:
    (a) the handoff is forward-directive (contains the resume imperative),
    (b) the most-recent code-writing assistant+result pair survives VERBATIM,
    (c) the remaining-work / open-task instruction is present,
    (d) tool_call/tool pairing stays valid (no orphan tool result),
    (e) the compressed size stays bounded.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from utils.llm import Message  # noqa: E402
from memory.generator_memory import (  # noqa: E402
    CODE_WRITE_TOOL_NAMES,
    RESUME_DIRECTIVE,
    SmartMessageCompressor,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _assistant_write(body: str, call_id: str, tool: str = "write") -> Message:
    """An assistant turn that writes a file (carries a file-write tool_call)."""
    return Message(
        role="assistant",
        content=f"WRITE_ANCHOR_BODY :: {body}",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool, "arguments": '{"path":"app/x.py"}'},
            }
        ],
    )


def _tool_result(call_id: str, text: str) -> Message:
    return Message(role="tool", content=text, tool_call_id=call_id)


def _texts(messages):
    out = []
    for m in messages:
        c = m.content if isinstance(m.content, str) else str(m.content)
        out.append(c or "")
    return "\n".join(out)


def _build_history(*, with_anchor: bool = True, n_pad: int = 60):
    """A long coding transcript whose only file-write is in the compress region."""
    msgs = [
        Message.system("system prompt"),
        Message.user(
            "TASK: implement tenant CRUD. POST /api/tenants, GET /api/tenants, "
            "DELETE /api/tenants/{id}"
        ),
    ]
    for i in range(n_pad):
        msgs.append(Message.user(f"NEXT to implement: GET /api/tenants/{i}"))
        msgs.append(Message.assistant(content=f"reasoning noise {i}"))
    if with_anchor:
        # The single most-recent file write — must survive verbatim.
        msgs.append(_assistant_write("def create_tenant(): return DB_INSERT_42", "call_anchor"))
        msgs.append(_tool_result("call_anchor", "wrote 42 lines to app/backend/tenants.py"))
    # Trailing recent turns (kept by keep_recent anyway).
    for i in range(30):
        msgs.append(Message.user(f"recent turn {i}"))
    return msgs


class CondensationMomentumTest(unittest.TestCase):

    def test_handoff_is_forward_directive(self) -> None:
        """The compressed handoff ends in a resume-work imperative, not a recap."""
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(_build_history(), keep_recent=28))
        joined = _texts(out)
        self.assertIn(RESUME_DIRECTIVE, joined)
        self.assertIn("RESUME NOW", joined)
        self.assertIn("WRITING CODE", joined)
        # NOT the old reflective framing.
        self.assertNotIn("[SMART CONTEXT SUMMARY", joined)

    def test_most_recent_code_pair_survives_verbatim(self) -> None:
        """The last file-write assistant(tool_calls)+result is pinned untouched."""
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(_build_history(), keep_recent=28))
        joined = _texts(out)
        # Verbatim body and result text both present.
        self.assertIn("WRITE_ANCHOR_BODY", joined)
        self.assertIn("DB_INSERT_42", joined)
        self.assertIn("wrote 42 lines to app/backend/tenants.py", joined)
        # And present as a real pair (assistant with tool_calls + tool result).
        anchor_idxs = [
            i for i, m in enumerate(out)
            if isinstance(m.content, str) and "WRITE_ANCHOR_BODY" in m.content
        ]
        self.assertEqual(len(anchor_idxs), 1)
        ai = anchor_idxs[0]
        self.assertEqual(out[ai].role, "assistant")
        self.assertTrue(out[ai].tool_calls)
        self.assertEqual(out[ai + 1].role, "tool")
        self.assertEqual(out[ai + 1].tool_call_id, "call_anchor")

    def test_remaining_work_or_task_instruction_present(self) -> None:
        """Either derived remaining endpoints or the 'query open tasks once' hint."""
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(_build_history(), keep_recent=28))
        joined = _texts(out)
        derived = "REMAINING WORK" in joined or "STILL TO DO" in joined
        self.assertTrue(derived)
        # The resume imperative itself instructs the one-shot task query fallback.
        self.assertIn("query your open tasks ONCE", RESUME_DIRECTIVE)

    def test_tool_pairing_stays_valid(self) -> None:
        """No tool result is orphaned: each 'tool' msg follows an assistant turn."""
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(_build_history(), keep_recent=28))
        for i, m in enumerate(out):
            if m.role == "tool":
                self.assertGreater(i, 0)
                self.assertEqual(
                    out[i - 1].role, "assistant",
                    msg=f"tool result at index {i} is not preceded by an assistant",
                )

    def test_compressed_size_is_bounded(self) -> None:
        """Compressed length stays near keep_recent + summary + system + anchor."""
        history = _build_history(n_pad=80)  # ~190 messages
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(history, keep_recent=28))
        self.assertLess(len(out), len(history))
        # system(1) + summary(1) + anchor_pair(2) + keep_recent(28) ≈ 32; allow slack.
        self.assertLessEqual(len(out), 40)
        # Far under the ~770 saturation point.
        self.assertLess(len(out), 770)

    def test_no_write_in_compress_region_still_directive(self) -> None:
        """With no code anchor available, the handoff is still forward-directive."""
        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(_build_history(with_anchor=False), keep_recent=28))
        joined = _texts(out)
        self.assertIn(RESUME_DIRECTIVE, joined)
        # No spurious anchor pointer when nothing was pinned.
        self.assertNotIn("preserved\nVERBATIM", joined)

    def test_extract_code_anchor_recognizes_all_write_tools(self) -> None:
        """edit / apply_patch are also treated as code anchors, not just write."""
        comp = SmartMessageCompressor(llm=None)
        for tool in sorted(CODE_WRITE_TOOL_NAMES):
            msgs = [
                _assistant_write(f"body-{tool}", f"c_{tool}", tool=tool),
                _tool_result(f"c_{tool}", "ok"),
            ]
            anchor = comp._extract_code_anchor(msgs)
            self.assertEqual(len(anchor), 2, msg=f"{tool} not recognized as anchor")
            self.assertEqual(anchor[0].role, "assistant")
            self.assertEqual(anchor[1].role, "tool")

    def test_works_with_dict_messages(self) -> None:
        """Compressor accepts plain dict messages (not just Message objects)."""
        msgs = [{"role": "system", "content": "sys"}]
        msgs.append({"role": "user", "content": "TASK: POST /api/things"})
        for i in range(60):
            msgs.append({"role": "user", "content": f"NEXT to implement: GET /api/things/{i}"})
            msgs.append({"role": "assistant", "content": f"noise {i}"})
        msgs.append({
            "role": "assistant",
            "content": "WRITE_ANCHOR_BODY :: dict_anchor",
            "tool_calls": [
                {"id": "d1", "type": "function",
                 "function": {"name": "write", "arguments": "{}"}}
            ],
        })
        msgs.append({"role": "tool", "content": "wrote dict file", "tool_call_id": "d1"})
        for i in range(20):
            msgs.append({"role": "user", "content": f"recent {i}"})

        comp = SmartMessageCompressor(llm=None)
        out, _ = _run(comp.compress(msgs, keep_recent=28))
        joined = "\n".join(m.get("content", "") for m in out if isinstance(m, dict))
        self.assertIn("RESUME NOW", joined)
        self.assertIn("WRITE_ANCHOR_BODY", joined)
        self.assertIn("dict_anchor", joined)


if __name__ == "__main__":
    unittest.main()
