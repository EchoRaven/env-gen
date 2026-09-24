"""#1202ey: the snapshot's capture must be a RULE, not a hand-maintained inventory.

`_STATE_DIRS_JSON_ONLY_1202CS` named `design/visual_gate`, so every design-level
state file added afterwards was silently outside the snapshot. The one that
mattered is `design/milestone_gates.json` -- the orchestrator's gate counters,
which are BOUNDS. A restore rewound the hubs to time T while the bounds stayed at
whatever the abandoned attempt had spent, so the restored run inherited exhausted
budgets its own work state had never used.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.run_snapshot import (  # noqa: E402
    restore_snapshot,
    take_snapshot,
)


def _run_dir():
    d = Path(tempfile.mkdtemp())
    (d / "shared" / "hubs").mkdir(parents=True)
    (d / "design" / "visual_gate").mkdir(parents=True)
    (d / "design" / "component_specs").mkdir()
    (d / "shared" / "hubs" / "workhub_tasks.json").write_text('{"t": 1}', encoding="utf-8")
    (d / "design" / "milestone_gates.json").write_text(
        json.dumps({"_fwval_stuck_count": 3, "_tu_squad_attempts": 2}), encoding="utf-8")
    (d / "design" / "visual_gate" / "gate_state.json").write_text("{}", encoding="utf-8")
    (d / "design" / "lane_page_exposure_946.json").write_text("{}", encoding="utf-8")
    (d / "design" / "reference_spec.json").write_text('{"screens": 13}', encoding="utf-8")
    (d / ".user_gates.json").write_text('{"g": true}', encoding="utf-8")
    (d / ".checkpoint").write_text("{}", encoding="utf-8")
    # the images #1202cs deliberately leaves behind
    (d / "design" / "visual_gate" / "round1.png").write_bytes(b"\x89PNG" + b"0" * 4096)
    (d / "design" / "shot.jpg").write_bytes(b"\xff\xd8" + b"0" * 4096)
    return d


class TestSnapshotCapturesByRule(unittest.TestCase):

    def setUp(self):
        self.run = _run_dir()
        self.snap = take_snapshot(self.run, kind="manual", label="t")
        self.assertIsNotNone(self.snap)

    def _in_snapshot(self, rel):
        return (Path(self.snap) / rel).exists()

    def test_the_gate_counters_are_captured(self):
        """The regression: these are bounds, and half-restoring them blends two moments."""
        self.assertTrue(self._in_snapshot("design/milestone_gates.json"))

    def test_a_new_design_state_file_needs_no_code_change(self):
        """The inventory is what failed. A rule covers what nobody has written yet."""
        (self.run / "design" / "invented_after_the_fix.json").write_text(
            '{"x": 1}', encoding="utf-8")
        snap2 = take_snapshot(self.run, kind="manual", label="t2")
        self.assertTrue((Path(snap2) / "design" / "invented_after_the_fix.json").exists())

    def test_the_visual_gate_subdir_is_still_covered(self):
        """The broader rule subsumes the narrower one it replaces."""
        self.assertTrue(self._in_snapshot("design/visual_gate/gate_state.json"))

    def test_images_are_still_left_behind(self):
        """#1202cs's saving: 170-265MB of images against ~1MB of JSON beside them."""
        self.assertFalse(self._in_snapshot("design/visual_gate/round1.png"))
        self.assertFalse(self._in_snapshot("design/shot.jpg"))

    def test_a_top_level_dotfile_no_directory_rule_reaches(self):
        self.assertTrue(self._in_snapshot(".user_gates.json"))

    def test_the_counters_survive_a_round_trip(self):
        """Capturing without restoring would be the same blend, one step later."""
        (self.run / "design" / "milestone_gates.json").write_text(
            json.dumps({"_fwval_stuck_count": 99, "_tu_squad_attempts": 99}), encoding="utf-8")
        restore_snapshot(self.run, Path(self.snap).name)
        back = json.loads((self.run / "design" / "milestone_gates.json").read_text(encoding="utf-8"))
        self.assertEqual(back["_fwval_stuck_count"], 3)
        self.assertEqual(back["_tu_squad_attempts"], 2)

    def test_the_hubs_are_untouched_by_the_widened_rule(self):
        self.assertTrue(self._in_snapshot("shared/hubs/workhub_tasks.json"))


class TheRestoreSaysWhatItDoesNotRewind(unittest.TestCase):

    def test_the_operator_is_told_the_code_is_not_rewound(self):
        """`app/` and `worktrees/` are git and deliberately untouched. "Restored N files"
        reads as "the run went back", and the wedged code is still there."""
        main = (THIS_DIR.parent / "env_generator" / "llm_generator"
                / "main.py").read_text(encoding="utf-8")
        i = main.index("res = restore_snapshot(output_dir")
        j = main.index("Continue with: --resume", i)
        told = main[i:j]
        self.assertIn("NOT", told)
        self.assertIn("app/", told)
        self.assertIn("worktrees/", told)

    def test_the_snapshot_still_does_not_carry_the_code(self):
        """The message would be a lie if it did."""
        run = _run_dir()
        (run / "app").mkdir()
        (run / "app" / "main.py").write_text("x = 1", encoding="utf-8")
        (run / "app" / "state.json").write_text("{}", encoding="utf-8")
        snap = Path(take_snapshot(run, kind="manual", label="code"))
        self.assertFalse((snap / "app" / "main.py").exists())
        self.assertFalse((snap / "app" / "state.json").exists(),
                         "the JSON-only rules must not reach into app/")


if __name__ == "__main__":
    unittest.main()
