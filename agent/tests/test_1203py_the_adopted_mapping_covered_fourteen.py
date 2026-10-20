r"""#1203py: the adopted design_system mapped 14 of 34 staged icons, and nothing said so.

`frontend_audit.audit_asset_usage` is the check that tells a lane "you drew an approximation
instead of using the real asset". It keys on `screens[].components[].assets` ids, so it can
only police assets the design_system MAPPED -- and the mapping is the analyst's work
(`"assets": []  # analyst maps real assets here`). `#1202hj` adopts a donor run's enriched
design_system and SKIPS the analyst spawn, which is right for everything the donor measured
and leaves everything staged since then mapped to nothing.

THE CHAIN, measured end to end on r185/r189/r190/r191:

    reference materials stage        34-36 icons per run
    design-prep ADOPTS a donor ds    r191's log: "adopting the ENRICHED design_system.json
                                     measured by tiktok-web-r190 ... skipping the
                                     design_analyst spawn"
    the ds maps                      23 assets, of which 14 are staged icons
    STAGED BUT UNMAPPED              20-22 icons + all 24 images
    audit_asset_usage sees           only the mapped ones -- structurally blind to the rest
    nothing anywhere compares        staged vs mapped
    the judge then scores            iconography 0.348 at FIRST render (color 0.610), and it
                                     gains an ordinary +0.137 afterwards, so the deficit is in
                                     what the first render was given

A SET DIFFERENCE on basenames, deliberately. `#1202uw`'s docstring warns off the name-matching
route ("a NAME-based attempt ... ran at 32% and both samples I checked were false"), and the
reverse -- pairing an icon FILENAME with a control's accessible label -- measured 0% recall
here. The design_system already carries the structural join, so nothing needs guessing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.design_prep import (  # noqa: E402
    _CHROME_ASSET_KINDS_1203PY as KINDS,
    staged_assets_not_mapped_1203py as F,
)


def _tree(staged, mapped):
    """staged: {kind: [names]}; mapped: [relative file paths in the design_system]."""
    out = Path(tempfile.mkdtemp(prefix="py1203_"))
    for kind, names in staged.items():
        d = out / "design" / "assets" / kind
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_text("x", encoding="utf-8")
    # `load_valid_design_system` requires `design_system` or `screens` to be TRUTHY -- an
    # empty `screens: []` is rejected as a non-design shape, which is correct and is what the
    # first version of this fixture got wrong.
    ds = {"screens": [{"name": "s1", "components": []}],
          "assets": [{"id": f.replace("/", "-"), "file": f} for f in mapped]}
    dsp = out / "design" / "design_system.json"
    dsp.parent.mkdir(parents=True, exist_ok=True)
    dsp.write_text(json.dumps(ds), encoding="utf-8")
    return out


class ItNamesWhatTheMappingMissed(unittest.TestCase):

    def test_r191s_shape(self):
        """★ THE TICKET: two icons mapped, two not."""
        t = _tree({"icons": ["a.svg", "b.svg", "c.svg", "d.svg"]},
                  ["icons/a.svg", "icons/b.svg"])
        self.assertEqual(F(t), {"icons": ["c.svg", "d.svg"]})

    def test_a_fully_mapped_kind_is_not_reported(self):
        """#983: a check that fires while naming nothing."""
        t = _tree({"icons": ["a.svg"]}, ["icons/a.svg"])
        self.assertEqual(F(t), {})

    def test_a_kind_the_ds_maps_NOTHING_under_is_reported_whole(self):
        """r185/r191 both stage 24 images and the design_system maps none of them."""
        t = _tree({"images": ["x.png", "y.png"]}, ["icons/a.svg"])
        self.assertEqual(F(t), {"images": ["x.png", "y.png"]})

    def test_the_match_is_on_BASENAME_not_the_path(self):
        """The ds records `icons/a.svg` while the file is found by walking; a path-equality
        test would report every mapped asset as unmapped."""
        t = _tree({"icons": ["a.svg"]}, ["design/assets/icons/a.svg"])
        self.assertEqual(F(t), {})

    def test_an_explicit_design_system_overrides_the_one_on_disk(self):
        t = _tree({"icons": ["a.svg"]}, [])
        self.assertEqual(F(t), {"icons": ["a.svg"]})
        self.assertEqual(F(t, design_system={"assets": [{"file": "icons/a.svg"}]}), {})


class ItIsScopedToChromeKinds(unittest.TestCase):
    """#647: the seed-data kinds are unmapped as their NORMAL state -- the design_system's one
    video entry points at `backend/dataset/videos.json` and the rows reach the app through the
    seed. Counting them would swamp 20 real icons with 69 videos."""

    def test_seed_data_kinds_are_not_counted(self):
        t = _tree({"real_videos": ["v%d.mp4" % i for i in range(5)],
                   "real_avatars": ["a1.png", "a2.png"]}, [])
        self.assertEqual(F(t), {})

    def test_the_kind_list_is_the_measured_one(self):
        self.assertEqual(tuple(KINDS), ("icons", "images", "fonts"))

    def test_icons_are_still_counted_beside_an_ignored_kind(self):
        """The control: a tree with both must report the icons and ignore the videos."""
        t = _tree({"icons": ["i.svg"], "real_videos": ["v.mp4"]}, [])
        self.assertEqual(F(t), {"icons": ["i.svg"]})


class ItNeverRaises(unittest.TestCase):

    def test_a_missing_tree_is_empty(self):
        self.assertEqual(F("/nonexistent/1203py"), {})

    def test_junk_is_empty(self):
        for bad in (None, 0, object(), ""):
            self.assertEqual(F(bad), {})

    def test_no_design_system_reports_everything_staged(self):
        """With no mapping on disk at all, nothing IS mapped, so naming every staged asset is
        the true answer rather than an alarm. The caller only runs this immediately after an
        adoption that already loaded and validated a donor design_system, so an unreadable one
        there is itself an anomaly worth a line."""
        out = Path(tempfile.mkdtemp(prefix="py1203b_"))
        d = out / "design" / "assets" / "icons"
        d.mkdir(parents=True)
        (d / "a.svg").write_text("x", encoding="utf-8")
        self.assertEqual(F(out), {"icons": ["a.svg"]})


if __name__ == "__main__":
    unittest.main()
