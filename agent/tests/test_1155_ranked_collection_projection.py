"""#1155: `/api/titles/top10` must not be a copy of `/api/titles`.

netflix-local-r13 DELIVERED (146 min, runtime-verified: --no-cache build, 779-char
token, frontend 200) and the delivered API answered 60 rows for /api/titles,
/api/titles/trending AND /api/titles/top10 -- identically.  The projected handler
was `db.query(Title).limit(100).all()`, with `top10_rank` SELECTED into every row
and never read, while the spec declares that column for exactly this endpoint.

It also put one of the framework's own detectors out of reach: remediation_
dispatcher's "N column(s) are filtered on but never seeded" P0 can only see a
column something FILTERS on, and nothing did -- so `top10_rank` being NULL in all
60 rows was never filed either.  Projecting the filter returns that column to the
detector's reach.

This projects code a lane CANNOT change, so the rule must not guess.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp

TITLE_COLS = ["id", "name", "kind", "year", "genre", "maturity_rating", "rating",
              "synopsis", "poster", "backdrop", "video_url", "duration", "top10_rank"]


def test_the_r13_endpoint_is_recognised():
    assert rp._ranked_collection_1155(
        "/api/titles/top10", TITLE_COLS, "titles") == ("top10_rank", 10, False)


def test_a_segment_with_no_matching_column_is_left_alone():
    """r13 also shipped /api/titles/trending; there is no `trending*` column, so the
    projector must not invent an ordering for it."""
    assert rp._ranked_collection_1155("/api/titles/trending", TITLE_COLS, "titles") is None


def test_the_resource_segment_itself_never_counts():
    assert rp._ranked_collection_1155("/api/titles", TITLE_COLS, "titles") is None
    assert rp._ranked_collection_1155("/api/genres", ["id", "name"], "genres") is None


def test_a_nested_child_collection_is_untouched():
    assert rp._ranked_collection_1155(
        "/api/titles/{id}/episodes", TITLE_COLS, "episodes") is None


def test_a_score_column_sorts_descending_and_the_number_caps_the_rows():
    assert rp._ranked_collection_1155(
        "/api/posts/top5", ["id", "top5_score"], "posts") == ("top5_score", 5, True)


def test_an_absurd_row_cap_falls_back_to_the_default():
    """`/api/titles/top99999` must not emit LIMIT 99999."""
    out = rp._ranked_collection_1155("/api/x/top99999", ["id", "top99999_rank"], "x")
    assert out is not None and out[1] == 100, out


def test_the_projection_filters_nulls_and_orders():
    """A ranked view whose rank is NULL is not in the ranking -- and the IS NOT NULL is
    exactly what makes the unseeded column visible to the P0 detector."""
    src = Path(rp.__file__).read_text(encoding="utf-8")
    i = src.index("_rank1155 = _ranked_collection_1155(")
    branch = src[i:src.index("elif cls and m in (\"POST\"", i)]
    assert ".isnot(None)" in branch
    assert ".order_by(" in branch
    assert ".limit({_rlim})" in branch


def test_the_unranked_path_still_emits_what_it_always_did():
    """No behaviour change for every endpoint the rule does not recognise."""
    src = Path(rp.__file__).read_text(encoding="utf-8")
    i = src.index("_rank1155 = _ranked_collection_1155(")
    branch = src[i:src.index("elif cls and m in (\"POST\"", i)]
    assert 'db.query({cls}).limit(100).all()' in branch
