r"""#1203oi: a screen that rendered NOTHING is not an empty state.

`empty_state` is the visual judge's SEMANTIC reading ("this looks like an empty-state UI").
`#1203ny` measures whether the capture has any INK at all against its own reference. Different
questions — and they overlap, so the task built from the first has been telling lanes the wrong
thing about screens that belong to the second.

MEASURED over the corpus: 73 runs filed the EMPTY-state task, and in 65 of them the delivered
tree carries no blank capture — the dispatch→work→fixed chain holds on this axis (the task
completes in 86 of 93 cases). In the 8 runs that DO still have a blank capture, SEVEN name a
blank screen in that very task, 13 screens in all:

    tiktok-web-r163      4 named, 4 blank  (explore_grid inks 0.27% vs 16.44%, ratio 0.016)
    tiktok-web-r180      4 named, 3 blank
    tiktok-web-r169      4 named, 1 blank
    gmrun3 / gmrun4 / gmrun7 / instagram-run70     2 / 1 / 1 / 1

For those screens both of the body's diagnoses are wrong: "seed the missing rows" and "a
read-path bug (filters/owner-scoping)". That is the same cost #1202ff fixed one level up — a
round burned on the wrong lane.

★ THE ASSIGNEE DOES NOT CHANGE, and that is measured too: 1 of the 7 runs is all-blank and 6
are mixed, so a blank-only routing rule would fire once while a mixed task belongs with the
backend anyway. What the lane needs is to be told which of its screens are not its question.
The TITLE changes only in the all-blank case, which is #1202ff's own rule.

★ AND ONE MIS-ATTRIBUTION I CAUGHT ON THE WAY: seeing 8 runs with blank captures after a
completed task, I nearly reported "completed did not mean fixed". It does not follow — the two
measures are different, and the existing check never claimed to be about ink. The finding is
the OVERLAP, not the completion rate.
"""
import ast
import inspect
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF


def _gate_source():
    """The source of the method that builds the empty-state task."""
    src = inspect.getsource(VF)
    i = src.index("_title_1202ff")
    j = src.rindex("_empty = sorted(", 0, i)
    k = src.index("visual fidelity gate raised", i)
    return src[j:k]


def _names_in(node):
    import ast as _a
    return {n.id for n in _a.walk(node) if isinstance(n, _a.Name)}


def _empty_state_task_call():
    """The `create_task(...)` Call that builds the EMPTY-state task, from the AST.

    ★ Source-TEXT assertions cannot see wiring: dropping `+ _blank_note_1203oi` from the
    description leaves the NAME defined above, so `"_blank_note_1203oi" in source` stays true
    and mutation OI1 read MISSED. The same shape made OI2 (`if False and …`) invisible. So the
    structure is read, not the text.
    """
    import ast as _a
    tree = _a.parse(inspect.getsource(VF))
    for node in _a.walk(tree):
        if not isinstance(node, _a.Call):
            continue
        if getattr(node.func, "attr", "") != "create_task":
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        tv = kw.get("title")
        if tv is not None and "_title_1202ff" in _names_in(tv):
            return kw
    raise AssertionError("the EMPTY-state create_task call was not found")


def _title_if_1203oi():
    """The `If` whose body assigns the all-blank title."""
    import ast as _a
    tree = _a.parse(inspect.getsource(VF))
    found = []
    for node in _a.walk(tree):
        if not isinstance(node, _a.If):
            continue
        dumped = _a.dump(_a.Module(body=node.body, type_ignores=[]))
        if "rendered NOTHING (near-zero ink" in dumped and "_title_1202ff" in dumped:
            found.append(node)
    if not found:
        raise AssertionError("the all-blank title branch was not found")
    # the INNERMOST one: an enclosing `if _empty and not self._seed_reminder_sent:` also has
    # the string in its body, and matching it first is how the first version of this helper
    # read the wrong condition.
    return min(found, key=lambda n: (n.end_lineno or 0) - n.lineno)


class TheBlankScreensAreNamedSeparately(unittest.TestCase):
    def test_the_task_body_carves_them_out(self):
        """AST, not text: the note must be part of the `description` the task is built with."""
        kw = _empty_state_task_call()
        self.assertIn("_blank_note_1203oi", _names_in(kw["description"]),
                      "the carve-out is defined but never reaches the description")
        s = _gate_source()
        self.assertIn("did not RENDER at all", s)
        self.assertIn("do NOT add seed rows", s)

    def test_the_note_says_what_to_look_at_instead(self):
        s = _gate_source()
        for want in ("crashed component", "failed bundle", "404 on the"):
            with self.subTest(phrase=want):
                self.assertIn(want, s)

    def test_the_remaining_screens_still_get_the_old_advice(self):
        """The carve-out must not blank the diagnosis for screens that DID render."""
        s = _gate_source()
        self.assertIn("REMAINING screen(s) only", s)
        self.assertIn("+ _diag +", s)

    def test_the_backend_message_carries_it_too(self):
        s = _gate_source()
        i = s.index("_create_message")
        self.assertIn("#1203oi", s[i:])
        self.assertIn("rendered NOTHING", s[i:])


class TheTitleCarriesTheVerdict(unittest.TestCase):
    """#1202ff's rule: the title must say what the body reached."""

    def test_an_all_blank_set_gets_its_own_title(self):
        """AST: the branch's CONDITION must actually read the blank set -- `if False and …`
        leaves the string in the source and mutation OI2 read MISSED against the text form."""
        import ast
        node = _title_if_1203oi()
        self.assertIn("_blank1203oi", _names_in(node.test),
                      "the all-blank title is unreachable from its own condition")
        self.assertIn("_empty", _names_in(node.test))
        # ★ `if False and set(_blank1203oi) == set(_empty):` keeps BOTH names in the test and
        # evaded the two checks above (mutation OI2). A literal boolean in a branch condition
        # is never load-bearing in real code, so its absence is the assertion.
        consts = [n.value for n in ast.walk(node.test)
                  if isinstance(n, ast.Constant) and isinstance(n.value, bool)]
        self.assertEqual(consts, [],
                         "the condition carries a literal boolean, so the branch is forced")

    def test_a_mixed_set_keeps_the_existing_two_titles(self):
        s = _gate_source()
        self.assertIn("seed the missing rows", s)
        self.assertIn("read-path bug (filters/owner-scoping), NOT seeding", s)

    def test_the_blank_branch_is_checked_FIRST(self):
        """Precedence is the whole point: with `_thin` truthy the old code would have said
        'seed the missing rows' about a page that drew nothing."""
        s = _gate_source()
        self.assertLess(s.index("set(_blank1203oi) == set(_empty)"),
                        s.index("if _thin else"))


class ItAsksTheMeasurementRatherThanGuessing(unittest.TestCase):
    def test_it_calls_1203ny(self):
        s = _gate_source()
        self.assertIn("blank_captures_1203ny(", s)

    def test_the_call_is_guarded_and_defaults_to_no_carve_out(self):
        """#1201: a diagnosis that fails must not cost the task. The default is the OLD
        behaviour, not a silent carve-out.

        The enclosing `try` comes from the AST -- #943 failed this file on `s[i:i + 700]`,
        which is the fixed-width source window that ratchet forbids."""
        import ast
        tree = ast.parse(inspect.getsource(VF))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        call = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(
                    node.func, "id", getattr(node.func, "attr", "")) == "blank_captures_1203ny":
                call = node
        self.assertIsNotNone(call, "nothing calls #1203ny from the gate")
        cur, tries = parents.get(call), []
        while cur is not None:
            if isinstance(cur, ast.Try):
                tries.append(cur)
            cur = parents.get(cur)
        self.assertTrue(tries, "the diagnosis is unguarded (#1201)")
        node = min(tries, key=lambda n: (n.end_lineno or 0) - n.lineno)
        handlers = ast.dump(ast.Module(body=[h for h in node.handlers], type_ignores=[]))
        self.assertIn("_blank1203oi", handlers,
                      "the handler does not reset the carve-out, so a fault could leave a "
                      "stale one")
        self.assertNotIn("Raise", handlers, "a diagnosis fault must not cost the task")

    def test_it_intersects_with_the_named_screens_only(self):
        """A blank screen the judge did not call empty_state is not this task's business —
        #1203ny reports it in the gate's own rows."""
        s = _gate_source()
        self.assertIn("sorted(n for n in _empty if n in _bn1203oi)", s)

    def test_the_screen_name_is_parsed_from_1203nys_own_row_shape(self):
        """If #1203ny's row format changes, this breaks loudly rather than silently matching
        nothing."""
        import tempfile
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "run"
            refs = run / "design" / "references"
            caps = run / "design" / "visual_gate"
            refs.mkdir(parents=True)
            caps.mkdir(parents=True)
            im = Image.new("L", (240, 160), 20)
            dr = ImageDraw.Draw(im)
            for x in range(0, 240, 3):
                dr.line([(x, 0), (x, 160)], fill=230)
            im.save(refs / "explore_grid.png")
            Image.new("L", (240, 160), 20).save(caps / "explore_grid.png")
            rows = VF.blank_captures_1203ny(run)
        self.assertTrue(rows)
        self.assertEqual(str(rows[0]).split(":", 1)[0].strip(), "explore_grid")


class WhatTheCorpusSays(unittest.TestCase):
    """The overlap, on the runs it was measured on."""

    _OVERLAP = {"tiktok-web-r163": 4, "tiktok-web-r180": 3, "tiktok-web-r169": 1}

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    @staticmethod
    def _named(run):
        import json
        f = run / "shared" / "hubs" / "workhub_tasks.json"
        if not f.is_file():
            return set()
        try:
            d = json.load(open(f, errors="ignore"))
        except Exception:
            return set()
        out = set()
        for t in d.values():
            if not isinstance(t, dict) or "render an EMPTY" not in str(t.get("title") or ""):
                continue
            m = re.search(r"EMPTY-state: ([^.]{0,300})", str(t.get("description") or ""))
            if m:
                out |= {s.strip() for s in m.group(1).split(",") if s.strip()}
        return out

    def test_the_measured_overlap_still_holds(self):
        checked = 0
        for run, n in sorted(self._OVERLAP.items()):
            d = self.corpus / run
            if not (d / "design" / "visual_gate").is_dir():
                continue
            checked += 1
            blank = {str(r).split(":", 1)[0].strip()
                     for r in (VF.blank_captures_1203ny(d) or [])}
            with self.subTest(run=run):
                self.assertEqual(len(blank & self._named(d)), n,
                                 "%s was measured at %d blank screen(s) named by the "
                                 "empty-state task" % (run, n))
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_r163_is_the_all_blank_case(self):
        d = self.corpus / "tiktok-web-r163"
        if not (d / "design" / "visual_gate").is_dir():
            self.skipTest("r163 is not on this disk")
        blank = {str(r).split(":", 1)[0].strip()
                 for r in (VF.blank_captures_1203ny(d) or [])}
        named = self._named(d)
        self.assertTrue(named)
        self.assertEqual(named & blank, named,
                         "r163 is the one run where every named screen is blank, which is the "
                         "case the new title exists for")

    def test_a_healthy_run_has_no_overlap(self):
        d = self.corpus / "tiktok-web-r191"
        if not (d / "design" / "visual_gate").is_dir():
            self.skipTest("r191 is not on this disk")
        blank = {str(r).split(":", 1)[0].strip()
                 for r in (VF.blank_captures_1203ny(d) or [])}
        self.assertEqual(blank & self._named(d), set())


if __name__ == "__main__":
    unittest.main()
