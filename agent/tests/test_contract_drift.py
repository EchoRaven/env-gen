"""Code↔schema drift detection for registered endpoints (Bug-5)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class TestExtractResponseKeys(unittest.TestCase):
    def test_express_res_json(self):
        from multi_agent.runtime.contract_drift import extract_response_keys
        code = """
        app.get('/api/users', (req, res) => {
            res.json({ users: rows });
        });
        """
        self.assertEqual(extract_response_keys(code), ["users"])

    def test_express_res_json_with_status(self):
        from multi_agent.runtime.contract_drift import extract_response_keys
        code = """
        return res.status(200).json({items: rows, total: count});
        """
        self.assertIn("items", extract_response_keys(code))

    def test_flask_jsonify_dict(self):
        from multi_agent.runtime.contract_drift import extract_response_keys
        code = """
        @app.route('/api/users')
        def users():
            return jsonify({'users': rows})
        """
        self.assertEqual(extract_response_keys(code), ["users"])

    def test_fastapi_jsonresponse(self):
        from multi_agent.runtime.contract_drift import extract_response_keys
        code = """
        return JSONResponse(content={"users": users, "total": total})
        """
        self.assertEqual(extract_response_keys(code), ["users"])

    def test_benign_envelope_keys_filtered(self):
        """``error`` / ``status`` shouldn't masquerade as the response_key."""
        from multi_agent.runtime.contract_drift import extract_response_keys
        code = """
        if (!valid) return res.status(400).json({ error: 'bad input' });
        return res.json({ items: rows });
        """
        keys = extract_response_keys(code)
        self.assertNotIn("error", keys)
        self.assertIn("items", keys)


class TestDetectEndpointDrift(unittest.TestCase):
    def test_no_drift_when_keys_match(self):
        from multi_agent.runtime.contract_drift import detect_endpoint_drift
        endpoint = {
            "id": "GET /api/users",
            "metadata": {"response_key": "users"},
            "schema": {},
        }
        report = detect_endpoint_drift(
            endpoint=endpoint,
            file_content="res.json({ users: rows });",
        )
        self.assertIsNone(report)

    def test_drift_when_code_uses_different_key(self):
        from multi_agent.runtime.contract_drift import detect_endpoint_drift
        endpoint = {
            "id": "GET /api/users",
            "metadata": {"response_key": "items"},
            "schema": {},
        }
        report = detect_endpoint_drift(
            endpoint=endpoint,
            file_content="res.json({ users: rows });",
        )
        self.assertIsNotNone(report)
        self.assertEqual(report["expected_key"], "items")
        self.assertIn("users", report["found_keys"])
        self.assertIn("registryhub_update_schema", report["hint"])

    def test_no_drift_when_no_declared_key(self):
        """If endpoint metadata lacks response_key, can't detect drift."""
        from multi_agent.runtime.contract_drift import detect_endpoint_drift
        endpoint = {
            "id": "GET /api/users",
            "metadata": {},
            "schema": {},
        }
        report = detect_endpoint_drift(
            endpoint=endpoint,
            file_content="res.json({ users: rows });",
        )
        self.assertIsNone(report)

    def test_no_drift_when_file_uses_no_recognised_pattern(self):
        """File that doesn't have any res.json/jsonify/JSONResponse —
        could be middleware/utility. Don't false-positive."""
        from multi_agent.runtime.contract_drift import detect_endpoint_drift
        endpoint = {
            "id": "GET /api/users",
            "metadata": {"response_key": "users"},
            "schema": {},
        }
        report = detect_endpoint_drift(
            endpoint=endpoint,
            file_content="module.exports = function middleware() {};",
        )
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
