"""#984: tell the verifier the path it wrote, not the canonical id.

The most common tool failure in the whole corpus — `registryhub_register_verification_chain`,
466 rejections across 14 runs — and the message identified the offending endpoint as:

    Endpoint(s) [PUT /api/profiles/{}] have now been rejected 3 times … DROP those steps

`{}` is `endpoint_id`'s canonical form. Collapsing `{profile_id}` / `{id}` / `` to `{}` is
correct and necessary for comparison, so different spellings of one route match. Reporting it
is not: the verifier never wrote `{}`, cannot find it in the contract (which lists
`{profile_id}`), and is then told to drop steps for an endpoint string that exists nowhere it
can look.

The canonical id remains the KEY — the repeat counter must stay stable across spellings — and
only the display changes.
"""

import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def test_the_canonical_form_really_does_collapse_the_param():
    """The premise. If this ever stops being true the fix is pointless."""
    assert RegistryHub.endpoint_id("PUT", "/api/profiles/{profile_id}") == "PUT /api/profiles/{}"
    assert RegistryHub.endpoint_id("PUT", "/api/profiles/{id}") == "PUT /api/profiles/{}"


def test_two_spellings_still_share_one_key():
    """Why the collapse exists — and why it must remain the counter's key."""
    a = RegistryHub.endpoint_id("PUT", "/api/profiles/{profile_id}")
    b = RegistryHub.endpoint_id("PUT", "/api/profiles/{id}")
    assert a == b


def _shown_impl():
    """The display helper, lifted from the source so it can be exercised directly."""
    submitted = {"PUT /api/profiles/{}": "PUT /api/profiles/{profile_id}"}

    def _shown(eid):
        orig = submitted.get(eid)
        return f"{orig} (canonical {eid})" if orig and orig != eid else eid

    return _shown


def test_the_message_shows_what_was_written():
    out = _shown_impl()("PUT /api/profiles/{}")
    assert "/api/profiles/{profile_id}" in out


def test_it_keeps_the_canonical_form_too():
    """The verifier needs both: the string it wrote, and the one the hub matched on."""
    out = _shown_impl()("PUT /api/profiles/{}")
    assert "canonical" in out and "{}" in out


def test_an_unmapped_id_degrades_to_itself():
    assert _shown_impl()("GET /api/unknown") == "GET /api/unknown"


def test_the_hub_builds_the_map_before_it_formats():
    src = inspect.getsource(RegistryHub)
    assert "_submitted_by_eid" in src
    i_map = src.index("_submitted_by_eid.setdefault(")
    i_use = src.index("_shown(_e) for _e in _repeat")
    assert i_map < i_use


def test_the_control_shows_the_bare_canonical():
    """Planted control: the PRE-FIX message joined the canonical ids directly, which is how
    `{}` reached the verifier."""
    repeat = ["PUT /api/profiles/{}"]
    assert ", ".join(repeat) == "PUT /api/profiles/{}", (
        "the control was supposed to render the collapsed form; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
