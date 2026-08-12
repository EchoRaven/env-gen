r"""#631: the delivered source is the last declaration of who consumes what.

#627 (pages) and #629 (components) registered consumers from what a record DECLARES in
`apis_used`, taking breaking-change delivery from 2.9% to 60.0% on a timestamp-ordered replay.
The remainder are endpoints nothing declares — and they are not unused:

    176 still-unrouted breaking changes in runs whose frontend survives on disk
    163 (93%) name a path that IS present in app/frontend/src

They are called from the shared api client, or from files whose registry record never listed
them. `sync_ui_page_statuses` already walks that source and already holds the registryhub, so the
last step needs no new machinery.

Two matching rules were compared on the corpus and both recover 159 of the 176, so the stricter
one is taken for free precision: the literal path must be followed by a URL boundary, not by more
path — otherwise `/api/titles` claims every occurrence of `/api/titles/trending`.

Only REGISTERED endpoints are considered. The source is used to answer "does the frontend call
this?", never to invent an endpoint.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    register_source_api_consumers_631,
)


class _Hub:
    def __init__(self, endpoints):
        self._eps = endpoints
        self.consumers = []

    def get_endpoints(self):
        return self._eps

    def register_consumer(self, **kw):
        self.consumers.append(kw)
        return kw


def _eps(*ids, status="implemented"):
    return {i: {"status": status} for i in ids}


_SRC = "/proj/app/frontend/src/services/api.js"


# --- what it registers ----------------------------------------------------------------------------

def test_an_endpoint_called_from_the_source_gets_a_consumer():
    hub = _Hub(_eps("GET /api/search"))
    n = register_source_api_consumers_631({_SRC: "api.get('/api/search')"}, hub)
    assert n == 1 and hub.consumers[0]["endpoint_id"] == "GET /api/search"


def test_the_owner_is_the_frontend_lane():
    hub = _Hub(_eps("GET /api/search"))
    register_source_api_consumers_631({_SRC: "'/api/search'"}, hub)
    assert hub.consumers[0]["agent"] == "frontend"


def test_the_calling_file_is_recorded_relative_to_the_project():
    hub = _Hub(_eps("GET /api/search"))
    register_source_api_consumers_631({_SRC: "'/api/search'"}, hub, project_dir=Path("/proj"))
    assert hub.consumers[0]["file_path"] == "app/frontend/src/services/api.js"


def test_it_is_marked_as_source_derived():
    hub = _Hub(_eps("GET /api/search"))
    register_source_api_consumers_631({_SRC: "'/api/search'"}, hub)
    assert hub.consumers[0]["metadata"]["auto_registered_by"] == "frontend_audit#631"


def test_a_parameterised_endpoint_matches_on_its_literal_prefix():
    hub = _Hub(_eps("GET /api/titles/{}"))
    n = register_source_api_consumers_631({_SRC: "api.get(`/api/titles/${id}`)"}, hub)
    assert n == 1


def test_several_endpoints_each_register():
    hub = _Hub(_eps("GET /api/search", "GET /api/genres", "POST /api/my-list"))
    register_source_api_consumers_631(
        {_SRC: "'/api/search' '/api/genres' '/api/my-list'"}, hub)
    assert len(hub.consumers) == 3


# --- precision ------------------------------------------------------------------------------------

def test_a_longer_path_does_not_claim_its_prefix():
    """Only `/api/titles/trending` is called; `/api/titles` must NOT be registered."""
    hub = _Hub(_eps("GET /api/titles", "GET /api/titles/trending"))
    register_source_api_consumers_631({_SRC: "api.get('/api/titles/trending')"}, hub)
    assert [c["endpoint_id"] for c in hub.consumers] == ["GET /api/titles/trending"]


def test_an_endpoint_absent_from_the_source_is_not_registered():
    hub = _Hub(_eps("GET /api/never-called"))
    assert register_source_api_consumers_631({_SRC: "api.get('/api/search')"}, hub) == 0


def test_a_deprecated_endpoint_is_skipped():
    hub = _Hub(_eps("GET /api/old", status="deprecated"))
    assert register_source_api_consumers_631({_SRC: "'/api/old'"}, hub) == 0


def test_a_too_short_literal_is_skipped():
    """A one-segment stub is not a path worth matching against arbitrary source."""
    hub = _Hub(_eps("GET /a/{}"))
    assert register_source_api_consumers_631({_SRC: "'/a/1'"}, hub) == 0


def test_only_registered_endpoints_are_considered():
    """The source answers 'is this called?', it never invents an endpoint."""
    hub = _Hub({})
    assert register_source_api_consumers_631({_SRC: "api.get('/api/invented')"}, hub) == 0


# --- it must never break the audit --------------------------------------------------------------

def test_no_registryhub_is_a_no_op():
    assert register_source_api_consumers_631({_SRC: "x"}, None) == 0


def test_an_empty_cache_is_a_no_op():
    assert register_source_api_consumers_631({}, _Hub(_eps("GET /api/search"))) == 0


def test_a_hub_that_raises_does_not_propagate():
    class _Boom:
        def get_endpoints(self):
            raise RuntimeError("down")

    assert register_source_api_consumers_631({_SRC: "x"}, _Boom()) == 0


def test_a_failing_registration_skips_only_that_endpoint():
    class _Half(_Hub):
        def register_consumer(self, **kw):
            if "search" in kw["endpoint_id"]:
                raise RuntimeError("nope")
            return super().register_consumer(**kw)

    hub = _Half(_eps("GET /api/search", "GET /api/genres"))
    n = register_source_api_consumers_631({_SRC: "'/api/search' '/api/genres'"}, hub)
    assert n == 1 and hub.consumers[0]["endpoint_id"] == "GET /api/genres"


def test_the_audit_calls_it_after_building_the_cache():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    src = inspect.getsource(fa.sync_ui_page_statuses)
    assert src.index("cache[str(f)] =") < src.index("register_source_api_consumers_631")


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    flat = " ".join(inspect.getsource(fa).replace("#", " ").split())
    assert "163 of 176 (93%)" in flat
    assert "159 of the 176" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
