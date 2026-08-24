"""#1079 — `_ui_snake` splits an ACRONYM letter by letter, defeating the case-dedup it exists
for and renaming the app's main screen out of every downstream match.

    FYPFeedPage  ->  f_y_p_feed_page      (should be fyp_feed_page)
    FYPFeed      ->  f_y_p_feed
    DMInboxPage  ->  d_m_inbox_page

The regex is `(?<!^)(?=[A-Z])`, which splits before EVERY capital. Every other camel→snake
site in the package already uses the acronym-safe form `(?<=[a-z0-9])(?=[A-Z])`
(completeness_audit.py:191, control_exercise.py:50, frontend_audit.py:1348, …) — this one is
the odd one out, and it is the one that mints the PAGE ID.

Two measured consequences on the 67-run corpus:

1. **Its own purpose is defeated.** The docstring says *"PascalCase component name → snake
   page id (round 38 case-dup fix)"* — one page, one id, however it is spelled. Three runs
   (r81, r89, r90) carry BOTH `fyp_feed` AND `f_y_p_feed` as separate ui_page records: two
   records for one page, which is the duplication round 38 built this to prevent.

2. **The main screen reads as an untested critical flow.** The page id is the requirement key
   `flow_coverage` demands a `validation:ui_flow` record for. Across 45 runs `f_y_p_feed` is
   the single largest requirement with no matching record (11 occurrences) — while the
   verifier's record is named `fyp_feed`, which can never meet it. For a TikTok clone that is
   the For-You feed: the primary screen, reported missing on an app that has it.

17 page ids in the corpus carry the mangled shape (3 distinct), from 4 acronym components
(FYPFeedPage ×10, FYPFeed ×6, FYPCommentsPage, DMInboxPage).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_snake = RegistryHub._ui_snake


class AnAcronymStaysOneWord(unittest.TestCase):

    def test_the_four_components_the_corpus_actually_carries(self):
        self.assertEqual(_snake("FYPFeedPage"), "fyp_feed_page")
        self.assertEqual(_snake("FYPFeed"), "fyp_feed")
        self.assertEqual(_snake("FYPCommentsPage"), "fyp_comments_page")
        self.assertEqual(_snake("DMInboxPage"), "dm_inbox_page")

    def test_an_all_caps_name_is_one_word(self):
        self.assertEqual(_snake("FAQ"), "faq")

    def test_a_trailing_acronym_too(self):
        self.assertEqual(_snake("UserDM"), "user_dm")


class OrdinaryPascalCaseIsUnchanged(unittest.TestCase):
    """The round-38 behaviour every other page depends on."""

    def test_the_common_shapes(self):
        self.assertEqual(_snake("LoginPage"), "login_page")
        self.assertEqual(_snake("HomePage"), "home_page")
        self.assertEqual(_snake("Profile"), "profile")
        self.assertEqual(_snake("CommentsPanelPage"), "comments_panel_page")

    def test_an_already_snake_name_is_returned_as_is(self):
        self.assertEqual(_snake("fyp_feed"), "fyp_feed")
        self.assertEqual(_snake("comments_panel"), "comments_panel")

    def test_empty_and_none(self):
        self.assertEqual(_snake(""), "")
        self.assertEqual(_snake(None), "")


class TheCaseDedupItExistsForActuallyWorks(unittest.TestCase):
    """r81/r89/r90 each carry both spellings as SEPARATE records. One page, one record."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ui_snake_1079_"))
        self.rh = RegistryHub(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_record_id_is_the_acronym_safe_snake(self):
        """Pin the ID itself. The obvious end-to-end phrasing — register both spellings and
        count records — passes TODAY for an unrelated reason: both carry route `/`, so #593's
        route dedup aliases the second onto the first and the name collision never shows. The
        id is the thing every downstream consumer keys off, so assert the id."""
        self.rh.register_ui_page(name="FYPFeedPage", route="/", component="FYPFeedPage",
                                 agent="frontend")
        pages = set(self.rh.list_ui_pages() or {})
        self.assertEqual(pages, {"fyp_feed_page"}, sorted(pages))

    def test_lookup_finds_the_page_under_either_spelling(self):
        self.rh.register_ui_page(name="fyp_feed", route="/", component="FYPFeed",
                                 agent="frontend")
        self.assertIsNotNone(self.rh.get_ui_page("FYPFeed"))
        self.assertIsNotNone(self.rh.get_ui_page("fyp_feed"))


if __name__ == "__main__":
    unittest.main()
