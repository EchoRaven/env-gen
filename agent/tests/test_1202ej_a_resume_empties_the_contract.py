r"""#1202ej: resuming a run empties 14 of its endpoint schemas.

Measured, on a real resume with no LLM spend: netflix r45 restored from its tick-12
snapshot and resumed. Endpoints carrying a substantive schema went

    23/31  ->  9/31

POST /auth/register, POST /auth/login, GET /api/profiles, GET /api/titles and ten others
came back as `{"request": {}, "response": {}}`. Every other field on those records
survived -- provider, metadata, breaking_change -- and `_updated_by` flipped from
"backend" to "orchestrator". That is the whole story: the orchestrator re-declared the
contract on resume and the backend lane's filled-in shapes went with it.

`register_endpoint` meant to prevent exactly this:

    "schema": _merge_query_alias_730(schema or (old or {}).get("schema") or {}),

but that is a FALSY check. `{"request": {}, "response": {}}` is a non-empty dict, so it is
truthy, and the skeleton the contract re-declares with sailed straight through.

This is #1202cw one layer down: that guard stops the framework overwriting a lane-owned
FILE. Nothing stopped it overwriting a lane-owned hub RECORD.
"""
import logging
import sys
import tempfile
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.registryhub import (  # noqa: E402
    RegistryHub, _is_vacuous_schema_1202ej,
)

RICH = {"request": {"email": "string", "password": "string"},
        "response": {"access_token": "string"}}
SKELETON = {"request": {}, "response": {}}


def _hub():
    return RegistryHub(Path(tempfile.mkdtemp()))


def _schema(h, key="POST /auth/login"):
    return (h._endpoints.get(key) or {}).get("schema") or {}


def test_the_contract_skeleton_no_longer_empties_a_lanes_schema():
    """The exact sequence a resume performs."""
    h = _hub()
    h.register_endpoint("POST", "/auth/login", schema=RICH,
                        provider="backend", agent="backend", status="implemented")
    h.register_endpoint("POST", "/auth/login", schema=SKELETON,
                        provider="backend", agent="orchestrator")
    assert _schema(h)["request"] == RICH["request"]
    assert _schema(h)["response"] == RICH["response"]


def test_a_real_schema_change_still_lands():
    """The fix must not freeze the contract."""
    h = _hub()
    h.register_endpoint("POST", "/auth/login", schema=RICH, agent="backend")
    grown = {"request": {"email": "string", "password": "string", "otp": "string"},
             "response": {"access_token": "string"}}
    h.register_endpoint("POST", "/auth/login", schema=grown, agent="backend")
    assert "otp" in _schema(h)["request"]


def test_the_falsy_cases_behave_as_they_always_did():
    h = _hub()
    h.register_endpoint("POST", "/auth/login", schema=RICH, agent="backend")
    for absent in (None, {}):
        h.register_endpoint("POST", "/auth/login", schema=absent, agent="orchestrator")
        assert _schema(h)["request"] == RICH["request"]


def test_a_first_registration_with_a_skeleton_is_still_stored():
    """No old record to fall back to -- the endpoint must still exist."""
    h = _hub()
    h.register_endpoint("GET", "/api/x", schema=SKELETON, agent="orchestrator")
    assert h._endpoints.get("GET /api/x") is not None


@pytest.mark.parametrize("s,vacuous", [
    (None, True), ({}, True),
    ({"request": {}, "response": {}}, True),
    ({"request": {}, "response": {}, "query": {}}, True),
    ({"request": {"a": "b"}, "response": {}}, False),
    ({"response_key": "item"}, False),          # a scalar IS substantive
    ({"response": {"id": "int"}}, False),
    ({"filters": {}}, False),                   # unknown key: #735 must still warn
    ("junk", False),                            # non-dict: register_endpoint must refuse it
    (["a"], False),
])
def test_vacuity_is_about_content_not_presence(s, vacuous):
    assert _is_vacuous_schema_1202ej(s) is vacuous


def test_an_unknown_empty_key_is_kept_so_735_can_warn():
    """Fixing this bug must not silence a different message. `{"filters": {}}` says
    nothing the framework reads, and #735 exists to say exactly that."""
    h = _hub()
    rec = h.register_endpoint("GET", "/api/a", schema={"filters": {}}, agent="backend")
    assert "READ BY NOTHING" in (rec.get("_note") or "")


def test_a_non_dict_schema_still_reaches_the_refusal():
    """Calling `schema="junk"` absent would silently accept it."""
    h = _hub()
    with pytest.raises(Exception):
        h.register_endpoint("GET", "/api/z", schema="junk", agent="backend")


def test_a_scalar_only_schema_is_not_discarded():
    """`response_key` alone is the whole schema for some endpoints (#708b/#730)."""
    h = _hub()
    h.register_endpoint("GET", "/api/y", schema={"response_key": "items"}, agent="backend")
    assert _schema(h, "GET /api/y").get("response_key") == "items"
