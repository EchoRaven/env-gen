r"""#1203mq: #842 reported `logo` unstaged 30 times while the wordmark was on disk.

`#842` decides whether a spec-requested asset class was staged by looking at the DIRECTORY
NAMES under `design/assets/`. Its own docstring records the false positive that caused:

    "an earlier cut also reported `logo`, which was a false positive
     (the wordmark is staged under `brand/`)"

That fix was a directory name, so it expired the moment a product staged the wordmark
elsewhere. r186-r190 all stage it as `icons/go-to-tiktok-for-you-feed_50508994.svg`, whose
own manifest record reads

    "description": "TikTok wordmark/music-note brand asset, dominant measured colors ..."
    "use":         ["expanded sidebar logo"]

so `logo` was reported unstaged while the brand mark sat on disk, measured and described.
MEASURED over 33 modern runs: 38 reports, 30 of them `logo`, and ALL 30 are this. It matters
because #842's stated consequence is that the lane "has nothing to point at, so it
substitutes whatever is nearest" — which is also one of the standing explanations for the
iconography floor.

★★★ WHY THE IDENTITY WORDS ARE NARROW, and how I found out. Matching the class word anywhere
in an asset's record rescues assets that merely MENTION it. instagram-r174/5/6 stage
`icons/Audio_is_muted_8a16b7d5.svg` with `use: ["reels video card mute state"]` and
`description: "Muted audio glyph displayed on reel video."` — "video" there is a modifier
saying where the glyph sits, and that run's `video` report is CORRECT: its spec asks for
"centered vertical 9:16 reel video" and no video is staged. My first two cuts both rescued
it, and reading the actual records is what caught them. The words kept name an asset's own
IDENTITY (`wordmark`, `brand asset`), which splits the corpus exactly:

    logo       30 of 30 reports refuted        avatar    0 of 3
    video       0 of 3                         backdrop  0 of 2

`video` and `icon` are deliberately EMPTY (#647): no word names "a video asset" the way
`wordmark` names a logo, and inventing one would re-create the defect in the other
direction.
"""
import json
import os
import tempfile
import unittest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ASSET_CLASS_IDENTITY_1203MQ,
    _asset_says_it_is_1203mq,
    _unstaged_asset_classes_842,
)

# the real r189 record, verbatim
WORDMARK = {
    "id": "go-to-tiktok-for-you-feed-50508994",
    "file": "icons/go-to-tiktok-for-you-feed_50508994.svg",
    "type": "svg",
    "use": ["expanded sidebar logo"],
    "description": ("TikTok wordmark/music-note brand asset, dominant measured colors "
                    "#25f4ee and #fe2c55"),
}
# the real instagram-r176 record that must NOT rescue `video`
MUTE_GLYPH = {
    "id": "audio-is-muted-8a16b7d5",
    "file": "icons/Audio_is_muted_8a16b7d5.svg",
    "type": None,
    "use": ["reels video card mute state"],
    "description": "Muted audio glyph displayed on reel video.",
}


def _run(tmp, must_have, asset_dirs, assets):
    os.makedirs(os.path.join(tmp, "design", "assets"))
    for d in asset_dirs:
        os.makedirs(os.path.join(tmp, "design", "assets", d), exist_ok=True)
    with open(os.path.join(tmp, "design", "reference_spec.json"), "w") as fh:
        json.dump({"screens": [{"name": "s1", "must_have": must_have}]}, fh)
    with open(os.path.join(tmp, "design", "design_system.json"), "w") as fh:
        json.dump({"assets": assets}, fh)
    return tmp


class TheAssetsOwnRecordCounts(unittest.TestCase):
    def test_the_wordmark_in_icons_satisfies_logo(self):
        """The regression: no `brand/` dir, wordmark staged under `icons/`."""
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["expanded sidebar logo"], ["icons", "fonts"], [WORDMARK])
            self.assertEqual(_unstaged_asset_classes_842(t), [])

    def test_a_brand_directory_still_satisfies_logo(self):
        """#842's original path must keep working."""
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["expanded sidebar logo"], ["brand", "icons"], [])
            self.assertEqual(_unstaged_asset_classes_842(t), [])

    def test_a_truly_missing_logo_is_still_reported(self):
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["expanded sidebar logo"], ["icons", "fonts"], [MUTE_GLYPH])
            self.assertEqual(_unstaged_asset_classes_842(t),
                             ["logo (asked by s1)"])

    def test_it_names_which_asset_satisfied_the_class(self):
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["logo"], ["icons"], [WORDMARK])
            self.assertIn("go-to-tiktok", _asset_says_it_is_1203mq(t, "logo"))


class AModifierIsNotAnIdentity(unittest.TestCase):
    def test_the_mute_glyph_does_not_rescue_video(self):
        """instagram-r174/5/6, verbatim: `use: ["reels video card mute state"]` and a
        description mentioning "reel video". That run's `video` report is CORRECT."""
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["centered vertical 9:16 reel video"], ["icons"], [MUTE_GLYPH])
            self.assertEqual(_unstaged_asset_classes_842(t),
                             ["video (asked by s1)"])
        self.assertEqual(_asset_says_it_is_1203mq(t, "video"), "")

    def test_video_and_icon_have_no_identity_words(self):
        """#647: no word names "a video asset" the way `wordmark` names a logo, so guessing
        one would re-create the defect in the other direction."""
        self.assertEqual(_ASSET_CLASS_IDENTITY_1203MQ["video"], ())
        self.assertEqual(_ASSET_CLASS_IDENTITY_1203MQ["icon"], ())

    def test_an_avatar_asset_rescues_avatar_but_a_mention_does_not(self):
        real = {"id": "a1", "file": "people/a1.png", "use": ["profile avatar"],
                "description": "Member avatar photograph"}
        mention = {"id": "b1", "file": "icons/edit.svg", "use": ["edit button"],
                   "description": "Pencil glyph shown beside the user name"}
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["profile avatars grid"], ["icons"], [real])
            self.assertEqual(_unstaged_asset_classes_842(t), [])
        with tempfile.TemporaryDirectory() as t2:
            _run(t2, ["profile avatars grid"], ["icons"], [mention])
            self.assertEqual(_unstaged_asset_classes_842(t2),
                             ["avatar (asked by s1)"])


class ItStaysTotalAndReportOnly(unittest.TestCase):
    def test_no_manifest_means_no_rescue_not_a_crash(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "design", "assets", "icons"))
            with open(os.path.join(t, "design", "reference_spec.json"), "w") as fh:
                json.dump({"screens": [{"name": "s1", "must_have": ["logo"]}]}, fh)
            self.assertEqual(_unstaged_asset_classes_842(t), ["logo (asked by s1)"])

    def test_the_helper_never_raises(self):
        for bad in (None, "/nonexistent/zz", 7, object()):
            self.assertEqual(_asset_says_it_is_1203mq(bad, "logo"), "")
        self.assertEqual(_asset_says_it_is_1203mq("/tmp", "nosuchclass"), "")

    def test_a_class_nobody_asked_for_is_not_reported(self):
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["a plain list of names"], ["icons"], [])
            self.assertEqual(_unstaged_asset_classes_842(t), [])


if __name__ == "__main__":
    unittest.main()


class TheNarrowWordsAreTheSaferGuessNotEvidence(unittest.TestCase):
    """What the corpus can and cannot show, pinned so the next reader does not over-trust it.

    The `video` narrowing IS in the data: instagram-r174/5/6's mute glyph is a real asset
    that mentions "video" and must not rescue it, and `AModifierIsNotAnIdentity` uses that
    record verbatim.

    The `logo` narrowing is NOT. Across 33 modern runs, assets mentioning "logo" WITHOUT
    also saying wordmark/brand asset number **zero**, so `("wordmark", "brand asset", ...)`
    and the plain `("logo",)` are indistinguishable on today's evidence. The narrow form is
    kept because it can only UNDER-rescue — which makes #842 report more, i.e. the status quo
    — and that asymmetry, not a measurement, is the argument. Mutation MQ3 widens it and
    survives on purpose.

    The fixture below is CONSTRUCTED, and labelled as such: it is a guard against a shape the
    corpus has not produced yet, not a reproduction of one it has.
    """

    CONSTRUCTED_MENTION = {
        "id": "nav-divider",
        "file": "icons/nav_divider.svg",
        "use": ["hairline shown to the right of the logo"],
        "description": "1px vertical rule separating the logo from the nav items",
    }

    def test_the_identity_words_do_not_match_a_constructed_mention(self):
        self.assertEqual(
            _asset_says_it_is_1203mq.__doc__ is None, False,
            "the helper lost its docstring, which carries why the words are narrow")
        with tempfile.TemporaryDirectory() as t:
            _run(t, ["expanded sidebar logo"], ["icons"], [self.CONSTRUCTED_MENTION])
            self.assertEqual(
                _unstaged_asset_classes_842(t), ["logo (asked by s1)"],
                "a constructed asset that only MENTIONS the logo rescued the class")

    def test_the_code_records_that_the_corpus_cannot_discriminate(self):
        """#1203l2's rule: write the known imperfection down instead of hiding it behind a
        word list that looks measured."""
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import delivery_gate as DG
        src = " ".join(inspect.getsource(DG).split())
        self.assertIn("TODAY'S CORPUS CANNOT TELL", src)
        self.assertIn("safer guess", src)


class ACouldNotTellIsAnnounced(unittest.TestCase):
    """#1202ah caught the first cut returning "" on a crash with nothing said.

    The direction was already safe — "" falls through to reporting the class, which is #842's
    pre-patch behaviour — but that is the argument the ratchet exists to stop anyone making
    silently, and "could not read the manifest" must not look like "no asset matched".
    """

    def test_the_crash_path_announces(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import delivery_gate as DG
        fn = next((n for n in ast.walk(ast.parse(inspect.getsource(DG)))
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_asset_says_it_is_1203mq"), None)
        self.assertIsNotNone(fn, "the helper is gone")
        handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
        self.assertTrue(handlers, "nothing catches any more")
        for h in handlers:
            names = {c.func.id for c in ast.walk(h)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            self.assertIn(
                "warn_once_1201", names,
                "the crash path returns a value without announcing, so a failed read looks "
                "exactly like a clean miss (#1202ah)")

    def test_an_unreadable_manifest_still_reports_the_class(self):
        """The safe direction, pinned: could-not-tell must fall through to #842 reporting."""
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "design", "assets", "icons"))
            with open(os.path.join(t, "design", "reference_spec.json"), "w") as fh:
                json.dump({"screens": [{"name": "s1", "must_have": ["logo"]}]}, fh)
            with open(os.path.join(t, "design", "design_system.json"), "w") as fh:
                fh.write("{ this is not json")
            self.assertEqual(_unstaged_asset_classes_842(t), ["logo (asked by s1)"])
