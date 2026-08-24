"""#1072 — `unviewed_manifest_paths` says "PURE — unit-testable" and had no tests.

It backs `ENVGEN_ENFORCE_REF_VIEW`, which rejects a frontend kickoff section whose
`reference_image_manifest` declares reference images the agent never actually
view_image'd this run — i.e. a manifest authored from memory. The flag is
env-gated and default-off; across the 201 kept run logs it is enabled 0 times, and
nothing referenced this function from a test.

The machinery around it is wired (`_viewed_reference_paths` is initialised in
base.py and populated by view_image), and both sides of the comparison normalise
through the same `_norm_ref_path`, so there is no false-mismatch asymmetry — the
failure mode I went looking for after #1071 turned up a real one in the sibling
flag. These tests pin what it does instead of leaving that to a first enabling
run, including the two "enforcement off" escapes the docstring promises.
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

from multi_agent.runtime.kickoff.section_substance import (  # noqa: E402
    manifest_paths, unviewed_manifest_paths,
)


class EnforcementIsOffWhenItCannotJudge(unittest.TestCase):

    def test_no_viewed_set_means_no_finding(self):
        """"no viewed-set supplied (enforcement off — e.g. the facilitator has no handle)"."""
        c = {"reference_image_manifest": {"design/refs/home.png": "the home screen"}}
        self.assertEqual(unviewed_manifest_paths(c, None), [])

    def test_the_empty_manifest_stub_is_not_a_finding(self):
        """"submit reference_image_manifest={} with a note" is the sanctioned answer."""
        self.assertEqual(unviewed_manifest_paths({"reference_image_manifest": {}}, set()), [])
        self.assertEqual(unviewed_manifest_paths({}, set()), [])
        self.assertEqual(unviewed_manifest_paths(None, set()), [])


class ItNamesOnlyWhatWasNotViewed(unittest.TestCase):

    def test_declared_but_unviewed_is_reported_sorted(self):
        c = {"reference_image_manifest": {"design/b.png": "", "design/a.png": ""}}
        self.assertEqual(unviewed_manifest_paths(c, set()), ["design/a.png", "design/b.png"])

    def test_a_viewed_path_is_not_reported(self):
        c = {"reference_image_manifest": {"design/a.png": "", "design/b.png": ""}}
        self.assertEqual(unviewed_manifest_paths(c, {"design/a.png"}), ["design/b.png"])

    def test_everything_viewed_is_clean(self):
        c = {"reference_image_manifest": {"design/a.png": ""}}
        self.assertEqual(unviewed_manifest_paths(c, {"design/a.png"}), [])


class BothSidesNormaliseTheSameWay(unittest.TestCase):
    """The asymmetry that would make every valid submission look unviewed."""

    def test_leading_dot_slash_and_backslashes_match(self):
        c = {"reference_image_manifest": {"./design\\refs\\home.png": ""}}
        self.assertEqual(unviewed_manifest_paths(c, {"design/refs/home.png"}), [])

    def test_a_leading_slash_matches_a_relative_viewed_path(self):
        c = {"reference_image_manifest": {"/design/refs/home.png": ""}}
        self.assertEqual(unviewed_manifest_paths(c, {"design/refs/home.png"}), [])

    def test_surrounding_whitespace_matches(self):
        c = {"reference_image_manifest": {"  design/a.png  ": ""}}
        self.assertEqual(unviewed_manifest_paths(c, {"design/a.png"}), [])


class TheListAndPathFormsAreAccepted(unittest.TestCase):
    """"manifest dict keys, or items if a list/`{path:...}` form was submitted"."""

    def test_a_list_of_strings(self):
        self.assertEqual(manifest_paths({"reference_image_manifest": ["./design/a.png"]}),
                         ["design/a.png"])

    def test_a_list_of_path_objects(self):
        self.assertEqual(
            manifest_paths({"reference_image_manifest": [{"path": "design/a.png"}]}),
            ["design/a.png"])

    def test_blank_entries_are_dropped(self):
        self.assertEqual(manifest_paths({"reference_image_manifest": {"   ": "x"}}), [])
        self.assertEqual(manifest_paths({"reference_image_manifest": ["", {"path": ""}]}), [])

    def test_a_non_mapping_content_is_empty(self):
        self.assertEqual(manifest_paths("frontend"), [])
        self.assertEqual(manifest_paths(None), [])


if __name__ == "__main__":
    unittest.main()
