"""#1203kd: a text character standing in for an icon.

The user's requirement is two-sided — a UI needs real behaviour AND icons that look like
icons. The behaviour half has a deterministic check that files a task (#1202bg) and it works:
38 of 39 modern runs deliver zero no-op handlers. The icon half had only the visual judge's
`iconography` score, and over 251 PASSING screens that is the weakest of seven dimensions
(mean 0.577, min 0.22) with 67 below 0.50 across 26 runs — a score inside a holistic bar
cannot force a change, and tightening the bar is the most expensive change available here
("70 of the 94 non-completed corpus runs die at this gate").

Real findings from the corpus, which is also what the judge saw independently ("bullet-like
red dots and simplified mismatched symbols", r185):

    r179 AuthModal.jsx:67  <AuthOption icon="⌗" label="Use QR code" .../>
    r181 CommentThread.jsx <span>♡</span><span>{compact(comment.like_count)}</span>
    r182 FeedNavigationControls.jsx <button aria-label="Previous video">⌃</button>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import glyph_icon_findings_1203kd as G  # noqa: E402


def _src(tmp_path, **files):
    d = tmp_path / "src"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


# --- the shapes that ARE a finding, each taken from a real run ---------------------------

def test_a_glyph_passed_as_the_icon_prop_is_reported_1203kd(tmp_path):
    d = _src(tmp_path, AuthModal=None) if False else _src(
        tmp_path, **{"AuthModal.jsx":
                     '<AuthOption icon="⌷" label="Use QR code" onClick={go} />\n'})
    out = G(d)
    assert len(out) == 1, out
    assert "AuthModal.jsx:1" in out[0] and "Use QR code" in out[0], out


def test_a_glyph_as_the_whole_element_body_is_reported_1203kd(tmp_path):
    d = _src(tmp_path, **{"CommentThread.jsx":
                          "<span>♡</span><span>{compact(c.like_count)}</span>\n"})
    assert len(G(d)) == 1, G(d)


def test_a_caret_in_a_button_is_reported_1203kd(tmp_path):
    d = _src(tmp_path, **{"Nav.jsx":
                          '<button aria-label="Previous video">⌃</button>\n'})
    assert len(G(d)) == 1, G(d)


# --- the shapes that must NOT be a finding ----------------------------------------------

def test_a_project_that_imports_a_real_icon_library_is_left_alone_1203kd(tmp_path):
    """Gated on the PROJECT: with a real set in use, the remaining glyph is a choice."""
    d = _src(tmp_path,
             **{"Nav.jsx": "import { Heart } from 'lucide-react'\n",
                "Row.jsx": "<span>♡</span>\n"})
    assert G(d) == [], G(d)
    # NON-VACUITY: the same tree without the import is a finding, so it is the import that
    # changed the answer and not the fixture.
    (d / "Nav.jsx").write_text("import React from 'react'\n", encoding="utf-8")
    assert len(G(d)) == 1, G(d)


def test_a_glyph_inside_a_sentence_is_copy_not_an_icon_1203kd(tmp_path):
    d = _src(tmp_path, **{"Empty.jsx":
                          "<p>No videos yet — tap ➕ to upload your first one</p>\n"})
    assert G(d) == [], G(d)


def test_plain_text_and_ascii_are_not_glyphs_1203kd(tmp_path):
    d = _src(tmp_path, **{"A.jsx": '<button aria-label="next">&gt;</button>\n'
                                   '<span>*</span><span icon="x">ok</span>\n'})
    assert G(d) == [], G(d)


# --- contract ---------------------------------------------------------------------------

def test_it_honours_its_limit_and_never_raises_1203kd(tmp_path):
    d = _src(tmp_path, **{"Many.jsx": "<span>♡</span>\n" * 40})
    assert len(G(d, limit=5)) == 5
    assert G(tmp_path / "does-not-exist") == []
    assert G(None) == []


def test_the_report_names_the_file_and_line_and_declares_its_cut_1203kd(tmp_path):
    long = "<div className=\"" + "x" * 200 + "\"><span>♡</span></div>\n"
    d = _src(tmp_path, **{"Big.jsx": "\n" + long})
    out = G(d)
    assert out and out[0].startswith("Big.jsx:2: "), out
    assert out[0].endswith("…"), ("#1034: a cut line must say it was cut", out)


# --- the dispatch half, which is where a finding becomes an instruction ------------------
#
# #1139/#1148's lesson, and #1203kc's from today: a finding with no consumer changes nothing,
# and the consumer can be dead while every test of the finding passes. The precedent #1202bg
# pins only its detector, so this pins the wiring too — by AST, because a source-text
# assertion gets fed by the comments that quote the code it is checking.

import ast  # noqa: E402

_SCAFFOLDER = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
               / "scaffolder.py")


def _calls_in_enclosing_scope_1203kd(needle):
    """Every function name called inside the def that calls `needle`."""
    tree = ast.parse(_SCAFFOLDER.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                names.add(f.id if isinstance(f, ast.Name)
                          else getattr(f, "attr", ""))
        if needle in names:
            return names
    return set()


def test_the_finding_reaches_a_lane_as_a_task_1203kd():
    names = _calls_in_enclosing_scope_1203kd("glyph_icon_findings_1203kd")
    assert names, "the detector is never called — the scan would be instrumentation only"
    assert "create_task" in names, (
        "#1203kd: a finding nobody is told about changes nothing (#1139/#1148). The glyph "
        "scan must file a task in the same scope that calls it.")
    assert "state_changed_1202ad" in names, (
        "#1202bn: create_task has no duplicate check and the scaffold runs many times per "
        "run (462 of 838 cancelled tasks were duplicates), so the filing must be gated on a "
        "CHANGED finding")


def test_it_rides_beside_its_precedent_1203kd():
    """Both halves of the same requirement are filed from the same place, so neither can be
    moved or dropped without the other being noticed."""
    names = _calls_in_enclosing_scope_1203kd("glyph_icon_findings_1203kd")
    assert "noop_handler_findings_1202bg" in names, (
        "#1203kd was written as #1202bg's sibling (behaviour / appearance); keeping them in "
        "one scope is what makes that reviewable")


def test_its_own_failure_cannot_cost_the_scaffold_1203kd():
    """#1201: an audit that raises must warn once, not take the scaffold pass down."""
    names = _calls_in_enclosing_scope_1203kd("glyph_icon_findings_1203kd")
    assert "warn_once_1201" in names, names


def test_the_object_literal_icon_form_is_reported_1203kd(tmp_path):
    """The `icon: '★'` spelling, which the generic `=` prop shape cannot see.

    Found by mutation: killing the `(?:icon|symbol|glyph)` alternative left every other test
    green, because `icon="⌗"` is ALSO a generic `=` prop. Only the colon form is unique to
    that alternative, so only this pins it.
    """
    d = _src(tmp_path, **{"nav.js":
                          "export const items = [{ label: 'Likes', icon: '♡' }]\n"})
    out = G(d)
    assert len(out) == 1, out
    assert "nav.js:1" in out[0], out


def test_a_missing_directory_is_not_reported_as_a_broken_scan_1203kd(tmp_path):
    """The `is_dir()` fast path is load-bearing for a reason a return value cannot show.

    Found by mutation: removing it still returns [] (rglob on a missing path is empty), so
    every assertion above stayed green — mutate.py's "semantic no-op" shape. But #1201's
    warning is observable, and it says "treat this as the mechanism being OFF". A frontend
    that simply has no src/ yet must not produce that sentence, or a real OFF is unreadable.
    """
    from multi_agent.runtime import message_format as MF
    MF._WARNED_1201.discard("glyph_icon_findings_1203kd")
    assert G(tmp_path / "no-src-here") == []
    assert "glyph_icon_findings_1203kd" not in MF._WARNED_1201, (
        "a frontend with no src/ is not a broken scan — #1201's warning claims the mechanism "
        "is OFF for the whole process, so it must stay for real faults")
