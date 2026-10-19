"""#1203p8: the number that authorises a release IS persisted, and #711's retraction said it was not.

`visual_fidelity.py`'s #711r paragraph withdrew a set of delivery claims "rather than
re-measured", on the stated ground that "the value that DOES authorise one is persisted
nowhere -- the current blocking-only average appears in no artifact -- so 'what number
released r146' cannot be recovered from disk at all".

It is persisted, by the same function, as `blocking_average_live` (#768r). These tests pin the
claim the correction makes, BEHAVIOURALLY rather than by reading prose: the decision formula
(`_blocking_similarity_average`, which the returned dict carries) and the persisted formula
agree on every non-empty blocking set, and diverge only when the blocking set is empty --
where the decision says 0.0 (a hard fail) and the record writes None (#883: a reader must not
take that None for "not recorded"). MEASURED: 42 of 1715 corpus rows are that None (2.4%).
"""

import ast
import inspect
import os
import re
import unittest
from collections.abc import Mapping

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _blocking_similarity_average)

_VF = os.path.join(os.path.dirname(
    inspect.getfile(_blocking_similarity_average)), "visual_fidelity.py")


def _comment_paragraph(src, landmark):
    """The contiguous `#` comment paragraph containing `landmark`.

    #943 forbids fixed-BYTE source windows and it caught this file: `src[i:i + 200]` breaks the
    moment a comment near the landmark grows -- which is exactly what #1203p9 then did to this
    region, in the same session. A paragraph is a landmark-anchored window: it ends where the
    comment block ends, whatever its length.
    """
    lines = src.split("\n")
    hit = next((n for n, l in enumerate(lines) if landmark in l), None)
    if hit is None:
        return ""

    def _is_comment(l):
        return l.strip().startswith("#") and l.strip() != "#"

    lo = hi = hit
    while lo > 0 and _is_comment(lines[lo - 1]):
        lo -= 1
    while hi + 1 < len(lines) and _is_comment(lines[hi + 1]):
        hi += 1
    return "\n".join(lines[lo:hi + 1])


def _persisted_formula(results):
    """`blocking_average_live` as visual_fidelity.py computes it, transcribed.

    Transcribed deliberately: the point of this test is that the two AGREE, so it must not
    call the one function and compare it with itself.
    """
    def _sim(s):
        try:
            return float(s.get("similarity") or 0.0)
        except Exception:
            return 0.0
    blk = [s for s in (results or []) if isinstance(s, Mapping)
           and not s.get("advisory") and s.get("blank") is not True]
    return round(sum(_sim(s) for s in blk) / len(blk), 4) if blk else None


_NONEMPTY = {
    "plain": [{"name": "a", "similarity": 0.6}, {"name": "b", "similarity": 0.8}],
    "advisory excluded": [{"name": "a", "similarity": 0.6},
                          {"name": "o", "similarity": 0.1, "advisory": True}],
    "blank excluded": [{"name": "a", "similarity": 0.6},
                       {"name": "z", "similarity": 0.0, "blank": True}],
    "a real zero counts": [{"name": "a", "similarity": 0.6},
                           {"name": "z", "similarity": 0.0, "blank": False}],
    "missing similarity is zero": [{"name": "a"}, {"name": "b", "similarity": 0.5}],
}


class TheAuthorisingNumberIsRecoverable(unittest.TestCase):

    def test_the_two_formulas_agree_on_every_nonempty_blocking_set(self):
        for label, results in _NONEMPTY.items():
            self.assertEqual(_blocking_similarity_average(results),
                             _persisted_formula(results), label)

    def test_they_diverge_only_when_the_blocking_set_is_empty(self):
        for results in ([], [{"name": "o", "similarity": 0.1, "advisory": True}],
                        [{"name": "z", "similarity": 0.0, "blank": True}]):
            self.assertEqual(_blocking_similarity_average(results), 0.0)
            self.assertIsNone(_persisted_formula(results))

    def test_the_divergence_is_a_hard_fail_not_an_unknown(self):
        """#883: the decision's answer for an empty blocking set is 0.0, which FAILS the bar."""
        self.assertLess(_blocking_similarity_average([]), 0.65)

    def test_the_verdict_row_itself_carries_the_live_average(self):
        """The correction's whole claim is "the record already carries the number", so the
        assertion has to be about the ROW, read as a dict literal.

        Substring forms do not work here and a mutation proved it: `'"blocking_average_live"'
        in src` is satisfied by the three places that READ the key, so renaming the one place
        that WRITES it survived every text-based check in this file.
        """
        with open(_VF, encoding="utf-8", errors="ignore") as fh:
            tree = ast.parse(fh.read())
        rows = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "code_state" in keys and "blocking_average" in keys:
                rows.append(keys)
        self.assertTrue(rows, "the persisted verdict row moved; re-aim this test")
        for keys in rows:
            self.assertIn("blocking_average_live", keys,
                          "the row that carries the merged number must carry the live one too")


class TheCorrectionReplacedTheFalseSentence(unittest.TestCase):

    def setUp(self):
        with open(_VF, encoding="utf-8", errors="ignore") as fh:
            self.src = fh.read()

    def test_the_false_claim_is_no_longer_asserted_in_its_own_voice(self):
        """#1202vs: a correction REPLACES the claim it corrects.

        The correction is allowed -- required, even -- to quote the sentence, so this does not
        forbid the words; it forbids them OUTSIDE a paragraph that carries the correcting
        ticket marker. That distinction is the #1203ox lesson: my first version of that test
        was failed by my own correction text.
        """
        paras = re.split(r"\n\s*#\s*\n", self.src)
        for p in paras:
            if "persisted nowhere" not in p:
                continue
            self.assertIn("1203p8", p,
                          "the claim survives in a paragraph that does not correct it")

    def test_the_correction_names_the_key_that_disproves_it(self):
        """Narrowed to the LOAD-BEARING sentence, not a window.

        The first version searched 2000 characters after the marker, and the correction
        mentions the key twice -- so a mutation that stripped it from the sentence asserting
        WHERE the number lives was fed by the other mention and survived (MISSED). The claim
        under test is "it is persisted, and here is its name", so that sentence is what must
        carry the name.
        """
        para = _comment_paragraph(self.src, "IS persisted, by")
        self.assertTrue(para, "the correction no longer asserts that it IS persisted")
        self.assertIn("blocking_average_live", para,
                      "the paragraph that says it is persisted must name the key")

    def test_the_correction_carries_the_divergence_it_found(self):
        para = _comment_paragraph(self.src, "cannot tell that None from")
        self.assertTrue(para, "the correction no longer describes the None/0.0 divergence")
        self.assertIn("883", para, "the None/0.0 divergence is a #883 shape and must be named")

    def test_the_retraction_above_it_is_untouched(self):
        """#711r's retraction of the CONSEQUENCE is correct and must survive this edit."""
        self.assertIn("RETRACTION OF THE CONSEQUENCE", self.src)

    def test_nothing_in_the_correction_changes_a_decision(self):
        """It is a comment. If an edit ever turns it into code, this fails."""
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id.endswith("1203p8"):
                self.fail("#1203p8 must stay prose; found an executable name %s" % node.id)


if __name__ == "__main__":
    unittest.main()
