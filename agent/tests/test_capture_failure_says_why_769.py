r"""#769: a screen that could not be photographed left no trace at all.

The per-screen capture body ended:

    except Exception:
        continue

So a navigation timeout, a closed page and a proxy refusal were indistinguishable from each
other and from nothing happening — and downstream the screen becomes a hard 0.00 that COUNTS
against the gate (#542's invariant, and #768r kept it deliberately).

r150 is what that costs. Its final round captured 3 of 12 screens and scored NINE zeros, and the
zeros track missing captures exactly, round by round:

    shots written   4    0    2    5    3
    zeros           0    7    4    6    9

The app was fine — captures from the earlier rounds are a complete Netflix clone with a working
title-detail modal and player. So the gate reported 0.1727 about the HARNESS, and nothing
anywhere said so.

Same shape as #748 one layer up: the reason existed, was caught, and was discarded at the
`except`. This is the third time this session that a swallowed cause turned out to be the whole
answer (#748 compose, #740 console, this).
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _src() -> str:
    return inspect.getsource(vf.capture_route_screenshots)


# --- the bare continue is gone -------------------------------------------------------------------

def test_the_handler_no_longer_swallows_silently():
    s = _src()
    assert "except Exception as _cap769:" in s
    assert "#769 capture FAILED for screen" in s


def test_the_exception_is_still_caught():
    """It must not start raising — one screen failing must never abort the whole capture."""
    s = _src()
    i = s.index("except Exception as _cap769:")
    blk = s[i:s.index("finally:", i)]
    assert "continue" in blk
    assert "raise" not in blk


def test_it_names_the_screen_and_the_route():
    s = _src()
    assert 'screen.get("name"), screen.get("route")' in s


def test_it_names_the_exception_TYPE():
    """A navigation timeout, a closed page and a proxy refusal are three different problems."""
    s = _src()
    assert "type(_cap769).__name__" in s


def test_the_message_is_bounded():
    s = _src()
    assert "str(_cap769)[:200]" in s


def test_it_says_the_zero_is_about_the_capture():
    """The line has to pre-empt the misreading, because the 0.00 it produces looks like a
    verdict on the page and is not."""
    # Adjacent string literals are joined first — the message wraps mid-sentence, and a plain
    # `" ".join(split())` leaves the quote characters inside the phrase. Same trap as #711's.
    import re
    flat = re.sub(r'"\s*\n\s*"', "", _src())
    assert "that zero is about the capture, not the page" in flat


# --- provenance --------------------------------------------------------------------------------------

def _prov() -> str:
    s = _src()
    i = s.index("#769: SAY WHY THE CAPTURE FAILED")
    return " ".join(l.strip().lstrip("#").strip() for l in s[i:s.index("_LOG.warning(", i)].split("\n"))


def test_the_r150_correlation_is_recorded():
    p = _prov()
    assert "captured 3 of 12 screens and" in p and "NINE zeros" in p
    assert "4 shots -> 0 zeros; 0 shots -> 7 zeros" in p


def test_it_records_that_the_app_was_fine():
    p = _prov()
    assert "The app was fine" in p
    assert "reported 0.1727 about the HARNESS" in p


def test_it_credits_the_pattern():
    p = _prov()
    assert "Same shape as #748 one layer up" in p


def test_it_records_that_the_downstream_zero_is_deliberate():
    """#768r decided the zero must still count. This line must not read as a plan to stop it."""
    p = _prov()
    assert "542's invariant, deliberately" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
