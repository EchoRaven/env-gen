r"""#819: the widest silent skip on the design-prep path, and the last one uninstrumented.

Three items chased where the enrichment vanished — the per-screen call (#813), the per-component
join (#815), the truncated input (#816) — and a fourth eliminated the reply budget. This is the
one above all of them:

    try:
        enriched = await _run_analyst(...)
    except Exception:
        enriched = None
    ds = _merge_enrichment(skeleton, enriched) if enriched else skeleton

**Any** exception anywhere in `_run_analyst` discards the enrichment for **every screen at once**.
That matches the corpus signature better than per-screen failure does: `build_notes` lands 1 time
in 4,006 components across 12 runs — essentially never, rather than sometimes.

"Best-effort, the skeleton still ships" is the right behaviour and is kept: the measured facts
(colors, crops, geometry) are worth more than nothing, and design-prep runs before every lane.
The defect was that it shipped **without a word**, while the frontend prompt kept telling every
lane to read fields that were therefore empty.

Two failure modes, reported separately — the call THREW, versus the call RETURNED nothing. Firing
both for one event would be #815's misdiagnosis, in the same file on the same day.
"""
import asyncio
import logging
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


_SKEL = {"design_system": {}, "assets": [],
         "screens": [{"name": "login", "components": [{"id": "a"}]}]}


class _Boom:
    def __getattr__(self, n):
        raise RuntimeError("no LLM here")


def _run(llm):
    with tempfile.TemporaryDirectory() as d:
        return asyncio.new_event_loop().run_until_complete(
            dp.enrich_design_system(dict(_SKEL), {}, d, llm)), d


def test_a_wholesale_failure_is_announced(caplog):
    with caplog.at_level(logging.WARNING):
        _run(_Boom())
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "FAILED WHOLESALE" in msg
    assert "NO component in this run" in msg


def test_it_says_what_still_ships():
    """'Everything is broken' would be false and would get the warning ignored: the measured
    facts do ship, and they are most of the file."""
    import inspect
    assert "The measured facts (colors, crops, geometry) still ship" in \
        inspect.getsource(dp.enrich_design_system)


def test_the_skeleton_is_still_written(caplog):
    """The behaviour is deliberately unchanged — design-prep runs before every lane."""
    import pathlib
    with caplog.at_level(logging.WARNING):
        with tempfile.TemporaryDirectory() as d:
            out = asyncio.new_event_loop().run_until_complete(
                dp.enrich_design_system(dict(_SKEL), {}, d, _Boom()))
            written = sorted(p.name for p in (pathlib.Path(d) / "design").glob("*"))
    assert out.get("screens")
    assert "design_system.json" in written and "design_system.md" in written


def test_an_empty_return_reports_differently(caplog, monkeypatch):
    """'It threw' and 'it returned nothing' need different fixes."""
    async def _empty(*a, **k):
        return None
    monkeypatch.setattr(dp, "_run_analyst", _empty)
    with caplog.at_level(logging.WARNING):
        _run(_Boom())
    msgs = [r.getMessage() for r in caplog.records]
    assert any("produced NO enrichment" in m for m in msgs)
    assert not any("FAILED WHOLESALE" in m for m in msgs)


def test_one_event_is_not_reported_as_two(caplog):
    """#815's misdiagnosis, avoided here: a throw must not also trip the empty-return warning."""
    with caplog.at_level(logging.WARNING):
        _run(_Boom())
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("FAILED WHOLESALE" in m for m in msgs) == 1
    assert not any("produced NO enrichment" in m for m in msgs)


def test_a_successful_pass_is_silent(caplog, monkeypatch):
    """Non-vacuity: a healthy run must add no noise, or the warning becomes decoration (#793)."""
    async def _ok(*a, **k):
        return {"screens": [{"name": "login",
                             "components": [{"id": "a", "build_notes": "n"}]}]}
    monkeypatch.setattr(dp, "_run_analyst", _ok)
    with caplog.at_level(logging.WARNING):
        out, _ = _run(_Boom())
    assert out["screens"][0]["components"][0].get("build_notes") == "n"
    assert not [r for r in caplog.records if "design-prep analyst" in r.getMessage()]


def test_it_never_raises():
    """It runs before every lane; an exception here costs the whole visual pipeline."""
    _run(_Boom())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
