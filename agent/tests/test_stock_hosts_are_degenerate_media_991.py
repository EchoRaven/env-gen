"""#991: a stock-photo host is degenerate media — the app must be self-contained.

r161's only real blocker. The delivery gate sat on
`['deliverability_ui_flow_failed', 'validation_ui_evidence_failed']` with `blank=[]` — the
pages RENDER, and every one of them logs:

    Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED

`backend_skeleton` seeds every image-ish column with
`https://picsum.photos/seed/<table><i>/<size>`, unreachable from the sandbox. Console errors
fail the UI-evidence gate, so the run cannot deliver.

#512 exists to fix exactly this kind of thing — it round-robins 60 real staged posters over
DEGENERATE media fields. But distinct picsum URLs pass every degeneracy test it had: they
differ per row, they look like image refs, and none is a `/crops/` fragment. The heal that
was built to fill media never fired, while the real assets sat unused.

Self-containment is the right property independent of this sandbox: a generated demo whose
images require the public internet is broken offline too.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
    _STOCK_HOST_991, _field_is_degenerate)


def _rows(*urls):
    return [{"poster": u} for u in urls]


@pytest.mark.parametrize("host", [
    "https://picsum.photos/seed/titles1/640/360",
    "https://unsplash.com/photos/x.jpg",
    "https://i.pravatar.cc/200",
    "https://via.placeholder.com/640x360",
    "https://dummyimage.com/640x360",
])
def test_the_stock_hosts_are_recognised(host):
    assert _STOCK_HOST_991.search(host)


@pytest.mark.parametrize("url", [
    "/assets/posters/p1.png",
    "https://cdn.myapp.example.com/real.jpg",
    "/static/media/hero.webp",
])
def test_real_media_is_not_a_stock_host(url):
    assert not _STOCK_HOST_991.search(url)


def test_distinct_picsum_urls_are_degenerate():
    """The exact r161 shape: every row DIFFERENT, every row unreachable."""
    rows = _rows("https://picsum.photos/seed/titles0/640/360",
                 "https://picsum.photos/seed/titles1/640/360",
                 "https://picsum.photos/seed/titles2/640/360")
    assert _field_is_degenerate(rows, "poster") is True


def test_the_framework_placeholder_is_upgradeable():
    """#994: #993's inline data-URI swatch renders with no network and no console error, but
    a wall of flat rectangles is the "30 identical cards" look #512 exists to prevent. The
    seed emitter is a pure function and cannot see the staged pool; #512 can. Marking the
    placeholder degenerate is what lets the two meet."""
    rows = _rows("data:image/svg+xml;utf8,%3Csvg%20a",
                 "data:image/svg+xml;utf8,%3Csvg%20b",
                 "data:image/svg+xml;utf8,%3Csvg%20c")
    assert _field_is_degenerate(rows, "poster") is True


def test_real_local_assets_are_left_alone():
    rows = _rows("/assets/posters/a.png", "/assets/posters/b.png", "/assets/posters/c.png")
    assert _field_is_degenerate(rows, "poster") is False


def test_a_minority_of_stock_urls_is_not_degenerate():
    """Majority rule, matching the /crops/ test beside it — one stray placeholder in a real
    catalogue must not trigger a full rewrite."""
    rows = _rows("/assets/a.png", "/assets/b.png", "/assets/c.png",
                 "https://picsum.photos/seed/x/1/1")
    assert _field_is_degenerate(rows, "poster") is False


def test_the_existing_degeneracy_rules_still_hold():
    assert _field_is_degenerate(_rows("/a.png", "/a.png", "/a.png"), "poster") is True
    assert _field_is_degenerate(_rows("/crops/x.png", "/crops/y.png"), "poster") is True
    assert _field_is_degenerate([{"poster": None}, {"poster": ""}], "poster") is True


def test_the_control_passes_picsum_through():
    """Planted control: the PRE-FIX rules — all-same, /crops/, empty — accept distinct picsum
    URLs as healthy media, which is why the heal never fired."""
    vals = ["https://picsum.photos/seed/t0/640/360", "https://picsum.photos/seed/t1/640/360"]
    assert len(set(vals)) > 1
    assert not any("/crops/" in v for v in vals)
    assert all(v.strip() for v in vals), (
        "the control was supposed to look healthy to the old rules; if it does not, this fix "
        "is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
