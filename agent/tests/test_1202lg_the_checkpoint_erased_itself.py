"""#1202lg: a second CheckpointManager silently erased the first one's record.

`CheckpointManager.__init__` built an empty `GenerationCheckpoint` and never read the file,
while `_save_if_auto` writes after every mutation. So the FIRST mutation of a second manager
over the same path overwrote everything the first had recorded.

Demonstrated: manager A records ['agent_workflow', 'milestone:1:X']; a manager B constructed on
the same path reads `phases: []`, and B's first `start_phase` leaves the file holding exactly
['agent_workflow'] with `current_phase: agent_workflow`.

★ THE CORPUS EVIDENCE I FIRST CITED FOR THIS WAS WRONG, and the mistake is worth more than
the fix. I reported "126 of 131 runs hold exactly one phase" and "tiktok-r119's checkpoint still
reads planning, iteration 0". Both came from my own TRUNCATED prints -- `json.dumps(phases)[:220]`
and `[:90]` -- so I compared the first 90 characters of each file and read identical prefixes as
identical files. Measured without truncation: of 159 checkpoints, 39 (25%) DO carry milestone
records, and r119's carries all four of its phases. The record was not being erased there.

What survives, and why this fix stands anyway: the constructor genuinely never loads, and a
second manager over the same path genuinely erases the first one's record. That is reproduced
below against the real class, not inferred -- manager A records
['agent_workflow', 'milestone:1:X']; a manager B constructed on the same path reads `phases: []`,
and B's first `start_phase` leaves the file holding exactly ['agent_workflow']. It is a real
failure mode with a real cost; it simply is not the one I claimed to have caught in r119.

WHAT THE RESUME PATH COSTS regardless: #1202bz gives `--resume` milestone-level granularity by
reading these phases ("skip a completed milestone only when a LATER milestone has a record").
21 runs in the corpus resumed -- tiktok-r96 seven times, googlemaps-r16 ten -- for zero
additional releases between them, and #1202bz has never appeared in any of 310 run logs. Why it
never fires is still open; with 25% of checkpoints carrying milestone records, "the record is
always gone" is NOT the explanation.

The class docstring already prescribed `if manager.load():` at the call site. Nothing called it.

WHAT IS VERIFIED: a second manager adopts the existing record instead of erasing it; a
completed milestone keeps its `complete` status across that boundary; construction over no file
still starts blank; a corrupt file does not raise; and end-to-end, a checkpoint written by a run
that finished M1+M2 and died in M3 makes #1202bz answer skip/skip/re-enter -- replayed with
tiktok-r119's real milestone records.

WHAT IS NOT: an explanation of every wipe. This proves the constructor CAN erase the file and
that adopting stops it; it does not prove that a second construction is the only way r119's
record was lost. r120 is running with milestone phases recorded, so the next failed run's
checkpoint is the observation that settles it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from env_generator.llm_generator.checkpoint import CheckpointManager  # noqa: E402
from multi_agent.runtime.milestone_resume import (  # noqa: E402
    milestone_key_1202bz, phase_status_map_1202bz, should_skip_milestone_1202bz)


class ASecondManagerAdoptsTheRecord(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="lg_"))
        self.p = self.d / ".checkpoint"

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _phases_on_disk(self):
        return list((json.load(open(self.p)).get("phases") or {}).keys())

    def test_the_second_manager_does_not_erase_the_first(self):
        """★ The case: this is how 126 of 131 corpus checkpoints lost their milestones."""
        a = CheckpointManager(self.p)
        a.start_phase("agent_workflow")
        a.start_phase("milestone:1:X")
        b = CheckpointManager(self.p)
        b.start_phase("agent_workflow")
        self.assertIn("milestone:1:X", self._phases_on_disk())

    def test_a_completed_milestone_keeps_its_status_across_the_boundary(self):
        a = CheckpointManager(self.p)
        a.start_phase("milestone:1:X")
        a.complete_phase("milestone:1:X")
        b = CheckpointManager(self.p)
        self.assertEqual(b.get_phase_status("milestone:1:X"), "complete")

    def test_no_file_still_starts_blank(self):
        """Idempotent: a fresh run must behave exactly as before."""
        c = CheckpointManager(self.d / "nope" / ".checkpoint")
        self.assertEqual(list(c.checkpoint.phases.keys()), [])

    def test_a_corrupt_checkpoint_does_not_raise(self):
        self.p.write_text("{not json", encoding="utf-8")
        c = CheckpointManager(self.p)          # must not raise
        self.assertEqual(list(c.checkpoint.phases.keys()), [])


class ResumeCanNowSkipWhatWasDelivered(unittest.TestCase):
    """The payoff, end to end -- this is what 21 resumed runs could never do."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="lg2_"))
        self.p = self.d / ".checkpoint"
        self.ms = [{"name": "M1-core", "index": 1}, {"name": "M2-discovery", "index": 2},
                   {"name": "M3-inbox", "index": 3}]

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _first_attempt_dies_in_m3(self):
        a = CheckpointManager(self.p)
        a.start_generation(name="t", description="d", domain_type="web_app")
        a.start_phase("agent_workflow")
        for i, m in enumerate(self.ms, start=1):
            k = milestone_key_1202bz(i, m)
            a.start_phase(k)
            if i < 3:
                a.complete_phase(k)

    def test_a_resume_skips_m1_and_m2_and_re_enters_m3(self):
        self._first_attempt_dies_in_m3()
        b = CheckpointManager(self.p)                      # the resuming process
        smap = phase_status_map_1202bz(b)
        got = [should_skip_milestone_1202bz(smap, i, m)
               for i, m in enumerate(self.ms, start=1)]
        self.assertEqual(got, [True, True, False])

    def test_the_milestone_in_flight_is_never_skipped(self):
        """#1202bz's own rule, and the reason it is not "complete means skip": the lanes'
        work — and therefore remediation — happens inside the milestone body."""
        self._first_attempt_dies_in_m3()
        b = CheckpointManager(self.p)
        smap = phase_status_map_1202bz(b)
        self.assertFalse(should_skip_milestone_1202bz(smap, 3, self.ms[2]))

    def test_without_adoption_the_resume_would_skip_nothing(self):
        """Counter-proof in situ: a manager that starts blank answers skip=False for all."""
        self._first_attempt_dies_in_m3()
        blank = CheckpointManager(self.d / "other" / ".checkpoint")
        smap = phase_status_map_1202bz(blank)
        got = [should_skip_milestone_1202bz(smap, i, m)
               for i, m in enumerate(self.ms, start=1)]
        self.assertEqual(got, [False, False, False])


if __name__ == "__main__":
    unittest.main()
