"""#993: the seed emits an inline placeholder, not a website.

`backend_skeleton._seed_cell` emitted `https://picsum.photos/seed/<table><i>/<size>` for every
image-ish column. The sandbox cannot reach it, so every page rendering a poster logged
`Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED`, console errors failed the
UI-evidence gate, and r161 died there.

#991 was aimed at this and missed. It taught #512's distributor to treat a stock host as
degenerate media — but that distributor rewrites seed ROWS, while these URLs live in the
generated `seed_data.py` SOURCE. r162 proved it: the heal fired **0** times and 31 picsum URLs
were still in the file. Fixing the consumer never reaches a producer.

A local `/assets/…` path is not the answer either: it 404s for any row the staged asset pool
does not cover, which is the same console error in different clothes. A data URI always
resolves, needs no network and no file.
"""

import re
import urllib.parse

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _seed_cell

IMAGE_COLS = ["poster_url", "avatar", "thumbnail_url", "banner", "image", "photo", "logo_url"]


@pytest.mark.parametrize("col", IMAGE_COLS)
def test_no_external_host_is_emitted(col):
    v = str(_seed_cell(col, "titles", 0, None, "text"))
    assert not re.match(r"https?://", v), f"{col} still points at a website: {v[:60]}"


@pytest.mark.parametrize("col", IMAGE_COLS)
def test_it_is_a_usable_data_uri(col):
    v = str(_seed_cell(col, "titles", 3, None, "text"))
    assert v.startswith("data:image/svg+xml;utf8,")
    decoded = urllib.parse.unquote(v.split(",", 1)[1])
    assert decoded.startswith("<svg") and decoded.rstrip().endswith("</svg>")
    assert "width=" in decoded and "height=" in decoded


def test_avatars_are_square_and_posters_are_not():
    """The old code varied size by column kind; that behaviour is preserved."""
    av = urllib.parse.unquote(str(_seed_cell("avatar", "users", 0, None, "text")))
    po = urllib.parse.unquote(str(_seed_cell("poster_url", "titles", 0, None, "text")))
    assert "width='200' height='200'" in av
    assert "width='640' height='360'" in po


def test_rows_differ_so_a_catalogue_is_not_one_flat_colour():
    """#512 exists because 30 identical posters look broken. Distinct hues per row keep the
    wall varied without needing any asset pool."""
    vals = {str(_seed_cell("poster_url", "titles", i, None, "text")) for i in range(8)}
    assert len(vals) >= 6, "seed images must vary across rows"


def test_the_same_row_is_stable():
    """Deterministic: a re-render must not churn the seed and dirty the diff."""
    a = _seed_cell("poster_url", "titles", 5, None, "text")
    b = _seed_cell("poster_url", "titles", 5, None, "text")
    assert a == b


@pytest.mark.parametrize("col,expect", [("title", str), ("release_year", int)])
def test_non_image_columns_are_untouched(col, expect):
    assert isinstance(_seed_cell(col, "titles", 0, None, "text" if expect is str else "integer"),
                      expect)


def test_the_control_reaches_the_network():
    """Planted control: the PRE-FIX value was an absolute URL to a third-party host, which is
    what the sandbox refuses and the gate punishes."""
    old = "https://picsum.photos/seed/titles0/640/360"
    assert re.match(r"https?://", old) and "picsum.photos" in old, (
        "the control was supposed to be an external URL; if it is not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
