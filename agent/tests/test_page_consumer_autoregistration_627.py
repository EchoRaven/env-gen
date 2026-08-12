r"""#627: the breaking-change notifier was complete, and wired to nobody.

`_record_breaking_change` finds an endpoint's registered consumers, sends each an urgent event,
and auto-creates a fix task per consumer agent. It is dead in most runs because nothing registers
consumers — `register_consumer` is an LLM TOOL, so it fires only when a lane thinks to call it.

Measured at EMIT TIME, from each event's own `recipients` field — the only reading that answers
"was anyone actually told":

    1129 breaking changes across 42 runs
      33 (2.9%) reached anybody
    +324 would have, replaying in timestamp order with only pages registered BEFORE each event
         -> 357 (31.6%)

That number took three attempts, and both wrong ones are worth keeping:

  * "25% -> 58%" came from the FINAL consumer store, which accumulates all run long and so
    credits consumers that did not exist when the event fired. **A final-state store is not a
    timeline** — the same trap as the squash-merge reading in #622. (30 of 45 runs do end with a
    consumer store holding only `_meta`.)
  * "2.9% -> 25.0%" fixed the timeline but matched endpoint ids with a hand-rolled string
    compare, missing that `endpoint_id()` collapses `{param}` -> `{}` (PROPOSAL #39). **Do not
    reimplement the code's normalization in a measurement — call it.**

`response_key_changed` alone is 583 of the total — exactly the shape of the crashes the verifier
later files as unowned P0s ("Landing page renders blank", "default-imported listTitles is an
object, not a function").

The link already exists in the framework's own records: 435 of 738 registered pages carry a
non-empty `apis_used`, and all 754 entries are already in the canonical ``METHOD /path`` form
that matches `endpoint_id`. The residual 75% are endpoints no page declares; widening that source
is a separate question, deliberately not attempted here.

The owner is the FRONTEND lane, from the page's own path — never `created_by`, which is the
orchestrator for 417 of those 754 entries and would repeat #626's "assigned to someone who
cannot fix it".
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _rh(tmp_path):
    rh = RegistryHub(Path(tmp_path))
    rh.register_endpoint("GET", "/api/titles", status="implemented",
                         schema={"response": {"items": "list"}}, agent="backend")
    return rh


def _consumers(rh):
    return {k: v for k, v in (rh._consumers.value() or {}).items() if k != "_meta"}


_PAGE = dict(name="browse", route="/browse", component="BrowsePage",
             path="app/frontend/src/pages/BrowsePage.jsx",
             apis_used=["GET /api/titles"], agent="orchestrator")


# --- registration -------------------------------------------------------------------------------

def test_a_page_declaring_an_api_becomes_its_consumer(tmp_path):
    rh = _rh(tmp_path)
    rh.register_ui_page(**_PAGE)
    assert any(c["endpoint_id"] == "GET /api/titles" for c in _consumers(rh).values())


def test_the_owner_is_the_frontend_lane_not_the_registrar(tmp_path):
    """`agent="orchestrator"` registers the page; the orchestrator cannot fix a frontend page."""
    rh = _rh(tmp_path)
    rh.register_ui_page(**_PAGE)
    assert {c["agent"] for c in _consumers(rh).values()} == {"frontend"}


def test_the_page_file_is_recorded_so_a_fix_task_can_name_it(tmp_path):
    rh = _rh(tmp_path)
    rh.register_ui_page(**_PAGE)
    c = next(iter(_consumers(rh).values()))
    assert c["file_path"] == "app/frontend/src/pages/BrowsePage.jsx"
    assert c["metadata"]["auto_registered_by"] == "register_ui_page#627"


def test_a_page_with_no_apis_used_registers_nothing(tmp_path):
    rh = _rh(tmp_path)
    rh.register_ui_page(name="landing", route="/", component="LandingPage",
                        path="app/frontend/src/pages/LandingPage.jsx", apis_used=[])
    assert _consumers(rh) == {}


def test_several_apis_on_one_page_all_register(tmp_path):
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/genres", status="implemented", agent="backend")
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/titles", "GET /api/genres"]})
    assert {c["endpoint_id"] for c in _consumers(rh).values()} == {
        "GET /api/titles", "GET /api/genres"}


def test_re_registering_the_page_does_not_duplicate(tmp_path):
    """register_ui_page fires 2644 times across the corpus; the key must overwrite."""
    rh = _rh(tmp_path)
    for _ in range(5):
        rh.register_ui_page(**_PAGE)
    assert len(_consumers(rh)) == 1


# --- an endpoint that does not exist yet ---------------------------------------------------------

def test_an_unpublished_endpoint_is_queued_not_rejected(tmp_path):
    """Pages are often registered before the backend publishes the endpoint."""
    rh = _rh(tmp_path)
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/not-yet"]})
    pending = {k: v for k, v in (rh._pending_consumers.value() or {}).items() if k != "_meta"}
    assert any(p["endpoint_id"] == "GET /api/not-yet" for p in pending.values())


def test_it_is_promoted_when_the_endpoint_arrives(tmp_path):
    rh = _rh(tmp_path)
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/later"]})
    rh.register_endpoint("GET", "/api/later", status="implemented", agent="backend")
    assert any(c["endpoint_id"] == "GET /api/later" for c in _consumers(rh).values())


# --- it must never break a page registration ------------------------------------------------------

@pytest.mark.parametrize("apis", [["notanendpoint"], [None], [123], "GET /api/titles"])
def test_a_malformed_apis_used_is_skipped_not_fatal(tmp_path, apis):
    rh = _rh(tmp_path)
    rec = rh.register_ui_page(**{**_PAGE, "apis_used": apis})
    assert rec["name"] == "browse"


def test_the_page_survives_a_consumer_failure(tmp_path, monkeypatch):
    rh = _rh(tmp_path)
    monkeypatch.setattr(rh, "register_consumer",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert rh.register_ui_page(**_PAGE)["name"] == "browse"


def test_a_page_with_no_path_still_gets_the_frontend_owner(tmp_path):
    rh = _rh(tmp_path)
    rh.register_ui_page(**{**_PAGE, "path": ""})
    assert {c["agent"] for c in _consumers(rh).values()} == {"frontend"}


# --- path parameters: #627 inherits PROPOSAL #39's param-agnostic identity ------------------------
#
# The endpoint store keys every path parameter as a bare `{}` (235 of 235 parameterised ids across
# 45 runs), while pages declare the NAME — 407 of 2777 `apis_used` entries are `{id}`/`{genre_id}`/
# `{title_id}`. That looks like it cannot match, and I measured a would-be fix for it. It was
# already handled: `endpoint_id()` collapses `{param}` -> `{}` (PROPOSAL #39), and
# `register_consumer` runs every id through it. The lesson is in the measurement, not the code —
# reimplementing the normalization offline UNDERCOUNTED #627's reach as 25.0% when calling the real
# function gives 31.6%. Pinned here so the resolution cannot silently regress.


def test_a_named_placeholder_resolves_to_the_stores_bare_one(tmp_path):
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/titles/{title_id}", status="implemented", agent="backend")
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/titles/{id}"]})
    assert any(c["endpoint_id"] == "GET /api/titles/{}" for c in _consumers(rh).values())


def test_the_parameter_name_does_not_matter(tmp_path):
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/genres/{gid}/titles", status="implemented", agent="backend")
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/genres/{genre_id}/titles"]})
    assert any(c["endpoint_id"] == "GET /api/genres/{}/titles" for c in _consumers(rh).values())


def test_an_express_style_param_resolves_too(tmp_path):
    """`:param` -> `{param}` -> `{}`, so a router-idiom declaration lands on the same endpoint."""
    rh = _rh(tmp_path)
    rh.register_endpoint("GET", "/api/titles/{title_id}", status="implemented", agent="backend")
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/titles/:id"]})
    assert any(c["endpoint_id"] == "GET /api/titles/{}" for c in _consumers(rh).values())


def test_an_endpoint_nobody_published_is_still_queued_under_its_own_id(tmp_path):
    """Param-agnostic identity must not invent a match — an unknown path stays pending."""
    rh = _rh(tmp_path)
    rh.register_ui_page(**{**_PAGE, "apis_used": ["GET /api/nothing/{id}"]})
    pending = {k: v for k, v in (rh._pending_consumers.value() or {}).items() if k != "_meta"}
    assert any(p["endpoint_id"] == "GET /api/nothing/{}" for p in pending.values())


def test_the_identity_is_param_name_agnostic_by_design(tmp_path):
    """PROPOSAL #39, relied on above. A separate `{id}` vs `{note_id}` identity used to fork a
    phantom `defined` endpoint that blocked delivery forever."""
    rh = _rh(tmp_path)
    assert rh.endpoint_id("GET", "/api/titles/{id}") == "GET /api/titles/{}"
    assert rh.endpoint_id("GET", "/api/titles/:id") == "GET /api/titles/{}"
    assert rh.endpoint_id("GET", "/api/titles/{title_id}") == "GET /api/titles/{}"


# --- end to end: the notifier is no longer wired to nobody -----------------------------------------

def test_a_breaking_change_now_reaches_the_page_that_uses_it(tmp_path):
    """The whole point. Register the endpoint, register a page that consumes it, then change the
    endpoint breakingly — the consumer must be in the recipient set."""
    rh = _rh(tmp_path)
    rh.register_ui_page(**_PAGE)
    sent = []
    orig = rh._emit

    def spy(event, payload, recipients=None, **kw):
        sent.append((event, list(recipients or [])))
        return orig(event, payload, recipients=recipients, **kw)

    rh._emit = spy
    rh.register_endpoint("GET", "/api/titles", status="implemented",
                         schema={"response": {"rows": "list"}}, agent="backend")
    breaking = [r for e, r in sent if e == "breaking_change_detected"]
    assert breaking, "the schema change should have been detected as breaking"
    assert "frontend" in breaking[0], f"recipients were {breaking[0]} — the notifier is wired to nobody"


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub
    flat = " ".join(inspect.getsource(
        registryhub.RegistryHub._autoregister_page_consumers_627).split())
    assert "(2.9%)" in flat and "357" in flat and "(31.6%)" in flat
    assert "A final-state store is not a timeline" in flat
    assert "Do not reimplement the code's normalization in a measurement" in flat, (
        "both wrong readings must stay recorded — each is a distinct trap")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
