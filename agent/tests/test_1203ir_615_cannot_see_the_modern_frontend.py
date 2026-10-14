r"""#1203ir: #615's detector cannot see the frontend the framework projects today.

`duplicate_route_content_groups` groups routes by the `'/api/...'` STRING LITERALS in each
page's source. The projected frontend routes every call through `services/api.js` named
exports, so the literals live in the service and not in the page.

Measured over the 205 runs with a `pages/` tree on this machine: 143 (70%) have NOT ONE page
containing an /api/ literal. Of the last 14 tiktok runs, 12 are at zero and the other two
have a single such page — one page can never reach the two routes a group needs. r185
DELIVERED `/discover` -> DiscoverPage -> `return <LiveDiscoverPage />` beside `/live` ->
LiveDiscoverPage, two nav destinations with one rendering, and the detector was silent.

These tests PIN THE BLINDNESS so it cannot be believed away: the fixtures copy the shape of
r185's own pages (`import { getFeed } from '../services/api.js'`, then `getFeed({limit:6})`).
When someone repairs the detector, `test_the_modern_shape_is_still_invisible` turns red —
which is the point. It is the one place that then has to be read, and it names what the
repair has to get right: #615's predicate is SET EQUALITY, and a PARTIAL resolution makes
unrelated pages match (projected over the corpus: r173 groups LoginPage with ExploreGrid on
`/api/me`, r170 groups LoginPage with Settings on `/api/auth/me` — session endpoints every
page calls, 126 such groups across 70 runs).
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _PAGE_FETCH_RE_615,
    duplicate_route_content_groups,
)

# r185/app/frontend/src/pages/LiveDiscoverPage.jsx, reduced to its API shape.
MODERN = """import TikTokUI from '../components/TikTokUI.jsx';
import { getFeed } from '../services/api.js';
export default function %sPage(){
  const [feed,setFeed]=useState([]);
  useEffect(()=>{getFeed({limit:6}).then(r=>setFeed(r.items||[]))},[]);
  return <TikTokUI>{feed.length}</TikTokUI>;
}
"""

# The older shape #615 was written against (r146-era), for contrast.
LITERAL = """export default function %sPage(){
  const [x,setX]=useState([]);
  useEffect(()=>{fetch('/api/titles').then(r=>r.json()).then(setX)},[]);
  return <div>{x.length}</div>;
}
"""


# The service the modern pages import from. A real app always has one — without it in the
# fixture, a mutation that teaches the detector to read `services/api.js` changes nothing and
# `test_the_modern_shape_is_still_invisible` cannot tell that the blindness was repaired. The
# first version of this file omitted it and that mutation survived.
SERVICE = """const api = {get:(u,q)=>fetch(u).then(r=>r.json())};
export const getFeed = (q) => api.get('/api/videos/feed', q);
export const getComments = (id) => api.get(`/api/videos/${id}/comments`);
"""


def _tree(tmp_path, shape, names, service=True):
    pages = tmp_path / "src" / "pages"
    pages.mkdir(parents=True)
    for n in names:
        (pages / ("%sPage.jsx" % n)).write_text(shape % n)
    if service:
        svc = tmp_path / "src" / "services"
        svc.mkdir(parents=True, exist_ok=True)
        (svc / "api.js").write_text(SERVICE)
    return [{"component": "%sPage" % n, "route": "/%s" % n.lower()} for n in names]


def test_the_older_literal_shape_is_what_the_detector_can_see(tmp_path):
    """The positive control: without it, a green test below could mean a broken fixture."""
    pages = _tree(tmp_path, LITERAL, ["Browse", "Games"])
    groups = duplicate_route_content_groups(tmp_path, pages)
    assert len(groups) == 1, groups
    assert sorted(groups[0]["routes"]) == ["/browse", "/games"]
    assert groups[0]["endpoints"] == ["/api/titles"]


def test_the_modern_shape_is_still_invisible(tmp_path):
    """Two routes, one rendering, and the detector returns nothing.

    RED means someone taught it the named-export shape. Read this module's docstring before
    accepting that: a PARTIAL resolution is worse than none for a set-equality predicate.
    """
    pages = _tree(tmp_path, MODERN, ["Live", "Discover"])
    assert duplicate_route_content_groups(tmp_path, pages) == []


def test_the_page_regex_is_what_misses_it():
    """Names the mechanism, so the next reader does not have to find it again."""
    assert not _PAGE_FETCH_RE_615.findall(MODERN % "Live")
    assert _PAGE_FETCH_RE_615.findall(LITERAL % "Browse")


def test_the_service_module_is_where_the_literal_went():
    """The literal is not gone from the app — it moved out of the page, into the file the
    fixture tree also writes, so the detector's miss is a choice of WHERE it looks."""
    assert "/api/videos/feed" in [e for e, _ in _PAGE_FETCH_RE_615.findall(SERVICE)]
    assert not _PAGE_FETCH_RE_615.findall(MODERN % "Live")


def test_the_fixture_really_contains_the_service_the_pages_import(tmp_path):
    """Guards the test above from the bug its own first version had: with no api.js in the
    tree, a repair of the detector would leave every assertion here green."""
    _tree(tmp_path, MODERN, ["Live", "Discover"])
    svc = tmp_path / "src" / "services" / "api.js"
    assert svc.is_file()
    assert "getFeed" in svc.read_text()
    assert "services/api.js" in (MODERN % "Live")


def test_the_measurement_and_the_refusal_are_recorded_at_the_call_site():
    """The call site is where a reader decides whether to trust the detector."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import deliverability
    flat = " ".join(inspect.getsource(deliverability).replace("#", " ").split())
    assert "143 of them (70%)" in flat
    assert "SET EQUALITY" in flat
    assert "worse than none" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
