r"""#1203n1: the page-lifecycle line has been written 2021 times and never said why.

`sync_ui_page_statuses` records, per page, the reason it did NOT flip to `implemented`:

    out["pending"][name] = missing          # frontend_audit.py

`missing` is the same list the flip decision was made on. Its ONLY consumer -- the
`UI-PAGE LIFECYCLE` warning in `scaffolder` -- printed `list(pending.keys())` and dropped it.

MEASURED over every run log on disk: `UI-PAGE LIFECYCLE` appears **2021 times**, and
`is NOT in the registered contract` -- one of the misses that puts a page in that list --
appears **0 times**, ever.

r190's live reading is the shape of the cost:

    UI-PAGE LIFECYCLE: implemented=['__noop_probe_do_not_use__', '__noop_probe_do_not_use_2__']
    regressed=[] pending=['fyp_feed_logged_out', 'fyp_feed_comments_panel', 'login_modal',
    'profile_own_page', 'following_suggested_creators_page', ..., 'profile_own']

-- the only pages it could call implemented were the framework's own two probes, and the eight
real ones carried no reason. Across 34 modern runs, 160 of 412 registered pages sit at
`defined` at delivery, and nothing on disk says what each was waiting for; that is also why
"the status is simply wrong" is NOT claimed here -- without the reasons it cannot be told
apart from "the page really is missing a declared component" (#883).

The FIRING CONDITION is deliberately unchanged (still an implemented/regressed transition):
at 2021 occurrences this is already a loud line, and making it fire on every pending page is
the noise #1203i2 had to undo elsewhere. Only the detail improves.
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime.message_format import (
    ui_page_pending_detail_1203n1 as detail,
)

R190 = {
    "fyp_feed_logged_out": ["declared API `GET /api/videos/feed` is NOT in the registered contract"],
    "login_modal": ["component LoginOptions not rendered"],
    "profile_own": [],
}


class TheReasonIsInTheSentence(unittest.TestCase):
    def test_the_page_and_its_reason(self):
        s = detail({"login_modal": ["component LoginOptions not rendered"]})
        self.assertIn("login_modal", s)
        self.assertIn("component LoginOptions not rendered", s)

    def test_r190s_contract_miss_is_quoted(self):
        s = detail(R190)
        self.assertIn("is NOT in the registered contract", s)

    def test_several_pages_are_all_named(self):
        s = detail(R190)
        for name in R190:
            self.assertIn(name, s)

    def test_several_reasons_for_one_page(self):
        s = detail({"p": ["first reason", "second reason"]})
        self.assertIn("first reason", s)
        self.assertIn("second reason", s)


class NoReasonIsStatedAsSuch(unittest.TestCase):
    """#883: having no reason is a state to report, not something to render as fine."""

    def test_an_empty_list_says_so(self):
        self.assertIn("no reason recorded", detail({"profile_own": []}))

    def test_a_none_reason_says_so(self):
        self.assertIn("no reason recorded", detail({"profile_own": None}))

    def test_it_does_not_swallow_the_page_name(self):
        self.assertIn("profile_own", detail({"profile_own": []}))


class TheCutsDeclareThemselves(unittest.TestCase):
    """#1034: both levels go through join_capped, which says what it cut."""

    def test_the_page_list_declares_its_cut(self):
        s = detail({"p%d" % i: ["r"] for i in range(10)}, cap=3)
        self.assertIn("more not shown", s)

    def test_the_reason_list_declares_its_cut(self):
        s = detail({"p": ["r%d" % i for i in range(5)]}, reasons_cap=2)
        self.assertIn("more not shown", s)


class ItNeverRaises(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertEqual(detail({}), "")
        self.assertEqual(detail(None), "")

    def test_a_non_mapping(self):
        self.assertEqual(detail(["not", "a", "mapping"]), "")

    def test_unstringable_reasons_do_not_blow_up(self):
        class _Bad:
            def __str__(self):
                raise RuntimeError("no")
        out = detail({"p": [_Bad()]})
        self.assertIsInstance(out, str)


class TheScaffolderUsesIt(unittest.TestCase):
    def _lifecycle_call(self):
        from env_generator.llm_generator.multi_agent.runtime import scaffolder
        tree = ast.parse(inspect.getsource(scaffolder))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or getattr(node.func, "attr", "") != "warning":
                continue
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and "UI-PAGE LIFECYCLE" in a.value:
                    return node
        return None

    def test_the_warning_is_still_there(self):
        self.assertIsNotNone(self._lifecycle_call())

    def test_the_pending_argument_is_the_detailed_one(self):
        """Not `list(pending.keys())` any more."""
        call = self._lifecycle_call()
        last = call.args[-1]
        self.assertEqual(getattr(last, "id", None), "_why1203n1",
                         "the lifecycle line is not passing the detailed pending text")

    def test_the_detail_helper_is_what_builds_it(self):
        from env_generator.llm_generator.multi_agent.runtime import scaffolder
        src = inspect.getsource(scaffolder)
        self.assertIn("ui_page_pending_detail_1203n1(_pa.get(\"pending\")", src)

    def test_the_firing_condition_is_unchanged(self):
        """Deliberate: 2021 occurrences already; firing on every pending page is noise."""
        from env_generator.llm_generator.multi_agent.runtime import scaffolder
        tree = ast.parse(inspect.getsource(scaffolder))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            dump = ast.dump(node.test)
            if "implemented" in dump and "regressed" in dump:
                found.append("pending" in dump)
        self.assertTrue(found, "the lifecycle guard is gone")
        self.assertFalse(any(found), "the guard now also fires on pending pages")


if __name__ == "__main__":
    unittest.main()
