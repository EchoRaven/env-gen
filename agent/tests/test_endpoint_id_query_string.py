"""endpoint_id must treat a QUERY STRING as part of the SAME endpoint.

A verifier chain that exercises a list filter writes a step path like
``GET /api/notes?tag=updated`` (a real request against the registered
``GET /api/notes``). The query is a filter ON that endpoint, not a distinct
endpoint — so identity must ignore it, else the chain is rejected as a
"phantom endpoint", business_chain never registers, and delivery is blocked
(smoke-notes exp6, 2026-06-29). The two endpoint_id twins must agree.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402
from multi_agent.runtime.kickoff.contract import endpoint_id as kickoff_eid  # noqa: E402

_eid = RegistryHub.endpoint_id


def test_query_string_ignored_in_identity():
    assert _eid("GET", "/api/notes?tag=updated") == _eid("GET", "/api/notes")
    assert _eid("GET", "/api/notes?tag=a&sort=desc") == _eid("GET", "/api/notes")


def test_query_string_with_path_param():
    assert _eid("GET", "/api/notes/{id}?expand=1") == _eid("GET", "/api/notes/{note_id}")


def test_no_query_unchanged():
    # paths without a query are completely unaffected (regression guard)
    assert _eid("GET", "/api/notes") == "GET /api/notes"
    assert _eid("POST", "/api/notes/") == "POST /api/notes"
    assert _eid("GET", "/api/notes/:id") == _eid("GET", "/api/notes/{id}")


def test_twins_stay_byte_identical():
    for m, p in [("GET", "/api/notes?tag=updated"), ("GET", "/api/notes"),
                 ("POST", "/api/notes/"), ("GET", "/api/notes/:id?x=1"),
                 ("GET", "/api/items/{id}?expand=author")]:
        assert _eid(m, p) == kickoff_eid(m, p), (m, p)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
