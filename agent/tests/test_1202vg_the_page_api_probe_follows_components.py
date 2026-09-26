"""#1202vg — the page API reachability probe asked nothing of a composing page.

`audit_ui_page` checked "can this page reach the APIs it declares" against `apis_used`
on the PAGE. The frontend prompt tells the lane to declare each API on the component
where the call lives, so a composing page declares none and the probe asks nothing:
tiktok-r133 flipped all 17 of its pages to `implemented` with this criterion vacuous.

Measured across 155 runs before shipping: 2688 pages unchanged, 2 newly caught (both
r124, on `PATCH /api/me/profile` — registered, declared by `profile_header`, and absent
from the entire frontend source), and 0 loosened.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    audit_ui_page,
    _effective_page_apis_1202vg as effective,
    _ui_components_1202vg as read_components,
)

_SRC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/frontend_audit.py")


def _project(tmp_path, files):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    for rel, body in files.items():
        (src / rel).write_text(body)
    (src / "App.jsx").write_text(
        "import FeedPage from './pages/FeedPage';\n"
        "export default function App(){return <Routes>"
        "<Route path='/' element={<FeedPage/>}/></Routes>;}\n")
    return src


_PAGE = {"route": "/", "component": "FeedPage", "apis_used": [],
         "components": ["FeedProvider"]}
_COMPONENTS = {"feed_provider": {"component": "FeedProvider",
                                 "apis_used": ["GET /api/feed"]}}


def _files(provider_body):
    return {
        "pages/FeedPage.jsx": ("import FeedProvider from '../components/FeedProvider';\n"
                               "export default function FeedPage(){return <FeedProvider/>;}\n"),
        "components/FeedProvider.jsx": provider_body,
    }


def test_the_probe_is_vacuous_without_the_component_registry(tmp_path):
    """The pre-#1202vg behaviour, stated so the change is visible: a page declaring
    nothing is asked nothing, even when its component's endpoint is nowhere in the app."""
    src = _project(tmp_path, _files("export default function FeedProvider(){return <div/>;}\n"))
    ok, missing = audit_ui_page(src, _PAGE)
    assert not [m for m in missing if "declared API" in m]


def test_an_endpoint_reached_through_a_component_is_now_checked(tmp_path):
    """Same app, same page, with the registry: the unreferenced endpoint is caught."""
    src = _project(tmp_path, _files("export default function FeedProvider(){return <div/>;}\n"))
    ok, missing = audit_ui_page(src, _PAGE, components=_COMPONENTS)
    assert [m for m in missing if "/api/feed" in m and "never referenced" in m]


def test_a_component_that_really_calls_it_passes(tmp_path):
    """The probe must follow the page's file closure, which already includes the files it
    imports — the call lives in the COMPONENT, not the page."""
    src = _project(tmp_path, _files(
        "export default function FeedProvider(){\n"
        "  fetch(`/api/feed`);\n  return <div/>;\n}\n"))
    ok, missing = audit_ui_page(src, _PAGE, components=_COMPONENTS)
    assert not [m for m in missing if "/api/feed" in m]


def test_an_inherited_auth_endpoint_is_excluded(tmp_path):
    """A shared auth control is rendered by every page, so ONE over-declaration there
    would charge all of them. Across 155 runs, 70 of ~80 newly-unreachable inherited
    declarations were `/auth/session|signout|signup|logout|me` from one component per run,
    and `audit_ui_component` already owns that finding (#1032: not two lanes, one cause)."""
    comps = {"account_menu": {"component": "FeedProvider",
                              "apis_used": ["GET /auth/session", "POST /auth/signout"]}}
    src = _project(tmp_path, _files("export default function FeedProvider(){return <div/>;}\n"))
    ok, missing = audit_ui_page(src, _PAGE, components=comps)
    assert not [m for m in missing if "declared API" in m]


def test_the_page_s_OWN_auth_declaration_is_still_checked(tmp_path):
    """The exclusion covers what a page INHERITS, never what it declared itself.
    Filtering both would have flipped 10 pages across 6 runs from correctly-failing to
    passing — the first draft did exactly that and the corpus measurement caught it."""
    page = {**_PAGE, "apis_used": ["GET /auth/session"]}
    src = _project(tmp_path, _files("export default function FeedProvider(){return <div/>;}\n"))
    ok, missing = audit_ui_page(src, page, components=_COMPONENTS)
    assert [m for m in missing if "/auth/session" in m and "never referenced" in m]


def test_the_effective_set_keeps_own_declarations_unfiltered():
    page = {"apis_used": ["GET /auth/me", "GET /api/x"], "components": ["C"]}
    comps = {"c": {"component": "C", "apis_used": ["POST /auth/logout", "GET /api/y"]}}
    assert effective(page, comps) == {"GET /auth/me", "GET /api/x", "GET /api/y"}


def test_the_stub_criteria_still_read_only_what_the_page_declared():
    """`apis` feeds `_declared_but_inert` and the #1077 branch, which read `bool(apis)` as
    'this page claims to fetch something ITSELF'. Feeding the effective set into those
    flipped 18 pages for reasons that had nothing to do with an unreachable API, so the
    probe gets its own list. Anchored to the landmarks, never a byte window (#943)."""
    src = _SRC.read_text()
    body = src[src.index("def audit_ui_page("):src.index("def _route_matchers(")]
    assert "for api in reach_apis:" in body
    inert = body[body.index("_declared_but_inert = "):]
    inert = inert[:inert.index("\n")]
    assert "bool(apis)" in inert and "reach_apis" not in inert


def test_an_unreadable_component_registry_falls_back_and_says_so(caplog):
    """#883: `{}` here is the pre-#1202vg behaviour exactly — neither fail-open nor
    fail-closed — but a reader must tell 'its components declared nothing' from 'the
    registry could not be read'."""
    import logging

    class _Boom:
        def get_ui_components(self):
            raise RuntimeError("hub down")

    with caplog.at_level(logging.WARNING):
        assert read_components(_Boom()) == {}
    assert "#1202vg" in " ".join(r.getMessage() for r in caplog.records)


def test_a_workhub_without_the_accessor_is_not_an_error():
    assert read_components(object()) == {}
