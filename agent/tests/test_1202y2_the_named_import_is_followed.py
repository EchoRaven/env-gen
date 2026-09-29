r"""#1202y2: follow a NAMED import too, and only when the module's answer cannot be diluted.

`page_api_endpoints_1202wd` descended through `import X from './X'` and nothing else, so a
page written against a multi-export module was unresolvable. r139's lane rewrote its pages
down to two lines each --

    import { ExploreScreen } from '../components/SecondaryScreens';
    export default function ExploreGridPage() { return <ExploreScreen />; }

-- and `components/SecondaryScreens.jsx` is what imports the service module. The resolver
answered [] for nine of twelve pages, so `deliverability_page_apis_understated` fired 0
times in 148 gate ticks and the gate went GREEN with those pages declaring `apis_used: []`.
14 corpus runs hold this shape (r139 7 pages, netflix-r2 6, r126 5, r137 3, r136 2).

★ THE FIRST ATTEMPT FIXED THE WRONG HALF. It taught `_locate` to find the file that EXPORTS
a name -- and `_locate` was never reached, because the walk only ever proposed names taken
from default imports. The test below is the one that caught it: it drives the resolver
end-to-end rather than the helper.

GUARDED, because the naive version is the failure this resolver already documents: r89
descended into a shared child and gave three unrelated pages the same four endpoints,
"worse in a blocker than saying nothing". A barrel holds SEVERAL components, so crediting a
page with everything the barrel calls is exactly that. Descend only when the module resolves
to AT MOST ONE endpoint -- then the union is the precise answer whichever export the page
took, and dilution is impossible by construction. r139's SecondaryScreens exports six
screens and imports one api function, which is why it resolves; a barrel reaching two
different endpoints stays unresolved rather than guessed at.

LOCAL-ONLY (gitignored).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.frontend_audit import page_api_endpoints_1202wd  # noqa: E402

_API_TWO = ("export async function getFeed() { return request('/api/videos/feed'); }\n"
            "export async function getSearch() { return request('/api/search'); }\n")


def _tree(tmp, pages, components, api=_API_TWO):
    src = tmp / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir()
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(api, encoding="utf-8")
    for n, body in pages.items():
        (src / "pages" / ("%s.jsx" % n)).write_text(body, encoding="utf-8")
    for n, body in components.items():
        (src / "components" / ("%s.jsx" % n)).write_text(body, encoding="utf-8")
    return tmp


_ONE_CALL_BARREL = ("import { getFeed } from '../services/api';\n"
                    "export function ExploreScreen() { getFeed(); return null; }\n"
                    "export function LiveScreen() { getFeed(); return null; }\n"
                    "export function ProfileScreen() { return null; }\n")

_TWO_CALL_BARREL = ("import { getFeed, getSearch } from '../services/api';\n"
                    "export function ExploreScreen() { getFeed(); return null; }\n"
                    "export function SearchScreen() { getSearch(); return null; }\n")

_PAGE = ("import { %s } from '../components/%s';\n"
         "export default function P() { return <%s />; }\n")


def test_a_named_import_of_a_one_call_module_resolves(tmp_path):
    """r139's exact shape, end to end through the resolver."""
    _tree(tmp_path,
          {"P": _PAGE % ("ExploreScreen", "SecondaryScreens", "ExploreScreen")},
          {"SecondaryScreens": _ONE_CALL_BARREL})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == ["GET /api/videos/feed"]


def test_a_module_reaching_two_endpoints_stays_unresolved(tmp_path):
    """★ r89's failure, made impossible: crediting the page with BOTH would be a guess
    about which export it took."""
    _tree(tmp_path,
          {"P": _PAGE % ("ExploreScreen", "Barrel", "ExploreScreen")},
          {"Barrel": _TWO_CALL_BARREL})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == [], (
        "a barrel reaching two endpoints must stay unresolved, not be guessed at")


def test_the_default_import_path_is_unchanged(tmp_path):
    _tree(tmp_path,
          {"P": ("import Shell from '../components/Shell';\n"
                 "export default function P() { return <Shell />; }\n")},
          {"Shell": ("import { getSearch } from '../services/api';\n"
                     "export default function Shell() { getSearch(); return null; }\n")})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == ["GET /api/search"]


def test_a_page_that_calls_for_itself_does_not_descend(tmp_path):
    """The existing `if own: return` guard: a file that calls the API is the answer, and
    its children are chrome (r89)."""
    _tree(tmp_path,
          {"P": ("import { getSearch } from '../services/api';\n"
                 "import { ExploreScreen } from '../components/SecondaryScreens';\n"
                 "export default function P() { getSearch(); return <ExploreScreen />; }\n")},
          {"SecondaryScreens": _ONE_CALL_BARREL})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == ["GET /api/search"], (
        "the page's own call is the answer; the barrel below it must not be added")


def test_a_named_import_of_a_module_with_no_api_call_adds_nothing(tmp_path):
    _tree(tmp_path,
          {"P": _PAGE % ("Chrome", "Chrome", "Chrome")},
          {"Chrome": "export function Chrome() { return null; }\n"})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == []


def test_a_named_import_of_a_module_that_does_not_exist_is_ignored(tmp_path):
    _tree(tmp_path,
          {"P": _PAGE % ("Gone", "NotHere", "Gone")},
          {"SecondaryScreens": _ONE_CALL_BARREL})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == []


def test_a_service_import_is_not_treated_as_a_component_module(tmp_path):
    """`import { getFeed } from '../services/api'` is the api client, not a child to walk;
    the existing branch above already consumed it."""
    _tree(tmp_path,
          {"P": ("import { getFeed } from '../services/api';\n"
                 "export default function P() { getFeed(); return null; }\n")},
          {})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == ["GET /api/videos/feed"]


def test_one_hop_only_and_the_walk_terminates(tmp_path):
    """The guard is deliberate and this is what it costs.

    Descent needs the module's endpoint set to be a single element, and a module that makes
    no call of its own has an UNDETERMINED set -- resolving it would mean walking the subtree
    first, which re-opens the dilution r89 measured. All 14 corpus runs carrying this shape
    are one hop (page -> a module that calls), so the chain below stays unresolved by design.
    It must also TERMINATE: A and B import each other."""
    _tree(tmp_path,
          {"P": _PAGE % ("A", "A", "A")},
          {"A": ("import { B } from '../components/B';\n"
                 "export function A() { return <B />; }\n"),
           "B": ("import { A } from '../components/A';\n"
                 "import { getFeed } from '../services/api';\n"
                 "export function B() { getFeed(); return null; }\n")})
    assert page_api_endpoints_1202wd(str(tmp_path), "P") == []
