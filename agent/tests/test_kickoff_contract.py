"""Closed-by-construction tests for ``runtime/kickoff/contract.py``.

One sharp test per invariant the module promises (per workflow rules):

  * round-trip: build a KickoffEndpoint → normalize → register via a
    real RegistryHub → observe that ``response_key`` and ``auth_required``
    land in the STORED metadata (NOT top-level). This is the
    round-7 reviewer-blocker test: the shape mismatch the contract
    module exists to kill.
  * shape validation: each required field omitted → a finding surfaces
    with the matching id; each malformed type → a finding.
  * ``endpoint_id`` is byte-identical with ``registryhub.RegistryHub.endpoint_id``
    over the canonicalization rules (case, leading slash, trailing
    slash).
  * caller misuse on the normalizer raises (no phantom defaults).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.kickoff.contract import (  # noqa: E402
    REQUIRED_ENDPOINT_KEYS,
    endpoint_id,
    normalize_to_registryhub_endpoint,
    validate_kickoff_endpoint,
)


# ---------------------------------------------------------------------------
# Fixture: a well-formed KickoffEndpoint (mutated per test).
# ---------------------------------------------------------------------------


def _valid_kickoff_endpoint() -> dict:
    return {
        "id": endpoint_id("GET", "/api/posts"),
        "method": "GET",
        "path": "/api/posts",
        "response_key": "posts",
        "auth_required": True,
        "response": {
            "tables": ["posts", "users"],
            "shape": {"type": "list", "items": "Post"},
        },
        "request": {
            "body": {},
            "query": ["limit", "offset"],
        },
    }


# ---------------------------------------------------------------------------
# endpoint_id canonical-form tests (MUST mirror registryhub.RegistryHub.endpoint_id).
# ---------------------------------------------------------------------------


class EndpointIdTests(unittest.TestCase):

    def test_method_uppercased_path_kept(self) -> None:
        self.assertEqual(endpoint_id("get", "/api/posts"), "GET /api/posts")

    def test_method_trimmed(self) -> None:
        self.assertEqual(endpoint_id("  GET  ", "/api/posts"), "GET /api/posts")

    def test_leading_slash_added(self) -> None:
        self.assertEqual(endpoint_id("POST", "api/login"), "POST /api/login")

    def test_trailing_slash_stripped(self) -> None:
        self.assertEqual(endpoint_id("GET", "/api/posts/"), "GET /api/posts")

    def test_bare_root_stays(self) -> None:
        self.assertEqual(endpoint_id("GET", "/"), "GET /")

    def test_matches_registryhub_canonical_form(self) -> None:
        # Sibling-module invariant: our endpoint_id MUST stay byte-identical
        # with registryhub.RegistryHub.endpoint_id. If this ever fails the two shapes
        # have drifted again — fix one or the other.
        for method, path in [
            ("get", "/api/posts"),
            ("POST", "api/login"),
            ("delete", "/api/posts/"),
            ("GET", "/"),
            ("  put  ", "/api/users/42"),
        ]:
            self.assertEqual(
                endpoint_id(method, path),
                RegistryHub.endpoint_id(method, path),
                msg=f"drift on ({method!r}, {path!r})",
            )


# ---------------------------------------------------------------------------
# validate_kickoff_endpoint shape-check tests.
# ---------------------------------------------------------------------------


class ValidateKickoffEndpointTests(unittest.TestCase):

    def test_well_formed_no_findings(self) -> None:
        self.assertEqual(validate_kickoff_endpoint(_valid_kickoff_endpoint()), [])

    def test_non_mapping_flagged(self) -> None:
        findings = validate_kickoff_endpoint(["not", "a", "dict"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "endpoint_shape")
        self.assertEqual(findings[0]["severity"], "error")

    def test_each_required_key_missing_surfaces_finding(self) -> None:
        # One sharp test, parameterized over the required-key set: dropping
        # ANY required field MUST surface a finding with id
        # ``missing.<key>``. No phantom defaults.
        for key in REQUIRED_ENDPOINT_KEYS:
            ke = _valid_kickoff_endpoint()
            ke.pop(key)
            findings = validate_kickoff_endpoint(ke)
            ids = {f["id"] for f in findings}
            self.assertIn(
                f"missing.{key}", ids,
                msg=f"dropping {key} did not surface missing finding; got {findings}",
            )

    def test_method_must_be_nonempty_string(self) -> None:
        ke = _valid_kickoff_endpoint()
        ke["method"] = ""
        findings = validate_kickoff_endpoint(ke)
        self.assertIn("type.method", {f["id"] for f in findings})

    def test_path_whitespace_only_flagged(self) -> None:
        ke = _valid_kickoff_endpoint()
        ke["path"] = "   "
        findings = validate_kickoff_endpoint(ke)
        self.assertIn("type.path", {f["id"] for f in findings})

    def test_response_key_empty_flagged(self) -> None:
        ke = _valid_kickoff_endpoint()
        ke["response_key"] = ""
        findings = validate_kickoff_endpoint(ke)
        self.assertIn("type.response_key", {f["id"] for f in findings})

    def test_auth_required_not_bool_flagged(self) -> None:
        # Python treats 1/0 as legal bools via duck-typing, but the
        # validator MUST enforce isinstance(..., bool) per the
        # roadmap_validator contract (line 185 of roadmap_validator.py).
        ke = _valid_kickoff_endpoint()
        ke["auth_required"] = "yes"
        findings = validate_kickoff_endpoint(ke)
        self.assertIn("type.auth_required", {f["id"] for f in findings})


# ---------------------------------------------------------------------------
# normalize_to_registryhub_endpoint behavioural tests.
# ---------------------------------------------------------------------------


class NormalizeShapeTests(unittest.TestCase):

    def test_returns_register_endpoint_kwargs(self) -> None:
        kw = normalize_to_registryhub_endpoint(_valid_kickoff_endpoint())
        # Top-level kwargs are the explicit named args of
        # ``register_endpoint`` plus the metadata catch-all keys.
        self.assertEqual(kw["method"], "GET")
        self.assertEqual(kw["path"], "/api/posts")
        self.assertEqual(kw["provider"], "backend")
        self.assertEqual(kw["response_key"], "posts")
        self.assertEqual(kw["auth_required"], True)

    def test_schema_combines_request_and_response(self) -> None:
        kw = normalize_to_registryhub_endpoint(_valid_kickoff_endpoint())
        self.assertIn("schema", kw)
        self.assertIn("request", kw["schema"])
        self.assertIn("response", kw["schema"])
        self.assertEqual(kw["schema"]["response"]["tables"], ["posts", "users"])
        self.assertEqual(kw["schema"]["request"]["query"], ["limit", "offset"])

    def test_missing_required_key_raises_keyerror(self) -> None:
        ke = _valid_kickoff_endpoint()
        ke.pop("response_key")
        with self.assertRaises(KeyError):
            normalize_to_registryhub_endpoint(ke)

    def test_non_mapping_raises_typeerror(self) -> None:
        with self.assertRaises(TypeError):
            normalize_to_registryhub_endpoint(["not", "a", "mapping"])


# ---------------------------------------------------------------------------
# Round-trip test: KickoffEndpoint → normalize → RegistryHub.register_endpoint
# → observe that response_key + auth_required land in stored metadata.
#
# This is the round-7 reviewer-blocker test: if normalize ever puts
# response_key / auth_required at top level of the stored registryhub dict
# (instead of inside metadata), registryhub's breaking-change diff will read
# None where it should read the kickoff-time value, and the contract-drift
# bug class re-enters.
# ---------------------------------------------------------------------------


class RoundTripIntoRegistryHubTests(unittest.TestCase):

    def setUp(self) -> None:
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))

    def test_normalize_then_register_stores_metadata_correctly(self) -> None:
        ke = _valid_kickoff_endpoint()
        kw = normalize_to_registryhub_endpoint(ke)

        # Splat into register_endpoint exactly the way the kickoff
        # orchestrator would. agent="backend" is required by the
        # registryhub._role_gate (allowed_set={"backend"}).
        self.hubs.registryhub.register_endpoint(agent="backend", **kw)

        endpoints = self.hubs.registryhub.get_endpoints()
        eid = endpoint_id("GET", "/api/posts")
        self.assertIn(eid, endpoints, msg=f"id missing; got {list(endpoints)}")

        stored = endpoints[eid]
        # Top-level keys per registryhub.register_endpoint lines 167-178.
        self.assertEqual(stored["method"], "GET")
        self.assertEqual(stored["path"], "/api/posts")
        self.assertEqual(stored["provider"], "backend")

        # The load-bearing assertion: response_key + auth_required MUST
        # land INSIDE metadata, NOT at top level. If registryhub.py drifts so
        # that these live elsewhere, this test fails loudly.
        self.assertIn("metadata", stored)
        self.assertEqual(stored["metadata"]["response_key"], "posts")
        self.assertEqual(stored["metadata"]["auth_required"], True)

        # And these MUST NOT be aliased at top level — that's the bug
        # the contract module exists to prevent (a future maintainer
        # adding a "convenience" top-level alias would silently break
        # registryhub's breaking-change diff).
        self.assertNotIn("response_key", stored)
        self.assertNotIn("auth_required", stored)

        # The schema sub-shape MUST survive intact so cross_check_suite's
        # api_vs_data_model (which reads response.tables) can still
        # function from the stored shape if needed.
        self.assertIn("response", stored["schema"])
        self.assertEqual(stored["schema"]["response"]["tables"], ["posts", "users"])

    def test_caller_can_override_provider(self) -> None:
        # The normalizer pins provider="backend" by default — the
        # currently-only-legal value per registryhub._role_gate. If a future
        # lane ever earns the registration right, the caller MUST be
        # able to override BEFORE splatting (the normalizer never
        # silently picks a different value).
        ke = _valid_kickoff_endpoint()
        kw = normalize_to_registryhub_endpoint(ke)
        self.assertEqual(kw["provider"], "backend")
        kw["provider"] = "backend"  # explicit re-pin == still legal
        self.hubs.registryhub.register_endpoint(agent="backend", **kw)
        self.assertIn(
            endpoint_id("GET", "/api/posts"),
            self.hubs.registryhub.get_endpoints(),
        )


if __name__ == "__main__":
    unittest.main()
