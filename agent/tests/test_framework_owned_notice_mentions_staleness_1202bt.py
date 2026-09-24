r"""#1202bt: a framework-owned file you cannot edit is also one you cannot see updated.

netflix-r34, watched live. The framework had already regenerated pyproject.toml without
the spurious `custom` dependency and integration carried the fix; the backend lane's
worktree was 5 commits behind and still had it:

    lane worktree line 13:   "custom",
    integration  line 13:    "psycopg2-binary",
    lane HEAD: da3452e (its own fix) — does NOT contain 12a5966, the commit that removed it

The lane then spent three claimed P0 tasks reporting a framework defect that was already
repaired upstream, and finally escalated with "cannot complete these tasks honestly" —
correct behaviour on incomplete information.

The #1144 notice told it the file is not its to edit. It did not tell it the copy might
be old, which is the other half of what "framework-owned" implies: the file changes
without you, and you only see it after you pull.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_READ = (THIS_DIR.parent / "env_generator" / "llm_generator" / "tools"
         / "canonical_file_tools" / "read.py")


def _notice():
    """The notice as the LANE receives it, not as the source spells it.

    Landmark-bounded (#943), then the source's string-concatenation seams are closed:
    the text is written across several adjacent literals, so `"... Merge "` and
    `"integration first ..."` are not contiguous on disk even though the lane reads one
    sentence. Asserting against the raw source failed on exactly that.
    """
    import re
    src = _READ.read_text(encoding="utf-8")
    i = src.index("FRAMEWORK-OWNED (#1144)")
    j = src.index("_notices_1144 = []", i)
    body = src[i:j]
    body = re.sub(r'"\s*(?:#[^\n]*\n\s*)*"', "", body)   # close literal seams + comments
    return re.sub(r"\s+", " ", body)


class NoticeMentionsStalenessTests(unittest.TestCase):
    def test_it_says_the_copy_may_be_stale(self):
        n = _notice()
        self.assertIn("behind integration", n)

    def test_it_names_the_action(self):
        """'Might be stale' without 'merge integration' is not actionable."""
        self.assertIn("Merge integration", _notice())

    def test_it_says_to_check_before_reporting(self):
        """The failure mode was reporting a framework defect that was already fixed."""
        self.assertIn("before reporting", _notice())

    def test_the_original_guidance_survives(self):
        """The notice's first job — where to author changes — must not be displaced."""
        n = _notice()
        self.assertIn("custom_routes.py", n)
        self.assertIn("src/pages/*.jsx", n)
        self.assertIn("discarded", n)


if __name__ == "__main__":
    unittest.main()
