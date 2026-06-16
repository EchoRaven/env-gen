"""GENERALITY: the persistence-probe body must be derived from the endpoint's
REGISTERED request schema, not hardcoded to instagram/social fields.

The persist gate (validation_runner) POSTs a parameterless collection endpoint then
GETs it back to confirm the write stuck. The probe body used to be hardcoded as
``{media_url, media_type, caption, ...}`` (instagram-shaped) — so on ANY non-social
create endpoint (a task app's ``{title, description}``, a docs app's ``{title,
body}``) the POST 422'd and the gate became a vacuous pass. ``_probe_body`` now
projects the body from the contract, so the probe works for every domain.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.validation_runner import _probe_body  # noqa: E402


def test_body_derived_from_request_schema_any_domain():
    # a NON-social create endpoint (project-mgmt task)
    ep = {"method": "POST", "path": "/api/tasks", "schema": {"request": {
        "title": "str", "description": "str?", "estimate": "int", "done": "bool",
        "labels": "str[]", "meta": "{...}",
    }}}
    body = _probe_body(ep)
    assert body["title"] == "persist-probe"        # text fields → string placeholder
    assert body["description"] == "persist-probe"
    assert body["estimate"] == 1                   # int → 1
    assert body["done"] is True                    # bool → True
    assert body["labels"] == []                    # array → []
    assert body["meta"] == {}                      # object → {}
    # NOT instagram-shaped: only the contract's fields are sent
    assert "media_type" not in body and "caption" not in body


def test_social_fields_only_when_the_contract_declares_them():
    ep = {"method": "POST", "path": "/api/posts", "schema": {"request": {"caption": "str", "media_url": "str"}}}
    body = _probe_body(ep)
    assert set(body) == {"caption", "media_url"}    # derived from the app's own schema


def test_generic_fallback_when_no_schema_is_registered():
    body = _probe_body({"method": "POST", "path": "/api/things"})
    # domain-agnostic generic fields, never instagram-specific
    assert "name" in body and "title" in body and "description" in body
    assert "media_type" not in body and "media_url" not in body and "caption" not in body
