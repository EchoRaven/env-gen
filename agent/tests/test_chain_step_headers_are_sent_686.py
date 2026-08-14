r"""#686: a chain step's own `headers` were silently discarded.

Reached by ranking every broken assertion in the corpus by status code rather than by wording:

    400  75  (37.1%)   <- the largest class, bigger than 404 (59) and 500 (36)
    404  59  (29.2%)
    500  36  (17.8%)

and then breaking the 400s down and CHECKING THE ERA of each cause:

    null value in column ...          53   all r13-r67   already fixed, historical
    X-Profile-Id header is required   11   all r100+     LIVE, and all in one run (r132)
    integrity constraint violated      6   all r<100     historical
    value must be up|down|love         1   r145          a single instance

`_headers` in the executor was only ever the framework's tenant-scope override, so a step that
authored headers had them dropped and then failed on the endpoint's own complaint. 275 steps
across the corpus declare `headers`. The endpoint genuinely demands one, so without this it is
untestable BY CONSTRUCTION rather than merely awkward to test.

The framework had told authors as much — the tool description listed only method/path/body/
expect/save/auth, and #586's rejection text said "a chain step carries no headers" — but nothing
rejected a step that declared them. Silently dropping input is worse than refusing it, so both
those texts now say headers are supported and the executor sends them.

Authorization is deliberately NOT taken from a step: actor identity comes from `auth`, and a
step-supplied bearer would quietly change actor and defeat the ownership probes (#591/#663).

The rating enum (`value must be up|down|love` while the contract declares `value: str`) is left
alone on purpose: one instance in the whole corpus, and the 400 body already names the allowed
values. With #683 now naming the owning chain, that loop closes without a special case.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


def _block():
    src = inspect.getsource(ce)
    i = src.index("#686: A STEP'S OWN")
    return src[i:src.index("res = _http(", i)]


# --- the step's headers reach the request ------------------------------------------------------

def test_authored_headers_are_read_from_the_step():
    assert 'step.get("headers")' in _block()


def test_they_are_only_taken_from_a_mapping():
    assert "isinstance(_authored, Mapping)" in _block()


def test_they_are_passed_to_the_request():
    src = inspect.getsource(ce)
    i = src.index("#686: A STEP'S OWN")
    assert "headers=_headers" in src[i:src.index("status = res.get", i)]


def test_blank_keys_are_dropped():
    assert "str(k).strip()" in _block()


def test_values_are_stringified():
    """A JSON number in a header would raise inside the HTTP layer."""
    assert "str(v)" in _block()


def test_no_headers_means_None_not_an_empty_dict():
    """`headers={}` and `headers=None` differ to some clients; keep the previous default."""
    assert "_headers = _headers or None" in _block()


# --- Authorization is never taken from a step -----------------------------------------------------

def test_authorization_is_filtered_out():
    assert 'str(k).lower() != "authorization"' in _block()


def test_the_reason_authorization_is_excluded_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "quietly change actor" in flat
    assert "591" in flat and "663" in flat


# --- the framework's own override still wins --------------------------------------------------

def test_the_framework_header_is_merged_last():
    body = _block()
    assert "{**(_headers or {}), **_fw}" in body


def test_the_factory_reset_scope_still_applies():
    body = _block()
    assert "_is_factory_reset(method, path)" in body
    assert "_scoped_reset_header(" in body


def test_the_scope_note_is_still_produced():
    assert "_scope_note = f\"reset-scoped->" in _block()


# --- the author-facing contract now matches the behaviour ----------------------------------------

def test_the_tool_description_offers_headers():
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    assert "headers (a dict of extra request headers" in src


def test_the_tool_description_warns_about_authorization():
    from env_generator.llm_generator.tools import hub_tools as ht
    assert "Authorization is ignored here, use auth" in inspect.getsource(ht)


def test_the_586_rejection_text_no_longer_says_headers_are_impossible():
    """It taught the opposite of the truth once headers work."""
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    assert "a chain step carries no " not in src
    assert "A step CAN set `headers`" in src


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "275 steps across the corpus declare" in flat
    assert "untestable" in flat


def test_the_era_check_is_recorded():
    """The 400 class is mostly historical; only this cause is live."""
    flat = " ".join(_block().replace("#", " ").split())
    assert "LIVE era (r100+)" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
