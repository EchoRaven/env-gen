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

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl


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
