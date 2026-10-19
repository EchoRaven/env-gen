r"""#887: an unreadable served-build stamp read as "the build is fresh".

Triage of the 18 silent empty-default handlers #884 left in the three files #883's scanner does
not cover. Classified by what the CONSUMER does with the empty value:

| | |
|---|---|
| cosmetic / optional | `_pid` (profile-select JS), `_rhythm` (a repair-text fragment), `_head_sha`, `_pk`, `_this_live` (stamps) |
| degrades a comparison | `_url_before` (navigation-change detection), `token2` (a second-token check) |
| costs tokens, not correctness | `_ck` — a failed cache key means the verdict cache is skipped and the screen is re-judged |
| conservative direction | `commits = 0` (less progress → stall handling fires), `framework_validation`'s signature reads |
| **false all-clear** | **`_prev738`** ← this |

★ Same shape as #884, one function away in the same file. `_sf738.exists()` already separates
"first round, no prior" — which `_served_build_is_stale_738`'s docstring calls a legitimate
never-stale state — from "the file is there and will not parse". The handler collapsed them back.

The probe returns `False` on an empty `prev` (`if not (_pc and _pb): return False`), so an
unreadable `served_build.json` reads as **NOT STALE** — a false all-clear on the one probe that
exists because, in its own words, *"#715 cannot see this case: the routes are unchanged, so it
reports the build clean"*. That is the mechanism recorded as letting r148 release v1.0.0 with the
SPA throwing on every route.

The permissive default stays — a corrupt stamp must not block a capture. What it must not be is
indistinguishable from round one.
"""
import asyncio
import inspect
import json
import pathlib
import tempfile
import types
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _span():
    src = inspect.getsource(vf)
    start = src.index("#887: same shape as #884")
    end = src.index("_served_build_is_stale_738(_prev738", start)
    return src[start:end]


def test_the_site_is_findable():
    """Non-vacuity."""
    assert "#887: same shape as #884" in inspect.getsource(vf)


def test_it_announces_with_the_module_s_logger():
    """`logger` does not exist in this module — #884's fix had that bug and it would have turned
    an unreadable stamp into a crashed capture."""
    span = _span()
    assert "_LOG.error" in span
    assert "logger.error" not in span.replace("_LOG.error", "")
    assert isinstance(vf._LOG, logging.Logger)


def test_it_names_the_blind_spot_it_restores():
    span = _span()
    assert "#738" in span and "#715" in span
    assert "DISABLED" in span


def test_it_says_it_once():
    src = inspect.getsource(vf)
    assert src.count("_said_sb_887") >= 2


def test_the_permissive_default_survives():
    span = _span()
    assert "_prev738 = {}" in span
    assert "raise" not in span


def test_the_first_round_stays_silent():
    """★ The distinction the handler was collapsing: `exists()` above means no-file never reaches
    the warning. Round one has no prior and is legitimately never stale."""
    src = inspect.getsource(vf)
    i = src.index("#887: same shape as #884")
    before = src[src.rindex("try:", 0, i):i]
    assert "_sf738.exists()" in before


def test_the_probe_still_treats_an_empty_prior_as_not_stale():
    """Unchanged behaviour — the ticket adds a voice, not a verdict."""
    assert vf._served_build_is_stale_738({}, "abc123", "main-x.js") is False
    assert vf._served_build_is_stale_738(None, "abc123", "main-x.js") is False


def test_the_probe_still_detects_a_real_stale_build():
    """Non-vacuity for the thing being protected."""
    prev = {"frontend_commit": "old", "bundle": "main-x.js"}
    assert vf._served_build_is_stale_738(prev, "new", "main-x.js") is True
    assert vf._served_build_is_stale_738(prev, "old", "main-x.js") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the announcement, DRIVEN -----------------------------------------------------------
#
# Every assertion above reads the SOURCE, and the two mutations that work on every member of the
# "fail open + say once" family walked through here too: making the `_LOG.error` unreachable, and
# inverting the say-once latch so the FIRST unreadable stamp is suppressed and nothing else ever
# sets the flag. `src.count("_said_sb_887") >= 2` holds either way, because the flag is written
# once and read once. Only the permissive default had a driver. Same in #882, #884 and #888.
#
# No docker and no extraction needed: the probe's one hard requirement is a container id, and
# `_container_id_936` is a module function.


def _clear_887():
    vf.__dict__.pop("_said_sb_887", None)


def _drive_887(stamp_bytes, monkeypatch):
    """Run one visual round with `served_build.json` holding `stamp_bytes`.

    Returns the error records the module logger received.
    """
    _clear_887()
    errors = []
    monkeypatch.setattr(vf, "_LOG", types.SimpleNamespace(
        error=lambda *a, **k: errors.append((a[0] % a[1:]) if len(a) > 1 else str(a[0])),
        warning=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None))
    monkeypatch.setattr(vf, "_container_id_936", lambda *a, **k: "deadbeefcafe")

    d = pathlib.Path(tempfile.mkdtemp())
    (d / "app" / "frontend" / "src").mkdir(parents=True)
    (d / "app" / "frontend" / "src" / "App.jsx").write_text(
        '<Route path="/a" element={<div/>} />', encoding="utf-8")
    (d / "docker").mkdir()
    (d / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    vg = d / "design" / "visual_gate"
    vg.mkdir(parents=True)
    if stamp_bytes is not None:
        (vg / "served_build.json").write_bytes(stamp_bytes)
    ref = d / "a.png"
    ref.write_bytes(b"\x89PNG\r\n")

    async def _capture(screens):
        out = {}
        for s in screens:
            p = d / ("shot_%s.png" % s["name"])
            p.write_bytes(b"\x89PNG\r\n" + s["name"].encode())
            out[s["name"]] = str(p)
        return out

    async def _judge(llm, screen, shot):
        return {"similarity": 0.9, "dimensions": {}, "deviations": [], "fixes": [],
                "summary": "ok", "empty_state": False}

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(vf.run_visual_fidelity(
            d, [str(ref)], llm=object(), capture_fn=_capture, judge_fn=_judge))
    finally:
        loop.close()
        _clear_887()
    return errors


def test_an_unreadable_stamp_really_announces(monkeypatch):
    errors = _drive_887(b"{ not json", monkeypatch)
    assert len(errors) == 1, "an unreadable served-build stamp was silent"
    assert "SERVED-BUILD STAMP UNREADABLE" in errors[0]


def test_the_announcement_names_the_consequence_and_the_fault(monkeypatch):
    msg = _drive_887(b"{ not json", monkeypatch)[0]
    assert "stale-bundle" in msg and "DISABLED" in msg
    assert "report the build clean" in msg, (
        "the direction of the failure must be named: it reads CLEAN, which is the blind spot")
    assert "JSONDecodeError" in msg or "ValueError" in msg, msg


def test_a_readable_stamp_announces_nothing(monkeypatch):
    """Non-vacuity: a normal round must stay quiet, or the test above proves nothing."""
    good = json.dumps({"frontend_commit": "abc", "bundle": "main.js"}).encode()
    assert _drive_887(good, monkeypatch) == []


def test_a_MISSING_stamp_announces_nothing(monkeypatch):
    """The distinction this ticket rests on: "first round, no prior" is a legitimate
    never-stale state and must NOT be reported as unreadable."""
    assert _drive_887(None, monkeypatch) == []


def test_it_really_says_it_once(monkeypatch):
    """The flag is module-global, which is what makes the inverted-latch mutation invisible to
    a source count — so say-once has to be driven, not spelled."""
    _clear_887()
    errors = []
    monkeypatch.setattr(vf, "_LOG", types.SimpleNamespace(
        error=lambda *a, **k: errors.append(str(a[0])), warning=lambda *a, **k: None,
        info=lambda *a, **k: None, debug=lambda *a, **k: None))
    monkeypatch.setattr(vf, "_container_id_936", lambda *a, **k: "deadbeefcafe")
    try:
        for _ in range(3):
            d = pathlib.Path(tempfile.mkdtemp())
            (d / "app" / "frontend" / "src").mkdir(parents=True)
            (d / "app" / "frontend" / "src" / "App.jsx").write_text(
                '<Route path="/a" element={<div/>} />', encoding="utf-8")
            (d / "docker").mkdir()
            (d / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
            vg = d / "design" / "visual_gate"
            vg.mkdir(parents=True)
            (vg / "served_build.json").write_bytes(b"{ not json")
            ref = d / "a.png"
            ref.write_bytes(b"\x89PNG\r\n")

            async def _capture(screens, _d=d):
                out = {}
                for s in screens:
                    p = _d / ("shot_%s.png" % s["name"])
                    p.write_bytes(b"\x89PNG\r\n" + s["name"].encode())
                    out[s["name"]] = str(p)
                return out

            async def _judge(llm, screen, shot):
                return {"similarity": 0.9, "dimensions": {}, "deviations": [], "fixes": [],
                        "summary": "ok", "empty_state": False}

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(vf.run_visual_fidelity(
                    d, [str(ref)], llm=object(), capture_fn=_capture, judge_fn=_judge))
            finally:
                loop.close()
        assert len(errors) == 1, "announced %d times" % len(errors)
        assert vf.__dict__.get("_said_sb_887") is True
    finally:
        _clear_887()
