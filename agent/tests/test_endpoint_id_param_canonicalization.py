"""PROPOSAL #29 P1 — endpoint IDENTITY canonicalizes Express ``:param`` ↔ FastAPI ``{param}``.

Run #28: the backend's finish was permanently blocked because the SAME route was
registered in two param idioms — /api/notes/:id (router/frontend) AND /api/notes/{id}
(FastAPI/backend) — and endpoint_id did NOT normalize them, so they were DISTINCT
endpoints; the backend implemented {id} while the :id phantom stayed 'defined'.

Fix: endpoint_id canonicalizes ``/:param`` → ``/{param}`` (slash-anchored, so a literal
mid-segment ``:`` like a custom-method path is untouched — the reviewer's
don't-break-other-envs bar). There are TWO byte-identical copies that MUST stay in sync
(RegistryHub.endpoint_id + kickoff/contract.endpoint_id) — the reviewer's mandatory
parity condition.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402
from multi_agent.runtime.kickoff.contract import endpoint_id as contract_endpoint_id  # noqa: E402

_rh_endpoint_id = RegistryHub.endpoint_id


class Canonicalization(unittest.TestCase):
    def test_colon_and_brace_are_one_id(self):
        self.assertEqual(_rh_endpoint_id("GET", "/api/notes/:id"),
                         _rh_endpoint_id("GET", "/api/notes/{id}"))

    def test_with_existing_case_slash_normalization(self):
        self.assertEqual(_rh_endpoint_id("get", "/api/notes/:id/"),
                         _rh_endpoint_id("GET", "/api/notes/{id}"))

    def test_multi_param(self):
        self.assertEqual(_rh_endpoint_id("PUT", "/api/tenants/:tid/notes/:id"),
                         _rh_endpoint_id("PUT", "/api/tenants/{tid}/notes/{id}"))

    def test_brace_param_collapses_to_agnostic(self):
        # PROPOSAL #39 #1: the id is param-NAME-agnostic — {id} collapses to {}.
        self.assertEqual(_rh_endpoint_id("DELETE", "/api/notes/{id}"),
                         "DELETE /api/notes/{}")

    def test_param_NAME_agnostic_one_id(self):
        # #39 #1 (the run #36 fix): the SAME route under DIFFERENT param names is ONE id,
        # so a backend implementing /notes/{note_id} updates the declared /notes/{id}
        # instead of forking a phantom `defined` endpoint that blocks validation forever.
        ids = {_rh_endpoint_id("GET", p) for p in
               ("/api/notes/{id}", "/api/notes/{note_id}", "/api/notes/:id", "/api/notes/:noteId")}
        self.assertEqual(ids, {"GET /api/notes/{}"})
        # distinct ROUTES still distinct (only the param NAME is collapsed, not structure)
        self.assertNotEqual(_rh_endpoint_id("GET", "/api/notes/{id}"),
                            _rh_endpoint_id("GET", "/api/users/{id}"))
        self.assertEqual(_rh_endpoint_id("GET", "/api/notes/{id}/c/{cid}"),
                         "GET /api/notes/{}/c/{}")

    def test_slash_anchored_does_not_touch_mid_segment_colon(self):
        # don't-break-other-envs: a literal ':' NOT after a slash (e.g. a Google/AIP
        # custom-method path /users:batchGet) must be left ALONE.
        self.assertEqual(_rh_endpoint_id("POST", "/v1/users:batchGet"),
                         "POST /v1/users:batchGet")

    def test_plain_paths_unchanged(self):
        self.assertEqual(_rh_endpoint_id("GET", "/api/notes"), "GET /api/notes")
        self.assertEqual(_rh_endpoint_id("GET", "/"), "GET /")


class TwinParity(unittest.TestCase):
    """The reviewer's mandatory condition: the storage-time (registryhub) and
    kickoff-time (contract) endpoint_id MUST produce byte-identical ids, or an id
    minted at kickoff won't match the one register_endpoint mints → the dup returns."""

    CASES = [
        ("GET", "/api/notes/:id"), ("GET", "/api/notes/{id}"),
        ("post", "/api/notes/"), ("DELETE", "/api/tenants/:tid/notes/:id"),
        ("POST", "/v1/users:batchGet"), ("GET", "/"), ("GET", "api/x"),
        ("PUT", "/a/:b/c/:d/"),
    ]

    def test_both_copies_agree(self):
        for m, p in self.CASES:
            self.assertEqual(_rh_endpoint_id(m, p), contract_endpoint_id(m, p),
                             f"registryhub vs contract endpoint_id diverge on {m} {p}")


class RegisterDeDuplicates(unittest.TestCase):
    def test_colon_then_brace_yields_one_endpoint(self):
        # register the same logical route in both idioms → ONE endpoint, not two
        try:
            rh = RegistryHub()
        except Exception:
            self.skipTest("RegistryHub requires construction args in this build")
        rh.register_endpoint("GET", "/api/notes/:id", provider="backend", agent="backend")
        rh.register_endpoint("GET", "/api/notes/{id}", provider="backend", agent="backend",
                             status="implemented")
        eps = rh.get_endpoints() or {}
        notes_id = [k for k in eps if "notes" in k and ("{id}" in k or ":id" in k)]
        self.assertEqual(len(notes_id), 1, f"expected ONE notes/:id|{{id}} endpoint, got {notes_id}")
        self.assertNotIn(":id", notes_id[0], "stored id must be the canonical {param} form")


if __name__ == "__main__":
    unittest.main()
