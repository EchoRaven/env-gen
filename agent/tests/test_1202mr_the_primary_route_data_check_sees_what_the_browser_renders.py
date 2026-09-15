"""#1202mr: the never-escaping `primary_dataless` hold must recognise seeded data it is shown.

tiktok-r124's M1 gate was otherwise clear and deferred for more than three hours on
`DELIVERY DEFERRED: browser test-user found the app UNUSABLE (primary_dataless=True)`, eight
attempts. FIX #152 makes that signal HARD — it never takes the bounded escape — and the P0 it
sends the frontend named nothing. Loading `/` on the live app showed a seeded video:

    @bts_official_bighit
    #KEEPSWIMMING with BTS. To everyone who keeps swimming no matter wha...

Two independent reasons the check missed it, both measured on that run's seed files:
  1. the caption is stored with TWO spaces after "BTS."; innerText renders one, and the match
     was an exact substring;
  2. it was not among the 40 sampled values (it is value 41+ of 139).

Extending the sample wholesale is unsafe — past 40 the corpus adds 993 single words for netflix
alone (`Music`, `Comedy`, `Drama`, `Family`) that a nav bar or genre chip renders on an empty
page. Only multi-word values of 20+ characters are added: across 143 runs, 9825 such values,
none of which occurs in the run's own ui_page registry text or App.jsx labels.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import test_user_runner as T  # noqa: E402

CAPTION = "#KEEPSWIMMING with BTS.  To everyone who keeps swimming no matter wha..."
R124_PRIMARY_TEXT = (
    "For You\nShop\nExplore\nFollowing\nLIVE\nUpload\nProfile\nMore\nLog in\nCompany\nProgram\n"
    "Terms & Policies\n© 2026 TikTok\nGet Coins\nGet App\nPC App\nLog in\n@bts_official_bighit\n"
    "#KEEPSWIMMING with BTS. To everyone who keeps swimming no matter wha...\n+\n3\n16\n2\n0")
SHELL_ONLY = R124_PRIMARY_TEXT.split("@bts_official_bighit")[0] + "No videos yet"


def _seed_project(tmp, videos, genres=()):
    be = Path(tmp) / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(json.dumps({
        "videos": videos,
        "genres": [{"name": g} for g in genres],
    }), encoding="utf-8")
    return Path(tmp)


def _many_videos(n=60, caption_at=50):
    rows = []
    for i in range(n):
        rows.append({"id": i, "title": f"Clip Number {i} Title",
                     "caption": (CAPTION if i == caption_at
                                 else f"A distinct caption number {i} for this clip")})
    return rows


def test_whitespace_the_browser_collapses_still_matches():
    v = T.real_data_verdict([R124_PRIMARY_TEXT], [CAPTION])
    assert v["rendered"] is True, v


def test_an_exact_substring_is_still_a_match():
    v = T.real_data_verdict(["hello Rehearsal room warm-up there"], ["Rehearsal room warm-up"])
    assert v["rendered"] is True


def test_the_shell_alone_is_still_empty():
    v = T.real_data_verdict([SHELL_ONLY], [CAPTION, "Rehearsal room warm-up"])
    assert v["checked"] is True and v["rendered"] is False, v


def test_a_long_content_value_past_the_first_40_is_checked():
    with tempfile.TemporaryDirectory() as tmp:
        proj = _seed_project(tmp, _many_videos())
        vals = T.extract_seed_display_values(proj)
        assert CAPTION in vals, len(vals)
        assert T.real_data_verdict([R124_PRIMARY_TEXT], vals)["rendered"] is True


def test_the_first_40_are_unchanged_so_the_search_token_is_too():
    with tempfile.TemporaryDirectory() as tmp:
        proj = _seed_project(tmp, _many_videos())
        merged = json.loads((proj / "app" / "backend" / "seed_dataset.json").read_text())
        assert T.extract_seed_display_values(proj)[:40] == T.salient_seed_values(merged)


def test_single_words_past_the_first_40_are_not_added():
    """A genre word a nav bar renders must not make an empty page read as populated."""
    genres = [f"Genreword{i}" for i in range(80)] + ["Comedy", "Drama", "Family"]
    with tempfile.TemporaryDirectory() as tmp:
        proj = _seed_project(tmp, _many_videos(), genres=genres)
        vals = T.extract_seed_display_values(proj)
        assert all(" " in v for v in vals[40:]), [v for v in vals[40:] if " " not in v][:5]
        nav = "Home Comedy Drama Family Genreword70 Genreword71 Log in"
        assert T.real_data_verdict([nav], vals[40:])["rendered"] is False


def test_the_hold_says_what_the_primary_route_rendered():
    report = {"ran": True, "api_login_ok": True, "auth_ok": True,
              "primary_dataless": True, "primary_route_rendered": "For You Shop Explore"}
    out = T.browser_unusable_signals(report)
    assert out.get("primary_route_rendered") == "For You Shop Explore", out
