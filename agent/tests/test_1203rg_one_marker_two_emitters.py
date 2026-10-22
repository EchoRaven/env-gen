r"""#1203rg -- a criterion that reads a MARKER reads every emitter behind it, not just the one
it was written for.

`verify_1020.py`'s `#1203qv` check asks whether the invisible-icon advice carries its
MECHANISM clause ("in the DOM and invisible on screen"), because advice that names only the
symptom contradicts what the lane can see in the DOM. It found the lines with
`r"#1203n0 ([^\n]*)"` and treated all of them as advice.

But `#1203n0` has TWO emitters in `heal_pipeline.repair_frontend_api`:

    orch._logger.warning(INVISIBLE_ICON_ADVICE_1203QV, _iv1203n0)     # the advice
    orch._logger.warning("#1203n0 %d more invisible icon reference(s) "
                         "not listed (#1034)", len(_inv1203n0) - 6)   # the #1034 cap notice

The second is a COUNT of what the 6-row log cap dropped. It is not advice and has no mechanism
to name, so every one of them was reported as "advice missing the mechanism clause".

MEASURED over all 213 run logs in the tree:

    advice lines                              82   ALL carry the clause
    clause-less lines                         12   ALL are the #1034 cap notice
    any other shape under this marker          0

So the criterion had 0 true and 12 false positives, and it fired on
`generated/instagram-core-di` -- a run that did heavy icon work -- where it read 90 lines as
advice and called 12 of them broken. A false FALSIFIED is worse than a false NOT MEASURED: it
sends a reader after a defect that is not there (#1203rd's rule, third instance of it here).

THE CAP ITSELF LOSES NOTHING ACTIONABLE, which is why only the criterion changed:
`invisible_icon_task_1203pm` is handed the FULL `_inv1203n0` -- not `_inv1203n0[:6]` -- and its
body renders through `join_capped(rows, total=len(rows), cap=8)`, which states the total. This
is the opposite of #1203p7/#1203pa, where the list sent to a lane was truncated silently.

WHY THE NEEDLES ARE PINNED TO PRODUCTION HERE: the fix distinguishes the two emitters by their
wording, so a reword on either side would send the criterion quietly to NOT MEASURED -- the
"parked measurement rots" failure, and the one a text-matching instrument is most prone to.
The advice needle is checked against the imported constant and the cap needle against the
format string extracted from `heal_pipeline` BY AST, so neither can be satisfied by a comment
(this series has been fed by its own comments more than once).
"""
import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_1020.py"
HEAL = (ROOT / "agent/env_generator/llm_generator/multi_agent/runtime"
        / "heal_pipeline.py")

ADVICE_NEEDLE = "loads a staged icon CSS colour cannot reach"
CLAUSE = "in the DOM and invisible on screen"


def _qv(logtext):
    """Drive the REAL `check_log_only` and return its `#1203qv` (verdict, detail)."""
    spec = importlib.util.spec_from_file_location("v1020_1203rg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUT.clear()
    mod.check_log_only(logtext, len(logtext.splitlines()))
    hits = [(v, d) for (t, v, d) in mod.OUT if t == "#1203qv"]
    assert len(hits) == 1, "expected exactly one #1203qv verdict, got %r" % (hits,)
    return hits[0]


def _advice_line(name="LeftSidebar.jsx", clause=True):
    """A real advice line, built from the production constant so it cannot drift."""
    from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
        INVISIBLE_ICON_ADVICE_1203QV as ADVICE)
    line = ADVICE % ("%s -> /assets/icons/home.svg (currentColor)" % name)
    if not clause:
        line = line.replace(CLAUSE, "it does not appear")
    return line.replace("\n", " ") + "\n"


def _cap_literal():
    """The #1034 cap-notice format string, extracted from heal_pipeline BY AST."""
    tree = ast.parse(HEAL.read_text(encoding="utf-8"))
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and n.value.startswith("#1203n0 %d more invisible icon reference")]
    assert len(found) == 1, (
        "expected exactly one #1034 cap-notice literal in heal_pipeline, got %r" % (found,))
    return found[0]


def _cap_line(n=7):
    return (_cap_literal() % n) + "\n"


# ---------------------------------------------------------------- needles vs production

def test_the_advice_needle_still_matches_the_shipped_constant():
    """If the advice is reworded past this needle the criterion goes silently NOT MEASURED."""
    from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
        INVISIBLE_ICON_ADVICE_1203QV as ADVICE)
    assert ADVICE_NEEDLE in ADVICE, (
        "verify_1020's #1203qv finds advice lines by this substring; reword the constant and "
        "every advice line stops being counted, which reads as 'never fired'")


def test_the_clause_the_criterion_demands_is_actually_in_the_advice():
    """The subject of the check: the clause must be present in what production ships."""
    from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
        INVISIBLE_ICON_ADVICE_1203QV as ADVICE)
    assert CLAUSE in ADVICE, (
        "#1203qv exists because mutation N08 deleted this clause and nothing noticed")


def test_the_cap_notice_needle_matches_the_literal_heal_pipeline_emits():
    """The regex that exempts the #1034 notice is checked against the real format string."""
    emitted = _cap_line(9).strip()
    body = emitted.split("#1203n0 ", 1)[1]
    assert re.match(r"^\d+ more invisible icon reference\(s\) not listed", body), (
        "verify_1020 exempts the cap notice with this pattern; it no longer matches %r, so "
        "the notice would be read as advice again" % (emitted,))


def test_the_two_emitters_are_distinguishable_at_all():
    """The exemption only works because the cap notice lacks the advice needle."""
    assert ADVICE_NEEDLE not in _cap_literal(), (
        "if the cap notice ever contains the advice needle the classifier cannot separate them")


# ---------------------------------------------------------------- behaviour of the criterion

def test_the_cap_notice_alone_is_not_a_falsification():
    """THE BUG. 12 of these existed in the corpus and every one was reported as broken advice."""
    verdict, detail = _qv(_cap_line(7) + _cap_line(11))
    assert verdict == "NOT MEASURED", (
        "two #1034 cap notices and no advice at all came back %s: %s" % (verdict, detail))
    assert "2 #1034 overflow notice(s)" in detail
    assert "0 advice line(s)" in detail


def test_advice_with_the_clause_plus_cap_notices_confirms():
    """The live shape on instagram-core-di: advice that is fine, alongside cap notices."""
    verdict, detail = _qv(_advice_line() + _advice_line("TopNav.jsx") + _cap_line(4))
    assert verdict == "CONFIRMED", detail
    assert "2 advice line(s), 0 missing the mechanism clause" in detail
    assert "1 #1034 overflow notice(s)" in detail


def test_advice_missing_the_clause_still_falsifies():
    """COUNTER-PROOF: narrowing the needle must not cost the finding it was built for."""
    verdict, detail = _qv(_advice_line(clause=False))
    assert verdict == "FALSIFIED", (
        "an advice line with the mechanism clause deleted must still be caught: %s" % detail)
    assert "1 missing the mechanism clause" in detail


def test_one_broken_advice_line_among_many_cap_notices_still_falsifies():
    """The exemption must not become a hiding place for a real one."""
    log = _cap_line(5) + _advice_line() + _advice_line(clause=False) + _cap_line(8)
    verdict, detail = _qv(log)
    assert verdict == "FALSIFIED", detail
    assert "2 advice line(s), 1 missing the mechanism clause" in detail


def test_a_third_shape_under_this_marker_falsifies_rather_than_being_swallowed():
    """The reason this CLASSIFIES instead of filtering: an unread emitter is itself a finding.

    Filtering by `not advice` would have put this in the advice bucket (the old bug); dropping
    everything that is not advice would hide it. Neither is right -- a `#1203n0` line in a
    shape nobody here has read means an emitter this criterion has never been checked against.
    """
    verdict, detail = _qv("#1203n0 some entirely new sentence about icons\n")
    assert verdict == "FALSIFIED", detail
    assert "1 line(s) in NO shape read here" in detail


def test_a_log_with_no_marker_at_all_is_not_measured():
    verdict, detail = _qv("nothing about icons here\n")
    assert verdict == "NOT MEASURED", detail
    assert "absent is fine" in detail
