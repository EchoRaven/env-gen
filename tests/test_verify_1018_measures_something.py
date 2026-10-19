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
    ("oc", "tiktok-web-r190", "FALSIFIED"),      # 3 pages render `seededVideos`
    ("oc", "tiktok-web-r155", "FALSIFIED"),      # 6 sites on `tiktokData.videos`
    ("oc", "tiktok-web-r191", "CONFIRMED"),      # the healthy control, 0 sites
    ("oc", "tiktok-web-r185", "CONFIRMED"),      # a second healthy control
    ("od", "netflix-local-r35", "CONFIRMED"),    # 30 routed pages, 26 hidden from the old regex
    ("od", "tiktok-web-r191", "CONFIRMED"),      # identical under both readers
    ("od", "googlemaps-r15", "N-A"),             # declares no router at all
    ("of", "tiktok-web-r190", "FALSIFIED"),      # profile-fix.css draws the tabs as ▦/⚑/♡
    ("of", "tiktok-web-r183", "FALSIFIED"),      # `♪` beside an imported `Music2`
    ("of", "tiktok-web-r191", "CONFIRMED"),      # imports an icon set and uses no glyph
    ("of", "tiktok-web-r185", "N-A"),            # imports no icon set -> #1203kd's half
    ("og", "tiktok-web-r191", "FALSIFIED"),      # 10 syntax failures, none naming the file
    ("og", "tiktok-web-r190", "FALSIFIED"),      # 4 of its 10 (the rest are #1203mr's class)
    ("og", "tiktok-web-r189", "CONFIRMED"),      # 4 build failures, no syntax error
    ("og", "tiktok-web-r188", "N-A"),            # no build failure at all
    ("oi", "tiktok-web-r163", "FALSIFIED"),      # all 4 named screens drew nothing
    ("oi", "tiktok-web-r180", "FALSIFIED"),      # 3 of 4
    ("oi", "tiktok-web-r191", "CONFIRMED"),      # 2 named, none blank
    ("oi", "tiktok-web-r190", "CONFIRMED"),      # 5 named, none blank
    ("oj", "tiktok-web-r120", "FALSIFIED"),      # 78 breaking-change P0s sent to the wrong lane
    ("oj", "tiktok-web-r191", "FALSIFIED"),      # 17
    ("oj", "tiktok-web-r190", "FALSIFIED"),      # 2
    ("oj", "tiktok-web-r185", "N-A"),            # none; 0 contradicting records either
    # `ok` reads the LOG, and this harness scores runs without `--log` on purpose (it is the
    # path every criterion must survive), so N-A is the control here. Verified by hand with
    # the log: r190 -> CONFIRMED, "11 refusal(s); 0 of them hold a chain that never passed".
    ("ok", "tiktok-web-r190", "N-A"),
    ("ok", "tiktok-web-r191", "N-A"),
    ("ol", "tiktok-web-r171", "FALSIFIED"),      # 1 path-keyed inbox, 108 events
    ("ol", "tiktok-web-r190", "CONFIRMED"),
    ("ol", "tiktok-web-r191", "CONFIRMED"),
    # `om` falsifies on EVERY pre-patch backend (101 of 101), so these four are a sample of
    # the universal state rather than a selected case.
    ("om", "tiktok-web-r181", "FALSIFIED"),
    ("om", "tiktok-web-r190", "FALSIFIED"),
    ("om", "tiktok-web-r191", "FALSIFIED"),
    ("om", "googlemaps-r15", "FALSIFIED"),
    # `oo` is CONFIRMED post-patch wherever the contract restates a path parameter at all, and
    # N-A where it never does -- so both arms are frozen here. Pre-patch (verified by applying
    # mutation OO1 to the shipped note and re-running) these same runs answered FALSIFIED
    # 1/1, 5/5, 2/2 and 3/3.
    ("oo", "tiktok-web-r190", "CONFIRMED"),
    ("oo", "instagram-core-r175", "CONFIRMED"),
    ("oo", "tiktok-web-r184", "CONFIRMED"),
    ("oo", "tiktok-web-r191", "N-A"),
    # `op` reads each run's own git history, so it answers on any run directory. These are the
    # measured counts: 37 / 17 / 4 / 2 tasks naming a file that never existed, pre-patch.
    ("op", "netflix-local-r44", "FALSIFIED"),
    ("op", "tiktok-web-r191", "FALSIFIED"),
    ("op", "tiktok-web-r184", "FALSIFIED"),
    ("op", "tiktok-web-r190", "N-A"),
    # `oq` -- r107 is N-A on purpose: same shape, but it predates #1202vq's notice, so there
    # was no framework conclusion for the prose to contradict.
    ("oq", "tiktok-web-r166", "FALSIFIED"),
    ("oq", "tiktok-web-r190", "FALSIFIED"),
    ("oq", "tiktok-web-r107", "N-A"),
    ("oq", "tiktok-web-r191", "N-A"),
    # `or` pairs the run to its log beside the repo (`gm_<run>.log`), so it answers on any
    # modern tree. r190 is N-A: it holds no contradicted capability claim at all.
    ("or", "instagram-core-r175", "FALSIFIED"),
    ("or", "tiktok-web-r185", "FALSIFIED"),
    ("or", "tiktok-web-r191", "FALSIFIED"),
    ("or", "tiktok-web-r190", "N-A"),
    # `os` reads the LOG, and this harness calls the script WITHOUT --log on purpose (the path
    # every criterion must survive), so N-A is the control here. Verified by hand with the
    # log: r191 -> FALSIFIED "10 findings still wear the #1201 template, 0 genuine
    # mechanism-off lines", r190 -> 8, r185 -> 10.
    ("os", "tiktok-web-r191", "N-A"),
    ("os", "tiktok-web-r190", "N-A"),
    # `ot` also reads the LOG, so N-A is the no---log control. Verified by hand with the log:
    # r190 -> FALSIFIED "797 lines for 1 distinct resolution", r191 427/1, r185 607/1.
    ("ot", "tiktok-web-r190", "N-A"),
    ("ot", "tiktok-web-r191", "N-A"),
    # `ou` reads the LOG too. Verified by hand with it: r190 -> FALSIFIED "212 lines for 5
    # distinct kept-page decisions", r183 208/17, r185 110/14, r191 88/9.
    ("ou", "tiktok-web-r190", "N-A"),
    ("ou", "tiktok-web-r191", "N-A"),
    # `ov` reads the LOG too. Verified by hand with it: r191 -> FALSIFIED "2 lines report a
    # silent walk as a failed login", r183 1, r185 1; r190 -> N-A (no all-empty line).
    ("ov", "tiktok-web-r191", "N-A"),
    ("ov", "tiktok-web-r190", "N-A"),
    # `ox` lives only in the run log, so the no-log call is N-A by construction; with the
    # log it is FALSIFIED on every run on this disk (14 lines each, one per profile).
    ("ox", "tiktok-web-r191", "N-A"),
    ("ox", "tiktok-web-r190", "N-A"),
    # `oy` reads codehub_releases.json, so it answers without a log: both runs cut releases
    # whose notes omit the visual verdict the same record carries.
    ("oy", "tiktok-web-r191", "FALSIFIED"),
    ("oy", "tiktok-web-r190", "FALSIFIED"),
    # `p2` lives only in the run log, so the no-log call is N-A by construction. With the
    # log, every pre-patch run is FALSIFIED: the condition held and the recorder did not
    # exist yet. Its CONFIRMED and N-A verdicts are BOTH answers -- see the criterion.
    ("p2", "tiktok-web-r191", "N-A"),
    ("p2", "tiktok-web-r190", "N-A"),
    # `p4` reads the EVENT STORE for the condition and the log for the answer, so without a
    # log it stops at "there was something to say and no log to check it in". r191 is N-A on
    # the artifact alone: every breaking change there had a consumer to tell.
    ("p4", "tiktok-web-r191", "N-A"),
    ("p4", "tiktok-web-r190", "N-A"),
    # `p6` reads two artifacts and no log, so it answers with or without one. Both runs
    # dispatched visual tasks (r191 9, r190 37) and named no UI skill in any of them.
    ("p6", "tiktok-web-r191", "FALSIFIED"),
    ("p6", "tiktok-web-r190", "FALSIFIED"),
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


# ---------------------------------------------------------------------------
# #1203oh — a criterion must be able to CONFIRM what it predicts.
# ---------------------------------------------------------------------------
# `og` shipped unable to: its CONFIRMED branch looked for the `#1203og` marker inside
# `compose_build_failure*.log`, a file `_compose` writes from the docker transcript alone, so
# no run could ever have satisfied it. The #947 ratchet caught the same defect one layer down
# (the finding reached a logger and a detail string, not a file) and following it is what
# surfaced this. Nothing checked the criterion itself.
#
# MEASURED, scoring all 104 corpus runs with each run's own generation log: 7 criteria are
# NEVER CONFIRMED anywhere (nf, nn, no, np, nq, nr, nt) -- which is CORRECT, because the
# corpus has no post-fix run and their CONFIRMED side asks for a sentence the patch only
# started emitting today. The audit cannot tell that apart from `og`'s defect by counting, so
# this table does it by mechanism: for each criterion, the strings the FRAMEWORK must emit for
# its CONFIRMED branch to be reachable. Every one is grepped for below.
#
# ★ THE AUDIT ALSO CAUGHT MY OWN INSTRUMENT. Scored without `--log`, five criteria (n5, n8,
# nc, nd, nr) read as "ALWAYS N-A, measures nothing on this corpus" -- they are log-based, and
# I had not passed the log. With it they are 39 CONFIRMED / 1 FALSIFIED each and `nr` shows 38
# FALSIFIED, which is exactly the 38 runs its own record names. A criterion that looks dead is
# a reason to check the harness first.
_CONFIRM_REQUIRES = {
    # the framework must say this for the criterion to be able to confirm
    "nf": ["#1203nf"],
    "nn": ["recorded gate evaluations"],
    "no": ["cannot both be right"],
    "np": ["seeded media reference"],
    "nr": ["IS declared in", "declares NO database service"],
    "od": ["noop|dummy|placeholder|todo|fixme|untitled|testpage|foobar|temppage"],
    # CONFIRMED comes from a measurement the criterion computes itself (a count, a ratio, a
    # parsed artifact), so there is no framework sentence to depend on.
    "n5": [], "n6": [], "n8": [], "n9": [], "nc": [], "nd": [], "ne": [], "nh": [],
    "ni": [], "nm": [], "nq": [], "ns": [], "nt": [], "oc": [], "of": [],
    # `og` reads its own recorder's artifact; the esbuild words it counts are a THIRD PARTY's
    # output, which is the distinction its first version got wrong.
    "og": [],
    # `oi` CONFIRMED needs the carve-out sentence the patched task body writes.
    "oi": ["near-zero ink against its own reference"],
    # `oj` CONFIRMED needs the note the corrected task description carries.
    "oj": ["this endpoint's consumer record was registered by"],
    # `ok` counts the freeze's own refusal sentence in the log.
    "ok": ["is frozen"],
    # `ol` reads inbox KEYS, not a framework sentence -- CONFIRMED is the absence of a
    # path-shaped one, which needs nothing emitted.
    "ol": [],
    # `om` CONFIRMED needs the header the patched guard template sets on its own 4xx.
    "om": ["Access-Control-Allow-Origin"],
    # `oo` renders the contract through the framework's own note function and reads the
    # labels back; CONFIRMED is a property of that output, not of anything the run emitted.
    "oo": [],
    # `op` CONFIRMED needs the note the patched task builder writes into the description.
    "op": ["#1203op"],
    # `oq` CONFIRMED needs the rewritten instruction the patched dispatch writes.
    "oq": ["never answered the business endpoints"],
    # `or` CONFIRMED needs the ledger line its own recorder writes.
    "or": ["contradicted_capability_claims_1203or"],
    # `os` CONFIRMED needs the marker the new announcer prints.
    "os": ["#1203os"],
    # `ot` counts lines against distinct bodies in the log; nothing has to be emitted for it
    # to be able to confirm.
    "ot": [],
    # `ou` counts lines against distinct bodies in the log; nothing has to be emitted.
    "ou": [],
    # `ov` CONFIRMED needs the wording the patched summary/signal emits.
    "ov": ["no login steps recorded"],
    # `ox` CONFIRMED needs the startup line to state the condition instead of the outcome.
    "ox": ["leaves the ranker a free slot"],
    # `oy` CONFIRMED needs the release note to carry the verdict clause.
    "oy": ["Visual verdict:"],
    # `p2` CONFIRMED needs the recorder's own line.
    "p2": ["omitted `apis_used` for the"],
    # `p4` CONFIRMED needs the no-consumer announcement.
    "p4": ["reached NO ONE"],
    # `p6` CONFIRMED needs the pointer the remediation body now carries.
    "p6": ["Two skills are about this exact job"],
}


def _unclassified_1203oh(found, table):
    """``(criteria with no table entry, table entries the script no longer has)``.

    A pure function because the assertion that used it could not fail on real data -- see
    `test_the_classification_check_can_actually_fail`.
    """
    return (sorted(set(found) - set(table)), sorted(set(table) - set(found)))


def _criteria_in_script():
    """The criterion ids the checker actually reports."""
    import re
    src = _SCRIPT.read_text(encoding="utf-8")
    found = set(re.findall(r'say\(\s*"([a-z0-9]{2})"', src))
    found.discard("lo")                          # the INFO row, not a criterion
    return found


class ACriterionCanConfirmWhatItPredicts(unittest.TestCase):
    """#1203oh. The half nothing was checking: `og` shipped with a CONFIRMED branch whose
    input could never contain the marker it looked for."""

    @staticmethod
    def _framework_source():
        """The framework's sources with ADJACENT-STRING CONCATENATION collapsed.

        Without that, `"… recorded gate "` + `"evaluations; …"` on the next line is not
        contiguous text and the search misses a sentence the framework really does emit --
        which is how the first version of this test failed on #1203nn.

        ★ EXCLUDED BY DIRECTORY, NOT BY NAME (#1203ov). `"test" in f.name` skipped TEN files,
        and only seven of them are tests (`multi_agent/bundled_tests/oauth_contract/*`). The
        other three -- `runtime/test_user_runner.py`, `runtime/test_user_squad.py`,
        `runtime/test_user_validation.py` -- are framework modules, so every sentence they
        emit was invisible to this check. It surfaced when #1203ov's required sentence lives
        in `test_user_runner.py` and the checker reported no emitter for a line the framework
        prints. Second time this checker's own reader was the bug (the first was calling the
        script without `--log`). A filter has to key on the ROLE, which here is the
        directory, not on the spelling of the filename.
        """
        import re as _re
        root = _ROOT / "agent" / "env_generator" / "llm_generator"
        out = []
        for f in root.rglob("*.py"):
            if ({"tests", "bundled_tests", "node_modules"} & set(f.parts)):
                continue
            try:
                out.append(f.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
        src = "\n".join(out)
        return _re.sub(r"""["']\s*\n\s*(?:f|r|rf|fr)?["']""", "", src)

    def test_the_source_reader_keeps_the_test_user_modules(self):
        """★ #1203ov: `runtime/test_user_runner.py` is framework source whose NAME starts with
        `test`. A name filter dropped it and two siblings, so every sentence they emit read as
        "no emitter". Pinned by content, not by the filter's shape."""
        src = self._framework_source()
        self.assertGreater(len(src), 100000)
        for needle, why in (
                ("no login steps recorded", "test_user_runner.py (#1203ov)"),
                ("did not finish within", "test_user_squad.py (#1203kk)")):
            with self.subTest(file=why):
                self.assertIn(needle, src,
                              "the reader is skipping %s again -- filter by DIRECTORY, not "
                              "by filename" % why)

    def test_the_source_reader_still_excludes_real_tests(self):
        """...and the exclusion it does need is still in force: the bundled OAuth contract
        tests under `bundled_tests/` must stay out, or a sentence that only a TEST contains
        would count as an emitter."""
        src = self._framework_source()
        self.assertNotIn("WHATSAPP_EXPECTED_AUDIENCE", src)
        self.assertNotIn("SLACK_EXPECTED_AUDIENCE", src)

    def test_every_required_sentence_has_an_emitter(self):
        src = self._framework_source()
        self.assertGreater(len(src), 100000, "the framework source did not load")
        missing = []
        for crit, needs in sorted(_CONFIRM_REQUIRES.items()):
            for lit in needs:
                if lit not in src:
                    missing.append((crit, lit))
        # NOT assertIn: the haystack is 10 MB and unittest would print it.
        self.assertEqual(missing, [],
                         "these criteria can only CONFIRM when the framework says something "
                         "nothing in it says -- that is `og`'s defect: %s"
                         % [(c, l[:50]) for c, l in missing])

    def test_every_criterion_is_classified(self):
        """Anti-vacuity: a criterion added without an entry here would skip the check above,
        which is how `og` got in."""
        found = _criteria_in_script()
        self.assertGreaterEqual(len(found), 20, "the criterion scan found almost nothing")
        self.assertEqual(_unclassified_1203oh(found, _CONFIRM_REQUIRES), ([], []),
                         "left: criteria with no entry; right: entries for a criterion the "
                         "script no longer has")

    def test_the_classification_check_can_actually_fail(self):
        """★ The mutation that taught me this: flipping the comparison above to `set() - ...`
        read MISSED, because with the real table every criterion IS classified, so both sides
        are empty either way. A check that cannot fail on the data it is given is not a check
        (#1202w0's shape), so the comparison is a pure function tested on synthetic input."""
        self.assertEqual(_unclassified_1203oh({"aa", "bb"}, {"aa": []}), (["bb"], []))
        self.assertEqual(_unclassified_1203oh({"aa"}, {"aa": [], "zz": []}), ([], ["zz"]))
        self.assertEqual(_unclassified_1203oh({"aa"}, {"aa": ["x"]}), ([], []))

    def test_the_table_is_not_all_empty(self):
        """If every entry were `[]` the check above would pass by saying nothing."""
        self.assertGreaterEqual(
            len([c for c, v in _CONFIRM_REQUIRES.items() if v]), 5,
            "no criterion depends on a framework sentence any more, so this ratchet is inert")


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
                     "nm", "nn", "no", "np", "nq", "nr", "ns", "nt", "oc",
                     "od", "of", "og", "oi", "oj", "ok", "ol", "om", "oo", "op", "oq", "or", "os", "ot", "ou", "ov",
                     "ox", "oy", "p2", "p4", "p6"):
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
