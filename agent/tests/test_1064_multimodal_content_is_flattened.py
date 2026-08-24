"""#1064 — a multimodal message content (a LIST) reaches a regex and kills the task.

Measured over the 201 kept run logs:

    "Task failed: expected string or bytes-like object, got 'list'"
        490 occurrences, in 136 of 201 runs (68%)

and in every sampled case the line immediately before it is

    [frontend] Condensing messages (len=NNN)

so the throw is on the condensation path. `_get_content` is annotated `-> str` and
its docstring says "Get content from message", but it hands back
``msg["content"]`` verbatim — and for a multimodal message that is the OpenAI
content-block LIST, ``[{"type": "text", "text": ...}, {"type": "image_url", ...}]``.

Two callers then run a regex straight over it:

    for m in re.finditer(r"NEXT to implement:\\s*(.+)", content)
    for match in re.finditer(r'[\\w/.-]+\\.(jsx?|tsx?|py|sql|json|md)', content)

TypeError, caught by the task handler in messaging.py, logged as "Task failed",
and the agent's whole task is abandoned — on 68% of runs.

Both classes that define `_get_content` (MessageImportanceScorer and
SmartMessageCompressor) have the identical body, so both are fixed and both are
tested here. Flattening keeps the text parts and drops the non-text blocks, which
is what every consumer here wants: they scan prose for paths, decisions and
"NEXT to implement" markers.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from memory.generator_memory import (  # noqa: E402
    MessageImportanceScorer, SmartMessageCompressor,
)

_MULTIMODAL = [
    {"type": "text", "text": "NEXT to implement: src/pages/Feed.jsx"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    {"type": "text", "text": "and app/backend/main.py"},
]


def _instances():
    for cls in (MessageImportanceScorer, SmartMessageCompressor):
        try:
            yield cls.__name__, cls()
        except TypeError:
            yield cls.__name__, cls.__new__(cls)


class ContentIsAlwaysAString(unittest.TestCase):

    def test_a_list_content_is_flattened(self):
        for name, obj in _instances():
            got = obj._get_content({"role": "assistant", "content": _MULTIMODAL})
            self.assertIsInstance(got, str, name)
            self.assertIn("NEXT to implement", got, name)
            self.assertIn("app/backend/main.py", got, name)

    def test_the_flattened_text_survives_a_regex(self):
        """The exact call shape that was throwing."""
        for name, obj in _instances():
            content = obj._get_content({"content": _MULTIMODAL})
            hits = [m.group() for m in
                    re.finditer(r'[\w/.-]+\.(jsx?|tsx?|py|sql|json|md)', content)]
            self.assertIn("src/pages/Feed.jsx", hits, name)
            self.assertIn("app/backend/main.py", hits, name)

    def test_a_plain_string_is_unchanged(self):
        for name, obj in _instances():
            self.assertEqual(obj._get_content({"content": "hello"}), "hello", name)

    def test_missing_and_none_content_stay_empty(self):
        for name, obj in _instances():
            self.assertEqual(obj._get_content({}), "", name)
            self.assertEqual(obj._get_content({"content": None}), "", name)

    def test_an_object_with_list_content_is_flattened_too(self):
        class _Msg:
            content = _MULTIMODAL
        for name, obj in _instances():
            got = obj._get_content(_Msg())
            self.assertIsInstance(got, str, name)
            self.assertIn("NEXT to implement", got, name)

    def test_unknown_block_shapes_do_not_raise(self):
        weird = [{"type": "image_url"}, {"no_text": 1}, "bare string", 42]
        for name, obj in _instances():
            got = obj._get_content({"content": weird})
            self.assertIsInstance(got, str, name)


if __name__ == "__main__":
    unittest.main()
