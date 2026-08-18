r"""#937: a plateau where the pixels never changed looked exactly like one where they did.

r154 sat at a flat live 0.5655 for rounds 4–12, across five distinct `code_state`s. Working out
why cost three detours:

  * md5-ing `design/visual_gate/history/` — which only exists because #141b caps it at 500 files
    and would have been useless on a longer run;
  * counting build events in `podman images` to REFUTE a stale bundle (20 frontend rebuilds during
    the run, so the container was being restaged all along);
  * `git log` on the component `App.jsx` actually routes to — `components/LoginPage.jsx`, edited
    TWICE in 148 minutes, the second time by 24 bytes.

    login 1 distinct image across 12 captures · landing 2 · games 2 · browse_home 3 · movies 3

The number that would have started that investigation is one #142 already computes — it keys its
verdict cache on `(screen, capture md5)` precisely because identical pixels must produce an
identical verdict — and then drops. A plateau with IDENTICAL pixels is a different defect from a
plateau where the pixels move and the score does not, and the ledger could not tell them apart.
"""
import hashlib
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _row(tmp_path, results, verdict=None):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True, exist_ok=True)
    vf._append_round_record_640(vdir, verdict or {"code_state": "abc"}, results)
    return [json.loads(l) for l in (vdir / "rounds.jsonl").read_text().splitlines() if l.strip()]


def _shot(tmp_path, name, payload):
    p = tmp_path / f"{name}.png"
    p.write_bytes(payload)
    return {"name": name, "similarity": 0.5, "screenshot": str(p)}


def test_the_fingerprint_is_recorded(tmp_path):
    rows = _row(tmp_path, [_shot(tmp_path, "login", b"pixels")])
    assert rows[-1]["capture_md5_937"]["login"] == hashlib.md5(b"pixels").hexdigest()[:12]


def test_an_unchanged_screen_is_visible_across_rounds(tmp_path):
    """★ r154's login: same bytes, round after round, while the code_state moves."""
    s = _shot(tmp_path, "login", b"same")
    _row(tmp_path, [s], {"code_state": "aaa"})
    _row(tmp_path, [s], {"code_state": "bbb"})
    rows = _row(tmp_path, [s], {"code_state": "ccc"})
    fps = {r["capture_md5_937"]["login"] for r in rows}
    states = {r["code_state"] for r in rows}
    assert len(fps) == 1 and len(states) == 3, (fps, states)


def test_a_changed_screen_shows_a_new_fingerprint(tmp_path):
    _row(tmp_path, [_shot(tmp_path, "landing", b"v1")])
    rows = _row(tmp_path, [_shot(tmp_path, "landing", b"v2")])
    assert rows[0]["capture_md5_937"]["landing"] != rows[1]["capture_md5_937"]["landing"]


def test_a_screen_with_no_capture_is_absent_not_blank(tmp_path):
    """A missing capture has no fingerprint; recording "" would make it look like a real image
    that happens to hash to nothing (#907: an empty container is not a fact)."""
    rows = _row(tmp_path, [{"name": "title_detail", "similarity": 0.0, "screenshot": None},
                           _shot(tmp_path, "landing", b"x")])
    assert set(rows[-1]["capture_md5_937"]) == {"landing"}


def test_a_vanished_file_does_not_break_the_row(tmp_path):
    r = _shot(tmp_path, "gone", b"x")
    (tmp_path / "gone.png").unlink()
    rows = _row(tmp_path, [r, _shot(tmp_path, "here", b"y")])
    assert set(rows[-1]["capture_md5_937"]) == {"here"}


def test_no_captures_adds_no_key(tmp_path):
    rows = _row(tmp_path, [{"name": "x", "similarity": 0.4}])
    assert "capture_md5_937" not in rows[-1]


def test_the_existing_columns_are_untouched(tmp_path):
    rows = _row(tmp_path, [_shot(tmp_path, "a", b"z")],
                {"code_state": "sha", "blocking_average": 0.5, "blocking_average_live": 0.4})
    r = rows[-1]
    assert r["code_state"] == "sha" and r["blocking_average"] == 0.5
    assert r["live"] == {"a": 0.5} and r["at"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
