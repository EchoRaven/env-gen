"""#1203qz: a <button> bound to nothing is a dead control, and the file-level check missed it.

`_page_dead_controls` asked two FILE-level questions -- is there interactive markup, and is
there a handler anywhere -- and both are too coarse:

  * `interactive` was `"<form" in text or 'type="submit"' in text`. A page of buttons with no
    form is therefore NOT interactive and the check never ran on it: 67 of the 85
    button-bearing files in modern deliveries (79%) were exempt.
  * `bound` was `any(tok in text for tok in _HANDLER_TOKENS)`, so ONE onClick anywhere in the
    file marked every button in it as bound. r187's TikTokUI.jsx has 32 buttons, 13 with no
    handler, and passed -- it would pass with all 32 dead.

The worst cases are not polish gaps. r189's ProfileOwnPage.jsx (4 of 4) and
NotificationsActivityPage.jsx (6 of 6) contain NO handler of any kind, no <form>, no parent
handler near any button, and ship `<button type="button" aria-label="Close">` that closes
nothing -- while both pages DO call the API, so they render real data behind dead controls.

HONEST SCOPE. 36 of the 37 modern dead buttons are in runs that never delivered (two killed
by their own spend cap, one blocked); exactly ONE reaches a delivered app. So this is not a
shipped-quality fix. It is landed because the check is objectively blind, the verdict is SOFT
(it feeds `pages_pending` and remediation, and the #1089 call site says in as many words that
it does not reach the delivery gate), and it helps runs still iterating -- r189 had 15 while
mid-flight. Blocking instead was costed and rejected: 4 of the 7 modern runs carry at least
one dead control, and the framework's own rule is that blocking delivery over something
dispatches a lane that cannot fix it (#1202tm).

LOCAL-ONLY (agent/tests/ is gitignored).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    _page_dead_controls, dead_control_count_1203qz, _BUTTON_TAG_RE_1203QZ)


class TheCountLooksAtEachTag(unittest.TestCase):
    """QZ1/QZ2: per-control, not per-file."""

    def test_one_live_button_does_not_exempt_the_dead_ones(self):
        src = ('<button onClick={go}>live</button>'
               '<button className="a">dead</button><button className="b">dead</button>')
        self.assertEqual(2, dead_control_count_1203qz(src),
                         "a handler on ONE button exempted the others -- that is the "
                         "file-level `any` this ticket exists to replace")
        self.assertTrue(_page_dead_controls(src))

    def test_a_file_of_buttons_with_no_form_is_examined_at_all(self):
        """The 79% blind spot: no <form> meant `interactive` was False."""
        src = '<div><button className="tab">One</button></div>'
        self.assertNotIn("<form", src)
        self.assertTrue(_page_dead_controls(src),
                        "a page of unbound buttons with no <form> is still unexamined")

    def test_every_button_wired_is_clean(self):
        src = '<button onClick={a}>x</button><button onSubmit={b}>y</button>'
        self.assertEqual(0, dead_control_count_1203qz(src))
        self.assertFalse(_page_dead_controls(src))


class TheExemptionsAreNarrow(unittest.TestCase):
    """QZ3/QZ4: #647 -- no guard wider than the evidence."""

    def test_a_disabled_button_is_not_a_defect(self):
        self.assertEqual(0, dead_control_count_1203qz('<button disabled>x</button>'),
                         "a deliberately inert control was reported as dead")

    def test_a_submit_button_acts_through_its_form(self):
        self.assertEqual(0, dead_control_count_1203qz('<button type="submit">x</button>'))

    def test_a_passive_handler_does_not_count_as_bound(self):
        """onFocus/onBlur do not make a button DO anything when clicked, so they must not
        exempt it. Measured before narrowing: 0 of the 366 modern <button> tags have a
        passive handler and no activation one, so this costs nothing today and keeps the
        check honest for the case that eventually shows up."""
        self.assertEqual(1, dead_control_count_1203qz('<button onBlur={x}>x</button>'),
                         "a button whose only handler is onBlur was treated as wired")
        self.assertEqual(0, dead_control_count_1203qz('<button onBlur={x} onClick={y}>x</button>'),
                         "a real activation handler stopped counting because a passive one "
                         "sits beside it")

    def test_a_spread_button_is_conceded(self):
        """`{...props}` can carry the handler from the parent and this function cannot see
        it, so counting it would be a false positive by construction. 0 of the 37 modern
        dead buttons use a spread, so the concession costs nothing."""
        self.assertEqual(0, dead_control_count_1203qz('<button {...props}>x</button>'))


class TheOriginalRuleSurvives(unittest.TestCase):
    """QZ5: widening must not drop what the check already caught."""

    def test_a_form_with_no_handler_anywhere_is_still_dead(self):
        self.assertTrue(_page_dead_controls('<form><input name="q"/></form>'))

    def test_a_form_with_onsubmit_is_still_clean(self):
        self.assertFalse(_page_dead_controls('<form onSubmit={go}><input/></form>'))


class TheMessageNamesTheCount(unittest.TestCase):
    """QZ6: #983 -- a check that fires must name its subject."""

    def test_the_audit_message_carries_how_many_of_how_many(self):
        """DRIVEN, not grepped.

        The first version of this asserted `"_dead_n" in inspect.getsource(audit_ui_page)`.
        A mutation that stripped the count out of the f-string left that assertion GREEN,
        because `_dead_n` is still assigned on the line above -- the same shape as the
        read-sites-feed-the-write-site-assertion failure. So drive the real function and
        read the real message."""
        import tempfile
        from pathlib import Path
        from multi_agent.runtime.frontend_audit import audit_ui_page
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            (src / "components").mkdir(parents=True)
            (src / "components" / "Widget.jsx").write_text(
                "export default function Widget(){\n"
                "  return (<div>\n"
                "    <button onClick={go}>live</button>\n"
                "    <button className=\"a\">dead</button>\n"
                "    <button className=\"b\">dead</button>\n"
                "  </div>);\n}\n", encoding="utf-8")
            _ok, missing = audit_ui_page(
                src, {"component": "Widget", "route": "",
                      "_is_component": True, "apis_used": []})
        dead_msgs = [m for m in missing if "dead controls" in m]
        self.assertTrue(dead_msgs, "no dead-controls message at all: %s" % missing)
        msg = dead_msgs[0]
        self.assertRegex(msg, r"\b2 of 3\b",
                         "the message does not name HOW MANY of HOW MANY, so the lane is "
                         "told a file is wrong and nothing about where to look: %r" % msg)

    def test_the_tag_regex_counts_what_the_message_reports(self):
        src = '<button>a</button><button onClick={x}>b</button>'
        self.assertEqual(2, len(_BUTTON_TAG_RE_1203QZ.findall(src)))
        self.assertEqual(1, dead_control_count_1203qz(src))


if __name__ == "__main__":
    unittest.main()
