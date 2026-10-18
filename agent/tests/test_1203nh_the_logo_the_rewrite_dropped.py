r"""#1203nh: the design_analyst's rewrite drops the measured LOGO component, every run.

`#1203kv` states the event in this very file -- "The spawned design_analyst REWRITES
design_system.json wholesale ... So every MEASURED machine field is gone" -- and repaired the
ASSET half of it. The COMPONENT half was never repaired, and it is bigger.

MEASURED on the three newest runs, by rebuilding the deterministic skeleton from the
`component_specs` still on disk and diffing it against the delivered design_system.json:

    run              skeleton writes   on disk   of those, from the skeleton
    tiktok-web-r189        172            35              5
    tiktok-web-r190        175            35              6
    tiktok-web-r191        168            35              6

So ~80% of the measured components -- their exact regions, measured colors and geometry --
never reach a lane, and 29-30 of the 35 survivors are ids the analyst invented.

ONLY THE LOGO IS RESTORED, and the numbers say why:

  * `#842` ("the SPEC asks for asset class(es) design-prep never staged") fires in 85 corpus
    logs and the class is `logo` in 85 of 85 -- never anything else. Its own sentence names
    the consequence: "The lane has nothing to point at, so it substitutes whatever is
    nearest", which is how the iconography floor gets built.
  * Across 102 runs and 1413 screens, 760 (54%) carry a NAME-matched logo component in
    `component_specs`, median region area 0.37% of the screen (p90 1.1%) -- logo-sized, not
    a header that happens to contain one.
  * On r189/r190/r191 the specs measure 9, 9 and 8 of them and EXACTLY ZERO survive.
  * A blanket restore was measured and rejected: `complete_design_system` cuts a crop per
    component with a region, r191's 35 crops already cost 14 MB, and ~170 would be ~68 MB a
    run on a shared disk this project has filled twice. One per screen is ~11 crops, ~4.5 MB.

The detector is NAME-only on purpose. A first version also matched `role`, which pulled in
`top_navigation_bar`, `search_bar` and `left_sidebar` -- 77% of screens instead of 54% -- the
same too-wide logo predicate this project recorded after the last time it wrote one.
"""
import ast
import inspect
import json
import pathlib
import re
import unittest

from env_generator.llm_generator.multi_agent.runtime import design_prep as DP
from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _LOGO_COMPONENT_1203NH,
    restore_measured_components_1203ni as restore_all,
    _skeleton_components,
    complete_design_system,
    restore_logo_component_1203nh as restore,
)

# r191's own shapes.
# r191's own shape, including the keys every spec component really carries: measured on
# fyp_feed_logged_out, `background` and `accents` are present on 17 of 17. A fixture without
# them would have made #1203ni's "the colors come free" claim untestable.
_ACC = {"blue": "#65c9d1", "red": "#ea445a"}
_SPEC = {"components": [
    {"name": "app_shell", "region": [0.0, 0.0, 1.0, 1.0], "role": "Full-screen layout",
     "state": "logged-out", "background": "#000000", "accents": _ACC},
    {"name": "left_sidebar", "region": [0.0, 0.0, 0.16, 1.0], "role": "Nav column",
     "state": "visible", "background": "#000000", "accents": _ACC},
    {"name": "brand_header", "region": [0.012, 0.018, 0.09, 0.065],
     "role": "App logo area at the top of the sidebar.",
     "state": "brand mark displayed", "background": "#000000", "accents": _ACC},
    {"name": "search_box", "region": [0.01, 0.072, 0.155, 0.13], "role": "Rounded search",
     "state": "empty", "background": "#121212", "accents": _ACC},
]}
_SCREEN = {"name": "fyp_feed_logged_out",
           "components": [{"id": "left-sidebar"}, {"id": "top-action-bar"},
                          {"id": "video-stage"}, {"id": "engagement-rail"}]}


def _screen():
    return json.loads(json.dumps(_SCREEN))


class ItPutsTheLogoBack(unittest.TestCase):
    def test_r191s_case(self):
        s = _screen()
        got = restore(s, _SPEC, None)
        self.assertIsNotNone(got)
        self.assertEqual(got["id"], "brand-header")
        self.assertEqual(got["region"], [0.012, 0.018, 0.09, 0.065])
        self.assertIn("logo", got["role"].lower())
        self.assertIn("brand-header", [c["id"] for c in s["components"]])

    def test_it_is_idempotent(self):
        s = _screen()
        self.assertIsNotNone(restore(s, _SPEC, None))
        self.assertIsNone(restore(s, _SPEC, None))
        self.assertEqual(len([c for c in s["components"] if c["id"] == "brand-header"]), 1)

    def test_a_screen_that_kept_its_logo_is_left_alone(self):
        s = {"name": "x", "components": [{"id": "sidebar-logo"}]}
        self.assertIsNone(restore(s, _SPEC, None))
        self.assertEqual(len(s["components"]), 1)

    def test_the_restored_entry_has_the_skeleton_shape(self):
        """#1032: shape comes from `_skeleton_components`, not from a second builder here."""
        got = restore(_screen(), _SPEC, None)
        want = set(_skeleton_components({"components": [_SPEC["components"][2]]}, None)[0])
        self.assertEqual(set(got), want)
        for k in ("region", "colors", "geometry", "role", "crop"):
            self.assertIn(k, got)

    def test_only_the_first_logo_is_restored(self):
        spec = {"components": [
            {"name": "brand_logo", "region": [0, 0, 0.1, 0.1], "role": "a"},
            {"name": "app_logo", "region": [0, 0, 0.1, 0.1], "role": "b"}]}
        s = {"name": "x", "components": []}
        self.assertIsNotNone(restore(s, spec, None))
        self.assertEqual(len(s["components"]), 1)


class ItRestoresNothingItCannotCrop(unittest.TestCase):
    def test_a_logo_without_a_region(self):
        spec = {"components": [{"name": "brand_logo", "role": "the mark"}]}
        s = {"name": "x", "components": []}
        self.assertIsNone(restore(s, spec, None))
        self.assertEqual(s["components"], [])

    def test_a_malformed_region(self):
        for bad in ([0, 0, 1], "x", None, {}):
            with self.subTest(region=repr(bad)):
                spec = {"components": [{"name": "brand_logo", "region": bad}]}
                self.assertIsNone(restore({"name": "x", "components": []}, spec, None))

    def test_a_spec_without_a_logo(self):
        spec = {"components": [{"name": "top_navigation_bar", "region": [0, 0, 1, 0.1]}]}
        self.assertIsNone(restore({"name": "x", "components": []}, spec, None))

    def test_hostile_shapes_never_raise(self):
        for spec in (None, {}, {"components": None}, {"components": ["nope", 7]}, "x"):
            with self.subTest(spec=repr(spec)[:30]):
                self.assertIsNone(restore({"name": "x", "components": []}, spec, None))
        self.assertIsNone(restore(None, _SPEC, None))
        self.assertIsNone(restore("nope", _SPEC, None))


class TheDetectorIsNameOnlyAndNarrow(unittest.TestCase):
    _LOGOS = ("brand_logo", "brand_header", "netflix_logo", "app_logo", "logo",
              "sidebar_logo", "tiktok_logo", "left_sidebar_logo", "brand-header",
              "sidebar-brand-header", "wordmark")
    _NOT = ("top_navigation_bar", "search_bar", "left_sidebar", "video_stage",
            "engagement_rail", "primary_nav_menu", "branding_guidelines_text",
            "rebrand_notice", "logout_button")

    def test_the_corpus_logo_names_match(self):
        for n in self._LOGOS:
            with self.subTest(name=n):
                self.assertTrue(_LOGO_COMPONENT_1203NH.search(n), n)

    def test_the_names_a_wider_predicate_wrongly_pulled_in(self):
        for n in self._NOT:
            with self.subTest(name=n):
                self.assertFalse(_LOGO_COMPONENT_1203NH.search(n), n)

    def test_it_does_not_read_the_role(self):
        """The too-wide version matched `role`, which is how `top_navigation_bar` got in.
        The fixture's role is the bare word, because the pattern's boundaries are `_`, `-`
        and the string ends -- against ordinary prose ("...containing the logo and...") a
        role-reading version would behave identically, so a prose fixture would pin
        nothing."""
        for role in ("logo", "brand", "wordmark"):
            with self.subTest(role=role):
                spec = {"components": [{"name": "top_navigation_bar",
                                        "region": [0, 0, 1, 0.1], "role": role}]}
                self.assertIsNone(restore({"name": "x", "components": []}, spec, None))


class TheRestOfTheLossComesBackToo1203ni(unittest.TestCase):
    """#1203ni: `#1203nh` stopped at the logo because a crop costs 400 KB and ~170 of them
    would be ~68 MB a run. That was the wrong place to stop -- the crop is not what most
    readers want. `_measured_vertical_gradient_602` derives a screen's CSS gradient from its
    full-bleed component bands and their measured `colors.bg`, and `components` is read in
    frontend_scaffold (six sites), frontend_audit and deliverability. So restore the DATA and
    not the crop: this runs AFTER the crop loop, every restored component carries
    `crop: None`, and the colors come free (every spec component carries `background` --
    17 of 17 on r191's fyp screen)."""

    def test_every_dropped_component_comes_back(self):
        """`left_sidebar` slugs to `left-sidebar`, which the analyst kept, so it is NOT
        restored -- the count is the spec minus the ids already present. On r191's real
        fyp screen that is 4 -> 19."""
        s = _screen()
        n = restore_all(s, _SPEC, None)
        self.assertEqual(n, len(_SPEC["components"]) - 1)
        self.assertEqual(len(s["components"]), 4 + n)
        ids = [c["id"] for c in s["components"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_it_is_idempotent(self):
        s = _screen()
        restore_all(s, _SPEC, None)
        self.assertEqual(restore_all(s, _SPEC, None), 0)

    def test_an_id_the_analyst_already_used_is_not_duplicated(self):
        s = {"name": "x", "components": [{"id": "left-sidebar"}]}
        restore_all(s, _SPEC, None)
        ids = [c["id"] for c in s["components"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count("left-sidebar"), 1)

    def test_every_restored_component_carries_the_measurement(self):
        s = _screen()
        restore_all(s, _SPEC, None)
        for c in s["components"][4:]:
            self.assertTrue(isinstance(c.get("region"), (list, tuple)))
            self.assertEqual(len(c["region"]), 4)
            self.assertIn("colors", c)
            self.assertIn("role", c)

    def test_the_measured_background_arrives(self):
        """`_measured_vertical_gradient_602` needs `colors.bg` to be a hex."""
        s = _screen()
        restore_all(s, _SPEC, None)
        bgs = [c["colors"].get("bg") for c in s["components"][4:]]
        self.assertTrue(any(isinstance(b, str) and b.startswith("#") for b in bgs), bgs)

    def test_nothing_restored_here_carries_a_crop(self):
        """The whole affordability argument: the data comes back, the 400 KB does not."""
        s = _screen()
        restore_all(s, _SPEC, None)
        self.assertTrue(all(c.get("crop") is None for c in s["components"][4:]))

    def test_a_component_without_a_region_is_skipped(self):
        spec = {"components": [{"name": "ghost", "role": "no region"},
                               {"name": "real", "region": [0, 0, 1, 1]}]}
        s = {"name": "x", "components": []}
        self.assertEqual(restore_all(s, spec, None), 1)
        self.assertEqual([c["id"] for c in s["components"]], ["real"])

    def test_hostile_shapes_never_raise(self):
        for spec in (None, {}, {"components": None}, {"components": ["x", 7]}, "nope"):
            with self.subTest(spec=repr(spec)[:24]):
                self.assertEqual(restore_all({"name": "x", "components": []}, spec, None), 0)
        self.assertEqual(restore_all(None, _SPEC, None), 0)


class TheCallSiteRunsBeforeTheCrop(unittest.TestCase):
    """The whole point is that the restored component gets a physical crop, which only
    happens if it is in `screen["components"]` when the crop loop runs."""

    def _src(self):
        return inspect.getsource(complete_design_system)

    def test_it_is_called(self):
        self.assertIn("restore_logo_component_1203nh", self._src())

    def test_it_is_called_before_the_crop_loop(self):
        src = self._src()
        self.assertLess(src.index("restore_logo_component_1203nh("),
                        src.index("crop_region("))

    def test_it_is_fed_this_screens_spec(self):
        tree = ast.parse(self._src().lstrip())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "restore_logo_component_1203nh"]
        self.assertTrue(calls)
        self.assertEqual(len(calls[0].args), 3, ast.dump(calls[0]))

    def test_the_bulk_restore_runs_AFTER_the_crop_loop_1203ni(self):
        """The logo is restored before the crop loop so it gets a crop; the rest after it so
        they do not. Getting that order backwards is the 68 MB."""
        src = self._src()
        self.assertLess(src.index("restore_logo_component_1203nh("), src.index("crop_region("))
        self.assertGreater(src.index("restore_measured_components_1203ni("),
                           src.index("crop_region("))

    def test_the_bulk_restore_is_announced_1203ni(self):
        tree = ast.parse(self._src().lstrip())
        for n in ast.walk(tree):
            if (isinstance(n, ast.If)
                    and "components_restored_1203ni" in ast.dump(n.test)):
                for sub in ast.walk(n):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "warning"):
                        return
        self.fail("the bulk restore is not announced under its own count")

    def test_the_restore_is_announced(self):
        """On the AST: a source-text match cannot see the CONDITION, and a mutation that
        changed the guard to `if False` left the sentence in place and survived."""
        tree = ast.parse(self._src().lstrip())
        guarded = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.If):
                continue
            if "logo_restored_1203nh" not in ast.dump(n.test):
                continue
            for sub in ast.walk(n):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "warning" and sub.args
                        and isinstance(sub.args[0], ast.Constant)
                        and "#1203nh restored" in str(sub.args[0].value)):
                    guarded.append(sub)
        self.assertTrue(guarded,
                        "the announcement is not inside an `if stats[...]` that reads the "
                        "restored count")

    def test_the_announcement_declares_a_cut_list(self):
        """#1034, anchored on the AST node rather than a byte window -- #943's ratchet caught
        the first version of this (`src[i:i+900]`), the same trap #1203n7 hit."""
        tree = ast.parse(self._src().lstrip())
        for n in ast.walk(tree):
            if not isinstance(n, ast.If) or "logo_restored_1203nh" not in ast.dump(n.test):
                continue
            calls = [c.func.id for c in ast.walk(n)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
            if "join_capped" in calls:
                return
        self.fail("the restored-name list is not rendered through join_capped")


class TheRealCorpusShapes(unittest.TestCase):
    """Driven on every component_specs file of the newest run that is on disk, if present."""

    def test_the_specs_that_carry_a_logo_all_restore(self):
        d = pathlib.Path("../generated/tiktok-web-r191/design")
        if not (d / "component_specs").is_dir():
            self.skipTest("the r191 artefacts are not on this disk")
        n_spec = n_restored = 0
        for f in sorted((d / "component_specs").glob("*.json")):
            spec = json.loads(f.read_text(encoding="utf-8"))
            if not [c for c in (spec.get("components") or [])
                    if isinstance(c, dict)
                    and _LOGO_COMPONENT_1203NH.search(str(c.get("name") or ""))
                    and isinstance(c.get("region"), list) and len(c["region"]) == 4]:
                continue
            n_spec += 1
            if restore({"name": f.stem, "components": []}, spec, None) is not None:
                n_restored += 1
        self.assertGreaterEqual(n_spec, 5, n_spec)
        self.assertEqual(n_spec, n_restored)


if __name__ == "__main__":
    unittest.main()


# ★ DECLARED NULL MUTATION (#1203jr): changing `want[:1]` to `want` comes back MISSED, and it
# is null by construction -- only `built[0]` is ever appended, so the slice is belt-and-braces
# over a list the code already takes one element from. `test_only_the_first_logo_is_restored`
# pins the OUTCOME (one component appended), which is the property that matters.
