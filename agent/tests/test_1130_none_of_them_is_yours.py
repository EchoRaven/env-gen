"""#1130: "could not single one out" was written for a case that never happens.

`container_id` resolves N containers matching a service NAME down to the one whose
`config_files` label is this run's compose file. #962 made it refuse to guess, and gave both
outcomes ONE message:

    "matched N containers and the config_files label could not single one out (M candidates
     for <file>). ... Stop the stale stack, or give the run its own compose project name."

That is right for M >= 2 and wrong for M == 0. With no candidates there is nothing to
disambiguate: every running container with that name belongs to some OTHER run, and this
run's own container is not up. Stopping a stale stack changes nothing.

Measured across both runs built by the current code: 97 of 97 were the M == 0 case
(netflix-local-r1 66, smoke-notes 31). The ambiguous case has not occurred once. It returns
"", and `seed_audit` then logs "#1039 live seed row-count DID NOT RUN (no database container
resolved)" — the seed audit was blind for whole runs while the log blamed a name collision.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime import container_runtime  # noqa: E402

MINE = "/runs/netflix-local-r2/docker/docker-compose.yml"
# exactly the host state that produced all 97: five *-database-1 from other projects
OTHERS = ["rydr", "paymo", "seed3val", "mm4val", "igpreview"]


class _Docker:
    """ids come back from the name filter; each id inspects to one config_files label."""

    def __init__(self, id_to_label):
        self.id_to_label = id_to_label

    def __call__(self, cmd, *a, **kw):
        if "compose" in cmd:
            out = ""
        elif "--filter" in cmd:
            out = "\n".join(self.id_to_label) + "\n"
        elif "inspect" in cmd:
            out = self.id_to_label.get(cmd[2], "")
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def _resolve(testcase, id_to_label):
    real = container_runtime.subprocess.run
    container_runtime.subprocess.run = _Docker(id_to_label)
    try:
        with testcase.assertLogs(logging.getLogger(), level="ERROR") as caught:
            cid = container_runtime.container_id(MINE, "database")
        return cid, "\n".join(caught.output)
    finally:
        container_runtime.subprocess.run = real


class NoneOfThemIsYours(unittest.TestCase):
    def setUp(self) -> None:
        # #1202au deduplicates this message by STATE, and that memo is process-wide,
        # so a sibling test that already saw the same state would silence this one.
        from multi_agent.runtime.message_format import reset_state_memo_1202ad
        reset_state_memo_1202ad("container_zero_match")


    def test_the_zero_case_says_this_run_is_not_running(self):
        cid, log = _resolve(self, {f"id{i}": f"/runs/{p}/docker/docker-compose.yml"
                                   for i, p in enumerate(OTHERS)})
        self.assertEqual(cid, "", "must still refuse to guess")
        self.assertIn("NOT RUNNING", log)
        self.assertIn("#1130", log)

    def test_the_zero_case_no_longer_prescribes_disambiguation(self):
        """The old remedy could not work here and sent readers after the wrong thing."""
        _, log = _resolve(self, {f"id{i}": f"/runs/{p}/docker/docker-compose.yml"
                                 for i, p in enumerate(OTHERS)})
        self.assertNotIn("could not single one out", log)
        self.assertNotIn("Stop the stale stack", log)

    def test_the_ambiguous_case_keeps_the_962_wording(self):
        """M >= 2 is the case that message WAS written for; it must survive."""
        _, log = _resolve(self, {"idA": MINE, "idB": MINE})
        self.assertIn("could not single one out", log)
        self.assertIn("Stop the stale stack", log)
        self.assertNotIn("NOT RUNNING", log)

    def test_a_single_match_still_resolves(self):
        real = container_runtime.subprocess.run
        container_runtime.subprocess.run = _Docker(
            {"mine": MINE, "theirs": "/runs/rydr/docker/docker-compose.yml"})
        try:
            self.assertEqual(container_runtime.container_id(MINE, "database"), "mine")
        finally:
            container_runtime.subprocess.run = real


if __name__ == "__main__":
    unittest.main()
