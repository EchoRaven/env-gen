r"""#1203l5: the framework said `copy` was the scoring floor, and the verdicts say iconography.

Two places stated it:

  * `visual_fidelity._copy_lines_797`'s docstring -- "84% of their notes DESCRIBED the text
    rather than quoting it, which is why `ui_copy` keeps scoring as a floor";
  * `design_prep`'s schema comment -- "`copy` is the most frequent scoring floor on `login`,
    which blocks 73% of runs".

Both are contradicted by the visual gate's own verdicts on disk, under either reading of
"floor" and in every era:

    mean score, 302 modern screens
        iconography .52   components .56   layout .63   style .71
        typography .74    copy .77         color .79
    times a dimension is the LOWEST on its screen, 1119 screens scored on 5+ dimensions
        iconography 41%   components 40%   layout 8%    copy 6%
        typography 3%     style 2%         color 2%

`copy` is 4th of 7 by that count and 6th of 7 by mean. Restricted to the narrower claim's own
universe -- 92 scored login/signup screens -- `copy` is the floor on ONE (1%), last of six,
while iconography is the floor on 44 (48%). Nor is it an era effect: the pre-r100 login floors
are color 13, components 13, iconography 7.

Nothing is removed by this: the `copy` slot is still worth having, 84% describing rather than
quoting is still measured, and #1203kz still fills the field #797 reads. What is gone is the
claim about WHICH dimension that costs, because it points effort away from the two dimensions
that are actually the floor -- and those two are exactly what #1203kd and #1203l4 touch. It is
also the sentence I repeated in #1203kz's own commit message before measuring it.

#1203j2's rule: a false sentence in the framework is its own defect, and deleting it is not
the same as adding an explanation.
"""
import ast
import inspect
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import design_prep as DP  # noqa: E402
from multi_agent.runtime import visual_fidelity as VF  # noqa: E402

CLAIMS = ("keeps scoring as a floor", "most frequent scoring floor")


def _comment_blocks(path):
    """Every contiguous run of comment lines in the file, whitespace-normalised.

    Per BLOCK and NORMALISED, both deliberately. Per block because a contiguous comment run is
    a structural anchor rather than the byte window #943 forbids; normalised because the first
    version of this test searched line by line and found nothing -- my own correction WRAPS the
    quoted sentence across two lines, which is the trap where prose defeats an `in` check.
    """
    out, cur = [], []
    for ln in path.read_text(encoding="utf-8").split("\n"):
        if ln.lstrip().startswith("#"):
            cur.append(ln.lstrip().lstrip("#"))
        elif cur:
            out.append(" ".join(" ".join(cur).split()))
            cur = []
    if cur:
        out.append(" ".join(" ".join(cur).split()))
    return out


def test_the_claim_is_no_longer_asserted_anywhere():
    """The subtlety: the correction QUOTES the sentence, so "the text is absent" is the wrong
    assertion -- it is the trap where a comment about the code feeds a text check. Every
    surviving occurrence must sit in a comment block that names the ticket correcting it."""
    for mod in (VF, DP):
        path = Path(inspect.getfile(mod))
        blocks = [b for b in _comment_blocks(path) if any(c in b for c in CLAIMS)]
        assert blocks, ("%s: the sentence vanished entirely, so this test proves nothing -- it "
                        "is supposed to be quoted inside the correction" % path.name)
        for b in blocks:
            assert "1203l5" in b, (path.name, b[:300])
            # ...and it must be QUOTED, not re-asserted. Mutation found the gap: contiguous
            # comment lines merge into one block, so re-inserting the claim on the line just
            # above the correction satisfied "the block names the ticket". A correction
            # QUOTES the sentence; an assertion does not.
            outside = re.sub(r'"[^"]*"', " ", b)
            for c in CLAIMS:
                assert c not in outside, (path.name, c, outside[:300])


def test_the_797_docstring_no_longer_carries_it():
    """The visual_fidelity occurrence was in a DOCSTRING, which is the framework asserting it.
    Asked of the parsed docstring, so a comment quoting the sentence cannot satisfy it."""
    doc = inspect.getdoc(VF._copy_lines_797) or ""
    for c in CLAIMS:
        assert c not in doc, doc
    # NON-VACUITY: the docstring still explains what the block is for
    assert "84%" in doc and "VERBATIM" in doc, doc


def test_the_schema_comment_is_asked_by_ast_not_by_text():
    """design_prep's occurrence is a comment beside a schema key, so the key must still be
    there -- the correction is to the prose, not to the contract."""
    tree = ast.parse(Path(inspect.getfile(DP)).read_text(encoding="utf-8"))
    # the schema dict itself, found by a key only it has -- not every string in the file.
    # Mutation found that: renaming the key to `copyx` left `"copy"` in the module's prose
    # and the first version of this assertion passed.
    schemas = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
               and any(isinstance(k, ast.Constant) and k.value == "build_notes"
                       for k in n.keys)]
    # TWO dicts carry `build_notes`: the skeleton's component shape and the analyst's JSON
    # schema. Both must carry these keys, so the assertion is made of each rather than of a
    # dict picked by position -- which is also stronger than the single one I first wrote.
    assert len(schemas) == 2, [n.lineno for n in schemas]
    for n in schemas:
        keys = {k.value for k in n.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        assert {"copy", "data_slots"} <= keys, (n.lineno, sorted(keys))


def test_the_replacement_numbers_hold_against_the_verdicts():
    """The measurement that replaced the claim, recomputed. Skipped when the corpus is absent."""
    import pytest
    low = Counter()
    means = defaultdict(list)
    screens_scored = 0
    login_low = Counter()
    LOGIN = re.compile(r"login|signin|sign_in|signup|sign_up|register|auth", re.I)
    for p in sorted((ROOT.parent / "generated").glob("*/design/visual_gate/verdict.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        screens = d.get("screens") or d.get("results") or []
        if isinstance(screens, dict):
            screens = list(screens.values())
        for s in screens:
            if not isinstance(s, dict):
                continue
            dims = s.get("dimensions") or s.get("scores") or {}
            got = {}
            if isinstance(dims, dict):
                for k, v in dims.items():
                    sc = v if isinstance(v, (int, float)) else (
                        v.get("score") if isinstance(v, dict) else None)
                    if isinstance(sc, (int, float)):
                        got[k] = float(sc)
            if len(got) < 5:
                continue
            screens_scored += 1
            for k, v in got.items():
                means[k].append(v)
            mn = min(got.values())
            name = str(s.get("name") or s.get("screen") or "")
            for k, v in got.items():
                if v == mn:
                    low[k] += 1
                    if LOGIN.search(name):
                        login_low[k] += 1
    if screens_scored < 300:
        pytest.skip("too few scored screens on this disk (%d)" % screens_scored)
    worst_two = {k for k, _ in low.most_common(2)}
    assert worst_two == {"iconography", "components"}, low.most_common()
    assert low["copy"] < low["iconography"] / 4, low.most_common()
    # and by mean, copy is in the upper half
    ranked = sorted(means, key=lambda k: statistics.mean(means[k]))
    assert ranked.index("copy") >= len(ranked) // 2, [
        (k, round(statistics.mean(means[k]), 3)) for k in ranked]
    # the narrower claim, on its own universe
    if sum(login_low.values()) >= 50:
        assert login_low.most_common(1)[0][0] == "iconography", login_low.most_common()
        assert login_low["copy"] <= 2, login_low.most_common()


def test_the_copy_block_still_renders_when_the_field_is_filled():
    """Non-regression: this ticket corrects prose and removes no behaviour."""
    ds = {"screens": [{"name": "login", "components": [
        {"id": "cta", "copy": "Log in to TikTok"}]}]}
    lines = VF._copy_lines_797(ds, "login")
    assert lines and any("Log in to TikTok" in ln for ln in lines), lines
    assert VF._copy_lines_797(ds, "nope") == []
    assert VF._copy_lines_797({"screens": [{"name": "login", "components": [
        {"id": "cta", "copy": ""}]}]}, "login") == []
