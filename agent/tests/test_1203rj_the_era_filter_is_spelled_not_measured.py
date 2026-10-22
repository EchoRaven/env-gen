r"""#1203rj -- "modern era" is decided by how a run DIRECTORY IS SPELLED, so it means "tiktok".

Eight test files place a run in the modern era with

    m = re.search(r"r(\d+)$", run)
    if m and int(m.group(1)) >= 183: ...

(test_1203kv, kx, ky, kz, l0, l2, ov, this_sessions_numbers_still_hold_880.) A run whose
directory does not end in `r<digits>` cannot be placed at all, and is silently dropped from
every modern-era measurement those files pin.

MEASURED over the 108 corpus runs. Seven cannot be placed by name, and dating them from the
framework's OWN timestamps (`_meta.last_modified_at` and per-record `created_at` in
`shared/hubs/*.json`) rather than from filesystem mtime:

    googlemaps-core-di.SUCCESS-gmrun{3,4,7}      2026-07-14 / 07-15   genuinely old
    instagram-core-di.SUCCESS-run70-...          2026-07-12           genuinely old
    outlook-mm4, outlook-seed3                   not datable          no shared/hubs at all
    instagram-core-di                            2026-10-21           NEWER THAN THE WHOLE ERA

The era floor is `tiktok-web-r183` at 2026-10-11, and the nine runs the filter calls modern are
**9 of 9 `tiktok-web`**. So two things follow: the only run that is modern by date and not
tiktok is dropped, and every modern-era measurement built on this filter is single-product BY
CONSTRUCTION -- which is the mechanism behind "generality cannot be measured on this corpus"
rather than a coincidence about what was run.

DO NOT DATE A RUN BY ITS DIRECTORY MTIME. The googlemaps trees read 2026-09-19 by mtime and
2026-07-14 by their own artifacts, two months apart, because the directories were copied later.
The first version of this measurement used mtime and got every date wrong while reaching the
right conclusion.

WHY THIS IS A GUARD AND NOT A REWRITE OF THE FILTER: changing the eight files to date-based
eras moves numbers they pin exactly (test_1203ov's modern squad pair would go 95/47 -> 105/48,
for one), and each would need re-measuring and re-arguing. This costs nothing and makes the
blind spot impossible to grow: add a second non-tiktok modern run and this turns red naming it.
"""
import glob
import json
import os
import re
import unittest
from pathlib import Path

_CORPUS = Path(__file__).resolve().parents[2] / "generated"

# The era filter as the eight files spell it, kept here verbatim so this guard breaks if they
# are ever changed to something else (at which point the premise above needs re-checking).
_NAME_ERA = re.compile(r"r(\d+)$")
_MODERN_FLOOR = 183

# Baselined, each with the reason it is not a defect. A NEW entry in either set is.
_KNOWN_UNPLACEABLE_MODERN = {"instagram-core-di"}
_KNOWN_UNDATABLE = {"outlook-mm4", "outlook-seed3"}


def _baseline_diff_1203rj(observed, baseline):
    """``(unexpected, vanished)`` -- an EXACT set comparison, both directions.

    Extracted because the live-corpus assertion cannot be driven: today `observed` already
    equals `baseline`, so weakening `==` to a subset test changes nothing a mutation could
    show (RJD came back MISSED on exactly that). The same reason #1203rf extracted
    `_baseline_delta_1203rf`. Both halves matter and for different reasons: `unexpected`
    is the blind spot growing, `vanished` is the guard going blind, and a guard going
    blind must not look like the defect being fixed.
    """
    return sorted(set(observed) - set(baseline)), sorted(set(baseline) - set(observed))


def _runs():
    return sorted(os.path.basename(p) for p in glob.glob(str(_CORPUS / "*"))
                  if os.path.isdir(p))


def _name_era(run):
    """The era number the eight files would read off this run's name, or None."""
    m = _NAME_ERA.search(run)
    return int(m.group(1)) if m else None


def _artifact_date(run):
    """Earliest timestamp the FRAMEWORK wrote into this run's hub artifacts, or None.

    Not mtime: see the module docstring. `_meta.last_modified_at` and each record's
    `created_at` are written by the hubs themselves and survive a copy.
    """
    best = None
    for f in glob.glob(str(_CORPUS / run / "shared" / "hubs" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        cands = []
        meta = d.get("_meta")
        if isinstance(meta, dict) and isinstance(meta.get("last_modified_at"), (int, float)):
            cands.append(meta["last_modified_at"])
        for v in d.values():
            if isinstance(v, dict) and isinstance(v.get("created_at"), (int, float)):
                cands.append(v["created_at"])
        for v in cands:
            # A plausible unix-seconds window; the hubs have carried junk values before.
            if 1.6e9 < v < 2.0e9 and (best is None or v < best):
                best = v
    return best


def _synthetic(tmp, runs):
    """Build a corpus of {run: timestamp-or-None} and return its path.

    The guard's real assertions read the live corpus, which cannot be mutated -- and a guard
    validated by mutating its own assertions proves nothing (a ratchet cannot verify itself).
    So the helpers are driven over a corpus built here, where the violation is PLANTED and the
    expected answer is known independently of what the assertions say.
    """
    for name, ts in runs.items():
        d = tmp / name
        if ts is None:                      # a salvaged tree: app/ only, no hubs
            (d / "app").mkdir(parents=True)
            continue
        h = d / "shared" / "hubs"
        h.mkdir(parents=True)
        (h / "registryhub_ui_pages.json").write_text(
            json.dumps({"_meta": {"last_modified_at": ts},
                        "p": {"created_at": ts, "name": "p"}}), encoding="utf-8")
    return tmp


class TheGuardDetectsAPlantedViolation(unittest.TestCase):
    """Drives the helpers over a SYNTHETIC corpus, so a planted offender has a known answer."""

    OLD, MID, NEW = 1.7000e9, 1.7600e9, 1.7930e9

    def _with(self, runs):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        _synthetic(tmp, runs)
        return tmp

    def _scan(self, corpus):
        """The guard's own computation, run against `corpus`."""
        global _CORPUS
        saved = globals()["_CORPUS"]
        globals()["_CORPUS"] = corpus
        try:
            runs = _runs()
            dates = [d for r in runs if (_name_era(r) or 0) >= _MODERN_FLOOR
                     for d in [_artifact_date(r)] if d]
            floor = min(dates) if dates else None
            offenders = {r for r in runs if _name_era(r) is None
                         and (_artifact_date(r) or 0) >= (floor or 0) and floor is not None}
            undatable = {r for r in runs if _artifact_date(r) is None}
            return floor, offenders, undatable
        finally:
            globals()["_CORPUS"] = saved

    def test_a_newer_unnamed_run_is_detected(self):
        """THE PLANTED CASE: a run newer than the era floor whose name carries no `r<N>`."""
        c = self._with({"tiktok-web-r200": self.MID, "newproduct-core-di": self.NEW})
        floor, off, _und = self._scan(c)
        self.assertEqual(floor, self.MID)
        self.assertEqual(off, {"newproduct-core-di"})

    def test_an_older_unnamed_run_is_not_detected(self):
        """COUNTER-PROOF: being unnameable is not the defect; being unnameable AND modern is.
        The googlemaps and outlook trees are exactly this case in the live corpus."""
        c = self._with({"tiktok-web-r200": self.MID, "oldproduct-core-di": self.OLD})
        _floor, off, _und = self._scan(c)
        self.assertEqual(off, set(), "an older unplaceable run must not be reported")

    def test_a_tree_with_no_hubs_is_reported_as_undatable_not_as_old(self):
        """The two outlook trees. Undatable must be its own answer -- calling them 'old'
        would hide a run the guard simply cannot see."""
        c = self._with({"tiktok-web-r200": self.MID, "salvaged-tree": None})
        _floor, off, und = self._scan(c)
        self.assertEqual(und, {"salvaged-tree"})
        self.assertNotIn("salvaged-tree", off)

    def test_mtime_would_have_given_the_wrong_answer(self):
        """Why the date comes from artifacts. The synthetic trees are written NOW, so by mtime
        every one of them is 'modern' and the old run would be a false offender."""
        c = self._with({"tiktok-web-r200": self.MID, "oldproduct-core-di": self.OLD})
        by_mtime = {r for r in sorted(os.path.basename(p) for p in glob.glob(str(c / "*")))
                    if _name_era(r) is None
                    and os.path.getmtime(str(c / r)) >= os.path.getmtime(str(c / "tiktok-web-r200"))}
        self.assertIn("oldproduct-core-di", by_mtime,
                      "the premise of this test is that mtime cannot tell these apart")
        _floor, off, _und = self._scan(c)
        self.assertEqual(off, set(),
                         "the artifact dates must separate what mtime cannot")


class TheBaselineComparisonIsExactInBothDirections(unittest.TestCase):
    """Drives `_baseline_diff_1203rj` directly, because the live sets agree today and so a
    subset test and an equality test cannot be told apart from the corpus alone."""

    def test_a_new_member_is_reported(self):
        unexpected, vanished = _baseline_diff_1203rj({"a", "b", "c"}, {"a", "b"})
        self.assertEqual(unexpected, ["c"], "the blind spot growing must be named")
        self.assertEqual(vanished, [])

    def test_a_member_that_disappeared_is_reported(self):
        unexpected, vanished = _baseline_diff_1203rj({"a"}, {"a", "b"})
        self.assertEqual(vanished, ["b"], "the guard going blind must be named too")
        self.assertEqual(unexpected, [])

    def test_agreement_reports_nothing(self):
        self.assertEqual(_baseline_diff_1203rj({"a", "b"}, {"b", "a"}), ([], []))


class TheEraFilterIsSpelledNotMeasured(unittest.TestCase):

    def setUp(self):
        if not _CORPUS.is_dir():
            self.skipTest("no corpus on this disk")
        self.runs = _runs()
        if len(self.runs) < 20:
            self.skipTest("corpus too small to reason about eras (%d runs)" % len(self.runs))

    def _floor(self):
        """The era floor as a DATE: the earliest artifact date among name-modern runs."""
        dates = [d for r in self.runs
                 if (_name_era(r) or 0) >= _MODERN_FLOOR
                 for d in [_artifact_date(r)] if d]
        self.assertTrue(dates, "no name-modern run could be dated, so there is no floor")
        return min(dates)

    def test_no_run_is_modern_by_date_while_unplaceable_by_name(self):
        """THE GUARD. A run newer than the era floor whose name has no `r<N>` is invisible to
        every modern-era measurement, and nothing says so."""
        floor = self._floor()
        offenders = set()
        for r in self.runs:
            if _name_era(r) is not None:
                continue
            d = _artifact_date(r)
            if d is not None and d >= floor:
                offenders.add(r)
        new = offenders - _KNOWN_UNPLACEABLE_MODERN
        self.assertFalse(
            new,
            "these run(s) are modern by the framework's own timestamps but cannot be placed "
            "by the `r(\\d+)$` filter, so eight test files drop them from every modern-era "
            "measurement: %r. Either name them `...r<N>` or move those files to dates."
            % sorted(new))
        gone = _KNOWN_UNPLACEABLE_MODERN - offenders
        self.assertFalse(
            gone,
            "%r no longer looks modern-but-unplaceable; if the corpus or the filter changed, "
            "re-measure the premise in this module's docstring instead of deleting the "
            "baseline" % sorted(gone))

    def test_every_run_can_be_dated_except_the_ones_with_no_hub_artifacts(self):
        """A guard that cannot date a run has only moved the blind spot, so name the gap."""
        undatable = {r for r in self.runs if _artifact_date(r) is None}
        unexpected, vanished = _baseline_diff_1203rj(undatable, _KNOWN_UNDATABLE)
        self.assertFalse(
            unexpected,
            "run(s) with no framework timestamp that are not baselined: %r. A new one means "
            "this guard silently stopped covering a run." % unexpected)
        self.assertFalse(
            vanished,
            "%r can be dated now, so the reason it was baselined no longer holds; re-check "
            "the premise instead of deleting the entry" % vanished)
        for r in sorted(_KNOWN_UNDATABLE):
            self.assertFalse(
                glob.glob(str(_CORPUS / r / "shared" / "hubs" / "*.json")),
                "%s was baselined as undatable BECAUSE it has no hub artifacts; it has some "
                "now, so it can and should be dated" % r)

    def test_the_modern_era_the_filter_produces_is_one_product(self):
        """The consequence, stated so it cannot be forgotten: the filter's modern set is all
        one product, while a non-tiktok run IS modern by date. That pairing is the defect --
        the counter-example exists and the instrument cannot see it."""
        named_modern = [r for r in self.runs if (_name_era(r) or 0) >= _MODERN_FLOOR]
        self.assertTrue(named_modern, "no modern runs by name at all")
        products = {r.split("-r")[0] for r in named_modern}
        self.assertEqual(
            products, {"tiktok-web"},
            "the name-based modern era is no longer single-product (%r) -- good news, and the "
            "generality note that cites this needs updating" % sorted(products))
        floor = self._floor()
        counter = {r for r in self.runs
                   if _name_era(r) is None
                   and (_artifact_date(r) or 0) >= floor
                   and not r.startswith("tiktok")}
        self.assertTrue(
            counter,
            "the premise of this module was that a non-tiktok run is modern by date while the "
            "filter hides it; none is, so re-measure before trusting the docstring")


if __name__ == "__main__":
    unittest.main()
