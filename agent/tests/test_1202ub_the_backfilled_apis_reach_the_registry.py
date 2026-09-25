r"""#1202ub: the framework worked out each page's APIs, projected from them, then threw them away.

`backfill_page_apis` exists because a ui_page registered with an empty `apis_used` projects a
bare fallback stub that the delivery gate rejects. It matches the page's own name/route/
component against the registered GET paths by token overlap, fills the gap, and the projector
builds a real component from the result.

It was then assigned to a LOCAL list. Nothing wrote it back. So the registry kept
`apis_used: []` and every reader of the CONTRACT stayed blind.

WHY THAT IS NOT COSMETIC -- the framework's own warning says it: "an empty list does not fail
the decoy-twin / consumer-wiring / implemented-flip checks, it TURNS THEM OFF, and the page
then ships without them ever looking at it." Each of those checks is a
`for a in (page.get("apis_used") or [])` whose body never runs on an empty list.

MEASURED in r133 (delivered, $416.73): 13 of 13 registered ui_pages had `apis_used: []`, so
that entire check family was off for every page in the run -- and
`deliverability_all_page_apis_empty` was the ONE failing check still standing at the delivery
cut. The gate was asking the lane to redo work the framework had already done and discarded.

DOMAIN-AGNOSTIC BY CONSTRUCTION, and a test below pins it: the backfill is pure token overlap
between a page's own strings and the registered GET paths, so renaming every table and page to
`t1`/`p1` must not change the behaviour.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_scaffold import backfill_page_apis  # noqa: E402
from multi_agent.runtime.scaffolder import persist_backfilled_apis_1202ub  # noqa: E402


class _Hub:
    """Records what register_ui_page was asked to persist."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def register_ui_page(self, name="", apis_used=None, agent="", **kw):
        if self.fail:
            raise RuntimeError("registry unavailable")
        self.calls.append({"name": name, "apis_used": list(apis_used or []), "agent": agent})
        return {}


def _pages_and_eps(page_name="profiles_page", collection="profiles"):
    pages = [{"name": page_name, "route": "/" + collection, "component": "ProfilesPage",
              "apis_used": []}]
    eps = [{"method": "GET", "path": "/api/" + collection},
           {"method": "GET", "path": "/api/unrelated"}]
    return pages, eps


def test_the_backfill_still_computes_the_answer():
    """Premise. If this stops filling, the write-back has nothing to persist."""
    pages, eps = _pages_and_eps()
    out = backfill_page_apis(pages, eps)
    assert out[0]["apis_used"], out


def test_what_the_backfill_filled_reaches_the_registry():
    """The bug: r133 registered 13 of 13 pages empty while the projector used real APIs."""
    pages, eps = _pages_and_eps()
    before = {p["name"]: list(p.get("apis_used") or []) for p in pages}
    filled = backfill_page_apis(pages, eps)
    hub = _Hub()
    n = persist_backfilled_apis_1202ub(hub, filled, before)
    assert n == 1 and len(hub.calls) == 1, hub.calls
    assert hub.calls[0]["name"] == "profiles_page"
    assert hub.calls[0]["apis_used"] == filled[0]["apis_used"]


def test_a_page_the_backfill_did_not_change_is_not_rewritten():
    """ADDITIVE only -- the lane's own declaration is the contract, not ours to restate."""
    pages = [{"name": "p", "route": "/x", "component": "P", "apis_used": ["/api/declared"]}]
    before = {"p": ["/api/declared"]}
    hub = _Hub()
    assert persist_backfilled_apis_1202ub(hub, pages, before) == 0
    assert hub.calls == []


def test_an_addition_to_a_non_empty_page_is_persisted_too():
    """#1202ug: the first version skipped ANY page that already declared something, which
    threw away the sharper half.

    `backfill_page_apis` ends in `_backfill_route_implied_apis` (#579), whose entire purpose
    is to enrich a page carrying a WRONG-but-non-empty list: netflix r142 had
    `title_detail_page` (/title/:id) declaring only `GET /api/profiles` while no page in the
    draw declared `/api/titles/{id}/episodes`, so the projected detail page fetched no title
    and rendered no episodes. Skipping on "was it empty" discarded exactly that repair.
    """
    pages = [{"name": "title_detail_page", "route": "/titles/:id",
              "component": "TitleDetailPage", "apis_used": ["GET /api/profiles"]}]
    eps = [{"method": "GET", "path": "/api/titles/{id}"},
           {"method": "GET", "path": "/api/titles/{id}/episodes"},
           {"method": "GET", "path": "/api/profiles"}]
    before = {"title_detail_page": ["GET /api/profiles"]}
    filled = backfill_page_apis([dict(p) for p in pages], eps)
    added = set(filled[0]["apis_used"]) - set(before["title_detail_page"])
    assert added, "#579 no longer enriches a non-empty page -- the premise is gone"

    hub = _Hub()
    assert persist_backfilled_apis_1202ub(hub, filled, before) == 1, hub.calls
    persisted = set(hub.calls[0]["apis_used"])
    assert added <= persisted, (added, persisted)
    assert "GET /api/profiles" in persisted, "the lane's own declaration was dropped"


def test_a_page_the_backfill_could_not_fill_is_left_alone():
    pages = [{"name": "p", "route": "/x", "component": "P", "apis_used": []}]
    hub = _Hub()
    assert persist_backfilled_apis_1202ub(hub, pages, {"p": []}) == 0
    assert hub.calls == []


def test_a_registry_that_refuses_never_breaks_the_run():
    """Scaffolding is not allowed to die because an advisory write failed."""
    pages, eps = _pages_and_eps()
    before = {p["name"]: [] for p in pages}
    assert persist_backfilled_apis_1202ub(_Hub(fail=True), backfill_page_apis(pages, eps),
                                          before) == 0
    assert persist_backfilled_apis_1202ub(None, None, {}) == 0


def test_it_is_domain_agnostic():
    """★ The user's iron rule, asserted rather than asserted-in-prose: rename everything to
    meaningless tokens and the behaviour must be identical."""
    real_pages, real_eps = _pages_and_eps("profiles_page", "profiles")
    anon_pages, anon_eps = _pages_and_eps("p1_page", "p1")
    outs = []
    for pages, eps in ((real_pages, real_eps), (anon_pages, anon_eps)):
        before = {p["name"]: [] for p in pages}
        hub = _Hub()
        persist_backfilled_apis_1202ub(hub, backfill_page_apis(pages, eps), before)
        outs.append([len(c["apis_used"]) for c in hub.calls])
    assert outs[0] == outs[1] == [1], outs
