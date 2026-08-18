r"""#933: a screen scored 0.00 five rounds running and nothing on disk could say why.

Every 0.0 this module produces is a JUDGE failure, and each path writes its cause as a deviation:
"judge returned no JSON", "judge JSON unparseable", "judge call failed: …", and #766's non-verdict.
#767 stamped `raw_judge_reply` onto the screen record for exactly this question and said why:

    "Only the raw text can say, and one round from now it will be gone."

It goes onto the screen record — which #500's merge discards whenever the screen COLLAPSED, which
is the only time anyone asks. #767's fix is defeated by the merge in precisely its own use case
(r150's 0.00 on a page that renders).

★ r154 is the live instance. `title_detail` scored 0.00 in rounds 2, 3, 4 and 5, across three
distinct code states, on a capture I opened: a complete working detail page — hero art,
"Disclosure Day", Play / + / like, 2026 · TV-14 · HD, synopsis, genre tag, Episodes with a Season 1
selector and an episode row. The reference is unmistakably the same screen (Netflix's "ALL
AMERICAN" modal). Round 1 scored that page 0.60. Nothing on disk says what the judge replied in
rounds 2–5, and the verdict shows 0.6 for it because the merge kept round 1.

`results` — the LIVE list — is already an argument to the ledger writer. Carry the reason there.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _write(tmp_path, results, verdict=None):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True, exist_ok=True)
    vf._append_round_record_640(vdir, verdict or {"code_state": "abc"}, results)
    return [json.loads(l) for l in (vdir / "rounds.jsonl").read_text().splitlines() if l.strip()]


def _zero(tmp_path, results):
    return _write(tmp_path, results)[-1].get("zero_reasons_933") or {}


# --------------------------------------------------------------------------- the reason survives

def test_a_judge_failure_reaches_the_ledger(tmp_path):
    """★ r154's title_detail, with the deviation the judge path actually writes."""
    z = _zero(tmp_path, [{"name": "title_detail", "similarity": 0.0, "judge_error": True,
                          "deviations": ["judge returned no JSON"],
                          "raw_judge_reply": "<html>502 Bad Gateway</html>"}])
    assert z["title_detail"]["why"] == "judge returned no JSON"
    assert z["title_detail"]["judge_error"] is True
    assert "502" in z["title_detail"]["raw_judge_reply"]


def test_a_non_verdict_is_distinguishable_from_a_considered_zero(tmp_path):
    """#766's whole point: a reply with no similarity and no dimensions is a NON-verdict, not a
    0.0. The ledger has to keep them apart a round later."""
    z = _zero(tmp_path, [
        {"name": "a", "similarity": 0.0, "judge_error": True,
         "deviations": ["judge returned JSON with no similarity and no dimensions — "
                        "a NON-VERDICT, not a 0.0 (#766)"]},
        {"name": "b", "similarity": 0.0,
         "deviations": ["the page renders a login form instead of the catalogue"]}])
    assert z["a"]["judge_error"] is True and "NON-VERDICT" in z["a"]["why"]
    assert z["b"]["judge_error"] is False and "login form" in z["b"]["why"]


def test_a_blank_capture_says_blank(tmp_path):
    z = _zero(tmp_path, [{"name": "player", "similarity": 0.0, "blank": True,
                          "deviations": ["capture was blank"]}])
    assert z["player"]["blank"] is True


def test_a_missing_capture_says_so(tmp_path):
    z = _zero(tmp_path, [{"name": "shows", "similarity": 0.0, "capture_missing": True,
                          "deviations": []}])
    assert z["shows"]["capture_missing"] is True and z["shows"]["why"] is None


def test_an_earlier_rounds_reason_is_not_erased(tmp_path):
    """The point of using the append-only file: round 5 recovering must not delete round 2."""
    _write(tmp_path, [{"name": "title_detail", "similarity": 0.0,
                       "deviations": ["judge call failed: TimeoutError"]}])
    rows = _write(tmp_path, [{"name": "title_detail", "similarity": 0.62, "deviations": []}])
    assert rows[0]["zero_reasons_933"]["title_detail"]["why"].startswith("judge call failed")
    assert "zero_reasons_933" not in rows[1]


# --------------------------------------------------------------------------- it stays quiet

def test_a_scoring_screen_is_not_recorded(tmp_path):
    assert _zero(tmp_path, [{"name": "landing", "similarity": 0.72,
                             "deviations": ["title is too small"]}]) == {}


def test_a_low_but_nonzero_score_is_not_a_judge_failure(tmp_path):
    """0.05 is a verdict, however bad. Only exact 0.0 is what the failure paths return, so the
    rule needs no threshold — and a threshold would quietly reclassify real low scores."""
    assert _zero(tmp_path, [{"name": "movies", "similarity": 0.05,
                             "deviations": ["photographed the login page"]}]) == {}


def test_a_clean_round_adds_no_key(tmp_path):
    row = _write(tmp_path, [{"name": "landing", "similarity": 0.72}])[-1]
    assert "zero_reasons_933" not in row


def test_the_existing_columns_are_untouched(tmp_path):
    row = _write(tmp_path, [{"name": "a", "similarity": 0.0, "deviations": ["x"]}],
                 {"code_state": "abc", "blocking_average": 0.5,
                  "blocking_average_live": 0.4, "passed": False})[-1]
    assert row["live"] == {"a": 0.0} and row["blocking_average"] == 0.5
    assert row["blocking_average_live"] == 0.4 and row["code_state"] == "abc"


def test_a_malformed_result_does_not_break_the_ledger(tmp_path):
    rows = _write(tmp_path, ["not a dict", {"similarity": 0.0},
                             {"name": "ok", "similarity": 0.0, "deviations": ["why"]}])
    assert rows[-1]["zero_reasons_933"] == {
        "ok": {"why": "why", "judge_error": False, "blank": None,
               "capture_missing": None, "raw_judge_reply": None}}


def test_a_non_numeric_similarity_is_skipped_not_counted_as_zero(tmp_path):
    """★ `float(None or 0.0)` is 0.0 — a screen with NO score would otherwise be filed as a judge
    failure. The guard must reject the value, not coerce it."""
    assert _zero(tmp_path, [{"name": "x", "similarity": "n/a", "deviations": ["d"]}]) == {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
