"""#1203jv: the missing-export repair knew two ways a name can exist, and there are three.

`repair_frontend_missing_local_exports` exists so that `import { X } from './Y'` against a Y
that does not export X cannot hard-fail the Rollup build. It branched on: already exported
(skip), declared with const/let/var/function/class (re-export), appears nowhere (stub). A name
BOUND BY AN IMPORT in the target matches none of those, so it fell off the chain and nothing
was written — silently.

tiktok-web-r186 paid for it: `npm run build` failed ELEVEN times with

    "Link" is not exported by "src/components/TikTokComponents.jsx",
    imported by "src/pages/LiveDiscoverPage.jsx"

while line 2 of that module read `import { Link, useNavigate } from '../lib/router.jsx';`.
The run delivered 1 of its 4 milestones. Measured across the corpus: 15 "is not exported by"
events, 11 of them this blind spot (all r186, all `Link`) and 4 the declared kind the repair
already handled.

Driven against the REAL artifact — r186's own TikTokComponents.jsx plus the importing line
quoted verbatim from the build log — the repair now appends `export { Link };`.
"""
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE)))

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _import_bound_1203jv as import_bound,
    repair_frontend_missing_local_exports as repair,
)


@pytest.mark.parametrize("stmt,name,expected", [
    ("import { Link, useNavigate } from '../lib/router.jsx';", "Link", True),
    ("import { Link, useNavigate } from '../lib/router.jsx';", "useNavigate", True),
    ("import { Link } from 'x';", "Nope", False),
    # the `as` direction, which is why this parses instead of grepping
    ("import { a as Link } from 'x';", "Link", True),
    ("import { a as Link } from 'x';", "a", False),
    ("import { Link as b } from 'x';", "Link", False),
    ("import { Link as b } from 'x';", "b", True),
    ("import Link from 'x';", "Link", True),
    ("import * as Link from 'x';", "Link", True),
    ("import Def, { Link } from 'x';", "Link", True),
    ("import Def, { Link } from 'x';", "Def", True),
    # a mention that is NOT a binding
    ("const s = 'import { Link } from';", "Link", False),
    # A commented-out import creates NO binding, so False is the only safe answer: emitting
    # `export { Link };` against it would replace one build breaker with another (an export
    # of an undefined name). My first version of this case expected True and the
    # implementation was right -- the anchor is `^[ \t]*import`, and `//` is not whitespace.
    ("// import { Link } from './x'", "Link", False),
])
def test_the_binding_direction_of_as_is_respected(stmt, name, expected):
    assert import_bound(stmt, name) is expected, (stmt, name)


def test_it_never_raises_on_junk():
    for junk in (None, "", "import", "import from", "import {", "import { } from"):
        assert import_bound(junk, "X") is False, junk


@pytest.mark.parametrize("bad", [123, b"import { X } from 'y'", object(), ["import"]])
def test_a_type_it_cannot_scan_declines_rather_than_asserting(bad):
    """Exercises the `except` itself, which the junk above never reaches.

    `None` and `""` are handled by `src or ""` without raising, so a mutation turning the
    handler into `return True` survived the first version of this file. It must not: "I could
    not look" has to mean DECLINE, because a True here emits `export { n };` for a binding
    that may not exist -- trading one build breaker for another.
    """
    assert import_bound(bad, "X") is False, bad


def _fe(tmp_path, target_src, page_import="import { Widget } from '../components/C.jsx';"):
    for d in ("src/components", "src/pages"):
        os.makedirs(os.path.join(str(tmp_path), d), exist_ok=True)
    open(os.path.join(str(tmp_path), "src/components/C.jsx"), "w").write(target_src)
    open(os.path.join(str(tmp_path), "src/pages/P.jsx"), "w").write(
        page_import + "\nexport default function P(){ return null; }\n")
    return str(tmp_path)


def test_an_import_bound_name_is_re_exported(tmp_path):
    """r186's shape: the target imports the name and uses it, but never re-exports it."""
    fe = _fe(tmp_path, "import { Widget } from '../lib/w.jsx';\n"
                       "export function Shell(){ return <Widget/>; }\n")
    out = repair(fe)
    assert ("C.jsx", ["Widget"]) in (out.get("reexported") or []), out
    body = open(os.path.join(fe, "src/components/C.jsx")).read()
    assert "export { Widget };" in body, body
    # and NOT stubbed -- a stub beside the import would be a duplicate declaration
    assert "export const Widget" not in body, body


def test_a_declared_name_is_still_re_exported(tmp_path):
    """The branch that already worked must keep working."""
    fe = _fe(tmp_path, "const Widget = createContext();\nexport function Shell(){ return null; }\n")
    out = repair(fe)
    assert ("C.jsx", ["Widget"]) in (out.get("reexported") or []), out


def test_a_name_that_appears_nowhere_is_still_stubbed(tmp_path):
    fe = _fe(tmp_path, "export function Shell(){ return null; }\n")
    out = repair(fe)
    assert ("C.jsx", ["Widget"]) in (out.get("repaired") or []), out
    assert "export const Widget" in open(os.path.join(fe, "src/components/C.jsx")).read()


def test_an_already_exported_name_is_left_alone(tmp_path):
    fe = _fe(tmp_path, "export function Widget(){ return null; }\n")
    out = repair(fe)
    assert not out.get("repaired") and not out.get("reexported"), out
    assert not out.get("unrepairable_1203jv"), out


def test_a_name_that_matches_no_branch_is_reported_not_swallowed(tmp_path):
    """The fall-through that cost eleven silent builds now has a name and a key.

    `Widget` here is neither exported, nor declared, nor import-bound, nor absent -- it only
    appears inside a string. Declining is still right (a stub could collide); declining in
    silence is what the run paid for.
    """
    fe = _fe(tmp_path, "export function Shell(){ return 'Widget is coming soon'; }\n")
    out = repair(fe)
    assert ("C.jsx", "Widget") in (out.get("unrepairable_1203jv") or []), out
    body = open(os.path.join(fe, "src/components/C.jsx")).read()
    assert "export const Widget" not in body and "export { Widget }" not in body, body


def test_the_real_r186_module_is_repaired(tmp_path):
    """Against the artifact itself, with the importing line quoted from the build log.

    Skips rather than passes when the run has been reclaimed -- a test that silently stops
    checking is the thing this repo keeps paying for.
    """
    real = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                        "generated/tiktok-web-r186/app/frontend/src/components/"
                        "TikTokComponents.jsx")
    if not os.path.isfile(real):
        pytest.skip("generated/tiktok-web-r186 is not on disk")
    src = open(real, encoding="utf-8", errors="ignore").read()
    assert "import { Link, useNavigate } from '../lib/router.jsx';" in src, (
        "the artifact no longer carries the line this test is about")
    fe = _fe(tmp_path, src,
             page_import="import { Icon, Link, VideoMedia, VideoTile } "
                         "from '../components/C.jsx';")
    out = repair(fe)
    names = dict(out.get("reexported") or []).get("C.jsx") or []
    assert "Link" in names, out
