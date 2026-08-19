"""#970: the icon heal must read minified imports, and splice into the import region.

netflix r157 failed `docker_up` twelve times on:

    /app/src/components/LandingHero.jsx:2:9: ERROR: The symbol "Link" has already been declared

and aborted at the no-convergence gate without delivering. Two bugs in
`repair_frontend_unimported_icons`, both from the same wrong assumption — that generated
components are line-oriented. They are routinely emitted MINIFIED: every import and the
whole component on one line.

  1. `_IMPORT_NAMES_RE` required `import\\s+`, so the very common no-space brace form
     `import{Link}from'react-router-dom'` never matched. The binding was invisible, `Link`
     looked unimported, and the heal injected a SECOND `Link` from lucide-react.
  2. The insertion point was "after the last LINE starting with `import `". In a minified
     file that line is the whole module, so the new import landed AFTER the component —
     an import statement in the middle of the module body.

Bug 1 alone caused r157; bug 2 would have produced invalid placement for any genuinely
missing icon in a minified file, so both are fixed here.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _IMPORT_STMT_RE, _unimported_jsx_tags, repair_frontend_unimported_icons)

# Verbatim shape from netflix r157 (whole module on one line, no space after `import`).
MINIFIED = (
    "import NetflixWordmark from'./NetflixWordmark';"
    "import RegistrationEntry from'./RegistrationEntry';"
    "import{Link}from'react-router-dom';"
    "export default function LandingHero(){return <main>"
    "<NetflixWordmark/><Link className=\"red\" to=\"/login\">Sign In</Link>"
    "<RegistrationEntry/></main>}"
)


def test_a_no_space_brace_import_counts_as_imported():
    assert "Link" not in _unimported_jsx_tags(MINIFIED), (
        "`import{Link}from'…'` binds Link; treating it as unimported is what injected the "
        "duplicate lucide-react import that broke every build in r157")


def test_importfoo_is_not_mistaken_for_an_import():
    """The relaxed whitespace must not swallow an identifier that merely starts with the
    word — \\bimport\\b has no boundary between two word characters."""
    src = "const importFoo = 1; export default () => <Widget/>;"
    assert "Widget" in _unimported_jsx_tags(src)


def test_a_normal_multiline_file_is_unaffected():
    src = (
        'import React from "react";\n'
        'import { Foo } from "./foo";\n'
        "\n"
        "export default function P(){ return <Bar/>; }\n"
    )
    assert _unimported_jsx_tags(src) == ["Bar"]


@pytest.mark.parametrize("src,tail", [
    ("import{Link}from'react-router-dom';export default function X(){}",
     "import{Link}from'react-router-dom';"),
    ('import React from "react";\nexport default function X(){}\n',
     'import React from "react";'),
    ("import './styles.css';\nexport default function X(){}\n",
     "import './styles.css';"),
])
def test_the_splice_point_is_the_last_import_statement(src, tail):
    last = list(_IMPORT_STMT_RE.finditer(src))[-1]
    assert src[:last.end()].endswith(tail), (
        "a new import must go after the last import STATEMENT; anchoring on the last "
        "import LINE puts it after the component in a minified file")


def test_the_injected_import_lands_before_the_component(tmp_path):
    """End to end: a genuinely missing icon in a MINIFIED file must still be spliced into
    the import region, not appended past the module body."""
    src_dir = tmp_path / "src" / "components"
    src_dir.mkdir(parents=True)
    page = src_dir / "Hero.jsx"
    # r157's exact shape: the FIRST import is spaced (so the old line rule found it and
    # anchored on line 0 = the whole module), a later one is not.
    page.write_text(
        "import NetflixWordmark from'./NetflixWordmark';"
        "import{Link}from'react-router-dom';"
        "export default function Hero(){return <Link to=\"/\"><NetflixWordmark/><Play/></Link>}",
        encoding="utf-8")

    repair_frontend_unimported_icons(tmp_path)
    out = page.read_text(encoding="utf-8")

    assert out.count("Link") >= 1 and "lucide-react" in out
    assert "Play" in out.split("lucide-react")[0], "Play is the icon that needed importing"
    inject_at = out.index("lucide-react")
    assert inject_at < out.index("export default"), (
        f"the injected import landed after the component:\n{out}")
    assert out.count("{ Link }") == 0, "Link must not be re-imported from lucide-react"


def test_the_control_misses_the_minified_import():
    """Planted control: the PRE-FIX regex must fail to see the no-space binding. Synthetic,
    so fixing the real scanner can never turn this red."""
    import re
    pre_fix = re.compile(
        r"import\s+(?:([A-Za-z_$][\w$]*)\s*,?\s*)?(?:\{([^}]*)\})?\s*from", re.S)
    seen = {g.strip() for m in pre_fix.finditer(MINIFIED) for g in (m.group(2) or "").split(",") if g.strip()}
    assert "Link" not in seen, (
        "the control was supposed to miss the no-space import; if it sees it, the fix is "
        "unmotivated and the main test proves nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
