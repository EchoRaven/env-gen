"""#1202vf — the gate told a lane to do the thing its own prompt forbids.

The frontend prompt's UI MODEL: "a component OWNS the API calls it makes (apis_used) ...
Declare each API on the component where the call actually lives — don't pile every API
onto the page."  `_no_page_declares_an_api_1202rm` read ui_pages only, so a lane that
followed that exactly was told: "Declare, on each page, the endpoints it actually calls."

tiktok-r133 is that run: 17 pages, every one `apis_used: []` and every one listing its
components, 3 of which carry the APIs. It sat in 211 of its 268 gate snapshots.
"""
import pathlib
from types import SimpleNamespace

import pytest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _component_key_1202vf as key,
    effective_page_apis_1202vf as effective,
    _no_page_declares_an_api_1202rm as check,
)

# r133's real registrations, trimmed to what the check reads.
_R133_COMPONENTS = {
    "feed_data_provider": {"id": "component:ui:feed_data_provider",
                           "component": "FeedDataProvider",
                           "apis_used": ["GET /api/feed"]},
    "comments_panel": {"id": "component:ui:comments_panel", "component": "CommentsPanel",
                       "apis_used": ["GET /api/videos/{id}/comments"]},
    "tiktok_shell": {"id": "component:ui:tiktok_shell", "component": "TikTokShell",
                     "apis_used": [], "children": ["LeftSidebar"]},
    "left_sidebar": {"id": "component:ui:left_sidebar", "component": "LeftSidebar",
                     "apis_used": []},
}
_R133_PAGE = {"route": "/", "component": "FypFeedLoggedOut", "apis_used": [],
              "components": ["TikTokShell", "LeftSidebar", "FeedDataProvider", "VideoCard"]}


def _hubs(pages, components, endpoints):
    eps = {f"{m} {p}": {"method": m, "path": p} for m, p in endpoints}
    return SimpleNamespace(registryhub=SimpleNamespace(
        list_ui_pages=lambda: dict(pages),
        list_ui_components=lambda: dict(components),
        get_endpoints=lambda: eps))


_BUSINESS = [("GET", "/api/feed"), ("GET", "/api/videos/{id}/comments"),
             ("POST", "/api/videos")]


@pytest.mark.parametrize("spelling", [
    "feed_data_provider", "FeedDataProvider", "component:ui:feed_data_provider",
    "feed-data-provider", "  FeedDataProvider  ",
])
def test_one_component_is_reachable_by_all_the_names_it_carries(spelling):
    """r133 registers it under a hub key, an id and a code name, and its pages reference
    the code name. Matching any single spelling misses."""
    assert key(spelling) == key("feed_data_provider")


def test_a_composing_page_consumes_what_its_components_declare():
    assert effective(_R133_PAGE, _R133_COMPONENTS) == {"GET /api/feed"}


def test_the_walk_follows_children_transitively():
    comps = dict(_R133_COMPONENTS)
    comps["left_sidebar"] = {**comps["left_sidebar"], "children": ["CommentsPanel"]}
    assert "GET /api/videos/{id}/comments" in effective(_R133_PAGE, comps)


def test_a_cycle_in_the_component_tree_terminates():
    comps = {"a": {"component": "A", "children": ["B"], "apis_used": ["GET /api/a"]},
             "b": {"component": "B", "children": ["A"], "apis_used": ["GET /api/b"]}}
    assert effective({"components": ["A"]}, comps) == {"GET /api/a", "GET /api/b"}


def test_an_unregistered_component_reference_is_ignored_not_fatal():
    """r133's pages name `VideoCard`, which that run never registered as a component."""
    assert effective({"components": ["VideoCard"]}, _R133_COMPONENTS) == set()


def test_r133_is_not_blocked():
    """The whole point. Every page declares nothing; the APIs are on the components."""
    assert check(_hubs({"fyp_feed_logged_out": _R133_PAGE}, _R133_COMPONENTS, _BUSINESS)) == []


def test_a_lane_that_declared_nowhere_is_still_blocked():
    """r130 (0 of 14 pages, 0 of 7 components) and r131 (0/13, 0/1). #1202vf yields to the
    prompt's model; it does not retire the check."""
    bare = {k: {**v, "apis_used": []} for k, v in _R133_COMPONENTS.items()}
    out = check(_hubs({"p1": _R133_PAGE, "p2": dict(_R133_PAGE)}, bare, _BUSINESS))
    assert out and "apis_used: []` while the contract" in out[0]


def test_a_page_declaring_its_own_api_short_circuits_as_before():
    out = check(_hubs({"p1": {**_R133_PAGE, "apis_used": ["GET /api/feed"]}},
                      _R133_COMPONENTS, _BUSINESS))
    assert out == []


def test_a_registry_with_no_components_hub_still_blocks():
    """The component lookup is optional machinery; its absence must not silently pass."""
    rh = SimpleNamespace(
        list_ui_pages=lambda: {"p1": _R133_PAGE, "p2": dict(_R133_PAGE)},
        get_endpoints=lambda: {f"{m} {p}": {"method": m, "path": p} for m, p in _BUSINESS})
    out = check(SimpleNamespace(registryhub=rh))
    assert out and "apis_used: []" in out[0]


def test_not_blocking_is_announced_and_says_the_readers_are_still_blind(caplog):
    """#1154's rule: a correct decision nobody can audit is the #691/#790 mistake. And the
    note must say the page-level readers still do not walk the tree -- r133 flipped all 17
    pages to `implemented` with that criterion vacuous."""
    import logging
    with caplog.at_level(logging.WARNING):
        assert check(_hubs({"fyp_feed_logged_out": _R133_PAGE},
                           _R133_COMPONENTS, _BUSINESS)) == []
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "#1202vf" in text
    assert "fyp_feed_logged_out" in text
    assert "vacuous" in text


def test_the_prompt_rule_this_yields_to_is_still_in_the_prompt():
    """If the UI MODEL ever changes to put APIs on pages, this yielding is wrong and the
    check should go back to reading pages alone. Anchored, not a byte window (#943)."""
    j2 = (pathlib.Path(__file__).resolve().parents[1]
          / "env_generator/llm_generator/multi_agent/prompts/v4/frontend_agent.j2").read_text()
    block = j2[j2.index("UI MODEL: pages COMPOSE components"):
               j2.index("ARCHITECTURE CONTRACT")]
    assert "a component OWNS the API calls it makes" in block
    assert "don't pile every API onto the page" in block


def test_a_hub_key_that_is_not_the_code_name_still_resolves():
    """The case that makes indexing the `component` field load-bearing, and the reason the
    first draft of the spelling test above proved nothing: r133 registers the shell under
    the hub key `tiktok_shell` while its pages reference `TikTokShell`, and the two do NOT
    normalise to the same string (`tiktok_shell` vs `tik_tok_shell`) -- where the word
    boundary falls is not recoverable from either spelling alone. Only the record's own
    `component` field bridges them.
    """
    assert key("tiktok_shell") != key("TikTokShell")      # the premise, stated
    comps = {"tiktok_shell": {"id": "component:ui:tiktok_shell", "component": "TikTokShell",
                              "apis_used": ["GET /api/session"]}}
    assert effective({"components": ["TikTokShell"]}, comps) == {"GET /api/session"}


def test_a_component_walk_that_could_not_run_is_announced_not_silent():
    """#883. With no components read, no page has effective APIs and the blocker below
    still fires — fail-closed, which is the safe direction. But "this lane declared
    nowhere" and "the component walk could not run" are different findings and only the
    first is lane work, so the swallow announces itself."""
    from types import SimpleNamespace as NS
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dl

    def _boom():
        raise RuntimeError("hub unavailable")

    rh = NS(list_ui_pages=lambda: {"p1": _R133_PAGE, "p2": dict(_R133_PAGE)},
            list_ui_components=_boom,
            get_endpoints=lambda: {f"{m} {p}": {"method": m, "path": p} for m, p in _BUSINESS})
    seen = []
    orig = dl._gate_absent_792
    dl._gate_absent_792 = lambda where, exc, default: seen.append((where, str(exc)))
    try:
        out = dl._no_page_declares_an_api_1202rm(NS(registryhub=rh))
    finally:
        dl._gate_absent_792 = orig
    assert out and "apis_used: []" in out[0]        # fail-closed: it still blocks
    assert seen and "list_ui_components" in seen[0][0]
