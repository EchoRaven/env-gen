"""#1080 — the projected pages render `F Y P Feed` as a heading.

r81's `src/pages/FYPFeed.jsx`, header line `// framework-projected page
(reference-structured)`, verbatim:

    <h2 className="mb-4 text-xl font-semibold">F Y P Feed</h2>
    <h3 className="mb-3 text-sm font-semibold opacity-80">F Y P Feed</h3>

Eight sites in `frontend_scaffold.py` derive a HUMAN-VISIBLE label from a PascalCase
component name with `re.sub(r"(?<!^)(?=[A-Z])", " ", name)` — split before EVERY capital —
across `_stub_page_component`, `_auth_page_src_540`, `wire_owned_list_shell_535`,
`_render_reference_page` and `_project_page_component`. It is the same defect as #1079 one
layer out: there it mangled the page ID, here it mangles the words the user reads. The label
is a heading, an app name and a nav item, so the app ships with its main screen titled with
the letters spaced out.

Same two-boundary rule as #1079 (lower/digit→Upper, and Upper→Upper+lower which ends an
acronym run), extracted to one helper because the identical expression appeared eight times —
the reason all eight drifted from the acronym-safe form the rest of the package uses.
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

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402


class TheHelperKeepsAcronymsWhole(unittest.TestCase):

    def test_the_corpus_components(self):
        self.assertEqual(fs._label_words_1080("FYPFeedPage"), "FYP Feed Page")
        self.assertEqual(fs._label_words_1080("FYPFeed"), "FYP Feed")
        self.assertEqual(fs._label_words_1080("DMInboxPage"), "DM Inbox Page")

    def test_ordinary_pascal_case_is_unchanged(self):
        self.assertEqual(fs._label_words_1080("LoginPage"), "Login Page")
        self.assertEqual(fs._label_words_1080("CommentsPanelPage"), "Comments Panel Page")
        self.assertEqual(fs._label_words_1080("Profile"), "Profile")

    def test_all_caps_and_edges(self):
        self.assertEqual(fs._label_words_1080("FAQ"), "FAQ")
        self.assertEqual(fs._label_words_1080(""), "")
        self.assertEqual(fs._label_words_1080(None), "")


class TheRenderedLabelReadsCorrectly(unittest.TestCase):

    def test_the_stub_page_heading(self):
        src = fs._stub_page_component("FYPFeedPage")
        self.assertIn("FYP Feed", src)
        self.assertNotIn("F Y P", src)

    def test_the_projected_page_heading(self):
        src = fs._project_page_component("FYPFeed", {"name": "fyp_feed", "route": "/"})
        self.assertNotIn("F Y P", src)

    def test_an_ordinary_page_is_unaffected(self):
        src = fs._stub_page_component("LoginPage")
        self.assertIn("Login", src)


class NoSiteKeepsTheNaiveSplit(unittest.TestCase):
    """Eight copies is how they drifted; a ratchet is how they stay converged."""

    def test_the_naive_pattern_is_gone_from_the_scaffold(self):
        src = Path(fs.__file__).read_text(encoding="utf-8")
        # the pattern may still be NAMED in a comment; only a live re.sub call counts
        live = [m for m in re.findall(r're\.sub\(r"\(\?<!\^\)\(\?=\[A-Z\]\)"[^\n]*', src)]
        self.assertEqual(live, [], f"naive camel split still live at {len(live)} site(s)")


if __name__ == "__main__":
    unittest.main()
