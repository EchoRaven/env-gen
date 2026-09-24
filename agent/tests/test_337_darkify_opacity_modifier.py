"""#337: the darkify pass eats Tailwind opacity modifiers.

`_DARKIFY_RE`'s trailing lookahead is `(?![\\w-])`, which does not exclude `/`
or `[`. So `bg-white/15` matches as `bg-white` and becomes `bg-zinc-950/15`:
a translucent-white overlay on a dark surface -- the correct, reference-accurate
treatment -- is turned into a near-invisible dark-on-dark overlay.

Measured in the delivered apps: `zinc-*/<opacity>` (the darkify output) appears
35 / 69 / 34 times in r91 / r92 / r93, while surviving `bg-white/<opacity>` is
0 in all three. Every translucent-white overlay the lane authored was
destroyed. (`text-white/<opacity>` survives -- 84 in r92 -- because it is not a
darkify target, which is why the damage is specific to backgrounds.)

It also drives an oscillation: the merge resolver hands component files back to
the lane, the lane re-authors `bg-white/15`, darkify re-converts it. r93
`VideoPlayer.jsx` has 22 changes across only 2 distinct blobs -- 20 revisits --
and the only difference between the two states is `- bg-white/15` / `+
bg-zinc-950/15`.

This test pins the regex boundary only. Whether darkify should run at all on
lane-owned files is a separate, riskier question (#209 fixed a real fidelity
wedge where a lane shipped a light page for a dark reference).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _darkify(text):
    from multi_agent.runtime.frontend_scaffold import darkify_light_utilities
    return darkify_light_utilities(text)


class OpacityModifiersAreLeftAlone(unittest.TestCase):

    def test_slash_opacity_is_not_darkified(self):
        out, n = _darkify("bg-white/15")
        self.assertEqual(out, "bg-white/15")
        self.assertEqual(n, 0)

    def test_arbitrary_opacity_is_not_darkified(self):
        out, n = _darkify("bg-white/[0.12]")
        self.assertEqual(out, "bg-white/[0.12]")
        self.assertEqual(n, 0)

    def test_a_real_jsx_overlay_survives(self):
        src = '<div className="absolute inset-0 bg-white/10 rounded-full" />'
        out, n = _darkify(src)
        self.assertEqual(out, src)
        self.assertEqual(n, 0)


class OpaqueLightUtilitiesAreStillDarkified(unittest.TestCase):
    """#209 must keep working — this narrows the match, it does not disable it."""

    def test_bare_bg_white_still_converts(self):
        out, n = _darkify("bg-white")
        self.assertNotEqual(out, "bg-white")
        self.assertEqual(n, 1)

    def test_light_neutral_text_still_converts(self):
        out, n = _darkify("text-zinc-900")
        self.assertNotEqual(out, "text-zinc-900")
        self.assertEqual(n, 1)

    def test_mixed_line_converts_only_the_opaque_one(self):
        out, n = _darkify('className="bg-white text-zinc-900 ring-white/20"')
        self.assertIn("ring-white/20", out)
        self.assertNotIn("bg-white ", out)
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
