"""FIX #160 (gmrun7 M1) — the real-data walk drives a SEARCH QUERY with a salient seed term.

gmrun7 M1 reported no_real_data=True (a FALSE positive: playwright-verified the frontend
renders "Pinecrest Diner / 401 Geary Street" once authenticated + queried). Root cause: the
walk visits each page's route BARE (no query). For a map/search/list app the real data only
renders on a SEARCH page WITH a query — the home map shows category chips + Leaflet pins (no
innerText place names), and a bare /search either shows "No results" or a default query whose
results may not intersect the salient-seed set. So the shallow bare-route walk sees no salient
value → no_real_data=True → spurious P0s to a working frontend.

Fix: when the bare walk found no real data, drive the search route(s) with a query token
derived from a salient seed value (guaranteeing the searched value is in the assertion set),
collect that text, and re-judge. Pure helpers here; the playwright glue is thin + best-effort.
LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    search_query_token, search_route_candidates)


# ------------------------------ search_query_token ------------------------------

def test_token_is_first_salient_word():
    assert search_query_token(["Pinecrest Diner", "Inle Burmese Cuisine"]) == "Pinecrest"


def test_token_skips_leading_numbers_and_short_words():
    # "401 Geary Street" → the query token should be a real word, not the house number
    assert search_query_token(["401 Geary Street"]) == "Geary"


def test_token_skips_a_pure_number_value_entirely():
    assert search_query_token(["2024", "Suppenküche"]) == "Suppenküche"


def test_token_none_when_no_usable_term():
    assert search_query_token([]) is None
    assert search_query_token(["7", "12", "$$"]) is None


def test_token_handles_unicode_word():
    assert search_query_token(["Tlaloc"]) == "Tlaloc"


def test_token_skips_stopwords():
    # FIX #163 (gmrun8): "The Little Chihuahua" -> the first word is the STOP-WORD "The",
    # a poor query token (matches too much / not the place). Pick a DISTINCTIVE word.
    assert search_query_token(["The Little Chihuahua"]) == "Little"
    assert search_query_token(["A Fine Cafe"]) == "Fine"
    assert search_query_token(["Of Mice and Men Bookstore"]) == "Mice"


def test_token_falls_back_to_stopword_only_value():
    # a value that is ONLY stop-words (degenerate) still yields something usable
    assert search_query_token(["The And", "Pinecrest Diner"]) == "Pinecrest"


def test_token_first_value_distinctive_word_wins_over_later_values():
    # still driven by the FIRST value's distinctive word, not a later value
    assert search_query_token(["The Pinecrest Diner", "Zzz"]) == "Pinecrest"


# ---------------------------- search_route_candidates ----------------------------

def test_identifies_search_route_by_name():
    pages = [{"name": "home_map", "route": "/"},
             {"name": "search_results", "route": "/search"},
             {"name": "place_detail", "route": "/place/:id"}]
    cands = search_route_candidates(pages)
    assert [c["route"] for c in cands] == ["/search"]


def test_identifies_by_route_keyword():
    pages = [{"name": "a", "route": "/explore"}, {"name": "b", "route": "/browse"},
             {"name": "c", "route": "/profile"}]
    routes = [c["route"] for c in search_route_candidates(pages)]
    assert "/explore" in routes and "/browse" in routes and "/profile" not in routes


def test_dedupes_and_skips_param_and_auth_routes():
    pages = [{"name": "search_results", "route": "/search"},
             {"name": "search_results2", "route": "/search"},   # dup route
             {"name": "search_detail", "route": "/search/:id"},  # param route — skip
             {"name": "login_search", "route": "/login"}]        # auth route — skip
    routes = [c["route"] for c in search_route_candidates(pages)]
    assert routes == ["/search"]


def test_empty_when_no_search_page():
    pages = [{"name": "home", "route": "/"}, {"name": "profile", "route": "/me"}]
    assert search_route_candidates(pages) == []


# ------------------------------ query-url assembly ------------------------------

def test_query_url_carries_common_param_aliases():
    from multi_agent.runtime.test_user_runner import search_query_url
    url = search_query_url("http://x", "/search", "Pinecrest")
    # robust to the app's param name — read whichever it uses; extras are ignored
    assert url.startswith("http://x/search?")
    for p in ("q=Pinecrest", "query=Pinecrest", "search=Pinecrest"):
        assert p in url, url


def test_query_url_url_encodes_the_term():
    from multi_agent.runtime.test_user_runner import search_query_url
    url = search_query_url("http://x", "/search", "San Francisco")
    assert "San%20Francisco" in url or "San+Francisco" in url
