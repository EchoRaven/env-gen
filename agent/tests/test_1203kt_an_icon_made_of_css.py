"""#1203kt: the icon mechanism `#1203kd` could not see, and the fragment that hid the evidence.

Two defects in my own fresh detector, found by auditing it against the corpus it was built from.

ONE — a structural blind spot, not a volume question. `#1203kd` scanned `.jsx/.tsx/.js/.ts`
and a CSS pseudo-element is a whole icon mechanism none of its JSX shapes can reach:

    .login-photo-main:before { content: "\u2661" }

Measured across the modern era: 8 runs carry `content: "<glyph>"`, 10 occurrences (r176
`\u2661` and `\u2605\u2304`, r150/r152 `\u266a`, five more with one each). Seven of those 8 already
reported through a JSX shape or import a library — but `instagram-core-r176` has no JSX hit
and no icon library, so the detector reported NOTHING for a login page whose heart and star
icons are both text characters. A stylesheet cannot import a library, so reading these files
cannot weaken the project-level gate; it can only add findings the gate already allows.

TWO — the report named the right line and showed the wrong text. The fragment was the first
90 characters of the line, and a stylesheet is usually minified onto one line, so r176's two
findings both read `styles.css:3: .login-reference-page{min-height:100vh;\u2026` — the glyph the
finding is ABOUT was never visible, and the two findings were textually identical. The window
is now centred on the match, measured by the match's own COLUMN rather than by searching the
matched text inside the line: r185's `TikTokUI.jsx` carries three glyph spans on one minified
line, and a search-based window would have centred all three on the first one.
"""
import ast
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import frontend_audit as FA  # noqa: E402

HEART = "\u2661"
STAR2 = "\u2605\u2304"      # r176's two-glyph pseudo-element, verbatim
NOTE = "\u266a"

_MINIFIED_R176 = (
    ".login-reference-page{min-height:100vh;background:#fff;color:#1c1e21;display:flex;"
    "flex-direction:column;align-items:center;justify-content:center;padding:0 16px}"
    '.login-photo-main:before{content:"%s";position:absolute;right:18px;bottom:11px;'
    'color:#f04;font-size:22px}.login-star:before{content:"%s";display:block;color:#fff;'
    "font-weight:800;text-align:center}" % (HEART, STAR2))


def _frontend(tmp_path, files):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    for name, body in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


def test_a_pseudo_element_icon_is_found_in_a_stylesheet(tmp_path):
    # NON-VACUITY: the same project with a plain stylesheet reports nothing, so the finding
    # below comes from the `content:` glyph and not from scanning `.css` at all.
    clean = _frontend(tmp_path / "clean", {
        "App.jsx": "export default function App(){return <div className='x'>Hello</div>}",
        "styles.css": ".x{color:#111;font-weight:600}",
    })
    assert FA.glyph_icon_findings_1203kd(clean) == []

    src = _frontend(tmp_path / "css", {
        "App.jsx": "export default function App(){return <div className='login-star'/>}",
        "styles.css": "/* header */\n.a{color:#000}\n%s\n" % _MINIFIED_R176,
    })
    out = FA.glyph_icon_findings_1203kd(src)
    assert len(out) == 2, out
    assert all(r.startswith("styles.css:3: ") for r in out), out
    # EACH finding shows its OWN glyph. This is the half that was broken: both rows used to
    # be the head of the minified line, where neither glyph appears.
    assert any(HEART in r for r in out), out
    assert any(STAR2 in r for r in out), out
    assert out[0] != out[1], out


def test_the_fragment_is_centred_on_the_match_not_on_the_line(tmp_path):
    # Three matches on ONE long line, the shape r185's TikTokUI.jsx has. A window found by
    # searching the matched text would put the same first hit in all three rows.
    long_line = (
        "const Nav=()=>(<nav>" + "{/* %s */}" % ("pad" * 40)
        + "<span className='a'>%s</span><span className='b'>%s</span>"
          "<span className='c'>%s</span></nav>)" % (NOTE, HEART, STAR2))
    src = _frontend(tmp_path, {"Nav.jsx": long_line})
    out = FA.glyph_icon_findings_1203kd(src)
    assert len(out) == 3, out
    assert len(set(out)) == 3, out
    assert all(r.startswith("Nav.jsx:1: ") for r in out), out
    for glyph, row in zip((NOTE, HEART, STAR2), out):
        assert glyph in row, (glyph, row)
    # #1034: a cut is declared. The ellipsis is what declares it.
    assert all("\u2026" in r for r in out), out
    # THE SAME glyph twice on one line is where a search-based window actually collapses,
    # and the differing glyphs above do not reach it: `find` returns the right offset for
    # each when they differ. Measured in the corpus (2026-10-14): 26 such occurrences across
    # 10 runs, r152 and r170 among them — `>\u25cf<` twice in one line of tiktok-r116's
    # LoginPage, `>\u2304<` twice in netflix-r24's. Both findings must point at their own
    # match, or the second one sends a lane to the first one's column.
    # The two matches are placed far apart so their windows cannot overlap: each window then
    # contains exactly one of the two markers, which is what tells the rows apart. (My first
    # version put them 35 characters apart and asserted a marker was absent from the second
    # row — the windows overlapped, so the assertion failed on CORRECT output.)
    twice = ("<div className=\"%s\"><span>%s</span>FIRSTMARK%s" "SECONDMARK<span>%s</span></div>"
             % ("x" * 120, HEART, "y" * 200, HEART))
    rows = FA.glyph_icon_findings_1203kd(_frontend(tmp_path / "twice", {"D.jsx": twice}))
    assert len(rows) == 2, rows
    assert rows[0] != rows[1], ("#1203kt: both findings centred on the first match", rows)
    assert "FIRSTMARK" in rows[0] and "SECONDMARK" not in rows[0], rows
    assert "SECONDMARK" in rows[1] and "FIRSTMARK" not in rows[1], rows

    # A match at the END of a long line is cut only at the FRONT, so the leading ellipsis is
    # the one that carries #1034's declaration. Pinned separately because the rows above are
    # cut at both ends and would pass with the front marker missing.
    tail_line = _frontend(tmp_path / "tail", {
        "T.jsx": "<div className=\"%s\"><span>%s</span></div>" % ("x" * 200, HEART)})
    row = FA.glyph_icon_findings_1203kd(tail_line)[0]
    assert row.startswith("T.jsx:1: …"), row
    assert not row.endswith("…"), row
    assert HEART in row, row

    # and a SHORT line is still shown whole, with no ellipsis to mislead
    short = _frontend(tmp_path / "short", {"B.jsx": "<span>%s</span>" % HEART})
    rows = FA.glyph_icon_findings_1203kd(short)
    assert rows == ["B.jsx:1: <span>%s</span>" % HEART], rows


def test_a_glyph_inside_css_copy_is_not_an_icon(tmp_path):
    # The check's subject is a character doing an ICON's job. `content` carrying a sentence is
    # copy, exactly as in the JSX half, so the quote must follow the glyph.
    src = _frontend(tmp_path, {
        "styles.css": '.more:after{content:"%s read more"}\n.q:before{content:"\\201C"}\n' % NOTE})
    assert FA.glyph_icon_findings_1203kd(src) == []


def test_the_project_gate_still_decides_and_a_stylesheet_cannot_lift_it(tmp_path):
    files = {
        "App.jsx": "export default function App(){return <div className='login-star'/>}",
        "styles.css": '.s:before{content:"%s"}' % HEART,
    }
    assert FA.glyph_icon_findings_1203kd(_frontend(tmp_path / "a", files)) != []
    # one real import anywhere in the project silences the whole scan, CSS findings included
    with_lib = dict(files)
    with_lib["Icon.jsx"] = "import { Heart } from 'lucide-react'\nexport default Heart\n"
    assert FA.glyph_icon_findings_1203kd(_frontend(tmp_path / "b", with_lib)) == []


def test_css_is_actually_in_the_scanned_suffixes():
    """Pinned at the call site: the two tests above drive the function, and a reader could
    satisfy them by scanning every file. The suffix tuple is the decision."""
    tree = ast.parse(inspect.getsource(FA.glyph_icon_findings_1203kd))
    suffixes = [set(ast.literal_eval(n)) for n in ast.walk(tree)
                if isinstance(n, ast.Tuple) and n.elts
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in n.elts)
                and ".jsx" in {e.value for e in n.elts}]
    assert len(suffixes) == 1, suffixes
    assert ".css" in suffixes[0], suffixes[0]


def test_the_corpus_run_this_was_found_on_reports(tmp_path):
    """instagram-core-r176 is the measured case: no JSX hit, no icon library, two CSS icons.
    Skipped rather than asserted when the corpus is not on this disk."""
    import pytest
    src = ROOT.parent / "generated" / "instagram-core-r176" / "app" / "frontend" / "src"
    if not src.is_dir():
        pytest.skip("corpus run instagram-core-r176 not present")
    out = FA.glyph_icon_findings_1203kd(src)
    assert out, "r176 is the run the blind spot was found on; it must report"
    assert all(re.search(FA._GLYPH_1203KD, r) for r in out), out
