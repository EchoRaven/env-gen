"""#1062 — #187's image prune fired 0 times in 12,487 opportunities, silently.

`_prune_stale_images_for_reroll` drops stale inline images from a retry payload on
a MALFORMED_FUNCTION_CALL re-roll, on the premise (#187) that "MALFORMED storms
correlate with huge MULTIMODAL contexts".

Measured over the 201 kept run logs:

    MALFORMED re-rolls at depth >= 2      12,487
    "pruned N stale inline image(s)"           0      in 0 of 201 logs

The premise does not describe where the storms are. Grouping the storm lines by
the agent that emitted them:

    orchestrator 6544 | verifier 3240 | frontend 3239 | backend 2184

— the text-only coding and coordination lanes, which carry no inline images to
drop. The visual judge and design analyst, the two roles whose payloads ARE
multimodal, are not in the list at all.

So the rung is inert exactly where it is invoked, the temperature rung is the only
one doing anything, and nothing said so: an unwatched grace is indistinguishable
from an absent one (#1047's rule, applied here). This does NOT change the retry
behaviour — it makes the no-op audible once per process, with the payload shape,
so the next run can answer what a rung that COULD help would have to key on.
"""
from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils import llm as _llm  # noqa: E402


class ThePremiseIsInertOnATextOnlyPayload(unittest.TestCase):
    """Why it never fires — the precondition, exercised directly."""

    def test_text_only_contents_prune_nothing(self):
        class _Part:
            def __init__(self, text): self.text, self.inline_data = text, None
        class _Content:
            def __init__(self, *texts): self.parts = [_Part(t) for t in texts]
        contents = [_Content("plan the milestone"), _Content("call a tool")]
        out, n = _llm._prune_stale_images_for_reroll(
            contents, 1, lambda t: _Part(t))
        self.assertEqual(n, 0, "a text-only payload has nothing to drop")
        self.assertIs(out, contents, "n == 0 must mean 'use the original'")


class TheNoOpIsAudibleAndBounded(unittest.TestCase):

    def test_the_latch_exists_and_is_one_shot(self):
        latch = getattr(_llm, "_MALFORMED_PRUNE_NOOP_1062", None)
        self.assertIsInstance(latch, dict)
        self.assertIn("said", latch)

    def test_the_branch_logs_when_the_prune_finds_nothing(self):
        src = inspect.getsource(_llm)
        i = src.index("_prune_stale_images_for_reroll(\n")
        # semantic end: the enclosing suite, not a byte count (the ratchet in
        # test_source_windows_do_not_grow_943 is why)
        j = src.find("\n            def _do_call", i)
        window = src[i:j if j != -1 else len(src)]
        self.assertIn("_MALFORMED_PRUNE_NOOP_1062", window,
                      "the no-op branch must record that it did nothing")
        self.assertIn("#1062", window)
        # and it must not spam a storm
        self.assertIn('["said"] = True', window)

    def test_it_does_not_change_the_retry_decision(self):
        """The note is additive: the un-pruned contents are still returned."""
        src = inspect.getsource(_llm)
        i = src.index("_MALFORMED_PRUNE_NOOP_1062[\"said\"]")
        j = src.find("\n            def _do_call", i)
        window = src[i:j if j != -1 else len(src)]
        self.assertIn("return contents", window,
                      "the inert path must still hand back the original payload")


if __name__ == "__main__":
    unittest.main()
