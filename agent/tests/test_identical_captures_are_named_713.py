r"""#713: four screens scored 0.03-0.08 because they all photographed the landing page.

r147 is the worked example and it cost 0.26 of live fidelity in a single round, invisibly.

Its final round renamed four routes in `App.jsx` — `/new-and-popular` → `/new`, `/genre/:id` →
`/browse/genre/:genreId`, `/browse-by-languages` → `/browse/languages`, plus a new
`/watch/:titleId`. The capture still navigated to the OLD paths, React Router matched nothing,
and every one of them fell through to the landing page:

    browse_by_languages.png, genre_category.png, new_and_popular.png, player.png
    and landing.png are ONE file — md5 02a3e3577bf5

    browse_by_languages 0.45 -> 0.05        new_and_popular      -> 0.05
    genre_category      0.60 -> 0.08        player          0.55 -> 0.03
    blocking_average_live 0.6400 -> 0.3817, while #500's best-of merge ROSE 0.688 -> 0.70

So the run shipped its worst capture while the recorded number climbed. #641/#698 flagged the
symptom — delta 0.2583, the largest in the corpus — but nothing named the CAUSE, and from a score
alone a fell-through capture is indistinguishable from a page that is merely bad.

Byte-identical captures are the cheap tell: two distinct screens cannot legitimately produce the
same PNG. Hashing what is already on disk costs one read per screen. Run against r147's real
captures the detector fires once and names all five.
"""
import hashlib
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#713: TWO SCREENS THAT CAPTURED THE SAME IMAGE")
    return src[i:src.index('(vdir / "verdict.json").write_text', i)]


# --- the rule, on the shape r147 actually produced -------------------------------------------

def _detect(files: dict) -> list:
    """Mirror of the production grouping."""
    by = {}
    for name, data in files.items():
        by.setdefault(hashlib.md5(data).hexdigest(), []).append(name)
    return [sorted(v) for v in by.values() if len(v) > 1]


def test_it_finds_the_r147_group():
    same = b"LANDING-PNG-BYTES"
    out = _detect({
        "browse_by_languages": same, "genre_category": same, "new_and_popular": same,
        "player": same, "landing": same,
        "browse_home": b"A", "movies": b"B", "login": b"C",
    })
    assert out == [["browse_by_languages", "genre_category", "landing",
                    "new_and_popular", "player"]]


def test_distinct_screens_are_silent():
    assert _detect({"a": b"1", "b": b"2", "c": b"3"}) == []


def test_a_single_screen_is_not_a_group():
    assert _detect({"only": b"1"}) == []


def test_two_is_enough_to_report():
    assert _detect({"a": b"same", "b": b"same"}) == [["a", "b"]]


# --- the production block ------------------------------------------------------------------------

def test_it_hashes_the_capture_on_disk():
    b = _block()
    assert 'vdir / f"{_n713}.png"' in b
    assert "md5(" in b


def test_it_skips_a_screen_with_no_capture():
    assert "_f713.is_file()" in _block()


def test_it_only_reports_collisions():
    assert "if len(_names713) < 2:" in _block()


def test_it_warns_and_records_on_the_verdict():
    b = _block()
    assert "_LOG.warning(" in b
    assert 'setdefault("identical_captures_713"' in b


def test_the_message_names_the_cause_not_just_the_symptom():
    b = " ".join(_block().split())
    assert "their routes did not resolve" in b
    assert "fell through to a common page" in b


def test_the_message_says_the_scores_are_meaningless():
    # "measures", not "measure": the production sentence is grammatical and the assertion
    # follows it, rather than the code being bent to match a typo in a test.
    # Strip the comment markers first: the sentence wraps, so the joined source reads
    # "not those # screens" — the same fold every other provenance check here does.
    b = " ".join(_block().replace("#", " ").split())
    assert "measures that page, not those screens" in b


def test_the_wrong_trigger_is_marked_wrong():
    """The first draft blamed a stale capture list. known_routes is re-parsed from App.jsx on
    every call, so it is never stale — the claim is struck through rather than deleted."""
    b = " ".join(_block().replace("#", " ").split())
    assert "is WRONG and was checked" in b
    assert "re-parsed out of App.jsx on every call" in b


def test_it_points_at_what_is_actually_proven():
    b = " ".join(_block().replace("#", " ").split())
    assert "comes from SOURCE while the browser hits the SERVED app" in b
    assert "is not decided here" in b


def test_it_cannot_break_the_verdict_write():
    b = _block()
    assert "except Exception:" in b and "pass" in b


def test_the_verdict_is_still_written():
    src = inspect.getsource(vf)
    assert '(vdir / "verdict.json").write_text' in src


# --- provenance -----------------------------------------------------------------------------------

def test_the_r147_evidence_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "md5 02a3e3577bf5" in b
    assert "0.6400 -> 0.3817" in b


def test_the_masking_by_the_merge_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "500's merge ROSE 0.688 -> 0.70" in b


def test_it_credits_what_already_caught_the_symptom():
    b = " ".join(_block().replace("#", " ").split())
    assert "641/ 698 flagged the symptom" in b or "641/#698 flagged the symptom" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
