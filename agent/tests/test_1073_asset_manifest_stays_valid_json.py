"""#1073 — the design analyst's asset manifest is handed to it as broken JSON.

The per-screen enrichment prompt carries:

    manifest = json.dumps([{"id": a.get("id"), "file": a.get("file")}
                           for a in (skeleton.get("assets") or [])])[:3000]
    ...
    {"type": "text", "text": "REAL ASSET MANIFEST (map ids onto components): " + manifest}

`[:3000]` slices the SERIALISED string, so it cuts mid-object. Measured on a real
design doc from the corpus (70 assets, 4146 chars):

    tail: ': "photo-camera-24", "file": "icons/photo_camera_24.svg"}, {"id": "pin'
    json.loads(...) -> JSONDecodeError
    50 of 70 entries survive, the 51st is a fragment

So the model is told "REAL ASSET MANIFEST" and given a string that does not parse,
ending in a half-written id. Asset mapping is not incidental — #343 and #507 are
both about the analyst's asset/colour output driving what the lane can build.

The corpus median is 144 assets and 150 of 152 design docs exceed 24, so the cap
has to stay a BUDGET rather than a count: fill up to the budget on ELEMENT
boundaries, and say how many were dropped instead of truncating silently.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.design_prep import _asset_manifest_1073 as _mf  # noqa: E402


def _assets(n, idlen=12):
    return [{"id": f"asset-{i:0{idlen}d}", "file": f"icons/asset_{i}.svg"} for i in range(n)]


class ItIsAlwaysValidJson(unittest.TestCase):

    def test_a_manifest_that_fits_is_complete(self):
        out = _mf(_assets(3), budget=3000)
        self.assertEqual(len(json.loads(out)), 3)

    def test_a_manifest_that_overflows_still_parses(self):
        """The whole defect: `json.dumps(...)[:3000]` cut mid-object."""
        out = _mf(_assets(400), budget=3000)
        parsed = json.loads(out)
        entries = [e for e in parsed if "__omitted__" not in e]
        self.assertGreater(len(entries), 0)
        self.assertTrue(all(set(e) == {"id", "file"} for e in entries))

    def test_no_entry_is_a_fragment(self):
        out = _mf(_assets(400), budget=3000)
        for e in json.loads(out):
            if "__omitted__" in e:      # the declared tail, not an asset
                continue
            self.assertTrue(e["id"] and e["file"])
            self.assertTrue(str(e["file"]).endswith(".svg"))

    def test_empty_and_missing_are_an_empty_array(self):
        for a in ([], None):
            self.assertEqual(json.loads(_mf(a, budget=3000)), [])


class ItRespectsTheBudgetAndSaysWhatItDropped(unittest.TestCase):

    def test_the_result_fits_the_budget(self):
        out = _mf(_assets(400), budget=3000)
        self.assertLessEqual(len(out), 3000)

    def test_a_dropped_tail_is_declared_not_silent(self):
        out = _mf(_assets(400), budget=3000)
        self.assertIn("__omitted__", out, "a silent cap reads as 'these are all the assets'")
        note = [e for e in json.loads(out) if "__omitted__" in e]
        self.assertEqual(len(note), 1)
        self.assertGreater(note[0]["__omitted__"], 0)

    def test_nothing_is_declared_when_nothing_was_dropped(self):
        out = _mf(_assets(3), budget=3000)
        self.assertNotIn("__omitted__", out)

    def test_a_budget_too_small_for_one_entry_is_still_valid_json(self):
        out = _mf(_assets(400), budget=20)
        json.loads(out)


class ItKeepsTheFieldsTheAnalystIsAskedToMap(unittest.TestCase):

    def test_id_and_file_are_carried(self):
        got = json.loads(_mf([{"id": "poster-1", "file": "img/p1.png", "extra": "x"}],
                             budget=3000))
        self.assertEqual(got, [{"id": "poster-1", "file": "img/p1.png"}])

    def test_a_non_mapping_entry_does_not_raise(self):
        json.loads(_mf(["oops", None, {"id": "a", "file": "b"}], budget=3000))


if __name__ == "__main__":
    unittest.main()
