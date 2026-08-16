r"""#782: the projected detail/hero metadata row read BARE field names.

Found by opening `title_detail.png` (r151) after item 107 flagged the judge's deviation
*"entire meta block missing (year, seasons, HD, rating, tags, description, cast, genres)"* as
half-false. Four of the eight were on screen. The other four were genuinely absent, and the cause
had never been identified — it is in the framework, not the lane:

    {[cur.year, cur.maturity_rating, _fmtDur(cur.duration || cur.runtime)] ...}   # was
    {cur.genres || cur.genre ? ... String(cur.genre).split(/,\s*/) ...}           # was

r151's `titles` table has NONE of `year`, `duration`, `runtime`, `genres`, `genre`. It has
`release_year`, `duration_min`, and a `title_genres` join. So the row collapsed to
`maturity_rating` plus the literal HD badge — which is EXACTLY what the capture shows (TV-14 and
HD present, year/runtime/genres absent).

The tell is that these were the only bare reads in the file: `_imgOf` tries 18 keys, `_titleOf`
10, `_subOf` 12, `_videoOf` 6, `_backdropOf` 6 — because the projector cannot know the app's
column names. Two sites broke that invariant, and `_metaOf` sat defined-but-unused on the same
page.

Corpus, over the 122 runs whose projected page reads these fields:
    a table aliases YEAR (`release_year`, ...)    17 runs  (13%)  -> year chip silently absent
    a table aliases DURATION (`duration_min`, ..)  5 runs  ( 4%)  -> runtime chip absent
    genres live in a JOIN table                  120 runs  (98%)  -> genre block absent

The first two are fixed here. **The 98% is not** — no frontend accessor can invent a field the
payload does not carry; that needs the detail endpoint to aggregate the join, which is item 109.

These tests EXECUTE the emitted JS under node rather than grepping the source for substrings.
A substring assertion is what pinned this defect in place for 122 runs
(`test_frontend_hero_cta.py` asserted `"cur.year" in out`).
"""
import json
import shutil
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_NODE = shutil.which("node") or shutil.which("nodejs")
pytestmark = pytest.mark.skipif(_NODE is None, reason="needs a node runtime to execute the JS")


def _js(expr_pairs):
    """Evaluate each JS expression against the real emitted helper block."""
    body = ",".join(f"JSON.stringify({e})" for _, e in expr_pairs)
    src = fs._REF_HELPERS_JS + f"\nconsole.log(JSON.stringify([{body}]));\n"
    out = subprocess.run([_NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"emitted helpers are not valid JS:\n{out.stderr}"
    return dict(zip([n for n, _ in expr_pairs], [json.loads(x) for x in json.loads(out.stdout)]))


# --- the r151 record, verbatim from its titles DDL ------------------------------------------------

R151 = {"id": 1, "kind": "show", "name": "Disclosure Day", "synopsis": "A leak upends a city.",
        "poster_url": "/p.jpg", "backdrop_url": "/b.jpg", "release_year": 2019,
        "maturity_rating": "TV-14", "duration_min": 48, "language": "en", "country": "US",
        "cast_list": "A, B", "director": "C", "avg_rating": 4.2}


def test_the_r151_record_now_yields_a_year_and_a_runtime():
    got = _js([("y", f"_yearOf({json.dumps(R151)})"), ("d", f"_durOf({json.dumps(R151)})")])
    assert got["y"] == "2019"
    assert got["d"] == "48m"


def test_the_old_expressions_really_did_yield_nothing():
    """Non-vacuity: without the fix this row had nothing but the rating to show."""
    got = _js([("y", f"({json.dumps(R151)}).year || ''"),
               ("d", f"({json.dumps(R151)}).duration || ({json.dumps(R151)}).runtime || ''"),
               ("g", f"({json.dumps(R151)}).genres || ({json.dumps(R151)}).genre || ''")])
    assert got["y"] == "" and got["d"] == "" and got["g"] == ""


# --- _yearOf ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("rec,want", [
    ({"year": 1999}, "1999"),
    ({"release_year": 2019}, "2019"),
    ({"air_year": 2004}, "2004"),
    ({"published_year": 2011}, "2011"),
    ({"release_date": "2021-04-03"}, "2021"),
    ({"first_aired": "03/09/1987"}, "1987"),
    ({}, ""),
    ({"year": None}, ""),
])
def test_year_fallbacks(rec, want):
    assert _js([("v", f"_yearOf({json.dumps(rec)})")])["v"] == want


def test_created_at_is_deliberately_not_a_year_source():
    """Every row has one, and it is the INSERT time — it would print a confident wrong year on
    every app in the corpus rather than leaving the chip out."""
    assert _js([("v", '_yearOf({"created_at": "2026-08-15T10:00:00Z"})')])["v"] == ""


# --- _durOf ----------------------------------------------------------------------------------------

def test_every_episode_duration_spelling_in_the_corpus_is_covered():
    """The episode row had the same bare read, and the first probe of its prevalence said 2% —
    wrong, because the candidate set omitted `duration_minutes` and `duration_seconds` (the
    `id` in `profile_id` class of miss). Enumerating the actual spellings gave:
        duration 115 | duration_minutes 19 | duration_min 4 | duration_seconds 1  -> 24/139 = 17%
    """
    recs = {"duration": 22, "duration_minutes": 22, "duration_min": 22, "duration_seconds": 1320}
    got = _js([(k, f'_durOf({{"{k}": {v}}})') for k, v in recs.items()])
    assert set(got.values()) == {"22m"}, got


@pytest.mark.parametrize("rec,want", [
    ({"duration_min": 48}, "48m"),
    ({"runtime_min": 95}, "1h 35m"),
    ({"runtime": 90}, "1h 30m"),
    ({"duration_sec": 5400}, "1h 30m"),
    ({}, ""),
    ({"duration_min": 0}, ""),
])
def test_duration_fallbacks(rec, want):
    assert _js([("v", f"_durOf({json.dumps(rec)})")])["v"] == want


def test_minutes_are_not_guessed_as_seconds():
    """`_fmtDur` guesses the unit from magnitude (>=300 means seconds). A 320-MINUTE film is a
    real value that lands on the wrong side of that guess. `_durOf` knows the unit from the key
    name, so it does not have to guess — and the old call site passed the raw number straight in."""
    got = _js([("new", '_durOf({"duration_min": 320})'), ("old", "_fmtDur(320)")])
    assert got["new"] == "5h 20m"
    assert got["old"] == "5m", "non-vacuity: this is what the old path produced"


# --- #850: the branch that did NOT have to guess was the one that lied ------------------------

@pytest.mark.parametrize("sec,want", [(30, "1m"), (90, "2m"), (180, "3m"), (240, "4m"),
                                      (299, "5m"), (300, "5m"), (5400, "1h 30m")])
def test_a_short_explicit_seconds_duration_is_not_rounded_up(sec, want):
    """★ The test above states the principle — "`_durOf` knows the unit from the key name, so it
    does not have to guess" — and the code violated it three characters away, on the very branch
    the docstring describes. `_fmtDur(Math.max(n, 300))` suppressed the magnitude guess by
    **rewriting the value**, so every duration under five minutes rendered "5m".

    Not a wrong guess. An unconditional lie, on the one branch where nothing had to be guessed.
    `duration_sec` is the unit, in the name."""
    assert _js([("v", f'_durOf({{"duration_sec": {sec}}})')])["v"] == want


def test_the_clamp_really_did_produce_five_minutes():
    """Non-vacuity: reproduce the old expression rather than assert what it used to do."""
    assert _js([("v", "_fmtDur(Math.max(180, 300))")])["v"] == "5m"


def test_the_magnitude_guess_survives_for_a_bare_duration():
    """Blast radius. A bare `duration` column has no unit in its name, the guess is the only thing
    available, and it is right on 100 of the 102 corpus runs that have one — r105 and r118 are the
    only two that straddle 300. Replacing it would swap a good guess for a different guess."""
    got = _js([("m", '_durOf({"duration": 45})'), ("s", '_durOf({"duration": 5400})')])
    assert got["m"] == "45m" and got["s"] == "1h 30m"


def test_zero_live_instances_and_that_is_the_point():
    """2348 `duration_seconds` values across 151 runs, minimum 720 — this fires on no Netflix run.
    It is a GENERALITY fix, and the distinction from `_parent_lookup_col`'s 0-instance fuzzy bind
    (deliberately NOT built) is the direction of travel: that one would have replaced a correct
    behaviour with a guess; this replaces a guess with the known answer. For a music or podcast
    app every track under five minutes read "5m"."""
    assert _js([("v", '_durOf({"duration_seconds": 210})')])["v"] == "4m"


# --- _genresOf -------------------------------------------------------------------------------------

@pytest.mark.parametrize("rec,want", [
    ({"genres": ["Drama", "Thriller"]}, ["Drama", "Thriller"]),
    ({"genres": [{"name": "Drama"}, {"name": "Crime"}]}, ["Drama", "Crime"]),
    ({"genre": "Drama, Thriller"}, ["Drama", "Thriller"]),
    ({"genre": "Drama|Thriller"}, ["Drama", "Thriller"]),
    ({"categories": ["Kids"]}, ["Kids"]),
    ({"tags": "a / b"}, ["a", "b"]),
    ({}, []),
    ({"genres": []}, []),
])
def test_genre_fallbacks(rec, want):
    assert _js([("v", f"_genresOf({json.dumps(rec)})")])["v"] == want


def test_the_join_table_case_is_still_empty_and_that_is_item_109():
    """98% of the corpus. Recorded as a passing test on purpose: it states the boundary of #782 so
    a later reader does not assume the genre block was fixed."""
    assert _js([("v", f"_genresOf({json.dumps(R151)})")])["v"] == []


# --- _ratingOf (#783): the sweep for more of #782's class turned up one more site ------------------

@pytest.mark.parametrize("rec,want", [
    ({"maturity_rating": "TV-14"}, "TV-14"),
    ({"content_rating": "PG-13"}, "PG-13"),
    ({"rating_label": "15+"}, "15+"),
    ({"rating_age": 18}, "18"),
    ({}, ""),
])
def test_rating_fallbacks(rec, want):
    assert _js([("v", f"_ratingOf({json.dumps(rec)})")])["v"] == want


@pytest.mark.parametrize("k", ["rating", "avg_rating", "average_rating", "rating_avg"])
def test_the_average_score_is_never_shown_as_a_certification(k):
    """★ The naive fix here is WORSE than the bug. 117 of 139 content tables carry BOTH
    `maturity_rating` and `rating` — and `rating` is the average score. A fallback list that
    included it would print `4.2` where `TV-14` belongs, in 117 of 139 runs, while the actual
    defect (`rating_label`/`rating_age` with no `maturity_rating`) is 2 of 139.

    Same shape as item 109's `my_list` trap: the candidates are structurally identical and only
    their MEANING separates a correct chip from a wrong one."""
    assert _js([("v", f'_ratingOf({{"{k}": 4.2}})')])["v"] == ""


def test_rating_prefers_the_certification_when_both_are_present():
    """The 117-run majority shape."""
    got = _js([("v", '_ratingOf({"maturity_rating": "TV-14", "rating": 4.2})')])
    assert got["v"] == "TV-14"


# --- the sweep's negative results, recorded so the class is not re-swept ----------------------------

def test_top10_rank_is_deliberately_left_bare():
    """`top10_rank` appears in 133 of 139 content tables and is never aliased; the other 6 have no
    rank column at all. An accessor here would be motion without a defect."""
    import inspect
    assert "cur.top10_rank" in inspect.getsource(fs) or "r.top10_rank" in inspect.getsource(fs)


def test_episodes_already_has_its_own_fallback():
    """`cur.episodes` is not a DDL column — the page falls back to a separate /episodes fetch when
    the detail payload does not embed them, which is the same fallback idea one level up."""
    import inspect
    src = inspect.getsource(fs)
    assert "episodes" in src and "_rec.episodes" in src


# --- the call sites actually use them ---------------------------------------------------------------

def test_both_call_sites_were_converted():
    import inspect
    # Comment lines are stripped first: the prose explaining the fix necessarily quotes the very
    # string being forbidden, and a raw `in src` check matches the explanation instead of the code.
    src = "\n".join(ln for ln in inspect.getsource(fs).splitlines()
                    if not ln.lstrip().startswith("#"))
    assert "cur.year" not in src, "a bare read survived"
    assert "cur.duration || cur.runtime" not in src
    assert "Array.isArray(cur.genres)" not in src
    assert src.count("_yearOf(cur)") >= 4, "hero + detail, in both the guard and the row"


def test_the_helpers_ship_on_every_page_that_uses_them():
    """A helper used but not emitted is a ReferenceError, which blanks the page — the #753 class.
    Both call sites live in the page family that emits _REF_HELPERS_JS."""
    import inspect
    src = inspect.getsource(fs)
    assert "+ _REF_HELPERS_JS +" in src
    for name in ("_yearOf", "_durOf", "_genresOf"):
        assert f"const {name} = " in fs._REF_HELPERS_JS, name


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
