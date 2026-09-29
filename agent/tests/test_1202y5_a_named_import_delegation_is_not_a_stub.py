r"""#1202y5: a delegating page written with a NAMED import is not a placeholder stub.

`_composes_child` credited a page that imports a component and renders it -- the tolerance
added for the pages that hold five real children and carry no call of their own. Its pattern
was `import \w+ from '...components/X'`, a DEFAULT import, so

    import { ExploreView } from '../components/DiscoveryPages';
    export default function ExploreGridPage() { return <ExploreView />; }

matched nothing. r140's lane wrote every delegating page that way, and the gate called all
seven "a placeholder stub that renders no real UI" -- 90 seconds AFTER the files were
written, holding delivery on finished pages. All four predicates were computed on the live
files to be sure: `_placeholder` False, `_has_call` False, `handler_tokens` False, and
`_composes_child` False on its own is what made `_declared_but_inert` True.

Measured on that run rather than argued: 7 pages named 21-24 times each between 02:49 and
02:54:58, the gate green at 02:56:17, and every one of the 7 cleared by the lane adding a
feed call -- to a profile page, a notifications page and a direct-message page alike. A
delegating page has no call of its own to offer, so the check asks it to prove itself in a
currency it does not hold and gets paid in calls that do not belong there.

The two import forms are the SAME evidence ("this page imports a component and renders
it"), so accepting only one of them was a gap, not a standard. Nothing is loosened.

★ WHY THIS ONE IS REAL AND THE PREVIOUS ONE WAS NOT. The same check was accused a week's
worth of runs earlier and the accusation was wrong twice over: the page had genuinely been a
stub when the blocker fired (the file was rewritten three minutes LATER), and
`_composes_child` already excused the shape being claimed. Here the timestamps run the other
way and the predicate is computed, not assumed.

Corpus: exactly ONE run carries this page style -- the run that found it. So this is a style
a lane can choose at any time rather than a long-standing defect, and the next lane to
choose it would have been blocked the same way.
"""
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_RUNTIME = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _composes_child_pattern():
    """The live pattern, read from the module rather than restated here (#1032)."""
    src = _read(os.path.join(_RUNTIME, "frontend_audit.py"))
    i = src.index("_composes_child = bool(re.search(")
    j = src.index("comp_file_text)) and bool", i)
    raw = src[src.index("r\"", i):j]
    return re.compile(eval(raw.strip().rstrip(",").strip()))


_NAMED = "import { ExploreView } from '../components/DiscoveryPages';"
_DEFAULT = "import Shell from '../components/Shell';"
_EXT = "import Modal from '../components/TitleDetailModal.jsx';"
_SERVICE = "import { getFeed } from '../services/api';"
_HOOK = "import { useCatalog } from '../hooks/useCatalog';"


def test_a_named_component_import_counts():
    """r140's exact line."""
    assert _composes_child_pattern().search(_NAMED), (
        "a named component import is the same evidence as a default one")


def test_the_default_import_still_counts():
    p = _composes_child_pattern()
    assert p.search(_DEFAULT)
    assert p.search(_EXT), "#566j's extension tolerance must survive"


def test_a_service_import_is_not_a_child_component():
    """`from '../services/api'` is the api client. Crediting it would excuse a page that
    imports the client and never calls it -- which is what §2 hardened against."""
    assert not _composes_child_pattern().search(_SERVICE)


def test_a_hook_import_is_not_a_child_component():
    assert not _composes_child_pattern().search(_HOOK)


def test_the_live_shape_is_no_longer_inert():
    """End to end on the four predicates, in the order the check applies them."""
    from multi_agent.runtime.frontend_audit import _has_real_api_call, _HANDLER_TOKENS

    text = (_NAMED + "\n"
            "export default function ExploreGridPage() { return <ExploreView />; }\n")
    placeholder = any(p in text.lower() for p in (
        "this section is being set up", "under construction", "coming soon",
        "placeholder page", "todo: implement"))
    composes = bool(_composes_child_pattern().search(text)) and bool(
        re.search(r"<[A-Z]\w+[\s/>]", text))
    inert = (True and not _has_real_api_call(text) and not composes
             and not any(t in text for t in _HANDLER_TOKENS))
    assert not placeholder and not inert, (
        "placeholder=%s inert=%s -- the page would still be called a stub" % (placeholder, inert))


def test_a_page_that_imports_a_component_but_renders_none_is_still_inert():
    """The second half of `_composes_child` is untouched: an import alone is not a child."""
    text = _NAMED + "\nexport default function P() { return null; }\n"
    composes = bool(_composes_child_pattern().search(text)) and bool(
        re.search(r"<[A-Z]\w+[\s/>]", text))
    assert not composes
