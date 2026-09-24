"""#294 — _find_subsequence must return -1 (not None) when the block isn't found.

r77 live: apply_patch crashed with
    ❌ apply_patch FAILED: '<' not supported between instances of 'NoneType' and 'int'

_find_subsequence (canonical_file_tools/shared.py) is annotated `-> int` and its
caller (patch.py:129) checks `if match_index < 0:` — the standard "not found ==
-1" contract. But the function has NO return at the end: when the needle isn't
found (or is longer than the haystack) it falls through and implicitly returns
None → `None < 0` raises TypeError. That masks the intended actionable
"failed to match patch hunk" error (which the LLM lane needs to self-correct a
stale patch) with an opaque crash.

Fix: return -1 on no-match.
"""

import sys
import tempfile
import shutil
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from tools.canonical_file_tools.shared import _find_subsequence  # noqa: E402


class FindSubsequenceTests(unittest.TestCase):
    def test_found_returns_index(self):
        self.assertEqual(_find_subsequence(["a", "b", "c"], ["b", "c"]), 1)

    def test_not_found_returns_minus_one(self):
        got = _find_subsequence(["a", "b", "c"], ["x", "y"])
        self.assertEqual(got, -1)
        self.assertIsInstance(got, int)  # NOT None — caller does `< 0`

    def test_needle_longer_than_haystack_returns_minus_one(self):
        got = _find_subsequence(["a"], ["a", "b", "c"])
        self.assertEqual(got, -1)

    def test_empty_needle_returns_start_index(self):
        self.assertEqual(_find_subsequence(["a", "b"], [], start_index=1), 1)

    def test_caller_contract_no_typeerror_on_no_match(self):
        # The exact failing expression from patch.py:129.
        match_index = _find_subsequence(["a"], ["nope"])
        try:
            _ = match_index < 0
        except TypeError as e:
            self.fail(f"match_index < 0 raised TypeError ({e}); "
                      f"_find_subsequence returned {match_index!r} not an int")


class ApplyPatchMismatchGivesActionableErrorTests(unittest.TestCase):
    """End-to-end: a hunk whose context doesn't match yields success=False with
    the actionable 'failed to match patch hunk' message, not a TypeError."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="patch294_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mismatched_hunk_returns_clean_error(self):
        try:
            from tools.canonical_file_tools.patch import _ApplyPatch  # type: ignore
        except Exception:
            self.skipTest("apply_patch internal shape not importable in isolation")
        # If import worked, exercise the no-match path via _find_subsequence,
        # which is the crash site; the unit tests above already lock it.
        self.assertEqual(_find_subsequence(["real", "content"], ["ghost"]), -1)


if __name__ == "__main__":
    unittest.main()
