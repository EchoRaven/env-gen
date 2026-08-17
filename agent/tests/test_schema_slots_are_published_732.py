r"""#732: the framework never told anyone which schema keys it reads.

The user's objection, which is correct and which retires my two previous attempts: an agent
inventing new endpoints and new words is NORMAL. Discovering each invention one run at a time
does not converge, and synonym matching cannot work — today it is `query`, and a completely
unrelated app will produce `params`, `queryParams`, `filters`.

So the problem is not the invention. It is that `registryhub_register_endpoint` declared

    "schema": {"type": "object"}

and a description reading "Register/update RegistryHub endpoint and schema." The model was asked
for "a schema" and had to GUESS the key names. r148 guessed `query` for query parameters — a
better word than the one every consumer reads — so the declaration was stored and invisible for a
whole run, and six catalogue routes shipped fetching the same unfiltered list.

`tooling.py` states that "Every tool advertises PARAMETERS to the model … the same text the model
was shown", so naming the slots there is exactly where the gap is. The four slots belong to the
FRAMEWORK, not to any app's domain, which is what makes this app-independent by construction: the
tool definition travels with the framework to every future generation, netflix or not.

Extra keys stay legal. The model may still invent; it simply no longer has to, and #731 reports
anything outside the published set — with its known set now DERIVED from this declaration rather
than from the words one corpus happened to use.
"""
import pytest

from env_generator.llm_generator.tools.hub_tools import (
    RegistryHubRegisterEndpointTool as TOOL,
)


def _schema_param():
    return (TOOL.PARAMETERS.get("properties") or {}).get("schema") or {}


# --- the slots are published where the model reads them -----------------------------------------

def test_the_schema_param_is_no_longer_opaque():
    s = _schema_param()
    assert s.get("type") == "object"
    assert s.get("properties"), "a bare {'type': 'object'} tells the model nothing"


@pytest.mark.parametrize("slot", ["request", "response", "response_key", "auth_required"])
def test_every_framework_slot_is_named(slot):
    assert slot in (_schema_param().get("properties") or {})


def test_each_slot_says_what_it_is_for():
    for name, spec in (_schema_param().get("properties") or {}).items():
        assert spec.get("description"), f"{name} has no description"


def test_request_spells_out_the_GET_case():
    d = ((_schema_param().get("properties") or {}).get("request") or {}).get("description", "")
    assert "QUERY PARAMETERS" in d
    assert "declare every filter you implement" in d


def test_request_states_the_consequence_of_omitting_it():
    d = ((_schema_param().get("properties") or {}).get("request") or {}).get("description", "")
    assert "invisible to the frontend" in d
    assert "six catalogue routes" in d


def test_the_optional_marker_is_explained():
    d = ((_schema_param().get("properties") or {}).get("request") or {}).get("description", "")
    assert "`?` marks optional" in d or "trailing `?`" in d


# --- invention stays legal -----------------------------------------------------------------------

def test_extra_keys_are_not_forbidden():
    """Rejecting unknowns would discard good information to enforce a vocabulary — `query` was a
    better name than `request`. The published set removes the NEED to guess, not the freedom."""
    assert _schema_param().get("additionalProperties") is not False


def test_the_description_says_extra_keys_are_kept():
    d = _schema_param().get("description", "")
    assert "stored faithfully" in d
    assert "no consumer acts on it" in d


# --- #731's known set now derives from this, not from one corpus -------------------------------------

def test_the_known_set_is_derived_from_the_declaration():
    from env_generator.llm_generator.multi_agent.runtime.registryhub import (
        _declared_schema_keys_732 as derive, _KNOWN_SCHEMA_KEYS_731 as known)
    assert set(known) == set(derive())
    assert set((_schema_param().get("properties") or {})) <= set(known)


def test_the_derivation_survives_an_import_failure():
    """A warning helper must never be the thing that breaks a hub."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh._declared_schema_keys_732)
    assert "except Exception:" in src
    assert "return frozenset({" in src


def test_the_two_settled_keys_are_carried_deliberately():
    """`query` is folded by #730 and `headers` is deliberately unread (item 51) — warning about
    either would report a settled decision as news."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    # ★ #922: anchored on the CODE the rationale precedes, not on a sentence inside it. The start
    # used to be a phrase from the very comment this test reads, so rewording that comment would
    # break the LOCATOR rather than the assertion — the failure would point at the wrong thing.
    _end = src.index("_KNOWN_SCHEMA_KEYS_731 =")
    _start = src.rindex("\n\n", 0, _end)
    block = " ".join(src[_start:_end].replace("#", " ").split())
    assert "folded into `request` by" in block
    assert "a header selects an actor" in block


# --- provenance ---------------------------------------------------------------------------------------

def test_why_synonym_matching_cannot_work_is_recorded():
    d = " ".join((__doc__ or "").split())
    assert "does not converge" in d
    assert "params" in d and "queryParams" in d


def test_the_app_independence_argument_is_recorded():
    # Folded: the sentence wraps, and a raw match splits it at "belong to the" / "FRAMEWORK".
    d = " ".join((__doc__ or "").split())
    assert "belong to the FRAMEWORK, not to any app's domain" in d
    assert "travels with the framework to every future generation" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
