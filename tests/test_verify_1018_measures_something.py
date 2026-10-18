r"""`scripts/verify_1018.py` must still BITE on a pre-patch run.

The script's own docstring states the failure mode it exists to avoid -- "A checker that
reports CONFIRMED on a pre-patch run is measuring nothing" -- and then validates itself only
by being run by hand. That is #826's shape exactly ("a check that lives in a habit is not a
check"), and it is the same shape as `scripts/mutate.py`, which has its own test for the same
reason.

What can go wrong silently: a criterion reads a field that gets renamed, or a ledger that stops
being written, and the verdict turns N-A. An accidental N-A is indistinguishable from a
legitimate one ("this run has no json columns"), so the next run's report would look clean
while measuring nothing. The triples below freeze the control answers that were checked when
each criterion was written.

Corpus-dependent by nature: each case SKIPS when its control run is no longer on this disk.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "verify_1018.py"
_PY = os.environ.get("SUITE_PYTHON", sys.executable)

# (criterion, control run, expected verdict) -- the answer recorded when it was written.
_CONTROLS = [
    ("nm", "tiktok-web-r190", "FALSIFIED"),      # 47 of 53 lines name a dotted column
    ("nm", "tiktok-web-r166", "FALSIFIED"),      # 52 of 52
    ("nn", "tiktok-web-r190", "FALSIFIED"),      # 467 of 467 gate records
    ("no", "tiktok-web-r183", "FALSIFIED"),      # 65 of 65 rows assert a direction
    ("np", "tiktok-web-r190", "FALSIFIED"),      # 83 ledger rows, 0 tasks
    ("nq", "tiktok-web-r182", "FALSIFIED"),      # 318 remapped rows unannotated
    ("n6", "tiktok-web-r190", "FALSIFIED"),      # 3 of 3 test-user reports ERRORed
]

_cache = {}


def _verdicts(run_name):
    """{criterion: verdict} for one run, via one subprocess call."""
    if run_name in _cache:
        return _cache[run_name]
    run = _ROOT / "generated" / run_name
    if not run.is_dir():
        _cache[run_name] = None
        return None
    p = subprocess.run([_PY, "-I", str(_SCRIPT), str(run)],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=600)
    out = {}
    for line in (p.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("CONFIRMED", "FALSIFIED", "N-A", "INFO"):
            out[parts[0]] = parts[1]
    _cache[run_name] = out or None
    return _cache[run_name]


class TheCheckerStillBites(unittest.TestCase):
    def test_the_script_exists_and_runs(self):
        self.assertTrue(_SCRIPT.is_file(), str(_SCRIPT))
        p = subprocess.run([_PY, "-I", str(_SCRIPT)], cwd=str(_ROOT),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 2, "no-argument call must print usage and exit 2")
        self.assertIn("PRE-REGISTERED", p.stdout)

    def test_every_control_still_returns_its_recorded_verdict(self):
        checked = 0
        for crit, run_name, want in _CONTROLS:
            v = _verdicts(run_name)
            if v is None:
                continue
            with self.subTest(criterion=crit, run=run_name):
                self.assertIn(crit, v,
                              "criterion %r is gone from the report for %s" % (crit, run_name))
                self.assertEqual(v[crit], want,
                                 "%s on %s: recorded %s, now %s — either the patch regressed "
                                 "or the criterion stopped measuring"
                                 % (crit, run_name, want, v[crit]))
                checked += 1
        if not checked:
            self.skipTest("none of the control runs is on this disk")

    def test_a_pre_patch_run_is_not_reported_clean(self):
        """The whole point, stated as one assertion: r190 predates every one of these
        patches, so its report must carry falsifications."""
        v = _verdicts("tiktok-web-r190")
        if v is None:
            self.skipTest("tiktok-web-r190 is not on this disk")
        bad = [k for k, x in v.items() if x == "FALSIFIED"]
        self.assertGreaterEqual(len(bad), 5,
                                "a run that predates all of these patches came back almost "
                                "clean (%d falsified): %s" % (len(bad), sorted(v.items())))

    def test_the_criteria_are_all_present(self):
        """A criterion silently dropped from the script would make its ticket unverifiable."""
        v = _verdicts("tiktok-web-r190")
        if v is None:
            self.skipTest("tiktok-web-r190 is not on this disk")
        for crit in ("n5", "n6", "n8", "n9", "nc", "nd", "ne", "nf", "nh", "ni",
                     "nm", "nn", "no", "np", "nq"):
            with self.subTest(criterion=crit):
                self.assertIn(crit, v)


class TheLogPairingGuardStillWorks(unittest.TestCase):
    """A log from ANOTHER run must not produce confident numbers -- the script records that
    this once gave "five answers about a run the log never watched"."""

    def test_a_foreign_log_is_ignored_with_a_reason(self):
        runs = sorted((_ROOT / "generated").glob("*/logs/generation_*.log")) \
            if (_ROOT / "generated").is_dir() else []
        if len(runs) < 2:
            self.skipTest("need two runs with logs on this disk")
        target = runs[-1].parents[1]
        foreign = next((p for p in runs if p.parents[1] != target), None)
        if foreign is None:
            self.skipTest("no log belonging to a different run")
        p = subprocess.run([_PY, "-I", str(_SCRIPT), str(target), "--log", str(foreign)],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=600)
        self.assertIn("IGNORED", p.stdout,
                      "a log from another run was accepted: %s" % p.stdout[:300])


if __name__ == "__main__":
    unittest.main()
