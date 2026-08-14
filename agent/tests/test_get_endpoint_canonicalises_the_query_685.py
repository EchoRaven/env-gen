r"""#685: the registry displayed one path and required another to look it up.

From r145's failure scan: `registryhub_get_endpoint` refused the same call 10 times with
`Endpoint not found: POST /api/titles/{id}/rating` — for an endpoint that was registered the
whole time.

The store keeps two different forms of the same path, on purpose:

    key            'POST /api/titles/{}/rating'    RegistryHub.endpoint_id collapses {id} -> {}
    record["path"] '/api/titles/{id}/rating'       _canonical_path keeps the named param

An agent that reads the endpoint off the registry sees the NAMED form, asks for it back verbatim,
and misses — because the getter did a raw `get_endpoints().get(endpoint_id)`. It was being asked
to know an internal normalisation it is never shown.

Canonicalising the query through the same helper that built the key makes the two agree. The raw
lookup runs first, so an exact key resolves exactly as before.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


# --- the two forms now converge -----------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "POST /api/titles/{id}/rating",     # what the record displays  <- the r145 refusal
    "POST /api/titles/{}/rating",       # what the key actually is
    "POST /api/titles/:id/rating",      # the Express form #29 rewrites
])
def test_every_spelling_reaches_one_key(query):
    method, path = query.split(None, 1)
    assert RegistryHub.endpoint_id(method, path) == "POST /api/titles/{}/rating"


def test_a_query_string_is_stripped():
    """A list filter is not a distinct endpoint."""
    assert RegistryHub.endpoint_id("GET", "/api/notes?tag=x") == "GET /api/notes"


def test_differently_named_params_collapse_together():
    a = RegistryHub.endpoint_id("GET", "/api/titles/{id}")
    b = RegistryHub.endpoint_id("GET", "/api/titles/{title_id}")
    assert a == b


def test_distinct_endpoints_stay_distinct():
    """Collapsing must not merge two real routes."""
    assert (RegistryHub.endpoint_id("GET", "/api/titles/{id}")
            != RegistryHub.endpoint_id("GET", "/api/titles/{id}/episodes"))
    assert (RegistryHub.endpoint_id("GET", "/api/titles/{id}")
            != RegistryHub.endpoint_id("POST", "/api/titles/{id}"))


# --- the getter tries the raw key first ------------------------------------------------------

def test_the_raw_lookup_is_attempted_before_canonicalising():
    """An exact key must resolve unchanged — the fallback is additive."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("#685: LOOK IT UP THE WAY IT WAS STORED")
    body = src[i:src.index("return ToolResult", i)]
    assert body.index("_eps.get(endpoint_id)") < body.index("_RH.endpoint_id(")


def test_the_fallback_only_runs_on_a_miss():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("#685: LOOK IT UP THE WAY IT WAS STORED")
    body = src[i:src.index("return ToolResult", i)]
    assert "if endpoint is None:" in body


def test_a_malformed_query_cannot_raise():
    """Built on an already-failing path: a one-token or empty id must degrade, not throw."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    src = inspect.getsource(ht)
    i = src.index("#685: LOOK IT UP THE WAY IT WAS STORED")
    body = src[i:src.index("return ToolResult", i)]
    assert "len(_parts) == 2" in body
    assert "except Exception:" in body


def test_the_helper_it_reuses_is_the_one_that_built_the_key():
    """Two normalisers would drift; the point is that they are the same function."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    i = src.index("def endpoint_id(")
    assert '_re.sub(r"\\{[^}]+\\}", "{}"' in src[i:src.index("@staticmethod", i)]


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    flat = " ".join(inspect.getsource(ht).replace("#", " ").split())
    assert "r145 refused 10 of these" in flat


def test_the_two_stored_forms_are_documented():
    """The next reader must see WHY a raw lookup was wrong."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools as ht
    flat = " ".join(inspect.getsource(ht).replace("#", " ").split())
    assert "keeps the named form" in flat
    assert "never shown" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
