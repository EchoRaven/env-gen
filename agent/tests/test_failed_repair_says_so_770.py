r"""#770: a source-mutating repair failed silently, then the gate reported its symptom.

Two auto-repairs in `deliverability` were wrapped in `except Exception: pass`, with the very next
statement being the blocker check the repair exists to clear:

    inject_auth_fetch_wrapper(_fe)          ->  bare_authed_fetch_blockers(...)
    repair_fabricated_fallbacks(_fsrc)      ->  invented_field_fallback_blockers(...)

So a throw meant the gate blocked and nothing said the framework had already tried and could not.
The lane is then handed a blocker it cannot reconcile with the code in front of it — the repair
was supposed to have fixed exactly that.

#769's class one layer up, and the fourth this session (#748 compose, #740 console, #769 capture,
this). The rule that came out of #769 — **an `except` that neither re-raises nor logs is a
decision to never find out** — is what found it, applied deliberately instead of waiting to be
bitten again.

**Scope, measured before acting.** The codebase has 2022 `except` clauses and 582 (28%) whose
body is only `pass`/`continue`. Fixing all of them would be wrong: "best-effort, never raises" is
the deliberate style for scaffolding. The discriminator that makes these two different is that
the swallowed failure becomes a GATE INPUT. Applied to the scoring module, the same filter found
13 candidates and hand-reading cleared every one — the blank probe falls back to "not blank"
(`never false-skip`, documented) and the image cache falls back to the original. No fourth
instance there.
"""
import inspect
import tempfile
import types
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa1203pg


def _src() -> str:
    return inspect.getsource(dl)


# --- both sites report -------------------------------------------------------------------------

@pytest.mark.parametrize("repair", ["inject_auth_fetch_wrapper", "repair_fabricated_fallbacks"])
def test_the_repair_is_named_when_it_fails(repair):
    assert f"#770 auto-repair {repair} failed" in _src()


def test_the_exception_type_is_reported():
    s = _src()
    assert s.count("type(_rep770).__name__") == 2


def test_the_message_is_bounded():
    assert _src().count("str(_rep770)[:160]") == 2


def test_it_warns_the_blocker_may_be_a_consequence():
    """The point: the blocker printed a line later is the SYMPTOM, and dispatching a lane at it
    is the wasted round this prevents."""
    import re
    flat = re.sub(r'"\s*\n\s*"', "", _src())
    assert flat.count("read it as a CONSEQUENCE before dispatching a lane at it") == 2


def test_neither_site_raises():
    """A failed repair must still not break the gate — it reports and continues."""
    s = _src()
    for i in [m.start() for m in __import__("re").finditer(r"except Exception as _rep770:", s)]:
        blk = s[i:s.index("return", i)]
        assert "raise" not in blk


def test_the_blocker_check_still_runs_after_the_failure():
    # Anchored on the `return` that ends each handler, not a character count — the eighth
    # catch by the fixed-width-source-window guard this session, and the window would stop
    # covering the statement the moment the comment above it grew.
    s = _src()
    i = s.index("#770 auto-repair inject_auth_fetch_wrapper failed")
    assert "bare_authed_fetch_blockers" in s[i:s.index("return", i) + 60]
    j = s.index("#770 auto-repair repair_fabricated_fallbacks failed")
    assert "invented_field_fallback_blockers" in s[j:s.index("return", j) + 60]


# --- provenance ------------------------------------------------------------------------------------

def test_the_rule_that_found_it_is_recorded():
    s = " ".join(_src().replace("#", " ").split())
    assert "769's class one layer up" in s or "769's" in s
    assert "the reason was caught and dropped at the" in s


def test_it_records_that_the_lane_cannot_reconcile_it():
    s = " ".join(_src().replace("#", " ").split())
    assert "a blocker it cannot reconcile with the code in front of it" in s


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the announcement, DRIVEN at both sites --------------------------------------------
#
# Every assertion above is a COUNT of a substring, and all three mutations went through -- even
# the one written as a control:
#
#   * each site's `_LOG_700.warning` made unreachable: both substrings are still there, twice,
#     so every count holds while a failed repair is silent again and the very next line reports
#     the blocker the repair exists to clear. That is the whole defect.
#   * site 1 returning `[]` after a failed repair instead of running the check: a repair failure
#     would read as "no blockers", which is worse than reporting the consequence. The file
#     asserts `bare_authed_fetch_blockers` appears just after the handler -- it still does.
#
# Both sites are small module-level functions taking only `app_root`, and both repairs are
# imported from `frontend_audit` INSIDE them, so the raise can be injected there.

_SITES_1203PG = (
    ("inject_auth_fetch_wrapper", "_bare_fetch_blockers", "bare_authed_fetch_blockers"),
    ("repair_fabricated_fallbacks", "_invented_field_blockers",
     "invented_field_fallback_blockers"),
)


def _drive_770(repair, entry, monkeypatch):
    """Make `repair` raise, run `entry`, and return (warnings, result)."""
    warnings = []
    monkeypatch.setattr(dl, "_LOG_700", types.SimpleNamespace(
        warning=lambda *a, **k: warnings.append((a[0] % a[1:]) if len(a) > 1 else str(a[0])),
        error=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None))

    def _boom(*a, **k):
        raise RuntimeError("the repair could not write")

    monkeypatch.setattr(fa1203pg, repair, _boom)
    d = Path(tempfile.mkdtemp())
    (d / "frontend" / "src").mkdir(parents=True)
    (d / "frontend" / "src" / "App.jsx").write_text("export default function App(){}",
                                                    encoding="utf-8")
    return warnings, getattr(dl, entry)(d)


@pytest.mark.parametrize("repair,entry,check", _SITES_1203PG)
def test_a_failed_repair_really_announces(repair, entry, check, monkeypatch):
    warnings, _ = _drive_770(repair, entry, monkeypatch)
    hit = [w for w in warnings if "#770 auto-repair" in w]
    assert len(hit) == 1, "the failed repair was silent: %s" % warnings
    assert repair in hit[0], hit[0]
    assert "RuntimeError" in hit[0], "the message must name the fault it reports"
    assert "the repair could not write" in hit[0], "and the message, not only the type"


@pytest.mark.parametrize("repair,entry,check", _SITES_1203PG)
def test_it_warns_the_blocker_may_be_a_consequence(repair, entry, check, monkeypatch):
    """The actionable half: a lane handed this blocker must know the framework already tried."""
    warnings, _ = _drive_770(repair, entry, monkeypatch)
    hit = [w for w in warnings if "#770 auto-repair" in w][0]
    assert "CONSEQUENCE" in hit
    assert "before dispatching a lane at it" in hit


@pytest.mark.parametrize("repair,entry,check", _SITES_1203PG)
def test_the_blocker_check_still_runs_after_a_failed_repair(repair, entry, check, monkeypatch):
    """A repair failure must not turn into "no blockers" -- that is the silence, one step on.

    SPIED, not type-checked. The first version asserted `isinstance(result, list)`, and the
    mutation it was written for returns `[]` -- which is a list. An assertion that cannot tell
    "ran the check and found nothing" from "never ran the check" is the same confusion #1039 is
    about, in my own test.
    """
    called = {"n": 0}

    def _spy(*a, **k):
        called["n"] += 1
        return ["SENTINEL-1203pg"]

    monkeypatch.setattr(fa1203pg, check, _spy)
    _, result = _drive_770(repair, entry, monkeypatch)
    assert called["n"] == 1, "the blocker check never ran after the repair failed"
    assert result == ["SENTINEL-1203pg"], result


@pytest.mark.parametrize("repair,entry,check", _SITES_1203PG)
def test_a_successful_repair_announces_nothing(repair, entry, check, monkeypatch):
    """Non-vacuity: without this, a reporter that warns on every tick would pass the tests
    above while making the message meaningless."""
    warnings = []
    monkeypatch.setattr(dl, "_LOG_700", types.SimpleNamespace(
        warning=lambda *a, **k: warnings.append(str(a[0])),
        error=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None))
    monkeypatch.setattr(fa1203pg, repair, lambda *a, **k: None)
    d = Path(tempfile.mkdtemp())
    (d / "frontend" / "src").mkdir(parents=True)
    (d / "frontend" / "src" / "App.jsx").write_text("export default function App(){}",
                                                    encoding="utf-8")
    getattr(dl, entry)(d)
    assert [w for w in warnings if "#770 auto-repair" in w] == [], warnings
