"""P0 — stack-pluggable contract extraction + frontend-call extractor.

The delivery gate's contract_extract was hardcoded to Express+Postgres; once the
backend lane emits FastAPI, every FastAPI route read as a 'missing endpoint'
(docs/contract_enforcement_and_lifecycle_design.md §A2, P0). And there was no
frontend-call extractor, so 'frontend calls an endpoint it never registered'
could not be caught on real code. This adds: detect_backend_stack,
FastAPI route extraction, extract_frontend_calls, and a param-agnostic match key.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class DetectStackTests(unittest.TestCase):
    def test_detects_fastapi_from_main_py(self):
        from multi_agent.delivery.contract_extract import detect_backend_stack
        with tempfile.TemporaryDirectory() as t:
            be = Path(t) / "app" / "backend"
            _write(be, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
            self.assertEqual(detect_backend_stack(be), "fastapi")

    def test_detects_express_from_server_js(self):
        from multi_agent.delivery.contract_extract import detect_backend_stack
        with tempfile.TemporaryDirectory() as t:
            be = Path(t) / "app" / "backend"
            _write(be, "src/server.js", "const express = require('express');\n")
            self.assertEqual(detect_backend_stack(be), "express")


class BackendRouteExtractionTests(unittest.TestCase):
    def test_extracts_fastapi_decorator_routes(self):
        from multi_agent.delivery.contract_extract import extract_backend_routes
        with tempfile.TemporaryDirectory() as t:
            be = Path(t) / "app" / "backend"
            _write(be, "main.py", (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "@app.get('/health')\ndef h(): ...\n"
                "@app.get('/api/posts')\ndef lp(): ...\n"
                "@app.post('/api/posts')\ndef cp(): ...\n"
                "@app.get('/api/posts/{post_id}')\ndef gp(): ...\n"
            ))
            routes = extract_backend_routes(be)
            self.assertIn("GET /api/posts", routes)
            self.assertIn("POST /api/posts", routes)
            self.assertIn("GET /health", routes)
            self.assertIn("GET /api/posts/:post_id", routes)

    def test_express_routes_still_work(self):
        from multi_agent.delivery.contract_extract import extract_backend_routes
        with tempfile.TemporaryDirectory() as t:
            be = Path(t) / "app" / "backend"
            _write(be, "src/server.js",
                   "import posts from './routes/posts.js'\napp.use('/api/posts', posts)\n")
            _write(be, "src/routes/posts.js",
                   "router.get('/', h)\nrouter.post('/', c)\n")
            routes = extract_backend_routes(be)
            self.assertIn("GET /api/posts", routes)
            self.assertIn("POST /api/posts", routes)


class FrontendCallExtractionTests(unittest.TestCase):
    def test_extracts_request_and_fetch_calls(self):
        from multi_agent.delivery.contract_extract import extract_frontend_calls
        with tempfile.TemporaryDirectory() as t:
            fe = Path(t) / "app" / "frontend"
            _write(fe, "src/services/api.js", (
                "export async function getPosts(){ return (await request('/api/posts')).items; }\n"
                "export async function getPost(id){ return (await request(`/api/posts/${id}`)).item; }\n"
                "export async function create(b){ return request('/api/posts', { method: 'POST', body: b }); }\n"
            ))
            calls = extract_frontend_calls(fe)
            self.assertIn("GET /api/posts", calls)
            self.assertIn("POST /api/posts", calls)
            self.assertIn("GET /api/posts/:id", calls)


class ParamAgnosticMatchTests(unittest.TestCase):
    def test_param_names_and_brace_colon_forms_match(self):
        from multi_agent.delivery.contract_extract import param_agnostic
        self.assertEqual(param_agnostic("GET /api/posts/{id}"),
                         param_agnostic("GET /api/posts/:post_id"))
        self.assertEqual(param_agnostic("GET /api/posts"), "GET /api/posts")
        self.assertNotEqual(param_agnostic("GET /api/posts"),
                            param_agnostic("POST /api/posts"))


class _FakeHub:
    def __init__(self, endpoints, tables):
        self._e = endpoints; self._t = tables
    def get_endpoints(self): return self._e
    def list_tables(self): return self._t


class _FakeHubs:
    def __init__(self, endpoints, tables):
        self.registryhub = _FakeHub(endpoints, tables)
        self.schema_hub = _FakeHub(endpoints, tables)


class ContractAlignmentGateTests(unittest.TestCase):
    def _run_gate(self, td: Path, endpoints):
        from multi_agent.orchestrator import Orchestrator
        o = object.__new__(Orchestrator)
        o.hubs = _FakeHubs(endpoints, {})
        o.output_dir = td
        return o._validate_contract_alignment()

    def test_frontend_call_to_unregistered_endpoint_is_error(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            _write(td, "app/backend/main.py",
                   "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/api/posts')\ndef p(): ...\n")
            _write(td, "app/frontend/src/services/api.js", (
                "export const a=()=>request('/api/posts');\n"       # registered
                "export const b=()=>request('/api/secrets');\n"     # NOT registered
                "export const c=()=>request('/idp/auth/login',{method:'POST'});\n"  # infra-exempt
            ))
            endpoints = {"GET /api/posts": {"method": "GET", "path": "/api/posts", "status": "implemented"}}
            res = self._run_gate(td, endpoints)
            joined = " ".join(res["errors"])
            self.assertIn("/api/secrets", joined)         # unregistered business call flagged
            self.assertNotIn("/api/posts", joined)        # registered call ok
            self.assertNotIn("/idp/auth/login", joined)   # infra exempt
            self.assertEqual(res["frontend_call_unregistered"], 1)

    def test_fastapi_route_matches_registered_endpoint_no_missing_warning(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            _write(td, "app/backend/main.py",
                   "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/api/posts/{id}')\ndef p(): ...\n")
            _write(td, "app/frontend/src/services/api.js", "export const a=()=>request(`/api/posts/${x}`);\n")
            endpoints = {"GET /api/posts/:id": {"method": "GET", "path": "/api/posts/:id", "status": "implemented"}}
            res = self._run_gate(td, endpoints)
            # param-agnostic: {id} route matches :id registered endpoint -> no missing warning, no error
            self.assertFalse([w for w in res["warnings"] if "missing declared" in w])
            self.assertEqual(res["frontend_call_unregistered"], 0)


if __name__ == "__main__":
    unittest.main()
