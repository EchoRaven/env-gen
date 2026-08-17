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
import inspect
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
