"""#1202gi — the JsonStore's own `_meta` was becoming a required UI flow.

`list_ui_pages()` returns the RAW store value, and every store carries
`_meta = {version, last_modified_by, last_modified_at}`. That is a dict, so it passed the
`isinstance(page, dict)` check in `_derive_ui_spec_from_hub` and became a page named
`_meta`. It has no `route` key, and #243 deliberately keeps a route-less entry REQUIRED
("an entry with NO route key at all is an older spec shape and stays required" — the
conservative choice, aimed at old specs, not at store bookkeeping).

So `_meta` became a required UI flow that no browser walk can ever record, and
`deliverability_ui_flow_missing` could not clear while the page-derived path was in use.

Measured with the production functions over the 137 kept ui_page stores on this machine:
`_meta` becomes a required flow in 137 of them — all of them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.flow_coverage import (  # noqa: E402
    _derive_ui_spec_from_hub, _extract_required_flows, _is_navigable_page)

# The real shape a JsonStore writes, verified against tiktok-r98's store.
STORE = {
    "_meta": {"version": 63, "last_modified_by": "orchestrator",
              "last_modified_at": 1788817505.59},
    "explore_grid_page": {"name": "explore_grid_page", "route": "/explore",
                          "component": "ExplorePage"},
    "profile_own_page": {"name": "profile_own_page", "route": "/@:username",
                         "component": "ProfilePage"},
}


class _WH:
    def list_documents(self, kind=None):
        return []


class _RH:
    def __init__(self, store):
        self._s = store

    def list_ui_pages(self):
        return self._s


class _Hubs:
    def __init__(self, store=None):
        self.workhub = _WH()
        self.registryhub = _RH(STORE if store is None else store)


def test_store_meta_is_not_a_required_flow():
    """The defect in one line: an unrecordable flow blocked the gate forever."""
    names, source = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs()))
    assert "_meta" not in names, names
    assert source == "pages"


def test_the_real_pages_survive():
    names, _ = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs()))
    assert sorted(names) == ["explore_grid_page", "profile_own_page"], names


def test_243_still_keeps_a_routeless_real_page_required():
    """#243's conservative choice is untouched — this filters by store KEY, not by the
    absence of a route."""
    store = dict(STORE)
    store["legacy_page"] = {"name": "legacy_page"}          # no route key at all
    names, _ = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs(store)))
    assert "legacy_page" in names, names
    assert _is_navigable_page({"name": "legacy_page"}) is True


def test_the_filter_is_independent_of_the_navigability_rule():
    """#1202gi drops a STORE KEY, not a shape. #243's own exemption has since been
    narrowed — `_is_navigable_page` now returns True for a route-less or empty-route entry,
    because the old exemption "removed real, validatable pages from the required set and
    swallowed 24 recorded failures". So this fix cannot lean on that rule, and does not:
    `_meta` goes because of its key, whatever the navigability rule says about it."""
    assert _is_navigable_page({"name": "video_grid", "route": ""}) is True
    assert _is_navigable_page(STORE["_meta"]) is True
    names, _ = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs()))
    assert "_meta" not in names


def test_it_filters_by_key_not_by_content():
    """A page whose own `name` starts with an underscore is not what this drops; the
    store reserves the leading underscore for its own keys."""
    store = {"_meta": STORE["_meta"],
             "real_page": {"name": "_odd_but_real", "route": "/odd"}}
    names, _ = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs(store)))
    assert names == ["_odd_but_real"], names


def test_an_empty_store_is_not_a_crash():
    names, source = _extract_required_flows(_derive_ui_spec_from_hub(_Hubs({})))
    assert names == []
