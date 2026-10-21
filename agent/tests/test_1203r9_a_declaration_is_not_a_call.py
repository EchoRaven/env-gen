"""#1203r9 -- a declaration is not a call, and `{}` is not a literal.

The reference probes in `frontend_audit` expand a declared API template into a regex so one
path param matches any single segment. The param class was `\\{[^}]+\\}` -- at least one
character inside the braces -- while the framework's own canonical shape form for a param is
the EMPTY `{}`. So `{}` never split, the pattern collapsed to an unmatchable literal, and
`declared API ... never referenced in frontend src` fired regardless of the code.

Measured: r46's last lifecycle line carried 8 of 8 such findings, all false -- every one of
those APIs is genuinely called in `services/api.js` with `encodeURIComponent`. Four of its six
pending pages were held on nothing else. Corpus floor: 43 APIs across 11 runs, both products.

The second half is what the first half caused. A bare `'METHOD /path'` literal counted as a
reference, so the check was satisfiable by DECLARING the string -- which is what lanes did,
385 times across 21 runs, in arrays named after the framework's own field. Honestly scoped:
0 of 168 declared APIs are satisfied ONLY by their declaration, so nothing is hidden today.

EVERY TEST HERE DRIVES THE REAL FUNCTIONS. The bug was a character class, and a source-text
assertion about the pattern would have read as coverage while the pattern matched nothing.
"""
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA

# the two spellings a lane actually writes, plus the one #912 was created for
REAL_CALLS = """
export async function getTitle(id) { return (await request(`/api/titles/${encodeURIComponent(id)}`)).item; }
export async function getEpisodes(id) { return (await request(`/api/titles/${encodeURIComponent(id)}/episodes`)).items; }
export async function removeFromMyList(id) { return (await request(`/api/my-list/${encodeURIComponent(id)}`, { method: 'DELETE' })).item; }
export async function getFeed() { return (await request('/api/feed')).items; }
"""

# r46's actual gamed declaration, verbatim in shape
GAMED = """
const TITLE_DETAIL_API_COVERAGE = [
  'GET /api/titles',
  'GET /api/titles/{}',
  'GET /api/titles/{}/episodes',
  'GET /api/my-list',
];
export default function TitleDetailPage() {
  void TITLE_DETAIL_API_COVERAGE;
  return null;
}
"""


def _referenced(api: str, src: str, tmp_path=None) -> bool:
    """Drive the REAL probe: build a page that declares `api`, hand `audit_ui_page` a source
    cache holding `src`, and read its `missing` list.

    DO NOT re-implement the regex here. The first version of this file did exactly that --
    it rebuilt the split and the wildcard join locally and only called the real
    `calls_only_1203r9` -- which is the seventh MISSED shape: a test driving a COPY of the
    rule. The character class was the whole defect, so a local copy of it would have gone on
    passing no matter what production did."""
    page = {"name": "p", "route": "/p", "component": "P",
            "path": "src/pages/P.jsx", "apis_used": ["GET " + api]}
    cache = {"/x/src/services/api.js": src, "/x/src/pages/P.jsx": "export default function P(){return null}"}
    _ok, missing = FA.audit_ui_page(Path("/x/src"), page, _src_cache=cache)
    needle = "declared API `%s` never referenced in frontend src" % api
    return not any(needle == m for m in missing)


# ------------------------------------------------- the false negative (`{}` blindness)
@pytest.mark.parametrize("api", [
    "/api/titles/{}",
    "/api/titles/{}/episodes",
    "/api/my-list/{}",
])
def test_the_shape_form_matches_a_genuine_call(api):
    """`{}` is the framework's OWN spelling; a real call must still be found through it."""
    assert _referenced(api, REAL_CALLS), (
        "%s reported `never referenced` although api.js calls it" % api)


@pytest.mark.parametrize("api", [
    "/api/titles/{id}",
    "/api/titles/{titleId}/episodes",
    "/api/my-list/{id}",
])
def test_the_named_form_still_matches(api):
    """The named spelling worked before and must not regress."""
    assert _referenced(api, REAL_CALLS)


def test_a_paramless_path_still_matches():
    assert _referenced("/api/feed", REAL_CALLS)


def test_an_api_nobody_calls_is_still_reported():
    """THE COUNTER-PROOF. Widening the class must not make the probe answer True always."""
    assert not _referenced("/api/titles/{}/rating", REAL_CALLS)
    assert not _referenced("/api/nonexistent", REAL_CALLS)


# ------------------------------------------------- the false positive (declaration ≠ call)
def test_a_declaration_array_alone_does_not_count_as_a_reference():
    """r46's `TITLE_DETAIL_API_COVERAGE` + `void` satisfied the probe by listing strings."""
    for api in ("/api/titles/{}", "/api/titles/{}/episodes", "/api/my-list", "/api/titles"):
        assert not _referenced(api, GAMED), (
            "%s was satisfied by a declaration literal, with no call anywhere" % api)


def test_the_declaration_does_not_mask_a_real_call_in_the_same_source():
    """Both present -> still referenced. The strip must remove the DECLARATION, not the call."""
    both = GAMED + REAL_CALLS
    assert _referenced("/api/titles/{}", both)
    assert _referenced("/api/titles/{}/episodes", both)
    assert not _referenced("/api/titles/{}/rating", both)


def test_the_strip_leaves_genuine_call_sites_alone():
    """0 of 2048 real call sites in the corpus put the method inside the quoted path, so a
    path-only literal must survive the strip untouched."""
    kept = FA.calls_only_1203r9(REAL_CALLS)
    for frag in ("/api/titles/${encodeURIComponent(id)}", "'/api/feed'", "method: 'DELETE'"):
        assert frag in kept, "the strip ate a genuine call fragment: %s" % frag


def test_the_strip_only_eats_a_method_prefixed_literal():
    src = "const a = 'GET /api/x'; const b = '/api/x'; const c = 'GETTING /api/x';"
    out = FA.calls_only_1203r9(src)
    assert "'GET /api/x'" not in out, "the declaration literal must go"
    assert "'/api/x'" in out, "a plain path literal is not a declaration"
    assert "'GETTING /api/x'" in out, "only the exact HTTP methods, not any word"


# ------------------------------------------------- the #918 site needs its own detector
def _unreachable_918(api: str, page_src: str, tmp_path):
    """Drive the REAL #918 probe (`API UNREACHABLE FROM ITS PAGE`) via sync_ui_page_statuses.

    #1203r9 changed TWO sites, and today's lesson (twice over) is that a patch touching two
    places needs a detector per place: mutation R9B reverts only this one, and nothing in the
    #912 tests above can see it."""
    import tempfile
    from env_generator.llm_generator.multi_agent.runtime import registryhub as R

    reg = R.RegistryHub(tempfile.mkdtemp())
    # NO endpoint registration. `register_endpoint` REFUSES the `{}` form outright
    # ("every {...} must be a NAMED identifier"), while `register_ui_page` accepts it --
    # which is how pages end up carrying a param spelling the contract forbids. #918's
    # `api_unreachable` is computed from the page's own `apis_used` and its closure, with
    # no reference to the contract, so the probe is driven without one.
    reg.register_ui_page("p", route="/p", component="P", apis_used=["GET " + api],
                         path="src/pages/P.jsx", agent="frontend")

    class _H:
        def get_ui_pages(self):
            return reg.list_ui_pages()
        def get_ui_components(self):
            return reg.list_ui_components()
        def update_ui_page(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_page(name, route=d.pop("route", ""),
                                        component=d.pop("component", ""),
                                        apis_used=d.pop("apis_used", None),
                                        components=d.pop("components", None),
                                        path=d.pop("path", ""),
                                        status=d.pop("status", ""), agent=agent, **d)
        def update_ui_component(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_component(name, component=d.pop("component", ""),
                                             apis_used=d.pop("apis_used", None),
                                             status=d.pop("status", ""), agent=agent, **d)

    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text("export default function App(){return null}", encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(page_src, encoding="utf-8")
    out = FA.sync_ui_page_statuses(tmp_path, _H(), reg)
    return "p" in (out.get("api_unreachable") or {})


def test_918_sees_a_real_call_through_the_shape_form(tmp_path):
    """`{}` must expand here too, or a page that genuinely calls its API is reported as an
    island -- the #918 message says NONE of its APIs is reachable."""
    page = ("export default function P(){\n"
            "  fetch(`/api/titles/${encodeURIComponent(id)}/episodes`);\n"
            "  return null;\n}")
    assert not _unreachable_918("/api/titles/{}/episodes", page, tmp_path)


def test_918_still_reports_a_page_that_calls_nothing(tmp_path):
    """THE COUNTER-PROOF for the test above: widening the class must not silence the probe."""
    assert _unreachable_918("/api/titles/{}/episodes",
                            "export default function P(){return null}", tmp_path)


def test_918_is_not_satisfied_by_a_declaration_in_the_page(tmp_path):
    """The gamed array lives IN the page file, so it is inside the page's own closure --
    which makes #918 the site the declaration trick satisfies most easily."""
    page = ("const APIS = ['GET /api/titles/{}/episodes'];\n"
            "export default function P(){ void APIS; return null; }")
    assert _unreachable_918("/api/titles/{}/episodes", page, tmp_path)


# ================================================================= sites 3 and 4: the HARD gate
# `_contract_misses` sets `ok = False` outright, so a page declaring a shape-formed api could
# never reach `implemented`. r46 carried 8 such findings and every distinct api in them was
# shape-formed, all three present in its contract under named params.
_CONTRACT = {("GET", "/api/titles/*/episodes"), ("GET", "/api/titles/*"),
             ("DELETE", "/api/my-list/*"), ("GET", "/api/feed")}


@pytest.mark.parametrize("api", [
    "GET /api/titles/{}/episodes",
    "GET /api/titles/{}",
    "DELETE /api/my-list/{}",
])
def test_a_shape_formed_api_matches_the_named_contract(api):
    """r46's three, verbatim. Each is IN its contract and each was reported missing."""
    assert FA._api_registered(api, _CONTRACT), (
        "%s reported NOT in the contract, which sets ok=False and blocks the page" % api)


@pytest.mark.parametrize("api", [
    "GET /api/titles/{titleId}/episodes",
    "DELETE /api/my-list/{listId}",
    "GET /api/feed",
])
def test_the_named_and_paramless_forms_still_match(api):
    assert FA._api_registered(api, _CONTRACT)


@pytest.mark.parametrize("api", [
    "GET /api/nope/{}",
    "POST /api/titles/{}/episodes",   # right path, WRONG METHOD
    "GET /api/titles/{}/rating",
])
def test_an_api_outside_the_contract_is_still_reported(api):
    """THE COUNTER-PROOF. Normalising `{}` must not turn this check into a rubber stamp --
    and the method must keep mattering, which a path-only comparison would lose."""
    assert not FA._api_registered(api, _CONTRACT)


def test_registered_paths_normalises_the_endpoint_side():
    """Site 3. `register_endpoint` refuses `{}`, so this side is always named today and the
    change is a no-op -- asserted anyway so the two halves of one comparison cannot drift
    apart, which is exactly how the mismatch arose."""
    class _Reg:
        def get_endpoints(self):
            return {
                "GET /api/titles/{titleId}": {"method": "GET", "path": "/api/titles/{titleId}"},
                "GET /api/x/{}": {"method": "GET", "path": "/api/x/{}"},
                "GET /api/old": {"method": "GET", "path": "/api/old", "status": "deprecated"},
            }
    got = FA._registered_paths(_Reg())
    assert ("GET", "/api/titles/*") in got, "a named param must normalise to *"
    assert ("GET", "/api/x/*") in got, "and so must the empty form, if one ever arrives"
    assert ("GET", "/api/old") not in got, "#231: a deprecated endpoint is not the contract"


def test_the_contract_miss_finding_is_gone_end_to_end(tmp_path):
    """Drive `sync_ui_page_statuses`, where `_contract_misses` actually lives.

    The first draft of this test rebuilt that closure's logic locally -- calling
    `_api_registered` itself and formatting the message by hand -- which is the copy-of-the-
    rule trap for the second time in this file. A local copy would keep agreeing with itself
    no matter what `_contract_misses` did. The closure is not importable, so the only honest
    way in is through the function that owns it, reading the per-page reason list #1203n1
    added."""
    import tempfile
    from env_generator.llm_generator.multi_agent.runtime import registryhub as R

    reg = R.RegistryHub(tempfile.mkdtemp())
    reg.register_endpoint("GET", "/api/titles/{titleId}/episodes", schema={"request": {}},
                          provider="backend", agent="backend", status="implemented")
    reg.register_ui_page("t", route="/t", component="T", path="src/pages/T.jsx",
                         apis_used=["GET /api/titles/{}/episodes"], agent="frontend")

    class _H:
        def get_ui_pages(self):
            return reg.list_ui_pages()
        def get_ui_components(self):
            return reg.list_ui_components()
        def update_ui_page(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_page(name, route=d.pop("route", ""),
                                        component=d.pop("component", ""),
                                        apis_used=d.pop("apis_used", None),
                                        components=d.pop("components", None),
                                        path=d.pop("path", ""),
                                        status=d.pop("status", ""), agent=agent, **d)
        def update_ui_component(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_component(name, component=d.pop("component", ""),
                                             apis_used=d.pop("apis_used", None),
                                             status=d.pop("status", ""), agent=agent, **d)

    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text(
        "import T from './pages/T'\nexport default function App(){return <Route path='/t' element={<T/>}/>}",
        encoding="utf-8")
    (src / "pages" / "T.jsx").write_text(
        "export default function T(){ fetch(`/api/titles/${encodeURIComponent(i)}/episodes`); return null; }",
        encoding="utf-8")

    out = FA.sync_ui_page_statuses(tmp_path, _H(), reg)
    reasons = (out.get("pending") or {}).get("t") or []
    bad = [r for r in reasons if "is NOT in the registered contract" in r]
    assert not bad, "the contract miss survived end to end: %s" % bad


def test_the_contract_miss_still_fires_for_an_api_nobody_registered(tmp_path):
    """COUNTER-PROOF for the test above: if the endpoint is absent from the contract, the
    finding must still appear -- otherwise the test above passes because the check is dead."""
    import tempfile
    from env_generator.llm_generator.multi_agent.runtime import registryhub as R

    reg = R.RegistryHub(tempfile.mkdtemp())
    reg.register_endpoint("GET", "/api/unrelated", schema={"request": {}},
                          provider="backend", agent="backend", status="implemented")
    reg.register_ui_page("t", route="/t", component="T", path="src/pages/T.jsx",
                         apis_used=["GET /api/titles/{}/episodes"], agent="frontend")

    class _H:
        def get_ui_pages(self):
            return reg.list_ui_pages()
        def get_ui_components(self):
            return reg.list_ui_components()
        def update_ui_page(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_page(name, route=d.pop("route", ""),
                                        component=d.pop("component", ""),
                                        apis_used=d.pop("apis_used", None),
                                        components=d.pop("components", None),
                                        path=d.pop("path", ""),
                                        status=d.pop("status", ""), agent=agent, **d)
        def update_ui_component(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_component(name, component=d.pop("component", ""),
                                             apis_used=d.pop("apis_used", None),
                                             status=d.pop("status", ""), agent=agent, **d)

    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text("export default function App(){return null}", encoding="utf-8")
    (src / "pages" / "T.jsx").write_text("export default function T(){return null}", encoding="utf-8")

    out = FA.sync_ui_page_statuses(tmp_path, _H(), reg)
    reasons = (out.get("pending") or {}).get("t") or []
    assert any("is NOT in the registered contract" in r for r in reasons), (
        "the contract check is DEAD in this fixture, so the sibling test proves nothing: %s"
        % reasons)
