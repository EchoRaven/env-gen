"""Fix #52/#53 — deterministic per-component color-diff gate + zoom_compare mandate.

Live context (run-30/33/35/38 post-mortems, HANDOFF 2026-07-02 §6.1): the visual
judge's advisory mismatches persist run after run because the lane fixes by
EYEBALL; the pre-measured component specs (design/component_specs/*.json) carry
regions as 0..1 fractions + measured hex, the gate captures screenshots — this
closes the loop deterministically: sample the SAME region from the screenshot,
compare to the spec hex, name the deviation with exact values.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from env_generator.llm_generator.multi_agent.runtime.material_prep import (  # noqa: E402
    color_distance, spec_color_deviations)
from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf  # noqa: E402

from PIL import Image  # noqa: E402


def _shot(path: Path, *, top_hex=(255, 255, 255), body_hex=(0x29, 0x29, 0x29),
          blue_block=False, size=(300, 300)):
    """Synthetic screenshot: top 10% strip + body, optional saturated blue block."""
    im = Image.new("RGB", size, body_hex)
    for x in range(size[0]):
        for y in range(int(size[1] * 0.1)):
            im.putpixel((x, y), top_hex)
    if blue_block:
        for x in range(120, 180):
            for y in range(150, 210):
                im.putpixel((x, y), (0x2d, 0x4e, 0xdf))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


_SPEC = {
    "components": [
        {"name": "top_bar", "region": [0.0, 0.0, 1.0, 0.1],
         "background": "#292929", "accents": {"blue": "#2d4edf"}},
        {"name": "body", "region": [0.0, 0.1, 1.0, 1.0],
         "background": "#292929", "accents": {}},
        {"name": "tiny", "region": [0.0, 0.0, 0.01, 0.01],
         "background": "#ff0000", "accents": {}},
    ]
}


class TestColorDistance(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(color_distance("#292929", "#292929"), 0.0)

    def test_black_white_is_large(self):
        self.assertGreater(color_distance("#000000", "#ffffff"), 500)

    def test_close_grays_are_small(self):
        self.assertLess(color_distance("#292929", "#2b2b2b"), 10)

    def test_unparseable_is_none(self):
        self.assertIsNone(color_distance("nope", "#ffffff"))
        self.assertIsNone(color_distance("#fff", "#ffffff"))


class TestSpecColorDeviations(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="colordiff_"))

    def test_wrong_background_named_with_exact_hexes(self):
        shot = _shot(self.tmp / "s.png")  # top strip WHITE, spec says #292929
        devs = spec_color_deviations(_SPEC, shot)
        bg = [d for d in devs if d["kind"] == "background"]
        self.assertEqual(len(bg), 1)
        self.assertEqual(bg[0]["component"], "top_bar")
        self.assertEqual(bg[0]["expected"], "#292929")
        self.assertEqual(bg[0]["actual"], "#ffffff")
        self.assertGreater(bg[0]["distance"], 100)
        self.assertEqual(len(bg[0]["region"]), 4)

    def test_matching_background_not_flagged(self):
        shot = _shot(self.tmp / "s2.png", top_hex=(0x29, 0x29, 0x29))
        devs = spec_color_deviations(_SPEC, shot)
        self.assertFalse([d for d in devs if d["kind"] == "background"])

    def test_semantic_color_loss_flagged_and_restored_accent_not(self):
        shot = _shot(self.tmp / "s3.png")  # no blue anywhere
        devs = spec_color_deviations(_SPEC, shot)
        acc = [d for d in devs if d["kind"] == "accent_missing"]
        self.assertEqual([(d["component"], d["hue"]) for d in acc],
                         [("top_bar", "blue")])
        # blue present in the region → no loss flagged
        shot2 = _shot(self.tmp / "s4.png", top_hex=(0x2d, 0x4e, 0xdf))
        devs2 = spec_color_deviations(_SPEC, shot2)
        self.assertFalse([d for d in devs2 if d["kind"] == "accent_missing"])

    def test_accent_elsewhere_on_screen_is_not_a_loss(self):
        """Review w6x6art4t (split): reference CONTENT (avatars/photos) seeds
        spec accents; the hue present ANYWHERE on the implemented screen means
        no semantic loss — only a whole-screen absence flags."""
        shot = _shot(self.tmp / "s8.png", blue_block=True)  # blue in BODY only
        devs = spec_color_deviations(_SPEC, shot)
        self.assertFalse([d for d in devs if d["kind"] == "accent_missing"])

    def test_tiny_region_skipped(self):
        shot = _shot(self.tmp / "s5.png")
        devs = spec_color_deviations(_SPEC, shot)
        self.assertFalse([d for d in devs if d["component"] == "tiny"])

    def test_threshold_env_override(self):
        import os
        shot = _shot(self.tmp / "s6.png")
        os.environ["ENVGEN_COLOR_DIFF_THRESHOLD"] = "9999"
        try:
            devs = spec_color_deviations(_SPEC, shot)
            self.assertFalse([d for d in devs if d["kind"] == "background"])
        finally:
            del os.environ["ENVGEN_COLOR_DIFF_THRESHOLD"]

    def test_best_effort_on_garbage(self):
        self.assertEqual(spec_color_deviations(None, "/nonexistent.png"), [])
        self.assertEqual(spec_color_deviations({"components": "junk"},
                                               "/nonexistent.png"), [])
        shot = _shot(self.tmp / "s7.png")
        self.assertEqual(
            spec_color_deviations({"components": [{"name": "x", "region": None,
                                                   "background": "#000000"}]}, shot),
            [])


class TestGateWiring(unittest.TestCase):
    """run_visual_fidelity attaches measured_deviations + reference; the
    remediation task renders the measured diff (#52) and the zoom_compare
    mandate with the real reference path (#53)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vfwire_"))
        self.project = self.tmp / "proj"
        # reference image whose stem maps to /inbox via App.jsx routes
        self.ref = _shot(self.tmp / "refs" / "testapp_inbox.png",
                         top_hex=(0x29, 0x29, 0x29))
        app_src = self.project / "app" / "frontend" / "src"
        app_src.mkdir(parents=True)
        (app_src / "App.jsx").write_text('<Route path="/inbox" element={<X/>} />')
        specs = self.project / "design" / "component_specs"
        specs.mkdir(parents=True)
        (specs / "testapp_inbox.json").write_text(json.dumps(_SPEC))
        # implementation shot: WRONG top bar (white) + no blue → 2 deviations
        self.impl = _shot(self.tmp / "impl.png")

    def _run(self, similarity):
        async def capture(screens):
            return {s["name"]: str(self.impl) for s in screens}

        async def judge(llm, screen, shot):
            return {"similarity": similarity, "dimensions": {},
                    "deviations": ["judge prose"], "fixes": [], "summary": "s"}

        # asyncio.run (not get_event_loop): under the full suite another test
        # may have closed the thread's default loop — a fresh loop per call.
        return asyncio.run(
            vf.run_visual_fidelity(self.project, [self.ref], llm=None,
                                   capture_fn=capture, judge_fn=judge))

    def test_measured_deviations_attached(self):
        result = self._run(0.2)
        (screen,) = result["screens"]
        self.assertEqual(screen["reference"], str(self.ref))
        kinds = sorted(d["kind"] for d in screen["measured_deviations"])
        self.assertEqual(kinds, ["accent_missing", "background"])

    def test_remediation_renders_measured_diff_and_zoom_mandate(self):
        result = self._run(0.2)
        text = vf.remediation_text(result, self.project)
        self.assertIn("MEASURED COLOR DIFF", text)
        self.assertIn("#292929", text)          # exact spec hex in-hand
        self.assertIn("#ffffff", text)          # exact rendered hex named
        self.assertIn("accent MISSING", text)
        # no staged copy in this harness → falls back to the original path
        self.assertIn(f'zoom_compare(reference="{self.ref}"', text)
        self.assertIn("region=", text)          # worst region pre-filled
        self.assertIn("scale=2", text)
        # the taught call must be EXECUTABLE: save_as is a REQUIRED tool arg
        # (review w6x6art4t — omitting it teaches a TypeError-ing call)
        self.assertIn('save_as="design/compare/testapp_inbox_check.png"', text)

    def test_zoom_mandate_prefers_lane_visible_staged_reference(self):
        """Review w6x6art4t: screen['path'] is a host-absolute orchestrator-side
        path the lane workspace can't resolve; when the framework staged a copy
        under design/references/, the taught call must use THAT relative path."""
        staged = self.project / "design" / "references" / "testapp_inbox.png"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(Path(self.ref).read_bytes())
        text = vf.remediation_text(self._run(0.2), self.project)
        self.assertIn('zoom_compare(reference="design/references/testapp_inbox.png"',
                      text)

    def test_passing_screen_emits_no_remediation_section(self):
        result = self._run(0.9)
        self.assertTrue(result["passed"])
        text = vf.remediation_text(result, self.project)
        self.assertNotIn("MEASURED COLOR DIFF", text)

    def test_missing_spec_is_best_effort(self):
        (self.project / "design" / "component_specs" / "testapp_inbox.json").unlink()
        result = self._run(0.2)
        (screen,) = result["screens"]
        self.assertEqual(screen["measured_deviations"], [])
        # zoom mandate still present (reference path known even without a spec)
        self.assertIn("zoom_compare(reference=", vf.remediation_text(result, self.project))


if __name__ == "__main__":
    unittest.main()
