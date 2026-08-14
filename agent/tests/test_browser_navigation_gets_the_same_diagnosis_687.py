r"""#687: the browser lane got none of #677's transport diagnosis, because Chromium spells it differently.

Found by sorting failures by LANE — an angle I had not used. The browser test users are 3868
failures across the corpus, 1684 of them in the live era, and their profile had never been read:

    test_api      HTTP Error: N                           890   -> #674
    test_api      ... requires AUTH                       756   (already good)
    browser_fill  Page.fill: Timeout                      668
    test_api      Connection refused                      536   -> #677
    browser_navigate  net::ERR_CONNECTION_REFUSED         308   <- this one
    browser_click Timeout                                 290

`browser_navigate` reported `Navigation failed: <raw>` for exactly the condition #677 explains
for `test_api`. It missed for a spelling reason: Chromium says `net::ERR_CONNECTION_REFUSED`,
which does not contain the substring "connection refused" that #677 matched on.

601 such navigations corpus-wide, 161 in the live era (r100+). Retrying a navigation to a process
that is not running cannot succeed however many times it is tried — the same argument #677 makes.

The fix normalises the `net::ERR_` tokens inside the ONE shared diagnosis rather than adding a
browser copy. #665's lesson was precisely that a second copy drifts from the first: #582 fixed one
retry loop and left its twin untouched for months.
"""
import pytest

from env_generator.llm_generator.tools.runtime_tools import (
    _request_failure_reason_677 as why,
)

URL = "http://localhost:8000/browse"


# --- the browser spellings now diagnose -----------------------------------------------------

def test_chromium_connection_refused_is_recognised():
    out = why(Exception("net::ERR_CONNECTION_REFUSED at http://localhost:8000/"), URL)
    assert "NOTHING IS LISTENING" in out
    assert "localhost:8000" in out


def test_chromium_name_not_resolved_is_recognised():
    out = why(Exception("net::ERR_NAME_NOT_RESOLVED"), URL)
    assert "does not resolve" in out
    assert "SERVICE name, not localhost" in out


def test_chromium_connection_reset_is_recognised():
    out = why(Exception("net::ERR_CONNECTION_RESET"), URL)
    assert "accepted then RESET" in out


def test_the_refused_advice_still_says_retrying_cannot_work():
    out = why(Exception("net::ERR_CONNECTION_REFUSED"), URL)
    assert "retrying this call cannot succeed" in out


# --- the urllib spellings are untouched ------------------------------------------------------

def test_the_original_urllib_form_still_works():
    import urllib.error
    out = why(urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), URL)
    assert "NOTHING IS LISTENING" in out


def test_an_unrecognised_error_is_still_passed_through():
    assert why(ValueError("something else"), URL) == "Request failed: something else"


def test_the_normalisation_cannot_invent_a_match():
    """Underscores are collapsed; that must not turn unrelated text into a diagnosis."""
    assert why(ValueError("some_unrelated_thing"), URL) == "Request failed: some_unrelated_thing"


# --- the browser tool calls it ---------------------------------------------------------------

def test_the_navigation_handler_calls_the_shared_helper():
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    assert "_request_failure_reason_677" in src


def test_it_keeps_the_raw_error_first():
    """The diagnosis is an addition, never a replacement."""
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    i = src.index("#687")
    tail = src[i:src.index("def _is_extension_error", i)]
    assert 'f"Navigation failed: {str(e)}"' in tail


def test_the_browser_import_is_local_and_guarded():
    """core.py must not gain a module-level dependency on runtime_tools."""
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    i = src.index("#687")
    tail = src[i:src.index("def _is_extension_error", i)]
    assert "from tools.runtime_tools import" in tail
    assert "except Exception:" in tail
    assert "from tools.runtime_tools" not in src[:i], "must not be a module-level import"


def test_a_helper_failure_leaves_the_raw_error_intact():
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    i = src.index("#687")
    tail = src[i:src.index("def _is_extension_error", i)]
    assert '_why = ""' in tail


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import core
    flat = " ".join(inspect.getsource(core).replace("#", " ").split())
    assert "601 ERR_CONNECTION_REFUSED navigations" in flat
    assert "161 of them in the LIVE era" in flat


def test_the_reason_for_one_shared_helper_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import runtime_tools as rt
    flat = " ".join(inspect.getsource(rt._request_failure_reason_677).replace("#", " ").split())
    assert "keeps ONE diagnosis in one place" in flat
    assert "665" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
