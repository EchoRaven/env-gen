r"""#1202y1: the understatement check compares the registry against the SOURCE, not
against the empty list.

`_page_api_declaration_drift` only ever examined pages declaring NOTHING
(`if rec.get("apis_used"): continue`), so a page declaring one of its three calls was
clean by construction. That is also why #1202wd refused to backfill from its own reader:
"a half-resolved list written into the registry would silence it while the contradiction
stood" -- true, with an empty-list trigger. #1202xv then made the framework fill
`apis_used` from that reader, which would have bought exactly that silence. This removes
the coupling: a partial list is still reported, so filling can never silence the check.

Measured over the corpus before the change: 99 runs hold a page whose `apis_used` is
non-empty and whose source calls MORE -- netflix-local-r30 14 pages / 53 endpoints,
tiktok-r138 5 / 15, r136 4 / 10 -- none of it visible to this check.

ONE DIRECTION ONLY. `page_api_endpoints_1202wd` does not traverse custom hooks
(netflix-r16's BrowseHomePage routes its calls through `useCatalog`, which is where the
service imports live), so `declared - source` is routinely non-empty on a CORRECT page.
Firing there would be the blind spot guessing; the reader missing a call must make this
check silent, not wrong.

AND THE NAME MUST STILL ROUTE. The check id is derived from the blocker PROSE by substring
(`delivery_gate._blocker_check_id`), so rewording it dispatches nobody -- #1202tu measured
that shape on r132: 67/67 gate snapshots carrying "NO remediation owner" while every other
check was dispatched. Both phrasings map to the same id, and a test below pins it.

LOCAL-ONLY (gitignored).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))


def _pages(*recs):
    return {("p%d" % i): r for i, r in enumerate(recs)}


class _RH:
    def __init__(self, pages):
        self._p = pages

    def list_ui_pages(self):
        return self._p


class _Hubs:
    def __init__(self, pages):
        self.registryhub = _RH(pages)


def _tree(tmp_path, calls_by_component):
    """A frontend tree whose pages call the service module, r139's own shape."""
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir()
    api = []
    for comp, eps in calls_by_component.items():
        body = []
        for i, (m, p) in enumerate(eps):
            fn = "call%s%d" % (comp, i)
            api.append("export async function %s() { return request('%s', {method:'%s'}); }"
                       % (fn, p, m))
            body.append("  %s();" % fn)
        (src / "pages" / ("%s.jsx" % comp)).write_text(
            "import { %s } from '../services/api.js';\n"
            "export default function %s() {\n%s\n  return null;\n}\n"
            % (", ".join("call%s%d" % (comp, i) for i in range(len(eps))), comp,
               "\n".join(body)), encoding="utf-8")
    (src / "services" / "api.js").write_text("\n".join(api) + "\n", encoding="utf-8")
    return tmp_path


def _drift(tmp_path, pages, calls):
    from multi_agent.runtime.deliverability import _page_api_declaration_drift_1202rr as d
    return d(_Hubs(pages), str(_tree(tmp_path, calls)))


def test_a_partial_declaration_is_reported(tmp_path):
    """The case the old trigger could not see, and the one #1202xv would have created."""
    out = _drift(tmp_path,
                 _pages({"name": "explore", "component": "Explore",
                         "apis_used": ["GET /api/videos/feed"]}),
                 {"Explore": [("GET", "/api/videos/feed"), ("GET", "/api/search")]})
    assert out, "a page declaring 1 of its 2 calls is still understated"
    assert "/api/search" in out[0], out
    assert "/api/videos/feed" not in out[0], (
        "only what the registry LACKS should be named: %r" % out)


def test_a_complete_declaration_is_clean(tmp_path):
    out = _drift(tmp_path,
                 _pages({"name": "explore", "component": "Explore",
                         "apis_used": ["GET /api/videos/feed", "GET /api/search"]}),
                 {"Explore": [("GET", "/api/videos/feed"), ("GET", "/api/search")]})
    assert out == [], out


def test_a_declaration_the_reader_cannot_confirm_never_fires(tmp_path):
    """★ The hook blind spot. `useCatalog` holds the service imports, the reader returns
    nothing, and a page that DECLARES something must not be called understated for it."""
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "hooks").mkdir()
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(
        "export async function getTitles() { return request('/api/titles'); }\n",
        encoding="utf-8")
    (src / "hooks" / "useCatalog.js").write_text(
        "import { getTitles } from '../services/api';\n"
        "export function useCatalog() { return getTitles(); }\n", encoding="utf-8")
    (src / "pages" / "BrowseHome.jsx").write_text(
        "import { useCatalog } from '../hooks/useCatalog';\n"
        "export default function BrowseHome() { useCatalog(); return null; }\n",
        encoding="utf-8")
    from multi_agent.runtime.deliverability import _page_api_declaration_drift_1202rr as d
    out = d(_Hubs(_pages({"name": "browse_home", "component": "BrowseHome",
                          "apis_used": ["GET /api/titles"]})), str(tmp_path))
    assert out == [], (
        "the reader cannot see through the hook, so this page must stay clean: %r" % out)


def test_an_empty_declaration_still_fires_as_before(tmp_path):
    out = _drift(tmp_path,
                 _pages({"name": "explore", "component": "Explore", "apis_used": []}),
                 {"Explore": [("GET", "/api/videos/feed")]})
    assert out and "/api/videos/feed" in out[0], out


def test_the_parameter_spelling_does_not_create_a_phantom_gap(tmp_path):
    """The reader answers `{}`-normalised and the registry spells the parameter."""
    out = _drift(tmp_path,
                 _pages({"name": "vid", "component": "Vid",
                         "apis_used": ["GET /api/videos/{video_id}"]}),
                 {"Vid": [("GET", "/api/videos/{id}")]})
    assert out == [], "the same endpoint spelled two ways must not read as missing: %r" % out


def test_both_phrasings_route_to_the_same_check(tmp_path):
    """#1202tu: the id comes from the prose by substring, so a reworded blocker
    dispatches nobody."""
    from multi_agent.runtime.delivery_gate import _deliverability_check_token as fn
    old = ("3 registered ui_page(s) declare `apis_used: []` while their own source calls "
           "an API: explore_grid_page (ExploreGridPage.jsx)")
    new = ("3 registered ui_page(s) understate `apis_used` while their own source calls "
           "an API: explore_grid_page (ExploreGridPage.jsx) calls 1 the registry does not "
           "list: GET /api/videos/feed")
    assert fn(old) == "deliverability_page_apis_understated", fn(old)
    assert fn(new) == "deliverability_page_apis_understated", fn(new)


def test_the_gate_still_owns_and_dispatches_the_check():
    """A check that can decline delivery must name an owner (#1202tu)."""
    import multi_agent.runtime.remediation_dispatcher as RD
    src = open(RD.__file__, encoding="utf-8").read()      # #1202eu
    assert "deliverability_page_apis_understated" in src, (
        "the dispatcher no longer knows this check, so it dispatches nobody")
