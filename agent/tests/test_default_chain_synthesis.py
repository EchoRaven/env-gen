"""Contract-projected default verification chain (FILL-IN).

When the verifier registers no usable chain, the framework projects a default
register->CRUD chain DETERMINISTICALLY FROM THE REGISTERED CONTRACT so business_chain
(and the delivery-gate RunHub run it gates) no longer dead-ends on a drifting agent.
This must be GENERIC (work for any app, not notes-shaped) and must NOT supplant a
verifier-authored chain when one exists.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.chain_executor import (  # noqa: E402
    synthesize_default_chain, load_verifier_chains, CHAINS_STORE_RELPATH)


def _ep(method, path, request=None, kind=None):
    return {"id": f"{method} {path}", "method": method, "path": path,
            "schema": {"request": request or {}},
            "metadata": {"kind": kind} if kind else {}}


# A NON-notes contract (videos) — proves genericity, not app-shaped.
_VIDEOS = [
    _ep("POST", "/auth/register", kind="auth"),
    _ep("POST", "/auth/login", kind="auth"),
    _ep("GET", "/api/videos"),
    _ep("POST", "/api/videos", request={"title": "str", "url": "str", "views": "int"}),
    _ep("GET", "/api/videos/{id}"),
    _ep("PUT", "/api/videos/{id}", request={"title": "str"}),
    _ep("DELETE", "/api/videos/{id}"),
    _ep("GET", "/api/v1/tenants", kind="infra"),     # fixed-kind → excluded
    _ep("POST", "/api/v1/tenants", kind="infra"),
]


def _paths(chain):
    return [s["path"] for s in chain["steps"]]


class DefaultChainSynthesisTests(unittest.TestCase):
    def test_projects_register_then_full_crud_for_any_resource(self):
        chains = synthesize_default_chain(_VIDEOS)
        self.assertEqual(len(chains), 1)
        paths = _paths(chains[0])
        # register first, then CRUD over /api/videos with the saved id
        self.assertEqual(paths[0], "/auth/register")
        self.assertIn("/api/videos", paths)                       # create + list
        self.assertIn("/api/videos/${api_videos_id}", paths)      # read/update/delete by saved id

    def test_create_saves_id_and_item_ops_reference_it(self):
        steps = synthesize_default_chain(_VIDEOS)[0]["steps"]
        create = next(s for s in steps if s["method"] == "POST" and s["path"] == "/api/videos")
        self.assertEqual(create["save"], {"api_videos_id": "id"})
        # the create body is projected from the request schema (generic typed placeholders)
        self.assertEqual(set(create["body"]), {"title", "url", "views"})
        self.assertEqual(create["body"]["views"], 1)              # int placeholder
        gets = [s for s in steps if s["method"] == "GET" and "${api_videos_id}" in s["path"]]
        self.assertTrue(gets)
        dele = next(s for s in steps if s["method"] == "DELETE")
        self.assertEqual(dele["path"], "/api/videos/${api_videos_id}")
        self.assertIn(204, dele["expect"])

    def test_fixed_kind_endpoints_excluded(self):
        paths = _paths(synthesize_default_chain(_VIDEOS)[0])
        self.assertFalse(any("tenants" in p for p in paths))     # infra never CRUD'd

    def test_no_business_collection_returns_empty(self):
        # only auth + a fixed-kind endpoint → nothing creatable → [] (verifier
        # feedback path still applies)
        eps = [_ep("POST", "/auth/register", kind="auth"),
               _ep("GET", "/api/v1/tenants", kind="infra")]
        self.assertEqual(synthesize_default_chain(eps), [])

    def test_body_falls_back_to_text_fields_without_schema(self):
        eps = [_ep("POST", "/auth/register", kind="auth"),
               _ep("POST", "/api/items"), _ep("GET", "/api/items/{id}")]
        create = next(s for s in synthesize_default_chain(eps)[0]["steps"]
                      if s["path"] == "/api/items" and s["method"] == "POST")
        self.assertIn("title", create["body"])  # generic text fields when no schema


class LoadVerifierChainsFillInTests(unittest.TestCase):
    def _write(self, root, rel, obj):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    def test_fills_in_default_when_no_verifier_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "shared/hubs/registryhub_endpoints.json",
                        {e["id"]: e for e in _VIDEOS})
            chains = load_verifier_chains(tmp)
            self.assertEqual(len(chains), 1)
            self.assertEqual(chains[0]["name"], "framework_default_crud")

    def test_verifier_chain_is_authoritative_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "shared/hubs/registryhub_endpoints.json",
                        {e["id"]: e for e in _VIDEOS})
            self._write(tmp, str(CHAINS_STORE_RELPATH), {
                "my_chain": {"name": "my_chain", "steps": [
                    {"method": "POST", "path": "/auth/register",
                     "body": {"email": "a@b.c", "password": "pw"}}]}})
            chains = load_verifier_chains(tmp)
            names = [c["name"] for c in chains]
            self.assertIn("my_chain", names)
            self.assertNotIn("framework_default_crud", names)  # NOT supplemented

    def test_empty_when_no_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_verifier_chains(tmp), [])


if __name__ == "__main__":
    unittest.main()
