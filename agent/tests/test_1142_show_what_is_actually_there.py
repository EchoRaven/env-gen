"""#1142: "Re-read from there" cost the caller a whole turn.

`_anchor_miss_reason_676` already localises a failed edit precisely — "its FIRST line is at
line N, but the block diverges after that" — and then told the agent to go and read the file.
That makes one edit a three-turn cycle: fail, read, retry, each re-sending 54-65K tokens of
context at ~6.3s.

Measured over the eight netflix runs: **179 of 360 edit/patch failures are this class**
(`old_string not found` 89, `patch hunk` mismatch 90), so the re-read alone is ~179 turns that
carry no new decision. The lines are already in hand at the point the message is built.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from tools.canonical_file_tools.edit import _anchor_miss_reason_676 as reason  # noqa: E402

CONTENT = "def a():\n    x = 1\n    y = 2\n    return x\n"


class ItHandsBackWhatTheNextEditNeeds(unittest.TestCase):

    def test_the_divergent_block_is_shown_verbatim(self):
        msg = reason(CONTENT, "    x = 1\n    y = 99\n", Path("f.py"))
        self.assertIn("WHAT IS ACTUALLY AT LINE 2", msg)
        self.assertIn("    x = 1", msg)
        self.assertIn("    y = 2", msg)

    def test_indentation_is_preserved_so_it_can_be_copied(self):
        msg = reason(CONTENT, "    x = 1\n    y = 99\n", Path("f.py"))
        self.assertIn("\n    x = 1", msg, "leading spaces must survive")

    def test_it_still_says_where(self):
        self.assertIn("line 2", reason(CONTENT, "    x = 1\n    y = 99\n", Path("f.py")))


class TheOtherBranchesAreUnchanged(unittest.TestCase):

    def test_absent_anchor_keeps_its_wording(self):
        msg = reason(CONTENT, "zzz\n", Path("f.py"))
        self.assertIn("no part of the anchor is present", msg)
        self.assertNotIn("WHAT IS ACTUALLY", msg)

    def test_whitespace_only_difference_keeps_its_wording(self):
        msg = reason(CONTENT, "    x  =  1\n    y  =  2\n", Path("f.py"))
        self.assertIn("different whitespace", msg)
        self.assertNotIn("WHAT IS ACTUALLY", msg)


class ItCannotFloodTheCaller(unittest.TestCase):
    """One error must not become a wall of text."""

    def test_the_excerpt_is_capped_by_the_anchors_own_length(self):
        content = "HEAD\n" + "".join(f"line{i}\n" for i in range(500))
        anchor = "HEAD\n" + "".join(f"WRONG{i}\n" for i in range(400))
        msg = reason(content, anchor, Path("big.py"))
        self.assertLess(len(msg), 2000, "excerpt must be bounded")

    def test_a_long_single_block_is_truncated_with_a_marker(self):
        content = "HEAD\n" + "".join("x" * 200 + "\n" for _ in range(20))
        anchor = "HEAD\n" + "".join("y" * 200 + "\n" for _ in range(12))
        msg = reason(content, anchor, Path("big.py"))
        self.assertTrue(len(msg) < 2200)
        if len(msg) > 1200:
            self.assertIn("truncated", msg)

    def test_a_fault_never_loses_the_base_message(self):
        self.assertIn("old_string not found", reason(None, None, None))


if __name__ == "__main__":
    unittest.main()
