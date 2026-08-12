r"""#627: the breaking-change notifier was complete, and wired to nobody.

`_record_breaking_change` finds an endpoint's registered consumers, sends each an urgent event,
and auto-creates a fix task per consumer agent. It is dead in most runs because nothing registers
consumers — `register_consumer` is an LLM TOOL, so it fires only when a lane thinks to call it.

Measured over 45 runs:

    1196 breaking changes detected
     299 (25%) reach anybody
      30 of 45 runs have ZERO consumer rows — the store holds `_meta` and nothing else

In those 30 runs every breaking change is broadcast to an empty recipient list and no fix task is
ever created. `response_key_changed` alone is 583 of the 1196 — exactly the shape of the crashes
the verifier later files as unowned P0s ("Landing page renders blank", "default-imported
listTitles is an object, not a function").

The link already exists in the framework's own records: 435 of 738 registered pages carry a
non-empty `apis_used`, and all 754 entries are already in the canonical ``METHOD /path`` form
that matches `endpoint_id`. Using it takes routing from **25% to 58%** on the same corpus.

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
    assert "only 299 (25%) reach anybody" in flat
    assert "30 of 45 runs have ZERO consumer rows" in flat
    assert "25% to 58%" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
