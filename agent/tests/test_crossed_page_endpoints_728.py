r"""#728: pages calling another page's endpoint while their own sits implemented and unused.

r148 shipped `GenreCategoryPage.jsx` fetching `/api/my-list`. Click any genre, see your watchlist.
`GET /api/genres/{id}/titles` was registered AND implemented, and nothing called it.

Nothing caught it, and the reason is worth more than the bug: the page also DECLARED
`apis_used: ['GET /api/my-list']`. Code and declaration agree, so every consistency audit passes
— they agree on the wrong thing. The only detector that noticed was #700, and it reported the
symptom ("these routes render identical content") rather than the cause.

Across the runs it is a rotation, not a slip:

    r146   genre_category -> /api/my-list, my_list -> /api/titles, title_detail -> /api/genres
    r147   none — same framework, same prompt, so it is avoidable rather than inherent
    r148   genre_category -> /api/my-list, title_detail -> /api/genres

The test needs no product standard, which is why it is wired rather than filed: a page whose
declared APIs share NO path word with its own route, while an implemented endpoint DOES, is wrong
under any reading. That is deliberately narrower than "every implemented endpoint should have a
UI caller" — 12 of 16 are unused in r146 and r148, and whether THAT is a defect is a judgement
about product scope, left to the user.

Two defects in this detector were caught by its own output before it shipped, both of which would
have made it worse than nothing:

  * no stemming, so `genre` and `genres` were different words and it reported a clean ZERO on
    r148 — the run whose bug motivated it;
  * alphabetical ranking, so for `/title/:id` it suggested `GET /api/genres/{id}/titles` over
    `GET /api/titles/{id}`, pointing at the wrong endpoint.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    crossed_page_endpoints_728 as crossed,
    _route_tokens_728 as toks,
)


def _eps(*paths):
    return {f"e{i}": {"method": "GET", "path": p, "status": "implemented"}
            for i, p in enumerate(paths)}


def _pages(**kw):
    return {k: {"name": k, **v} for k, v in kw.items()}


# --- the shipped bug ------------------------------------------------------------------------

def test_the_genre_page_calling_my_list_is_flagged():
    out = crossed(
        _pages(genre_category_page={"route": "/browse/genre/:genreId",
                                    "apis_used": ["GET /api/my-list"]}),
        _eps("/api/genres/{id}/titles", "/api/my-list"))
    assert len(out) == 1
    assert out[0]["page"] == "genre_category_page"
    assert "GET /api/genres/{id}/titles" in out[0]["unused_match"]


def test_stemming_is_what_makes_it_fire():
    """`genre` vs `genres`: without folding the plural this detector reports zero on r148."""
    assert toks("/browse/genre/:genreId") & toks("/api/genres/{id}/titles")


def test_the_suggestion_is_ranked_by_overlap_not_alphabet():
    out = crossed(
        _pages(title_detail_page={"route": "/title/:id", "apis_used": ["GET /api/genres"]}),
        _eps("/api/genres/{id}/titles", "/api/titles/{id}"))
    assert out[0]["unused_match"][0] == "GET /api/titles/{id}"


# --- it must not fire on correct pages ------------------------------------------------------------

def test_a_page_using_its_own_endpoint_is_clean():
    assert crossed(
        _pages(my_list_page={"route": "/my-list", "apis_used": ["GET /api/my-list"]}),
        _eps("/api/my-list")) == []


def test_one_matching_api_among_several_is_enough():
    """A page may legitimately call extra endpoints; only ZERO overlap is suspicious."""
    assert crossed(
        _pages(p={"route": "/movies", "apis_used": ["GET /api/genres", "GET /api/movies"]}),
        _eps("/api/movies")) == []


def test_no_flag_without_a_better_candidate():
    """A page calling something unrelated is not actionable unless a fitting endpoint EXISTS."""
    assert crossed(
        _pages(p={"route": "/settings", "apis_used": ["GET /api/titles"]}),
        _eps("/api/titles")) == []


def test_an_unimplemented_candidate_does_not_count():
    eps = {"e0": {"method": "GET", "path": "/api/genres/{id}/titles", "status": "defined"}}
    assert crossed(
        _pages(p={"route": "/browse/genre/:id", "apis_used": ["GET /api/my-list"]}), eps) == []


@pytest.mark.parametrize("pages,eps", [
    ({}, {}), (None, None), ({"_meta": {}}, {"_meta": {}}),
    ({"p": {"route": "", "apis_used": []}}, {}),
    ({"p": "junk"}, {"e": "junk"}),
])
def test_degenerate_input_is_safe(pages, eps):
    assert crossed(pages, eps) == []


# --- back-tested against the real runs --------------------------------------------------------------

@pytest.mark.parametrize("run,expected", [
    ("netflix-web-r146", 3), ("netflix-web-r147", 0), ("netflix-web-r148", 2)])
def test_it_reproduces_the_measured_counts(run, expected):
    root = Path(__file__).resolve().parents[2] / "generated" / run / "shared" / "hubs"
    if not root.is_dir():
        pytest.skip(f"{run} not on disk")
    pg = json.loads((root / "registryhub_ui_pages.json").read_text())
    ep = json.loads((root / "registryhub_endpoints.json").read_text())
    assert len(crossed(pg, ep)) == expected


def test_r147_is_the_negative_control():
    """Same framework and prompt with zero crossings — so this is avoidable, not inherent, and
    a detector that fired on every run would be measuring something else."""
    root = Path(__file__).resolve().parents[2] / "generated" / "netflix-web-r147"
    if not root.is_dir():
        pytest.skip("r147 not on disk")
    h = root / "shared" / "hubs"
    assert crossed(json.loads((h / "registryhub_ui_pages.json").read_text()),
                   json.loads((h / "registryhub_endpoints.json").read_text())) == []


# --- provenance -------------------------------------------------------------------------------------

def test_the_stemming_regression_is_recorded():
    d = " ".join((crossed.__doc__ or "").split())
    assert "declaration agree" in d


def test_the_scope_limit_is_recorded():
    d = " ".join((crossed.__doc__ or "").split())
    assert "12 of 16 endpoints are unused" in d
    assert "deliberately not made here" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
