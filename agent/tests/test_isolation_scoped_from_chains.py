"""Verifier-driven read isolation (the user's "must work for ALL envs" choice): a table
the verifier's chains probe for CROSS-USER isolation (a by-id read it asserts must be
DENIED 403/404 to a non-owner) is marked owner_scoped_reads BY CONSTRUCTION, so the
projected read handler owner-scopes it — closing the cross-user data leak the backend
agent unreliably declares (outlook run-9/10: scoped messages, forgot events). ENV-AGNOSTIC:
a PUBLIC resource (social feed) gets no isolation probe, so it is never scoped.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.heal_pipeline import _isolation_scoped_tables_from_chains  # noqa: E402


class _Reg:
    def __init__(self, chains):
        self._c = chains
    def get_verification_chains(self):
        return self._c


def test_isolation_probe_marks_only_probed_private_tables():
    chains = {
        "events_flow": {"steps": [
            {"method": "POST", "path": "/api/events", "expect": [201]},          # create (success)
            {"method": "GET", "path": "/api/events/${id}", "expect": [403, 404]},  # CROSS-USER isolation probe
        ]},
        "public_feed": {"steps": [
            {"method": "GET", "path": "/api/posts/${id}", "expect": [200]},       # PUBLIC read — no isolation
        ]},
        "messages_flow": {"steps": [
            {"method": "GET", "path": "/api/messages", "expect": [200]},          # list, no isolation probe
        ]},
    }
    out = _isolation_scoped_tables_from_chains(_Reg(chains), {"events", "posts", "messages"})
    assert "events" in out          # isolation probe → owner-scoped
    assert "posts" not in out       # public read, no probe → stays open (social feed safe)
    assert "messages" not in out    # no isolation probe → not scoped here


def test_probe_on_unknown_table_is_ignored():
    chains = {"c": {"steps": [{"method": "GET", "path": "/api/widgets/${id}", "expect": [404]}]}}
    out = _isolation_scoped_tables_from_chains(_Reg(chains), {"events"})  # 'widgets' not a real table
    assert out == set()


def test_empty_and_malformed_are_safe():
    assert _isolation_scoped_tables_from_chains(_Reg({}), {"events"}) == set()
    assert _isolation_scoped_tables_from_chains(_Reg({"c": {"steps": None}}), {"events"}) == set()
    assert _isolation_scoped_tables_from_chains(_Reg(None), {"events"}) == set()

    class _Boom:
        def get_verification_chains(self):
            raise RuntimeError("boom")
    assert _isolation_scoped_tables_from_chains(_Boom(), {"events"}) == set()   # never raises


def test_write_denial_does_NOT_scope_reads_77():
    # #77: a cross-user DELETE/PUT/PATCH denial proves only WRITE authz ("you may not delete
    # someone ELSE's row") — a near-universal property that ALSO holds for PUBLIC resources (a
    # forum comment). Deriving READ-scoping from it wrongly scoped a world-readable feed's reads
    # to the caller (public threads silently vanish, ships GREEN). Only a GET denial scopes reads.
    for m in ("DELETE", "PUT", "PATCH"):
        chains = {"c": {"steps": [{"method": m, "path": "/api/events/${id}", "expect": [403]}]}}
        assert _isolation_scoped_tables_from_chains(_Reg(chains), {"events"}) == set(), m
    get_chain = {"c": {"steps": [{"method": "GET", "path": "/api/events/${id}", "expect": [403]}]}}
    assert _isolation_scoped_tables_from_chains(_Reg(get_chain), {"events"}) == {"events"}


def test_register_isolation_chain_marks_table_owner_scoped(tmp_path):
    """End-to-end: registering a chain with a cross-user-isolation probe sets the probed
    table's owner_scoped_reads — so the backend regen scopes its reads BY CONSTRUCTION."""
    from multi_agent.runtime.hub_registry import HubRegistry
    rh = HubRegistry(tmp_path).registryhub
    rh.register_table("events", schema={"columns": [{"name": "id"}, {"name": "user_id"}]},
                      agent="backend", status="implemented")
    rh.register_endpoint("POST", "/auth/register", agent="backend", status="implemented")
    rh.register_endpoint("POST", "/api/events", agent="backend", status="implemented")
    rh.register_endpoint("GET", "/api/events/{eventId}", agent="backend", status="implemented")
    res = rh.register_verification_chain("iso", steps=[
        {"method": "POST", "path": "/api/events", "expect": [201]},
        {"method": "GET", "path": "/api/events/${eventId}", "expect": [403, 404]},  # isolation probe
    ], agent="verifier")
    assert "error" not in res, res
    assert (rh.get_table("events").get("metadata") or {}).get("owner_scoped_reads") is True


def test_register_public_read_chain_does_not_scope(tmp_path):
    """A chain that only reads a resource (expect 200, no isolation probe) must NOT scope it
    — a public feed stays open."""
    from multi_agent.runtime.hub_registry import HubRegistry
    rh = HubRegistry(tmp_path).registryhub
    rh.register_table("posts", schema={"columns": [{"name": "id"}, {"name": "user_id"}]},
                      agent="backend", status="implemented")
    rh.register_endpoint("POST", "/auth/register", agent="backend", status="implemented")
    rh.register_endpoint("GET", "/api/posts/{postId}", agent="backend", status="implemented")
    res = rh.register_verification_chain("pub", steps=[
        {"method": "GET", "path": "/api/posts/${postId}", "expect": [200]},  # public read
    ], agent="verifier")
    assert "error" not in res, res
    assert not (rh.get_table("posts").get("metadata") or {}).get("owner_scoped_reads")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
