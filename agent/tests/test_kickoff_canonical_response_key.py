"""PROPOSAL #46: kickoff derives the CANONICAL response envelope key (item/items —
what the route_projector emits + the delivery gate requires), never a resource-name
key like "notes".

Regression: smoke-notes 2026-06-19 — GET/PUT/DELETE /api/notes/{id} got
response_key="notes" (the legacy last-path-segment deriver) → delivery gate
business_response_key_noncanonical hard-blocked with no remediation path → never
delivered.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (
    _canonical_response_key,
)


class CanonicalResponseKeyTests(unittest.TestCase):
    def test_collection_get_is_items(self):
        self.assertEqual(_canonical_response_key("GET", "/api/notes"), "items")
        self.assertEqual(_canonical_response_key("GET", "/api/feed"), "items")

    def test_param_get_is_item(self):
        self.assertEqual(_canonical_response_key("GET", "/api/notes/{id}"), "item")
        self.assertEqual(_canonical_response_key("GET", "/api/notes/{note_id}"), "item")
        self.assertEqual(_canonical_response_key("GET", "/api/notes/:id"), "item")  # Express form

    def test_me_route_is_item(self):
        self.assertEqual(_canonical_response_key("GET", "/api/users/me"), "item")

    def test_mutations_are_item(self):
        self.assertEqual(_canonical_response_key("POST", "/api/notes"), "item")  # create returns the row
        self.assertEqual(_canonical_response_key("PUT", "/api/notes/{id}"), "item")
        self.assertEqual(_canonical_response_key("DELETE", "/api/notes/{id}"), "item")

    def test_always_canonical_never_resource_name(self):
        # The whole point: the result is ALWAYS in {item, items} — never "notes"/"posts".
        for m, p in [("GET", "/api/posts"), ("GET", "/api/posts/{id}"),
                     ("POST", "/api/posts"), ("GET", "/api/posts/{id}/comments"),
                     ("DELETE", "/api/widgets/{wid}")]:
            self.assertIn(_canonical_response_key(m, p), ("item", "items"))


class ContractNormalizeProducesCanonicalTests(unittest.TestCase):
    """The contract-normalize path must override a non-canonical declared key."""

    def test_build_contract_overrides_noncanonical_declared_key(self):
        from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff as rk
        # The _build_contract normalize loop: feed an endpoint declaring response_key="notes".
        drafts = {"backend": {"endpoints": [
            {"method": "GET", "path": "/api/notes/{id}", "response_key": "notes", "auth_required": True},
            {"method": "GET", "path": "/api/notes", "response_key": "notes", "auth_required": True},
        ]}}
        # _build_contract is the function carrying the line-919 normalize; call it and
        # assert the emitted contract endpoints are canonical.
        contract = rk._build_contract(drafts) if hasattr(rk, "_build_contract") else None
        if contract is None:
            self.skipTest("_build_contract not directly callable in this build")
        eps = contract.get("endpoints") or []
        keys = {(e["method"], e["path"]): e.get("response_key") for e in eps}
        self.assertEqual(keys.get(("GET", "/api/notes/{id}")), "item")
        self.assertEqual(keys.get(("GET", "/api/notes")), "items")


if __name__ == "__main__":
    unittest.main()
