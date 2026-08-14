r"""#740: the capture drives a browser to every route and threw the console away.

There was no `page.on("console")` and no `"pageerror"` anywhere in `visual_fidelity.py`. The
gate navigates a real browser to every declared route, every remediation round, and discarded
the single most diagnostic signal on the page. A crashed SPA could therefore only be described
by its SYMPTOM — "route X rendered BLANK — the SPA never hydrated" — and the remediation task
handed to the lane said "fix the page's mount/data load, not its styling".

r148 is what that costs. Its frontend threw `TypeError: (void 0) is not a function` on every
authenticated route. The capture saw ten blank shells and said so; the error text reached the
lane only because the VERIFIER separately drove a browser and read the console, 9 minutes later.

Corpus, over the 148 task stores:

    runs whose tasks carry a frontend runtime-crash signature      14
    of those, runs that RELEASED                                   14
    of those, released with the crash task still open               9
    runs carrying `(void 0) is not a function` specifically         5

**A frontend runtime crash has never once stopped a release.** Reading the console does not by
itself stop one either — this is diagnosis, not a gate — but it puts the cause in the artifact
the lane is actually handed, instead of leaving it to be rediscovered.

Bounded on purpose: 5 distinct messages per screen, 300 chars each, `error`-level console
entries and uncaught exceptions only. A page looping an error cannot flood the verdict.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --- the grouping is by MESSAGE, because one import breaks every route ------------------------

def test_one_error_across_many_screens_is_one_group():
    got = vf._group_console_errors_740({
        "browse_home": ["uncaught: TypeError: (void 0) is not a function"],
        "movies": ["uncaught: TypeError: (void 0) is not a function"],
        "shows": ["uncaught: TypeError: (void 0) is not a function"],
    })
    assert list(got) == ["uncaught: TypeError: (void 0) is not a function"]
    assert got["uncaught: TypeError: (void 0) is not a function"] == [
        "browse_home", "movies", "shows"]


def test_distinct_errors_stay_distinct():
    got = vf._group_console_errors_740({"a": ["e1"], "b": ["e2"]})
    assert got == {"e1": ["a"], "e2": ["b"]}


def test_a_screen_with_several_errors_appears_in_each():
    got = vf._group_console_errors_740({"a": ["e1", "e2"]})
    assert got == {"e1": ["a"], "e2": ["a"]}


def test_a_screen_is_not_listed_twice_for_a_repeated_message():
    got = vf._group_console_errors_740({"a": ["e1", "e1"]})
    assert got == {"e1": ["a"]}


def test_empty_and_blank_messages_are_dropped():
    assert vf._group_console_errors_740({"a": ["", "   "]}) == {}


@pytest.mark.parametrize("junk", [None, "", [], 0, {"a": None}, {"a": "notalist"}, {"a": 5}])
def test_malformed_input_never_raises(junk):
    assert vf._group_console_errors_740(junk) == {}


def test_it_is_pure():
    src = inspect.getsource(vf._group_console_errors_740)
    assert "_LOG" not in src and "raise" not in src


# --- the collector is wired to the real events -------------------------------------------------

def _cap() -> str:
    return inspect.getsource(vf.capture_route_screenshots)


def test_the_capture_accepts_a_sink():
    sig = inspect.signature(vf.capture_route_screenshots)
    p = sig.parameters["console_errors"]
    assert p.default is None, "must stay opt-in so existing callers are byte-identical"


def test_both_event_sources_are_registered():
    c = _cap()
    assert 'page.on("pageerror"' in c, "uncaught exceptions"
    assert 'page.on("console"' in c, "console.error"


def test_only_error_level_console_is_kept():
    """Warnings and logs are noise; a React dev warning is not a crash."""
    c = _cap()
    assert 'm.type == "error"' in c


def test_the_sink_is_bounded():
    c = _cap()
    assert "len(_b) < 5" in c
    assert "[:300]" in c


def test_errors_are_attributed_to_the_screen_being_captured():
    """Without this every error lands on whatever screen happened to be current."""
    c = _cap()
    assert '_cur740["name"] = str(screen["name"])' in c
    i, j = c.index('_cur740["name"] = str(screen["name"])'), c.index("await page.goto(base_url +")
    assert i < j, "the attribution must be set BEFORE the navigation it attributes"


def test_nothing_is_collected_when_no_sink_is_passed():
    c = _cap()
    assert "if console_errors is None:" in c
    assert "if console_errors is not None:" in c


def test_the_recorder_cannot_break_a_capture():
    # Anchored on the statement that follows the function, not on a character count — a
    # fixed-width window silently stops covering the body the moment the body grows.
    c = _cap()
    body = c[c.index("def _rec740("):c.index("if console_errors is not None:")]
    assert "except Exception:" in body
    assert "return" in body


# --- the caller uses it -------------------------------------------------------------------------

def _run() -> str:
    return inspect.getsource(vf.run_visual_fidelity)


def test_the_gate_passes_a_sink():
    assert "console_errors=_console740" in _run()


def test_a_blank_screen_names_the_actual_error():
    r = _run()
    assert "The browser reported: " in r
    assert "it is the reason the shell is empty" in r


def test_the_error_reaches_the_persisted_record():
    assert '"console_errors": _console740.get(screen["name"]) or []' in _run()


def test_the_pass_level_summary_is_grouped_not_per_screen():
    r = _run()
    assert "_by740 = _group_console_errors_740(_console740)" in r
    assert "distinct uncaught/console error(s)" in r


def test_the_injected_capture_path_still_works():
    """`capture_fn` callers (tests, dry runs) never touch playwright — they must still have
    the name bound, or the summary block raises on an unbound local."""
    r = _run()
    assert "_console740 = {}" in r


# --- provenance -----------------------------------------------------------------------------------

def test_the_corpus_measurement_is_recorded():
    c = " ".join(_cap().replace("#", " ").split())
    assert "14 runs carry a frontend runtime-crash" in c
    assert "all 14 released" in c
    assert "9 of them with the crash" in c


def test_it_records_what_the_absence_cost():
    c = " ".join(_cap().replace("#", " ").split())
    assert "could only ever be described by its SYMPTOM" in c
    assert "(void 0) is not a function" in c


def test_it_records_that_it_is_additive():
    c = " ".join(_cap().replace("#", " ").split())
    assert "Purely additive" in c
    assert "byte-identical to before" in c


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
