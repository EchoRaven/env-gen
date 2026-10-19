r"""#1203os: 599 of the 602 "#1201: this mechanism is OFF" lines were nothing of the kind.

`warn_once_1201` exists to answer one question -- *which guarded mechanisms were off in this
run?* -- and its template says so in the strongest terms it can:

    #1201 <what> did NOT run this process: <cause>. It is guarded so it cannot break the run,
    which also means nothing else will report it — treat this as the mechanism being OFF, not
    as a transient.

Three call sites were using it for something else: a FACT ABOUT THE GENERATED APP, or an
EVENT the framework chose on purpose. MEASURED over the 294 corpus run logs -- 602 `#1201`
lines in all:

    registryhub: "ui_page 'X' registered with no `apis_used`"              565 / 66 logs
    registryhub: "ui_page 'X' claimed IMPLEMENTED with no route/component"  32 / 10 logs
    compose_mutex: "waited Ns for the stack lease ... tearing it down"       2 /  2 logs
    ------------------------------------------------------------------------------------
    a mechanism that actually declined                                       3 /  3 logs

★ THE COST IS NOT HYPOTHETICAL AND I PAID IT. This was found by auditing exactly the question
#1201 is for -- "which guarded mechanisms turned off in real runs?" -- and the audit returned
608 rows of which 3 were real. Every other row was a finding wearing the wrong template.

★ AND IT BURIES THE FINDINGS. Two of the three are the UI contract: a page registered without
naming the endpoints it reads is what turns the decoy-twin / consumer-wiring / implemented-flip
checks OFF for that page, which is the sharpest "UI with no real function" signal the framework
has. The third is the lease-wait announcement that the 13.2h `lease_wait` measurement rests on.
A reader who meets any of them inside #1201's template is told to read it as a broken
mechanism.

So: `announce_once_1203os(site, message, *args)` -- same dedupe contract, separate store, and
it says the thing instead of claiming something failed. #1201 keeps its template and gains an
honest cause clause for `exc=None` ("its precondition was not met"), which is what the three
real A-class sites pass.
"""
from __future__ import annotations

import ast
import logging
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import message_format as MF  # noqa: E402

_RUNTIME = LLM / "multi_agent" / "runtime"


class TheTwoHelpersSayDifferentThings(unittest.TestCase):

    def setUp(self):
        MF._WARNED_1201.clear()
        MF._ANNOUNCED_1203OS.clear()

    def test_an_announcement_does_not_claim_anything_failed(self):
        with self.assertLogs("multi_agent.runtime.message_format", level="WARNING") as cm:
            MF.announce_once_1203os("s1", "ui_page %r registered with no apis_used", "x")
        line = " ".join(cm.output)
        self.assertIn("#1203os", line)
        self.assertIn("ui_page 'x' registered with no apis_used", line)
        for claim in ("did NOT run", "mechanism being OFF", "#1201"):
            self.assertNotIn(claim, line, "an announcement still reads as a failure: %r" % line)

    def test_a_warning_still_says_the_mechanism_is_off(self):
        with self.assertLogs("multi_agent.runtime.message_format", level="WARNING") as cm:
            MF.warn_once_1201("s2", "the twin check", RuntimeError("boom"))
        line = " ".join(cm.output)
        self.assertIn("did NOT run this process", line)
        self.assertIn("RuntimeError: boom", line)

    def test_a_missing_precondition_is_not_rendered_as_NoneType_None(self):
        """The three legitimate `exc=None` callers checked a precondition; the tail used to
        read `NoneType: None`, which looks like a bug in the reporter."""
        with self.assertLogs("multi_agent.runtime.message_format", level="WARNING") as cm:
            MF.warn_once_1201("s3", "the twin check", None)
        line = " ".join(cm.output)
        self.assertIn("precondition was not met", line)
        self.assertNotIn("NoneType: None", line)

    def test_each_helper_speaks_once_per_site(self):
        with self.assertLogs("multi_agent.runtime.message_format", level="WARNING") as cm:
            MF.announce_once_1203os("s4", "once")
            MF.announce_once_1203os("s4", "once")
            MF.warn_once_1201("s5", "m", None)
            MF.warn_once_1201("s5", "m", None)
        self.assertEqual(len(cm.output), 2, cm.output)

    def test_the_two_stores_are_separate_so_moving_a_site_cannot_silence_it(self):
        """★ If they shared a store, moving a call site from one helper to the other would
        make the first announcement after the move disappear -- which is the failure this
        whole ticket is about, one level up."""
        MF.warn_once_1201("same_site", "m", None)
        with self.assertLogs("multi_agent.runtime.message_format", level="WARNING") as cm:
            MF.announce_once_1203os("same_site", "the finding")
        self.assertIn("#1203os", " ".join(cm.output))

    def test_neither_helper_raises_on_junk(self):
        """★ The first version passed None / 5 / object() and mutation OS8 (turning the
        swallow into a `raise`) walked through it: all three are hashable and str()-able, so
        the except branch never executed. An UNHASHABLE site is what reaches it -- `[] in
        set()` raises TypeError. A guard is only pinned by an input that needs it."""
        for bad in (None, 5, object(), [], {"a": 1}, {1, 2}):
            with self.subTest(arg=type(bad).__name__):
                MF.announce_once_1203os(bad, bad)
                MF.warn_once_1201(bad, bad, bad)


class TheThreeSitesNowAnnounce(unittest.TestCase):
    """The moved call sites, read from the source they ship in."""

    def _calls(self, filename, func_name):
        src = (_RUNTIME / filename).read_text(encoding="utf-8")
        tree = ast.parse(src)
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                nm = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if nm == func_name:
                    try:
                        out.append(ast.unparse(node))
                    except Exception:
                        out.append("<unparsed>")
        return out

    def test_the_ui_page_findings_are_announcements(self):
        got = " || ".join(self._calls("registryhub.py", "announce_once_1203os"))
        self.assertIn("ui_page_no_apis_1202rn", got)
        self.assertIn("ui_page_implemented_without_a_surface_1202ud", got)
        warned = " || ".join(self._calls("registryhub.py", "warn_once_1201"))
        self.assertNotIn("ui_page_no_apis_1202rn", warned)
        self.assertNotIn("ui_page_implemented_without_a_surface_1202ud", warned)

    def test_the_lease_wait_event_is_an_announcement(self):
        got = " || ".join(self._calls("compose_mutex.py", "announce_once_1203os"))
        self.assertIn("stack_lease_wait_1202nx", got)
        warned = " || ".join(self._calls("compose_mutex.py", "warn_once_1201"))
        self.assertNotIn("stack_lease_wait_1202nx", warned)

    def test_the_lease_wait_name_is_bound_at_module_level(self):
        """★ That call site is NOT inside a try, so a name it cannot resolve would raise
        NameError and take the run down -- the sixth time this project has paid for a name
        reached for but never bound. Asserted by importing the module and reading the binding,
        not by grepping for the import line."""
        from multi_agent.runtime import compose_mutex as CM
        self.assertTrue(callable(getattr(CM, "announce_once_1203os", None)))
        self.assertTrue(callable(getattr(CM, "warn_once_1201", None)))


class NoNewFindingWearsThe1201Template(unittest.TestCase):
    """The ratchet. Every `warn_once_1201` call OUTSIDE an except handler is a claim that a
    mechanism declined without anything having failed, so each one has to be a deliberate,
    named case."""

    # site-name fragment -> why it is legitimately outside an except handler
    _ALLOWED = {
        "fabricated_record_arrays_1203oc":
            "the #1203oc scan checked its precondition (file absent / nothing parsed) and "
            "declined; the mechanism really did not run",
        "heal_pipeline.twins_1202zb_unmeasured":
            "the twin check has no live row counts this cycle, so it really did not run",
        "frontend_audit.fallback_repair_write_1202tr":
            "constructs a real RuntimeError for a writer that is unavailable",
    }

    def test_every_non_except_warn_site_is_a_named_case(self):
        offenders = []
        checked = 0
        for f in sorted(_RUNTIME.rglob("*.py")):
            try:
                src = f.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except Exception:
                continue
            checked += 1
            inside = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    for sub in ast.walk(node):
                        inside.add(id(sub))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                nm = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if nm != "warn_once_1201" or id(node) in inside:
                    continue
                try:
                    site = ast.unparse(node.args[0])
                except Exception:
                    site = "<unparsed>"
                if not any(k in site for k in self._ALLOWED):
                    offenders.append("%s:%d %s" % (f.name, node.lineno, site))
        # ★ ON4's lesson: a ratchet that looked at nothing SKIPS or passes vacuously.
        self.assertGreater(checked, 40, "only %d runtime modules parsed" % checked)
        self.assertEqual(offenders, [],
                         "a warn_once_1201 call outside an except handler claims a mechanism "
                         "declined with nothing having failed. If it really is a mechanism "
                         "that could not run, name it in _ALLOWED with the reason; if it is a "
                         "finding or an event, use announce_once_1203os.")

    def test_the_allowlist_has_no_dead_entries(self):
        """#1203oa: a named exemption that no longer matches anything is a rotted claim."""
        seen = set()
        for f in sorted(_RUNTIME.rglob("*.py")):
            try:
                src = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for k in self._ALLOWED:
                if k in src:
                    seen.add(k)
        self.assertEqual(sorted(set(self._ALLOWED) - seen), [])


if __name__ == "__main__":
    unittest.main()
