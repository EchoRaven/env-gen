r"""#1199: a ui_page's `apis_used` is reconciled with the code that shipped.

The declaration is written once, at registration, and nothing ever checks it against what the
page calls — while 84 call sites read it (delivery gates, the projector's
`_all_get_endpoints`, the #627/#629 consumer index). Measured on r26 and hand-verified by
reading the delivered files:

    my_list_page             declares GET /api/titles     ships getMyList() -> /api/my-list
    card_hover_preview_page  declares GET /api/profiles   ships fetch('/api/titles')

#728 warns about the first 478 times in one run and nothing acts on it. Its own words name the
damage: *"code and declaration agree, so the consistency audits pass on the wrong thing"* —
except here they do not even agree.

Which side is ground truth is not fixed (in r26 the code was right and the declaration stale;
#728's warning assumes the opposite), and reconciling toward the CODE is right either way: a
stale declaration is corrected, and a page that really is calling another page's endpoint now
says so where the route-word audit can catch it deliberately instead of by accident.

★ The resolver had to be measured against real files, and its first version was wrong in a way
that would have CORRUPTED the registry — it reported search_page as using /api/my-list and
top10_page as using /api/genres. Two faults compounded:

  * endpoints written as template literals — `` request(`/api/titles?${qs}`) `` — were skipped
    by a quote-only pattern, so a helper contributed nothing of its own; and
  * the body was read as a fixed 600-char window (the thing #943 bans), which then ran past a
    one-line helper into the NEXT export and picked up ITS endpoint.

Together they shifted the whole helper map by one function. After the fix, the dry run over
three runs reports 3 drifts in r26 — including both hand-verified pages — and 0 in r22/r23.

Never wipes: a page whose endpoints cannot be resolved keeps its declaration exactly.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402


_API_MODULE = """
export async function getTitles(params = {}) { const qs = new URLSearchParams(params).toString();
  return (await request(`/api/titles?${qs}`)).items; }
export async function getTop10Titles(params = {}) { return (await request('/api/titles/top10')).items; }
export async function getGenres() { return (await request('/api/genres')).items || []; }
export async function searchTitles(q) { return (await request(`/api/search?q=${q}`)).items; }
export async function getMyList() { return (await request('/api/my-list')).items; }
"""


def _tree(tmp_path, page_src, *, component_src=None):
    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "services" / "api.js").write_text(_API_MODULE, encoding="utf-8")
    if component_src is not None:
        (src / "components" / "ListPanel.jsx").write_text(component_src, encoding="utf-8")
    (src / "pages" / "MyListPage.jsx").write_text(page_src, encoding="utf-8")
    return tmp_path / "app" / "frontend"


class _Hub:
    def __init__(self):
        self.calls = []

    def register_ui_page(self, **kw):
        self.calls.append(kw)


def _page(apis):
    return {"name": "my_list_page", "route": "/browse/my-list",
            "path": "app/frontend/src/pages/MyListPage.jsx", "apis_used": list(apis)}


# ------------------------------------------------------------------ the helper map

def test_a_template_literal_endpoint_is_resolved_to_its_own_helper(tmp_path):
    """Both original faults, pinned: backticks, and a body that stops at the next export."""
    fe = _tree(tmp_path, "export default function MyListPage(){ return null; }")
    m = fs._api_helper_map_1199(fe / "src")
    assert m["getTitles"] == "/api/titles"          # template literal, not the next export's
    assert m["searchTitles"] == "/api/search"       # was /api/my-list before the fix
    assert m["getTop10Titles"] == "/api/titles/top10"   # was /api/genres
    assert m["getMyList"] == "/api/my-list"


# ------------------------------------------------------------------- reconciliation

def test_a_stale_declaration_is_reported_and_NOT_rewritten(tmp_path):
    """r26's my_list_page: declared /api/titles, ships getMyList().

    ★ This asserted a REWRITE until the corpus was measured. Across all 114 generated
    frontends the write-back degraded declarations more often than it corrected them
    (tiktok /api/comments/:id/like -> /api/comments; googlemaps /api/places/:id ->
    /api/places; instagram /api/users/:id/follow -> /api/explore), and three successive
    guards cut the false rewrites from 34 environments to 21 without reaching zero.
    `apis_used` has 84 readers; it is not a field to write from a static reading I cannot
    verify page by page. The disagreement is reported instead."""
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); return null; }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], hub)
    assert [r["page"] for r in rep["reconciled"]] == ["my_list_page"]
    assert rep["reconciled"][0]["was"] == ["/api/titles"]
    assert rep["reconciled"][0]["now"] == ["/api/my-list"]
    assert hub.calls == []           # nothing written


def test_evidence_only_in_a_shared_component_does_NOT_reconcile(tmp_path):
    """★ This test asserted the OPPOSITE until the corpus said otherwise.

    It was written from #1197's login shape — a page that delegates entirely, evidence one hop
    away — and that shape is real. But it is not evidence about THIS page's endpoints, because
    the components a page imports are mostly SHARED chrome, and chrome contributes its calls to
    every page that mounts it.

    Measured across all 114 generated frontends: instagram's `profile` declares
    /api/users/:id/follow and /api/users/:id/unfollow, its own calls are parameterised (so they
    resolve to nothing), and the only endpoint reachable from it was `/api/explore` — its nav's.
    Reconciling would have replaced a precise, correct declaration with an unrelated one. The
    rule is now: the page's OWN file must contribute at least one resolved endpoint, or the
    page is not measured at all and keeps what it declares.
    """
    fe = _tree(tmp_path, "import ListPanel from '../components/ListPanel.jsx';\n"
                         "export default function MyListPage(){ return <ListPanel/>; }",
               component_src="import { getMyList } from '../services/api';\n"
                             "export default function ListPanel(){ getMyList(); return null; }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], hub)
    assert rep["reconciled"] == []
    assert hub.calls == []


def test_a_generalisation_of_the_declaration_is_not_drift(tmp_path):
    """A page declaring /api/places/:id whose resolvable call is /api/places is the same
    endpoint seen without its parameter — googlemaps' `place_detail`, which would otherwise
    have been rewritten to the collection."""
    fe = _tree(tmp_path, "export default function MyListPage(){ fetch('/api/titles'); }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles/{id}"])], hub)
    assert rep["reconciled"] == []


def test_a_declaration_the_code_agrees_with_is_left_alone(tmp_path):
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); return null; }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/my-list"])], hub)
    assert rep["reconciled"] == []
    assert hub.calls == []


# --------------------------------------------------------------- never wipes anything

def test_a_page_whose_endpoints_cannot_be_resolved_keeps_its_declaration(tmp_path):
    """The one way this could do harm: an inference miss erasing a correct declaration."""
    fe = _tree(tmp_path, "export default function MyListPage(){ return <div/>; }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], hub)
    assert rep["reconciled"] == []
    assert hub.calls == []


def test_a_bare_prefix_is_not_an_endpoint(tmp_path):
    """`${API}/titles` leaves a bare `/api` behind; treating it as an endpoint would make
    every such page disagree with its declaration."""
    fe = _tree(tmp_path, "const API='/api';\n"
                         "export default function MyListPage(){ fetch(API + '/titles'); }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], hub)
    assert rep["reconciled"] == []


def test_a_page_with_no_declaration_is_not_given_one(tmp_path):
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page([])], hub)
    assert rep["reconciled"] == []
    assert hub.calls == []


def test_a_hub_that_raises_cannot_break_the_scaffold(tmp_path):
    """It no longer writes, so a hostile hub is never called — and must still not raise."""
    class _Angry:
        def register_ui_page(self, **kw):
            raise RuntimeError("hub down")

    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); }")
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], _Angry())
    assert [r["page"] for r in rep["reconciled"]] == ["my_list_page"]


# --------------------------------------- #1199b: the write must not land on another page

def test_a_route_less_page_is_never_reconciled(tmp_path):
    """#1195 merges a route-less `register_ui_page(name, route="", path=X)` into whatever
    other record already holds path X. Writing a reconciliation through that door lands THIS
    page's endpoints on ANOTHER page's record — corrupting the field this fix exists to
    correct. Verified against the real hub before guarding: a_page(/a) and b_page("") sharing
    Shared.jsx, reconciling b_page rewrote a_page's apis_used to b_page's endpoints.
    """
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); return null; }")
    hub = _Hub()
    page = _page(["GET /api/titles"])
    page["route"] = ""            # the shape #1195 folds by path
    rep = fs.reconcile_ui_page_apis_1199(fe, [page], hub)
    assert rep["reconciled"] == []
    assert hub.calls == []


def test_a_routed_page_is_still_reconciled(tmp_path):
    """The guard must not swallow the ordinary case it was added around."""
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); return null; }")
    hub = _Hub()
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], hub)
    assert [r["page"] for r in rep["reconciled"]] == ["my_list_page"]


def test_a_lane_reregistration_cannot_start_an_oscillation(tmp_path):
    """The failure #1197 spent a day on, in a different place: two writers fighting over one
    record forever.

    Lanes DO re-register pages — 20 of 35 in r26, `login` eight times, and all three drifting
    pages 2-3 times each. If a re-registration re-declared the stale endpoints, the framework
    would reconcile, the lane would revert, and the value would depend on who wrote last (a
    gate reading it mid-flight would see either).

    It does not, for two reasons that this test pins because both could change silently:
    the lane's re-registrations carry no `apis_used` at all, and `register_ui_page` PRESERVES
    omitted fields rather than blanking them.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "env_generator" / "llm_generator"))
    from multi_agent.runtime.registryhub import RegistryHub

    hub = RegistryHub(tmp_path / "hubs")
    hub.register_ui_page(name="p", route="/p", path="src/pages/P.jsx",
                         apis_used=["GET /api/x"], components=["C"], actor="lane")
    # the framework reconciles to what the code reaches
    hub.register_ui_page(name="p", route="/p", path="src/pages/P.jsx",
                         apis_used=["GET /api/my-list"], components=["C"],
                         actor="framework:1199")
    # the lane re-registers the way it actually does: without apis_used
    hub.register_ui_page(name="p", route="/p", path="src/pages/P.jsx", actor="lane")

    assert hub.list_ui_pages()["p"]["apis_used"] == ["GET /api/my-list"]
    assert hub.list_ui_pages()["p"]["components"] == ["C"]


def test_a_registered_path_that_resolves_to_nothing_is_reported(tmp_path, caplog):
    """#1202g: a `path` pointing at no file makes every path-based check skip that page in
    silence — this reporter, the staleness guard, the audits.

    Measured across all 114 generated environments: 4 carry such records, and instagram run51
    carries 13 of them, `login` and `home_feed` among them. Its app is fine — the routes are
    mounted and the files ship as `HomeFeedPage.jsx` — but the lane registered
    `frontend/src/pages/home_feed.jsx`: no `app/` prefix, snake_case name. Nothing validates a
    path at registration, so the record points nowhere and every reader quietly agrees.
    """
    import logging

    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); }")
    ghost = dict(_page(["GET /api/titles"]),
                 name="home_feed", path="frontend/src/pages/home_feed.jsx")
    with caplog.at_level(logging.WARNING, logger=fs.__name__):
        rep = fs.reconcile_ui_page_apis_1199(fe, [ghost], _Hub())
    assert rep.get("unresolved_paths") == ["home_feed"]
    assert "#1202g" in caplog.text
    assert "home_feed" in caplog.text


def test_a_resolvable_path_is_not_reported_as_unresolved(tmp_path):
    fe = _tree(tmp_path, "import { getMyList } from '../services/api';\n"
                         "export default function MyListPage(){ getMyList(); }")
    rep = fs.reconcile_ui_page_apis_1199(fe, [_page(["GET /api/titles"])], _Hub())
    assert not rep.get("unresolved_paths")
