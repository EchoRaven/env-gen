r"""#791: a blocker scan that throws must not ERASE the blockers it already found.

Continuing #790's sweep into the files that FEED the delivery gate. `validation_runner.py` came
back clean (0 permissive silent defaults). `framework_validation.py`'s three return `False` for
"no progress detected", which is the strict answer, not the permissive one. `frontend_audit.py`
had the real ones — and they are a worse shape than #790's:

    blockers: List[str] = []
    try:
        ...            # blockers.append(...) as real defects are found
    except Exception:
        return []      # <- not a default. The findings already made are DESTROYED.

An exception on file 6 discarded five genuine blockers from files 1-5, and all three of these feed
`deliverability.py` — the release-BLOCKING path — which then read the run as clean.

This is not "falling back to a permissive default" (#790, where the default was at least the
honest empty answer for a check that never ran). It is **evidence destruction**, the same shape as
#737's blank capture erasing the record.

The fix returns the partial findings and announces the truncation, because a partial scan is not
a clean one. Two sites qualified; a third handler in `invented_field_fallback_blockers` was left
alone because `blockers` does not exist at that point — nothing had been found yet, so `[]` is
honest there. Distinguishing those two cases is the whole point (item 110: shape is not
consequence).
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


@pytest.fixture(autouse=True)
def _clean():
    fa.reset_scan_errors_791()
    yield
    fa.reset_scan_errors_791()


def test_a_healthy_scan_records_nothing():
    """Non-vacuity: silent when everything works, or it is noise and gets ignored — how #788
    happened."""
    assert fa.scan_errors_791() == []


def _two_file_frontend(tmp_path):
    """Two files that each contain a bare authed fetch — real findings, real scan."""
    src = tmp_path / "src"
    src.mkdir()
    for n in ("A", "B"):
        (src / f"{n}.jsx").write_text(
            "export default function %s(){ fetch('/api/things').then(r=>r.json()); }\n" % n,
            encoding="utf-8")
    return src


def test_the_scan_really_finds_things_first(tmp_path):
    """Non-vacuity for the test below: without an injected fault, both files are flagged."""
    found = fa.bare_authed_fetch_blockers(_two_file_frontend(tmp_path))
    assert len(found) >= 2, found


def test_partial_findings_survive_a_throw(tmp_path, caplog):
    """The core of it: findings made before the fault must come back, not be discarded.

    The fault is injected where a real one would land — inside the per-file match loop, after the
    first file has already produced a blocker."""
    real = fa._BARE_FETCH_RE

    class _FlakyRe:
        def __init__(self):
            self.calls = 0

        def finditer(self, text):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("scan blew up on the second file")
            return real.finditer(text)

    fa._BARE_FETCH_RE = _FlakyRe()
    try:
        with caplog.at_level(logging.WARNING):
            got = fa.bare_authed_fetch_blockers(_two_file_frontend(tmp_path))
    finally:
        fa._BARE_FETCH_RE = real

    assert got, "the findings from file 1 were destroyed — this is the #791 defect"
    assert any("BLOCKER SCAN TRUNCATED" in r.getMessage() for r in caplog.records)
    assert fa.scan_errors_791() and "kept 1 finding(s)" in fa.scan_errors_791()[0]


def test_the_warning_says_absence_is_not_evidence(caplog):
    with caplog.at_level(logging.WARNING):
        fa._scan_truncated_791("demo_scan", RuntimeError("boom"), 2)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "BLOCKER SCAN TRUNCATED" in msg
    assert "not evidence there are none" in msg


def test_it_is_recorded_once_not_per_file(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            fa._scan_truncated_791("demo_scan", RuntimeError("boom"), 1)
    assert len(fa.scan_errors_791()) == 1


def test_the_reporter_cannot_break_the_audit():
    class _Unprintable(Exception):
        def __str__(self):
            raise ValueError("even the message explodes")
    fa._scan_truncated_791("x", _Unprintable(), 0)          # must not raise


# --- the wiring ---------------------------------------------------------------------------------

def test_both_evidence_erasing_sites_were_converted():
    import inspect
    src = inspect.getsource(fa)
    for fn in ("routed_fallback_page_blockers", "bare_authed_fetch_blockers"):
        assert f'_scan_truncated_791("{fn}"' in src, fn


def test_neither_returns_the_empty_list_from_its_handler():
    """The defect was literally `return []` where `blockers` was in scope and non-empty."""
    import inspect
    for fn in (fa.routed_fallback_page_blockers, fa.bare_authed_fetch_blockers):
        body = inspect.getsource(fn)
        i = body.rindex("except Exception")
        assert "return blockers" in body[i:], fn.__name__
        assert "return []" not in body[i:], fn.__name__


def test_the_site_with_nothing_to_keep_was_left_alone():
    """In `invented_field_fallback_blockers` the guarded handler runs before `blockers` exists —
    `[]` is the honest answer there, and wrapping it would be cargo-culting the pattern."""
    import inspect
    src = inspect.getsource(fa.invented_field_fallback_blockers)
    assert "_scan_truncated_791" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
