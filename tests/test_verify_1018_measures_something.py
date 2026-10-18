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
    ("ns", "tiktok-web-r140", "FALSIFIED"),      # comments.body never got the dataset's text
    ("nt", "tiktok-web-r191", "FALSIFIED"),      # users.avatar set, avatar_url absent
    ("nt", "tiktok-web-r189", "FALSIFIED"),      # users + videos, both one-sided
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
                     "nm", "nn", "no", "np", "nq", "nr", "ns", "nt"):
            with self.subTest(criterion=crit):
                self.assertIn(crit, v)


class TheLogBackedCriteriaBite(unittest.TestCase):
    """#1203nr reads the RUN LOG, so the frozen triples above (which call the script with no
    --log) can only ever see it as N-A. Exercised here with the real log, which also drives
    the pairing guard's happy path."""

    def test_nr_is_falsified_on_a_pre_patch_run_with_its_own_log(self):
        run = _ROOT / "generated" / "tiktok-web-r190"
        logs = sorted(run.glob("logs/generation_*.log"))
        if not run.is_dir() or not logs:
            self.skipTest("tiktok-web-r190 or its log is not on this disk")
        p = subprocess.run([_PY, "-I", str(_SCRIPT), str(run), "--log", str(logs[-1])],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=900)
        line = next((l for l in (p.stdout or "").splitlines()
                     if l.split()[:1] == ["nr"]), "")
        self.assertIn("FALSIFIED", line,
                      "nr came back %r on a run whose log carries the stale cause 41 times"
                      % line)

    def test_the_log_was_actually_paired(self):
        """Non-vacuity: a log the script rejected would make every log-based criterion N-A
        and the assertion above would fail for the wrong reason."""
        run = _ROOT / "generated" / "tiktok-web-r190"
        logs = sorted(run.glob("logs/generation_*.log"))
        if not run.is_dir() or not logs:
            self.skipTest("tiktok-web-r190 or its log is not on this disk")
        p = subprocess.run([_PY, "-I", str(_SCRIPT), str(run), "--log", str(logs[-1])],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=900)
        line = next((l for l in (p.stdout or "").splitlines()
                     if l.split()[:1] == ["log"]), "")
        self.assertNotIn("IGNORED", line, line)
        self.assertIn("bytes", line, line)


class TheNtCriterionRespectsTheReferenceGuard(unittest.TestCase):
    """A twin holding a NON-reference value must not be reported as a one-sided twin.

    `#1203nt` deliberately refuses to mirror an initials blob or a colour into a url column,
    so a run in that shape is correct and the criterion has to agree. The corpus cannot test
    it -- every twin value it holds is a path or URL (avatar 70, thumbnail 62, thumbnail_url
    35, avatar_url 20, zero of any other shape) -- which is exactly why a mutation dropping
    the guard came back MISSED. A synthetic run tree is the only available control.
    """

    def _run_tree(self, tmp, avatar_value):
        be = tmp / "app" / "backend"
        be.mkdir(parents=True)
        (be / "models.py").write_text(
            "class User(Base):\n"
            '    __tablename__ = "users"\n'
            "    id = Column(Integer, primary_key=True)\n"
            "    avatar = Column(String)\n"
            "    avatar_url = Column(String)\n", encoding="utf-8")
        (be / "seed_dataset.json").write_text(
            json.dumps({"users": [{"id": 1, "avatar": avatar_value}]}), encoding="utf-8")
        return tmp

    def _nt(self, tmp):
        p = subprocess.run([_PY, "-I", str(_SCRIPT), str(tmp)],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=300)
        return next((l for l in (p.stdout or "").splitlines()
                     if l.split()[:1] == ["nt"]), "")

    def test_a_non_reference_twin_is_not_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            line = self._nt(self._run_tree(Path(d) / "fake-run", "AB"))
            self.assertNotIn("FALSIFIED", line,
                             "an initials blob was reported as a one-sided media twin, so "
                             "the criterion would fail a run #1203nt deliberately leaves "
                             "alone: %r" % line)

    def test_a_reference_twin_IS_reported(self):
        """Non-vacuity for the test above: the same tree with a real path must fire."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            line = self._nt(self._run_tree(Path(d) / "fake-run", "/assets/a.jpg"))
            self.assertIn("FALSIFIED", line, line)


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
