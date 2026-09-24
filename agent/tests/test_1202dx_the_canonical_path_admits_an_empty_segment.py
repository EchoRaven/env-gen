r"""#1202dx: `_canonical_path` calls itself canonical and admits `//`.

It trims, forces one leading `/`, strips a trailing `/`, and rewrites `:param` to `{param}`
— "The canonical FastAPI path form used by both ``endpoint_id`` and the stored endpoint
``path`` field". It does not collapse an interior empty segment, so two spellings of one
route persist as two endpoints:

    GET /api/titles//episodes
    GET /api/titles/episodes

netflix-r44 registered both. Its registry ends with three `episodes` entries where the app
serves one shape, and `#1202h` reported `GET /api/titles//episodes (custom_routes.py)` as a
route "SERVED but never registered, so no gate sees them" during the window before the second
spelling was registered.

The framework already disagrees with itself about this. `param_agnostic` — what the delivery
gate matches on — collapses the empty segment, so the registry and the gates hold different
counts of the same surface. `_norm_route_1202h` does not collapse it, which is why the two
spellings could not match each other there.

No URL path has an empty segment, so collapsing at the door is safe and makes the stored form
actually canonical. Fixed here rather than in each consumer, for the reason #1202dw was: a
door fix is inherited by every gate, including ones added later.
"""
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _hub():
    return RegistryHub(Path(tempfile.mkdtemp()))


@pytest.mark.parametrize("raw,want", [
    ("/api/titles//episodes", "/api/titles/episodes"),
    ("/api//titles//episodes", "/api/titles/episodes"),
    ("//api/titles", "/api/titles"),
    ("/api/titles//", "/api/titles"),
])
def test_an_empty_segment_is_collapsed(raw, want):
    assert _hub()._canonical_path(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("/api/titles", "/api/titles"),
    ("/api/notes/:id", "/api/notes/{id}"),
    ("api/titles", "/api/titles"),
    ("/api/titles/", "/api/titles"),
    ("/", "/"),
    ("/api/titles/{id}/episodes", "/api/titles/{id}/episodes"),
])
def test_the_existing_normalisations_are_unchanged(raw, want):
    """PROPOSAL #38 A2 / #29 behaviour must survive verbatim."""
    assert _hub()._canonical_path(raw) == want


def test_the_two_spellings_register_as_ONE_endpoint():
    """r44's shape: the registry held both and counted them separately."""
    h = _hub()
    h.register_endpoint("GET", "/api/titles//episodes", status="implemented")
    h.register_endpoint("GET", "/api/titles/episodes", status="implemented")
    keys = sorted(k for k in h.get_endpoints() if k != "_meta")
    assert keys == ["GET /api/titles/episodes"], keys


def test_the_stored_path_is_the_collapsed_form():
    h = _hub()
    h.register_endpoint("GET", "/api/titles//episodes", status="implemented")
    rec = h.get_endpoints()["GET /api/titles/episodes"]
    assert rec["path"] == "/api/titles/episodes"


def test_it_now_agrees_with_param_agnostic():
    """The registry and the delivery gate must count the same surface."""
    from env_generator.llm_generator.multi_agent.delivery.contract_extract import (
        param_agnostic,
    )
    h = _hub()
    canon = h._canonical_path("/api/titles//episodes")
    assert param_agnostic("GET " + canon) == param_agnostic("GET /api/titles//episodes")
