r"""#1203qd: two `%`-format counts beside cut lists, in #1034's own scan scope, unseen.

#1034 ratchets "a count beside a cut list" -- the number says 27 and the list shows 6 -- and
its detector `_count_beside_cut_list_1203jx` walks `JoinedStr` nodes. This package formats
with `%` far more often than with f-strings, so two real violations sat inside
`_PKG_1203JX` and the ratchet could not see either. #1203qe widens the detector; this file
pins what the two repaired sites must keep saying.

  auto_commit.py  `"%d file(s): %s" % (len(_names), ", ".join(_names[:6]))`
      The promotion-conflict detail. MEASURED over the kept run logs: 12 of 12 occurrences
      are cut -- 17, 18, 19, 20, 21x3, 22x2, 23, 27 and 30 files, every single one showing
      SIX names. #1151, three lines below it, records that this branch is the ONLY outcome
      this function has ever produced, so that text is the whole of what a lane ever reads
      about which files to go and resolve.

  hub_tools.py    `"... the existing %d entry(ies) were KEPT: %s" % (len(_kept), ...[:8])`
      45 of 1687 ui_page records carry more than 8 `apis_used` (2.7%), up to 17
      (tiktok-web-r164) and 16 (instagram-core-r176). This note is #1203b0, which exists
      because a lane concluded it had fixed a `page_apis_understated` blocker 19 times over.
      The count is the entire point of the sentence.

WHY AST AND NOT BEHAVIOUR HERE. The subject of this check is which `total` the call is
given -- #1203pl's defect is `total=<the shown count>`, which is behaviourally identical to
an honest call on every input where nothing is cut, and textually still spells `join_capped`.
Only the source expression distinguishes them. (Contrast #1203qb/qc, where the subject was
whether a VALUE arrives and only a driven test could see it.)
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_LLM = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
_SITES = {
    "auto_commit.py": (_LLM / "multi_agent" / "agents" / "runtime" / "auto_commit.py", "_names", 6),
    "hub_tools.py": (_LLM / "tools" / "hub_tools.py", "_kept", 8),
}


def _capped_calls(path: Path):
    """Every join_capped call in the file, with its keywords resolved to source text."""
    src = path.read_text(encoding="utf-8")
    out = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if not name or "join_capped" not in name and not name.startswith("_jc"):
            continue
        kw = {k.arg: k.value for k in n.keywords if k.arg}
        out.append((n, kw, src))
    return out


class BothSitesDeclareTheirCut(unittest.TestCase):

    def test_each_site_renders_through_the_shared_owner(self):
        """#1032: one owner for the cut, and no bare slice-join left behind."""
        for label, (path, var, cap) in _SITES.items():
            with self.subTest(site=label):
                calls = _capped_calls(path)
                self.assertTrue(calls, "%s no longer calls join_capped at all" % label)
                src = path.read_text(encoding="utf-8")
                self.assertNotIn('", ".join(%s[:%d])' % (var, cap), src,
                                 "%s still carries the bare slice-join" % label)

    def test_the_total_is_the_whole_list_not_the_shown_count(self):
        """#1203pl: `total=<cap>` makes the sentence self-consistent and still hides the rest.
        Behaviourally invisible whenever nothing is cut, so it is asserted structurally."""
        for label, (path, var, cap) in _SITES.items():
            with self.subTest(site=label):
                hits = []
                for node, kw, src in _capped_calls(path):
                    tot = kw.get("total")
                    if tot is None:
                        continue
                    txt = ast.unparse(tot)
                    if var in txt:
                        hits.append(txt)
                self.assertTrue(hits, "%s: no join_capped call declares a total over %s"
                                      % (label, var))
                for txt in hits:
                    self.assertTrue(
                        txt.startswith("len("),
                        "%s: total is %r -- it must be len() of the WHOLE list, never the "
                        "shown count (#1203pl)" % (label, txt))

    def test_the_cap_is_still_a_bound(self):
        """A cap lifted instead of declared pastes an unbounded list into text a model reads."""
        for label, (path, var, cap) in _SITES.items():
            with self.subTest(site=label):
                caps = [ast.unparse(kw["cap"]) for _n, kw, _s in _capped_calls(path)
                        if kw.get("cap") is not None]
                self.assertIn(str(cap), caps,
                              "%s: expected a cap of %d among %s" % (label, cap, caps))


class TheDetectorSeesPercentFormatting(unittest.TestCase):
    """#1203qe: the widening itself, checked on synthetic code so it cannot pass vacuously."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_r1034", Path(__file__).resolve().parent / "test_counts_and_lists_agree_1034.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def _hits(self, code):
        return self.m._count_beside_cut_list_1203jx(ast.parse(code))

    def test_a_percent_format_count_beside_a_cut_list_is_found(self):
        self.assertTrue(self._hits(
            'def f(x):\n    return "%d file(s): %s" % (len(x), ", ".join(x[:6]))\n'))

    def test_the_f_string_shape_still_fires(self):
        self.assertTrue(self._hits(
            'def f(x):\n    return f"{len(x)} file(s): {\', \'.join(x[:6])}"\n'))

    def test_a_declared_percent_cut_is_not_reported(self):
        self.assertEqual(self._hits(
            'def f(x):\n    return "%d file(s): %s" % (len(x), join_capped(x, cap=6))\n'), [])

    def test_an_uncut_percent_list_is_not_reported(self):
        self.assertEqual(self._hits(
            'def f(x):\n    return "%d file(s): %s" % (len(x), ", ".join(x))\n'), [])

    def test_a_percent_format_with_no_count_is_not_this_ratchets_subject(self):
        """#1203q7 was a cut with no count at all -- a different defect, deliberately out."""
        self.assertEqual(self._hits(
            'def f(x):\n    return "files: %s" % (", ".join(x[:6]),)\n'), [])


if __name__ == "__main__":
    unittest.main()
