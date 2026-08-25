"""#1091 — 80% of the screens reported as "never captured, never scored" ARE captured.

Live in r95, design-prep's first warning:

    the reference SPEC declares 11 screen(s) with no reference image, so they are absent from
    design_system.json and the visual gate will never capture, score or block on them:
    ['activity', 'explore', 'following', 'friends', 'fyp_feed', 'fyp_feed_comments',
     'messages', 'profile', 'settings_more', 'signup_modal', 'upload']

The reference directory in that same run holds `explore_grid.png`,
`following_suggested_creators.png`, `fyp_feed_logged_out.png`, `notifications_activity.png`,
`profile_own.png`, `messages_dm_empty.png`, `settings_more_menu.png` … The screens ARE
photographed; `design_system.json` builds each screen's name from the image STEM, so they are
captured, scored and blocked on under the filename's fuller name. Only `signup_modal` and
`upload` were genuinely uncovered.

Both #822's warning and #823's `_imageless_spec_screens_unreachable_823` decide coverage with
`name in image_stems` — exact string equality between two vocabularies that name the same
screens differently. Measured over the 76 corpus runs carrying both a spec and a reference
dir: of the **576** screens reported imageless, **461 (80%) have an image whose stem contains
the screen's name as a contiguous run of underscore tokens**; only 115 truly have none
(`signup` 33, `fyp_comments` 20, `upload` 15).

That is the same failure #823's own docstring says it removed from the other side — *"two
earlier attempts … reported screens that ARE built, because the spec's names and the app's
route vocabulary differ"*. The vocabulary gap is on the IMAGE side too.

Token-contiguous, not substring: `search` must not be satisfied by `research_page`. Narrowing
only — #823 is REPORTED, not enforced, and #822 is a log line, so nothing that blocks changes;
what changes is that neither states a gap that is not there.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _imageless_spec_screens_unreachable_823)
from multi_agent.runtime.design_prep import (  # noqa: E402
    spec_screen_has_reference_image_1091)

_R95_STEMS = {"explore_grid", "following_suggested_creators", "friends_suggested_creators",
              "fyp_feed_comments_panel", "fyp_feed_logged_out", "live_discover",
              "login_modal", "messages_dm_empty", "notifications_activity",
              "profile_own", "settings_more_menu"}


class TheR95Screens(unittest.TestCase):

    def test_the_nine_that_are_actually_photographed(self):
        for name in ("explore", "following", "friends", "fyp_feed", "fyp_feed_comments",
                     "messages", "profile", "settings_more", "activity"):
            self.assertTrue(spec_screen_has_reference_image_1091(name, _R95_STEMS),
                            f"{name} was reported as never captured")

    def test_the_two_that_really_have_none(self):
        for name in ("upload", "signup_modal"):
            self.assertFalse(spec_screen_has_reference_image_1091(name, _R95_STEMS), name)


class TheMatchIsTokenContiguousNotSubstring(unittest.TestCase):

    def test_an_exact_name_still_matches(self):
        self.assertTrue(spec_screen_has_reference_image_1091("login_modal", _R95_STEMS))

    def test_a_word_fragment_does_not_match(self):
        self.assertFalse(spec_screen_has_reference_image_1091("search", {"research_page"}))
        self.assertFalse(spec_screen_has_reference_image_1091("list", {"playlist_grid"}))

    def test_tokens_must_be_adjacent_and_in_order(self):
        self.assertTrue(spec_screen_has_reference_image_1091("fyp_feed", {"fyp_feed_x"}))
        self.assertFalse(spec_screen_has_reference_image_1091("fyp_feed", {"fyp_x_feed"}))
        self.assertFalse(spec_screen_has_reference_image_1091("feed_fyp", {"fyp_feed_x"}))

    def test_empty_inputs_are_safe(self):
        self.assertFalse(spec_screen_has_reference_image_1091("", _R95_STEMS))
        self.assertFalse(spec_screen_has_reference_image_1091("explore", set()))


class TheUnreachableCheckUsesIt(unittest.TestCase):
    """#823 starts from the same set, so it inherited the same inflation."""

    def _tree(self, screens, stems, app_routes) -> Path:
        root = Path(mkdtemp())
        d = root / "design"
        (d / "references").mkdir(parents=True)
        for s in stems:
            (d / "references" / f"{s}.png").write_bytes(b"\x89PNG")
        (d / "reference_spec.json").write_text(
            json.dumps({"screens": [{"name": n, "route_hint": "/" + n} for n in screens]}),
            encoding="utf-8")
        src = root / "app" / "frontend" / "src"
        src.mkdir(parents=True)
        (src / "App.jsx").write_text(
            "".join(f'<Route path="{r}" element={{<X/>}} />' for r in app_routes),
            encoding="utf-8")
        return root

    def test_a_qualified_image_no_longer_reads_as_unreachable(self):
        root = self._tree(["explore"], ["explore_grid"], ["/"])
        self.assertEqual(_imageless_spec_screens_unreachable_823(root), [])

    def test_a_genuinely_imageless_unreachable_screen_still_reports(self):
        root = self._tree(["upload"], ["explore_grid"], ["/"])
        out = _imageless_spec_screens_unreachable_823(root)
        self.assertTrue([x for x in out if x.startswith("upload")], out)

    def test_a_genuinely_imageless_but_REACHABLE_screen_stays_silent(self):
        root = self._tree(["upload"], ["explore_grid"], ["/upload"])
        self.assertEqual(_imageless_spec_screens_unreachable_823(root), [])


if __name__ == "__main__":
    unittest.main()
