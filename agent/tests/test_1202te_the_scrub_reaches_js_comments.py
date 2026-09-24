r"""#1202te: the provenance scrub was Python-only, and framework tags shipped in JS comments.

`scrub_provenance_1202mi` states its own limit — *"Python only; anything else is returned
unchanged"* — and `#1202mi`'s inventory covers the six modules that write framework-authored
**Python**. Nothing covered the JS the same projectors emit.

Measured on the 8 most recent corpus runs, counting only unambiguous ticket tags (`#1202xx`,
`FIX #N`, `PROPOSAL #N` — a bare `#555` is a CSS colour, and the first version of this census
reported 1,074 of those as leaks before I checked):

    43 tags   .py   inside runtime LOG STRINGS
     8 tags   .js   whole-line `//` comments — every one in vite.config.js

The Python ones are left alone deliberately: they sit in `logger.warning("#1202ki restored
%d FRAMEWORK route(s)…")`, and rewriting a runtime string changes behaviour rather than
removing a comment. That is a separate decision, recorded rather than taken here.

The JS ones are comments, and comments are exactly what this scrub exists to clean.

WHY WHOLE-LINE ONLY, and why this is not a JS tokenizer: `//` appears inside ordinary string
literals (`"http://host"`) and regex literals, and rewriting one would corrupt a served file —
the failure the module's own docstring refuses ("shipping a tag is better than shipping a
broken file"). A line whose first non-space characters are `//` cannot be inside a string. The
rule was chosen after measuring, not before: all 8 observed leaks are that shape.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.provenance_scrub import scrub_provenance_1202mi as scrub  # noqa: E402


def test_the_leak_that_shipped_is_removed():
    """vite.config.js:71, verbatim from frontend_scaffold's own template."""
    src = ("export default defineConfig({\n"
           "  // #1202ef: a JS crash here must name a place someone can go. `sourcemap`\n"
           "  build: { sourcemap: true },\n})\n")
    out = scrub(src, "vite.config.js")
    assert "#1202ef" not in out
    assert "a JS crash here must name a place someone can go." in out, "the prose must survive"
    assert out.count("\n") == src.count("\n"), "no line may be added or lost"


@pytest.mark.parametrize("name", ["a.js", "a.jsx", "a.ts", "a.tsx", "a.mjs", "a.cjs"])
def test_every_js_flavour_is_covered(name):
    assert "#1202db" not in scrub("// #1202db: note\n", name)


def test_a_url_in_a_string_is_never_touched():
    """The whole reason this is not a tokenizer. `//` inside a literal must survive, tag or
    no tag."""
    for src in ('const base = "http://localhost:8000";\n',
                'const u = "http://h/#1202ef";\n',
                "const re = /https?:\\/\\/#1202ef/;\n"):
        assert scrub(src, "api.js") == src


def test_a_trailing_comment_after_code_is_left_alone():
    """Deliberately out of scope: telling a trailing `//` from one inside a string needs a
    tokenizer. None was observed in the corpus; if one ships, the same census finds it."""
    src = 'const base = "http://x";  // #1202ef trailing\n'
    assert scrub(src, "api.js") == src


def test_the_orphaned_punctuation_is_tidied():
    """`// FIX #130: text` must not become `//: text` — a stray marker reads as a typo in a
    served file. The Python path has had this since #1202mi; the JS path needed the same."""
    assert scrub("  // FIX #130: the route order matters\n", "App.jsx") == \
        "  // the route order matters\n"


def test_a_comment_free_js_file_is_not_reported_as_unparsed():
    """#1202mi logs and records a file it could not parse, so a released environment can be
    audited. A JS file with no whole-line comment is not that case, and must not pollute the
    census."""
    src = 'const x = "#1202ef";\n'
    assert scrub(src, "x.js") == src


def test_css_and_other_text_are_still_untouched():
    assert scrub("/* #1202ef */\n", "styles.css") == "/* #1202ef */\n"
    assert scrub("# #1202ef\n", "notes.txt") == "# #1202ef\n"


def test_python_behaviour_is_unchanged():
    assert scrub("# FIX #130: the route order matters\n", "x.py") == \
        "# the route order matters\n"
    assert scrub("# #1202ef: a crash here must name a place\n", "y.py") == \
        "# a crash here must name a place\n"


def test_the_template_that_shipped_it_still_carries_the_tag_in_the_FRAMEWORK():
    """The tag belongs in our source — it is how the next reader finds #1202ef's reasoning.
    The scrub removes it on the way OUT; this pins that we did not 'fix' it by deleting the
    provenance from the framework itself."""
    fs = (LLM_DIR / "multi_agent" / "runtime" / "frontend_scaffold.py").read_text(
        encoding="utf-8")
    assert "// #1202ef:" in fs
