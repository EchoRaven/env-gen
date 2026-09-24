"""B-direction — the browser test-user asserts the app renders REAL seeded data.

googlemaps run-3 shipped a UI that LOOKED fine — logged in, pages non-blank, no console
errors — but every core screen rendered a hardcoded MOCK twin ("HI Point Montara
Lighthouse …") instead of the 171 real seeded places ("Pinecrest Diner", "The Little
Chihuahua"). The existing browser gate only checks blank / login-redirect, so a page full
of *fake* text sailed through. This gate closes that hole: extract the salient real values
from the seed (multi-word proper names — place names, authors, addresses), collect the
innerText of every walked page, and assert that AT LEAST ONE seed value renders SOMEWHERE
in the app. Zero seed values across the whole walk ⇒ the frontend is not wired to real
data (mock twin, placeholder, or a silently-failing fetch).

False-positive guards: (1) a GLOBAL assertion — one page showing one seed value passes the
whole app, so pages that need a query/param to populate don't trip it; (2) only SALIENT
values are used (multi-word or capitalized proper nouns ≥5 chars — never ids, lat/lng,
urls, #hex, lowercase enum categories, or generic UI words); (3) if there are no seed
values or no page rendered any text, the check is SKIPPED (checked=False) so a legitimately
static app is never flagged. LOCAL-ONLY (agent/tests/ gitignored).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    salient_seed_values,
    real_data_verdict,
    extract_seed_display_values,
    _finalize_walkthrough,
    browser_report_unusable,
)

GMAPS_SEED = {
    "places": [
        {"id": 1, "name": "Pinecrest Diner", "category": "restaurant",
         "lat": 37.787004, "lng": -122.409993, "address": "401 Geary Street, San Francisco, CA",
         "website": "https://pinecrestdiner.com/", "phone": "(415) 885-6407", "rating": 4.2,
         "photo_url": "https://x/p.jpg", "price_level": 2},
        {"id": 16, "name": "The Little Chihuahua", "category": "restaurant",
         "lat": 37.76, "lng": -122.44, "address": "292 Divisadero St", "rating": 4.5},
    ],
    "reviews": [
        {"id": 1, "place_id": 15, "author": "Priya H.", "rating": 4,
         "text": "Consistently good.", "relative_time": "5 months ago"},
    ],
    "transit_stops": [
        {"id": 1, "name": "2nd & King", "lat": 37.77, "lng": -122.39,
         "mode": "tram", "network": "Muni", "line_refs": ["N", "T"]},
    ],
}


# ─────────────────────── salient_seed_values ───────────────────────

def test_salient_values_include_multiword_proper_names():
    vals = salient_seed_values(GMAPS_SEED)
    assert "Pinecrest Diner" in vals
    assert "The Little Chihuahua" in vals
    assert "Priya H." in vals
    assert "2nd & King" in vals


def test_salient_values_exclude_noise_columns_and_types():
    vals = salient_seed_values(GMAPS_SEED)
    joined = " || ".join(vals)
    # ids / numbers / coords / urls / phone / lowercase enum categories are NOT salient
    assert "37.787004" not in joined and "-122.409993" not in joined
    assert "https://pinecrestdiner.com/" not in joined
    assert "restaurant" not in vals  # lowercase single-word enum
    assert "tram" not in vals
    assert "1" not in vals and "16" not in vals


def test_salient_values_deduped_and_capped():
    big = {"places": [{"id": i, "name": f"Cafe Number {i}"} for i in range(200)]}
    vals = salient_seed_values(big, limit=40)
    assert len(vals) <= 40
    assert len(vals) == len(set(v.lower() for v in vals))


def test_salient_values_empty_on_junk():
    assert salient_seed_values({}) == []
    assert salient_seed_values({"t": "notalist"}) == []
    assert salient_seed_values({"t": [1, 2, 3]}) == []


def test_salient_values_diversify_across_columns():
    # a VERBOSE column (long templated descriptions) must not crowd out a compact but
    # highly-renderable column (place names) — names are the field a list/card most likely
    # shows, so at least one must survive into the capped salient set.
    rows = [{"name": f"Kabab House {i}",
             "description": f"A well-loved eatery number {i} serving classic dishes "
                            f"in a warm relaxed neighborhood setting for everyone."}
            for i in range(50)]
    vals = salient_seed_values({"places": rows}, limit=40)
    assert any(v.startswith("Kabab House") for v in vals), \
        "verbose description column crowded out every place name"


def test_name_column_keeps_row_order_so_first_rows_are_covered():
    # a default list/card renders the FIRST rows, not the longest-named ones. So the
    # name-like column must contribute its EARLY rows (not just its longest) to the salient
    # set — otherwise a compact name-only list of the first places matches nothing.
    rows = ([{"id": 1, "name": "Pier 3"}, {"id": 2, "name": "Al's"}]  # short, first, real
            + [{"id": i, "name": f"The Very Long Historical Society Museum Number {i}"}
               for i in range(3, 80)])
    vals = salient_seed_values({"places": rows}, limit=40)
    assert "Pier 3" in vals, f"first-row name dropped for longer later names: {vals[:5]}"


# ─────────────────────── real_data_verdict ───────────────────────

def test_verdict_rendered_when_any_seed_value_on_any_page():
    seed = ["Pinecrest Diner", "The Little Chihuahua", "2nd & King"]
    texts = ["Nearby\nSearch", "Results:\nThe Little Chihuahua ★4.5\nMexican"]
    v = real_data_verdict(texts, seed)
    assert v["checked"] is True
    assert v["rendered"] is True
    assert "The Little Chihuahua" in v["matched"]


def test_verdict_not_rendered_when_mock_text_has_no_seed_value():
    # run-3 shape: pages full of MOCK text, none of it a real seed value
    seed = ["Pinecrest Diner", "The Little Chihuahua", "2nd & King"]
    texts = ["Search\nHI Point Montara Lighthouse $165", "Map\nGolden Gate Hostel $99"]
    v = real_data_verdict(texts, seed)
    assert v["checked"] is True
    assert v["rendered"] is False
    assert v["matched"] == []


def test_verdict_skipped_when_no_seed_values():
    v = real_data_verdict(["anything at all"], [])
    assert v["checked"] is False


def test_verdict_skipped_when_no_page_text():
    v = real_data_verdict(["", "   "], ["Pinecrest Diner"])
    assert v["checked"] is False


def test_verdict_match_is_case_insensitive():
    v = real_data_verdict(["results: pinecrest diner"], ["Pinecrest Diner"])
    assert v["rendered"] is True


# ─────────────────── extract_seed_display_values (file IO, dual-source) ───────────────────

def _write_backend(tmp_path, dataset=None, lane=None):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    if dataset is not None:
        (be / "seed_dataset.json").write_text(json.dumps(dataset))
    if lane is not None:
        (be / "seed_data.json").write_text(json.dumps(lane))
    return tmp_path


def test_extract_reads_dataset_and_lane_seed(tmp_path):
    proj = _write_backend(tmp_path, dataset=GMAPS_SEED,
                          lane={"places": [{"id": 1, "name": "Lane Only Place"}]})
    vals = extract_seed_display_values(proj)
    assert "Pinecrest Diner" in vals       # from dataset
    assert "Lane Only Place" in vals        # from lane seed_data.json


def test_extract_missing_files_returns_empty(tmp_path):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    assert extract_seed_display_values(tmp_path) == []


# ─────────────────── _finalize_walkthrough rolls no_real_data ───────────────────

def test_finalize_flags_no_real_data_when_checked_and_not_rendered():
    report = {"ran": True, "pages": [{"name": "home", "blank": False}], "steps": [],
              "real_data": {"checked": True, "rendered": False, "matched": []}}
    out = _finalize_walkthrough(report)
    assert out["no_real_data"] is True


def test_finalize_no_flag_when_rendered():
    report = {"ran": True, "pages": [{"name": "home", "blank": False}], "steps": [],
              "real_data": {"checked": True, "rendered": True, "matched": ["Pinecrest Diner"]}}
    out = _finalize_walkthrough(report)
    assert out["no_real_data"] is False


def test_finalize_no_flag_when_skipped():
    report = {"ran": True, "pages": [], "steps": [],
              "real_data": {"checked": False, "rendered": False, "matched": []}}
    out = _finalize_walkthrough(report)
    assert out["no_real_data"] is False


def test_finalize_no_flag_when_no_real_data_key():
    # back-compat: a report that never ran the real-data check must not flag
    report = {"ran": True, "pages": [], "steps": []}
    out = _finalize_walkthrough(report)
    assert out.get("no_real_data") is False


# ─────────────────── browser_report_unusable holds delivery on no_real_data ───────────────────

def test_no_real_data_makes_report_unusable():
    # run-3 mock shape: auth works, pages non-blank, but no real data → HOLD delivery
    report = {"ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
              "hollow_frontend": False, "no_real_data": True}
    assert browser_report_unusable(report) is True


def test_rendered_real_data_report_not_unusable():
    report = {"ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
              "hollow_frontend": False, "no_real_data": False}
    assert browser_report_unusable(report) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
